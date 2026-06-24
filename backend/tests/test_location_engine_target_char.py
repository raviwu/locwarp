"""Characterization: api/location._engine must return the engine for the
TARGET udid after a lazy rebuild, not the primary one. Dual-device guard:
rebuilding B while A is primary must NOT hand back A's engine (which would
make teleport/navigate on B silently drive A).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import api.location as location_mod

pytestmark = pytest.mark.asyncio


async def test_engine_returns_target_engine_not_primary_after_rebuild():
    eng_a = MagicMock(name="engine_A")  # primary
    eng_b = MagicMock(name="engine_B")  # the device we actually target

    registry = MagicMock()
    # A is already primary; simulation_engine (primary accessor) returns A.
    registry.simulation_engine = eng_a
    registry._primary_udid = "UDID-A"

    engines = {"UDID-A": eng_a}

    # get_engine(B) is empty before rebuild, populated after.
    def _get_engine(u):
        return engines.get(u)
    registry.get_engine = MagicMock(side_effect=_get_engine)

    async def _create(u, force=False):
        engines[u] = eng_b  # rebuild populates B, leaves A primary
    registry.create_engine_for_device = AsyncMock(side_effect=_create)

    dm = MagicMock()
    dm._connections = {"UDID-A": object(), "UDID-B": object()}
    registry.device_manager = dm

    result = await location_mod._engine("UDID-B", registry)

    assert result is eng_b, "must return B's engine, not the primary (A)"


class _FakeRegistry:
    """Minimal AppState stand-in whose `simulation_engine` property reflects
    the live engines dict + primary udid (so the udid=None fallback path is
    actually exercised, not short-circuited at entry)."""

    def __init__(self, dm):
        self.engines: dict = {}
        self._primary_udid = None
        self.device_manager = dm
        self.create_calls: list = []

    @property
    def simulation_engine(self):
        if self._primary_udid and self._primary_udid in self.engines:
            return self.engines[self._primary_udid]
        return None

    def get_engine(self, udid):
        if udid is None:
            return self.simulation_engine
        return self.engines.get(udid)

    async def create_engine_for_device(self, udid, force=False):
        self.create_calls.append(udid)
        self.engines[udid] = self._next_engine
        if self._primary_udid is None:
            self._primary_udid = udid


async def test_engine_falls_back_to_primary_when_udid_arg_is_none():
    """udid arg is None: no primary yet, slot empty -> lazy rebuild promotes
    the only connected device to primary, and the primary fallback returns it.
    Guards the `else app_state.simulation_engine` branch of the fix."""
    eng_a = MagicMock(name="engine_A")

    dm = MagicMock()
    dm._connections = {"UDID-A": object()}

    reg = _FakeRegistry(dm)
    reg._next_engine = eng_a  # what create_engine_for_device installs

    # simulation_engine starts None (no primary) so _engine does NOT
    # short-circuit on the udid-None fast path; it rebuilds, then the
    # primary fallback is acceptable because no specific target was requested.
    result = await location_mod._engine(None, reg)
    assert result is eng_a
    assert reg.create_calls == ["UDID-A"]
