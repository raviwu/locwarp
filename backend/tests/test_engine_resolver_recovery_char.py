"""Characterize EngineResolver.with_recovery + cleanup_device_lost, lifted
from api/location.py::_try_with_recovery_retry / _handle_device_lost. REAL
resolver over fakes; asserts exact retry count, exact published tuple, exact
(reason, message). Mirrors test_location_device_lost_publisher.py.

Also covers the snapshot-resume fix: with_recovery must capture
capture_resumable_snapshot() before full_reconnect and call
resume_from_snapshot(snapshot) on the new engine after recovery, matching
the watchdog's semantics (wifi_tunnel_service.py::run_watchdog +
infra/device/tunnel_restart.py::attempt_tunnel_restart).
"""
import asyncio
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


# ---------------------------------------------------------------------------
# Snapshot-resume characterization tests (Follow-up A)
# ---------------------------------------------------------------------------

class _FakeEngine:
    """Minimal engine fake for snapshot tests.

    ``capture_resumable_snapshot`` returns the snapshot dict passed at
    construction (or None when the engine is idle / no route running).
    ``resume_from_snapshot`` is an AsyncMock so we can assert calls.
    """
    def __init__(self, snapshot: dict | None):
        self._snapshot = snapshot
        self.resume_from_snapshot = AsyncMock()

    def capture_resumable_snapshot(self) -> dict | None:
        return self._snapshot


class _SwappingRegistry:
    """Registry whose simulation_engines dict starts with old_engine and is
    replaced by new_engine when full_reconnect fires (simulating the tunnel
    restart rebuilding the engine under the same udid key)."""

    def __init__(self, udid: str, old_engine, new_engine):
        self._udid = udid
        self.simulation_engines: dict = {udid: old_engine}
        self._new_engine = new_engine
        self.remove_engine = AsyncMock(return_value=None)

    def _swap_to_new(self):
        """Called by the fake DM's full_reconnect to simulate engine replacement."""
        self.simulation_engines[self._udid] = self._new_engine


class _SwappingDM:
    """DM whose full_reconnect swaps the registry engine to simulate a real
    tunnel restart that rebuilds the engine under the same udid key."""

    def __init__(self, connections, publisher, registry):
        self._connections = connections
        self._events = publisher
        self._registry = registry
        self._disconnected: list = []

    async def full_reconnect(self, udid: str) -> bool:
        self._registry._swap_to_new()
        return True

    async def disconnect(self, u):
        self._disconnected.append(u)
        self._connections.pop(u, None)


async def test_with_recovery_resumes_route_on_new_engine_after_full_reconnect():
    """DANGER-ZONE: when op raises DeviceLostError on a WiFi device that has a
    running navigate/loop/multi-stop route, with_recovery must:
      1. capture_resumable_snapshot() on the OLD engine before full_reconnect
      2. call resume_from_snapshot(snapshot) on the NEW engine after full_reconnect

    This mirrors wifi_tunnel_service.run_watchdog + attempt_tunnel_restart
    semantics exactly so a route is NOT silently dropped across a WiFi blip.
    """
    udid = "WIFI-U1"
    snap = {
        "kind": "multi_stop",
        "args": {"waypoints": [[1.0, 2.0], [3.0, 4.0]]},
        "current_pos": [1.1, 2.1],
        "segment_index": 1,
        "lap_count": 0,
        "user_waypoint_next": 2,
        "distance_traveled": 500.0,
        "speed_was_applied": False,
        "random_walk_count": 0,
    }
    old_eng = _FakeEngine(snapshot=snap)
    new_eng = _FakeEngine(snapshot=None)  # new engine: no snapshot pre-captured

    pub = _CapPublisher()
    reg = _SwappingRegistry(udid, old_eng, new_eng)
    dm = _SwappingDM({udid: object()}, pub, reg)
    resolver = EngineResolver(reg, dm)

    calls = []
    async def op():
        calls.append(1)
        if len(calls) == 1:
            raise DeviceLostError("WiFi blip", reason=DeviceLostError.REASON_TUNNEL_DEAD)
        return "route_resumed"

    result = await resolver.with_recovery(udid, op)
    assert result == "route_resumed"

    # Give the create_task a chance to complete.
    await asyncio.sleep(0)

    # The NEW engine must have received resume_from_snapshot with the snapshot
    # that was captured from the OLD engine before the reconnect.
    new_eng.resume_from_snapshot.assert_awaited_once_with(snap)
    # The OLD engine must NOT have had resume_from_snapshot called on it.
    old_eng.resume_from_snapshot.assert_not_awaited()


async def test_with_recovery_no_resume_when_no_route_running():
    """If the engine is idle (capture_resumable_snapshot returns None), with_recovery
    must NOT attempt resume_from_snapshot on the new engine after reconnect.
    This is the non-route-op path (teleport / restore with no running route)."""
    udid = "WIFI-U2"
    old_eng = _FakeEngine(snapshot=None)  # no running route → returns None
    new_eng = _FakeEngine(snapshot=None)

    pub = _CapPublisher()
    reg = _SwappingRegistry(udid, old_eng, new_eng)
    dm = _SwappingDM({udid: object()}, pub, reg)
    resolver = EngineResolver(reg, dm)

    calls = []
    async def op():
        calls.append(1)
        if len(calls) == 1:
            raise DeviceLostError("USB pulled")
        return "ok"

    result = await resolver.with_recovery(udid, op)
    assert result == "ok"
    await asyncio.sleep(0)

    # No resume must be attempted because there was no running route.
    new_eng.resume_from_snapshot.assert_not_awaited()
    old_eng.resume_from_snapshot.assert_not_awaited()
