import asyncio
import pytest

from models.schemas import Coordinate, SavedRoute
from services.route_distance_service import compute_road_distance


class _RM:
    """Minimal route_manager stub: holds one route, records _save() calls."""
    def __init__(self, route):
        self._route = route
        self.saves = 0

    def _find_route(self, rid):
        return self._route if self._route and self._route.id == rid else None

    def _save(self):
        self.saves += 1


class _RS:
    """route_service stub returning a queued sequence of get_multi_route results.
    A result is a dict; an Exception instance is raised instead."""
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    async def get_multi_route(self, coords, profile):
        self.calls += 1
        r = self._results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class _Pub:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _route():
    return SavedRoute(id="r1", name="R", waypoints=[Coordinate(lat=25.0, lng=121.0),
                                                    Coordinate(lat=26.0, lng=122.0)],
                      profile="walking", road_distance_status="pending")


async def _noop_sleep(_):
    return None


@pytest.mark.asyncio
async def test_success_writes_ok_and_broadcasts():
    rt = _route()
    rm, rs, pub = _RM(rt), _RS([{"distance": 12345.0}]), _Pub()
    await compute_road_distance("r1", route_manager=rm, route_service=rs,
                                publisher=pub, sleep=_noop_sleep)
    assert rt.road_distance_status == "ok"
    assert rt.road_distance_m == 12345.0
    assert rt.updated_at != ""
    assert rm.saves == 1
    assert pub.events == [("routes_changed", {"reason": "distance"})]


@pytest.mark.asyncio
async def test_all_attempts_fail_writes_unavailable_not_pending():
    rt = _route()
    # 1 initial + len(backoff) retries, all fallback -> unavailable
    rm, rs, pub = _RM(rt), _RS([{"fallback": True}] * 5), _Pub()
    await compute_road_distance("r1", route_manager=rm, route_service=rs,
                                publisher=pub, sleep=_noop_sleep)
    assert rt.road_distance_status == "unavailable"
    assert rt.road_distance_m is None
    assert rm.saves == 1
    assert pub.events == [("routes_changed", {"reason": "distance"})]


@pytest.mark.asyncio
async def test_retry_then_success():
    rt = _route()
    rm, rs, pub = _RM(rt), _RS([{"fallback": True}, {"distance": 999.0}]), _Pub()
    await compute_road_distance("r1", route_manager=rm, route_service=rs,
                                publisher=pub, sleep=_noop_sleep)
    assert rt.road_distance_status == "ok" and rt.road_distance_m == 999.0
    assert rs.calls == 2


@pytest.mark.asyncio
async def test_exception_attempt_counts_as_failure():
    rt = _route()
    rm, rs, pub = _RM(rt), _RS([ValueError("bad json"), {"distance": 5.0}]), _Pub()
    await compute_road_distance("r1", route_manager=rm, route_service=rs,
                                publisher=pub, sleep=_noop_sleep)
    assert rt.road_distance_status == "ok" and rt.road_distance_m == 5.0


@pytest.mark.asyncio
async def test_path_changed_under_us_discards_result():
    rt = _route()
    rm, rs, pub = _RM(rt), _RS([{"distance": 12345.0}]), _Pub()

    # Mutate the route's path AFTER the fingerprint is captured but before the
    # write, by swapping get_multi_route to also edit the route.
    orig = rs.get_multi_route
    async def _editing(coords, profile):
        rt.waypoints = [Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)]
        return await orig(coords, profile)
    rs.get_multi_route = _editing

    await compute_road_distance("r1", route_manager=rm, route_service=rs,
                                publisher=pub, sleep=_noop_sleep)
    assert rt.road_distance_status == "pending"  # untouched
    assert rm.saves == 0 and pub.events == []
