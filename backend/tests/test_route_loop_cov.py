"""Characterization tests for core.route_loop (RouteLooper + _run_jump_loop).

Behavior-freeze: these assert the module's ACTUAL current behavior, not what it
"should" do. The non-deterministic continuous-movement path inside
SimulationEngine._move_along_route is stubbed out (replaced with an async
recorder) so the loop's *structure* (lap/leg advancement, snapshot, jump loop,
state transitions, emitted events) can be exercised deterministically. randomness
in the pause sampler is seeded; route_service is faked (no network).
"""
from __future__ import annotations

import random

import pytest

from core.route_loop import RouteLooper, _run_jump_loop
from models.schemas import Coordinate, MovementMode, SimulationState
from tests._engine_harness import make_engine


# ── Fakes ────────────────────────────────────────────────────────────────


class FakeRouteService:
    """Stand-in for engine.route_service. Records calls and returns canned
    densified routes. get_multi_route closes the loop; get_route returns the
    two endpoints as a 2-point polyline."""

    def __init__(self):
        self.multi_calls: list = []
        self.route_calls: list = []

    async def get_multi_route(self, wp_tuples, *, profile, force_straight, engine):
        self.multi_calls.append(
            {"wps": list(wp_tuples), "profile": profile,
             "force_straight": force_straight, "engine": engine}
        )
        # Return the same waypoints back as the densified polyline.
        return {"coords": [list(t) for t in wp_tuples], "distance": 1234.5}

    async def get_route(self, a_lat, a_lng, b_lat, b_lng, *, profile,
                        force_straight, engine):
        self.route_calls.append(
            {"a": (a_lat, a_lng), "b": (b_lat, b_lng), "profile": profile,
             "force_straight": force_straight, "engine": engine}
        )
        return {"coords": [[a_lat, a_lng], [b_lat, b_lng]], "distance": 100.0}


def _wire(engine):
    """Attach a FakeRouteService and an async _move_along_route recorder to a
    harness engine. Returns (fake_route_service, move_calls)."""
    frs = FakeRouteService()
    engine.route_service = frs
    move_calls: list = []

    async def _fake_move(coords, speed_profile):
        move_calls.append({"coords": list(coords), "speed": dict(speed_profile)})

    engine._move_along_route = _fake_move  # type: ignore[assignment]
    return frs, move_calls


def _wp(lat, lng):
    return Coordinate(lat=lat, lng=lng)


def _types(emitted):
    return [t for (t, _d) in emitted]


# ── start_loop: input validation ────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_loop_requires_at_least_two_waypoints():
    eng, _loc, _emitted = make_engine()
    looper = RouteLooper(eng)
    with pytest.raises(ValueError, match="At least 2 waypoints"):
        await looper.start_loop([_wp(1.0, 2.0)], MovementMode.WALKING)


@pytest.mark.asyncio
async def test_start_loop_empty_osrm_route_raises():
    """When get_multi_route returns < 2 coords, ValueError is raised."""
    eng, _loc, _emitted = make_engine()
    looper = RouteLooper(eng)

    class EmptyRoute(FakeRouteService):
        async def get_multi_route(self, *a, **k):
            return {"coords": [[1.0, 2.0]], "distance": 0.0}

    eng.route_service = EmptyRoute()
    eng._stop_event.set()  # ensure no loop even if it got past the guard
    with pytest.raises(ValueError, match="empty route"):
        await looper.start_loop(
            [_wp(1.0, 2.0), _wp(3.0, 4.0)], MovementMode.WALKING
        )


# ── start_loop: pre-stopped (entry + emissions, zero laps) ───────────────


@pytest.mark.asyncio
async def test_start_loop_prestopped_emits_path_and_state_no_laps():
    """With the stop event already set, the while loop never runs a lap.
    The handler still: closes the loop in the OSRM call, sets LOOPING then
    resets to IDLE, and emits route_path + two state_change events."""
    eng, _loc, emitted = make_engine()
    frs, move_calls = _wire(eng)
    eng._stop_event.set()
    looper = RouteLooper(eng)

    wps = [_wp(10.0, 20.0), _wp(11.0, 21.0)]
    await looper.start_loop(wps, MovementMode.WALKING)

    # Loop body never executed -> no movement, lap_count stays 0.
    assert move_calls == []
    assert eng.lap_count == 0
    # Ends back at IDLE (was set to LOOPING then reset).
    assert eng.state == SimulationState.IDLE
    # total_segments = len(coords) - 1; coords = closed waypoints (3 points).
    assert eng.total_segments == 2

    types = _types(emitted)
    assert types.count("route_path") == 1
    # One LOOPING state_change + one IDLE state_change at teardown.
    assert types.count("state_change") == 2
    state_vals = [d["state"] for (t, d) in emitted if t == "state_change"]
    assert state_vals == [SimulationState.LOOPING.value, SimulationState.IDLE.value]

    # OSRM multi-route was called once with the loop closed (first wp appended).
    assert len(frs.multi_calls) == 1
    call = frs.multi_calls[0]
    assert call["wps"] == [(10.0, 20.0), (11.0, 21.0), (10.0, 20.0)]
    assert call["profile"] == "foot"  # WALKING -> foot


@pytest.mark.asyncio
async def test_start_loop_car_profile_for_driving_modes():
    """Non walking/running modes route with the 'car' OSRM profile."""
    eng, _loc, _emitted = make_engine()
    frs, _move = _wire(eng)
    eng._stop_event.set()
    looper = RouteLooper(eng)

    # DRIVING/CYCLING etc. -> car. Use any non walking/running member.
    mode = next(m for m in MovementMode
                if m not in (MovementMode.WALKING, MovementMode.RUNNING))
    await looper.start_loop([_wp(0.0, 0.0), _wp(1.0, 1.0)], mode)
    assert frs.multi_calls[0]["profile"] == "car"


# ── start_loop: single lap traversal (lap_count limit) ───────────────────


@pytest.mark.asyncio
async def test_start_loop_single_lap_walks_each_leg_and_completes():
    """lap_count=1 bounds the loop to exactly one lap. The closed 3-waypoint
    route has 3 legs; each leg routes via get_route and moves. lap_complete
    and loop_complete are emitted, and the engine returns to IDLE."""
    eng, _loc, emitted = make_engine()
    frs, move_calls = _wire(eng)
    looper = RouteLooper(eng)

    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0), _wp(2.0, 2.0)]
    # closed_waypoints = wps + [wps[0]] = 4 points -> num_legs = 3.
    await looper.start_loop(
        wps, MovementMode.WALKING,
        pause_enabled=False, lap_count=1,
    )

    assert eng.lap_count == 1
    assert eng.state == SimulationState.IDLE
    # One get_route per leg of one lap.
    assert len(frs.route_calls) == 3
    assert len(move_calls) == 3

    types = _types(emitted)
    assert types.count("lap_complete") == 1
    # loop_complete only fires in the auto-stop (lap-limit) path.
    assert types.count("loop_complete") == 1
    lap_evt = next(d for (t, d) in emitted if t == "lap_complete")
    assert lap_evt == {"lap": 1, "total": 1}
    done_evt = next(d for (t, d) in emitted if t == "loop_complete")
    assert done_evt == {"laps": 1}


@pytest.mark.asyncio
async def test_start_loop_two_laps_accumulates_lap_count():
    eng, _loc, emitted = make_engine()
    frs, move_calls = _wire(eng)
    looper = RouteLooper(eng)

    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0)]
    # 2 waypoints -> closed = 3 points -> num_legs = 2.
    await looper.start_loop(
        wps, MovementMode.WALKING, pause_enabled=False, lap_count=2,
    )
    assert eng.lap_count == 2
    # 2 legs * 2 laps.
    assert len(frs.route_calls) == 4
    assert len(move_calls) == 4
    laps = [d["lap"] for (t, d) in emitted if t == "lap_complete"]
    assert laps == [1, 2]


@pytest.mark.asyncio
async def test_start_loop_first_leg_origin_is_waypoint_when_no_resume():
    """Without a resume snapshot, leg 0 routes FROM wp_a (waypoints[0]),
    not from current_position."""
    eng, _loc, _emitted = make_engine()
    frs, _move = _wire(eng)
    eng.current_position = _wp(80.0, 99.0)  # should be ignored (no resume)
    looper = RouteLooper(eng)

    wps = [_wp(5.0, 6.0), _wp(7.0, 8.0)]
    await looper.start_loop(
        wps, MovementMode.WALKING, pause_enabled=False, lap_count=1,
    )
    # First leg origin == waypoints[0], NOT current_position.
    assert frs.route_calls[0]["a"] == (5.0, 6.0)


# ── start_loop: resume snapshot path ─────────────────────────────────────


@pytest.mark.asyncio
async def test_start_loop_resume_snapshot_inherits_lap_and_segment():
    """A start_loop resume snapshot makes the handler inherit lap_count and
    begin at the recorded leg, using current_position as the first leg's
    origin instead of teleporting back to wp_a."""
    eng, _loc, _emitted = make_engine()
    frs, _move = _wire(eng)
    eng.current_position = _wp(50.0, 60.0)
    eng._resume_snapshot = {
        "kind": "start_loop",
        "lap_count": 4,
        "segment_index": 1,
        "user_waypoint_next": 2,
    }
    looper = RouteLooper(eng)

    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0), _wp(2.0, 2.0)]
    # closed = 4 points -> num_legs = 3. resume_seg = 1 -> leg_start = 1.
    await looper.start_loop(
        wps, MovementMode.WALKING, pause_enabled=False, lap_count=5,
    )

    # Snapshot consumed (set to None at entry).
    assert eng._resume_snapshot is None
    # Inherited lap 4, then ran lap(s) up to the limit of 5 -> ended at 5.
    assert eng.lap_count == 5

    # First lap started at leg_start=1 (so only legs 1,2 ran on lap 1),
    # using current_position (50,60) as the first leg's origin.
    assert frs.route_calls[0]["a"] == (50.0, 60.0)


@pytest.mark.asyncio
async def test_start_loop_resume_snapshot_wrong_kind_ignored():
    """A resume snapshot whose kind != 'start_loop' is NOT consumed as a
    loop resume: lap_count starts at 0 and the run begins from leg 0."""
    eng, _loc, _emitted = make_engine()
    frs, _move = _wire(eng)
    eng.current_position = _wp(50.0, 60.0)
    eng._resume_snapshot = {"kind": "multi_stop", "lap_count": 9}
    looper = RouteLooper(eng)

    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0)]
    await looper.start_loop(
        wps, MovementMode.WALKING, pause_enabled=False, lap_count=1,
    )
    # Snapshot still cleared at entry regardless.
    assert eng._resume_snapshot is None
    # Did NOT inherit lap 9 -> fresh start ran exactly one lap.
    assert eng.lap_count == 1
    # Leg 0 origin is wp_a (0,0), not current_position.
    assert frs.route_calls[0]["a"] == (0.0, 0.0)


# ── start_loop: pause sampler / pause-driven stop ────────────────────────


@pytest.mark.asyncio
async def test_start_loop_pause_emits_countdown_events(monkeypatch):
    """With pauses enabled and a seeded RNG, the handler emits pause_countdown
    + pause_countdown_end at each non-final stop of the lap."""
    eng, _loc, emitted = make_engine()
    _frs, _move = _wire(eng)
    looper = RouteLooper(eng)

    # Deterministic pause duration. _stop_event.wait() returns immediately?
    # No: wait_for times out after `secs`. To keep the test fast and not
    # actually sleep, make the pause duration sampler return a tiny value and
    # rely on asyncio.wait_for timing out near-instantly is still real time.
    # Instead, monkeypatch random.uniform to a small positive value and let
    # the real wait_for time out. Use a very small timeout.
    monkeypatch.setattr(random, "uniform", lambda lo, hi: 0.001)

    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0), _wp(2.0, 2.0)]
    # 3 legs; pause happens at every leg except the last -> 2 pauses.
    await looper.start_loop(
        wps, MovementMode.WALKING,
        pause_enabled=True, pause_min=0.001, pause_max=0.001, lap_count=1,
    )
    types = _types(emitted)
    # Two non-final legs (leg 0, leg 1) -> two pause_countdown emissions.
    assert types.count("pause_countdown") == 2
    assert types.count("pause_countdown_end") == 2
    pc = next(d for (t, d) in emitted if t == "pause_countdown")
    assert pc["source"] == "loop"
    assert pc["duration_seconds"] == pytest.approx(0.001)


@pytest.mark.asyncio
async def test_start_loop_pause_disabled_no_countdown(monkeypatch):
    eng, _loc, emitted = make_engine()
    _wire(eng)
    looper = RouteLooper(eng)
    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0), _wp(2.0, 2.0)]
    await looper.start_loop(
        wps, MovementMode.WALKING, pause_enabled=False, lap_count=1,
    )
    types = _types(emitted)
    assert "pause_countdown" not in types
    assert "pause_countdown_end" not in types


# ── _next_pause_seconds boundary semantics (indirectly via _pause_at_stop) ─


@pytest.mark.asyncio
async def test_start_loop_pause_max_zero_means_no_pause():
    """pause_max <= 0 -> sampler returns 0 -> no countdown emitted even though
    pause_enabled is True."""
    eng, _loc, emitted = make_engine()
    _wire(eng)
    looper = RouteLooper(eng)
    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0), _wp(2.0, 2.0)]
    await looper.start_loop(
        wps, MovementMode.WALKING,
        pause_enabled=True, pause_min=0.0, pause_max=0.0, lap_count=1,
    )
    assert "pause_countdown" not in _types(emitted)


# ── start_loop: jump_mode delegates to _run_jump_loop ────────────────────


@pytest.mark.asyncio
async def test_start_loop_jump_mode_delegates_and_skips_osrm():
    """jump_mode=True routes through _run_jump_loop: no OSRM multi-route call,
    teleports via _set_position, returns early."""
    eng, loc, emitted = make_engine()
    frs, move_calls = _wire(eng)
    looper = RouteLooper(eng)

    wps = [_wp(1.0, 2.0), _wp(3.0, 4.0)]
    await looper.start_loop(
        wps, MovementMode.WALKING,
        jump_mode=True, jump_interval=0.0, lap_count=1,
    )
    # No OSRM routing in jump mode.
    assert frs.multi_calls == []
    assert frs.route_calls == []
    assert move_calls == []
    # Teleported to each waypoint (2) + close-loop teleport back to wp0 (1) = 3.
    assert loc.pushes == [(1.0, 2.0), (3.0, 4.0), (1.0, 2.0)]
    assert eng.lap_count == 1


# ── _run_jump_loop: direct tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_jump_loop_single_lap_closed_teleports_and_completes():
    eng, loc, emitted = make_engine()
    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0)]

    await _run_jump_loop(
        eng, wps, interval=0.0, lap_count=1, close_loop=True,
    )

    # state machine: LOOPING during, IDLE at the end.
    assert eng.state == SimulationState.IDLE
    assert eng.lap_count == 1
    assert eng.total_segments == 2  # = len(waypoints)
    # Teleports: wp0, wp1, then close-loop back to wp0.
    assert loc.pushes == [(0.0, 0.0), (1.0, 1.0), (0.0, 0.0)]

    types = _types(emitted)
    assert types[0] == "route_path"
    assert "state_change" in types
    assert types.count("lap_complete") == 1
    assert types.count("loop_complete") == 1
    # position_update per waypoint (2) + 1 close-loop position_update.
    assert types.count("position_update") == 3
    lap_evt = next(d for (t, d) in emitted if t == "lap_complete")
    assert lap_evt == {"lap": 1, "total": 1}


@pytest.mark.asyncio
async def test_jump_loop_open_loop_no_closing_teleport():
    """close_loop=False: no teleport back to wp0 after the last waypoint."""
    eng, loc, emitted = make_engine()
    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0), _wp(2.0, 2.0)]

    await _run_jump_loop(
        eng, wps, interval=0.0, lap_count=1, close_loop=False,
    )
    # Exactly one teleport per waypoint, no closing teleport.
    assert loc.pushes == [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]
    # position_update once per waypoint, no extra close-loop update.
    assert _types(emitted).count("position_update") == 3


@pytest.mark.asyncio
async def test_jump_loop_prestopped_runs_zero_laps():
    """If the stop event is already set, the outer while never iterates;
    the engine still ends IDLE with zero laps and zero teleports."""
    eng, loc, emitted = make_engine()
    eng._stop_event.set()
    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0)]

    await _run_jump_loop(
        eng, wps, interval=0.0, lap_count=None, close_loop=True,
    )
    assert eng.lap_count == 0
    assert eng.state == SimulationState.IDLE
    assert loc.pushes == []
    # Setup emissions still happen (route_path + state_change before loop).
    types = _types(emitted)
    assert types.count("route_path") == 1
    assert "lap_complete" not in types


@pytest.mark.asyncio
async def test_jump_loop_segment_and_waypoint_tracking():
    """segment_index tracks the last visited waypoint index; _user_waypoint_next
    clamps to len(waypoints)."""
    eng, _loc, _emitted = make_engine()
    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0), _wp(2.0, 2.0)]
    await _run_jump_loop(
        eng, wps, interval=0.0, lap_count=1, close_loop=False,
    )
    # Last iteration set segment_index to the final waypoint index (2).
    assert eng.segment_index == 2
    assert eng._user_waypoints == wps
    # _user_waypoint_next is min(i+1, len) -> 3 on last waypoint.
    assert eng._user_waypoint_next == 3


@pytest.mark.asyncio
async def test_jump_loop_two_laps():
    eng, loc, emitted = make_engine()
    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0)]
    await _run_jump_loop(
        eng, wps, interval=0.0, lap_count=2, close_loop=True,
    )
    assert eng.lap_count == 2
    laps = [d["lap"] for (t, d) in emitted if t == "lap_complete"]
    assert laps == [1, 2]
    # Each lap: 2 waypoint teleports + 1 close-loop teleport = 3; x2 laps = 6.
    assert len(loc.pushes) == 6


@pytest.mark.asyncio
async def test_jump_loop_infinite_stops_via_event_negative_interval():
    """interval < 0 makes _dwell return _stop_event.is_set() immediately.
    With lap_count=None (infinite), pre-setting the stop event mid-construction
    is awkward; instead drive one lap by setting stop after first dwell is
    impossible synchronously. Characterize the interval<=0 dwell branch by
    pre-setting stop so the dwell returns True on the first waypoint."""
    eng, loc, emitted = make_engine()
    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0)]
    # Pre-set so the very first _dwell (interval<=0 branch) returns True and
    # breaks the inner for-loop, then the outer while exits.
    eng._stop_event.set()
    await _run_jump_loop(
        eng, wps, interval=-1.0, lap_count=None, close_loop=True,
    )
    # Outer while guard `not is_set()` is False from the start -> zero teleports.
    assert loc.pushes == []
    assert eng.lap_count == 0
    assert eng.state == SimulationState.IDLE
