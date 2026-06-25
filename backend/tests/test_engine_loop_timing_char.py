"""Characterization: start_loop(timestamps=...) routes a timed GPX route into
the dedicated timed-replay branch, which calls the REAL _move_along_route ONCE
over the raw user waypoints with offsets=timestamps (1:1 with the waypoints).
Non-timed routes fall through to the existing leg-by-leg path with offsets=None.

Offline: jitter OFF, a FakeRouteService replaces engine.route_service so no
httpx OSRM call is made on EITHER path, and the inter-tick wait_for timeout
branch fires instantly. _move_along_route is WRAPPED (not stubbed) to capture
the offsets it receives while still running for real."""
from __future__ import annotations

import asyncio

import pytest

from models.schemas import Coordinate, MovementMode
from tests._engine_harness import FakeClock, SteppedSleep, make_engine


pytestmark = pytest.mark.asyncio


class FakeRouteService:
    """Canned densified routes -- no network. get_multi_route closes the loop;
    get_route returns the two endpoints as a 2-point polyline (mirrors
    tests/test_route_loop_cov.py)."""

    async def get_multi_route(self, wp_tuples, *, profile, force_straight, engine):
        return {"coords": [list(t) for t in wp_tuples], "distance": 1234.5}

    async def get_route(self, a_lat, a_lng, b_lat, b_lng, *, profile,
                        force_straight, engine):
        return {"coords": [[a_lat, a_lng], [b_lat, b_lng]], "distance": 100.0}


def _wrap_capture(eng, captured):
    """Wrap (don't replace) the real _move_along_route so the method under test
    still runs end-to-end while we record the offsets it was handed."""
    real = eng._move_along_route

    async def wrapped(coords, speed_profile, offsets=None):
        captured.append({"coords": list(coords), "offsets": offsets})
        return await real(coords, speed_profile, offsets=offsets)

    eng._move_along_route = wrapped  # type: ignore[assignment]


async def _drive(monkeypatch, eng, wps, *, timestamps, lap_count=1):
    # Inter-tick pacing uses asyncio.wait_for(stop_event.wait(), timeout); fire
    # the timeout branch instantly so the position stream is timing-independent.
    async def _instant_timeout(aw, timeout):
        aw.close()
        raise asyncio.TimeoutError
    monkeypatch.setattr(asyncio, "wait_for", _instant_timeout)
    eng.route_service = FakeRouteService()
    await eng.start_loop(
        wps, MovementMode.WALKING, lap_count=lap_count, timestamps=timestamps,
    )


async def test_timed_route_uses_dedicated_branch_with_offsets(monkeypatch):
    eng, _loc, _emitted = make_engine()
    captured: list[dict] = []
    _wrap_capture(eng, captured)
    wps = [
        Coordinate(lat=25.0, lng=121.0),
        Coordinate(lat=25.0, lng=121.001),
        Coordinate(lat=25.0, lng=121.002),
    ]
    offsets = [0.0, 4.0, 5.0]
    await _drive(monkeypatch, eng, wps, timestamps=offsets)
    # start_loop stored the offsets on the engine.
    # (Cleared by the timed branch after consuming, so assert via the capture.)
    assert len(captured) == 1                      # exactly ONE call (no leg-by-leg)
    call = captured[0]
    assert call["offsets"] == [0.0, 4.0, 5.0]      # offsets reached _move_along_route
    assert call["coords"] == wps                   # over the RAW waypoints (1:1)
    assert len(call["offsets"]) == len(call["coords"])  # Task 9 guard holds
    # Pending offsets cleared after the timed branch consumed them.
    assert eng._pending_route_offsets is None


async def test_untimed_route_falls_through_to_leg_by_leg_with_none(monkeypatch):
    eng, _loc, _emitted = make_engine()
    captured: list[dict] = []
    _wrap_capture(eng, captured)
    wps = [
        Coordinate(lat=25.0, lng=121.0),
        Coordinate(lat=25.0, lng=121.001),
    ]
    await _drive(monkeypatch, eng, wps, timestamps=None)
    # No timed branch: the existing leg-by-leg path runs (>=1 leg call), each
    # with offsets=None (constant-speed replay, byte-for-byte unchanged).
    assert eng._pending_route_offsets is None
    assert captured                                 # at least one leg call
    assert all(c["offsets"] is None for c in captured)
