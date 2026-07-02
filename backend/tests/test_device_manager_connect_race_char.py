"""Characterization: DeviceManager.connect() must coalesce concurrent same-udid
connects instead of each opening its own helper tunnel.

Two concurrent connect(udid) coroutines for the SAME device both used to pass
the membership check under self._lock (neither has installed yet) and both ran
the heavy autopair+tunnel build. In the real world that means two overlapping
auto-connect triggers (startup discover + usbmux watchdog + full_reconnect)
each open a helper-owned USB tunnel for the same device, and the second build
collides with the first -> helper error -32003 "tunnel already exists".

The fix serializes connect(udid) behind a per-UDID asyncio.Lock
(DeviceManager._connect_locks): the loser blocks on the lock while the winner
builds, then re-checks membership and returns without building a second
tunnel. This test drives the REAL connect() path (it stubs only the heavy
I/O: list_devices, autopair, _connect_tunnel) and asserts the tunnel build
(_connect_tunnel) runs exactly once for two overlapping connect(udid) calls.
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
@pytest.mark.timeout(10)
async def test_connect_same_udid_coalesces_no_duplicate_tunnel(monkeypatch):
    """Two overlapping connect(udid) for the SAME device must build the helper
    tunnel exactly once. Without the per-UDID latch the second call passes the
    membership check while the first is still building and opens a second
    tunnel (real-world: helper error -32003 'tunnel already exists')."""
    monkeypatch.setattr(dm_mod, "list_devices",
                        lambda: _async_value([_Raw("UDID-USB")]))
    monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)

    async def _fake_autopair(udid, autopair=True):
        return _StubLockdown(), False
    monkeypatch.setattr(pair_mod, "autopair_with_recovery", _fake_autopair)

    mgr = DeviceManager()
    build_count = 0
    build_started = asyncio.Semaphore(0)   # released each time a build begins
    release_first = asyncio.Event()        # holds the first build "in flight"

    async def _fake_connect_tunnel(self, udid, lockdown, ios_version):
        nonlocal build_count
        build_count += 1
        build_started.release()
        await release_first.wait()
        return _ActiveConnection(udid=udid, lockdown=lockdown,
                                 ios_version=ios_version, rsd=lockdown)
    monkeypatch.setattr(DeviceManager, "_connect_tunnel",
                        _fake_connect_tunnel, raising=True)

    t1 = asyncio.create_task(mgr.connect("UDID-USB"))
    await build_started.acquire()          # first build is in flight

    t2 = asyncio.create_task(mgr.connect("UDID-USB"))
    # Give t2 ample opportunity to (wrongly) start a SECOND build.
    try:
        await asyncio.wait_for(build_started.acquire(), timeout=0.5)
        second_build_started = True
    except asyncio.TimeoutError:
        second_build_started = False

    assert second_build_started is False   # RED without latch, GREEN with it

    release_first.set()
    await asyncio.gather(t1, t2)

    assert build_count == 1
    assert list(mgr._connections.keys()) == ["UDID-USB"]


def _async_value(value):
    async def _coro():
        return value

    return _coro()
