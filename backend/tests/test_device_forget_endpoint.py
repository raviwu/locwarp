"""Tests for POST /api/device/{udid}/forget."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_sticky_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.device_manager.STICKY_DENIED_FILE", tmp_path / "sticky_denied.json"
    )
    yield


@pytest.fixture(autouse=True)
def clean_dm_state():
    """Tests mutate the app_state singleton; restore it afterwards."""
    from main import app_state
    dm = app_state.device_manager
    yield
    dm._connections.clear()
    dm.sticky_user_denied.clear()
    app_state.simulation_engines.clear()
    app_state._primary_udid = None
    # The WiFi test inserts a fake TunnelRunner; clear it even when the
    # test fails before the endpoint pops it, so the cap-check in later
    # tests doesn't count a leaked fake runner.
    import api.device as device_mod
    device_mod._tunnels.clear()


def _patch_record_deletes(monkeypatch, deletes: list):
    async def fake_delete_sys(udid):
        deletes.append(f"sys:{udid}")
        return True

    def fake_delete_local(udid):
        deletes.append(f"local:{udid}")
        return True

    monkeypatch.setattr(
        "services.usbmux_pair_records.delete_system_pair_record",
        fake_delete_sys, raising=False,
    )
    monkeypatch.setattr(
        "services.usbmux_pair_records.delete_local_pair_record",
        fake_delete_local, raising=False,
    )


def test_forget_full_flow_for_connected_usb_device(monkeypatch, tmp_path):
    """Connected USB device: unpair called on the session lockdown, session
    torn down, both record deletes called, sticky marked + persisted,
    200 with status=forgotten."""
    from main import app, app_state

    udid = "UDID-FORGET-USB"
    dm = app_state.device_manager

    fake_usb_lockdown = MagicMock()
    fake_usb_lockdown.unpair = AsyncMock()
    conn = MagicMock()
    conn.connection_type = "USB"
    conn.usbmux_lockdown = fake_usb_lockdown
    conn.lockdown = MagicMock()
    dm._connections[udid] = conn
    app_state.simulation_engines[udid] = MagicMock()
    app_state._primary_udid = udid

    disconnected = []

    async def fake_disconnect(u):
        disconnected.append(u)
        dm._connections.pop(u, None)

    monkeypatch.setattr(dm, "disconnect", fake_disconnect)

    deletes: list = []
    _patch_record_deletes(monkeypatch, deletes)

    client = TestClient(app)
    resp = client.post(f"/api/device/{udid}/forget")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "forgotten"
    assert body["udid"] == udid
    assert body["system_cleared"] is True
    assert body["local_cleared"] is True

    fake_usb_lockdown.unpair.assert_awaited_once()
    assert disconnected == [udid]
    assert udid not in app_state.simulation_engines
    assert app_state._primary_udid is None
    assert f"sys:{udid}" in deletes
    assert f"local:{udid}" in deletes
    assert udid in dm.sticky_user_denied
    sticky_file = tmp_path / "sticky_denied.json"
    assert udid in json.loads(sticky_file.read_text())


def test_forget_idempotent_for_unknown_udid(monkeypatch, tmp_path):
    """Forget for a udid with no connection and no records: still 200,
    sticky marked. Re-posting is also 200."""
    from main import app, app_state

    udid = "UDID-NEVER-SEEN"
    deletes: list = []
    _patch_record_deletes(monkeypatch, deletes)

    client = TestClient(app)
    resp1 = client.post(f"/api/device/{udid}/forget")
    resp2 = client.post(f"/api/device/{udid}/forget")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert udid in app_state.device_manager.sticky_user_denied


def test_forget_tears_down_wifi_tunnel(monkeypatch, tmp_path):
    """A udid with a registered TunnelRunner gets the per-udid tunnel
    teardown (runner.stop awaited, registry entry removed)."""
    from main import app, app_state
    import api.device as device_mod

    udid = "UDID-FORGET-WIFI"
    dm = app_state.device_manager

    conn = MagicMock()
    conn.connection_type = "Network"
    conn.usbmux_lockdown = None
    conn.lockdown = MagicMock()
    conn.lockdown.unpair = AsyncMock()
    dm._connections[udid] = conn

    async def fake_disconnect(u):
        dm._connections.pop(u, None)

    monkeypatch.setattr(dm, "disconnect", fake_disconnect)

    runner = MagicMock()
    runner.stop = AsyncMock()
    runner.is_running = MagicMock(return_value=True)
    device_mod._tunnels[udid] = runner

    deletes: list = []
    _patch_record_deletes(monkeypatch, deletes)

    client = TestClient(app)
    resp = client.post(f"/api/device/{udid}/forget")

    assert resp.status_code == 200
    runner.stop.assert_awaited_once()
    assert udid not in device_mod._tunnels


def test_forget_unpair_failure_does_not_block(monkeypatch, tmp_path):
    """lockdown.unpair raising must not abort the flow — records are still
    cleared and the response is still 200."""
    from main import app, app_state

    udid = "UDID-UNPAIR-FAIL"
    dm = app_state.device_manager

    bad_lockdown = MagicMock()
    bad_lockdown.unpair = AsyncMock(side_effect=RuntimeError("unpair exploded"))
    conn = MagicMock()
    conn.connection_type = "USB"
    conn.usbmux_lockdown = bad_lockdown
    conn.lockdown = MagicMock()
    dm._connections[udid] = conn

    async def fake_disconnect(u):
        dm._connections.pop(u, None)

    monkeypatch.setattr(dm, "disconnect", fake_disconnect)

    deletes: list = []
    _patch_record_deletes(monkeypatch, deletes)

    client = TestClient(app)
    resp = client.post(f"/api/device/{udid}/forget")

    assert resp.status_code == 200
    assert f"sys:{udid}" in deletes
    assert udid in dm.sticky_user_denied
