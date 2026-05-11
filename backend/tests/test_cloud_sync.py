"""Tests for cloud sync migration and rollback."""

import pytest
from pathlib import Path

from services.cloud_sync import migrate_bookmarks


def test_migrate_bookmarks_copies_and_deletes_source(tmp_path):
    src = tmp_path / "src" / "bookmarks.json"
    src.parent.mkdir()
    src.write_text('{"categories":[],"bookmarks":[]}', encoding="utf-8")
    dst = tmp_path / "dst" / "bookmarks.json"
    dst.parent.mkdir()

    migrate_bookmarks(src=src, dst=dst)

    assert dst.read_text(encoding="utf-8") == '{"categories":[],"bookmarks":[]}'
    assert not src.exists()


def test_migrate_bookmarks_noop_when_source_missing(tmp_path):
    src = tmp_path / "missing.json"
    dst = tmp_path / "dst.json"
    migrate_bookmarks(src=src, dst=dst)
    assert not dst.exists()


def test_migrate_bookmarks_rollback_on_post_copy_failure(tmp_path, monkeypatch):
    src = tmp_path / "src.json"
    src.write_text("payload", encoding="utf-8")
    dst = tmp_path / "dst.json"

    original_unlink = Path.unlink

    def fail_unlink(self, missing_ok=False):
        if self == src:
            raise OSError("simulated failure deleting source")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(OSError):
        migrate_bookmarks(src=src, dst=dst)

    assert src.exists()
    assert not dst.exists()
