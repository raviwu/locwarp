"""Characterization: WifiTunnelService.run_watchdog threads a DeviceLostError's
reason+last_error into tunnel_degraded/tunnel_lost (deep-equal), and a clean exit
keeps reason='task_exited' with NO last_error key. Real task, no stubbing of the
method under test; teardown skips the restart loop (no target ip/port).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.location_service import DeviceLostError
from services.wifi_tunnel_service import WifiTunnelService

pytestmark = pytest.mark.asyncio


class _CapPublisher:
    def __init__(self):
        self.events: list[tuple] = []
    async def publish(self, event):
        etype, data = event
        self.events.append((etype, {**data}))


def _make_service(*, tunnels, publish):
    return WifiTunnelService(
        tunnels=tunnels,
        tunnels_lock=asyncio.Lock(),
        tunnel_watchdogs={},
        engines_for=lambda udid: None,            # no sim engine
        attempt_restart=AsyncMock(return_value=False),
        cleanup_wifi=AsyncMock(return_value=True),
        publish=publish,
        logger=MagicMock(),
        sim_state_disconnected=None,
        restart_backoff=(3.0, 6.0, 12.0),
    )


async def test_run_watchdog_threads_device_lost_reason():
    udid = "UDID-WD-REASON"
    async def _dead_task():
        raise DeviceLostError(
            "WiFi tunnel gone",
            reason=DeviceLostError.REASON_TUNNEL_DEAD,
            last_error="helper reports tunnel for X is gone",
        )
    runner = MagicMock()
    runner.task = asyncio.create_task(_dead_task())
    runner.target_ip = None
    runner.target_port = None
    pub = _CapPublisher()
    tunnels = {udid: runner}
    svc = _make_service(tunnels=tunnels, publish=pub.publish)
    await svc.run_watchdog(udid, runner)
    by_type = {e: d for e, d in pub.events}
    assert by_type["tunnel_degraded"] == {
        "udid": udid,
        "reason": DeviceLostError.REASON_TUNNEL_DEAD,
        "last_error": "helper reports tunnel for X is gone",
    }
    assert by_type["tunnel_lost"] == {
        "udid": udid,
        "reason": DeviceLostError.REASON_TUNNEL_DEAD,
        "last_error": "helper reports tunnel for X is gone",
    }


async def test_run_watchdog_clean_exit_keeps_task_exited_shape():
    udid = "UDID-WD-CLEAN"
    async def _clean_task():
        return
    runner = MagicMock()
    runner.task = asyncio.create_task(_clean_task())
    runner.target_ip = None
    runner.target_port = None
    pub = _CapPublisher()
    svc = _make_service(tunnels={udid: runner}, publish=pub.publish)
    await svc.run_watchdog(udid, runner)
    by_type = {e: d for e, d in pub.events}
    assert by_type["tunnel_degraded"] == {"udid": udid, "reason": "task_exited"}
    assert by_type["tunnel_lost"] == {"udid": udid, "reason": "task_exited"}
