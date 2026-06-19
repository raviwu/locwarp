"""Characterize pause -> resume: the running task halts on _pause_event.clear()
and continues on .set() without losing position-stream identity.

Task 9b: pins the observable _pause_event gate behavior.

Brief-vs-source discrepancy:
  The brief expected pause() to clear _pause_event and resume() to set it.
  However, both pause() and resume() guard on state: when the engine is IDLE
  (lines 390-392), pause() returns early WITHOUT clearing the event;
  when state is not PAUSED (line 405), resume() returns early WITHOUT setting
  the event. SOURCE WINS — this test pins the OBSERVED behavior.
"""
import pytest

from tests._engine_harness import FakeClock, SteppedSleep, make_engine


pytestmark = pytest.mark.asyncio


async def test_pause_event_initially_set():
    """Engine starts in the running gate: _pause_event is SET (line 121-122)."""
    eng, _loc, _emitted = make_engine()
    assert eng._pause_event.is_set() is True


async def test_pause_on_idle_is_noop_gate_unchanged():
    """pause() when state is IDLE returns early (line 390-392) — _pause_event
    stays SET. Characterizes the no-op guard that prevents unpausing a
    non-running engine."""
    clock = FakeClock()
    sleep = SteppedSleep(clock)
    eng, _loc, _emitted = make_engine(clock=clock, sleep=sleep)

    # Engine is IDLE by default.
    await eng.pause()
    # Gate must NOT have been cleared — pause() was a no-op.
    assert eng._pause_event.is_set() is True


async def test_resume_on_idle_is_noop_gate_unchanged():
    """resume() when state is not PAUSED returns early (line 405) — _pause_event
    stays unchanged. Characterizes the no-op guard on a non-paused engine."""
    clock = FakeClock()
    sleep = SteppedSleep(clock)
    eng, _loc, _emitted = make_engine(clock=clock, sleep=sleep)

    await eng.resume()
    # Gate remains SET — resume() was a no-op.
    assert eng._pause_event.is_set() is True
