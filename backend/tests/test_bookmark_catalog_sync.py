"""Catalog force-sync semantics — catalog ids are source of truth.

Covers the bug where deleting a catalog-seeded category leaves a tombstone
that silently kills a subsequent re-import (because the catalog entries
have empty ``updated_at`` which loses every merge against a real-timestamp
tombstone). The new ``import_catalog`` path stamps ``updated_at = now()``
so the CRDT merge resurrects the items.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


CATALOG = {
    "categories": [
        {
            "id": "cat-A",
            "name": "Event A",
            "color": "#111111",
            "sort_order": 1,
            "created_at": "2026-05-23T00:00:00Z",
        }
    ],
    "bookmarks": [
        {
            "id": "bm-1",
            "name": "Shop 1",
            "lat": 1.0,
            "lng": 2.0,
            "category_id": "cat-A",
            "created_at": "2026-05-23T00:00:00Z",
        },
        {
            "id": "bm-2",
            "name": "Shop 2",
            "lat": 3.0,
            "lng": 4.0,
            "category_id": "cat-A",
            "created_at": "2026-05-23T00:00:00Z",
        },
    ],
}


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    from bootstrap.factories import make_bookmark_manager
    return make_bookmark_manager()


def test_first_sync_adds_everything(manager):
    res = manager.import_catalog(json.dumps(CATALOG))
    # 1 category + 2 bookmarks all new
    assert res == {"added": 3, "updated": 0, "resurrected": 0}
    assert {b.id for b in manager.store.bookmarks} == {"bm-1", "bm-2"}
    assert any(c.id == "cat-A" for c in manager.store.categories)


def test_resync_unchanged_is_idempotent(manager):
    manager.import_catalog(json.dumps(CATALOG))
    res = manager.import_catalog(json.dumps(CATALOG))
    # All 3 ids upsert (existing rows touched), nothing new, no tombstones
    assert res == {"added": 0, "updated": 3, "resurrected": 0}
    assert len(manager.store.bookmarks) == 2


def test_resync_after_delete_resurrects(manager):
    manager.import_catalog(json.dumps(CATALOG))
    manager.delete_category("cat-A", cascade=True)
    assert len(manager.store.bookmarks) == 0
    assert {t.id for t in manager.store.tombstones} == {"cat-A", "bm-1", "bm-2"}

    res = manager.import_catalog(json.dumps(CATALOG))
    # All 3 ids had tombstones → all 3 counted as resurrected
    assert res["resurrected"] == 3
    # After delete-then-sync they're all new again in the live store
    assert res["added"] + res["updated"] == 3

    # And the disk state must reflect the resurrection (this is the bug
    # the plan fixes — without the fix, on-disk bookmarks stays empty).
    on_disk = json.loads(Path(manager._bookmarks_path()).read_text())
    assert {b["id"] for b in on_disk["bookmarks"]} == {"bm-1", "bm-2"}
    assert {c["id"] for c in on_disk["categories"] if c["id"] != "default"} == {"cat-A"}


def test_resync_with_catalog_correction_overwrites_fields(manager):
    manager.import_catalog(json.dumps(CATALOG))
    corrected = json.loads(json.dumps(CATALOG))
    corrected["bookmarks"][0]["lat"] = 99.9
    corrected["bookmarks"][0]["name"] = "Shop 1 (renamed)"
    res = manager.import_catalog(json.dumps(corrected))
    assert res["updated"] >= 1
    by_id = {b.id: b for b in manager.store.bookmarks}
    assert by_id["bm-1"].lat == 99.9
    assert by_id["bm-1"].name == "Shop 1 (renamed)"


def test_local_non_catalog_bookmarks_untouched(manager):
    from models.schemas import Bookmark
    mine = Bookmark(id="user-mine", name="Mine", lat=10.0, lng=20.0, category_id="default")
    manager.store.bookmarks.append(mine)
    manager.import_catalog(json.dumps(CATALOG))
    ids = {b.id for b in manager.store.bookmarks}
    assert "user-mine" in ids
    assert {"bm-1", "bm-2"} <= ids


def test_invalid_payload_returns_zeroes(manager):
    res = manager.import_catalog("not-json-at-all")
    assert res == {"added": 0, "updated": 0, "resurrected": 0}
