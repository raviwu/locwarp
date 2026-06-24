"""User import_json must stamp updated_at=now on incoming items so a
locally-deleted id (real-timestamp tombstone) is RESURRECTED by a re-import,
not silently killed by merge_stores inside _save(). Mirrors the catalog path
(import_catalog already does this via force_seed_items); import_json did not.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.schemas import Bookmark, Coordinate, SavedRoute


@pytest.fixture
def bm_mgr(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", object())
    from bootstrap.factories import make_bookmark_manager
    return make_bookmark_manager()


@pytest.fixture
def rt_mgr(tmp_path, monkeypatch):
    monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("services.route_store._CONFIG_DEFAULT_ROUTES_FILE", object())
    from bootstrap.factories import make_route_manager
    return make_route_manager()


def test_bookmark_import_json_resurrects_deleted_id(bm_mgr):
    # Create a real bookmark, capture its id, then delete it -> real-ts tombstone.
    created = bm_mgr.create_bookmark(name="Place", lat=1.0, lng=2.0)
    bm_id = created.id
    bm_mgr.delete_bookmark(bm_id)
    assert any(t.id == bm_id for t in bm_mgr.store.tombstones)
    assert not any(b.id == bm_id for b in bm_mgr.store.bookmarks)

    # Re-import the SAME id with an empty updated_at (the pitfall). Without the
    # fix, merge_stores in _save() lets the tombstone win and the item dies.
    payload = json.dumps({
        "categories": [],
        "bookmarks": [
            {"id": bm_id, "name": "Place (reimported)", "lat": 1.0, "lng": 2.0,
             "category_id": "default", "created_at": "", "last_used_at": "",
             "updated_at": ""},
        ],
    })
    result = bm_mgr.import_json(payload)
    assert result == {"imported": 1, "skipped": 0}

    # Alive on disk — the load-bearing assertion (merge ran inside _save).
    on_disk = json.loads(Path(bm_mgr._bookmarks_path()).read_text())
    assert bm_id in {b["id"] for b in on_disk["bookmarks"]}, (
        "import_json must stamp updated_at so the item beats the tombstone on disk"
    )
    assert any(b.id == bm_id for b in bm_mgr.store.bookmarks)


def test_route_import_json_resurrects_deleted_id(rt_mgr):
    created = rt_mgr.create_route(SavedRoute(
        name="R",
        waypoints=[Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)],
        profile="walking",
        category_id="default",
    ))
    rt_id = created.id
    rt_mgr.delete_route(rt_id)
    assert any(t.id == rt_id for t in rt_mgr.store.tombstones)
    assert not any(r.id == rt_id for r in rt_mgr.store.routes)

    # Re-import the SAME id with empty updated_at.
    payload = json.dumps({
        "categories": [],
        "routes": [
            {"id": rt_id, "name": "R (reimported)", "profile": "walking",
             "category_id": "default", "created_at": "",
             "waypoints": [{"lat": 1.0, "lng": 1.0}, {"lat": 2.0, "lng": 2.0}],
             "updated_at": ""},
        ],
    })
    imported = rt_mgr.import_json(payload)
    assert imported == 1

    on_disk = json.loads(Path(rt_mgr._routes_path()).read_text())
    assert rt_id in {r["id"] for r in on_disk["routes"]}, (
        "route import_json must stamp updated_at so the item beats the tombstone on disk"
    )
    assert any(r.id == rt_id for r in rt_mgr.store.routes)
