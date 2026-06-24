"""Characterize the 3-attempt position push-retry loop currently inline in
SimulationEngine._move_along_route, before it is carved into _push_with_retry.
Drives a REAL SimulationEngine; the device push is a fake LocationService
whose .set raises on a scripted schedule (the engine's _DefaultDevicePort
fallback delegates set_location -> location_service.set).
"""
import asyncio

import pytest

from tests._engine_harness import FakeClock, SteppedSleep

pytestmark = pytest.mark.asyncio


class _ScriptedLoc:
    """location_service double: .set raises the next scripted exception (or
    succeeds when the schedule is exhausted), recording every (lat,lng) it
    accepts. None in the schedule = succeed this call."""
    def __init__(self, schedule):
        self._schedule = list(schedule)
        self.pushes = []

    async def set(self, lat, lng):
        if self._schedule:
            exc = self._schedule.pop(0)
            if exc is not None:
                raise exc
        self.pushes.append((lat, lng))

    async def clear(self):
        pass


def _make_with_loc(loc, clock, sleep):
    from core.simulation_engine import SimulationEngine
    return SimulationEngine(loc, None, clock=clock, sleep=sleep)


async def test_push_succeeds_first_attempt_no_backoff_sleep():
    clock = FakeClock(); sleep = SteppedSleep(clock)
    loc = _ScriptedLoc([None])  # first .set succeeds
    eng = _make_with_loc(loc, clock, sleep)
    ok = await eng._push_with_retry(25.0, 121.0)
    assert ok is True
    assert loc.pushes == [(25.0, 121.0)]
    assert sleep.durations == []  # no backoff on first-attempt success
    assert (eng.current_position.lat, eng.current_position.lng) == (25.0, 121.0)


async def test_push_retries_with_increasing_backoff_then_succeeds():
    clock = FakeClock(); sleep = SteppedSleep(clock)
    # attempt 1 -> ConnectionError (sleep 0.5), attempt 2 -> OSError (sleep 1.0),
    # attempt 3 -> success.
    loc = _ScriptedLoc([ConnectionError("boom"), OSError("boom2"), None])
    eng = _make_with_loc(loc, clock, sleep)
    ok = await eng._push_with_retry(25.0, 121.0)
    assert ok is True
    assert loc.pushes == [(25.0, 121.0)]
    assert sleep.durations == [0.5, 1.0]  # 0.5*(0+1), 0.5*(1+1)


async def test_push_exhausts_three_attempts_returns_false():
    clock = FakeClock(); sleep = SteppedSleep(clock)
    loc = _ScriptedLoc([ConnectionError("1"), ConnectionError("2"), ConnectionError("3")])
    eng = _make_with_loc(loc, clock, sleep)
    ok = await eng._push_with_retry(25.0, 121.0)
    assert ok is False
    assert loc.pushes == []
    # backoff runs after each failure INCLUDING the last, matching the
    # current inline loop: 0.5, 1.0, 1.5.
    assert sleep.durations == [0.5, 1.0, 1.5]


async def test_generic_exception_breaks_immediately_returns_false():
    clock = FakeClock(); sleep = SteppedSleep(clock)
    loc = _ScriptedLoc([ValueError("unexpected")])
    eng = _make_with_loc(loc, clock, sleep)
    ok = await eng._push_with_retry(25.0, 121.0)
    assert ok is False
    assert sleep.durations == []  # generic Exception path does NOT backoff-sleep


async def test_cancelled_error_propagates():
    clock = FakeClock(); sleep = SteppedSleep(clock)
    loc = _ScriptedLoc([asyncio.CancelledError()])
    eng = _make_with_loc(loc, clock, sleep)
    with pytest.raises(asyncio.CancelledError):
        await eng._push_with_retry(25.0, 121.0)
