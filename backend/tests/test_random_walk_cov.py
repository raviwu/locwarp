"""Characterization tests for core/random_walk.py (RandomWalkHandler).

Freezes the ACTUAL current behavior of the random-walk handler. Randomness is
made deterministic by passing an explicit seed (the handler builds a
random.Random(seed)) and by seeding the global random module for unseeded
paths. The OSRM route fetch and the per-leg mover are mocked so the loop runs
deterministically; termination is forced by setting the engine's _stop_event
from inside a mocked collaborator.

A KEY observed behavior pinned here: when _stop_event becomes set DURING a
leg's move, the handler's post-move `if engine._stop_event.is_set(): break`
fires BEFORE walk_count is incremented and `random_walk_arrived` is emitted.
To freeze the clean-arrival path instead, get_route returns a valid route for
the first N legs (each fully completes + emits arrival), then on call N+1 it
sets the stop event AND returns a 1-point (too-short) route so the loop hits
its short-route `continue` and exits cleanly at the while-condition check.

core.random_walk.asyncio.sleep is patched to a no-op (autouse fixture) so the
short-route 0.5s sleep and the error-backoff sleeps don't slow the suite.

No source files are modified; tests assert real observed values.
"""
from __future__ import annotations

import asyncio
import math
import random

import pytest

from models.schemas import Coordinate, MovementMode, SimulationState
from services.interpolator import RouteInterpolator
from tests._engine_harness import make_engine

import core.random_walk as rw


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _noop_sleep(monkeypatch):
    """Neutralize real asyncio.sleep inside the handler module."""
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(rw.asyncio, "sleep", fake_sleep)
    return sleeps


def _route_payload(coords, distance=42.0):
    return {"coords": coords, "distance": distance}


def _install_route_then_stop(engine, coords, n_legs, distance=42.0):
    """get_route returns a valid route for the first n_legs calls; on call
    n_legs+1 it sets the stop event and returns a short (1-point) route."""
    calls = []

    async def fake_get_route(slat, slng, dlat, dlng, *, profile, force_straight, engine=None, **kw):
        calls.append({
            "slat": slat, "slng": slng, "dlat": dlat, "dlng": dlng,
            "profile": profile, "force_straight": force_straight,
            "engine": engine,
        })
        if len(calls) > n_legs:
            target._stop_event.set()
            return _route_payload([[slat, slng]], distance)  # too short -> continue
        return _route_payload(coords, distance)

    target = engine
    engine.route_service.get_route = fake_get_route  # type: ignore[assignment]
    return calls


def _install_mover(engine):
    """Mock _move_along_route to record calls (never stops the walk itself)."""
    moves = []

    async def fake_move(coords, speed_profile):
        moves.append({"coords": coords, "speed_profile": speed_profile})

    engine._move_along_route = fake_move  # type: ignore[assignment]
    return moves


# ===========================================================================
# Pure helper: RouteInterpolator.random_point_in_radius (drives the walk)
# ===========================================================================

def test_random_point_in_radius_is_deterministic_with_seed():
    rng = random.Random(1234)
    p1 = RouteInterpolator.random_point_in_radius(25.0, 121.0, 500.0, rng=rng)
    rng2 = random.Random(1234)
    p2 = RouteInterpolator.random_point_in_radius(25.0, 121.0, 500.0, rng=rng2)
    assert p1 == p2
    # Pin the REAL observed first value for this seed (area sqrt-trick +
    # move_point haversine projection).
    assert p1[0] == pytest.approx(25.002919125392516, abs=1e-9)
    assert p1[1] == pytest.approx(120.99931085074311, abs=1e-9)


def test_random_point_in_radius_sequence_advances_rng():
    rng = random.Random(7)
    a = RouteInterpolator.random_point_in_radius(0.0, 0.0, 100.0, rng=rng)
    b = RouteInterpolator.random_point_in_radius(0.0, 0.0, 100.0, rng=rng)
    assert a != b


def test_random_point_in_radius_stays_within_radius():
    rng = random.Random(99)
    center_lat, center_lng, radius_m = 25.0375, 121.5637, 800.0
    _R = 6371000.0
    for _ in range(500):
        lat, lng = RouteInterpolator.random_point_in_radius(
            center_lat, center_lng, radius_m, rng=rng,
        )
        dlat = math.radians(lat - center_lat)
        dlng = math.radians(lng - center_lng)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(center_lat))
            * math.cos(math.radians(lat))
            * math.sin(dlng / 2) ** 2
        )
        dist = 2 * _R * math.asin(math.sqrt(a))
        assert dist <= radius_m + 1e-6


def test_random_point_zero_radius_returns_center():
    rng = random.Random(3)
    lat, lng = RouteInterpolator.random_point_in_radius(10.0, 20.0, 0.0, rng=rng)
    assert lat == pytest.approx(10.0, abs=1e-12)
    assert lng == pytest.approx(20.0, abs=1e-12)


# ===========================================================================
# Async handler tests
# ===========================================================================

@pytest.mark.asyncio
async def test_start_without_position_raises():
    eng, _loc, _emitted = make_engine()
    eng.current_position = None
    with pytest.raises(RuntimeError, match="no current position"):
        await eng._random_walk.start(
            Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.WALKING,
        )


@pytest.mark.asyncio
async def test_single_leg_emits_and_completes_no_pause():
    eng, _loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)

    coords = [[25.0, 121.0], [25.001, 121.001]]
    route_calls = _install_route_then_stop(eng, coords, n_legs=1, distance=77.0)
    moves = _install_mover(eng)

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.WALKING,
        pause_enabled=False, seed=42,
    )

    assert eng.state == SimulationState.IDLE

    types = [t for (t, _d) in emitted]
    assert types[0] == "state_change"
    assert emitted[0][1]["state"] == "random_walk"
    assert emitted[0][1]["center"] == {"lat": 25.0, "lng": 121.0}
    assert emitted[0][1]["radius_m"] == 500.0
    assert "route_path" in types
    assert "random_walk_arrived" in types
    assert types[-2:] == ["random_walk_complete", "state_change"]
    assert emitted[-1][1] == {"state": "idle"}

    arrived = next(d for (t, d) in emitted if t == "random_walk_arrived")
    assert arrived["count"] == 1
    complete = next(d for (t, d) in emitted if t == "random_walk_complete")
    assert complete["destinations_visited"] == 1

    # 2 route fetches (leg 1 + the stop-triggering short route); 1 actual move.
    assert len(route_calls) == 2
    assert route_calls[0]["profile"] == "foot"
    assert len(moves) == 1
    assert eng.distance_remaining == 77.0
    assert eng.lap_count == 1
    assert eng._random_walk_count == 1


@pytest.mark.asyncio
async def test_arrived_dest_matches_seeded_random_point():
    eng, _loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)
    _install_route_then_stop(eng, [[25.0, 121.0], [25.001, 121.001]], n_legs=1)
    _install_mover(eng)

    rng_expected = random.Random(2024)
    exp_lat, exp_lng = RouteInterpolator.random_point_in_radius(
        25.0, 121.0, 300.0, rng=rng_expected,
    )

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 300.0, MovementMode.WALKING,
        pause_enabled=False, seed=2024,
    )

    arrived = next(d for (t, d) in emitted if t == "random_walk_arrived")
    assert arrived["lat"] == pytest.approx(exp_lat, abs=1e-12)
    assert arrived["lng"] == pytest.approx(exp_lng, abs=1e-12)


@pytest.mark.asyncio
async def test_two_legs_increment_counts():
    eng, _loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)
    _install_route_then_stop(eng, [[25.0, 121.0], [25.001, 121.001]], n_legs=2)
    moves = _install_mover(eng)

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.WALKING,
        pause_enabled=False, seed=1,
    )

    arrived = [d for (t, d) in emitted if t == "random_walk_arrived"]
    assert [a["count"] for a in arrived] == [1, 2]
    assert len(moves) == 2
    assert eng.lap_count == 2
    complete = next(d for (t, d) in emitted if t == "random_walk_complete")
    assert complete["destinations_visited"] == 2


@pytest.mark.asyncio
async def test_driving_mode_uses_car_profile():
    eng, _loc, _emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)
    route_calls = _install_route_then_stop(eng, [[25.0, 121.0], [25.001, 121.001]], n_legs=1)
    _install_mover(eng)

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.DRIVING,
        pause_enabled=False, seed=1,
    )
    assert route_calls[0]["profile"] == "car"


@pytest.mark.asyncio
async def test_running_mode_uses_foot_profile():
    eng, _loc, _emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)
    route_calls = _install_route_then_stop(eng, [[25.0, 121.0], [25.001, 121.001]], n_legs=1)
    _install_mover(eng)

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.RUNNING,
        pause_enabled=False, seed=1,
    )
    assert route_calls[0]["profile"] == "foot"


@pytest.mark.asyncio
async def test_straight_line_and_route_engine_forwarded():
    eng, _loc, _emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)
    route_calls = _install_route_then_stop(eng, [[25.0, 121.0], [25.001, 121.001]], n_legs=1)
    _install_mover(eng)

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.WALKING,
        pause_enabled=False, seed=1,
        straight_line=True, route_engine="osrm",
    )
    assert route_calls[0]["force_straight"] is True
    assert route_calls[0]["engine"] == "osrm"


@pytest.mark.asyncio
async def test_short_route_skips_move_and_continues(_noop_sleep):
    """First leg returns a too-short route (no move/arrival); second returns a
    valid one (move + arrival), then the third call stops the walk."""
    eng, _loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)

    seq = [
        [[25.0, 121.0]],                      # too short -> skip move, sleep, continue
        [[25.0, 121.0], [25.001, 121.001]],   # valid -> move + arrival
    ]
    idx = {"i": 0}

    async def fake_get_route(slat, slng, dlat, dlng, *, profile, force_straight, engine=None, **kw):
        i = idx["i"]
        idx["i"] += 1
        if i < len(seq):
            return _route_payload(seq[i])
        eng._stop_event.set()
        return _route_payload([[slat, slng]])

    eng.route_service.get_route = fake_get_route  # type: ignore[assignment]
    moves = _install_mover(eng)

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.WALKING,
        pause_enabled=False, seed=5,
    )

    # short route -> a 0.5s sleep was recorded; only ONE real move happened.
    assert 0.5 in _noop_sleep
    assert len(moves) == 1
    arrived = [d for (t, d) in emitted if t == "random_walk_arrived"]
    assert len(arrived) == 1
    assert arrived[0]["count"] == 1


@pytest.mark.asyncio
async def test_too_many_generic_errors_stops_walk(_noop_sleep):
    eng, _loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)

    async def boom(*a, **kw):
        raise ValueError("route blew up")

    eng.route_service.get_route = boom  # type: ignore[assignment]

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.WALKING,
        pause_enabled=False, seed=1,
    )

    # 5 consecutive errors -> break. First 4 sleep(1.0); the 5th breaks before sleeping.
    assert _noop_sleep == [1.0, 1.0, 1.0, 1.0]
    complete = next(d for (t, d) in emitted if t == "random_walk_complete")
    assert complete["destinations_visited"] == 0
    assert eng.state == SimulationState.IDLE


@pytest.mark.asyncio
async def test_connection_error_emits_connection_lost_then_user_stops(monkeypatch):
    eng, _loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)

    async def conn_drop(*a, **kw):
        raise ConnectionError("wifi dropped")

    eng.route_service.get_route = conn_drop  # type: ignore[assignment]

    # The loop top checks `while not stop_event.is_set()`, so we can't pre-set
    # stop. Instead patch wait_for to set the stop event and return -> the
    # handler's `break` after the wait fires.
    async def fake_wait_for(awaitable, timeout):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        eng._stop_event.set()
        return None

    monkeypatch.setattr(rw.asyncio, "wait_for", fake_wait_for)

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.WALKING,
        pause_enabled=False, seed=1,
    )

    conn = [d for (t, d) in emitted if t == "connection_lost"]
    assert len(conn) == 1
    assert conn[0]["retry"] == 1
    assert conn[0]["max_retries"] == 60
    assert conn[0]["next_retry_seconds"] == 5.0
    assert eng.state == SimulationState.IDLE


@pytest.mark.asyncio
async def test_connection_error_backoff_growth_until_max_retries(monkeypatch):
    """Stop event never set; wait_for is patched to raise TimeoutError so the
    loop keeps retrying until max_consecutive_conn_errors (60)."""
    eng, _loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)

    async def conn_drop(*a, **kw):
        raise ConnectionError("wifi dropped")

    eng.route_service.get_route = conn_drop  # type: ignore[assignment]

    async def fake_wait_for(awaitable, timeout):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(rw.asyncio, "wait_for", fake_wait_for)

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.WALKING,
        pause_enabled=False, seed=1,
    )

    conn = [d for (t, d) in emitted if t == "connection_lost"]
    # Emits for retries 1..59; the 60th hits the limit and breaks before emit.
    assert len(conn) == 59
    assert conn[0]["next_retry_seconds"] == 5.0
    # Backoff caps at 30.0s.
    assert conn[-1]["next_retry_seconds"] == 30.0
    assert conn[-1]["retry"] == 59
    assert eng.state == SimulationState.IDLE


@pytest.mark.asyncio
async def test_pause_then_stop_during_pause_breaks(monkeypatch):
    eng, _loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)
    _install_route_then_stop(eng, [[25.0, 121.0], [25.001, 121.001]], n_legs=99)
    _install_mover(eng)

    async def fake_wait_for(awaitable, timeout):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        return None  # simulate stop_event firing during the pause -> break

    monkeypatch.setattr(rw.asyncio, "wait_for", fake_wait_for)

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.WALKING,
        pause_enabled=True, pause_min=5.0, pause_max=20.0, seed=1,
    )

    types = [t for (t, _d) in emitted]
    assert "pause_countdown" in types
    # Stop-during-pause breaks BEFORE pause_countdown_end.
    assert "pause_countdown_end" not in types
    pc = next(d for (t, d) in emitted if t == "pause_countdown")
    assert pc["source"] == "random_walk"
    assert 5.0 <= pc["duration_seconds"] <= 20.0
    assert eng.state == SimulationState.IDLE


@pytest.mark.asyncio
async def test_pause_completes_then_next_leg_with_negative_lo_clamp(monkeypatch):
    """Pause elapses normally (wait_for TimeoutError) -> pause_countdown_end is
    emitted and the next leg is picked. pause_min<0 is clamped to 0.0 so the
    uniform draw is in [0, hi]."""
    eng, _loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)
    # 2 valid legs, then stop on the 3rd route fetch.
    _install_route_then_stop(eng, [[25.0, 121.0], [25.001, 121.001]], n_legs=2)
    _install_mover(eng)

    async def fake_wait_for(awaitable, timeout):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        raise asyncio.TimeoutError  # pause elapses normally

    monkeypatch.setattr(rw.asyncio, "wait_for", fake_wait_for)

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.WALKING,
        pause_enabled=True, pause_min=-5.0, pause_max=10.0, seed=1,
    )

    types = [t for (t, _d) in emitted]
    # First leg's pause ran to completion -> end event present.
    assert "pause_countdown_end" in types
    pcs = [d for (t, d) in emitted if t == "pause_countdown"]
    # Two arrivals -> at least one full pause cycle; durations clamped to [0,10].
    assert len(pcs) >= 1
    for pc in pcs:
        assert 0.0 <= pc["duration_seconds"] <= 10.0
    assert eng.state == SimulationState.IDLE


@pytest.mark.asyncio
async def test_pause_disabled_when_both_bounds_nonpositive():
    eng, _loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)
    _install_route_then_stop(eng, [[25.0, 121.0], [25.001, 121.001]], n_legs=1)
    _install_mover(eng)

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.WALKING,
        pause_enabled=True, pause_min=0.0, pause_max=0.0, seed=1,
    )

    types = [t for (t, _d) in emitted]
    assert "pause_countdown" not in types
    assert eng.state == SimulationState.IDLE


@pytest.mark.asyncio
async def test_resume_snapshot_fast_forwards_rng():
    eng, _loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)
    _install_route_then_stop(eng, [[25.0, 121.0], [25.001, 121.001]], n_legs=1)
    _install_mover(eng)

    center = Coordinate(lat=25.0, lng=121.0)
    radius = 400.0
    seed = 555
    eng._resume_snapshot = {"kind": "random_walk", "random_walk_count": 2}

    rng_expected = random.Random(seed)
    RouteInterpolator.random_point_in_radius(25.0, 121.0, radius, rng=rng_expected)
    RouteInterpolator.random_point_in_radius(25.0, 121.0, radius, rng=rng_expected)
    exp_lat, exp_lng = RouteInterpolator.random_point_in_radius(
        25.0, 121.0, radius, rng=rng_expected,
    )

    await eng._random_walk.start(
        center, radius, MovementMode.WALKING,
        pause_enabled=False, seed=seed,
    )

    arrived = next(d for (t, d) in emitted if t == "random_walk_arrived")
    assert arrived["lat"] == pytest.approx(exp_lat, abs=1e-12)
    assert arrived["lng"] == pytest.approx(exp_lng, abs=1e-12)
    # Snapshot consumed on entry.
    assert eng._resume_snapshot is None
    # walk_count resumed from 2 -> first completed leg makes it 3.
    assert eng._random_walk_count == 3
    assert arrived["count"] == 3


@pytest.mark.asyncio
async def test_unseeded_walk_uses_global_random():
    eng, _loc, emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)
    _install_route_then_stop(eng, [[25.0, 121.0], [25.001, 121.001]], n_legs=1)
    _install_mover(eng)

    # Seed the GLOBAL random module so the unseeded path is deterministic.
    random.seed(123456)
    exp_lat, exp_lng = RouteInterpolator.random_point_in_radius(
        25.0, 121.0, 250.0, rng=None,
    )

    random.seed(123456)
    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 250.0, MovementMode.WALKING,
        pause_enabled=False, seed=None,  # unseeded -> global random
    )

    arrived = next(d for (t, d) in emitted if t == "random_walk_arrived")
    assert arrived["lat"] == pytest.approx(exp_lat, abs=1e-12)
    assert arrived["lng"] == pytest.approx(exp_lng, abs=1e-12)


@pytest.mark.asyncio
async def test_applied_speed_profile_honored_on_each_leg():
    eng, _loc, _emitted = make_engine()
    eng.current_position = Coordinate(lat=25.0, lng=121.0)
    _install_route_then_stop(eng, [[25.0, 121.0], [25.001, 121.001]], n_legs=1)
    moves = _install_mover(eng)

    applied = {"min_speed_mps": 1.23, "max_speed_mps": 4.56}
    eng._speed_was_applied = True
    eng._active_speed_profile = applied

    await eng._random_walk.start(
        Coordinate(lat=25.0, lng=121.0), 500.0, MovementMode.WALKING,
        pause_enabled=False, seed=1,
    )

    # Mover received a COPY of the active applied profile (dict(...)).
    assert moves[0]["speed_profile"] == applied
    assert moves[0]["speed_profile"] is not applied
    # Random walk clears named waypoints / highlight index.
    assert eng._user_waypoints == []
    assert eng._user_waypoint_next == 0
