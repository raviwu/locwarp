"""Characterization tests for the "user restore must retry a flaky
fire-and-forget DVT stop" fix.

Root cause: pymobiledevice3's stopLocationSimulation DTX method is
``expects_reply=False`` — the backend sends "stop" and never confirms the
phone obeyed. Empirically a single stop sometimes does not land. Compounding
that, ``DvtLocationService.clear()`` / ``LegacyLocationService.clear()``
short-circuit ``if not self._active: return`` — so once ``_active`` flips
False (because a real clear() was SENT, even if it didn't actually land),
every subsequent user restore press silently no-ops and the user cannot
recover by retrying; they have to re-teleport.

Fix: ``clear(force=True)`` bypasses the ``_active`` guard so a
user-initiated restore always re-sends the real device stop, giving the
flaky fire-and-forget clear another chance to land. Internal callers
(teardown in device_manager.py) keep calling bare ``clear()`` — guard still
applies there.
"""
from __future__ import annotations

import pytest

from core.restore import RestoreHandler
from services.location_service import DvtLocationService

pytestmark = pytest.mark.asyncio


class _RecordingSim:
    """Stand-in for the DVT LocationSimulation instrument. Records every
    clear() call so tests can tell whether the guard was bypassed."""

    def __init__(self) -> None:
        self.clear_calls = 0

    async def clear(self) -> None:
        self.clear_calls += 1

    async def set(self, lat, lng) -> None:  # pragma: no cover - unused here
        pass


def _make_dvt_service_with_recording_sim(*, initial_active: bool) -> tuple[DvtLocationService, _RecordingSim]:
    """Build a DvtLocationService whose _ensure_instrument returns a
    _RecordingSim directly, bypassing the real DVT provider plumbing."""
    service = DvtLocationService(object(), initial_active=initial_active)
    fake_sim = _RecordingSim()

    async def _fake_ensure_instrument():
        return fake_sim

    service._ensure_instrument = _fake_ensure_instrument  # type: ignore[method-assign]
    return service, fake_sim


async def test_clear_force_true_bypasses_inactive_guard_and_reaches_device():
    """(a) _active=False (simulating the state right after a previous
    ineffective clear): clear(force=True) MUST invoke the fake sim's
    clear() — force bypasses the guard."""
    service, fake_sim = _make_dvt_service_with_recording_sim(initial_active=False)

    await service.clear(force=True)

    assert fake_sim.clear_calls == 1


async def test_clear_without_force_still_noops_when_inactive():
    """(b) Same service, _active=False: clear() (force defaults False) MUST
    NOT invoke the fake sim's clear() — the guard still holds for internal
    (non-forced) callers, e.g. device_manager teardown."""
    service, fake_sim = _make_dvt_service_with_recording_sim(initial_active=False)

    await service.clear()

    assert fake_sim.clear_calls == 0


class _StubEngine:
    """Minimal stand-in for SimulationEngine, just enough surface for
    RestoreHandler.restore() to run: state, location_service, and an
    _emit() it can await."""

    def __init__(self, location_service: DvtLocationService) -> None:
        from models.schemas import SimulationState

        self.state = SimulationState.IDLE
        self.location_service = location_service
        self.distance_traveled = 0.0
        self.distance_remaining = 0.0
        self.lap_count = 0
        self.segment_index = 0
        self.total_segments = 0
        self.emitted: list[tuple[str, dict]] = []

    async def stop(self) -> None:  # pragma: no cover - state is already IDLE
        pass

    async def _emit(self, event_type: str, data: dict) -> None:
        self.emitted.append((event_type, dict(data)))


async def test_restore_forces_device_clear_even_when_service_believes_inactive():
    """(c) RestoreHandler.restore() on an engine whose location_service
    is _active=False but the device is still simulating (the exact
    production scenario: a previous restore press sent a real clear that
    the phone silently ignored, flipping _active False without actually
    clearing) MUST still reach a real device clear() — proving the
    user-facing restore path forces, so retrying restore can recover."""
    service, fake_sim = _make_dvt_service_with_recording_sim(initial_active=False)
    engine = _StubEngine(service)
    handler = RestoreHandler(engine)

    await handler.restore()

    assert fake_sim.clear_calls == 1
    assert "restored" in [t for (t, _d) in engine.emitted]
