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


def test_merge_bookmark_stores_collapses_same_name_categories(tmp_path):
    """Same-name categories from local + remote should fold into one.

    The keeper is the earliest ``created_at``; bookmarks pointing at the
    dropped duplicate are remapped onto the keeper.
    """
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"

    local_cats = [
        {"id": "default", "name": "預設", "color": "#6c8cff",
         "sort_order": 0, "created_at": "2026-01-01T00:00:00+00:00"},
        {"id": "local-cat", "name": "Working", "color": "#aaa",
         "sort_order": 1, "created_at": "2026-02-01T00:00:00+00:00"},
    ]
    remote_cats = [
        {"id": "default", "name": "預設", "color": "#6c8cff",
         "sort_order": 0, "created_at": "2026-01-01T00:00:00+00:00"},
        {"id": "remote-cat", "name": "Working", "color": "#bbb",
         "sort_order": 1, "created_at": "2026-03-01T00:00:00+00:00"},
    ]
    _write(local, _bm_payload([{
        "id": "bm1", "name": "A", "lat": 1.0, "lng": 1.0,
        "category_id": "local-cat", "created_at": "2026-02-02T00:00:00+00:00",
    }], local_cats))
    _write(remote, _bm_payload([{
        "id": "bm2", "name": "B", "lat": 2.0, "lng": 2.0,
        "category_id": "remote-cat", "created_at": "2026-03-02T00:00:00+00:00",
    }], remote_cats))

    merge_bookmark_stores(local, remote)

    merged = json.loads(remote.read_text())
    cat_names = sorted(c["name"] for c in merged["categories"])
    assert cat_names == ["Working", "預設"]
    cat_ids = {c["id"] for c in merged["categories"]}
    assert "local-cat" in cat_ids  # earlier created_at wins
    assert "remote-cat" not in cat_ids
    bms_by_id = {b["id"]: b for b in merged["bookmarks"]}
    assert bms_by_id["bm1"]["category_id"] == "local-cat"
    assert bms_by_id["bm2"]["category_id"] == "local-cat"  # remapped


def test_merge_route_stores_collapses_same_name_categories(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    local_cats = [
        {"id": "default", "name": "預設", "color": "#6c8cff",
         "sort_order": 0, "created_at": "2026-01-01T00:00:00+00:00"},
        {"id": "local-cat", "name": "Trips", "color": "#aaa",
         "sort_order": 1, "created_at": "2026-02-01T00:00:00+00:00"},
    ]
    remote_cats = [
        {"id": "default", "name": "預設", "color": "#6c8cff",
         "sort_order": 0, "created_at": "2026-01-01T00:00:00+00:00"},
        {"id": "remote-cat", "name": "Trips", "color": "#bbb",
         "sort_order": 1, "created_at": "2026-03-01T00:00:00+00:00"},
    ]
    _write(local, _route_payload([{
        "id": "r1", "name": "Loop", "category_id": "local-cat",
        "profile": "walking",
        "waypoints": [{"lat": 1.0, "lng": 1.0}, {"lat": 2.0, "lng": 2.0}],
        "created_at": "2026-02-02T00:00:00+00:00",
    }], local_cats))
    _write(remote, _route_payload([{
        "id": "r2", "name": "Hill", "category_id": "remote-cat",
        "profile": "walking",
        "waypoints": [{"lat": 3.0, "lng": 3.0}, {"lat": 4.0, "lng": 4.0}],
        "created_at": "2026-03-02T00:00:00+00:00",
    }], remote_cats))

    merge_route_stores(local, remote)

    merged = json.loads(remote.read_text())
    cat_ids = {c["id"] for c in merged["categories"]}
    assert "local-cat" in cat_ids
    assert "remote-cat" not in cat_ids
    routes_by_id = {r["id"]: r for r in merged["routes"]}
    assert routes_by_id["r1"]["category_id"] == "local-cat"
    assert routes_by_id["r2"]["category_id"] == "local-cat"


def test_merge_bookmark_stores_skips_on_parse_failure(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    _write(local, _bm_payload([]))
    remote.write_text("{not json}")

    # Should not raise; remote file left as-is.
    merge_bookmark_stores(local, remote)
    assert remote.read_text() == "{not json}"
