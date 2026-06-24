"""Pin the api/location.py recovery BOUNDARY after the EngineResolver lift:
the controller is the ONLY place HTTPException is built. A DeviceLostError
from the teleport op must surface as the frozen 503 device_lost body.
Real app + TestClient; the engine + dm are doubles that genuinely fail.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from services.location_service import DeviceLostError

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def test_teleport_device_lost_surfaces_frozen_503(client):
    from main import app_state

    udid = "UDID-TELE-LOST"
    dm = app_state.device_manager

    fake_engine = MagicMock()
    fake_engine.current_position = None
    fake_engine.teleport = AsyncMock(
        side_effect=DeviceLostError("gone", reason=DeviceLostError.REASON_USB_GONE)
    )

    async def fake_resolver(u=None, registry=None):
        return fake_engine

    fake_connections = {udid: object()}

    async def _fake_disconnect(u):
        fake_connections.pop(u, None)

    class _CapPublisher:
        async def publish(self, event):
            pass

    cooldown = app_state.cooldown_timer
    with (
        patch("api.location._engine", fake_resolver),
        patch.object(dm, "_connections", fake_connections),
        patch.object(dm, "_events", _CapPublisher()),
        patch.object(dm, "disconnect", side_effect=_fake_disconnect),
        patch.object(dm, "full_reconnect", new=AsyncMock(return_value=False)),
        patch.object(app_state, "remove_engine", new=AsyncMock(return_value=None)),
        patch.object(app_state, "simulation_engines", {}),
        patch.object(cooldown, "enabled", False),
        patch.object(app_state, "_primary_udid", udid),
    ):
        resp = client.post("/api/location/teleport",
                           json={"lat": 25.0, "lng": 121.0, "udid": udid})

    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["code"] == "device_lost"
    assert body["detail"]["reason"] == DeviceLostError.REASON_USB_GONE
    assert body["detail"]["message"] == "USB 已拔除,請重新插上後再操作"
