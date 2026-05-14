"""Commutative, idempotent store merge — the core of conflict-free iCloud sync.

merge_stores must satisfy merge(a, b) == merge(b, a) and merge(a, a) == a so
that two devices writing the same file in any order converge to the same
result. Per-item ``updated_at`` breaks collisions (last write wins);
tombstones suppress deleted items and survive concurrent writers.
"""

from datetime import datetime, timedelta, timezone

from models.schemas import (
    Bookmark, BookmarkCategory, BookmarkStore,
    RouteCategory, RouteStore, SavedRoute, Tombstone,
)


def test_schema_defaults_are_backward_compatible():
    # Old JSON has no updated_at / tombstones — must still load.
    bs = BookmarkStore(**{"categories": [{"name": "X"}], "bookmarks": []})
    assert bs.tombstones == []
    assert bs.categories[0].updated_at == ""
    rs = RouteStore(**{"categories": [], "routes": []})
    assert rs.tombstones == []


def test_tombstone_model_roundtrips():
    t = Tombstone(id="abc", kind="bookmark", deleted_at="2026-05-14T00:00:00+00:00")
    assert Tombstone(**t.model_dump()) == t
