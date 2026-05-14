"""Commutative, idempotent merge for cloud-synced stores.

LWW-element-set semantics:
  - items unioned by id; newer ``updated_at`` wins a collision
  - tombstones suppress an item iff deleted_at >= item.updated_at
  - tombstones older than TOMBSTONE_RETENTION_DAYS are dropped

No I/O, no logging. merge_stores(a, b) == merge_stores(b, a); merge_stores(a, a) == a.

This is the single merge primitive used everywhere two copies of a store can
diverge: BookmarkManager / RouteManager save + reconcile, and the enable/disable
migration in sync_merge.py. Because it is commutative it does not matter which
device wrote the file last — both converge to the same result.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TypeVar

from models.schemas import BookmarkStore, RouteStore, Tombstone

# Tombstones older than this are garbage-collected during a merge. Safe because
# every device is expected to sync well within this window — by the time a
# tombstone is this old, every device has already applied the deletion.
TOMBSTONE_RETENTION_DAYS = 30

StoreT = TypeVar("StoreT", BookmarkStore, RouteStore)


def _items_attr(store) -> str:
    """Name of the per-store item list — 'bookmarks' or 'routes'."""
    return "bookmarks" if isinstance(store, BookmarkStore) else "routes"


def _newer(a_ts: str, b_ts: str) -> bool:
    """True if a_ts is strictly newer than b_ts. Empty string sorts oldest, so
    a legacy record (no updated_at) always loses to a properly stamped copy."""
    return (a_ts or "") > (b_ts or "")


def _union_by_id(left: list, right: list) -> list:
    """Union two item lists by id, keeping the copy with the newer updated_at.

    Output is sorted by id so the merge is order-independent: merge(a, b) and
    merge(b, a) produce byte-identical results. Display order is the caller's
    concern (list_categories sorts by sort_order, etc.)."""
    out: dict[str, object] = {}
    for item in list(left) + list(right):
        existing = out.get(item.id)
        if existing is None or _newer(item.updated_at, existing.updated_at):
            out[item.id] = item
    return [out[k] for k in sorted(out)]


def _merge_tombstones(left: list[Tombstone], right: list[Tombstone]) -> list[Tombstone]:
    """Union tombstones by id (newest deleted_at wins), then GC old ones."""
    out: dict[str, Tombstone] = {}
    for t in list(left) + list(right):
        existing = out.get(t.id)
        if existing is None or _newer(t.deleted_at, existing.deleted_at):
            out[t.id] = t
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=TOMBSTONE_RETENTION_DAYS)
    ).isoformat()
    return [out[k] for k in sorted(out) if out[k].deleted_at >= cutoff]


def merge_stores(a: StoreT, b: StoreT) -> StoreT:
    """Merge two stores of the same type into one. Commutative and idempotent."""
    items_attr = _items_attr(a)
    categories = _union_by_id(a.categories, b.categories)
    items = _union_by_id(getattr(a, items_attr), getattr(b, items_attr))
    tombstones = _merge_tombstones(a.tombstones, b.tombstones)

    tomb_at = {t.id: t.deleted_at for t in tombstones}

    def _alive(obj) -> bool:
        # A tombstone wins iff the delete is at-or-after the item's last edit.
        # A later edit (updated_at > deleted_at) out-votes the delete — the
        # other device was actively using the item, so resurrect it.
        ts = tomb_at.get(obj.id)
        return ts is None or not (ts >= (obj.updated_at or ""))

    categories = [c for c in categories if _alive(c)]
    items = [i for i in items if _alive(i)]

    store_cls = type(a)
    return store_cls(**{
        "categories": categories,
        items_attr: items,
        "tombstones": tombstones,
    })
