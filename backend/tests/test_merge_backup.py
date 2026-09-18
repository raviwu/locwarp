"""merge_backup.py — safe restore path that folds a Desktop backup JSON into
the live store via the commutative merge_stores.

Contract: the merge is additive (union by id, resolved per merge unit -- the
newer per-field stamp wins -- and the live copy wins an exact tie on every
unit), the live file is copied aside before any write, and a live tombstone
still suppresses a backup item unless --force-restore is given.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from merge_backup import detect_store_cls, merge_backup_into_live
from models.schemas import BookmarkStore, RouteStore


def _write(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data))


def _recent(hours_ago):
    """ISO timestamp ``hours_ago`` hours before now — always inside the 30-day
    tombstone retention window so GC never drops it (deterministic vs wall clock)."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _bm(id, name, updated_at):
    return {
        "id": id, "name": name, "lat": 0.0, "lng": 0.0,
        "category_id": "default", "updated_at": updated_at,
    }


# ── detect_store_cls ──────────────────────────────────────────────────────


def test_detect_bookmark_store():
    assert detect_store_cls({"bookmarks": [], "categories": []}) is BookmarkStore


def test_detect_route_store():
    assert detect_store_cls({"routes": [], "categories": []}) is RouteStore


def test_detect_unknown_raises():
    with pytest.raises(ValueError):
        detect_store_cls({"something_else": []})


# ── merge_backup_into_live ────────────────────────────────────────────────


def test_merge_adds_missing_bookmarks(tmp_path):
    live = tmp_path / "bookmarks.json"
    backup = tmp_path / "backup.json"
    _write(live, {"categories": [], "tombstones": [],
                  "bookmarks": [_bm("a", "A", "2026-05-14T01:00:00+00:00")]})
    _write(backup, {"categories": [], "tombstones": [], "bookmarks": [
        _bm("a", "A", "2026-05-14T01:00:00+00:00"),
        _bm("b", "B", "2026-05-14T01:00:00+00:00"),
    ]})
    summary = merge_backup_into_live(backup, live)
    result = json.loads(live.read_text())
    assert {x["id"] for x in result["bookmarks"]} == {"a", "b"}
    assert summary["items_restored"] == 1


def test_merge_does_not_clobber_newer_live(tmp_path):
    live = tmp_path / "bookmarks.json"
    backup = tmp_path / "backup.json"
    _write(live, {"categories": [], "tombstones": [],
                  "bookmarks": [_bm("a", "NEW", "2026-05-14T09:00:00+00:00")]})
    _write(backup, {"categories": [], "tombstones": [],
                    "bookmarks": [_bm("a", "OLD", "2026-05-14T01:00:00+00:00")]})
    merge_backup_into_live(backup, live)
    [bm] = json.loads(live.read_text())["bookmarks"]
    assert bm["name"] == "NEW"


def test_tombstone_suppresses_backup_item_without_force(tmp_path):
    live = tmp_path / "bookmarks.json"
    backup = tmp_path / "backup.json"
    _write(live, {"categories": [], "bookmarks": [], "tombstones": [
        {"id": "x", "kind": "bookmark", "deleted_at": _recent(1)}]})
    _write(backup, {"categories": [], "tombstones": [],
                    "bookmarks": [_bm("x", "X", _recent(5))]})
    summary = merge_backup_into_live(backup, live)
    assert json.loads(live.read_text())["bookmarks"] == []
    assert summary["tombstone_suppressed"] == ["x"]


def test_force_restore_brings_back_tombstoned_item(tmp_path):
    live = tmp_path / "bookmarks.json"
    backup = tmp_path / "backup.json"
    _write(live, {"categories": [], "bookmarks": [], "tombstones": [
        {"id": "x", "kind": "bookmark", "deleted_at": "2026-05-14T05:00:00+00:00"}]})
    _write(backup, {"categories": [], "tombstones": [],
                    "bookmarks": [_bm("x", "X", "2026-05-14T01:00:00+00:00")]})
    summary = merge_backup_into_live(backup, live, force_restore=True)
    assert {x["id"] for x in json.loads(live.read_text())["bookmarks"]} == {"x"}
    assert summary["tombstones_dropped"] == ["x"]


def test_dry_run_does_not_write(tmp_path):
    live = tmp_path / "bookmarks.json"
    backup = tmp_path / "backup.json"
    original = {"categories": [], "tombstones": [],
                "bookmarks": [_bm("a", "A", "2026-05-14T01:00:00+00:00")]}
    _write(live, original)
    _write(backup, {"categories": [], "tombstones": [],
                    "bookmarks": [_bm("b", "B", "2026-05-14T01:00:00+00:00")]})
    summary = merge_backup_into_live(backup, live, dry_run=True)
    assert json.loads(live.read_text()) == original   # untouched
    assert summary["items_restored"] == 1             # but reports what would change
    assert summary["dry_run"] is True


def test_creates_timestamped_backup_of_live(tmp_path):
    live = tmp_path / "bookmarks.json"
    backup = tmp_path / "backup.json"
    _write(live, {"categories": [], "tombstones": [],
                  "bookmarks": [_bm("a", "A", "2026-05-14T01:00:00+00:00")]})
    _write(backup, {"categories": [], "tombstones": [],
                    "bookmarks": [_bm("b", "B", "2026-05-14T01:00:00+00:00")]})
    summary = merge_backup_into_live(backup, live)
    assert summary["backup_copy"] is not None
    assert Path(summary["backup_copy"]).exists()
    assert len(list(tmp_path.glob("bookmarks.json.bak-*"))) == 1


def test_routes_backup_merges(tmp_path):
    live = tmp_path / "routes.json"
    backup = tmp_path / "backup.json"
    wp = [{"lat": 1.0, "lng": 1.0}, {"lat": 2.0, "lng": 2.0}]
    _write(live, {"categories": [], "tombstones": [], "routes": [
        {"id": "r1", "name": "Loop", "waypoints": wp, "profile": "walking",
         "category_id": "default", "updated_at": "2026-05-14T01:00:00+00:00"}]})
    _write(backup, {"categories": [], "tombstones": [], "routes": [
        {"id": "r2", "name": "Hill", "waypoints": wp, "profile": "walking",
         "category_id": "default", "updated_at": "2026-05-14T01:00:00+00:00"}]})
    summary = merge_backup_into_live(backup, live)
    assert summary["store_type"] == "routes"
    assert {r["id"] for r in json.loads(live.read_text())["routes"]} == {"r1", "r2"}


def test_missing_backup_file_raises(tmp_path):
    with pytest.raises(ValueError):
        merge_backup_into_live(tmp_path / "nope.json", tmp_path / "bookmarks.json")


def test_merge_into_absent_live_is_clean_restore(tmp_path):
    # Live store gone entirely — backup becomes the new store, no .bak made.
    live = tmp_path / "bookmarks.json"
    backup = tmp_path / "backup.json"
    _write(backup, {"categories": [], "tombstones": [],
                    "bookmarks": [_bm("a", "A", "2026-05-14T01:00:00+00:00")]})
    summary = merge_backup_into_live(backup, live)
    assert {x["id"] for x in json.loads(live.read_text())["bookmarks"]} == {"a"}
    assert summary["backup_copy"] is None


# ── change G: the restore is per merge unit ──────────────────────────────


def test_a_backup_restores_a_lost_field_without_dragging_back_the_others(tmp_path):
    """The reason a restore is per unit and not per record.

    The live store lost the address (say a bad sync wrote a blank one) but has
    since been renamed. Restoring must bring the address back and leave the
    newer name alone -- whole-record LWW could only do one or the other.
    """
    live_p, backup_p = tmp_path / "bookmarks.json", tmp_path / "backup.json"
    old, new = _recent(48), _recent(1)
    _write(live_p, {"categories": [], "tombstones": [], "bookmarks": [
        {**_bm("a", "renamed later", new), "address": "",
         "field_updated_at": {"name": new, "address": new}},
    ]})
    _write(backup_p, {"categories": [], "tombstones": [], "bookmarks": [
        {**_bm("a", "old name", old), "address": "10 Real Street",
         "field_updated_at": {"name": old, "address": old}},
    ]})

    merge_backup_into_live(backup_p, live_p)

    bm = json.loads(live_p.read_text())["bookmarks"][0]
    assert bm["name"] == "renamed later"
    assert bm["address"] == "", "the live blank is NEWER, so the merge keeps it"

    # Same backup, but the blanking happened before the rename: now the
    # address genuinely is the older value on the live side and comes back.
    _write(live_p, {"categories": [], "tombstones": [], "bookmarks": [
        {**_bm("a", "renamed later", new), "address": "",
         "field_updated_at": {"name": new, "address": _recent(72)}},
    ]})
    merge_backup_into_live(backup_p, live_p)

    bm = json.loads(live_p.read_text())["bookmarks"][0]
    assert bm["name"] == "renamed later"
    assert bm["address"] == "10 Real Street"


def test_the_live_store_wins_when_every_unit_is_an_exact_tie(tmp_path):
    """The one case the merge cannot decide, so this path decides it.

    merge_stores is commutative and breaks an exact tie by sorting the values,
    which is symmetric but arbitrary. "A backup only fills gaps" is this
    script's own promise, and since change G argument order no longer carries
    it -- hence the explicit re-application of the live record.

    The two names are chosen so the content sort prefers the BACKUP. Pick them
    the other way round and the test passes with the policy deleted.
    """
    live_p, backup_p = tmp_path / "bookmarks.json", tmp_path / "backup.json"
    same = _recent(5)
    _write(live_p, {"categories": [], "tombstones": [],
                    "bookmarks": [_bm("a", "aaa live copy", same)]})
    _write(backup_p, {"categories": [], "tombstones": [],
                      "bookmarks": [_bm("a", "zzz backup copy", same)]})

    merge_backup_into_live(backup_p, live_p)

    assert json.loads(live_p.read_text())["bookmarks"][0]["name"] == "aaa live copy"


def test_a_tied_category_also_keeps_the_live_copy(tmp_path):
    live_p, backup_p = tmp_path / "bookmarks.json", tmp_path / "backup.json"
    same = _recent(5)
    cat = {"id": "c1", "color": "#111111", "updated_at": same}
    _write(live_p, {"tombstones": [], "bookmarks": [],
                    "categories": [{**cat, "name": "aaa live cat"}]})
    _write(backup_p, {"tombstones": [], "bookmarks": [],
                      "categories": [{**cat, "name": "zzz backup cat"}]})

    merge_backup_into_live(backup_p, live_p)

    assert json.loads(live_p.read_text())["categories"][0]["name"] == "aaa live cat"


# ── a backup that carries deletion history can DELETE live items ──────────
# Since 2026-09-18 snapshots carry tombstones. That is correct CRDT behaviour
# but it must never be silent, and --force-restore must actually protect the
# live store from it.


def test_backup_tombstone_deletes_a_live_item_and_reports_it(tmp_path):
    live = tmp_path / "bookmarks.json"
    backup = tmp_path / "backup.json"
    _write(live, {"categories": [], "tombstones": [],
                  "bookmarks": [_bm("x", "X", _recent(5))]})
    _write(backup, {"categories": [], "bookmarks": [_bm("y", "Y", _recent(3))],
                    "tombstones": [{"id": "x", "kind": "bookmark",
                                    "deleted_at": _recent(1)}]})

    summary = merge_backup_into_live(backup, live)

    assert {b["id"] for b in json.loads(live.read_text())["bookmarks"]} == {"y"}
    assert summary["live_items_deleted"] == ["x"], (
        "a restore that removes live data must report it"
    )


def test_force_restore_keeps_a_live_item_the_backup_tombstoned(tmp_path):
    """The keep-set must cover ids the LIVE store holds alive. Scoping the
    backup-side tombstone drop to backup_ids alone would drop nothing here,
    because the dangerous tombstones are exactly the ones for ids the backup
    does NOT carry alive."""
    live = tmp_path / "bookmarks.json"
    backup = tmp_path / "backup.json"
    _write(live, {"categories": [], "tombstones": [],
                  "bookmarks": [_bm("x", "X", _recent(5))]})
    _write(backup, {"categories": [], "bookmarks": [_bm("y", "Y", _recent(3))],
                    "tombstones": [{"id": "x", "kind": "bookmark",
                                    "deleted_at": _recent(1)}]})

    summary = merge_backup_into_live(backup, live, force_restore=True)

    assert {b["id"] for b in json.loads(live.read_text())["bookmarks"]} == {"x", "y"}
    assert summary["live_items_deleted"] == []
    assert "x" in summary["backup_tombstones_dropped"]


def test_force_restore_preserves_a_backup_tombstone_neither_side_holds_alive(tmp_path):
    """The other half of the contract: --force-restore must not blanket-erase
    deletion history. A tombstone for an id nobody holds alive is real history
    and has to survive, or every force restore resurrects old deletions."""
    live = tmp_path / "bookmarks.json"
    backup = tmp_path / "backup.json"
    _write(live, {"categories": [], "tombstones": [],
                  "bookmarks": [_bm("x", "X", _recent(5))]})
    _write(backup, {"categories": [], "bookmarks": [],
                    "tombstones": [{"id": "z", "kind": "bookmark",
                                    "deleted_at": _recent(1)}]})

    summary = merge_backup_into_live(backup, live, force_restore=True)

    assert "z" not in summary["backup_tombstones_dropped"]
    written = json.loads(live.read_text())
    assert "z" in {t["id"] for t in written["tombstones"]}
