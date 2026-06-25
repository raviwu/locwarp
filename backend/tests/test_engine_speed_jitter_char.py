"""Characterization: per-tick speed jitter.

- With speed_jitter=0 (the default the existing char-tests use), the emitted
  position_update speed_mps is constant == base (no behavior change).
- With speed_jitter=0.15 and a SEEDED engine rng, every emitted speed_mps stays
  within ±15% of base and is strictly > 0; two identical seeded runs match.
Drives the REAL _move_along_route with position jitter OFF (jitter=0.0)."""
from __future__ import annotations

import asyncio
import random

import pytest

from models.schemas import Coordinate
from core.simulation_engine import SimulationEngine
from tests._engine_harness import FakeClock, SteppedSleep, RecordingLocation


pytestmark = pytest.mark.asyncio


def _make_engine_with_rng(rng):
    clock = FakeClock()
    sleep = SteppedSleep(clock)
    loc = RecordingLocation()
    emitted: list[tuple[str, dict]] = []

    async def cb(event_type, data):
        emitted.append((event_type, dict(data)))

    eng = SimulationEngine(loc, cb, clock=clock, sleep=sleep, rng=rng)
    return eng, loc, emitted


async def _run(monkeypatch, profile, rng):
    async def _instant_timeout(aw, timeout):
        aw.close()
        raise asyncio.TimeoutError
    monkeypatch.setattr(asyncio, "wait_for", _instant_timeout)
    eng, loc, emitted = _make_engine_with_rng(rng)
    coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]
    await eng._move_along_route(coords, profile)
    return [d["speed_mps"] for (t, d) in emitted if t == "position_update"]


async def test_speed_jitter_zero_keeps_speed_constant(monkeypatch):
    profile = {"speed_mps": 20.0, "jitter": 0.0, "update_interval": 1.0, "speed_jitter": 0.0}
    speeds = await _run(monkeypatch, profile, random.Random(1))
    assert speeds  # non-empty
    assert all(s == 20.0 for s in speeds)


async def test_speed_jitter_on_stays_within_bound_and_positive(monkeypatch):
    profile = {"speed_mps": 20.0, "jitter": 0.0, "update_interval": 1.0, "speed_jitter": 0.15}
    speeds = await _run(monkeypatch, profile, random.Random(42))
    assert speeds
    for s in speeds:
        assert 20.0 * 0.85 - 1e-9 <= s <= 20.0 * 1.15 + 1e-9
        assert s > 0.0


async def test_speed_jitter_seed_deterministic(monkeypatch):
    profile = {"speed_mps": 20.0, "jitter": 0.0, "update_interval": 1.0, "speed_jitter": 0.15}
    a = await _run(monkeypatch, profile, random.Random(42))
    b = await _run(monkeypatch, profile, random.Random(42))
    assert a == b
