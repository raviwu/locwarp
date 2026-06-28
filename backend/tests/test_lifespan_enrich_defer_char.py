"""Characterization: lifespan startup runs bookmark geo-enrichment.

Win 1 moves enrich_all() OFF the awaited critical path (spawned via
asyncio.to_thread) but the end state is identical — enrich_all must still
be invoked exactly once during startup, and the server must reach `yield`
without awaiting it inline. We drive the REAL lifespan with the real
app_state.bookmark_manager (a real BookmarkManager built by load_state),
and spy on enrich_all via a call-counter wrapper installed AFTER load_state
rebuilds the manager.
"""
from __future__ import annotations

import asyncio

import pytest

from main import lifespan, app_state, helper_client

pytestmark = pytest.mark.asyncio


async def test_lifespan_invokes_enrich_all_during_startup(monkeypatch):
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

    async def fake_discover():
        return []

    async def fake_disconnect_all():
        return None

    monkeypatch.setattr(app_state.device_manager, "discover_devices", fake_discover)
    monkeypatch.setattr(app_state.device_manager, "disconnect_all", fake_disconnect_all)

    app_state.bookmark_manager = None
    app_state.route_manager = None

    calls = {"n": 0}

    # Spy: count enrich_all invocations regardless of HOW startup defers it
    # (inline pre-change, or via the _deferred_enrich async wrapper that warms
    # the resolver off-thread then sweeps on the loop post-change). load_state
    # rebuilds bookmark_manager, so install the spy by wrapping the class
    # method — it survives the rebuild.
    from services.bookmarks import BookmarkManager
    real_enrich = BookmarkManager.enrich_all

    def counting_enrich(self):
        calls["n"] += 1
        return real_enrich(self)

    monkeypatch.setattr(BookmarkManager, "enrich_all", counting_enrich)

    async with lifespan(None):
        # Inside the yield window the server is "serving". enrich_all may be
        # inline (pre-change) or spawned (post-change); allow the spawned
        # to_thread task a moment to run.
        for _ in range(50):
            if calls["n"] >= 1:
                break
            await asyncio.sleep(0.01)
        assert calls["n"] >= 1, "enrich_all must run during startup"
        assert app_state.bookmark_manager is not None


async def test_load_state_does_not_enrich_inline(monkeypatch):
    """Win 1 invariant: load_state() builds the manager but does NOT call
    enrich_all inline — enrichment is spawned by the lifespan instead. Calling
    load_state() directly (outside lifespan) therefore leaves enrich_all
    un-invoked."""
    from services.bookmarks import BookmarkManager

    calls = {"n": 0}
    real_enrich = BookmarkManager.enrich_all

    def counting_enrich(self):
        calls["n"] += 1
        return real_enrich(self)

    monkeypatch.setattr(BookmarkManager, "enrich_all", counting_enrich)

    app_state.bookmark_manager = None
    app_state.route_manager = None
    await app_state.load_state()

    assert calls["n"] == 0, "load_state must NOT call enrich_all inline (Win 1: deferred)"
    assert app_state.bookmark_manager is not None, "store load stays pre-yield"


async def test_deferred_enrich_broadcasts_when_changed(monkeypatch):
    """D1: after the deferred sweep fills geo fields (changed > 0), the
    lifespan must broadcast a bookmarks_changed event so the UI refreshes —
    the watcher cannot (its self-write is mtime-suppressed in _watcher_tick)."""
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

    async def fake_discover():
        return []

    async def fake_disconnect_all():
        return None

    monkeypatch.setattr(app_state.device_manager, "discover_devices", fake_discover)
    monkeypatch.setattr(app_state.device_manager, "disconnect_all", fake_disconnect_all)

    app_state.bookmark_manager = None
    app_state.route_manager = None

    # Force a positive changed-count so the broadcast condition fires.
    from services.bookmarks import BookmarkManager
    monkeypatch.setattr(BookmarkManager, "enrich_all", lambda self: 3)

    events: list[tuple[str, dict]] = []

    async def spy_broadcast(event_type, data):
        events.append((event_type, data))

    # _deferred_enrich does `from api.websocket import broadcast` at call time,
    # so patch the source attribute.
    monkeypatch.setattr("api.websocket.broadcast", spy_broadcast)

    async with lifespan(None):
        for _ in range(50):
            if any(e[0] == "bookmarks_changed" for e in events):
                break
            await asyncio.sleep(0.01)

    enrich_events = [e for e in events if e[0] == "bookmarks_changed"]
    assert enrich_events, "deferred enrich must broadcast bookmarks_changed when changed > 0"
    assert enrich_events[0][1] == {"reason": "enrich"}


async def test_deferred_enrich_no_broadcast_when_unchanged(monkeypatch):
    """D1: an idempotent sweep (changed == 0) must NOT broadcast — avoids a
    spurious UI refresh on every cold start of an already-enriched store."""
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

    async def fake_discover():
        return []

    async def fake_disconnect_all():
        return None

    monkeypatch.setattr(app_state.device_manager, "discover_devices", fake_discover)
    monkeypatch.setattr(app_state.device_manager, "disconnect_all", fake_disconnect_all)

    app_state.bookmark_manager = None
    app_state.route_manager = None

    from services.bookmarks import BookmarkManager
    monkeypatch.setattr(BookmarkManager, "enrich_all", lambda self: 0)

    events: list[tuple[str, dict]] = []

    async def spy_broadcast(event_type, data):
        events.append((event_type, data))

    monkeypatch.setattr("api.websocket.broadcast", spy_broadcast)

    async with lifespan(None):
        # Give the spawned _deferred_enrich task time to run to completion.
        await asyncio.sleep(0.1)

    enrich_events = [e for e in events if e == ("bookmarks_changed", {"reason": "enrich"})]
    assert enrich_events == [], "no enrich broadcast expected when changed == 0"
