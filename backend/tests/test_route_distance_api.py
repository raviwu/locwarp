import asyncio
import pytest

import api.route as route_api
from models.schemas import Coordinate, SavedRoute


class _RM:
    def __init__(self):
        self.routes = []

    def create_route(self, route):
        route.id = route.id or "rid"
        self.routes.append(route)
        return route

    def list_routes(self):
        return self.routes


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
