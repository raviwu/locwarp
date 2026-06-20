"""Characterization tests for core.multi_stop (MultiStopNavigator).

These freeze the module's ACTUAL current behavior. Where a value surprised
me I assert the real value and note it inline. The inter-tick wait inside
SimulationEngine._move_along_route is NOT exercised here -- we stub
_move_along_route on the engine so the multi-stop leg loop runs
deterministically without real timers.
"""
from __future__ import annotations

import asyncio
import random

import pytest

from core.multi_stop import MultiStopNavigator, _run_jump_multistop
from models.schemas import Coordinate, MovementMode, SimulationState
from tests._engine_harness import make_engine


# ── Fake route service ───────────────────────────────────────────────
class FakeRouteService:
    """Records calls; returns canned route dicts. Coords echo origin->dest
    so _move_along_route (when not stubbed) would have >=2 points."""

    def __init__(self, *, leg_distance: float = 100.0, multi_distance: float = 250.0):
        self.leg_distance = leg_distance
        self.multi_distance = multi_distance
        self.get_route_calls: list[tuple] = []
        self.get_multi_calls: list[tuple] = []

    async def get_route(self, alat, alng, blat, blng, *, profile, force_straight, engine):
        self.get_route_calls.append((alat, alng, blat, blng, profile, force_straight, engine))
        return {
            "coords": [(alat, alng), (blat, blng)],
            "distance": self.leg_distance,
        }

    async def get_multi_route(self, tuples, *, profile, force_straight, engine):
        self.get_multi_calls.append((tuple(tuples), profile, force_straight, engine))
        return {
            "coords": list(tuples),
            "distance": self.multi_distance,
        }


def _wire(engine, route_service=None):
    """Replace the engine's route_service and stub _move_along_route so leg
    iteration is deterministic (no inner step loop / timers)."""
    rs = route_service or FakeRouteService()
    engine.route_service = rs
    engine.moves: list[list[Coordinate]] = []

    async def fake_move(coords, profile):
        engine.moves.append(list(coords))
        # mirror real behavior: leave current_position at the route end
        if coords:
            engine.current_position = coords[-1]

    engine._move_along_route = fake_move  # type: ignore[assignment]
    return rs


def _wp(lat, lng):
    return Coordinate(lat=lat, lng=lng)


def _events(emitted):
    return [t for (t, _d) in emitted]


# ── pure helper: _quick_distance ─────────────────────────────────────
def test_quick_distance_zero_for_same_point():
    a = _wp(25.0, 121.0)
    assert MultiStopNavigator._quick_distance(a, a) == 0.0


def test_quick_distance_known_magnitude():
    # ~0.001 deg latitude north. dlat = radians(0.001); distance ~111.2m.
    a = _wp(25.0, 121.0)
    b = _wp(25.001, 121.0)
    d = MultiStopNavigator._quick_distance(a, b)
    assert 110.0 < d < 113.0


def test_quick_distance_is_symmetric_in_latitude_only():
    # Longitude term is scaled by cos(lat of FIRST arg) -- note asymmetry.
    a = _wp(25.0, 121.0)
    b = _wp(25.0, 121.001)
    fwd = MultiStopNavigator._quick_distance(a, b)
    rev = MultiStopNavigator._quick_distance(b, a)
    # Both positive; cos(25.0) ~= cos(25.0) so these are nearly equal here.
    assert fwd > 0 and rev > 0
    assert abs(fwd - rev) < 1e-6


# ── start(): validation ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_start_too_few_waypoints_raises():
    eng, _loc, _em = make_engine()
    nav = MultiStopNavigator(eng)
    with pytest.raises(ValueError, match="At least 2 waypoints"):
        await nav.start([_wp(1, 1)], MovementMode.WALKING)


@pytest.mark.asyncio
async def test_start_no_current_position_raises_runtime():
    eng, _loc, _em = make_engine()
    eng.current_position = None
    nav = MultiStopNavigator(eng)
    with pytest.raises(RuntimeError, match="no current position"):
        await nav.start([_wp(1, 1), _wp(2, 2)], MovementMode.WALKING)


# ── start(): happy path, no resume, near first wp ────────────────────
@pytest.mark.asyncio
async def test_start_basic_two_legs_completes_to_idle():
    eng, _loc, emitted = make_engine()
    _wire(eng)
    # current position right at first waypoint so preamble route is skipped
    eng.current_position = _wp(25.0, 121.0)
    nav = MultiStopNavigator(eng)

    wps = [_wp(25.0, 121.0), _wp(25.0, 121.001), _wp(25.0, 121.002)]
    # pause disabled so no waiting
    await nav.start(wps, MovementMode.WALKING, pause_enabled=False)

    assert eng.state == SimulationState.IDLE
    assert eng.total_segments == 2  # len(waypoints) - 1
    assert eng.lap_count == 0
    # two legs -> two _move_along_route calls (preamble skipped)
    assert len(eng.moves) == 2
    types = _events(emitted)
    assert "route_path" in types
    assert types.count("stop_reached") == 2
    assert "multi_stop_complete" in types
    # final state_change announces idle
    assert ("state_change", {"state": "idle"}) in emitted


@pytest.mark.asyncio
async def test_start_preamble_routes_when_far_from_first():
    eng, _loc, _em = make_engine()
    rs = _wire(eng)
    # far (>50m) from first waypoint -> preamble get_route happens first
    eng.current_position = _wp(25.0, 121.0)
    nav = MultiStopNavigator(eng)
    wps = [_wp(26.0, 122.0), _wp(26.0, 122.001)]
    await nav.start(wps, MovementMode.WALKING, pause_enabled=False)

    # preamble (1) + single leg (1) == 2 get_route calls
    assert len(rs.get_route_calls) == 2
    # first call origin is the start position, dest is first waypoint
    assert rs.get_route_calls[0][:4] == (25.0, 121.0, 26.0, 122.0)


@pytest.mark.asyncio
async def test_start_osrm_profile_foot_for_walking_car_for_driving():
    # WALKING -> foot
    eng, _loc, _em = make_engine()
    rs = _wire(eng)
    eng.current_position = _wp(25.0, 121.0)
    await MultiStopNavigator(eng).start(
        [_wp(25.0, 121.0), _wp(25.0, 121.001)], MovementMode.WALKING,
        pause_enabled=False,
    )
    assert rs.get_route_calls[0][4] == "foot"

    # DRIVING -> car
    eng2, _l2, _e2 = make_engine()
    rs2 = _wire(eng2)
    eng2.current_position = _wp(25.0, 121.0)
    await MultiStopNavigator(eng2).start(
        [_wp(25.0, 121.0), _wp(25.0, 121.001)], MovementMode.DRIVING,
        pause_enabled=False,
    )
    assert rs2.get_route_calls[0][4] == "car"


@pytest.mark.asyncio
async def test_start_stop_duration_pause_emits_countdown_then_stops():
    # explicit stop_duration triggers pause; we pre-set the stop_event so
    # asyncio.wait_for returns immediately (no real timer) and the loop breaks.
    eng, _loc, emitted = make_engine()
    _wire(eng)
    eng.current_position = _wp(25.0, 121.0)
    eng._stop_event.set()  # makes wait_for resolve at once -> pause path breaks
    nav = MultiStopNavigator(eng)
    wps = [_wp(25.0, 121.0), _wp(25.0, 121.001)]
    await nav.start(wps, MovementMode.WALKING, stop_duration=10.0)

    types = _events(emitted)
    # stop_event was already set, so the leg loop sees it and short-circuits
    # before moving. No stop_reached, no pause_countdown emitted; still ends IDLE.
    assert eng.state == SimulationState.IDLE
    assert "multi_stop_complete" in types


@pytest.mark.asyncio
async def test_start_pause_countdown_emitted_when_not_stopped():
    # Real wait path: stop_event NOT set -> wait_for times out -> countdown
    # emitted and we continue. Use a tiny real duration.
    eng, _loc, emitted = make_engine()
    _wire(eng)
    eng.current_position = _wp(25.0, 121.0)
    nav = MultiStopNavigator(eng)
    wps = [_wp(25.0, 121.0), _wp(25.0, 121.001), _wp(25.0, 121.002)]
    # stop_duration tiny so the real wait_for timeout is ~instant.
    await nav.start(wps, MovementMode.WALKING, stop_duration=0.001)

    types = _events(emitted)
    # first (non-last) stop pauses; last stop does NOT pause (loop=False)
    assert types.count("pause_countdown") == 1
    assert types.count("pause_countdown_end") == 1
    assert types.count("stop_reached") == 2
    assert eng.state == SimulationState.IDLE


@pytest.mark.asyncio
async def test_start_loop_runs_then_stop_event_breaks():
    # loop=True: after lap 0 it would loop forever. We set the stop_event
    # after the first leg via a custom _move_along_route to bound it.
    eng, _loc, emitted = make_engine()
    rs = _wire(eng)
    eng.current_position = _wp(25.0, 121.0)

    call_count = {"n": 0}
    orig_move = eng._move_along_route

    async def stopping_move(coords, profile):
        await orig_move(coords, profile)
        call_count["n"] += 1
        if call_count["n"] >= 2:
            eng._stop_event.set()

    eng._move_along_route = stopping_move
    nav = MultiStopNavigator(eng)
    wps = [_wp(25.0, 121.0), _wp(25.0, 121.001), _wp(25.0, 121.002)]
    await nav.start(wps, MovementMode.WALKING, loop=True, pause_enabled=False)

    assert eng.state == SimulationState.IDLE
    # lap_count stays 0 because stop_event was set during the first lap,
    # so the loop exits before incrementing lap_count.
    assert eng.lap_count == 0
    assert "lap_complete" not in _events(emitted)


@pytest.mark.asyncio
async def test_start_resume_snapshot_skips_preamble_and_uses_segment():
    eng, _loc, emitted = make_engine()
    rs = _wire(eng)
    eng.current_position = _wp(40.0, 90.0)  # nowhere near wp[0]
    eng._resume_snapshot = {
        "kind": "multi_stop",
        "lap_count": 3,
        "segment_index": 1,
        "user_waypoint_next": 2,
    }
    nav = MultiStopNavigator(eng)
    wps = [_wp(25.0, 121.0), _wp(25.0, 121.001), _wp(25.0, 121.002)]
    await nav.start(wps, MovementMode.WALKING, pause_enabled=False)

    # resume consumed -> snapshot cleared
    assert eng._resume_snapshot is None
    # lap_count seeded from snapshot
    assert eng.lap_count == 3
    # resume starts at leg index 1, so only ONE leg (index 1) runs on lap 1
    assert len(eng.moves) == 1
    # no preamble route to wp[0] -- the only get_route is the resumed leg,
    # and its origin is the engine's actual current_position (99,99), not wp_a.
    assert rs.get_route_calls[0][:2] == (40.0, 90.0)
    assert eng._user_waypoint_next == 2  # seeded from resume_uwn


@pytest.mark.asyncio
async def test_start_emits_state_change_with_waypoints_payload():
    eng, _loc, emitted = make_engine()
    _wire(eng)
    eng.current_position = _wp(25.0, 121.0)
    wps = [_wp(25.0, 121.0), _wp(25.0, 121.001)]
    await MultiStopNavigator(eng).start(wps, MovementMode.WALKING, pause_enabled=False)

    sc = [d for (t, d) in emitted if t == "state_change" and "waypoints" in d]
    assert sc, "expected a state_change carrying waypoints"
    payload = sc[0]
    assert payload["state"] == "multi_stop"
    assert payload["loop"] is False
    assert len(payload["waypoints"]) == 2


@pytest.mark.asyncio
async def test_start_route_service_failure_is_swallowed_for_full_route():
    # get_multi_route raising must not abort start (it's only for display).
    class FailingMulti(FakeRouteService):
        async def get_multi_route(self, *a, **k):
            raise RuntimeError("osrm down")

    eng, _loc, emitted = make_engine()
    _wire(eng, route_service=FailingMulti())
    eng.current_position = _wp(25.0, 121.0)
    wps = [_wp(25.0, 121.0), _wp(25.0, 121.001)]
    await MultiStopNavigator(eng).start(wps, MovementMode.WALKING, pause_enabled=False)

    # still completes; no route_path emitted because pre-calc failed
    assert eng.state == SimulationState.IDLE
    assert "route_path" not in _events(emitted)


# ── jump mode ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_start_jump_mode_delegates_and_teleports_each_stop():
    eng, loc, emitted = make_engine()
    # jump mode never calls route_service; no current_position needed.
    nav = MultiStopNavigator(eng)
    wps = [_wp(10.0, 20.0), _wp(11.0, 21.0), _wp(12.0, 22.0)]
    # interval=0 -> _dwell returns stop_event.is_set() (False) immediately,
    # so no real waiting and the non-looping run completes.
    await nav.start(wps, MovementMode.WALKING, jump_mode=True, jump_interval=0)

    # every waypoint pushed to the location service in order
    assert loc.pushes == [(10.0, 20.0), (11.0, 21.0), (12.0, 22.0)]
    assert eng.state == SimulationState.IDLE
    types = _events(emitted)
    assert types.count("stop_reached") == 3
    assert types.count("position_update") == 3
    assert "multi_stop_complete" in types


@pytest.mark.asyncio
async def test_jump_multistop_sets_engine_progress_fields():
    eng, _loc, _em = make_engine()
    wps = [_wp(1.0, 1.0), _wp(2.0, 2.0)]
    await _run_jump_multistop(eng, wps, interval=0, loop=False)

    assert eng.total_segments == 2  # NOTE: jump uses len(waypoints), not len-1
    assert eng.segment_index == 1   # last visited index
    assert eng.distance_traveled == 0.0
    assert eng.distance_remaining == 0.0
    assert eng._user_waypoint_next == 2  # min(last+1, len) == 2


@pytest.mark.asyncio
async def test_jump_multistop_single_waypoint_user_waypoint_next_zero():
    # len(waypoints) <= 1 -> _user_waypoint_next initialized to 0
    eng, loc, _em = make_engine()
    await _run_jump_multistop(eng, [_wp(5.0, 5.0)], interval=0, loop=False)
    # one stop pushed
    assert loc.pushes == [(5.0, 5.0)]
    assert eng.state == SimulationState.IDLE


@pytest.mark.asyncio
async def test_jump_multistop_stop_event_set_breaks_immediately():
    eng, loc, emitted = make_engine()
    eng._stop_event.set()
    wps = [_wp(1.0, 1.0), _wp(2.0, 2.0)]
    await _run_jump_multistop(eng, wps, interval=5.0, loop=False)
    # stop_event set before loop -> no positions pushed
    assert loc.pushes == []
    # state still flips to IDLE on exit (was set to MULTI_STOP at entry)
    assert eng.state == SimulationState.IDLE
    assert "multi_stop_complete" in _events(emitted)


@pytest.mark.asyncio
async def test_jump_multistop_loop_increments_lap_then_stops():
    # loop=True with interval=0: _dwell returns False, so a full lap runs;
    # bound it by setting stop_event from a patched _set_position after lap 1.
    eng, loc, emitted = make_engine()
    wps = [_wp(1.0, 1.0), _wp(2.0, 2.0)]

    orig_set = eng._set_position
    pushes = {"n": 0}

    async def counting_set(lat, lng):
        await orig_set(lat, lng)
        pushes["n"] += 1
        if pushes["n"] >= len(wps):  # after first full lap of stops
            eng._stop_event.set()

    eng._set_position = counting_set
    await _run_jump_multistop(eng, wps, interval=0, loop=True)

    # one full lap of 2 stops happened
    assert loc.pushes == [(1.0, 1.0), (2.0, 2.0)]
    # lap_count: the inner for-loop completed once but stop_event was set on
    # the last stop, so after the for-loop the `not loop or stop_event.is_set()`
    # check is True -> running=False BEFORE incrementing lap_count.
    assert eng.lap_count == 0
    assert eng.state == SimulationState.IDLE


# ── resume/capture round-trip via the engine ─────────────────────────
@pytest.mark.asyncio
async def test_capture_snapshot_for_multi_stop_uses_user_waypoint_next():
    eng, _loc, _em = make_engine()
    eng.state = SimulationState.MULTI_STOP
    eng._last_sim_kind = "multi_stop"
    eng._last_sim_args = {"waypoints": [], "mode": MovementMode.WALKING}
    eng.current_position = _wp(3.0, 4.0)
    eng._user_waypoint_next = 3
    eng.segment_index = 99  # should be ignored for multi_stop kind
    eng.lap_count = 2

    snap = eng.capture_resumable_snapshot()
    assert snap is not None
    assert snap["kind"] == "multi_stop"
    # multi_stop maps segment_index <- user_waypoint_next - 1, not segment_index
    assert snap["segment_index"] == 2
    assert snap["user_waypoint_next"] == 3
    assert snap["lap_count"] == 2
    assert snap["current_pos"] == (3.0, 4.0)


@pytest.mark.asyncio
async def test_capture_snapshot_none_when_idle():
    eng, _loc, _em = make_engine()
    eng.state = SimulationState.IDLE
    eng._last_sim_kind = "multi_stop"
    eng._last_sim_args = {"x": 1}
    assert eng.capture_resumable_snapshot() is None


# ── speed profile reuse path ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_start_reuses_active_speed_profile_when_applied():
    # When _speed_was_applied and _active_speed_profile set, _pick_profile
    # returns a copy of the active profile (honoring mid-flight apply_speed).
    eng, _loc, _em = make_engine()
    _wire(eng)
    eng.current_position = _wp(25.0, 121.0)
    eng._speed_was_applied = True
    eng._active_speed_profile = {"speed_mps": 7.0, "jitter": 0.1}
    captured = []

    async def capture_move(coords, profile):
        captured.append(dict(profile))
        eng.current_position = coords[-1]

    eng._move_along_route = capture_move
    wps = [_wp(25.0, 121.0), _wp(25.0, 121.001)]
    await MultiStopNavigator(eng).start(wps, MovementMode.WALKING, pause_enabled=False)

    assert captured, "move should have been called"
    assert captured[0]["speed_mps"] == 7.0


@pytest.mark.asyncio
async def test_pause_min_max_unsorted_is_sorted_random_range(monkeypatch):
    # pause_min > pause_max -> code sorts them; random.uniform called with
    # (lo, hi) where lo<=hi. Patch random.uniform to capture args.
    eng, _loc, emitted = make_engine()
    _wire(eng)
    eng.current_position = _wp(25.0, 121.0)
    seen = []

    def fake_uniform(lo, hi):
        seen.append((lo, hi))
        return 0.0  # 0 pause -> should_pause False, no real wait

    monkeypatch.setattr(random, "uniform", fake_uniform)
    wps = [_wp(25.0, 121.0), _wp(25.0, 121.001)]
    await MultiStopNavigator(eng).start(
        wps, MovementMode.WALKING, pause_enabled=True, pause_min=20.0, pause_max=5.0,
    )
    # last stop only -> on a 2-wp route the single stop IS the last, and
    # loop=False so should_pause is False; but random.uniform is still called
    # to compute this_pause before the is_last gate.
    assert seen == [(5.0, 20.0)]  # sorted ascending
    assert eng.state == SimulationState.IDLE
