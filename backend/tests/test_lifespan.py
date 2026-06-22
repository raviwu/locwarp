"""Lifespan contract: helper handshake is fail-fast.

Per design §5.1, if the elevated helper isn't reachable or rejects our
identity, the backend cannot safely write to ~/.locwarp/ (root-owned
files left from a previous launch). The lifespan must raise SystemExit
so the ASGI process exits — Electron sees that and surfaces a clear
"restart and grant admin" error to the user, rather than coming up in
a half-broken read-only-bookmark state.
"""

import asyncio

import pytest

from main import lifespan, app_state, helper_client
from services.tunnel_helper_client import HelperError


@pytest.mark.asyncio
async def test_lifespan_loads_state_after_helper_handshake(monkeypatch):
    """Happy path: connect + migrate succeed → load_state runs and
    bookmark_manager is non-None inside the yield window."""

    # The helper handshake is darwin-only; force darwin so this test
    # exercises the gated path even on Linux CI / Windows dev.
    monkeypatch.setattr("sys.platform", "darwin")

    async def fake_connect(timeout=90.0):
        return None

    migration_calls = []

    async def fake_migrate(home, uid, gid):
        migration_calls.append((home, uid, gid))
        return {"chowned": 0, "skipped": 5, "failed": 0}

    async def fake_shutdown():
        return {"ok": True}

    async def fake_close():
        return None

    monkeypatch.setattr(helper_client, "connect", fake_connect)
    monkeypatch.setattr(helper_client, "migrate_user_state", fake_migrate)
    monkeypatch.setattr(helper_client, "shutdown", fake_shutdown)
    monkeypatch.setattr(helper_client, "close", fake_close)

    # Stub out device discovery / disconnect so the lifespan body doesn't
    # touch real iOS devices.
    async def fake_discover():
        return []

    async def fake_disconnect_all():
        return None

    monkeypatch.setattr(app_state.device_manager, "discover_devices", fake_discover)
    monkeypatch.setattr(app_state.device_manager, "disconnect_all", fake_disconnect_all)

    # Reset state so we can confirm load_state runs.
    app_state.bookmark_manager = None
    app_state.route_manager = None

    async with lifespan(None):
        assert app_state.bookmark_manager is not None
        assert app_state.route_manager is not None
        assert app_state.backup_service is not None
        running = [
            t for t in asyncio.all_tasks() if "_bookmark_backup_loop" in repr(t.get_coro())
        ]
        assert running, "backup loop task should be running inside the lifespan"

    # After shutdown the backup loop must be cancelled, not leaked.
    await asyncio.sleep(0)
    leaked = [
        t for t in asyncio.all_tasks()
        if "_bookmark_backup_loop" in repr(t.get_coro()) and not t.done()
    ]
    assert not leaked, "backup loop task leaked past shutdown"

    assert migration_calls, "migrate_user_state should have been called"


@pytest.mark.asyncio
async def test_lifespan_exits_when_helper_connect_fails(monkeypatch):
    """If helper connect raises TimeoutError, lifespan must raise SystemExit
    so ASGI shuts down."""

    monkeypatch.setattr("sys.platform", "darwin")

    async def fake_connect(timeout=90.0):
        raise TimeoutError("helper not ready")

    monkeypatch.setattr(helper_client, "connect", fake_connect)

    with pytest.raises(SystemExit):
        async with lifespan(None):
            pytest.fail("should not reach yield")


@pytest.mark.asyncio
async def test_lifespan_exits_on_helper_error_from_migrate(monkeypatch):
    """If helper rejects our identity (HelperError), lifespan must raise
    SystemExit(2) — this is a launcher bug, not a missing helper."""

    monkeypatch.setattr("sys.platform", "darwin")

    async def fake_connect(timeout=90.0):
        return None

    async def fake_migrate(home, uid, gid):
        raise HelperError(-32602, "uid 999 does not match parent_uid 501")

    monkeypatch.setattr(helper_client, "connect", fake_connect)
    monkeypatch.setattr(helper_client, "migrate_user_state", fake_migrate)

    with pytest.raises(SystemExit) as ei:
        async with lifespan(None):
            pytest.fail("should not reach yield")
    assert ei.value.code == 2
