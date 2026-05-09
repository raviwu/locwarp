"""Unit tests for format-detecting bookmark import."""
from __future__ import annotations

import json
import pytest


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    from services.bookmarks import BookmarkManager
    return BookmarkManager()


def test_full_store_import(manager):
    from services.bookmark_import import detect_and_import
    payload = json.dumps({
        "categories": [
            {"id": "cat-x", "name": "事件 A", "color": "#ef4444",
             "sort_order": 1, "created_at": "2026-05-09T00:00:00Z"},
        ],
        "bookmarks": [
            {"id": "b1", "name": "p1", "lat": 1.0, "lng": 2.0,
             "category_id": "cat-x", "created_at": "", "last_used_at": ""},
        ],
    })
    result = detect_and_import(manager, payload)
    assert result["scope"] == "full_store"
    assert result["imported"] == 1
    assert any(c.id == "cat-x" for c in manager.store.categories)


def test_single_category_import(manager):
    from services.bookmark_import import detect_and_import
    payload = json.dumps({
        "_meta": {"exported_at": "2026-05-09T08:30:00Z", "format_version": 1, "scope": "category"},
        "category": {"id": "cat-shared", "name": "京都散步", "color": "#ef4444",
                     "sort_order": 1, "created_at": "2026-05-09T00:00:00Z"},
        "bookmarks": [
            {"id": "b1", "name": "常照皇寺", "lat": 35.2, "lng": 135.7,
             "category_id": "cat-shared", "created_at": "", "last_used_at": ""},
        ],
    })
    result = detect_and_import(manager, payload)
    assert result["scope"] == "category"
    assert result["imported"] == 1
    cat = next(c for c in manager.store.categories if c.name == "京都散步")
    assert any(b.category_id == cat.id for b in manager.store.bookmarks)


def test_single_category_import_collision_mints_new_ids(manager):
    """When the incoming category id collides locally, mint a new id and
    rewrite bookmark category_ids to point at it."""
    from services.bookmark_import import detect_and_import
    # Pre-create a local category named "Existing" with id "cat-foo"
    pre = manager.create_category(name="Existing")
    payload = json.dumps({
        "_meta": {"exported_at": "x", "format_version": 1, "scope": "category"},
        "category": {"id": pre.id, "name": "Imported", "color": "#fff",
                     "sort_order": 9, "created_at": ""},
        "bookmarks": [
            {"id": "b9", "name": "p", "lat": 0.0, "lng": 0.0,
             "category_id": pre.id, "created_at": "", "last_used_at": ""},
        ],
    })
    result = detect_and_import(manager, payload)
    assert result["imported"] == 1
    # New category exists with a fresh id
    imported_cat = next(c for c in manager.store.categories if c.name == "Imported")
    assert imported_cat.id != pre.id
    # The bookmark's category_id was rewritten
    bm = next(b for b in manager.store.bookmarks if b.name == "p")
    assert bm.category_id == imported_cat.id


def test_garbage_payload_raises(manager):
    from services.bookmark_import import detect_and_import, InvalidImportError
    with pytest.raises(InvalidImportError):
        detect_and_import(manager, json.dumps({"random": "shape"}))
