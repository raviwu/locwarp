"""Characterization: connect_wifi_tunnel replaces a stale same-udid connection
atomically — the existence-check + disconnect + assignment run under _lock."""
from __future__ import annotations

import pytest

import core.device_manager as dm_mod
from core.device_manager import DeviceManager


class _StubRSD:
    """Stands in for RemoteServiceDiscoveryService((addr, port))."""

    def __init__(self, addr_port):
        self.peer_info = {
            "Properties": {
                "UniqueDeviceID": "UDID-WIFI",
                "OSVersion": "17.5",
                "DeviceClass": "iPhone",
            }
        }
        self.all_values = {"DeviceName": "My iPhone"}

    async def connect(self):
        return None

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_connect_wifi_tunnel_replaces_stale_same_udid_atomically(monkeypatch):
    monkeypatch.setattr(dm_mod, "RemoteServiceDiscoveryService", _StubRSD)
    # name-cache / alias writers touch disk; stub them out.
    monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)
    monkeypatch.setattr(dm_mod, "_remember_wifi_alias", lambda *a, **k: None)
    monkeypatch.setattr(dm_mod, "_load_device_name_cache", lambda: {})

    mgr = DeviceManager()

    # Pre-seed a STALE connection for the same udid; record that it's torn down.
    disconnected: list[str] = []
    stale = object()
    mgr._connections["UDID-WIFI"] = stale

    async def _fake_disconnect(udid):
        disconnected.append(udid)
        mgr._connections.pop(udid, None)

    monkeypatch.setattr(mgr, "disconnect", _fake_disconnect)

    info = await mgr.connect_wifi_tunnel("127.0.0.1", 12345)

    # the stale same-udid conn was disconnected exactly once...
    assert disconnected == ["UDID-WIFI"]
    # ...and replaced by the fresh connection (not the stale object)
    assert mgr._connections["UDID-WIFI"] is not stale
    assert mgr._connections["UDID-WIFI"].connection_type == "Network"
    assert info.udid == "UDID-WIFI"
    assert info.connection_type == "Network"
    assert info.is_connected is True
