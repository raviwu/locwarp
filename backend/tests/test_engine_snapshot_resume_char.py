"""Characterize resume_from_snapshot getattr(self, kind) dispatch for the four
resumable kinds + the unknown-kind warn-and-return guard.

Task 9d: pins exact dispatch surface (lines 529-547 of simulation_engine.py).
"""
import pytest

from tests._engine_harness import FakeClock, SteppedSleep, make_engine


# Only the async tests get the asyncio mark; the sync parametrized test is plain.
@pytest.mark.parametrize("kind", ["navigate", "start_loop", "multi_stop", "random_walk"])
def test_kind_resolves_to_a_bound_method(kind):
    """The dispatch is getattr(self, kind, None) (line 531). Each resumable
    kind MUST resolve to a callable bound method on the engine."""
    eng, _loc, _emitted = make_engine()
    method = getattr(eng, kind, None)
    assert callable(method), f"engine.{kind} must be callable for resume dispatch"


@pytest.mark.asyncio
async def test_unknown_kind_snapshot_warns_and_returns_without_raising():
    """A snapshot with a bogus kind hits the warn-and-return guard (lines 532-534)
    and returns None — does NOT raise."""
    eng, _loc, _emitted = make_engine()
    snap = {"kind": "no_such_method", "args": {}}
    result = await eng.resume_from_snapshot(snap)
    assert result is None


@pytest.mark.asyncio
async def test_empty_kind_snapshot_returns_early():
    """kind missing -> `if not kind: return` (line 529-530)."""
    eng, _loc, _emitted = make_engine()
    result = await eng.resume_from_snapshot({"args": {}})
    assert result is None


@pytest.mark.asyncio
async def test_none_kind_snapshot_returns_early():
    """kind=None is falsy -> early return without raising."""
    eng, _loc, _emitted = make_engine()
    result = await eng.resume_from_snapshot({"kind": None, "args": {}})
    assert result is None
