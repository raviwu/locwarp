"""Unit tests for the generic store merge helper."""

import json
from pathlib import Path

import pytest

from models.schemas import (
    Bookmark, BookmarkCategory, BookmarkStore,
    SavedRoute, RouteCategory, RouteStore,
)
from services.sync_merge import merge_bookmark_stores, merge_route_stores


def _write(p: Path, payload: dict) -> None:
    p.write_text(json.dumps(payload))


def _bm_payload(bookmarks, categories=None) -> dict:
    cats = categories or [{
        "id": "default", "name": "預設", "color": "#6c8cff",
        "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
    }]
    return {"categories": cats, "bookmarks": bookmarks}


def _route_payload(routes, categories=None) -> dict:
    cats = categories or [{
        "id": "default", "name": "預設", "color": "#6c8cff",
        "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
    }]
    return {"categories": cats, "routes": routes}


def test_merge_bookmark_stores_union(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    _write(local, _bm_payload([{
        "id": "a", "name": "A", "lat": 1.0, "lng": 1.0,
        "category_id": "default", "created_at": "2026-05-12T00:00:00+00:00",
    }]))
    _write(remote, _bm_payload([{
        "id": "b", "name": "B", "lat": 2.0, "lng": 2.0,
        "category_id": "default", "created_at": "2026-05-12T00:00:00+00:00",
    }]))

    merge_bookmark_stores(local, remote)

    merged = json.loads(remote.read_text())
    ids = {b["id"] for b in merged["bookmarks"]}
    assert ids == {"a", "b"}


def test_merge_bookmark_stores_local_wins_on_conflict(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    _write(local, _bm_payload([{
        "id": "a", "name": "LOCAL", "lat": 1.0, "lng": 1.0,
        "category_id": "default", "created_at": "2026-05-12T00:00:00+00:00",
    }]))
    _write(remote, _bm_payload([{
        "id": "a", "name": "REMOTE", "lat": 9.0, "lng": 9.0,
        "category_id": "default", "created_at": "2026-05-12T00:00:00+00:00",
    }]))

    merge_bookmark_stores(local, remote)

    merged = json.loads(remote.read_text())
    [bm] = merged["bookmarks"]
    assert bm["name"] == "LOCAL"
    assert bm["lat"] == 1.0


def test_merge_route_stores_union(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    _write(local, _route_payload([{
        "id": "r1", "name": "Loop", "category_id": "default",
        "profile": "walking", "waypoints": [{"lat": 1.0, "lng": 1.0}, {"lat": 2.0, "lng": 2.0}],
        "created_at": "2026-05-12T00:00:00+00:00",
    }]))
    _write(remote, _route_payload([{
        "id": "r2", "name": "Hill", "category_id": "default",
        "profile": "walking", "waypoints": [{"lat": 3.0, "lng": 3.0}, {"lat": 4.0, "lng": 4.0}],
        "created_at": "2026-05-12T00:00:00+00:00",
    }]))

    merge_route_stores(local, remote)

    merged = json.loads(remote.read_text())
    ids = {r["id"] for r in merged["routes"]}
    assert ids == {"r1", "r2"}


def test_merge_route_stores_local_wins_on_conflict(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    base = {
        "id": "r1", "category_id": "default", "profile": "walking",
        "waypoints": [{"lat": 1.0, "lng": 1.0}], "created_at": "2026-05-12T00:00:00+00:00",
    }
    _write(local, _route_payload([dict(base, name="LOCAL")]))
    _write(remote, _route_payload([dict(base, name="REMOTE")]))

    merge_route_stores(local, remote)

    merged = json.loads(remote.read_text())
    [route] = merged["routes"]
    assert route["name"] == "LOCAL"


def test_merge_bookmark_stores_skips_on_parse_failure(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    _write(local, _bm_payload([]))
    remote.write_text("{not json}")

    # Should not raise; remote file left as-is.
    merge_bookmark_stores(local, remote)
    assert remote.read_text() == "{not json}"
