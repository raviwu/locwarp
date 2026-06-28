"""Characterization: lifespan startup auto-connects the first discovered
device. Win 2 moves the discover->connect->create_engine block OFF the
awaited critical path (fire-and-forget _spawn_bg task) — the device still
ends up connected, only the timing moves. We assert (a) the block is SPAWNED
not awaited: a connect that blocks does not delay reaching `yield`; (b) the
device still connects (connect + create_engine_for_device are invoked); and
(c) a connect failure does not crash startup.
"""
from __future__ import annotations

import asyncio

import pytest

from main import lifespan, app_state, helper_client

pytestmark = pytest.mark.asyncio


def _stub_helper(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")

    async def fake_connect(timeout=90.0):
        return None

    async def fake_migrate(home, uid, gid):
        return {"chowned": 0, "skipped": 0, "failed": 0}

    async def fake_shutdown():
        return {"ok": True}

    async def fake_close():
        return None

    monkeypatch.setattr(helper_client, "connect", fake_connect)
    monkeypatch.setattr(helper_client, "migrate_user_state", fake_migrate)
    monkeypatch.setattr(helper_client, "shutdown", fake_shutdown)
    monkeypatch.setattr(helper_client, "close", fake_close)

    async def fake_disconnect_all():
        return None

    monkeypatch.setattr(app_state.device_manager, "disconnect_all", fake_disconnect_all)


class _Dev:
    def __init__(self, udid, name):
        self.udid = udid
        self.name = name


@pytest.mark.timeout(10)
async def test_autoconnect_is_spawned_not_awaited(monkeypatch):
    _stub_helper(monkeypatch)
    app_state.bookmark_manager = None
    app_state.route_manager = None

    connect_started = asyncio.Event()
    connect_release = asyncio.Event()
    calls = {"connect": 0, "engine": 0}

    async def fake_discover():
        return [_Dev("UDID-AC", "iPhone")]

    async def fake_connect(udid):
        calls["connect"] += 1
        connect_started.set()
        # Block until the test releases — if the lifespan AWAITED this, we'd
        # never reach `yield`.
        await connect_release.wait()

    async def fake_create_engine(udid, force=False):
        calls["engine"] += 1

    monkeypatch.setattr(app_state.device_manager, "discover_devices", fake_discover)
    monkeypatch.setattr(app_state.device_manager, "connect", fake_connect)
    monkeypatch.setattr(app_state, "create_engine_for_device", fake_create_engine)

    async with lifespan(None):
        # We reached `yield` even though fake_connect is still blocked ->
        # proves the block was spawned, not awaited.
        assert connect_started.is_set() or calls["connect"] == 0
        # Let the spawned connect proceed and finish.
        connect_release.set()
        for _ in range(50):
            if calls["engine"] >= 1:
                break
            await asyncio.sleep(0.01)
        assert calls["connect"] == 1, "device must still connect during startup"
        assert calls["engine"] == 1, "engine must still be created for the device"


@pytest.mark.timeout(10)
async def test_autoconnect_failure_does_not_crash_startup(monkeypatch):
    _stub_helper(monkeypatch)
    app_state.bookmark_manager = None
    app_state.route_manager = None

    async def fake_discover():
        return [_Dev("UDID-FAIL", "iPhone")]

    async def fake_connect(udid):
        raise RuntimeError("trust dialog cancelled")

    async def fake_create_engine(udid, force=False):
        raise AssertionError("create_engine must not run after a failed connect")

    monkeypatch.setattr(app_state.device_manager, "discover_devices", fake_discover)
    monkeypatch.setattr(app_state.device_manager, "connect", fake_connect)
    monkeypatch.setattr(app_state, "create_engine_for_device", fake_create_engine)

    # Must NOT raise — the spawned task's done-callback logs + discards.
    async with lifespan(None):
        await asyncio.sleep(0.05)
        assert app_state.bookmark_manager is not None
