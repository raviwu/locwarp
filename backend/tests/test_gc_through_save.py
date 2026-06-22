"""GC-through-_save integration net.

Guards the Task 4 I/O relocation: a stale Tombstone that has aged past
TOMBSTONE_RETENTION_DAYS must be dropped from the on-disk JSON when the
next _save() runs (triggered here by create_bookmark).  If _save() is
moved to a repository layer in Phase 4 the merge_stores call must still
run, or this test goes red.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from models.schemas import Tombstone
from services.store_merge import TOMBSTONE_RETENTION_DAYS


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr(
        "services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    from services.bookmarks import BookmarkManager
    return BookmarkManager()


def test_stale_tombstone_absent_from_disk_after_save(manager, tmp_path):
    """A tombstone older than TOMBSTONE_RETENTION_DAYS must be GC'd by _save.

    Steps:
      1. Inject a stale Tombstone into manager.store.tombstones (deleted_at
         TOMBSTONE_RETENTION_DAYS + 1 days in the past).
      2. Trigger _save() by calling create_bookmark (any write path will do).
      3. Read the raw JSON that _save() wrote and assert the stale id is absent
         from the "tombstones" array — merge_stores ran its GC sweep.
    """
    stale_deleted_at = (
        datetime.now(timezone.utc) - timedelta(days=TOMBSTONE_RETENTION_DAYS + 1)
    ).isoformat()

    stale = Tombstone(id="stale-id-must-vanish", kind="bookmark", deleted_at=stale_deleted_at)
    manager.store.tombstones.append(stale)

    # Trigger _save() via any mutating operation.
    manager.create_bookmark(name="trigger-save", lat=1.0, lng=2.0)

    on_disk = json.loads((tmp_path / "bookmarks.json").read_text(encoding="utf-8"))
    tombstone_ids = {t["id"] for t in on_disk.get("tombstones", [])}
    assert "stale-id-must-vanish" not in tombstone_ids, (
        f"Stale tombstone survived _save(); on-disk tombstones: {tombstone_ids}"
    )
