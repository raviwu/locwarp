"""RouteManager.import_json must be idempotent: re-importing the same bundle
(same route ids) must NOT duplicate every route. The bookmark importer skips
existing ids; routes used to always mint a fresh uuid + "(匯入)" suffix, so a
double-import doubled the store.
"""
from __future__ import annotations

import json

import pytest

from models.schemas import Coordinate, SavedRoute


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("services.route_store._CONFIG_DEFAULT_ROUTES_FILE", object())
    from bootstrap.factories import make_route_manager
    return make_route_manager()


def _bundle() -> str:
    return json.dumps({
        "categories": [],
        "routes": [
            {"id": "route-a", "name": "Alpha", "profile": "walking",
             "category_id": "default", "created_at": "2026-01-01T00:00:00+00:00",
             "updated_at": "2026-01-01T00:00:00+00:00",
             "waypoints": [{"lat": 1.0, "lng": 1.0}, {"lat": 2.0, "lng": 2.0}]},
        ],
    })


def test_first_import_adds_one_route(mgr):
    imported = mgr.import_json(_bundle())
    assert imported == 1
    assert sum(1 for r in mgr.store.routes if r.id == "route-a") == 1


def test_double_import_does_not_duplicate(mgr):
    assert mgr.import_json(_bundle()) == 1
    # Re-import the SAME bundle: the live id 'route-a' must be skipped, not
    # re-minted with a fresh uuid + "(匯入)" suffix.
    second = mgr.import_json(_bundle())
    assert second == 0, "re-importing the same live id must import nothing"
    assert sum(1 for r in mgr.store.routes if r.name == "Alpha") == 1
    assert not any("(匯入)" in r.name for r in mgr.store.routes)
    assert len([r for r in mgr.store.routes]) == 1
