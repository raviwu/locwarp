"""merge_backup.py — safe restore path that folds a Desktop backup JSON into
the live store via the commutative merge_stores.

Contract: the merge is additive (union by id, newer updated_at wins, live
wins ties), the live file is copied aside before any write, and a live
tombstone still suppresses a backup item unless --force-restore is given.
"""

import json
from pathlib import Path

import pytest

from merge_backup import detect_store_cls, merge_backup_into_live
from models.schemas import BookmarkStore, RouteStore


def _write(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data))


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
        {"id": "x", "kind": "bookmark", "deleted_at": "2026-05-14T05:00:00+00:00"}]})
    _write(backup, {"categories": [], "tombstones": [],
                    "bookmarks": [_bm("x", "X", "2026-05-14T01:00:00+00:00")]})
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
