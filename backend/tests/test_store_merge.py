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


# ── merge_stores ──────────────────────────────────────────────────────────
from services.store_merge import merge_stores, TOMBSTONE_RETENTION_DAYS  # noqa: E402


def _bm(id, name, updated_at, cat="default"):
    return Bookmark(id=id, name=name, lat=0, lng=0, category_id=cat, updated_at=updated_at)


def _store(bms=(), cats=(), tombs=()):
    return BookmarkStore(bookmarks=list(bms), categories=list(cats), tombstones=list(tombs))


def _recent(hours_ago):
    """ISO timestamp ``hours_ago`` hours before now — always inside the 30-day
    tombstone retention window so GC never drops it. Keeps these merge tests
    deterministic instead of drifting red once the wall clock passes a
    hard-coded date + TOMBSTONE_RETENTION_DAYS."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_merge_unions_distinct_ids():
    a = _store(bms=[_bm("1", "A", "2026-05-14T01:00:00+00:00")])
    b = _store(bms=[_bm("2", "B", "2026-05-14T01:00:00+00:00")])
    merged = merge_stores(a, b)
    assert {x.id for x in merged.bookmarks} == {"1", "2"}


def test_merge_newer_updated_at_wins_on_collision():
    old = _bm("1", "old", "2026-05-14T01:00:00+00:00")
    new = _bm("1", "new", "2026-05-14T05:00:00+00:00")
    assert merge_stores(_store(bms=[old]), _store(bms=[new])).bookmarks[0].name == "new"
    # commutative — same result regardless of argument order
    assert merge_stores(_store(bms=[new]), _store(bms=[old])).bookmarks[0].name == "new"


def test_merge_is_commutative_and_idempotent():
    a = _store(bms=[_bm("1", "A", "2026-05-14T01:00:00+00:00")])
    b = _store(bms=[_bm("2", "B", "2026-05-14T02:00:00+00:00")])
    assert merge_stores(a, b).model_dump() == merge_stores(b, a).model_dump()
    assert merge_stores(a, a).model_dump() == a.model_dump()


def test_tombstone_suppresses_older_item():
    item = _bm("1", "doomed", _recent(5))
    tomb = Tombstone(id="1", kind="bookmark", deleted_at=_recent(3))
    merged = merge_stores(_store(bms=[item]), _store(tombs=[tomb]))
    assert merged.bookmarks == []


def test_edit_after_delete_resurrects_item():
    # Item edited AFTER the tombstone — the live edit out-votes the delete.
    item = _bm("1", "revived", "2026-05-14T05:00:00+00:00")
    tomb = Tombstone(id="1", kind="bookmark", deleted_at="2026-05-14T03:00:00+00:00")
    merged = merge_stores(_store(bms=[item]), _store(tombs=[tomb]))
    assert [x.name for x in merged.bookmarks] == ["revived"]


def test_old_tombstones_are_garbage_collected():
    stale = (datetime.now(timezone.utc) - timedelta(days=TOMBSTONE_RETENTION_DAYS + 1)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    merged = merge_stores(
        _store(tombs=[Tombstone(id="old", kind="bookmark", deleted_at=stale)]),
        _store(tombs=[Tombstone(id="new", kind="bookmark", deleted_at=fresh)]),
    )
    assert {t.id for t in merged.tombstones} == {"new"}


def test_missing_updated_at_loses_to_stamped_copy():
    legacy = _bm("1", "legacy", "")          # pre-upgrade item, no timestamp
    stamped = _bm("1", "stamped", "2026-05-14T01:00:00+00:00")
    assert merge_stores(_store(bms=[legacy]), _store(bms=[stamped])).bookmarks[0].name == "stamped"


def test_merge_routes_unions_and_keeps_tombstones():
    wp = [{"lat": 1.0, "lng": 1.0}, {"lat": 2.0, "lng": 2.0}]
    a = RouteStore(
        routes=[SavedRoute(id="r1", name="A", waypoints=wp, updated_at=_recent(5))],
        tombstones=[],
    )
    b = RouteStore(
        routes=[SavedRoute(id="r2", name="B", waypoints=wp, updated_at=_recent(5))],
        tombstones=[Tombstone(id="r1", kind="route", deleted_at=_recent(1))],
    )
    merged = merge_stores(a, b)
    # r1 tombstoned after its last edit → suppressed; r2 survives
    assert {r.id for r in merged.routes} == {"r2"}
    assert {t.id for t in merged.tombstones} == {"r1"}
