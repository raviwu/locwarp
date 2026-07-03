"""Characterization: DeviceManager._connect_tunnel must bound the RSD connect
and classify its failure.

Real-world bug (finding #4, 12h log 2026-07-03): a redundant connect received a
stale/superseded tunnel address whose transport was dead; the unbounded
``rsd.connect()`` hung ~75s on the OS TCP default, then the bare ``except`` at
device_manager.py wrapped the ``TimeoutError`` into a misleading
"請以系統管理員身份執行 LocWarp" RuntimeError with no ``raise ... from``.

This locks in: (1) a bounded RSD connect, (2) a transport/timeout failure is NOT
reported as a privilege problem, and (3) the true cause is chained.
"""
import asyncio

import pytest

import core.device_manager as dm_mod
import core.wifi_tunnel as wt_mod
from core.device_manager import DeviceManager


class _HangingRSD:
    """An RSD whose connect() never completes (models a dead tunnel address)."""

    def __init__(self, addr):
        self.addr = addr

    async def connect(self):
        await asyncio.sleep(3600)


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_connect_tunnel_rsd_timeout_is_classified_not_privilege(monkeypatch):
    # Helper present so we pass the "_helper_client is None" guard.
    monkeypatch.setattr(wt_mod, "_helper_client", object(), raising=False)

    async def _fake_open(method, udid, **kwargs):
        return {"rsd_address": "fd00::1", "rsd_port": 12345}

    monkeypatch.setattr(wt_mod, "open_tunnel_with_reconcile", _fake_open, raising=False)
    monkeypatch.setattr(dm_mod, "RemoteServiceDiscoveryService", _HangingRSD)
    # Shrink the bound so the test does not actually wait the full timeout.
    monkeypatch.setattr(dm_mod, "RSD_CONNECT_TIMEOUT_S", 0.1, raising=False)

    mgr = DeviceManager()
    with pytest.raises(RuntimeError) as ei:
        await mgr._connect_tunnel("UDID-STALE", object(), "26.5")

    msg = str(ei.value)
    # Must NOT blame privileges for a plain transport timeout.
    assert "系統管理員" not in msg
    assert "administrator" not in msg.lower()
    # Should name the real problem (stale/timed-out tunnel).
    assert ("tunnel" in msg.lower()) or ("逾時" in msg) or ("timeout" in msg.lower())
    # The true cause must be chained, not swallowed.
    assert isinstance(ei.value.__cause__, (asyncio.TimeoutError, TimeoutError))
