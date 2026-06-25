"""Characterization: _move_along_route honors per-point timing offsets when
present, and falls back to the constant-speed cadence when absent.

Danger-zone-test-first: drives the REAL _move_along_route with jitter OFF and
asserts the ordered position_update stream + inter-tick wait timeline. The
inter-tick pacing uses asyncio.wait_for(stop_event.wait(), timeout), so we
patch wait_for to fire its timeout branch instantly (position stream is
timing-independent) and capture the requested timeouts to assert the cadence.
"""
from __future__ import annotations

import asyncio

import pytest

from models.schemas import Coordinate
from tests._engine_harness import FakeClock, SteppedSleep, make_engine


pytestmark = pytest.mark.asyncio


async def _run(monkeypatch, coords, profile, offsets):
    waits: list[float] = []

    async def _instant_timeout(aw, timeout):
        waits.append(timeout)
        aw.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", _instant_timeout)
    clock = FakeClock()
    sleep = SteppedSleep(clock)
    eng, loc, emitted = make_engine(clock=clock, sleep=sleep)
    await eng._move_along_route(coords, profile, offsets=offsets)
    latlng = [(d["lat"], d["lng"]) for (t, d) in emitted if t == "position_update"]
    return latlng, waits, loc


async def test_timing_present_paces_off_original_offsets(monkeypatch):
    # Two segments: leg 1 = 4s, leg 2 = 1s. Same geometry length per leg, so a
    # constant-speed plan would pace both legs identically; with timing the
    # inter-tick waits reflect the ORIGINAL cadence (leg 2 ticks come faster).
    coords = [
        Coordinate(lat=25.0, lng=121.0),
        Coordinate(lat=25.0, lng=121.001),
        Coordinate(lat=25.0, lng=121.002),
    ]
    profile = {"speed_mps": 20.0, "jitter": 0.0, "update_interval": 1.0}
    offsets = [0.0, 4.0, 5.0]
    latlng, waits, loc = await _run(monkeypatch, coords, profile, offsets)
    # First + last vertex are present and exact.
    assert latlng[0] == (25.0, 121.0)
    assert latlng[-1] == (25.0, 121.002)
    # The emitted stream pushed every interpolated point in order.
    assert loc.pushes == latlng
    # Inter-tick waits derived from consecutive timestamp_offset deltas of the
    # timing-aware interpolation (1s grid → mostly 1.0s waits, with the final
    # short hop < 1.0s to land exactly on the 5.0s total). All waits > 0.
    assert all(w >= 0.0 for w in waits)
    assert any(abs(w - 1.0) < 1e-9 for w in waits)


async def test_timing_absent_matches_constant_speed_golden(monkeypatch):
    # Same coords, NO offsets → identical to the frozen constant-speed golden
    # from test_interpolator_golden.test_move_along_route_position_stream...
    coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]
    profile = {"speed_mps": 20.0, "jitter": 0.0, "update_interval": 1.0}
    latlng, _waits, loc = await _run(monkeypatch, coords, profile, None)
    assert latlng == [
        (25.0, 121.0),
        (25.0, 121.0001984583204),
        (25.0, 121.00039691664081),
        (25.0, 121.00059537496121),
        (25.0, 121.0007938332816),
        (25.0, 121.00099229160202),
        (25.0, 121.001),
    ]
    assert loc.pushes == latlng
