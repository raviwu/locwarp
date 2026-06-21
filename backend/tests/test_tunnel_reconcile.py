"""Characterization: opening a helper tunnel self-heals a stale
"tunnel already exists" (-32003) by close+retry, instead of a misleading 500.

Root cause (pre-existing): the elevated tunnel helper persists its tunnels
across backend restarts (it is a separate root process), so a reconnect — or a
USB<->WiFi switch — finds a leftover tunnel for the udid and the helper raises
``HelperError -32003``. Previously ``device_manager._connect_tunnel`` caught that
in a generic ``except Exception`` and re-raised "請以系統管理員身份執行" → HTTP 500
(misleading: it is NOT an admin-rights problem). Now ``open_tunnel_with_reconcile``
closes the stale tunnel and retries the open exactly once.
"""
import pytest

from core import wifi_tunnel as wt
from services.tunnel_helper_client import HelperError


class _FakeHelper:
    """Duck-typed helper client; first open optionally fails with a code."""

    def __init__(self, *, first_open_error_code=None):
        self._first_open_error_code = first_open_error_code
        self.open_usb_calls = 0
        self.open_wifi_calls = []
        self.close_calls = []

    async def open_usb_tunnel(self, udid):
        self.open_usb_calls += 1
        if self.open_usb_calls == 1 and self._first_open_error_code is not None:
            raise HelperError(code=self._first_open_error_code,
                              message=f"tunnel already exists for {udid}")
        return {"rsd_address": "fd00::1", "rsd_port": 49152}

    async def open_wifi_tunnel(self, udid, ip, port):
        self.open_wifi_calls.append((udid, ip, port))
        if len(self.open_wifi_calls) == 1 and self._first_open_error_code is not None:
            raise HelperError(code=self._first_open_error_code,
                              message=f"tunnel already exists for {udid}")
        return {"rsd_address": "fd00::2", "rsd_port": 50000}

    async def close_tunnel(self, udid):
        self.close_calls.append(udid)
        return {"closed": True}


@pytest.mark.asyncio
async def test_usb_open_reconciles_tunnel_already_exists():
    fake = _FakeHelper(first_open_error_code=-32003)
    wt.set_helper_client(fake)
    try:
        info = await wt.open_tunnel_with_reconcile("open_usb_tunnel", "UDID-X")
    finally:
        wt.set_helper_client(None)
    assert fake.close_calls == ["UDID-X"]   # the stale tunnel was closed
    assert fake.open_usb_calls == 2         # open retried exactly once
    assert info["rsd_address"] == "fd00::1"


@pytest.mark.asyncio
async def test_wifi_open_reconciles_and_passes_ip_port_through():
    fake = _FakeHelper(first_open_error_code=-32003)
    wt.set_helper_client(fake)
    try:
        info = await wt.open_tunnel_with_reconcile(
            "open_wifi_tunnel", "UDID-W", ip="192.168.0.5", port=49152)
    finally:
        wt.set_helper_client(None)
    assert fake.close_calls == ["UDID-W"]
    # retried with the SAME ip/port
    assert fake.open_wifi_calls == [
        ("UDID-W", "192.168.0.5", 49152),
        ("UDID-W", "192.168.0.5", 49152),
    ]
    assert info["rsd_address"] == "fd00::2"


@pytest.mark.asyncio
async def test_other_helper_error_is_not_reconciled():
    fake = _FakeHelper(first_open_error_code=-32002)  # NOT -32003
    wt.set_helper_client(fake)
    try:
        with pytest.raises(HelperError) as ei:
            await wt.open_tunnel_with_reconcile("open_usb_tunnel", "UDID-Y")
    finally:
        wt.set_helper_client(None)
    assert ei.value.code == -32002
    assert fake.close_calls == []     # did NOT close
    assert fake.open_usb_calls == 1   # did NOT retry


@pytest.mark.asyncio
async def test_no_helper_client_raises_runtimeerror():
    wt.set_helper_client(None)
    with pytest.raises(RuntimeError):
        await wt.open_tunnel_with_reconcile("open_usb_tunnel", "UDID-Z")
