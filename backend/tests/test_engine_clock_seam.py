"""Phase 0a: clock/sleep seam on SimulationEngine.

Pins (a) the default real-clock wiring is unchanged, and (b) injected
clock/sleep callables are stored and used. No external behaviour change.
"""
import asyncio
import time

import pytest

from core.simulation_engine import SimulationEngine


class _NullLocation:
    """Minimal location_service stub; engine only awaits .set()."""
    async def set(self, lat: float, lng: float) -> None:
        return None


def test_default_clock_is_real_monotonic():
    eng = SimulationEngine(_NullLocation())
    # Contract: default clock is time.monotonic, default sleep is asyncio.sleep.
    assert eng._clock is time.monotonic
    assert eng._sleep is asyncio.sleep


def test_injected_clock_and_sleep_are_stored():
    fake_clock = lambda: 42.0
    async def fake_sleep(_): return None
    eng = SimulationEngine(_NullLocation(), clock=fake_clock, sleep=fake_sleep)
    assert eng._clock is fake_clock
    assert eng._sleep is fake_sleep
    assert eng._clock() == 42.0


def test_event_callback_still_positional_second_arg():
    # Regression: the existing (location_service, event_callback) positional
    # signature must be preserved; clock/sleep are keyword-only-ish extras.
    seen = []
    async def cb(t, d): seen.append((t, d))
    eng = SimulationEngine(_NullLocation(), cb)
    assert eng.event_callback is cb
