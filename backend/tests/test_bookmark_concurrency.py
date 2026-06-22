# Note: every ``create_bookmark`` call below runs ``enrich_bookmark`` via the
# offline geo resolver, so coordinates like (1.0, 1.0) / (2.0, 2.0) come back
# with concrete country_code / timezone / city / region (the nearest GeoNames
# city). These tests don't assert on those fields — they're orthogonal to
# concurrency — but be aware they're populated if you ever add assertions.
from datetime import datetime, timezone
from pathlib import Path

from services.bookmarks import BookmarkManager


def _patch_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", tmp_path / "bookmarks.json")


def test_manager_records_mtime_after_load(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"
    bookmarks.write_text(
        '{"categories":[{"id":"default","name":"x","color":"#fff","sort_order":0,"created_at":"2026-01-01T00:00:00+00:00"}],"bookmarks":[]}',
        encoding="utf-8",
    )
    mgr = BookmarkManager()
    assert mgr._last_loaded_mtime == bookmarks.stat().st_mtime
    assert len(mgr.store.categories) == 1


def test_manager_records_mtime_after_save(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    mgr = BookmarkManager()
    bm = mgr.create_bookmark(name="A", lat=1.0, lng=2.0)
    assert (tmp_path / "bookmarks.json").exists()
    assert mgr._last_loaded_mtime == (tmp_path / "bookmarks.json").stat().st_mtime
    assert any(b.id == bm.id for b in mgr.store.bookmarks)


import json as _json


def test_save_merges_when_disk_changed_externally(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"

    # Manager A creates a bookmark
    mgr_a = BookmarkManager()
    mgr_a.create_bookmark(name="A1", lat=1.0, lng=1.0)

    # Simulate device B writing a different bookmark to disk
    payload = _json.loads(bookmarks.read_text(encoding="utf-8"))
    payload["bookmarks"].append({
        "id": "external-id",
        "name": "from-device-b",
        "lat": 9.0,
        "lng": 9.0,
        "address": "",
        "category_id": "default",
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_used_at": "2026-01-01T00:00:00+00:00",
        "country_code": "",
    })
    bookmarks.write_text(_json.dumps(payload), encoding="utf-8")
    # Force a newer mtime than what mgr_a recorded
    import os
    os.utime(bookmarks, (mgr_a._last_loaded_mtime + 10, mgr_a._last_loaded_mtime + 10))

    # Now A creates another bookmark — _save should merge in B's entry
    mgr_a.create_bookmark(name="A2", lat=2.0, lng=2.0)

    final = _json.loads(bookmarks.read_text(encoding="utf-8"))
    ids = {b["id"] for b in final["bookmarks"]}
    names = {b["name"] for b in final["bookmarks"]}
    assert "external-id" in ids
    assert {"A1", "A2", "from-device-b"} <= names


def test_save_merges_concurrent_external_addition(tmp_path, monkeypatch):
    """Two managers on the same file, each adding a distinct bookmark.

    Reproduces symptom 2: B's _save must read-merge-write so A's
    already-written bookmark is not clobbered."""
    _patch_paths(tmp_path, monkeypatch)
    a = BookmarkManager()
    b = BookmarkManager()
    a.create_bookmark(name="from-A", lat=1.0, lng=1.0)   # a._save writes file
    b.create_bookmark(name="from-B", lat=2.0, lng=2.0)   # b._save must keep from-A
    names = {bm.name for bm in BookmarkManager().list_bookmarks()}
    assert names == {"from-A", "from-B"}


def test_delete_propagates_and_does_not_resurrect(tmp_path, monkeypatch):
    """Reproduces symptom 3: a category deleted on A must stay deleted even
    after B (which still had it) read-merge-writes an unrelated change."""
    _patch_paths(tmp_path, monkeypatch)
    a = BookmarkManager()
    cat = a.create_category("Trip")
    b = BookmarkManager()                        # b loads the file, also has "Trip"
    a.delete_category(cat.id)                    # a writes file w/ tombstone
    b.create_bookmark(name="unrelated", lat=1.0, lng=1.0)  # b read-merge-writes
    cats = {c.id for c in BookmarkManager().list_categories()}
    assert cat.id not in cats


def test_reconcile_loads_external_bookmark(tmp_path, monkeypatch):
    """Directly exercise _reconcile_from_disk — bypasses watcher timing."""
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"

    mgr = BookmarkManager()
    mgr.create_bookmark(name="local", lat=1.0, lng=1.0)

    payload = _json.loads(bookmarks.read_text(encoding="utf-8"))
    payload["bookmarks"].append({
        "id": "remote-id",
        "name": "remote",
        "lat": 5.0,
        "lng": 5.0,
        "address": "",
        "category_id": "default",
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_used_at": "2026-01-01T00:00:00+00:00",
        "country_code": "",
    })
    bookmarks.write_text(_json.dumps(payload), encoding="utf-8")

    mgr._reconcile_from_disk()

    names = {b.name for b in mgr.store.bookmarks}
    assert "local" in names
    assert "remote" in names


def test_reconcile_ignores_zero_byte_placeholder(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"
    mgr = BookmarkManager()
    mgr.create_bookmark(name="local", lat=1.0, lng=1.0)
    bookmarks.write_text("", encoding="utf-8")  # iCloud placeholder
    mgr._reconcile_from_disk()
    assert any(b.name == "local" for b in mgr.store.bookmarks)


def test_watcher_tick_reloads_and_fires_callback(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"
    mgr = BookmarkManager()
    mgr.create_bookmark(name="A", lat=1.0, lng=1.0)

    payload = _json.loads(bookmarks.read_text(encoding="utf-8"))
    payload["bookmarks"].append({
        "id": "ext", "name": "B-side", "lat": 9.0, "lng": 9.0,
        "address": "", "category_id": "default",
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_used_at": "2026-01-01T00:00:00+00:00",
        "country_code": "",
    })
    bookmarks.write_text(_json.dumps(payload), encoding="utf-8")
    import os
    os.utime(bookmarks, (mgr._last_loaded_mtime + 10, mgr._last_loaded_mtime + 10))

    called = []
    mgr._on_external_change = lambda: called.append(True)
    mgr._watcher_tick()

    assert called == [True]
    assert any(b.name == "B-side" for b in mgr.store.bookmarks)


def test_watcher_tick_ignores_self_echo(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    mgr = BookmarkManager()
    mgr.create_bookmark(name="A", lat=1.0, lng=1.0)
    called = []
    mgr._on_external_change = lambda: called.append(True)
    mgr._watcher_tick()
    assert called == []


def test_watcher_handler_triggers_on_moved_to_target(tmp_path, monkeypatch):
    """Atomic rename of a sibling temp file onto bookmarks.json must fire reconcile.

    iCloud, watchdog-on-macOS, and most editors write a temp file and
    rename it into place. The resulting watchdog event is a FileMovedEvent
    whose src_path is the temp name and dest_path is the real file. The
    handler must recognise this as a write to our target.

    Capture strategy: monkeypatch ``services.bookmarks._watcher_schedule`` to
    intercept the REAL nested ``_Handler`` instance that ``start_watcher``
    passes to it — no re-implementation.  If the handler logic relocates away
    from ``start_watcher`` the capture will be None and the assertion fails,
    which is exactly the signal we want.
    """
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"
    mgr = BookmarkManager()
    mgr.create_bookmark(name="local", lat=1.0, lng=1.0)

    from unittest.mock import MagicMock, sentinel

    # Capture the real handler that start_watcher passes to _watcher_schedule.
    captured = []

    def _fake_schedule(handler, parent):
        captured.append(handler)
        return sentinel.watch  # dummy ObservedWatch — unschedule is also patched

    monkeypatch.setattr("services.bookmarks._watcher_schedule", _fake_schedule)
    monkeypatch.setattr("services.bookmarks._watcher_unschedule", lambda w: None)

    # Patch _schedule_reconcile BEFORE start_watcher so the captured handler
    # already holds the patched manager method.
    fired = []
    monkeypatch.setattr(mgr, "_schedule_reconcile", lambda: fired.append(True))

    mgr.start_watcher(on_change=lambda: None)

    assert captured, "start_watcher never called _watcher_schedule"
    real_handler = captured[0]

    fake_event = MagicMock()
    fake_event.is_directory = False
    fake_event.src_path = str(tmp_path / ".bookmarks.tmp-abc")
    fake_event.dest_path = str(bookmarks)
    real_handler.on_moved(fake_event)
    assert fired == [True]


def test_two_managers_on_same_file_converge(tmp_path, monkeypatch):
    """Simulate two devices both editing the same bookmarks.json.

    After both have written, the final state contains all edits from both
    sides. merge_stores unions by id; on an id collision the newer
    updated_at wins. Disjoint edits all survive.
    """
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"

    mgr_a = BookmarkManager()
    mgr_a.create_bookmark(name="from-A-1", lat=1.0, lng=1.0)

    mgr_b = BookmarkManager()
    # B has loaded what A wrote
    assert any(b.name == "from-A-1" for b in mgr_b.list_bookmarks())

    mgr_b.create_bookmark(name="from-B-1", lat=2.0, lng=2.0)

    # A now writes a second bookmark; should merge B's bookmark in
    mgr_a.create_bookmark(name="from-A-2", lat=3.0, lng=3.0)

    final = _json.loads(bookmarks.read_text(encoding="utf-8"))
    names = {b["name"] for b in final["bookmarks"]}
    assert names == {"from-A-1", "from-A-2", "from-B-1"}
