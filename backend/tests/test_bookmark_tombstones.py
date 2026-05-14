"""BookmarkManager stamps updated_at on every mutation and records a
Tombstone on every delete — the per-item metadata merge_stores needs to
resolve concurrent cloud-sync edits without clobbering or resurrecting.
"""

import pytest

from services.bookmarks import BookmarkManager


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    # _bookmarks_path() returns Path(BOOKMARKS_FILE) when the module-level
    # name differs from the import-time default — point both so the manager
    # reads/writes an isolated tmp file.
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", object())
    return BookmarkManager()


def test_create_bookmark_stamps_updated_at(mgr):
    bm = mgr.create_bookmark("Pin", 1.0, 2.0)
    assert bm.updated_at != ""


def test_update_bookmark_advances_updated_at(mgr):
    bm = mgr.create_bookmark("Pin", 1.0, 2.0)
    first = bm.updated_at
    updated = mgr.update_bookmark(bm.id, name="Renamed")
    assert updated.updated_at >= first and updated.name == "Renamed"


def test_delete_bookmark_emits_tombstone(mgr):
    bm = mgr.create_bookmark("Pin", 1.0, 2.0)
    mgr.delete_bookmark(bm.id)
    assert any(t.id == bm.id and t.kind == "bookmark" for t in mgr.store.tombstones)
    assert all(b.id != bm.id for b in mgr.store.bookmarks)


def test_delete_category_emits_tombstone(mgr):
    cat = mgr.create_category("Trip")
    mgr.delete_category(cat.id)
    assert any(t.id == cat.id and t.kind == "category" for t in mgr.store.tombstones)


def test_create_category_stamps_updated_at(mgr):
    cat = mgr.create_category("Trip")
    assert cat.updated_at != ""


def test_update_category_advances_updated_at(mgr):
    cat = mgr.create_category("Trip")
    first = cat.updated_at
    updated = mgr.update_category(cat.id, name="Vacation")
    assert updated.updated_at >= first and updated.name == "Vacation"


def test_move_bookmarks_stamps_updated_at(mgr):
    cat = mgr.create_category("Trip")
    bm = mgr.create_bookmark("Pin", 1.0, 2.0)
    before = bm.updated_at
    mgr.move_bookmarks([bm.id], cat.id)
    moved = next(b for b in mgr.store.bookmarks if b.id == bm.id)
    assert moved.category_id == cat.id and moved.updated_at >= before


def test_delete_category_noncascade_stamps_reparented_bookmarks(mgr):
    cat = mgr.create_category("Trip")
    bm = mgr.create_bookmark("Pin", 1.0, 2.0, category_id=cat.id)
    before = bm.updated_at
    mgr.delete_category(cat.id)  # non-cascade: bookmark moves to "default"
    reparented = next(b for b in mgr.store.bookmarks if b.id == bm.id)
    assert reparented.category_id == "default" and reparented.updated_at >= before
