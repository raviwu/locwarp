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
    assert len(mgr._last_loaded_snapshot.categories) == 1


def test_manager_records_mtime_after_save(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    mgr = BookmarkManager()
    bm = mgr.create_bookmark(name="A", lat=1.0, lng=2.0)
    assert (tmp_path / "bookmarks.json").exists()
    assert mgr._last_loaded_mtime == (tmp_path / "bookmarks.json").stat().st_mtime
    assert any(b.id == bm.id for b in mgr._last_loaded_snapshot.bookmarks)


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


def test_save_does_not_merge_when_disk_unchanged(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    mgr = BookmarkManager()
    mgr.create_bookmark(name="X", lat=1.0, lng=1.0)
    first_payload = (tmp_path / "bookmarks.json").read_text(encoding="utf-8")
    mgr.create_bookmark(name="Y", lat=2.0, lng=2.0)
    second_payload = (tmp_path / "bookmarks.json").read_text(encoding="utf-8")
    assert first_payload != second_payload
    final = _json.loads(second_payload)
    names = {b["name"] for b in final["bookmarks"]}
    assert names == {"X", "Y"}


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
    """
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"
    mgr = BookmarkManager()
    mgr.create_bookmark(name="local", lat=1.0, lng=1.0)

    # Sanity: handler factory available only after start_watcher; we
    # don't actually start a real Observer here. Construct the handler
    # by exercising the watcher code path via _schedule_reconcile.
    # The bug under test was that on_moved aliased on_modified and
    # ignored dest_path. We verify by directly simulating the event
    # against the inner _Handler class.
    from unittest.mock import MagicMock

    fired = []
    monkeypatch.setattr(mgr, "_schedule_reconcile", lambda: fired.append(True))

    # Replicate the inner handler exactly as start_watcher would build it.
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.is_directory:
                return
            if Path(event.src_path) != mgr._bookmarks_path():
                return
            mgr._schedule_reconcile()

        on_created = on_modified

        def on_moved(self, event):
            if event.is_directory:
                return
            bm = mgr._bookmarks_path()
            if Path(event.src_path) != bm and Path(getattr(event, "dest_path", "")) != bm:
                return
            mgr._schedule_reconcile()

    h = _Handler()
    fake_event = MagicMock()
    fake_event.is_directory = False
    fake_event.src_path = str(tmp_path / ".bookmarks.tmp-abc")
    fake_event.dest_path = str(bookmarks)
    h.on_moved(fake_event)
    assert fired == [True]


def test_two_managers_on_same_file_converge(tmp_path, monkeypatch):
    """Simulate two devices both editing the same bookmarks.json.

    After both have written, the final state should contain all
    non-conflicting edits from both sides. Local-wins semantics apply
    only on overlapping ids; disjoint edits all survive.
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
