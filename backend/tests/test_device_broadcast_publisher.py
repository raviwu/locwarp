"""api/device.py routes all WS broadcasts through the injected
EventPublisher (dm._events.publish) instead of lazy `from api.websocket
import broadcast` calls.

Two guards:

1. A static no-import guard: the source file must contain ZERO
   `from api.websocket import broadcast` lines once Task 17 has migrated
   every call-site to `dm._events.publish`.

2. A route-driven check that DELETE /api/device/{udid}/connect emits the
   SAME (type, payload) tuple as before — now through the injected
   publisher. We swap the live device_manager's `_events` for a capturing
   publisher and patch DeviceService.disconnect so no hardware /
   pymobiledevice3 is touched.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import api.device as device_mod


def test_device_module_has_no_websocket_import():
    src = open(device_mod.__file__, encoding="utf-8").read()
    assert "from api.websocket import broadcast" not in src


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def test_disconnect_emits_device_disconnected_via_injected_publisher(
    client, monkeypatch
):
    """DELETE /{udid}/connect emits the unchanged device_disconnected
    tuple through device_service._dm._events.publish."""
    from main import app_state

    udid = "UDID-DISCONNECT-PUB"
    dm = app_state.device_manager

    captured = []

    class _CapPublisher:
        async def publish(self, event):
            etype, data = event
            captured.append((etype, {**data}))

    monkeypatch.setattr(dm, "_events", _CapPublisher())

    # Keep the device-I/O seam inert: DeviceService.disconnect awaits
    # dm.disconnect + engine_registry.remove_engine; stub both so no
    # hardware is touched.
    with (
        patch.object(dm, "disconnect", new=AsyncMock(return_value=None)),
        patch.object(
            app_state, "remove_engine", new=AsyncMock(return_value=None)
        ),
    ):
        resp = client.delete(f"/api/device/{udid}/connect")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "disconnected", "udid": udid}

    assert (
        "device_disconnected",
        {"udid": udid, "udids": [udid], "reason": "user"},
    ) in captured
