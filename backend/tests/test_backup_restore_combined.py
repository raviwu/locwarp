"""The combined rotating-backup snapshot must be restorable through the real
merge_backup path — the recovery path is the whole point of the feature.

Regression guard for the review finding: feeding the combined file
{_backup_meta, bookmarks:{...}, routes:{...}} to the per-store restore raised a
ValidationError (nested dict vs list[Bookmark]) and restored nothing.
"""
import json
from datetime import datetime

from bootstrap.factories import make_bookmark_manager, make_route_manager
from domain import backup
from merge_backup import (
    is_combined_snapshot,
    merge_backup_into_live,
    restore_combined_snapshot,
)
from models.schemas import Coordinate, SavedRoute


def _build_combined(tmp_path, recent=None):
    """Produce a real combined snapshot file exactly like the lifespan loop does."""
    bm = make_bookmark_manager()
    cat = bm.create_category(name="Cat")
    bm.create_bookmark(name="B", lat=1.0, lng=2.0, category_id=cat.id)
    rm = make_route_manager()
    rm.create_route(SavedRoute(name="R", waypoints=[Coordinate(lat=1.0, lng=2.0)]))

    snap = backup.build_snapshot(
        bm.snapshot_export(), rm.snapshot_export(), recent or [],
        datetime(2026, 6, 22, 12, 0, 0), "in-process",
    )
    f = tmp_path / "locwarp-latest-backup.json"
    f.write_text(json.dumps(snap), encoding="utf-8")
    return f


def test_detects_combined_vs_per_store():
    assert is_combined_snapshot(
        {"_backup_meta": {}, "bookmarks": {"bookmarks": []}, "routes": {"routes": []}}
    )
    # Bare per-store files (top-level list) must NOT be treated as combined.
    assert not is_combined_snapshot({"bookmarks": [], "categories": []})
    assert not is_combined_snapshot({"routes": [], "categories": []})


def test_combined_snapshot_restores_both_stores(tmp_path):
    f = _build_combined(tmp_path)
    raw = json.loads(f.read_text())
    bm_live = tmp_path / "restored-bookmarks.json"
    rt_live = tmp_path / "restored-routes.json"

    summary = restore_combined_snapshot(raw, bm_live, rt_live, force_restore=True)

    assert summary["bookmarks"]["items_restored"] >= 1
    assert summary["routes"]["items_restored"] >= 1
    assert bm_live.exists() and rt_live.exists()
    assert any(b["name"] == "B" for b in json.loads(bm_live.read_text())["bookmarks"])
    assert any(r["name"] == "R" for r in json.loads(rt_live.read_text())["routes"])


def test_combined_snapshot_restores_recent_via_union(tmp_path):
    """The recent sub-store restores through merge_recent's union (not a
    replace): a row already present in the live file survives alongside a row
    that only the backup carries. Relies on the autouse conftest guard, which
    redirects config.RECENT_PLACES_FILE to this test's own tmp_path."""
    live_recent = [{"lat": 5.0, "lng": 6.0, "kind": "teleport", "name": "Live", "ts": 1}]
    (tmp_path / "recent_places.json").write_text(json.dumps(live_recent), encoding="utf-8")

    backup_recent = [{"lat": 25.0, "lng": 121.0, "kind": "route_stop", "name": "",
                       "ts": 2, "visit_count": 3}]
    f = _build_combined(tmp_path, recent=backup_recent)
    raw = json.loads(f.read_text())
    bm_live = tmp_path / "restored-bookmarks.json"
    rt_live = tmp_path / "restored-routes.json"

    summary = restore_combined_snapshot(raw, bm_live, rt_live, force_restore=True)

    assert summary["recent"] == {"merged": 2, "incoming": 1}
    restored = json.loads((tmp_path / "recent_places.json").read_text())
    assert {"teleport", "route_stop"} == {e["kind"] for e in restored}


def test_combined_snapshot_pre_recent_key_does_not_crash_restore(tmp_path):
    """A combined snapshot written before recent joined the payload has no
    'recent' key at all — the restore must simply skip it, not crash."""
    f = _build_combined(tmp_path)
    raw = json.loads(f.read_text())
    del raw["recent"]
    bm_live = tmp_path / "restored-bookmarks.json"
    rt_live = tmp_path / "restored-routes.json"

    summary = restore_combined_snapshot(raw, bm_live, rt_live, force_restore=True)

    assert "recent" not in summary


def test_per_store_file_still_restores(tmp_path):
    """Regression: a bare per-store BookmarkStore file still restores unchanged."""
    bm_file = tmp_path / "locwarp-bookmark.json"
    bm_file.write_text(
        json.dumps(
            {
                "categories": [],
                "bookmarks": [
                    {
                        "id": "x",
                        "name": "X",
                        "lat": 1.0,
                        "lng": 2.0,
                        "updated_at": "2026-06-22T00:00:00+00:00",
                    }
                ],
                "tombstones": [],
            }
        ),
        encoding="utf-8",
    )
    live = tmp_path / "live-bookmarks.json"
    summary = merge_backup_into_live(bm_file, live, force_restore=True)
    assert summary["items_restored"] == 1
    assert live.exists()


def test_main_cli_restores_combined_file(tmp_path, monkeypatch, capsys):
    """The documented `make restore-backup` command (merge_backup.main on a
    combined file) restores both stores and exits 0 — end-to-end through the
    real CLI entrypoint, with live-path resolution pointed at tmp."""
    import merge_backup

    f = _build_combined(tmp_path)
    bm_live = tmp_path / "cli-bookmarks.json"
    rt_live = tmp_path / "cli-routes.json"
    monkeypatch.setattr(merge_backup, "get_bookmarks_path", lambda: bm_live)
    monkeypatch.setattr(merge_backup, "get_routes_path", lambda: rt_live)

    rc = merge_backup.main([str(f), "--force-restore"])

    assert rc == 0
    assert bm_live.exists() and rt_live.exists()
    assert "Combined restore complete." in capsys.readouterr().out
