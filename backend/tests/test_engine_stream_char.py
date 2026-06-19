"""Characterize the engine's position/ETA emit stream as ordered exact tuples.

Task 9a: pins the teleport emit order as observed from core/teleport.py.
"""
import pytest

from tests._engine_harness import FakeClock, SteppedSleep, make_engine


pytestmark = pytest.mark.asyncio


async def test_teleport_emits_ordered_state_and_position():
    clock = FakeClock()
    sleep = SteppedSleep(clock)
    eng, loc, emitted = make_engine(clock=clock, sleep=sleep)

    pos = await eng.teleport(25.0375, 121.5637)

    assert (pos.lat, pos.lng) == (25.0375, 121.5637)
    # location_service.set was called exactly once with the teleport target.
    assert loc.pushes == [(25.0375, 121.5637)]
    # Exact ordered emit stream for a teleport (core/teleport.py):
    #   state_change(TELEPORTING) -> teleport -> position_update -> state_change(IDLE)
    types = [t for (t, _d) in emitted]
    assert types == [
        "state_change", "teleport", "position_update", "state_change",
    ]
    assert emitted[0][1] == {"state": "teleporting"}
    assert emitted[1][1] == {"lat": 25.0375, "lng": 121.5637}
    assert emitted[2][1] == {"lat": 25.0375, "lng": 121.5637}
    assert emitted[3][1] == {"state": "idle"}
