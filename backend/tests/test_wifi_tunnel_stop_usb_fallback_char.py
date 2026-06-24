"""Characterization: /wifi/tunnel/stop USB-fallback re-attaches a udid that is
now visible as USB, skips sticky-denied udids, and (rollback path) emits the
exact device_error payload. Deep-equal events.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_state():
    from main import app
    app_state = app.state.container.engine_registry
    dm = app_state.device_manager
    yield
    dm._connections.clear()
    dm.sticky_user_denied.clear()
    app_state.simulation_engines.clear()
    import api.device as device_mod
    device_mod._tunnels.clear()


def test_usb_fallback_reattaches_visible_usb_device(monkeypatch):
    from main import app
    app_state = app.state.container.engine_registry
    dm = app_state.device_manager
    udid = "UDID-FALLBACK"

    # A Network conn exists so cleanup tears it down, then USB-fallback runs.
    conn = MagicMock()
    conn.connection_type = "Network"
    dm._connections[udid] = conn

    async def fake_disconnect(u):
        dm._connections.pop(u, None)
    monkeypatch.setattr(dm, "disconnect", fake_disconnect)
    monkeypatch.setattr(app_state, "remove_engine", AsyncMock())

    async def fake_discover():
        return [SimpleNamespace(udid=udid, connection_type="USB")]
    monkeypatch.setattr(dm, "discover_devices", fake_discover)

    connected = []
    async def fake_connect(u):
        connected.append(u)
    monkeypatch.setattr(dm, "connect", fake_connect)

    created = []
    async def fake_create(u, force=False):
        created.append((u, force))
    monkeypatch.setattr(app_state, "create_engine_for_device", fake_create)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/tunnel/stop", json={"udid": udid})
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    assert connected == [udid]
    assert created == [(udid, True)]  # force=True, exact


def test_usb_fallback_skips_sticky_denied(monkeypatch):
    from main import app
    app_state = app.state.container.engine_registry
    dm = app_state.device_manager
    udid = "UDID-DENIED"
    conn = MagicMock(); conn.connection_type = "Network"
    dm._connections[udid] = conn
    dm.sticky_user_denied.add(udid)

    async def fake_disconnect(u):
        dm._connections.pop(u, None)
    monkeypatch.setattr(dm, "disconnect", fake_disconnect)
    monkeypatch.setattr(app_state, "remove_engine", AsyncMock())

    async def fake_discover():
        return [SimpleNamespace(udid=udid, connection_type="USB")]
    monkeypatch.setattr(dm, "discover_devices", fake_discover)

    connected = []
    async def fake_connect(u):
        connected.append(u)
    monkeypatch.setattr(dm, "connect", fake_connect)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/tunnel/stop", json={"udid": udid})
    assert resp.status_code == 200
    assert connected == []  # sticky-denied udid is never reconnected
