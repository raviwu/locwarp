"""Tests for the atomic two-file (bookmarks + routes) migration."""

import json
from pathlib import Path

import pytest

from services.cloud_sync import migrate_pair


def _write_bookmarks(p: Path, ids: list[str]) -> None:
    p.write_text(json.dumps({
        "categories": [{
            "id": "default", "name": "預設", "color": "#6c8cff",
            "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
        }],
        "bookmarks": [
            {"id": i, "name": i, "lat": 1.0, "lng": 1.0,
             "category_id": "default",
             "created_at": "2026-05-12T00:00:00+00:00"}
            for i in ids
        ],
    }))


def _write_routes(p: Path, ids: list[str]) -> None:
    p.write_text(json.dumps({
        "categories": [{
            "id": "default", "name": "預設", "color": "#6c8cff",
            "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
        }],
        "routes": [
            {"id": i, "name": i, "category_id": "default",
             "waypoints": [{"lat": 1.0, "lng": 1.0}],
             "created_at": "2026-05-12T00:00:00+00:00"}
            for i in ids
        ],
    }))


def test_migrate_pair_src_only(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    _write_bookmarks(src / "bookmarks.json", ["a"])
    _write_routes(src / "routes.json", ["r1"])

    migrate_pair(src, dst)

    assert (dst / "bookmarks.json").exists()
    assert (dst / "routes.json").exists()
    assert not (src / "bookmarks.json").exists()
    assert not (src / "routes.json").exists()


def test_migrate_pair_dst_only_is_noop(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    _write_bookmarks(dst / "bookmarks.json", ["a"])
    _write_routes(dst / "routes.json", ["r1"])

    migrate_pair(src, dst)

    # No src files to migrate; dst untouched.
    dst_bm = json.loads((dst / "bookmarks.json").read_text())
    assert [b["id"] for b in dst_bm["bookmarks"]] == ["a"]


def test_migrate_pair_both_present_union_merges(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    _write_bookmarks(src / "bookmarks.json", ["a"])
    _write_bookmarks(dst / "bookmarks.json", ["b"])
    _write_routes(src / "routes.json", ["r1"])
    _write_routes(dst / "routes.json", ["r2"])

    migrate_pair(src, dst)

    dst_bm = json.loads((dst / "bookmarks.json").read_text())
    dst_rt = json.loads((dst / "routes.json").read_text())
    assert {b["id"] for b in dst_bm["bookmarks"]} == {"a", "b"}
    assert {r["id"] for r in dst_rt["routes"]} == {"r1", "r2"}
    assert not (src / "bookmarks.json").exists()
    assert not (src / "routes.json").exists()


def test_migrate_pair_partial_src_only_bookmarks(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    _write_bookmarks(src / "bookmarks.json", ["a"])
    # routes only on dst — should remain
    _write_routes(dst / "routes.json", ["r2"])

    migrate_pair(src, dst)

    assert (dst / "bookmarks.json").exists()
    assert (dst / "routes.json").exists()
    dst_rt = json.loads((dst / "routes.json").read_text())
    assert [r["id"] for r in dst_rt["routes"]] == ["r2"]


def test_migrate_pair_rollback_on_failure(tmp_path, monkeypatch):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    _write_bookmarks(src / "bookmarks.json", ["a"])
    _write_routes(src / "routes.json", ["r1"])

    # Inject a failure when migrating the routes file (after bookmarks
    # have already been written to dst). The rollback must:
    #   - restore src/bookmarks.json
    #   - remove dst/bookmarks.json (which we created this call)
    import services.cloud_sync as cs
    original = cs._move_or_merge_file

    def boom(src_file, dst_file, kind):
        if kind == "routes":
            raise OSError("simulated failure")
        return original(src_file, dst_file, kind)

    monkeypatch.setattr("services.cloud_sync._move_or_merge_file", boom)

    with pytest.raises(OSError):
        migrate_pair(src, dst)

    # Source must be restored.
    assert (src / "bookmarks.json").exists()
    assert (src / "routes.json").exists()
    # Destination must not contain partial state.
    assert not (dst / "bookmarks.json").exists()
    assert not (dst / "routes.json").exists()
