import asyncio
from pathlib import Path

import pytest

import api.route as route_api
from domain.route_distance import straight_line_distance_m
from models.schemas import Coordinate, RouteCategory, RouteStore, SavedRoute
from services.route_store import RouteManager


class _RM:
    def __init__(self):
        self.routes = []

    def create_route(self, route):
        route.id = route.id or "rid"
        self.routes.append(route)
        return route

    def list_routes(self):
        return self.routes


class _InMemoryRouteRepo:
    """In-memory RouteRepository fake — load returns the seeded store,
    save is identity (no disk, no merge). Lets the test exercise the REAL
    RouteManager.replace_route, so it genuinely goes RED before the
    Finding-1 distance-field-copy fix and GREEN after."""

    def __init__(self, store: RouteStore):
        self._store = store

    def load(self):
        return self._store

    def load_or_empty(self):
        return self._store

    def save(self, store):
        self._store = store
        return store

    def path(self):
        return Path("/tmp/__locwarp_test_routes__.json")


def _real_route_manager_with_existing() -> RouteManager:
    """A real RouteManager seeded with one 'ok'-status route carrying
    stale old-path distances. replace_saved on this exercises the real
    route_store.replace_route field-copy semantics under test."""
    old_wp = [Coordinate(lat=10.0, lng=10.0), Coordinate(lat=11.0, lng=11.0)]
    existing = SavedRoute(
        id="existing-id",
        name="Old Name",
        waypoints=old_wp,
        profile="walking",
        straight_distance_m=999.0,
        road_distance_m=1500.0,
        road_distance_status="ok",
        dist_fingerprint="old-fp",
    )
    store = RouteStore(categories=[RouteCategory(id="default", name="Default")], routes=[existing])
    return RouteManager(_InMemoryRouteRepo(store))


@pytest.mark.asyncio
async def test_stamp_sets_straight_fingerprint_pending():
    route = SavedRoute(name="R", waypoints=[Coordinate(lat=25.0, lng=121.0),
                                            Coordinate(lat=26.0, lng=122.0)],
                       profile="walking")
    route_api._stamp_distance_fields(route)
    assert route.straight_distance_m is not None and route.straight_distance_m > 0
    assert route.dist_fingerprint != ""
    assert route.road_distance_m is None
    assert route.road_distance_status == "pending"


@pytest.mark.asyncio
async def test_save_route_stamps_and_spawns(monkeypatch):
    spawned = []
    monkeypatch.setattr(route_api, "_spawn", lambda coro: spawned.append(coro) or coro.close())
    rm = _RM()
    route = SavedRoute(name="R", waypoints=[Coordinate(lat=25.0, lng=121.0),
                                            Coordinate(lat=26.0, lng=122.0)],
                       profile="walking")
    saved = await route_api.save_route(route, rm=rm, route_service=object(), publisher=object())
    assert saved.road_distance_status == "pending"
    assert saved.straight_distance_m is not None
    assert len(spawned) == 1  # a road compute was scheduled


@pytest.mark.asyncio
async def test_bulk_import_spawns_for_pending_routes(monkeypatch):
    spawned = []
    monkeypatch.setattr(route_api, "_spawn", lambda coro: spawned.append(coro) or coro.close())

    class _ImportRM(_RM):
        def import_json(self, data):
            # Simulate the store landing two pending imported routes.
            self.routes = [
                SavedRoute(id="a", name="A",
                           waypoints=[Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)],
                           road_distance_status="pending"),
                SavedRoute(id="b", name="B",
                           waypoints=[Coordinate(lat=3.0, lng=3.0), Coordinate(lat=4.0, lng=4.0)],
                           road_distance_status="ok", road_distance_m=1.0),
            ]
            return 2

    rm = _ImportRM()
    body = route_api._RouteImportBody(routes=[], categories=[])
    res = await route_api.import_all_saved_routes(body, rm=rm, route_service=object(), publisher=object())
    assert res == {"imported": 2}
    assert len(spawned) == 1  # only the 'pending' route 'a' is scheduled, not the 'ok' one


@pytest.mark.asyncio
async def test_replace_saved_stamps_new_path_and_spawns(monkeypatch):
    """PUT /saved/{id}: the response must carry the NEW-path straight distance,
    road_distance_status=='pending', road_distance_m==None, and spawn a road compute.

    Drives the REAL RouteManager.replace_route (via an in-memory repo), so it
    fails against the unfixed route_store.replace_route — which did NOT copy the
    distance fields from incoming, leaving the stored route's stale old-path
    straight_distance_m=999.0 / road_distance_status='ok' in place — and passes
    after the Finding-1 fix."""
    spawned = []
    monkeypatch.setattr(route_api, "_spawn", lambda coro: spawned.append(coro) or coro.close())

    rm = _real_route_manager_with_existing()
    new_wps = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=26.0, lng=122.0)]
    new_route = SavedRoute(name="New Name", waypoints=new_wps, profile="walking")

    updated = await route_api.replace_saved(
        "existing-id", new_route, rm=rm, route_service=object(), publisher=object()
    )

    expected_straight = straight_line_distance_m(new_wps)
    assert updated.straight_distance_m == pytest.approx(expected_straight, rel=1e-6)
    assert updated.road_distance_status == "pending"
    assert updated.road_distance_m is None
    assert len(spawned) == 1


@pytest.mark.asyncio
async def test_import_gpx_stamps_and_spawns(monkeypatch):
    """POST /gpx/import: stamps straight+pending and spawns a road compute."""
    spawned = []
    monkeypatch.setattr(route_api, "_spawn", lambda coro: spawned.append(coro) or coro.close())

    gpx_coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=26.0, lng=122.0)]

    class _GpxService:
        def parse_gpx_timed(self, text):
            return gpx_coords, []

    class _UploadFile:
        filename = "track.gpx"
        async def read(self):
            return b"<gpx/>"

    rm = _RM()
    saved = await route_api.import_gpx(
        file=_UploadFile(),
        rm=rm,
        gpx_service=_GpxService(),
        route_service=object(),
        publisher=object(),
    )

    assert saved["status"] == "imported"
    assert len(rm.routes) == 1
    r = rm.routes[0]
    assert r.straight_distance_m is not None and r.straight_distance_m > 0
    assert r.road_distance_status == "pending"
    assert r.road_distance_m is None
    assert len(spawned) == 1
