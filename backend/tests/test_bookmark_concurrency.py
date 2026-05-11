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
