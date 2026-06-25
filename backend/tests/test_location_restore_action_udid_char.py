"""Fix 4 characterization: /restore must capture action_udid AFTER _engine()
resolves, not before.

Scenario: udid=None in the request, _primary_udid=None at entry (no prior
engine), but one live entry in dm._connections (lazy-resolved by _engine()).
When eng.restore() raises DeviceLostError, cleanup_device_lost must tear
down the RESOLVED udid — not no-op with udids:[].
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


def test_restore_device_lost_with_null_primary_udid_cleans_resolved_device(client):
    """Fix 4: /restore with no udid + _primary_udid=None + one live connection.

    Before the fix: action_udid was captured as None (get_primary_udid()
    returned None before _engine() ran), so cleanup_device_lost got udid=None,
    lost_udids=[], and broadcast device_disconnected with udids:[].

    After the fix: _engine() is called first (setting _primary_udid to the
    resolved udid), then action_udid = None or get_primary_udid() = resolved
    udid, so cleanup tears down the actual device.
    """
    from main import app_state

    resolved_udid = "UDID-RESTORE-FIX4"
    dm = app_state.device_manager

    fake_engine = MagicMock()
    fake_engine.restore = AsyncMock(
        side_effect=DeviceLostError("disconnected", reason=DeviceLostError.REASON_USB_GONE)
    )

    # _engine() must be able to resolve the udid.  We patch _engine to:
    # 1. set _primary_udid (simulating what create_engine_for_device does)
    # 2. return the fake_engine
    resolved_once = [False]
    _orig_primary = app_state._primary_udid  # save to restore

    async def fake_engine_resolver(u=None, registry=None):
        # Simulate _engine() setting the primary udid on first call.
        if not resolved_once[0]:
            app_state._primary_udid = resolved_udid
            resolved_once[0] = True
        return fake_engine

    # Track what disconnect is called with.
    disconnected_udids: list = []
    fake_connections = {resolved_udid: object()}

    async def _fake_disconnect(u):
        disconnected_udids.append(u)
        fake_connections.pop(u, None)

    # Capture the WS broadcast payload.
    published_events: list = []

    class _CapPublisher:
        async def publish(self, event):
            published_events.append(event)

    with (
        patch("api.location._engine", fake_engine_resolver),
        patch.object(dm, "_connections", fake_connections),
        patch.object(dm, "_events", _CapPublisher()),
        patch.object(dm, "disconnect", side_effect=_fake_disconnect),
        patch.object(dm, "full_reconnect", new=AsyncMock(return_value=False)),
        patch.object(app_state, "remove_engine", new=AsyncMock(return_value=None)),
        patch.object(app_state, "simulation_engines", {}),
        patch.object(app_state, "_primary_udid", None),
    ):
        resp = client.post("/api/location/restore")  # no udid in request

    assert resp.status_code == 503, f"Expected 503, got {resp.status_code}: {resp.json()}"
    body = resp.json()
    assert body["detail"]["code"] == "device_lost"

    # The resolved udid must have been disconnected — NOT empty cleanup.
    assert resolved_udid in disconnected_udids, (
        f"disconnect was not called for resolved udid {resolved_udid!r}; "
        f"called for: {disconnected_udids}"
    )

    # The WS broadcast must carry the resolved udid, not udids:[].
    device_disconnected_events = [
        e for e in published_events if isinstance(e, tuple) and e[0] == "device_disconnected"
    ]
    assert device_disconnected_events, "device_disconnected event must be published"
    payload = device_disconnected_events[0][1]
    assert resolved_udid in payload.get("udids", []), (
        f"device_disconnected broadcast must carry {resolved_udid!r}; got {payload}"
    )
