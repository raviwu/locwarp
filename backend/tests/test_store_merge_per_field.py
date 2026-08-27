"""Change G: per-field resolution inside the CRDT merge.

Before G, ``_union_by_id`` kept the record with the newer ``updated_at`` and
discarded the other WHOLE. Two machines editing different fields of one record
between syncs therefore lost one machine's field — the residual hazard E1 and F
could not reach, because each machine legitimately edited its own field.

G resolves each *merge unit* independently against a per-field stamp map
(``field_updated_at``), falling back to the record's ``updated_at`` for any unit
with no stamp. That fallback is what makes G additive: a record written by a
build that predates G has no map, every unit resolves at ``updated_at``, and the
pair behaves exactly as it did before G.

Design: docs/superpowers/plans/2026-08-27-bookmark-per-field-merge-g.md §4.
"""
from __future__ import annotations

import logging

import random

import pytest

from domain.store_merge import (
    BOOKMARK_MERGE_UNITS,
    CATEGORY_MERGE_UNITS,
    merge_records,
    merge_stores,
    stamp_units,
    unit_stamp,
)
from models.schemas import Bookmark, BookmarkCategory, BookmarkStore, Tombstone

T1 = "2026-08-01T00:00:00+00:00"
T2 = "2026-08-02T00:00:00+00:00"
T3 = "2026-08-03T00:00:00+00:00"


def _bm(**over) -> Bookmark:
    base = dict(
        id="b1", name="Old", lat=1.0, lng=2.0, address="addr",
        category_id="default", updated_at=T1,
    )
    base.update(over)
    return Bookmark(**base)


def _cat(**over) -> BookmarkCategory:
    base = dict(id="c1", name="Cat", color="#111111", sort_order=0, updated_at=T1)
    base.update(over)
    return BookmarkCategory(**base)


# ── unit_stamp: the fallback that makes G additive ────────────────────


def test_unit_stamp_falls_back_to_the_record_stamp():
    bm = _bm(updated_at=T2)
    assert unit_stamp(bm, "name") == T2


def test_unit_stamp_prefers_an_explicit_field_stamp():
    bm = _bm(updated_at=T2, field_updated_at={"name": T3})
    assert unit_stamp(bm, "name") == T3
    assert unit_stamp(bm, "address") == T2, "an unstamped unit still falls back"


def test_unit_stamp_ignores_an_empty_string_stamp():
    """Empty sorts oldest everywhere else in this module; treat it as absent."""
    bm = _bm(updated_at=T2, field_updated_at={"name": ""})
    assert unit_stamp(bm, "name") == T2


# ── merge_records: rule 1, newer unit stamp wins ──────────────────────


def _written(bm: Bookmark, changed: set[str], now: str) -> Bookmark:
    """A record as a writer leaves it: every unit explicitly stamped."""
    stamp_units(bm, changed, now, BOOKMARK_MERGE_UNITS)
    return bm


def test_each_unit_resolves_independently():
    """THE point of G: disjoint edits on one record both survive.

    Both sides start from the same T1 record and are put through the writer
    helper, which is what a real ``update_bookmark`` does.
    """
    left = _written(_bm(name="Renamed"), {"name"}, T2)
    right = _written(_bm(address="New addr"), {"address"}, T3)

    out = merge_records(left, right, BOOKMARK_MERGE_UNITS)

    assert out.name == "Renamed", "left's newer name must survive right's newer record stamp"
    assert out.address == "New addr"


def test_an_unstamped_unit_is_read_pessimistically():
    """Why ``stamp_units`` fills in the units a write did NOT touch.

    Without that fill-in, the peer's untouched fields inherit its fresh record
    stamp through ``unit_stamp``'s fallback and keep clobbering — G would buy
    nothing. This pins the fallback so the writer contract cannot be quietly
    dropped as redundant.
    """
    left = _bm(name="Renamed", updated_at=T2, field_updated_at={"name": T2})
    right = _bm(address="New addr", updated_at=T3)  # no map at all

    out = merge_records(left, right, BOOKMARK_MERGE_UNITS)

    assert out.name == "Old", "right's unstamped name reads as T3 and wins"


def test_the_merged_record_stamp_is_the_max_of_everything():
    left = _bm(updated_at=T2, field_updated_at={"name": T2})
    right = _bm(updated_at=T1, field_updated_at={"address": T3})

    out = merge_records(left, right, BOOKMARK_MERGE_UNITS)

    assert out.updated_at == T3, "tombstone comparisons rely on this staying 'last touched'"


def test_lat_and_lng_move_as_one_unit():
    """Splitting the pair would synthesise a coordinate neither machine had."""
    left = _bm(lat=10.0, lng=20.0, updated_at=T3, field_updated_at={"coords": T3})
    right = _bm(lat=30.0, lng=40.0, updated_at=T2, field_updated_at={"coords": T2})

    out = merge_records(left, right, BOOKMARK_MERGE_UNITS)

    assert (out.lat, out.lng) == (10.0, 20.0)


def test_geo_fields_follow_the_winning_coords():
    """country_code / timezone / city / region are deterministic from the
    coordinate and are authored only by enrich_bookmark, so they are not units
    of their own — they ride along with whichever side wins `coords`."""
    left = _bm(lat=10.0, lng=20.0, country_code="jp", timezone="Asia/Tokyo",
               updated_at=T3, field_updated_at={"coords": T3})
    right = _bm(lat=30.0, lng=40.0, country_code="tw", timezone="Asia/Taipei",
                updated_at=T2, field_updated_at={"coords": T2})

    out = merge_records(left, right, BOOKMARK_MERGE_UNITS)

    assert (out.lat, out.country_code, out.timezone) == (10.0, "jp", "Asia/Tokyo")


def test_the_merged_map_carries_the_winning_stamps_forward():
    left = _written(_bm(name="L"), {"name"}, T2)
    right = _written(_bm(address="R"), {"address"}, T3)

    out = merge_records(left, right, BOOKMARK_MERGE_UNITS)

    assert out.field_updated_at["name"] == T2
    assert out.field_updated_at["address"] == T3


# ── rules 2 and 3: the tiebreaks ──────────────────────────────────────


def test_tie_on_unit_stamp_falls_to_the_record_stamp():
    left = _bm(name="L", updated_at=T2, field_updated_at={"name": T2})
    right = _bm(name="R", updated_at=T3, field_updated_at={"name": T2})

    out = merge_records(left, right, BOOKMARK_MERGE_UNITS)

    assert out.name == "R"


def test_tie_on_both_stamps_falls_to_a_symmetric_value_sort():
    """Rule 3 exists ONLY to keep the merge commutative.

    A 'prefer left' tiebreak would be simpler and would let the two machines
    resolve the same conflict differently, diverging permanently. The choice of
    winner is arbitrary; that both sides make the SAME arbitrary choice is not.
    """
    left = _bm(name="aaa", updated_at=T2, field_updated_at={"name": T2})
    right = _bm(name="zzz", updated_at=T2, field_updated_at={"name": T2})

    assert merge_records(left, right, BOOKMARK_MERGE_UNITS).name == "zzz"
    assert merge_records(right, left, BOOKMARK_MERGE_UNITS).name == "zzz"


# ── §4.4 degradation matrix: G is additive ────────────────────────────


def test_no_map_on_either_side_is_exactly_pre_g_whole_record_lww():
    left = _bm(name="L", address="L-addr", updated_at=T2)
    right = _bm(name="R", address="R-addr", updated_at=T3)

    out = merge_records(left, right, BOOKMARK_MERGE_UNITS)

    assert (out.name, out.address) == ("R", "R-addr"), "the whole newer record wins"


def test_a_mapped_side_can_still_beat_an_unmapped_one_per_field():
    """Row 2 of the matrix: strictly better than pre-G, never worse."""
    left = _bm(name="L", address="L-addr", updated_at=T1, field_updated_at={"name": T3})
    right = _bm(name="R", address="R-addr", updated_at=T2)

    out = merge_records(left, right, BOOKMARK_MERGE_UNITS)

    assert out.name == "L", "left's explicitly-stamped name is newer than right's record"
    assert out.address == "R-addr", "left's unstamped address still loses to the newer record"


def test_an_old_build_stripping_the_map_degrades_and_does_not_crash():
    """What actually happens when a pre-G build round-trips the file: pydantic
    v2 ignores unknown keys, so the map is dropped on its write-back."""
    left = _bm(name="L", updated_at=T2, field_updated_at={"name": T3})
    stripped = Bookmark(**{k: v for k, v in left.model_dump().items() if k != "field_updated_at"})
    right = _bm(name="R", updated_at=T3)

    out = merge_records(stripped, right, BOOKMARK_MERGE_UNITS)

    assert out.name == "R", "with no map on either side this is plain whole-record LWW"


# ── categories ────────────────────────────────────────────────────────


def test_category_units_resolve_independently():
    left = _cat(name="Renamed")
    stamp_units(left, {"name"}, T2, CATEGORY_MERGE_UNITS)
    right = _cat(color="#222222")
    stamp_units(right, {"color"}, T3, CATEGORY_MERGE_UNITS)

    out = merge_records(left, right, CATEGORY_MERGE_UNITS)

    assert out.name == "Renamed"
    assert out.color == "#222222"


def test_category_dates_move_as_one_unit():
    left = _cat(start_date="2026-01-01", end_date="2026-01-31",
                updated_at=T3, field_updated_at={"dates": T3})
    right = _cat(start_date="2026-02-01", end_date="2026-02-28",
                 updated_at=T2, field_updated_at={"dates": T2})

    out = merge_records(left, right, CATEGORY_MERGE_UNITS)

    assert (out.start_date, out.end_date) == ("2026-01-01", "2026-01-31")


# ── every mutable field is accounted for (risk §9.2) ──────────────────


@pytest.mark.parametrize(
    "model, units, exempt",
    [
        (
            Bookmark, BOOKMARK_MERGE_UNITS,
            # id: the merge key. created_at: immutable. updated_at /
            # field_updated_at: the merge's own bookkeeping. The geo four are
            # deterministic from the coordinate and ride along with `coords`.
            {"id", "created_at", "updated_at", "field_updated_at",
             "country_code", "timezone", "city", "region"},
        ),
        (
            BookmarkCategory, CATEGORY_MERGE_UNITS,
            {"id", "created_at", "updated_at", "field_updated_at"},
        ),
    ],
)
def test_every_field_is_either_in_a_unit_or_explicitly_exempt(model, units, exempt):
    """A field added later without a unit silently falls back to whole-record
    LWW — safe, but invisible. This forces the choice to be written down."""
    covered = {f for fields in units.values() for f in fields}
    unaccounted = set(model.model_fields) - covered - exempt
    assert not unaccounted, (
        f"{model.__name__} fields with no merge unit and no exemption: "
        f"{sorted(unaccounted)} — add them to the unit table or to this test's "
        f"exempt set, with a reason."
    )


# ── the CRDT contract (plan §5.3) ─────────────────────────────────────


def _random_bookmark(rng: random.Random, bid: str) -> Bookmark:
    stamps = [T1, T2, T3]
    field_map = {}
    for unit in ("name", "coords", "address", "category_id"):
        if rng.random() < 0.5:
            field_map[unit] = rng.choice(stamps)
    # Well-formed by construction: updated_at >= every stamp in the map, the
    # invariant stamp_units maintains and merge_records documents.
    updated_at = max([*field_map.values(), rng.choice(stamps + [""])])
    return Bookmark(
        id=bid,
        name=rng.choice(["a", "b", "c"]),
        lat=rng.choice([1.0, 2.0]),
        lng=rng.choice([3.0, 4.0]),
        address=rng.choice(["x", "y", ""]),
        category_id=rng.choice(["default", "cat-1"]),
        updated_at=updated_at,
        field_updated_at=field_map,
    )


def _store(rng: random.Random, n: int) -> BookmarkStore:
    ids = [f"b{i}" for i in range(n)]
    return BookmarkStore(
        categories=[],
        bookmarks=[_random_bookmark(rng, i) for i in ids if rng.random() < 0.8],
        tombstones=[
            Tombstone(id=i, kind="bookmark", deleted_at=rng.choice([T1, T2, T3]))
            for i in ids if rng.random() < 0.2
        ],
    )


def test_merge_stays_commutative_and_idempotent_over_random_stores():
    """The property the whole store design leans on, re-proved under G.

    Seeded, so a failure is reproducible; no new dependency. This is the test
    that makes the §4.3 rule-3 tiebreak impossible to quietly drop — without a
    symmetric tiebreak, commutativity fails here.
    """
    rng = random.Random(20260827)
    for _ in range(300):
        a, b = _store(rng, 6), _store(rng, 6)

        ab = merge_stores(a, b).model_dump()
        ba = merge_stores(b, a).model_dump()
        assert ab == ba, "merge_stores must be commutative"

        # Idempotence is stated on the merge's own OUTPUT, not on arbitrary
        # input. `merge_stores(a, a) == a` does not hold in general and never
        # did: a store may carry a live item that its own tombstone suppresses
        # (the deletion has not been applied locally yet), and the merge
        # applies it. That filtering is `_alive`, which change G does not
        # touch. What must hold — and what convergence actually needs — is
        # that merging a settled store with itself changes nothing further.
        settled = merge_stores(a, a)
        assert merge_stores(settled, settled).model_dump() == settled.model_dump(), (
            "merge_stores must be idempotent on its own output"
        )
        merged = merge_stores(a, b)
        assert merge_stores(merged, merged).model_dump() == merged.model_dump()


def test_an_arbitrary_tiebreak_is_logged(caplog):
    """Q3: the same-field conflict stays silent to the user, but not to the log.

    Only the rule-3 case is logged. A same-field conflict the stamps CAN
    separate is an ordinary LWW outcome, and it happens on every single
    `_save()` (the in-memory record differs from the on-disk copy by
    definition), so logging that would be noise that hides this.
    """
    same = "2026-08-27T00:00:00+00:00"
    a = Bookmark(id="x", name="alpha", lat=1.0, lng=2.0, updated_at=same)
    b = Bookmark(id="x", name="omega", lat=1.0, lng=2.0, updated_at=same)

    with caplog.at_level(logging.WARNING, logger="domain.store_merge"):
        merged = merge_records(a, b, BOOKMARK_MERGE_UNITS)

    assert merged.name == "omega"          # content sort
    assert len(caplog.records) == 1
    assert "Merge tie on Bookmark.name (id=x)" in caplog.records[0].getMessage()


def test_an_ordinary_lww_resolution_is_not_logged(caplog):
    older = "2026-08-27T00:00:00+00:00"
    newer = "2026-08-27T01:00:00+00:00"
    a = Bookmark(id="x", name="alpha", lat=1.0, lng=2.0, updated_at=older)
    b = Bookmark(id="x", name="omega", lat=1.0, lng=2.0, updated_at=newer)

    with caplog.at_level(logging.WARNING, logger="domain.store_merge"):
        merge_records(a, b, BOOKMARK_MERGE_UNITS)

    assert caplog.records == []
