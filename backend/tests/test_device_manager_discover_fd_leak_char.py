"""Characterization: discover_devices() must close the per-device lockdown
client on the SUCCESS path too, not just the except path.

The success branch (currently device_manager.py:378-403) appends a DeviceInfo
but never closes the lockdown returned by create_using_usbmux. discover runs on
every UI refresh / watchdog tick, so the un-closed usbmuxd socket leaks until
the process exits -> eventual "iPhone not detected" until restart. This test
asserts the success-path lockdown is closed exactly once. The except branch
already closes (lines 404-416); we add a second case to lock in that the
try/finally does not double-close.
"""
from __future__ import annotations

import pytest

import core.device_manager as dm_mod
from core.device_manager import DeviceManager


class _Raw:
    def __init__(self, serial, connection_type="USB"):
        self.serial = serial
        self.connection_type = connection_type


class _StubLockdown:
    """Success-path lockdown: every property/method works."""

    def __init__(self):
        self.all_values = {
            "DeviceName": "My iPhone",
            "ProductVersion": "17.5",
            "UniqueDeviceID": "UDID-OK",
        }
        self.close_calls = 0

    async def get_developer_mode_status(self):
        return True

    async def close(self):
        self.close_calls += 1


def _async_value(value):
    async def _coro():
        return value

    return _coro()


@pytest.mark.asyncio
async def test_discover_devices_closes_lockdown_on_success(monkeypatch):
    lk = _StubLockdown()

    monkeypatch.setattr(dm_mod, "list_devices", lambda: _async_value([_Raw("UDID-OK")]))
    monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)

    async def _fake_create(serial, autopair=False):
        return lk

    monkeypatch.setattr(dm_mod, "create_using_usbmux", _fake_create)

    mgr = DeviceManager()
    devices = await mgr.discover_devices()

    # The device is still surfaced...
    assert [d.udid for d in devices] == ["UDID-OK"]
    assert devices[0].name == "My iPhone"
    assert devices[0].developer_mode_enabled is True
    # ...and its lockdown socket was closed exactly once (no leak, no double).
    assert lk.close_calls == 1, (
        "discover_devices leaked the usbmuxd socket on the success path "
        f"(close_calls={lk.close_calls}, expected 1)"
    )
