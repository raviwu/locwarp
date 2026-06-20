"""Characterization tests for core.navigator.Navigator.

These freeze the *current* behavior of single-destination navigation.
The engine's real ``_move_along_route`` inter-tick wait loop is
non-deterministic, so we stub it (and ``_set_position`` / ``route_service``)
to drive only the navigator's own logic: route fetch, segment/state setup,
event emission, the <2-point teleport fallback, and the completion epilogue.
"""
from __future__ import annotations

import pytest

from core.navigator import Navigator
from models.schemas import Coordinate, MovementMode, SimulationState
from config import SPEED_PROFILES
from tests._engine_harness import make_engine


def _wire(engine):
    """Replace the engine collaborators the navigator touches with fakes.

    Returns a dict of recorders so tests can assert on the interactions.
    """
    rec = {
        "route_args": None,
        "route_kwargs": None,
        "route_return": {"coords": [[0.0, 0.0], [1.0, 1.0]], "distance": 1234.0},
        "move_calls": [],
        "set_position_calls": [],
    }

    class FakeRouteService:
        async def get_route(self, *args, **kwargs):
            rec["route_args"] = args
            rec["route_kwargs"] = kwargs
            return rec["route_return"]

    engine.route_service = FakeRouteService()

    async def fake_move(coords, speed_profile):
        rec["move_calls"].append((list(coords), dict(speed_profile)))

    engine._move_along_route = fake_move

    async def fake_set_position(lat, lng):
        rec["set_position_calls"].append((lat, lng))
        engine.current_position = Coordinate(lat=lat, lng=lng)

    engine._set_position = fake_set_position

    return rec


# --------------------------------------------------------------------------
# guard: no current position
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_navigate_without_position_raises():
    engine, _loc, _emitted = make_engine()
    engine.current_position = None
    nav = Navigator(engine)
    with pytest.raises(RuntimeError, match="no current position"):
        await nav.navigate_to(Coordinate(lat=1.0, lng=2.0), MovementMode.WALKING)


# --------------------------------------------------------------------------
# happy path: route with >= 2 coords
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_navigate_happy_path_sets_state_and_segments():
    engine, _loc, emitted = make_engine()
    engine.current_position = Coordinate(lat=10.0, lng=20.0)
    rec = _wire(engine)
    rec["route_return"] = {
        "coords": [[10.0, 20.0], [10.5, 20.5], [11.0, 21.0]],
        "distance": 5000.0,
    }
    nav = Navigator(engine)

    dest = Coordinate(lat=11.0, lng=21.0)
    await nav.navigate_to(dest, MovementMode.WALKING)

    # 3 coords -> 2 segments; counters reset
    assert engine.total_segments == 2
    assert engine.segment_index == 0
    assert engine.distance_traveled == 0.0
    assert engine.distance_remaining == 5000.0
    # finished -> IDLE (move stub did not change state)
    assert engine.state == SimulationState.IDLE
    # move loop delegated once with the densified coords
    assert len(rec["move_calls"]) == 1
    moved_coords, profile = rec["move_calls"][0]
    assert len(moved_coords) == 3
    assert all(isinstance(c, Coordinate) for c in moved_coords)
    # walking default profile passed through
    assert profile == SPEED_PROFILES["walking"]


@pytest.mark.asyncio
async def test_navigate_emits_expected_event_sequence():
    engine, _loc, emitted = make_engine()
    engine.current_position = Coordinate(lat=0.0, lng=0.0)
    _wire(engine)
    nav = Navigator(engine)

    dest = Coordinate(lat=1.0, lng=1.0)
    await nav.navigate_to(dest, MovementMode.WALKING)

    types = [t for t, _ in emitted]
    # route_path, the NAVIGATING state_change, then completion epilogue
    assert types == [
        "route_path",
        "state_change",
        "navigation_complete",
        "state_change",
    ]

    # route_path carries the coord list
    rp = emitted[0][1]
    assert rp["coords"] == [{"lat": 0.0, "lng": 0.0}, {"lat": 1.0, "lng": 1.0}]

    # first state_change announces NAVIGATING + destination
    sc1 = emitted[1][1]
    assert sc1["state"] == "navigating"
    assert sc1["destination"] == {"lat": 1.0, "lng": 1.0}

    # navigation_complete carries destination
    assert emitted[2][1] == {"destination": {"lat": 1.0, "lng": 1.0}}

    # final state_change is back to IDLE
    assert emitted[3][1] == {"state": "idle"}


@pytest.mark.asyncio
async def test_navigate_sets_user_waypoints_start_and_dest():
    engine, _loc, _emitted = make_engine()
    start = Coordinate(lat=2.0, lng=3.0)
    engine.current_position = start
    _wire(engine)
    nav = Navigator(engine)

    dest = Coordinate(lat=9.0, lng=8.0)
    await nav.navigate_to(dest, MovementMode.RUNNING)

    assert engine._user_waypoints == [start, dest]
    assert engine._user_waypoint_next == 1


# --------------------------------------------------------------------------
# OSRM profile mapping + speed profile selection
# --------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected_osrm,expected_profile_key",
    [
        (MovementMode.WALKING, "foot", "walking"),
        (MovementMode.RUNNING, "foot", "running"),
        (MovementMode.DRIVING, "car", "driving"),
    ],
)
async def test_navigate_osrm_profile_and_speed_mapping(
    mode, expected_osrm, expected_profile_key
):
    engine, _loc, _emitted = make_engine()
    engine.current_position = Coordinate(lat=0.0, lng=0.0)
    rec = _wire(engine)
    nav = Navigator(engine)

    await nav.navigate_to(Coordinate(lat=1.0, lng=1.0), mode)

    assert rec["route_kwargs"]["profile"] == expected_osrm
    _coords, profile = rec["move_calls"][0]
    assert profile == SPEED_PROFILES[expected_profile_key]


@pytest.mark.asyncio
async def test_navigate_passes_route_args_and_flags():
    engine, _loc, _emitted = make_engine()
    engine.current_position = Coordinate(lat=5.0, lng=6.0)
    rec = _wire(engine)
    nav = Navigator(engine)

    dest = Coordinate(lat=7.0, lng=8.0)
    await nav.navigate_to(
        dest, MovementMode.DRIVING,
        straight_line=True, route_engine="osrm",
    )

    # positional: start.lat, start.lng, dest.lat, dest.lng
    assert rec["route_args"] == (5.0, 6.0, 7.0, 8.0)
    assert rec["route_kwargs"]["force_straight"] is True
    assert rec["route_kwargs"]["engine"] == "osrm"
    assert rec["route_kwargs"]["profile"] == "car"


@pytest.mark.asyncio
async def test_navigate_custom_fixed_speed_overrides_default():
    engine, _loc, _emitted = make_engine()
    engine.current_position = Coordinate(lat=0.0, lng=0.0)
    rec = _wire(engine)
    nav = Navigator(engine)

    await nav.navigate_to(
        Coordinate(lat=1.0, lng=1.0), MovementMode.WALKING, speed_kmh=36.0,
    )

    _coords, profile = rec["move_calls"][0]
    # 36 km/h -> 10 m/s; not the walking default
    assert profile["speed_mps"] == pytest.approx(10.0)
    assert profile != SPEED_PROFILES["walking"]


# --------------------------------------------------------------------------
# teleport fallback: route returns < 2 points
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_navigate_short_route_teleports_and_returns():
    engine, _loc, emitted = make_engine()
    engine.current_position = Coordinate(lat=0.0, lng=0.0)
    rec = _wire(engine)
    rec["route_return"] = {"coords": [[3.0, 4.0]], "distance": 0.0}
    nav = Navigator(engine)

    dest = Coordinate(lat=3.0, lng=4.0)
    await nav.navigate_to(dest, MovementMode.WALKING)

    # teleported to dest, no move loop, no state transition events
    assert rec["set_position_calls"] == [(3.0, 4.0)]
    assert rec["move_calls"] == []
    # state untouched (stays IDLE), no route_path / state_change emitted
    assert engine.state == SimulationState.IDLE
    assert emitted == []
    # segment counters never set up
    assert engine.total_segments == 0


@pytest.mark.asyncio
async def test_navigate_empty_route_teleports():
    engine, _loc, _emitted = make_engine()
    engine.current_position = Coordinate(lat=0.0, lng=0.0)
    rec = _wire(engine)
    rec["route_return"] = {"coords": [], "distance": 0.0}
    nav = Navigator(engine)

    dest = Coordinate(lat=1.0, lng=2.0)
    await nav.navigate_to(dest, MovementMode.WALKING)

    assert rec["set_position_calls"] == [(1.0, 2.0)]
    assert rec["move_calls"] == []


# --------------------------------------------------------------------------
# completion epilogue: only fires if still NAVIGATING after move loop
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_navigate_no_completion_if_move_loop_left_non_navigating():
    """If the move loop ends in a non-NAVIGATING state (e.g. stopped),
    the navigator does NOT force IDLE or emit completion events."""
    engine, _loc, emitted = make_engine()
    engine.current_position = Coordinate(lat=0.0, lng=0.0)
    rec = _wire(engine)

    async def move_that_stops(coords, speed_profile):
        rec["move_calls"].append((list(coords), dict(speed_profile)))
        engine.state = SimulationState.IDLE  # simulate external stop

    engine._move_along_route = move_that_stops
    nav = Navigator(engine)

    await nav.navigate_to(Coordinate(lat=1.0, lng=1.0), MovementMode.WALKING)

    types = [t for t, _ in emitted]
    # route_path + the NAVIGATING state_change only; no completion epilogue
    assert types == ["route_path", "state_change"]
    assert engine.state == SimulationState.IDLE
