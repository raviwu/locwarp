"""Restore handler -- stop simulation and clear device location."""

from __future__ import annotations

import logging

from models.schemas import SimulationState

logger = logging.getLogger(__name__)


class RestoreHandler:
    """Stops all active simulation and clears the simulated location
    on the device, restoring the real GPS signal."""

    def __init__(self, engine):
        self.engine = engine

    async def restore(self, raise_on_clear_failure: bool = False) -> None:
        """Stop everything and clear the location service.

        1. Stop any active movement task.
        2. Clear the simulated location on the device.
        3. Reset engine state to IDLE.

        ``raise_on_clear_failure`` (default False): the interactive one-click
        restore stays LENIENT — a failed device clear() is logged and swallowed,
        and a "restored" event is still emitted (preserved pre-existing
        behavior). The Gold Ditto cycle opts in with True so that a real clear()
        failure is SURFACED: no "restored" is emitted and the exception
        propagates, letting the cycle show its restore_failed banner instead of
        lying "restored" while the phone is left simulated at the target.
        """
        engine = self.engine

        # Stop any running movement
        if engine.state not in (SimulationState.IDLE, SimulationState.DISCONNECTED):
            await engine.stop()

        # Clear the simulated location on the device
        clear_error: Exception | None = None
        try:
            await engine.location_service.clear()
            logger.info("Device location simulation cleared (restored real GPS)")
        except Exception as e:  # noqa: BLE001 — decision deferred to raise_on_clear_failure
            logger.exception("Failed to clear device location")
            clear_error = e

        # Reset engine state (keep current_position so user can restart without teleporting)
        engine.distance_traveled = 0.0
        engine.distance_remaining = 0.0
        engine.lap_count = 0
        engine.segment_index = 0
        engine.total_segments = 0
        engine.state = SimulationState.IDLE

        if clear_error is not None and raise_on_clear_failure:
            # Surface the failure without lying "restored". The caller (Gold
            # Ditto cycle) emits restore_failed and returns non-2xx.
            raise clear_error

        await engine._emit("restored", {})
        await engine._emit("state_change", {"state": engine.state.value})

        logger.info("Simulation fully restored")
