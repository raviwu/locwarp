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
