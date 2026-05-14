"""RouteManager stamps updated_at on every mutation and records a Tombstone
on every delete — the per-item metadata merge_stores needs to resolve
concurrent cloud-sync edits without clobbering or resurrecting routes.
"""

import pytest

from models.schemas import Coordinate, SavedRoute
from services.route_store import RouteManager


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("services.route_store._CONFIG_DEFAULT_ROUTES_FILE", object())
    return RouteManager()


def _route(name="R", category_id="default"):
    return SavedRoute(
        name=name,
        waypoints=[Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)],
        profile="walking",
        category_id=category_id,
    )


def test_create_route_stamps_updated_at(mgr):
    r = mgr.create_route(_route())
    assert r.updated_at != ""


def test_delete_route_emits_tombstone(mgr):
    r = mgr.create_route(_route())
    mgr.delete_route(r.id)
    assert any(t.id == r.id and t.kind == "route" for t in mgr.store.tombstones)
    assert all(x.id != r.id for x in mgr.store.routes)


def test_create_category_stamps_updated_at(mgr):
    cat = mgr.create_category("Trip")
    assert cat.updated_at != ""


def test_update_category_advances_updated_at(mgr):
    cat = mgr.create_category("Trip")
    first = cat.updated_at
    updated = mgr.update_category(cat.id, name="Vacation")
    assert updated.updated_at >= first and updated.name == "Vacation"


def test_delete_category_emits_tombstone(mgr):
    cat = mgr.create_category("Trip")
    mgr.delete_category(cat.id)
    assert any(t.id == cat.id and t.kind == "category" for t in mgr.store.tombstones)


def test_delete_category_stamps_reparented_routes(mgr):
    cat = mgr.create_category("Trip")
    r = mgr.create_route(_route(category_id=cat.id))
    before = r.updated_at
    mgr.delete_category(cat.id)  # routes in it move to "default"
    reparented = next(x for x in mgr.store.routes if x.id == r.id)
    assert reparented.category_id == "default" and reparented.updated_at >= before
