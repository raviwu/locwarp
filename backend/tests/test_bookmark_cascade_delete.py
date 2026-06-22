"""Unit tests for cascade-delete behaviour on BookmarkManager."""
from __future__ import annotations

import pytest


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """Fresh BookmarkManager backed by a tmp file (so the user's
    real ~/.locwarp/bookmarks.json is never touched)."""
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    from bootstrap.factories import make_bookmark_manager
    return make_bookmark_manager()


def test_delete_category_cascade_false_keeps_bookmarks(manager):
    cat = manager.create_category(name="evt")
    bm = manager.create_bookmark(name="x", lat=0.0, lng=0.0, category_id=cat.id)
    manager.delete_category(cat.id, cascade=False)
    assert any(b.id == bm.id for b in manager.store.bookmarks)
    assert manager._find_bookmark(bm.id).category_id == "default"


def test_delete_category_cascade_true_deletes_bookmarks(manager):
    cat = manager.create_category(name="evt")
    bm1 = manager.create_bookmark(name="x", lat=0.0, lng=0.0, category_id=cat.id)
    bm2 = manager.create_bookmark(name="y", lat=1.0, lng=1.0, category_id=cat.id)
    manager.delete_category(cat.id, cascade=True)
    assert not any(b.id in {bm1.id, bm2.id} for b in manager.store.bookmarks)
    assert manager._find_category(cat.id) is None


def test_delete_default_category_blocked_even_with_cascade(manager):
    bm = manager.create_bookmark(name="x", lat=0.0, lng=0.0)
    assert manager.delete_category("default", cascade=True) is False
    assert manager._find_bookmark(bm.id) is not None


def test_delete_returns_count_of_deleted_bookmarks(manager):
    cat = manager.create_category(name="evt")
    manager.create_bookmark(name="x", lat=0.0, lng=0.0, category_id=cat.id)
    manager.create_bookmark(name="y", lat=1.0, lng=1.0, category_id=cat.id)
    manager.create_bookmark(name="other", lat=2.0, lng=2.0)  # default
    result = manager.delete_category(cat.id, cascade=True)
    # New return contract: dict with status + deleted count
    assert result == {"deleted": True, "deleted_bookmarks": 2}
