"""The device-push value and the recorded live position can differ.

Backward compatible: with no state_* args, current_position == pushed (today's
behavior). With state_* args, the device gets (lat,lng) but current_position
records (state_lat, state_lng) — the seam the jitter fix relies on."""
from __future__ import annotations

import pytest

from tests._engine_harness import make_engine

pytestmark = pytest.mark.asyncio


async def test_set_position_default_records_pushed_value():
    eng, loc, _ = make_engine()
    await eng._set_position(10.0, 20.0)
    assert loc.pushes[-1] == (10.0, 20.0)
    assert (eng.current_position.lat, eng.current_position.lng) == (10.0, 20.0)


async def test_set_position_records_state_while_pushing_device_value():
    eng, loc, _ = make_engine()
    await eng._set_position(10.001, 20.001, state_lat=10.0, state_lng=20.0)
    # Device got the (jittered) push value...
    assert loc.pushes[-1] == (10.001, 20.001)
    # ...but the recorded live position is the pristine state value.
    assert (eng.current_position.lat, eng.current_position.lng) == (10.0, 20.0)


async def test_push_with_retry_forwards_state():
    eng, loc, _ = make_engine()
    ok = await eng._push_with_retry(10.001, 20.001, state_lat=10.0, state_lng=20.0)
    assert ok is True
    assert loc.pushes[-1] == (10.001, 20.001)
    assert (eng.current_position.lat, eng.current_position.lng) == (10.0, 20.0)
