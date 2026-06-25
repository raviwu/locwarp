"""Characterization: _per_tunnel_watchdog must thread a DeviceLostError's
reason + last_error into the tunnel_degraded and tunnel_lost WS payloads
instead of hardcoding reason='task_exited'. Deep-equal JSON comparison.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import api.device as device_mod
from services.location_service import DeviceLostError

pytestmark = pytest.mark.asyncio


class _CapPublisher:
    def __init__(self):
        self.events: list[tuple] = []

    async def publish(self, event):
        etype, data = event
        # copy the dict so later mutation can't rewrite history
        self.events.append((etype, {**data}))


async def test_watchdog_threads_device_lost_reason_into_payloads():
    udid = "UDID-WD-REASON"

    # Runner whose monitored task raises a classified DeviceLostError.
    async def _dead_task():
        raise DeviceLostError(
            "WiFi tunnel gone",
            reason=DeviceLostError.REASON_TUNNEL_DEAD,
            last_error="helper reports tunnel for X is gone",
        )

    runner = MagicMock()
    runner.task = asyncio.create_task(_dead_task())
    # No captured target -> watchdog skips the restart loop and goes straight
    # to teardown, so we exercise BOTH tunnel_degraded and tunnel_lost.
    runner.target_ip = None
    runner.target_port = None

    pub = _CapPublisher()
    dm = MagicMock()
    dm._events = pub

    eng_reg = MagicMock()
    eng_reg.simulation_engines = {}

    with (
        patch.object(device_mod, "_dm", return_value=dm),
        patch.object(device_mod, "_engines", return_value=eng_reg),
        patch.dict(device_mod._tunnels, {udid: runner}, clear=False),
        patch.object(device_mod, "_cleanup_wifi_connection_for", new=AsyncMock(return_value=True)),
    ):
        await device_mod._per_tunnel_watchdog(udid, runner)

    by_type = {etype: data for etype, data in pub.events}
    assert by_type["tunnel_degraded"] == {
        "udid": udid,
        "reason": DeviceLostError.REASON_TUNNEL_DEAD,
        "last_error": "helper reports tunnel for X is gone",
        "attempt": 1,
        "max_attempts": 3,
        "next_delay_s": 3.0,
    }
    assert by_type["tunnel_lost"] == {
        "udid": udid,
        "reason": DeviceLostError.REASON_TUNNEL_DEAD,
        "last_error": "helper reports tunnel for X is gone",
    }


async def test_watchdog_clean_exit_keeps_task_exited_shape():
    """A clean (non-DeviceLostError) task exit keeps the legacy payload shape:
    reason='task_exited', no last_error key."""
    udid = "UDID-WD-CLEAN"

    async def _clean_task():
        return  # tunnel poll loop returns when helper says gone

    runner = MagicMock()
    runner.task = asyncio.create_task(_clean_task())
    runner.target_ip = None
    runner.target_port = None

    pub = _CapPublisher()
    dm = MagicMock()
    dm._events = pub
    eng_reg = MagicMock()
    eng_reg.simulation_engines = {}

    with (
        patch.object(device_mod, "_dm", return_value=dm),
        patch.object(device_mod, "_engines", return_value=eng_reg),
        patch.dict(device_mod._tunnels, {udid: runner}, clear=False),
        patch.object(device_mod, "_cleanup_wifi_connection_for", new=AsyncMock(return_value=True)),
    ):
        await device_mod._per_tunnel_watchdog(udid, runner)

    by_type = {etype: data for etype, data in pub.events}
    assert by_type["tunnel_degraded"] == {
        "udid": udid,
        "reason": "task_exited",
        "attempt": 1,
        "max_attempts": 3,
        "next_delay_s": 3.0,
    }
    assert by_type["tunnel_lost"] == {"udid": udid, "reason": "task_exited"}
