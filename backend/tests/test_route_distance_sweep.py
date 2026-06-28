import asyncio
import pytest

import main as main_mod
from models.schemas import Coordinate, SavedRoute


class _Store:
    def __init__(self, routes):
        self.routes = routes


class _RM:
    def __init__(self, routes):
        self.store = _Store(routes)
        self.saves = 0

    def _find_route(self, rid):
        return next((r for r in self.store.routes if r.id == rid), None)

    def _save(self):
        self.saves += 1


class _Pub:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


class _RS:
    async def get_multi_route(self, coords, profile):
        return {"distance": 4242.0}


class _Container:
    def __init__(self, rs, pub):
        self.route_service = rs
        self.event_publisher = pub


@pytest.mark.asyncio
async def test_sweep_backfills_stale_and_skips_fresh(monkeypatch):
    fresh = SavedRoute(id="ok", name="OK",
                       waypoints=[Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)],
                       profile="walking", road_distance_status="ok", road_distance_m=1.0)
    # make the fresh route's fingerprint match so it is skipped
    from domain.route_distance import route_distance_fingerprint
    fresh.dist_fingerprint = route_distance_fingerprint(fresh.waypoints, fresh.profile)

    stale = SavedRoute(id="legacy", name="Legacy",
                       waypoints=[Coordinate(lat=3.0, lng=3.0), Coordinate(lat=4.0, lng=4.0)],
                       profile="walking")  # status defaults to 'pending', no fingerprint

    rm, pub = _RM([fresh, stale]), _Pub()
    # _run_route_distance_sweep does `from bootstrap.runtime import get_container`
    # INSIDE the function, so patch it at its source module, not on `main`.
    monkeypatch.setattr("bootstrap.runtime.get_container", lambda: _Container(_RS(), pub))

    await main_mod._run_route_distance_sweep(rm)

    assert stale.straight_distance_m is not None  # straight backfilled
    assert stale.road_distance_status == "ok" and stale.road_distance_m == 4242.0
    assert fresh.road_distance_m == 1.0  # fresh untouched value
    # at least the straight-backfill broadcast + the per-route distance broadcast
    assert ("routes_changed", {"reason": "distance_backfill"}) in pub.events
    assert ("routes_changed", {"reason": "distance"}) in pub.events
