"""api/location.py _handle_device_lost emits device_disconnected through the
injected EventPublisher (dm._events.publish) instead of `from api.websocket
import broadcast`.

Two guards:

1. A static no-import guard: the source file must contain ZERO
   `from api.websocket import broadcast` lines once Task 18 has migrated
   the call-site to `dm._events.publish`.

2. An async characterization test that `_handle_device_lost(exc, udid)`
   emits the UNCHANGED (type, payload) tuple through a swapped
   _CapPublisher rather than the real WS broadcaster.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import api.location as location_mod

pytestmark = pytest.mark.asyncio


def test_location_module_has_no_websocket_import():
    src = open(location_mod.__file__, encoding="utf-8").read()
    assert "from api.websocket import broadcast" not in src


async def test_handle_device_lost_emits_via_injected_publisher():
    """_handle_device_lost(exc, udid) emits device_disconnected through
    dm._events.publish, not a lazy broadcast import."""
    from main import app_state

    udid = "UDID-DEVICE-LOST-PUB"
    dm = app_state.device_manager

    captured = []

    class _CapPublisher:
        async def publish(self, event):
            etype, data = event
            captured.append((etype, {**data}))

    exc = Exception("device gone")

    fake_connections: dict = {udid: object()}

    async def _fake_disconnect(u):
        # Mimic real disconnect: remove from _connections so remaining_count is 0
        fake_connections.pop(u, None)

    with (
        patch.object(dm, "_events", _CapPublisher()),
        patch.object(dm, "_connections", fake_connections),
        patch.object(dm, "disconnect", side_effect=_fake_disconnect),
        patch.object(
            app_state, "remove_engine", new=AsyncMock(return_value=None)
        ),
        patch.object(app_state, "simulation_engines", {}),
    ):
        result = await location_mod._handle_device_lost(exc, udid)

    # Must return HTTPException(503)
    from fastapi import HTTPException
    assert isinstance(result, HTTPException)
    assert result.status_code == 503

    assert len(captured) == 1
    etype, data = captured[0]
    assert etype == "device_disconnected"
    assert data["udids"] == [udid]
    assert data["reason"] == "device_lost"
    assert data["error"] == "device gone"
    assert data["remaining_count"] == 0


async def test_handle_device_lost_requires_udid():
    """udid is a required positional — the old all-devices fallback is gone."""
    import inspect
    sig = inspect.signature(location_mod._handle_device_lost)
    udid_param = sig.parameters["udid"]
    assert udid_param.default is inspect.Parameter.empty, (
        "_handle_device_lost(exc, udid) must require udid (no None default)"
    )


async def test_handle_device_lost_only_touches_named_udid():
    """Only the failing udid is disconnected — a co-connected device is left alone."""
    from main import app_state

    failing = "UDID-FAILING"
    survivor = "UDID-SURVIVOR"
    dm = app_state.device_manager

    disconnected: list[str] = []
    fake_connections = {failing: object(), survivor: object()}

    async def _fake_disconnect(u):
        disconnected.append(u)
        fake_connections.pop(u, None)

    class _CapPublisher:
        async def publish(self, event):
            pass

    with (
        patch.object(dm, "_events", _CapPublisher()),
        patch.object(dm, "_connections", fake_connections),
        patch.object(dm, "disconnect", side_effect=_fake_disconnect),
        patch.object(app_state, "remove_engine", new=AsyncMock(return_value=None)),
        patch.object(app_state, "simulation_engines", {}),
    ):
        await location_mod._handle_device_lost(Exception("gone"), failing)

    assert disconnected == [failing]
    assert survivor in fake_connections
