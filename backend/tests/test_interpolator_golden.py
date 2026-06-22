"""Bit-exact golden vectors for RouteInterpolator + a deterministic
_move_along_route integration char (Phase 3, Task 6). Guards the verbatim
services->domain relocation in Task 7: the math must round-trip identically.

Float literals are CAPTURED from the current implementation (run-once, freeze),
asserted with exact `==`. They are NOT hand-derived.
"""
import asyncio
import random

import pytest

from models.schemas import Coordinate
from services.interpolator import RouteInterpolator as R
from tests._engine_harness import FakeClock, SteppedSleep, make_engine


def test_haversine_golden():
    assert R.haversine(25.0339, 121.5645, 25.0478, 121.5170) == 5028.724286241932


def test_bearing_golden():
    assert R.bearing(25.0, 121.0, 25.0, 121.001) == 89.99978869089777


def test_move_point_golden():
    assert R.move_point(25.0, 121.0, 90.0, 111.0) == (24.99999999594495, 121.00110144367822)


def test_interpolate_golden_two_point_route():
    coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]
    pts = R.interpolate(coords, speed_mps=20.0, interval_sec=1.0)
    assert [(p["lat"], p["lng"]) for p in pts] == [
        (25.0, 121.0),
        (25.0, 121.0001984583204),
        (25.0, 121.00039691664081),
        (25.0, 121.00059537496121),
        (25.0, 121.0007938332816),
        (25.0, 121.00099229160202),
        (25.0, 121.001),
    ]
    assert pts[0]["timestamp_offset"] == 0.0 and pts[0]["seg_idx"] == 0
    assert pts[-1]["lat"] == 25.0 and pts[-1]["lng"] == 121.001  # final wp always included


def test_random_point_in_radius_is_seed_deterministic():
    a = R.random_point_in_radius(25.0, 121.0, 500.0, rng=random.Random(42))
    b = R.random_point_in_radius(25.0, 121.0, 500.0, rng=random.Random(42))
    assert a == b   # same seed -> identical point (group-mode invariant)


@pytest.mark.asyncio
async def test_move_along_route_position_stream_matches_frozen_golden(monkeypatch):
    """GAP-2: drive _move_along_route with jitter disabled and assert the EXACT
    ordered position_update lat/lng stream against a FROZEN GOLDEN (NOT a
    push==emit tautology — both sinks get the same per-tick var, so equality
    alone would stay green even if the interpolation extraction broke).

    Inter-tick pacing uses `asyncio.wait_for(self._stop_event.wait(), ...)` (NOT
    the injected sleep), so without help this runs ~5s of real wall-clock. Patch
    wait_for to fire its timeout branch instantly; the position stream is
    timing-independent, so this only removes the wait.
    """
    async def _instant_timeout(aw, timeout):
        aw.close()                       # close the un-awaited stop-event coroutine
        raise asyncio.TimeoutError
    monkeypatch.setattr(asyncio, "wait_for", _instant_timeout)

    clock = FakeClock()
    sleep = SteppedSleep(clock)
    eng, loc, emitted = make_engine(clock=clock, sleep=sleep)

    # _move_along_route copies the passed profile into self._active_speed_profile
    # at its start (simulation_engine.py:670) — no field pre-arming needed.
    coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]
    profile = {"speed_mps": 20.0, "jitter": 0.0, "update_interval": 1.0}

    await eng._move_along_route(coords, profile)

    latlng = [(d["lat"], d["lng"]) for (t, d) in emitted if t == "position_update"]
    assert latlng == [
        (25.0, 121.0),
        (25.0, 121.0001984583204),
        (25.0, 121.00039691664081),
        (25.0, 121.00059537496121),
        (25.0, 121.0007938332816),
        (25.0, 121.00099229160202),
        (25.0, 121.001),
    ]
    assert loc.pushes == latlng   # secondary invariant: every emit had a matching push, in order
