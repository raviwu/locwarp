"""Characterization tests for core.joystick.JoystickHandler.

Freezes the CURRENT behavior of the realtime directional control:
start/stop lifecycle, bounds (no-position guard), state transitions,
input swap, and a single deterministic tick of the position-delta
state machine (move_point + jitter + distance accumulation + emit).

The inter-tick wait loop uses real asyncio.sleep + time.monotonic and
waits on engine._pause_event, so full multi-tick runs are not driven
deterministically here (see `gaps`). Single ticks are driven by flipping
is_active off after the first push and replacing asyncio.sleep with a
no-op so the loop exits without real waiting.
"""
from __future__ import annotations

import asyncio
import math

import pytest

from core.joystick import JoystickHandler, _TICK_INTERVAL
from models.schemas import (
    Coordinate,
    JoystickInput,
    MovementMode,
    SimulationState,
)
from config import SPEED_PROFILES
from services.interpolator import RouteInterpolator

from tests._engine_harness import make_engine


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------
class FakeEngine:
    """Minimal engine double exposing exactly what JoystickHandler touches."""

    def __init__(self, position: Coordinate | None = None):
        self.current_position = position
        self.state = SimulationState.IDLE
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # running
        self.distance_traveled = 0.0
        self.emitted: list[tuple[str, dict]] = []
        self.positions: list[tuple[float, float]] = []
        self.stop_calls = 0

    async def stop(self):
        self.stop_calls += 1
        # mirror real engine: returns to IDLE
        self.state = SimulationState.IDLE

    async def _emit(self, event_type, data):
        self.emitted.append((event_type, dict(data)))

    async def _set_position(self, lat, lng):
        self.positions.append((lat, lng))
        self.current_position = Coordinate(lat=lat, lng=lng)


# --------------------------------------------------------------------------
# start() — bounds / guards
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_start_raises_without_position():
    eng = FakeEngine(position=None)
    h = JoystickHandler(eng)
    with pytest.raises(RuntimeError, match="no current position"):
        await h.start(MovementMode.WALKING)
    assert h.is_active is False
    assert h._task is None


@pytest.mark.asyncio
async def test_start_does_not_stop_when_idle():
    eng = FakeEngine(position=Coordinate(lat=25.0, lng=121.0))
    eng.state = SimulationState.IDLE
    h = JoystickHandler(eng)
    await h.start(MovementMode.WALKING)
    try:
        assert eng.stop_calls == 0
    finally:
        await h.stop()


@pytest.mark.asyncio
async def test_start_does_not_stop_when_disconnected():
    eng = FakeEngine(position=Coordinate(lat=25.0, lng=121.0))
    eng.state = SimulationState.DISCONNECTED
    h = JoystickHandler(eng)
    await h.start(MovementMode.WALKING)
    try:
        assert eng.stop_calls == 0
    finally:
        await h.stop()


@pytest.mark.asyncio
async def test_start_stops_running_simulation_first():
    eng = FakeEngine(position=Coordinate(lat=25.0, lng=121.0))
    eng.state = SimulationState.NAVIGATING
    h = JoystickHandler(eng)
    await h.start(MovementMode.RUNNING)
    try:
        assert eng.stop_calls == 1
    finally:
        await h.stop()


# --------------------------------------------------------------------------
# start() — state transitions + profile selection
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", list(MovementMode))
async def test_start_selects_profile_and_transitions(mode):
    eng = FakeEngine(position=Coordinate(lat=25.0, lng=121.0))
    h = JoystickHandler(eng)
    await h.start(mode)
    try:
        assert h.is_active is True
        assert h.speed_profile == SPEED_PROFILES[mode.value]
        assert eng.state == SimulationState.JOYSTICK
        # state_change emitted with the joystick state value
        assert ("state_change", {"state": "joystick"}) in eng.emitted
        # current input reset to neutral
        assert h._current_input.direction == 0
        assert h._current_input.intensity == 0
        # background task spawned
        assert isinstance(h._task, asyncio.Task)
        # stop_event cleared so the loop may run
        assert eng._stop_event.is_set() is False
    finally:
        await h.stop()


@pytest.mark.asyncio
async def test_start_clears_stop_event():
    eng = FakeEngine(position=Coordinate(lat=25.0, lng=121.0))
    eng._stop_event.set()
    h = JoystickHandler(eng)
    await h.start(MovementMode.DRIVING)
    try:
        assert eng._stop_event.is_set() is False
    finally:
        await h.stop()


# --------------------------------------------------------------------------
# update_input() — non-blocking input swap
# --------------------------------------------------------------------------
def test_update_input_swaps_current_input():
    eng = FakeEngine(position=Coordinate(lat=25.0, lng=121.0))
    h = JoystickHandler(eng)
    assert h._current_input.direction == 0
    new_input = JoystickInput(direction=90.0, intensity=0.5)
    h.update_input(new_input)
    assert h._current_input is new_input
    assert h._current_input.direction == 90.0
    assert h._current_input.intensity == 0.5


# --------------------------------------------------------------------------
# stop()
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stop_resets_input_and_clears_active():
    eng = FakeEngine(position=Coordinate(lat=25.0, lng=121.0))
    h = JoystickHandler(eng)
    await h.start(MovementMode.WALKING)
    h.update_input(JoystickInput(direction=45.0, intensity=1.0))
    await h.stop()
    assert h.is_active is False
    assert h._task is None
    assert h._current_input.direction == 0
    assert h._current_input.intensity == 0


@pytest.mark.asyncio
async def test_stop_is_idempotent_when_never_started():
    eng = FakeEngine(position=Coordinate(lat=25.0, lng=121.0))
    h = JoystickHandler(eng)
    # _task is None, is_active False — stop must be a no-op that doesn't raise
    await h.stop()
    assert h.is_active is False
    assert h._task is None


@pytest.mark.asyncio
async def test_stop_cancels_running_task():
    eng = FakeEngine(position=Coordinate(lat=25.0, lng=121.0))
    h = JoystickHandler(eng)
    await h.start(MovementMode.WALKING)
    task = h._task
    assert task is not None
    await h.stop()
    assert task.done() is True


# --------------------------------------------------------------------------
# _loop() — single deterministic tick of the position-delta state machine
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_loop_tick_moves_position_and_emits(monkeypatch):
    """One tick with intensity>0: computes move_point + jitter, pushes the
    position, accumulates distance, emits position_update. The loop is
    forced to exit after one push by replacing asyncio.sleep with a
    deactivating no-op, and jitter randomness is removed by stubbing
    add_jitter to identity (frozen: real loop ADDS jitter via add_jitter,
    here we isolate the move_point delta + distance/emit bookkeeping)."""
    eng = FakeEngine(position=Coordinate(lat=25.0, lng=121.0))
    h = JoystickHandler(eng)
    h.speed_profile = dict(SPEED_PROFILES["walking"])
    h.is_active = True
    h._current_input = JoystickInput(direction=90.0, intensity=1.0)

    # jitter -> identity so the pushed position is exactly move_point output
    monkeypatch.setattr(
        RouteInterpolator, "add_jitter",
        staticmethod(lambda lat, lng, j: (lat, lng)),
    )

    # asyncio.sleep replacement: deactivate then return immediately so the
    # while-loop condition (is_active) is False on the next check -> exit.
    async def _kill_sleep(_s):
        h.is_active = False

    monkeypatch.setattr("core.joystick.asyncio.sleep", _kill_sleep)

    await h._loop()

    # exactly one push happened
    assert len(eng.positions) == 1

    # the pushed position equals move_point(start, dir, distance)
    speed_mps = SPEED_PROFILES["walking"]["speed_mps"] * 1.0
    distance = speed_mps * _TICK_INTERVAL
    exp_lat, exp_lng = RouteInterpolator.move_point(25.0, 121.0, 90.0, distance)
    got_lat, got_lng = eng.positions[0]
    assert got_lat == pytest.approx(exp_lat)
    assert got_lng == pytest.approx(exp_lng)

    # distance accumulated by exactly one tick's worth
    assert eng.distance_traveled == pytest.approx(distance)

    # position_update emitted with bearing == direction and speed_mps
    kinds = [e for e in eng.emitted if e[0] == "position_update"]
    assert len(kinds) == 1
    _, data = kinds[0]
    assert data["bearing"] == 90.0
    assert data["speed_mps"] == pytest.approx(speed_mps)
    assert data["lat"] == pytest.approx(exp_lat)
    assert data["lng"] == pytest.approx(exp_lng)

    # heading east (bearing 90) from lng 121 increases longitude, lat ~unchanged
    assert got_lng > 121.0
    assert got_lat == pytest.approx(25.0, abs=1e-6)


@pytest.mark.asyncio
async def test_loop_tick_zero_intensity_skips_move(monkeypatch):
    """intensity == 0: no push, no distance, no position_update. The loop
    still reaches the sleep and we use it to break out."""
    eng = FakeEngine(position=Coordinate(lat=10.0, lng=20.0))
    h = JoystickHandler(eng)
    h.speed_profile = dict(SPEED_PROFILES["running"])
    h.is_active = True
    h._current_input = JoystickInput(direction=180.0, intensity=0.0)

    async def _kill_sleep(_s):
        h.is_active = False

    monkeypatch.setattr("core.joystick.asyncio.sleep", _kill_sleep)

    await h._loop()

    assert eng.positions == []
    assert eng.distance_traveled == 0.0
    assert not any(e[0] == "position_update" for e in eng.emitted)


@pytest.mark.asyncio
async def test_loop_exits_immediately_when_stop_event_set():
    """If the stop event is already set, the while condition is False on
    entry -> no ticks, finally sets is_active False."""
    eng = FakeEngine(position=Coordinate(lat=0.0, lng=0.0))
    eng._stop_event.set()
    h = JoystickHandler(eng)
    h.speed_profile = dict(SPEED_PROFILES["walking"])
    h.is_active = True
    h._current_input = JoystickInput(direction=0.0, intensity=1.0)

    await h._loop()

    assert eng.positions == []
    assert h.is_active is False  # finally block


@pytest.mark.asyncio
async def test_loop_intensity_scales_distance(monkeypatch):
    """Half intensity -> half the per-tick distance accumulation."""
    eng = FakeEngine(position=Coordinate(lat=25.0, lng=121.0))
    h = JoystickHandler(eng)
    h.speed_profile = dict(SPEED_PROFILES["driving"])
    h.is_active = True
    h._current_input = JoystickInput(direction=0.0, intensity=0.5)

    monkeypatch.setattr(
        RouteInterpolator, "add_jitter",
        staticmethod(lambda lat, lng, j: (lat, lng)),
    )

    async def _kill_sleep(_s):
        h.is_active = False

    monkeypatch.setattr("core.joystick.asyncio.sleep", _kill_sleep)

    await h._loop()

    expected = SPEED_PROFILES["driving"]["speed_mps"] * 0.5 * _TICK_INTERVAL
    assert eng.distance_traveled == pytest.approx(expected)


@pytest.mark.asyncio
async def test_loop_swallows_exception_and_deactivates(monkeypatch):
    """A raising _set_position is caught by the broad except; finally still
    flips is_active False (loop never re-raises)."""
    eng = FakeEngine(position=Coordinate(lat=25.0, lng=121.0))

    async def boom(lat, lng):
        raise ValueError("device gone")

    eng._set_position = boom
    h = JoystickHandler(eng)
    h.speed_profile = dict(SPEED_PROFILES["walking"])
    h.is_active = True
    h._current_input = JoystickInput(direction=0.0, intensity=1.0)

    monkeypatch.setattr(
        RouteInterpolator, "add_jitter",
        staticmethod(lambda lat, lng, j: (lat, lng)),
    )

    # Must not raise out of _loop
    await h._loop()

    assert h.is_active is False
    assert eng.positions == []  # push raised before append


# --------------------------------------------------------------------------
# Integration against the REAL engine via the harness
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_start_against_real_engine_transitions_state():
    eng, loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0375, lng=121.5637)
    jh = eng._joystick
    await jh.start(MovementMode.WALKING)
    try:
        assert eng.state == SimulationState.JOYSTICK
        assert jh.is_active is True
        assert ("state_change", {"state": "joystick"}) in emitted
    finally:
        await jh.stop()
    assert jh.is_active is False


@pytest.mark.asyncio
async def test_real_engine_stop_deactivates_joystick():
    eng, loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0375, lng=121.5637)
    jh = eng._joystick
    await jh.start(MovementMode.RUNNING)
    # engine.stop() must also stop the joystick handler
    await eng.stop()
    assert jh.is_active is False
    assert eng.state == SimulationState.IDLE


def test_module_tick_interval_constant():
    # frozen default cadence
    assert _TICK_INTERVAL == 0.2
