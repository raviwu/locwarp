"""Characterization: connect_wifi_tunnel replaces a stale same-udid connection
atomically AND deadlock-free.

The udid claim (pop stale + assign fresh) runs under ``self._lock``; the heavy
teardown of the displaced connection runs AFTER the lock is released via the
lock-free ``_teardown_connection`` helper. The previous A9 implementation called
``self.disconnect(udid)`` *inside* ``self._lock`` — and ``disconnect`` re-takes
the (non-reentrant) ``self._lock``, self-deadlocking the event loop. This test
drives the REAL ``disconnect`` / teardown path (it does NOT stub ``disconnect``),
so it hangs on the buggy code and the ``asyncio.wait_for`` guard turns that hang
into a ``TimeoutError`` failure.
"""
from __future__ import annotations

import asyncio

import pytest

import core.device_manager as dm_mod
from core.device_manager import DeviceManager, _ActiveConnection


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
        self.closed = False

    async def connect(self):
        return None

    async def close(self):
        self.closed = True
        return None


@pytest.mark.asyncio
async def test_connect_wifi_tunnel_replaces_stale_same_udid_atomically(monkeypatch):
    monkeypatch.setattr(dm_mod, "RemoteServiceDiscoveryService", _StubRSD)
    # name-cache / alias writers touch disk; stub them out.
    monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)
    monkeypatch.setattr(dm_mod, "_remember_wifi_alias", lambda *a, **k: None)
    monkeypatch.setattr(dm_mod, "_load_device_name_cache", lambda: {})

    mgr = DeviceManager()

    # Pre-seed a STALE connection for the same udid with a real RSD so the REAL
    # disconnect()/teardown path actually runs (closes the stale RSD). We do NOT
    # stub disconnect — that is the whole point: the stale-replace path must not
    # self-deadlock by re-taking self._lock.
    stale_rsd = _StubRSD(None)
    stale = _ActiveConnection(
        udid="UDID-WIFI",
        lockdown=stale_rsd,
        ios_version="17.5",
        connection_type="Network",
        name="old-iPhone",
        rsd=stale_rsd,
    )
    mgr._connections["UDID-WIFI"] = stale

    # Wrap in wait_for so the d05010b self-deadlock (disconnect() under _lock)
    # surfaces as a TimeoutError instead of hanging the test run forever.
    try:
        info = await asyncio.wait_for(
            mgr.connect_wifi_tunnel("127.0.0.1", 12345), timeout=2.0
        )
    except asyncio.TimeoutError:  # pragma: no cover - only on the buggy code
        pytest.fail(
            "connect_wifi_tunnel self-deadlocked replacing a stale same-udid "
            "connection (disconnect()/teardown awaited while holding _lock — "
            "self._lock is non-reentrant)."
        )

    # The displaced stale connection's RSD was actually torn down (real
    # teardown ran, not a lock-free stub)...
    assert stale_rsd.closed is True
    # ...exactly one live connection remains for the udid, and it is the FRESH
    # one (not the stale object).
    assert mgr._connections["UDID-WIFI"] is not stale
    assert mgr._connections["UDID-WIFI"].connection_type == "Network"
    assert mgr._connections["UDID-WIFI"].rsd is not stale_rsd
    assert info.udid == "UDID-WIFI"
    assert info.connection_type == "Network"
    assert info.is_connected is True


@pytest.mark.asyncio
async def test_connect_wifi_tunnel_fresh_udid_no_teardown(monkeypatch):
    """When there is no prior connection for the udid, nothing is torn down and
    the fresh connection is installed."""
    monkeypatch.setattr(dm_mod, "RemoteServiceDiscoveryService", _StubRSD)
    monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)
    monkeypatch.setattr(dm_mod, "_remember_wifi_alias", lambda *a, **k: None)
    monkeypatch.setattr(dm_mod, "_load_device_name_cache", lambda: {})

    mgr = DeviceManager()
    assert "UDID-WIFI" not in mgr._connections

    info = await asyncio.wait_for(
        mgr.connect_wifi_tunnel("127.0.0.1", 12345), timeout=2.0
    )

    assert info.udid == "UDID-WIFI"
    assert mgr._connections["UDID-WIFI"].connection_type == "Network"
