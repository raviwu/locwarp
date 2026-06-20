"""Characterization: DeviceService.disconnect must not race a concurrent
create_engine_for_device. Teardown goes through the locked remove_engine."""
from __future__ import annotations

import asyncio

import pytest

from services.device_service import DeviceService


@pytest.mark.asyncio
async def test_disconnect_does_not_race_concurrent_create():
    from main import app_state
    app_state.simulation_engines.clear()
    app_state._primary_udid = None
    app_state.simulation_engines["KEEP"] = object()
    app_state.simulation_engines["DROP"] = object()
    app_state._primary_udid = "DROP"

    started = asyncio.Event()

    class _DM:
        async def disconnect(self, udid):
            started.set()
            await asyncio.sleep(0)

    class FakeLocService:
        async def set(self, lat, lng):
            pass

    async def fake_get_location_service(udid):
        return FakeLocService()

    app_state.device_manager.get_location_service = fake_get_location_service

    svc = DeviceService(device_manager=_DM(), tunnel_registry=object(), engine_registry=app_state)

    async def do_create():
        await started.wait()
        await app_state.create_engine_for_device("NEW")

    await asyncio.gather(svc.disconnect("DROP"), do_create())

    assert "DROP" not in app_state.simulation_engines
    assert "KEEP" in app_state.simulation_engines
    assert "NEW" in app_state.simulation_engines
    assert app_state._primary_udid in ("KEEP", "NEW")
    app_state.simulation_engines.clear()
    app_state._primary_udid = None
