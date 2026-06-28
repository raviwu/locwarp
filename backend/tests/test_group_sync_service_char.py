"""Characterization: GroupSyncService.auto_sync_new_device_to_primary.

Pins the danger-zone behaviour of the extracted group-sync use-case:
  (a) the new follower is teleported to the primary's current_position FIRST;
  (b) when the primary is in a dynamic sim state, a position-follower is
      attached that mirrors primary positions onto the follower (verified via
      a short real-sleep poll mirror);
  (c) all the noop cases: no primary, primary == new, missing engines, primary
      has no position, primary idle/non-dynamic (teleport only, no follower).

These functions had NO direct tests before the service extraction; the
behaviour asserted here is the verbatim pre-move behaviour of
``main._auto_sync_new_device_to_primary`` / ``main._follow_primary_positions``.
"""
from __future__ import annotations

import asyncio

import pytest

from models.schemas import SimulationState
from services.group_sync_service import GroupSyncService

pytestmark = pytest.mark.asyncio


class _Pos:
    def __init__(self, lat: float, lng: float):
        self.lat = lat
        self.lng = lng


class _FakeStopEvent:
    def __init__(self):
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True


class _FakeEngine:
    def __init__(self, state=SimulationState.IDLE, position=None):
        self.state = state
        self.current_position = position
        self._stop_event = _FakeStopEvent()
        self.teleport_calls: list[tuple[float, float]] = []
        self.set_position_calls: list[tuple[float, float]] = []

    async def teleport(self, lat: float, lng: float) -> None:
        self.teleport_calls.append((lat, lng))

    async def _set_position(self, lat: float, lng: float) -> None:
        self.set_position_calls.append((lat, lng))


class _FakeRegistry:
    def __init__(self):
        self._primary_udid: str | None = None
        self.simulation_engines: dict = {}


def _svc(reg: _FakeRegistry) -> GroupSyncService:
    return GroupSyncService(engine_registry=reg, device_manager=object())


# ── noop cases ───────────────────────────────────────────────────────────


async def test_noop_when_no_primary():
    reg = _FakeRegistry()
    reg._primary_udid = None
    new_eng = _FakeEngine(position=_Pos(1.0, 2.0))
    reg.simulation_engines["NEW"] = new_eng
    await _svc(reg).auto_sync_new_device_to_primary("NEW")
    assert new_eng.teleport_calls == []


async def test_noop_when_primary_is_new():
    reg = _FakeRegistry()
    reg._primary_udid = "NEW"
    new_eng = _FakeEngine(position=_Pos(1.0, 2.0))
    reg.simulation_engines["NEW"] = new_eng
    await _svc(reg).auto_sync_new_device_to_primary("NEW")
    assert new_eng.teleport_calls == []


async def test_noop_when_primary_engine_missing():
    reg = _FakeRegistry()
    reg._primary_udid = "P"
    new_eng = _FakeEngine()
    reg.simulation_engines["NEW"] = new_eng  # primary engine absent
    await _svc(reg).auto_sync_new_device_to_primary("NEW")
    assert new_eng.teleport_calls == []


async def test_noop_when_primary_has_no_position():
    reg = _FakeRegistry()
    reg._primary_udid = "P"
    reg.simulation_engines["P"] = _FakeEngine(position=None)
    new_eng = _FakeEngine()
    reg.simulation_engines["NEW"] = new_eng
    await _svc(reg).auto_sync_new_device_to_primary("NEW")
    assert new_eng.teleport_calls == []


# ── teleport-then-(maybe)follow ──────────────────────────────────────────


async def test_idle_primary_teleports_but_does_not_follow():
    reg = _FakeRegistry()
    reg._primary_udid = "P"
    reg.simulation_engines["P"] = _FakeEngine(
        state=SimulationState.IDLE, position=_Pos(10.0, 20.0)
    )
    new_eng = _FakeEngine()
    reg.simulation_engines["NEW"] = new_eng

    await _svc(reg).auto_sync_new_device_to_primary("NEW")

    # Teleport happened to the primary's position; no follower mirror.
    assert new_eng.teleport_calls == [(10.0, 20.0)]
    await asyncio.sleep(0.05)
    assert new_eng.set_position_calls == []


async def test_dynamic_primary_teleports_then_attaches_follower_mirror():
    reg = _FakeRegistry()
    reg._primary_udid = "P"
    primary = _FakeEngine(state=SimulationState.LOOPING, position=_Pos(10.0, 20.0))
    reg.simulation_engines["P"] = primary
    new_eng = _FakeEngine()
    reg.simulation_engines["NEW"] = new_eng

    await _svc(reg).auto_sync_new_device_to_primary("NEW")

    # Teleport ran first.
    assert new_eng.teleport_calls == [(10.0, 20.0)]

    # Follower task is now attached and mirrors primary positions. The poll
    # interval is 0.5s, so a 0.6s real sleep guarantees at least one mirror
    # cycle after we move the primary.
    primary.current_position = _Pos(11.0, 21.0)
    await asyncio.sleep(0.6)

    assert (11.0, 21.0) in new_eng.set_position_calls

    # Tear the follower down so it doesn't dangle past the test: flip primary.
    reg._primary_udid = "OTHER"
    await asyncio.sleep(0.6)


@pytest.mark.timeout(10)
async def test_follower_stops_when_primary_changes():
    reg = _FakeRegistry()
    reg._primary_udid = "P"
    primary = _FakeEngine(state=SimulationState.NAVIGATING)
    follower = _FakeEngine()
    reg.simulation_engines["P"] = primary
    reg.simulation_engines["F"] = follower

    task = asyncio.create_task(
        _svc(reg)._follow_primary_positions("F", "P")
    )
    await asyncio.sleep(0.05)
    reg._primary_udid = "OTHER"
    await asyncio.wait_for(task, timeout=2.0)
    assert task.done()


@pytest.mark.timeout(10)
async def test_follower_stops_when_stop_event_set():
    reg = _FakeRegistry()
    reg._primary_udid = "P"
    primary = _FakeEngine(state=SimulationState.NAVIGATING, position=_Pos(1.0, 1.0))
    follower = _FakeEngine()
    follower._stop_event.set()
    reg.simulation_engines["P"] = primary
    reg.simulation_engines["F"] = follower

    task = asyncio.create_task(
        _svc(reg)._follow_primary_positions("F", "P")
    )
    await asyncio.wait_for(task, timeout=2.0)
    assert task.done()
    assert follower.set_position_calls == []
