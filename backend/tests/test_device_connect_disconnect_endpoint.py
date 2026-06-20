"""Request-level DI tests for POST /api/device/{udid}/connect and
DELETE /api/device/{udid}/connect.

GAP 3 (LocWarp P1 risk analysis): only POST /api/device/wifi/repair
currently drives Depends(get_device_service) through the real container
via TestClient. The connect / disconnect routes had NO request-level
test, so a broken DI resolution — container None, the wrong
device_service, or a fresh per-call instance instead of the singleton —
could ship undetected.

These tests prove the DI plumbing, NOT device I/O:

- get_device_service resolves to request.app.state.container.device_service,
  the ONE real singleton, whose ._dm IS app_state.device_manager.
- the route awaits the service, which awaits the underlying device-manager
  work with the right udid.

So we patch the device-I/O seam (the AsyncMocks on the real
app_state.device_manager + AppState.create_engine_for_device that
DeviceService.connect/disconnect await) — no hardware / pymobiledevice3
is touched — and additionally assert the resolved service is the real
singleton bound to the same device_manager the patched method lives on.
That singleton-identity assertion is what makes this a regression guard:
if DI ever resolved to a different / per-call DeviceService, the patched
method on the real dm would NOT be the one the route awaited, and the
`assert_awaited_once_with` would fail.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


# ── connect: happy path + DI singleton identity ──


def test_connect_drives_di_singleton_and_awaits_dm_connect(client):
    """POST /{udid}/connect resolves get_device_service to the real
    container singleton and awaits dm.connect(udid) + create_engine."""
    from main import app, app_state

    udid = "UDID-CONNECT-DI"
    dm = app_state.device_manager

    # The device-I/O seam DeviceService.connect awaits: dm.connect +
    # engine_registry.create_engine_for_device. AsyncMock both so no
    # pymobiledevice3 / hardware is touched.
    with (
        patch.object(dm, "connect", new=AsyncMock(return_value=None)) as mock_connect,
        patch.object(
            app_state, "create_engine_for_device", new=AsyncMock(return_value=None)
        ) as mock_engine,
        # Post-connect broadcast path also hits hardware via discover_devices;
        # stub it so the route's best-effort notify stays inert.
        patch.object(dm, "discover_devices", new=AsyncMock(return_value=[])),
        patch("api.websocket.broadcast", new=AsyncMock(return_value=None)),
    ):
        resp = client.post(f"/api/device/{udid}/connect")

        # (a) route returns the documented status
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "connected", "udid": udid}

        # (b) the patched device-manager work was awaited with the right udid
        mock_connect.assert_awaited_once_with(udid)
        mock_engine.assert_awaited_once_with(udid)

        # (c) DI resolved to the ONE real singleton bound to the same dm the
        #     patched method lives on. If it resolved to a wrong / per-call
        #     DeviceService, the route would have awaited a DIFFERENT dm.connect
        #     and (b) above would already have failed — this makes the identity
        #     explicit and load-bearing. (Asserted inside the patch scope so the
        #     AsyncMock is still bound to the real dm.)
        service = app.state.container.device_service
        assert service._dm is app_state.device_manager
        assert service._dm.connect is mock_connect


# ── connect: domain error maps to documented HTTP status ──


def test_connect_unsupported_ios_maps_to_400(client):
    """UnsupportedIosVersionError raised inside the service maps to
    HTTP 400 with code=ios_unsupported (the route's documented mapping)."""
    from main import app_state
    from core.device_manager import UnsupportedIosVersionError

    udid = "UDID-OLD-IOS"
    dm = app_state.device_manager

    # dm.connect raises the domain error; DeviceService.connect propagates it,
    # the route catches UnsupportedIosVersionError → 400.
    with (
        patch.object(
            dm,
            "connect",
            new=AsyncMock(side_effect=UnsupportedIosVersionError("15.0")),
        ),
        # create_engine must NOT be reached once connect raises.
        patch.object(
            app_state, "create_engine_for_device", new=AsyncMock(return_value=None)
        ) as mock_engine,
    ):
        resp = client.post(f"/api/device/{udid}/connect")

    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "ios_unsupported"
    assert detail["ios_version"] == "15.0"
    assert detail["min_version"] == UnsupportedIosVersionError.MIN_VERSION
    mock_engine.assert_not_awaited()


# ── connect: generic exception maps to 500 ──


def test_connect_generic_error_maps_to_500(client):
    """A non-domain exception from the service maps to HTTP 500 with the
    raw message (the route's catch-all branch)."""
    from main import app_state

    udid = "UDID-BOOM"
    dm = app_state.device_manager

    with (
        patch.object(
            dm, "connect", new=AsyncMock(side_effect=RuntimeError("boom-xyz"))
        ),
        patch.object(
            app_state, "create_engine_for_device", new=AsyncMock(return_value=None)
        ),
    ):
        resp = client.post(f"/api/device/{udid}/connect")

    assert resp.status_code == 500, resp.text
    assert "boom-xyz" in resp.json()["detail"]


# ── disconnect: happy path + DI singleton identity ──
# NOTE: disconnect is DELETE /{udid}/connect (not POST) — verified against
# api/device.py:1521 (@router.delete("/{udid}/connect")).


def test_disconnect_drives_di_singleton_and_awaits_dm_disconnect(client):
    """DELETE /{udid}/connect resolves the same singleton and awaits
    dm.disconnect(udid) via the service."""
    from main import app, app_state

    udid = "UDID-DISCONNECT-DI"
    dm = app_state.device_manager

    with (
        patch.object(dm, "disconnect", new=AsyncMock(return_value=None)) as mock_disc,
        patch("api.websocket.broadcast", new=AsyncMock(return_value=None)),
    ):
        resp = client.delete(f"/api/device/{udid}/connect")

        # (a) documented status
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "disconnected", "udid": udid}

        # (b) the patched device-manager work was awaited with the right udid
        mock_disc.assert_awaited_once_with(udid)

        # (c) resolved to the ONE real singleton bound to app_state's dm
        #     (asserted inside the patch scope so the AsyncMock is still bound).
        service = app.state.container.device_service
        assert service._dm is app_state.device_manager
        assert service._dm.disconnect is mock_disc
