"""Test force_seed primitive: on-disk resurrection of deleted catalog items.

Treatment: create+delete a bookmark (leaving a real-timestamp tombstone), then
call manager.force_seed([...]) with the same id and empty updated_at; assert the
item is ALIVE on disk.

Control: a naive append (no stamp) stays DEAD on disk because the tombstone
wins the merge_stores _alive() check (empty updated_at loses to any real ts).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.schemas import Bookmark


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    from bootstrap.factories import make_bookmark_manager
    return make_bookmark_manager()


def _make_bookmark(bm_id: str) -> Bookmark:
    return Bookmark(
        id=bm_id,
        name="Test Place",
        lat=1.0,
        lng=2.0,
        category_id="default",
        updated_at="",  # empty — simulating a catalog item with no stamp
    )


def test_force_seed_resurrects_on_disk(manager):
    """Treatment: delete creates tombstone; force_seed stamps and wins."""
    # Create a bookmark via create_bookmark to get a proper real-timestamp entry
    created = manager.create_bookmark(name="Test Place", lat=1.0, lng=2.0)
    bm_id = created.id
    # Delete to create a real-timestamp tombstone
    manager.delete_bookmark(bm_id)

    # Confirm it is gone from the live store and a tombstone exists
    assert not any(b.id == bm_id for b in manager.store.bookmarks)
    assert any(t.id == bm_id for t in manager.store.tombstones)

    # force_seed with the same id but empty updated_at — must still resurrect
    seed_item = Bookmark(
        id=bm_id,
        name="Test Place (seeded)",
        lat=1.0,
        lng=2.0,
        category_id="default",
        updated_at="",  # empty — the pitfall
    )
    result = manager.force_seed([seed_item])

    # The item must appear ALIVE on disk — this is the key assertion
    disk_path = Path(manager._bookmarks_path())
    on_disk = json.loads(disk_path.read_text())
    disk_ids = {b["id"] for b in on_disk["bookmarks"]}
    assert bm_id in disk_ids, (
        "force_seed must stamp updated_at so the item beats the tombstone on disk"
    )

    # Also alive in the live store
    assert any(b.id == bm_id for b in manager.store.bookmarks)

    # Return contract: the resurrected id was absent from the live list
    # (deleted -> tombstoned), so force_seed counts it as an add.
    assert result == {"added": 1, "updated": 0}


def test_naive_append_stays_dead_on_disk(manager):
    """Control: without force_seed's stamp, tombstone wins and kills the item."""
    created = manager.create_bookmark(name="Test Place", lat=1.0, lng=2.0)
    bm_id = created.id
    manager.delete_bookmark(bm_id)

    # Naive append — bypass force_seed, directly touch store + save
    naive = Bookmark(
        id=bm_id,
        name="Test Place (naive)",
        lat=1.0,
        lng=2.0,
        category_id="default",
        updated_at="",  # no stamp — will lose to tombstone
    )
    manager.store.bookmarks.append(naive)
    manager._save()  # merge_stores runs here; tombstone wins because updated_at=""

    disk_path = Path(manager._bookmarks_path())
    on_disk = json.loads(disk_path.read_text())
    disk_ids = {b["id"] for b in on_disk["bookmarks"]}
    assert bm_id not in disk_ids, (
        "naive append with empty updated_at must lose to the tombstone in merge"
    )
