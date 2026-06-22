"""Characterize capture_resumable_snapshot's dict assembly before the pure
serializer is extracted to domain/movement.py (Phase 3, Task 4).

White-box: sets the engine fields capture reads, then asserts the exact snapshot
dict. Pins: the 9 base keys + optional active_speed_profile, the seg_for_resume
kind branch (multi_stop/start_loop use _user_waypoint_next-1; navigate/random_walk
use segment_index), the active_speed_profile key (present iff truthy), and the
None-when-not-resumable gate.

NOTE: capture_resumable_snapshot short-circuits to None when `_last_sim_args` is
falsy (simulation_engine.py:507), so every armed case passes a NON-EMPTY args dict.
"""
import pytest

from models.schemas import Coordinate, SimulationState
from tests._engine_harness import make_engine


def _arm(eng, *, state, kind, args, seg=0, uwn=0, lap=0, dist=0.0,
         speed_applied=False, rw=0, profile=None, pos=(25.0, 121.0)):
    eng.state = state
    eng._last_sim_kind = kind
    eng._last_sim_args = args
    eng.current_position = Coordinate(lat=pos[0], lng=pos[1]) if pos else None
    eng.segment_index = seg
    eng._user_waypoint_next = uwn
    eng.lap_count = lap
    eng.distance_traveled = dist
    eng._speed_was_applied = speed_applied
    eng._random_walk_count = rw
    eng._active_speed_profile = profile
    return eng


def test_navigate_snapshot_uses_segment_index():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.NAVIGATING, kind="navigate",
         args={"lat": 1.0, "lng": 2.0}, seg=7, uwn=3, dist=123.5)
    snap = eng.capture_resumable_snapshot()
    assert snap == {
        "kind": "navigate",
        "args": {"lat": 1.0, "lng": 2.0},
        "current_pos": (25.0, 121.0),
        "segment_index": 7,          # navigate -> segment_index, NOT uwn-1
        "lap_count": 0,
        "user_waypoint_next": 3,
        "distance_traveled": 123.5,
        "speed_was_applied": False,
        "random_walk_count": 0,
    }
    assert "active_speed_profile" not in snap   # falsy profile -> key absent


def test_multi_stop_snapshot_uses_user_waypoint_next_minus_one():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.MULTI_STOP, kind="multi_stop",
         args={"stops": []}, seg=99, uwn=4)
    snap = eng.capture_resumable_snapshot()
    assert snap["segment_index"] == 3   # max(0, uwn-1) = 3, NOT seg=99
    assert snap["user_waypoint_next"] == 4


def test_start_loop_snapshot_uses_user_waypoint_next_minus_one_floored():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.LOOPING, kind="start_loop",
         args={"x": 1}, seg=12, uwn=0)   # non-empty args: dodge the falsy short-circuit
    snap = eng.capture_resumable_snapshot()
    assert snap["segment_index"] == 0   # max(0, 0-1) floors to 0


def test_random_walk_snapshot_uses_segment_index_and_count():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.RANDOM_WALK, kind="random_walk",
         args={"radius": 500}, seg=5, uwn=9, rw=2)
    snap = eng.capture_resumable_snapshot()
    assert snap["segment_index"] == 5
    assert snap["random_walk_count"] == 2


def test_active_speed_profile_present_when_truthy():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.NAVIGATING, kind="navigate",
         args={"x": 1}, profile={"speed_mps": 30.0, "jitter": 0.0})
    snap = eng.capture_resumable_snapshot()
    assert snap["active_speed_profile"] == {"speed_mps": 30.0, "jitter": 0.0}


def test_current_pos_none_when_no_position():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.NAVIGATING, kind="navigate",
         args={"x": 1}, pos=None)
    snap = eng.capture_resumable_snapshot()
    assert snap["current_pos"] is None


@pytest.mark.parametrize("state", [SimulationState.IDLE, SimulationState.PAUSED,
                                   SimulationState.TELEPORTING])
def test_returns_none_when_not_in_a_resumable_state(state):
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=state, kind="navigate", args={"x": 1})
    assert eng.capture_resumable_snapshot() is None


def test_returns_none_when_no_last_sim_kind():
    eng, _loc, _emitted = make_engine()
    _arm(eng, state=SimulationState.NAVIGATING, kind="", args={})
    assert eng.capture_resumable_snapshot() is None
