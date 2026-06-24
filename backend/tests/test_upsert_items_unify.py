"""Characterization: import_json / import_catalog / force_seed all upsert via
one primitive. Pins CURRENT add/update counts + on-disk survival BEFORE the
refactor, so the carve is byte-for-byte behavior-preserving."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.schemas import Bookmark


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    from bootstrap.factories import make_bookmark_manager
    return make_bookmark_manager()


def test_import_json_add_then_skip(manager):
    payload = json.dumps({
        "categories": [{"id": "cat-x", "name": "E", "color": "#ef4444",
                        "sort_order": 1, "created_at": ""}],
        "bookmarks": [{"id": "b1", "name": "p1", "lat": 1.0, "lng": 2.0,
                       "category_id": "cat-x", "created_at": "",
                       "last_used_at": "", "updated_at": ""}],
    })
    assert manager.import_json(payload) == {"imported": 1, "skipped": 0}
    assert manager.import_json(payload) == {"imported": 0, "skipped": 1}
    # import_json stamps updated_at=now so the bookmark survives the merge.
    on_disk = json.loads(Path(manager._bookmarks_path()).read_text())
    bm = next(b for b in on_disk["bookmarks"] if b["id"] == "b1")
    assert bm["updated_at"] != ""
    # cat-x exists (added by this import), so the bookmark keeps its category.
    assert bm["category_id"] == "cat-x"


def test_import_catalog_add_update_resurrect(manager):
    # Seed one catalog category + one catalog bookmark.
    cat_payload = json.dumps({
        "categories": [{"id": "seed-cat", "name": "Seed", "color": "#111111",
                        "sort_order": 0, "created_at": ""}],
        "bookmarks": [{"id": "seed-1", "name": "Orig", "lat": 1.0, "lng": 2.0,
                       "category_id": "seed-cat", "created_at": "",
                       "last_used_at": ""}],
    })
    first = manager.import_catalog(cat_payload)
    # 1 category + 1 bookmark are both new -> added counts BOTH (added_cats+added_bms).
    assert first == {"added": 2, "updated": 0, "resurrected": 0}
    # Re-sync with a name+coord correction -> the existing ids are UPSERTED.
    cat_payload2 = json.dumps({
        "categories": [{"id": "seed-cat", "name": "Seed", "color": "#111111",
                        "sort_order": 0, "created_at": ""}],
        "bookmarks": [{"id": "seed-1", "name": "Corrected", "lat": 9.0, "lng": 8.0,
                       "category_id": "seed-cat", "created_at": "",
                       "last_used_at": ""}],
    })
    second = manager.import_catalog(cat_payload2)
    assert second == {"added": 0, "updated": 2, "resurrected": 0}
    bm = next(b for b in manager.store.bookmarks if b.id == "seed-1")
    assert bm.name == "Corrected" and bm.lat == 9.0 and bm.lng == 8.0


def test_import_catalog_resurrects_deleted_id(manager):
    created = manager.create_bookmark(name="X", lat=1.0, lng=2.0)
    manager.delete_bookmark(created.id)
    payload = json.dumps({
        "categories": [],
        "bookmarks": [{"id": created.id, "name": "Back", "lat": 1.0, "lng": 2.0,
                       "category_id": "default", "created_at": "",
                       "last_used_at": ""}],
    })
    result = manager.import_catalog(payload)
    assert result["resurrected"] == 1
    on_disk = json.loads(Path(manager._bookmarks_path()).read_text())
    assert created.id in {b["id"] for b in on_disk["bookmarks"]}


def test_force_seed_add_then_update(manager):
    item = Bookmark(id="f1", name="Seeded", lat=1.0, lng=2.0,
                    category_id="default", updated_at="")
    assert manager.force_seed([item]) == {"added": 1, "updated": 0}
    item2 = Bookmark(id="f1", name="Seeded v2", lat=3.0, lng=4.0,
                     category_id="default", updated_at="")
    assert manager.force_seed([item2]) == {"added": 0, "updated": 1}
    bm = next(b for b in manager.store.bookmarks if b.id == "f1")
    assert bm.name == "Seeded v2" and bm.lat == 3.0
