"""Characterization: WifiTunnelService.run_watchdog enriches tunnel_degraded
with {attempt, max_attempts, next_delay_s} so the UI can show "attempt 1/3,
retrying in 3s". Backward-compatible additive keys; reason/last_error keep
their existing shape. Real task; no stubbing of the method under test. The
no-target path (target_ip/port None) skips the restart loop, so we exercise
only the single degraded emit here.
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


def _make_service(*, tunnels, publish, restart_backoff):
    return WifiTunnelService(
        tunnels=tunnels,
        tunnels_lock=asyncio.Lock(),
        tunnel_watchdogs={},
        engines_for=lambda udid: None,
        attempt_restart=AsyncMock(return_value=False),
        cleanup_wifi=AsyncMock(return_value=True),
        publish=publish,
        logger=MagicMock(),
        sim_state_disconnected=None,
        restart_backoff=restart_backoff,
    )


async def test_tunnel_degraded_carries_attempt_max_and_next_delay():
    udid = "UDID-DEG-ATTEMPT"

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
    svc = _make_service(tunnels={udid: runner}, publish=pub.publish, restart_backoff=(3.0, 6.0, 12.0))
    await svc.run_watchdog(udid, runner)
    by_type = {e: d for e, d in pub.events}
    assert by_type["tunnel_degraded"] == {
        "udid": udid,
        "reason": DeviceLostError.REASON_TUNNEL_DEAD,
        "last_error": "helper reports tunnel for X is gone",
        "attempt": 1,
        "max_attempts": 3,
        "next_delay_s": 3.0,
    }


async def test_tunnel_degraded_clean_exit_still_carries_attempt_keys():
    udid = "UDID-DEG-CLEAN"

    async def _clean_task():
        return

    runner = MagicMock()
    runner.task = asyncio.create_task(_clean_task())
    runner.target_ip = None
    runner.target_port = None
    pub = _CapPublisher()
    svc = _make_service(tunnels={udid: runner}, publish=pub.publish, restart_backoff=(3.0, 6.0, 12.0))
    await svc.run_watchdog(udid, runner)
    by_type = {e: d for e, d in pub.events}
    assert by_type["tunnel_degraded"] == {
        "udid": udid,
        "reason": "task_exited",
        "attempt": 1,
        "max_attempts": 3,
        "next_delay_s": 3.0,
    }


async def test_tunnel_degraded_empty_backoff_omits_attempt_keys():
    udid = "UDID-DEG-EMPTY"

    async def _clean_task():
        return

    runner = MagicMock()
    runner.task = asyncio.create_task(_clean_task())
    runner.target_ip = None
    runner.target_port = None
    pub = _CapPublisher()
    svc = _make_service(tunnels={udid: runner}, publish=pub.publish, restart_backoff=())
    await svc.run_watchdog(udid, runner)
    by_type = {e: d for e, d in pub.events}
    assert by_type["tunnel_degraded"] == {"udid": udid, "reason": "task_exited"}
