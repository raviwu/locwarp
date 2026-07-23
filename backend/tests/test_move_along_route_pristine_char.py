"""Characterization: GPS jitter reaches the DEVICE but never the recorded
live position or the position_update broadcast.

Root cause of the 'saved bookmark drifts a few metres with a long-precision
tail' bug: the jittered coord used to be written into current_position and
broadcast, so 'Bookmark Here' persisted it. This pins the fix: device gets
jittered, current_position + position_update stay pristine (the exact route
point). add_jitter is stubbed to a fixed offset for determinism, mirroring the
identity-stub pattern in test_joystick_cov.py."""
from __future__ import annotations

import asyncio

import pytest

from models.schemas import Coordinate
from core.simulation_engine import SimulationEngine
from domain.movement import RouteInterpolator
from tests._engine_harness import FakeClock, SteppedSleep, RecordingLocation

pytestmark = pytest.mark.asyncio


def _make_engine():
    clock = FakeClock()
    sleep = SteppedSleep(clock)
    loc = RecordingLocation()
    emitted: list[tuple[str, dict]] = []

    async def cb(event_type, data):
        emitted.append((event_type, dict(data)))

    eng = SimulationEngine(loc, cb, clock=clock, sleep=sleep)
    return eng, loc, emitted


async def test_route_jitter_hits_device_not_broadcast(monkeypatch):
    # Deterministic non-identity jitter: +0.001 on each axis.
    monkeypatch.setattr(
        RouteInterpolator, "add_jitter",
        staticmethod(lambda lat, lng, j, rng=None: (lat + 0.001, lng + 0.001)),
    )

    async def _instant_timeout(aw, timeout):
        aw.close()
        raise asyncio.TimeoutError
    monkeypatch.setattr(asyncio, "wait_for", _instant_timeout)

    eng, loc, emitted = _make_engine()
    coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]
    profile = {"speed_mps": 20.0, "jitter": 5.0, "update_interval": 1.0, "speed_jitter": 0.0}
    await eng._move_along_route(coords, profile)

    pos_events = [d for (t, d) in emitted if t == "position_update"]
    assert pos_events, "expected at least one position_update"

    # The route runs along lat==25.0; every pushed device coord carries the
    # +0.001 jitter offset (pushed lat == 25.001), while the broadcast lat
    # stays pristine (25.0).
    # Device-side jitter is asserted on lat here; the both-axes device-jitter
    # property is covered exactly by the joystick test (single-tick exact tuple).
    assert loc.pushes, "expected at least one device push"
    assert all(plat == pytest.approx(25.001) for (plat, _plng) in loc.pushes)

    # Broadcast + recorded live position are the pristine route points (no offset).
    for d in pos_events:
        assert d["lat"] == pytest.approx(25.0)
    assert eng.current_position.lat == pytest.approx(25.0)
    assert eng.current_position.lng == pytest.approx(121.001)  # pristine final point
