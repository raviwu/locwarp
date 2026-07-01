"""RestoreHandler clear()-failure semantics (H4 fix).

The interactive one-click restore stays LENIENT: a failed device clear() is
logged, swallowed, and a "restored" event is still emitted (pre-existing
behavior, preserved). The Gold Ditto cycle opts in with
``raise_on_clear_failure=True`` so a real clear() failure is SURFACED instead of
lying "restored" while the phone is left simulated at the target.
"""
import pytest

from tests._engine_harness import make_engine

pytestmark = pytest.mark.asyncio


async def _failing_clear():
    raise RuntimeError("clear failed")


async def test_restore_lenient_swallows_clear_failure_and_emits_restored():
    """Default (interactive) restore: clear() failure is swallowed, no raise,
    and 'restored' is still emitted. Locks in the pre-existing behavior so the
    H4 fix does not regress the one-click restore button."""
    eng, loc, emitted = make_engine()
    loc.clear = _failing_clear

    await eng.restore()  # must NOT raise

    assert "restored" in [t for (t, _d) in emitted]


async def test_restore_strict_reraises_and_skips_restored_on_clear_failure():
    """strict restore: clear() failure re-raises and 'restored' is NOT emitted."""
    eng, loc, emitted = make_engine()
    loc.clear = _failing_clear

    with pytest.raises(RuntimeError, match="clear failed"):
        await eng.restore(raise_on_clear_failure=True)

    assert "restored" not in [t for (t, _d) in emitted]


async def test_restore_strict_success_still_emits_restored():
    """strict restore with a healthy clear() behaves normally: clears once and
    emits 'restored'."""
    eng, loc, emitted = make_engine()

    await eng.restore(raise_on_clear_failure=True)

    assert loc.clears == 1
    assert "restored" in [t for (t, _d) in emitted]
