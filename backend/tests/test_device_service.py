"""Unit tests for DeviceService.connect/disconnect/repair.

Verifies that the orchestration calls are made in the correct order
against a fake device manager + engine registry, without touching any
real iPhone hardware or filesystem.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.device_service import DeviceService


@pytest.mark.asyncio
async def test_connect_calls_dm_and_engine_factory():
    """connect() must await dm.connect then create_engine_for_device."""
    dm = MagicMock()
    dm._connections = {}
    dm.connect = AsyncMock()
    engine_registry = MagicMock()
    engine_registry.create_engine_for_device = AsyncMock()

    svc = DeviceService(
        device_manager=dm,
        tunnel_registry=MagicMock(),
        engine_registry=engine_registry,
    )
    await svc.connect("U1")

    dm.connect.assert_awaited_once_with("U1")
    engine_registry.create_engine_for_device.assert_awaited_once_with("U1")


@pytest.mark.asyncio
async def test_connect_order_is_dm_first_then_engine():
    """dm.connect must be called BEFORE create_engine_for_device."""
    call_order: list[str] = []

    dm = MagicMock()
    dm._connections = {}

    async def fake_connect(udid):
        call_order.append("dm.connect")

    dm.connect = AsyncMock(side_effect=fake_connect)

    engine_registry = MagicMock()

    async def fake_create(udid):
        call_order.append("create_engine")

    engine_registry.create_engine_for_device = AsyncMock(side_effect=fake_create)

    svc = DeviceService(
        device_manager=dm,
        tunnel_registry=MagicMock(),
        engine_registry=engine_registry,
    )
    await svc.connect("U2")

    assert call_order == ["dm.connect", "create_engine"]


@pytest.mark.asyncio
async def test_disconnect_calls_dm_and_pops_engine():
    """disconnect() must await dm.disconnect and remove the engine + update _primary_udid."""
    dm = MagicMock()
    dm.disconnect = AsyncMock()

    fake_engines = {"U3": MagicMock(), "U4": MagicMock()}
    engine_registry = MagicMock()
    engine_registry.simulation_engines = fake_engines
    engine_registry._primary_udid = "U3"

    async def fake_remove_engine(udid):
        fake_engines.pop(udid, None)
        if engine_registry._primary_udid == udid:
            engine_registry._primary_udid = next(iter(fake_engines), None)

    engine_registry.remove_engine = AsyncMock(side_effect=fake_remove_engine)

    svc = DeviceService(
        device_manager=dm,
        tunnel_registry=MagicMock(),
        engine_registry=engine_registry,
    )
    await svc.disconnect("U3")

    dm.disconnect.assert_awaited_once_with("U3")
    engine_registry.remove_engine.assert_awaited_once_with("U3")
    assert "U3" not in fake_engines
    # _primary_udid must be updated to a remaining engine or None
    assert engine_registry._primary_udid != "U3"


@pytest.mark.asyncio
async def test_disconnect_non_primary_leaves_primary_unchanged():
    """Disconnecting a non-primary udid must not touch _primary_udid."""
    dm = MagicMock()
    dm.disconnect = AsyncMock()

    fake_engines = {"U5": MagicMock(), "U6": MagicMock()}
    engine_registry = MagicMock()
    engine_registry.simulation_engines = fake_engines
    engine_registry._primary_udid = "U5"

    async def fake_remove_engine(udid):
        fake_engines.pop(udid, None)
        if engine_registry._primary_udid == udid:
            engine_registry._primary_udid = next(iter(fake_engines), None)

    engine_registry.remove_engine = AsyncMock(side_effect=fake_remove_engine)

    svc = DeviceService(
        device_manager=dm,
        tunnel_registry=MagicMock(),
        engine_registry=engine_registry,
    )
    await svc.disconnect("U6")

    dm.disconnect.assert_awaited_once_with("U6")
    engine_registry.remove_engine.assert_awaited_once_with("U6")
    assert "U6" not in fake_engines
    assert engine_registry._primary_udid == "U5"


@pytest.mark.asyncio
async def test_repair_clears_user_denied():
    """repair() must call dm.clear_user_denied(udid)."""
    dm = MagicMock()
    dm.clear_user_denied = MagicMock()

    svc = DeviceService(
        device_manager=dm,
        tunnel_registry=MagicMock(),
        engine_registry=MagicMock(),
    )
    await svc.repair("U7")

    dm.clear_user_denied.assert_called_once_with("U7")
