"""Characterize EngineResolver.with_recovery + cleanup_device_lost, lifted
from api/location.py::_try_with_recovery_retry / _handle_device_lost. REAL
resolver over fakes; asserts exact retry count, exact published tuple, exact
(reason, message). Mirrors test_location_device_lost_publisher.py.
"""
from unittest.mock import AsyncMock

import pytest

from services.engine_resolver import EngineResolver
from services.location_service import DeviceLostError

pytestmark = pytest.mark.asyncio


class _CapPublisher:
    def __init__(self):
        self.captured = []
    async def publish(self, event):
        etype, data = event
        self.captured.append((etype, {**data}))


class _FakeDM:
    def __init__(self, connections, publisher):
        self._connections = connections
        self._events = publisher
        self.full_reconnect = AsyncMock(return_value=True)
        self._disconnected = []
    async def disconnect(self, u):
        self._disconnected.append(u)
        self._connections.pop(u, None)


class _FakeRegistry:
    def __init__(self, dm, engines):
        self.device_manager = dm
        self.simulation_engines = engines
        self.remove_engine = AsyncMock(return_value=None)


async def test_with_recovery_retries_op_once_after_full_reconnect():
    pub = _CapPublisher()
    dm = _FakeDM({"U1": object()}, pub)
    reg = _FakeRegistry(dm, {})
    resolver = EngineResolver(reg, dm)
    calls = []
    async def op():
        calls.append(1)
        if len(calls) == 1:
            raise DeviceLostError("gone", reason=DeviceLostError.REASON_USB_GONE)
        return "ok"
    out = await resolver.with_recovery("U1", op)
    assert out == "ok"
    assert len(calls) == 2  # original + one retry
    dm.full_reconnect.assert_awaited_once_with("U1")


async def test_with_recovery_reraises_when_full_reconnect_fails():
    pub = _CapPublisher()
    dm = _FakeDM({"U1": object()}, pub)
    dm.full_reconnect = AsyncMock(return_value=False)
    reg = _FakeRegistry(dm, {})
    resolver = EngineResolver(reg, dm)
    async def op():
        raise DeviceLostError("gone")
    with pytest.raises(DeviceLostError):
        await resolver.with_recovery("U1", op)


async def test_cleanup_device_lost_only_named_udid_and_exact_publish():
    pub = _CapPublisher()
    dm = _FakeDM({"U1": object(), "U2": object()}, pub)
    reg = _FakeRegistry(dm, {})
    resolver = EngineResolver(reg, dm)
    exc = DeviceLostError("device gone", reason=DeviceLostError.REASON_TUNNEL_DEAD)
    reason, message = await resolver.cleanup_device_lost(exc, "U1")
    assert reason == DeviceLostError.REASON_TUNNEL_DEAD
    assert message == "WiFi 連線中斷,請確認手機 WiFi 與電腦同網段、解鎖手機後再試"
    assert dm._disconnected == ["U1"]
    assert "U2" in dm._connections  # survivor untouched
    assert len(pub.captured) == 1
    etype, data = pub.captured[0]
    assert etype == "device_disconnected"
    assert data["udids"] == ["U1"]
    assert data["reason"] == "device_lost"
    assert data["error"] == "device gone"
    assert data["remaining_count"] == 1
