"""Characterization: DeviceManager.connect() must atomically claim the udid.

Two concurrent connect(udid) coroutines both pass the membership check under
self._lock (neither has installed yet), both run the heavy autopair+tunnel with
NO lock held, then both reinstall. On the buggy code the reinstall is a bare
``self._connections[udid] = conn`` (no pop-displaced) so the second write
silently clobbers the first WITHOUT tearing it down -> an orphaned helper-owned
utun tunnel that leaks until restart.

This test drives the REAL claim/teardown path (it stubs only the heavy I/O:
list_devices, autopair, _connect_tunnel) and asserts (a) exactly one connection
survives and (b) the displaced connection's _teardown_connection ran. It mirrors
test_device_manager_wifi_tunnel_race_char's stubbing approach: source-module
globals via monkeypatch, instance method override for the heavy connect, and a
controllable barrier so both coroutines are guaranteed past the membership check
before either reinstalls.
"""
from __future__ import annotations

import asyncio

import pytest

import core.device_manager as dm_mod
import services.usbmux_pair_records as pair_mod
from core.device_manager import DeviceManager, _ActiveConnection


class _StubLockdown:
    """Minimal stand-in for the lockdown client returned by autopair."""

    def __init__(self):
        self.all_values = {"ProductVersion": "17.5", "DeviceName": "My iPhone"}
        self.closed = False

    async def close(self):
        self.closed = True


class _Raw:
    def __init__(self, serial):
        self.serial = serial
        self.connection_type = "USB"


@pytest.mark.asyncio
async def test_connect_same_udid_concurrent_claims_atomically(monkeypatch):
    monkeypatch.setattr(dm_mod, "list_devices", lambda: _async_value([_Raw("UDID-USB")]))
    monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)

    # autopair_with_recovery is lazily imported INSIDE connect() from its source
    # module, so patch it on services.usbmux_pair_records (not on dm_mod).
    async def _fake_autopair(udid, autopair=True):
        return _StubLockdown(), False

    monkeypatch.setattr(pair_mod, "autopair_with_recovery", _fake_autopair)

    mgr = DeviceManager()

    # Barrier: hold both coroutines inside the heavy connect (after the
    # membership check, before reinstall) until both have arrived. This
    # deterministically reproduces the interleave; without it the two awaits
    # could serialize and the second would see the first already installed.
    both_inside = asyncio.Event()
    arrived = 0
    torn_down: list[_ActiveConnection] = []

    async def _fake_connect_tunnel(self, udid, lockdown, ios_version):
        nonlocal arrived
        conn = _ActiveConnection(
            udid=udid,
            lockdown=lockdown,
            ios_version=ios_version,
            rsd=lockdown,  # so a real teardown has an rsd to close
        )
        arrived += 1
        if arrived >= 2:
            both_inside.set()
        await both_inside.wait()
        return conn

    real_teardown = mgr._teardown_connection

    async def _spy_teardown(udid, conn):
        torn_down.append(conn)
        await real_teardown(udid, conn)

    monkeypatch.setattr(
        DeviceManager, "_connect_tunnel", _fake_connect_tunnel, raising=True
    )
    mgr._teardown_connection = _spy_teardown  # type: ignore[assignment]

    await asyncio.gather(mgr.connect("UDID-USB"), mgr.connect("UDID-USB"))

    # Exactly one live connection remains for the udid.
    assert list(mgr._connections.keys()) == ["UDID-USB"]
    survivor = mgr._connections["UDID-USB"]

    # The displaced connection was torn down (not silently clobbered/leaked).
    assert len(torn_down) == 1, (
        "exactly one of the two concurrent connects must be displaced and "
        "torn down; bare reinstall leaks the loser's tunnel"
    )
    assert torn_down[0] is not survivor
    # The displaced connection's rsd was actually closed by the real teardown.
    assert torn_down[0].rsd.closed is True


def _async_value(value):
    async def _coro():
        return value

    return _coro()
