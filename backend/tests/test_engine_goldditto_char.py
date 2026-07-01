"""Characterize goldditto_cycle: single-target teleport + restore, return dict shape.

Task 9c: pins actual behavior from core/goldditto.py.

Brief-vs-source discrepancy:
  The brief expected both A and B coords in loc.pushes in a single call. The
  SOURCE shows that goldditto_cycle teleports to exactly ONE target (A or B,
  chosen by _pick), waits, then restores. Only one push per call.
  Also: goldditto uses asyncio.sleep directly (line 88 of goldditto.py), NOT
  the engine's seamed _sleep — the SteppedSleep seam does not intercept it.
  SOURCE WINS — tests use a tiny wait_seconds=0.001 for speed.
"""
import pytest

from tests._engine_harness import FakeClock, SteppedSleep, make_engine


pytestmark = pytest.mark.asyncio


async def test_goldditto_cycle_returns_dict_with_expected_keys():
    """goldditto_cycle returns a dict with target_used, lat, lng, duration_ms."""
    clock = FakeClock()
    sleep = SteppedSleep(clock)
    eng, loc, emitted = make_engine(clock=clock, sleep=sleep)

    result = await eng.goldditto_cycle(
        target="A",
        lat_a=25.0,
        lng_a=121.0,
        lat_b=26.0,
        lng_b=122.0,
        wait_seconds=0.001,
    )

    assert isinstance(result, dict)
    assert set(result.keys()) == {"target_used", "lat", "lng", "duration_ms"}
    assert result["target_used"] == "A"
    assert result["lat"] == 25.0
    assert result["lng"] == 121.0
    assert isinstance(result["duration_ms"], int)


async def test_goldditto_cycle_target_a_pushes_a_not_b():
    """target='A' teleports to A coords only; exactly one location push."""
    eng, loc, emitted = make_engine()

    await eng.goldditto_cycle(
        target="A",
        lat_a=25.0,
        lng_a=121.0,
        lat_b=26.0,
        lng_b=122.0,
        wait_seconds=0.001,
    )

    assert (25.0, 121.0) in loc.pushes
    assert (26.0, 122.0) not in loc.pushes
    # Exactly one teleport push per cycle.
    assert len(loc.pushes) == 1


async def test_goldditto_cycle_target_b_pushes_b_not_a():
    """target='B' teleports to B coords only; exactly one location push."""
    eng, loc, emitted = make_engine()

    await eng.goldditto_cycle(
        target="B",
        lat_a=25.0,
        lng_a=121.0,
        lat_b=26.0,
        lng_b=122.0,
        wait_seconds=0.001,
    )

    assert (26.0, 122.0) in loc.pushes
    assert (25.0, 121.0) not in loc.pushes
    assert len(loc.pushes) == 1


async def test_goldditto_cycle_emit_order():
    """Exact ordered emit stream for a complete goldditto cycle (target='A').

    Observed order (core/goldditto.py + core/teleport.py + core/restore.py):
      state_change(TELEPORTING) -> teleport -> position_update ->
      state_change(IDLE) -> goldditto_cycle(teleported) ->
      restored -> state_change(IDLE) -> goldditto_cycle(restored)
    """
    eng, _loc, emitted = make_engine()

    await eng.goldditto_cycle(
        target="A",
        lat_a=10.0,
        lng_a=20.0,
        lat_b=30.0,
        lng_b=40.0,
        wait_seconds=0.001,
    )

    types = [t for (t, _d) in emitted]
    assert types == [
        "state_change",    # TELEPORTING
        "teleport",
        "position_update",
        "state_change",    # IDLE (after teleport)
        "goldditto_cycle", # phase=teleported
        "restored",
        "state_change",    # IDLE (after restore)
        "goldditto_cycle", # phase=restored
    ]
    assert emitted[0][1] == {"state": "teleporting"}
    assert emitted[4][1]["phase"] == "teleported"
    assert emitted[7][1]["phase"] == "restored"


async def test_goldditto_cycle_clear_failure_emits_restore_failed_and_raises():
    """H4 fix: if the device clear() fails during restore, the cycle must NOT
    lie 'restored'. It emits goldditto_cycle(restore_failed), emits no bare
    'restored', and re-raises so the API returns non-2xx. This only works
    because the cycle calls restore(raise_on_clear_failure=True)."""
    eng, loc, emitted = make_engine()

    async def boom_clear():
        raise RuntimeError("dvt channel dropped during clear")
    loc.clear = boom_clear

    with pytest.raises(RuntimeError, match="dvt channel dropped"):
        await eng.goldditto_cycle(
            target="A",
            lat_a=10.0, lng_a=20.0,
            lat_b=30.0, lng_b=40.0,
            wait_seconds=0.001,
        )

    gold_phases = [d["phase"] for (t, d) in emitted if t == "goldditto_cycle"]
    assert "teleported" in gold_phases
    assert "restore_failed" in gold_phases
    assert "restored" not in gold_phases
    # RestoreHandler must NOT have emitted the bare 'restored' event either.
    assert "restored" not in [t for (t, _d) in emitted]
