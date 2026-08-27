"""Commutative, idempotent merge for cloud-synced stores.

LWW-element-set semantics:
  - items unioned by id; an id collision is resolved PER FIELD (change G)
  - tombstones suppress an item iff deleted_at >= item.updated_at
  - tombstones older than TOMBSTONE_RETENTION_DAYS are dropped

Per-field resolution (change G, 2026-08-27). A collision used to keep the
record with the newer ``updated_at`` and discard the other whole, so two
machines editing *different* fields of one record between syncs lost one of
them. Records now carry ``field_updated_at``, a map of merge-unit name to ISO
stamp, and each unit is resolved on its own. A unit with no stamp falls back to
the record's ``updated_at``, which is what makes the change additive: a record
written by a build that predates G has no map, every unit resolves at
``updated_at``, and the pair behaves exactly as it did before G.

Design: docs/superpowers/plans/2026-08-27-bookmark-per-field-merge-g.md

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

# ── Merge units (change G) ────────────────────────────────────────────
#
# A *unit* is a set of fields that must move together. `lat` and `lng` are one
# unit because taking a latitude from one machine and a longitude from the
# other synthesises a coordinate neither machine ever had — a bookmark in the
# sea. Everything else is a unit of one.
#
# Fields deliberately absent from these tables fall back to whole-record LWW,
# which is safe but invisible, so the choice is pinned by
# test_store_merge_per_field.py::test_every_field_is_either_in_a_unit_or_explicitly_exempt.
# The notable exemptions:
#   - id / created_at            immutable or the merge key
#   - updated_at / field_updated_at   the merge's own bookkeeping
#   - country_code / timezone / city / region
#         deterministic from (lat, lng) and authored solely by
#         enrich_bookmark, which never stamps. They ride along with whichever
#         side wins `coords`, which is what keeps them consistent with it.

BOOKMARK_MERGE_UNITS: dict[str, tuple[str, ...]] = {
    "name": ("name",),
    "coords": ("lat", "lng", "country_code", "timezone", "city", "region"),
    "address": ("address",),
    "category_id": ("category_id",),
    "last_used_at": ("last_used_at",),
}

CATEGORY_MERGE_UNITS: dict[str, tuple[str, ...]] = {
    "name": ("name",),
    "color": ("color",),
    "sort_order": ("sort_order",),
    "dates": ("start_date", "end_date"),
}

# Route categories have no start_date / end_date, so they need their own table
# rather than sharing the bookmark one.
ROUTE_CATEGORY_MERGE_UNITS: dict[str, tuple[str, ...]] = {
    "name": ("name",),
    "color": ("color",),
    "sort_order": ("sort_order",),
}

# `geometry` bundles the shape with everything derived from it. The distance
# cache is keyed by `dist_fingerprint` (a hash of waypoints + profile), so a
# distance taken from one machine and a geometry from the other would describe
# a route that never existed — the same reasoning that keeps lat/lng together.
ROUTE_MERGE_UNITS: dict[str, tuple[str, ...]] = {
    "name": ("name",),
    "category_id": ("category_id",),
    "geometry": (
        "waypoints", "profile", "timestamps",
        "straight_distance_m", "road_distance_m", "road_distance_status",
        "dist_fingerprint",
    ),
}


def unit_stamp(record, unit: str) -> str:
    """When this record's copy of ``unit`` was last written.

    Falls back to the record-level ``updated_at`` when the unit has no stamp —
    the record predates G, or predates that unit. An empty stamp is treated as
    absent, matching ``_newer``'s "empty sorts oldest" convention.
    """
    stamps = getattr(record, "field_updated_at", None) or {}
    return stamps.get(unit) or (record.updated_at or "")


def merge_records(left, right, units: dict[str, tuple[str, ...]]):
    """Resolve one id collision unit by unit. Commutative by construction.

    Per unit, in order:
      1. the side with the newer unit stamp wins;
      2. tie -> the side with the newer record-level ``updated_at``;
      3. still tied -> the side whose unit value sorts greater.

    Rule 3 is arbitrary on purpose, and load-bearing: an asymmetric tiebreak
    (say "prefer left") would let two machines resolve the same conflict
    differently and diverge permanently, which is strictly worse than the
    revert G exists to fix. The property test in
    test_store_merge_per_field.py fails without it.

    The result's ``updated_at`` is the max over both inputs and every surviving
    unit stamp, so it still means "last time anything about this record
    changed" and the tombstone rule in ``merge_stores`` is unaffected.

    INVARIANT this relies on, maintained by ``stamp_units``: a record's
    ``updated_at`` is >= every stamp in its own map. Merging a record that
    violates it normalises it (once, then stably) rather than preserving it.
    """
    winner_of: dict[str, object] = {}
    for unit, fields in units.items():
        ls, rs = unit_stamp(left, unit), unit_stamp(right, unit)
        if ls != rs:
            winner = left if ls > rs else right
        elif (left.updated_at or "") != (right.updated_at or ""):
            winner = left if (left.updated_at or "") > (right.updated_at or "") else right
        else:
            lv = [getattr(left, f) for f in fields]
            rv = [getattr(right, f) for f in fields]
            winner = left if repr(lv) > repr(rv) else right
        winner_of[unit] = winner

    values = {}
    stamps: dict[str, str] = {}
    for unit, fields in units.items():
        winner = winner_of[unit]
        for f in fields:
            values[f] = getattr(winner, f)
        # Carry forward the newest EXPLICIT stamp held by any side whose value
        # for this unit equals the winning value. Two subtleties, both of them
        # things the property test catches:
        #   - only explicit stamps: materialising a fallback would turn
        #     merge(a, a) into a record with a fuller map than `a`.
        #   - "any side holding the winning value", not "the winner object":
        #     when both sides hold the SAME value, rule 3 falls through to a
        #     positional pick, so merge(a, b) and merge(b, a) would otherwise
        #     carry different maps for an identical record.
        winning = [getattr(winner, f) for f in fields]
        candidates = [
            (getattr(side, "field_updated_at", None) or {}).get(unit)
            for side in (left, right)
            if [getattr(side, f) for f in fields] == winning
        ]
        explicit = max([c for c in candidates if c], default=None)
        if explicit:
            stamps[unit] = explicit

    newest = max(
        [left.updated_at or "", right.updated_at or "", *stamps.values()]
    )

    # `base` only supplies the fields no unit owns (id, created_at, and any
    # field an exemption covers). Its pick has to be symmetric too, so a tie on
    # updated_at falls through to the same content sort rule 3 uses.
    lu, ru = left.updated_at or "", right.updated_at or ""
    if lu != ru:
        base = left if lu > ru else right
    else:
        base = left if repr(left.model_dump()) > repr(right.model_dump()) else right
    merged = base.model_copy(deep=True)
    for f, v in values.items():
        setattr(merged, f, v)
    merged.updated_at = newest
    if hasattr(merged, "field_updated_at"):
        merged.field_updated_at = stamps
    return merged


def units_all_tied(a, b) -> bool:
    """True when ``a`` and ``b`` carry the same stamp for every merge unit.

    ``merge_records`` breaks such a tie with a content sort, deliberately, so
    that it stays commutative. A caller that wants a *positional* preference on
    an exact tie — ``sync_merge``'s one-shot "local wins" bootstrap is the only
    one — has to say so itself, and this is how it detects the case.
    """
    units = merge_units_for(a)
    if units is None or merge_units_for(b) is not units:
        return (a.updated_at or "") == (b.updated_at or "")
    return all(unit_stamp(a, u) == unit_stamp(b, u) for u in units)


def stamp_units(record, changed: set[str], now_iso: str, units: dict[str, tuple[str, ...]]) -> None:
    """Record a write: ``changed`` units get ``now_iso``, the rest keep theirs.

    Every unit ends up with an explicit stamp, and that completeness is the
    whole point. ``unit_stamp``'s fallback to ``updated_at`` is *pessimistic*:
    it reads an unstamped unit as though it had been written when the record
    was last touched. So if a peer edits one field and stamps only that one,
    its other units inherit the fresh record stamp and go on clobbering exactly
    the way they did before G. Filling in the untouched units with the record's
    PREVIOUS ``updated_at`` — the best available estimate of when those values
    were actually last set — is what makes per-field resolution real.

    Also maintains ``merge_records``'s invariant: ``updated_at`` is set last
    and is >= every stamp in the map.
    """
    stamps = dict(getattr(record, "field_updated_at", None) or {})
    previous = record.updated_at or ""
    for unit in units:
        if unit in changed:
            stamps[unit] = now_iso
        elif not stamps.get(unit):
            if previous:
                stamps[unit] = previous
    record.field_updated_at = stamps
    record.updated_at = now_iso


def merge_units_for(item) -> dict[str, tuple[str, ...]] | None:
    """The unit table for this record type, or None for a type G does not
    cover yet (which keeps the pre-G whole-record path)."""
    from models.schemas import Bookmark, BookmarkCategory, RouteCategory, SavedRoute

    if isinstance(item, Bookmark):
        return BOOKMARK_MERGE_UNITS
    if isinstance(item, BookmarkCategory):
        return CATEGORY_MERGE_UNITS
    if isinstance(item, RouteCategory):
        return ROUTE_CATEGORY_MERGE_UNITS
    if isinstance(item, SavedRoute):
        return ROUTE_MERGE_UNITS
    return None



def _items_attr(store) -> str:
    """Name of the per-store item list — 'bookmarks' or 'routes'."""
    return "bookmarks" if isinstance(store, BookmarkStore) else "routes"


def _newer(a_ts: str, b_ts: str) -> bool:
    """True if a_ts is strictly newer than b_ts. Empty string sorts oldest, so
    a legacy record (no updated_at) always loses to a properly stamped copy."""
    return (a_ts or "") > (b_ts or "")


def _union_by_id(left: list, right: list) -> list:
    """Union two item lists by id, resolving a collision unit by unit.

    See ``merge_records``. Types without a unit table keep the pre-G rule
    (whole record with the newer ``updated_at`` wins).

    Output is sorted by id so the merge is order-independent: merge(a, b) and
    merge(b, a) produce byte-identical results. Display order is the caller's
    concern (list_categories sorts by sort_order, etc.)."""
    out: dict[str, object] = {}
    for item in list(left) + list(right):
        existing = out.get(item.id)
        if existing is None:
            out[item.id] = item
            continue
        units = merge_units_for(item)
        if units is None:
            # A record type G does not cover: pre-G whole-record LWW.
            if _newer(item.updated_at, existing.updated_at):
                out[item.id] = item
        else:
            out[item.id] = merge_records(existing, item, units)
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


def force_seed_items(items: list, now_iso: str) -> list:
    """Stamp updated_at=now on each item so a force-seed/import beats any
    pre-existing real-timestamp tombstone in merge_stores (the empty-updated_at
    pitfall). Pure: mutates + returns the given items. Caller supplies the time."""
    for it in items:
        it.updated_at = now_iso
    return items


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
