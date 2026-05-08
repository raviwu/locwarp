"""Unit tests for GoldDittoHandler."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from core.goldditto import GoldDittoHandler, GoldDittoLockedError
from models.schemas import Coordinate


# ── Fake engine ────────────────────────────────────────────────────────────

@dataclass
class FakeEngine:
    """Stand-in for SimulationEngine. Records call order so tests can assert
    teleport → sleep → restore happens in order with the correct args."""
    current_position: Coordinate | None = None
    teleport_calls: list[tuple[float, float]] = None
    restore_calls: int = 0
    emitted: list[tuple[str, dict]] = None

    def __post_init__(self):
        self.teleport_calls = []
        self.emitted = []

    async def teleport(self, lat: float, lng: float) -> Coordinate:
        self.teleport_calls.append((lat, lng))
        self.current_position = Coordinate(lat=lat, lng=lng)
        return self.current_position

    async def restore(self) -> None:
        self.restore_calls += 1
        # Real engine keeps current_position after restore; mirror that.

    async def _emit(self, event_type: str, data: dict) -> None:
        self.emitted.append((event_type, data))


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def handler(engine) -> GoldDittoHandler:
    return GoldDittoHandler(engine)


A = (25.034897, 121.545827)
B = (25.10, 121.60)


# ── Target picker ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_target_A_returns_A(handler):
    result = await handler.cycle(target="A", lat_a=A[0], lng_a=A[1],
                                  lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert result["target_used"] == "A"
    assert (result["lat"], result["lng"]) == A


@pytest.mark.asyncio
async def test_target_B_returns_B(handler):
    result = await handler.cycle(target="B", lat_a=A[0], lng_a=A[1],
                                  lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert result["target_used"] == "B"
    assert (result["lat"], result["lng"]) == B


@pytest.mark.asyncio
async def test_auto_with_no_current_position_picks_A(handler, engine):
    engine.current_position = None
    result = await handler.cycle(target="auto", lat_a=A[0], lng_a=A[1],
                                  lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert result["target_used"] == "A"


@pytest.mark.asyncio
async def test_auto_when_close_to_A_picks_B(handler, engine):
    engine.current_position = Coordinate(lat=A[0], lng=A[1])
    result = await handler.cycle(target="auto", lat_a=A[0], lng_a=A[1],
                                  lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert result["target_used"] == "B"


@pytest.mark.asyncio
async def test_auto_when_close_to_B_picks_A(handler, engine):
    engine.current_position = Coordinate(lat=B[0], lng=B[1])
    result = await handler.cycle(target="auto", lat_a=A[0], lng_a=A[1],
                                  lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert result["target_used"] == "A"


# ── Cycle orchestration ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cycle_calls_teleport_then_restore_in_order(handler, engine):
    await handler.cycle(target="A", lat_a=A[0], lng_a=A[1],
                        lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert engine.teleport_calls == [A]
    assert engine.restore_calls == 1


@pytest.mark.asyncio
async def test_cycle_emits_phase_events(handler, engine):
    await handler.cycle(target="A", lat_a=A[0], lng_a=A[1],
                        lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    events = [e for e in engine.emitted if e[0] == "goldditto_cycle"]
    assert len(events) == 2
    assert events[0][1]["phase"] == "teleported"
    assert events[0][1]["target"] == "A"
    assert events[1][1]["phase"] == "restored"


@pytest.mark.asyncio
async def test_concurrent_cycle_raises_locked(handler, engine):
    """Second cycle started while first is mid-sleep must raise GoldDittoLockedError."""
    cycle1 = asyncio.create_task(handler.cycle(
        target="A", lat_a=A[0], lng_a=A[1],
        lat_b=B[0], lng_b=B[1], wait_seconds=0.2))
    await asyncio.sleep(0.05)  # let cycle1 enter the lock

    with pytest.raises(GoldDittoLockedError):
        await handler.cycle(target="B", lat_a=A[0], lng_a=A[1],
                            lat_b=B[0], lng_b=B[1], wait_seconds=0.01)

    await cycle1
    assert engine.restore_calls == 1


@pytest.mark.asyncio
async def test_teleport_failure_skips_sleep_and_restore(handler, engine):
    """If teleport raises, cycle propagates and never sleeps or restores."""
    async def boom(lat, lng):
        raise RuntimeError("device unplugged")
    engine.teleport = boom

    with pytest.raises(RuntimeError, match="device unplugged"):
        await handler.cycle(target="A", lat_a=A[0], lng_a=A[1],
                            lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert engine.restore_calls == 0


# ── Lock release after exception ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_lock_released_after_teleport_failure(handler, engine):
    """After teleport raises, the lock must be released so the next cycle can run."""
    call_count = {"n": 0}

    original = engine.teleport

    async def fail_once(lat, lng):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient")
        return await original(lat, lng)

    engine.teleport = fail_once

    with pytest.raises(RuntimeError, match="transient"):
        await handler.cycle(target="A", lat_a=A[0], lng_a=A[1],
                            lat_b=B[0], lng_b=B[1], wait_seconds=0.01)

    # Second call must succeed — i.e. lock was released.
    result = await handler.cycle(target="A", lat_a=A[0], lng_a=A[1],
                                  lat_b=B[0], lng_b=B[1], wait_seconds=0.01)
    assert result["target_used"] == "A"
    assert engine.restore_calls == 1
