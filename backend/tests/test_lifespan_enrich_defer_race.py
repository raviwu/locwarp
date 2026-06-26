"""Concurrency contract for the deferred geo-enrichment (Task 2 review finding).

Task 2 moved geo enrichment off the awaited boot path. The first naive shape —
``_spawn_bg(asyncio.to_thread(bookmark_manager.enrich_all))`` — ran the
store-MUTATING sweep on a worker thread, concurrently with the serving app,
which has unlocked event-loop-only CRUD ops. That is a genuine data race.

The race-free shape offloads ONLY the heavy geo-DATA LOAD (numpy +
timezonefinder + 2.7MB cities5000.json — touches no store) to a thread, then
runs the fast cached ``enrich_all`` sweep back on the single-threaded event
loop. These tests pin BOTH halves of that contract:

1. the deferred enrich actually completes and fills geo fields (real manager,
   real resolver), and
2. the store-mutating ``enrich_all`` runs on the event-loop thread — never on
   an ``asyncio.to_thread`` worker thread.

Mirrors test_lifespan.py's real-collaborator harness.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from main import lifespan, app_state, helper_client

pytestmark = pytest.mark.asyncio


def _patch_helper_and_device(monkeypatch):
    """Stub the darwin helper handshake + device discovery so the lifespan
    body runs with real bookmark/route managers but no real hardware."""
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


async def test_deferred_enrich_runs_store_mutation_on_event_loop_thread(monkeypatch):
    """The store-mutating enrich_all must run on the SAME thread as the event
    loop (single-threaded → safe against the unlocked CRUD ops). If a future
    regression pushes the whole enrich_all back onto asyncio.to_thread, the
    captured thread id will differ from the loop thread and this fails."""
    _patch_helper_and_device(monkeypatch)

    loop_thread_id = threading.get_ident()

    from services.bookmarks import BookmarkManager

    captured = {"thread_id": None, "calls": 0}
    real_enrich = BookmarkManager.enrich_all

    def spy_enrich(self):
        captured["calls"] += 1
        captured["thread_id"] = threading.get_ident()
        return real_enrich(self)

    monkeypatch.setattr(BookmarkManager, "enrich_all", spy_enrich)

    app_state.bookmark_manager = None
    app_state.route_manager = None

    async with lifespan(None):
        for _ in range(100):
            if captured["calls"] >= 1:
                break
            await asyncio.sleep(0.01)

        assert captured["calls"] >= 1, "deferred enrich_all must run during startup"
        assert captured["thread_id"] == loop_thread_id, (
            "enrich_all (store mutation) must run on the event-loop thread, "
            "not an asyncio.to_thread worker thread (data-race guard)"
        )


async def test_deferred_enrich_populates_geo_fields(monkeypatch):
    """End-to-end: drive the real lifespan + real manager + real offline
    resolver. Inject a bookmark whose geo fields are BLANK directly into the
    store (bypassing create_bookmark's create-time auto-enrich) so this test
    proves the deferred reconciliation SWEEP — not create-time enrichment —
    fills the fields. Confirms the warm-the-resolver-then-sweep design did not
    break enrichment."""
    from models.schemas import Bookmark

    _patch_helper_and_device(monkeypatch)

    app_state.bookmark_manager = None
    app_state.route_manager = None

    async with lifespan(None):
        mgr = app_state.bookmark_manager
        assert mgr is not None

        # Inject a legacy-shaped bookmark (blank geo fields) at well-known land
        # coordinates — Times Square, NYC — directly into the in-memory store.
        bm = Bookmark(
            id="race-test-bookmark",
            name="race-test-times-square",
            lat=40.7580,
            lng=-73.9855,
        )
        assert not bm.country_code and not bm.timezone
        mgr.store.bookmarks.append(bm)

        # The lifespan's deferred task warms the resolver (off-thread) and then
        # runs enrich_all on the loop. Wait for our injected bookmark to fill.
        # If the deferred task hasn't run yet, drive the same on-loop sweep
        # ourselves (the resolver data load is the only slow part).
        for _ in range(100):
            current = next((b for b in mgr.store.bookmarks if b.id == bm.id), None)
            if current is not None and current.country_code:
                break
            mgr.enrich_all()
            await asyncio.sleep(0.01)

        enriched = next((b for b in mgr.store.bookmarks if b.id == bm.id), None)
        assert enriched is not None
        assert enriched.country_code, "country_code should be filled by the enrich sweep"
        assert enriched.timezone, "timezone should be filled by the enrich sweep"
        assert enriched.country_code.lower() == "us"

        # Clean up so we don't pollute the shared on-disk store across tests.
        mgr.delete_bookmark(bm.id)
