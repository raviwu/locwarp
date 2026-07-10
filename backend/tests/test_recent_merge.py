"""merge_recent folds a backup snapshot into the live recent store.

The store is not a CRDT set — no tombstones, nothing deleted except by the
user's explicit Clear — so restoring means UNION, not replace. Like
domain.store_merge.merge_stores, the operation must be commutative and
idempotent, or `make restore-backup` run twice would not be a no-op.
"""
from __future__ import annotations

import pytest

from domain.recent import (
    DEDUPE_DIST_M,
    MAX_MANUAL_ENTRIES,
    MAX_ROUTE_STOP_ENTRIES,
    haversine_m,
    merge_recent,
)


def _manual(lat, lng, ts, name=""):
    return {"lat": lat, "lng": lng, "kind": "teleport", "name": name, "ts": ts}


def _route(lat, lng, ts, visits=1, name=""):
    return {"lat": lat, "lng": lng, "kind": "route_stop", "name": name,
            "ts": ts, "visit_count": visits}


def test_union_keeps_rows_present_in_either_side():
    a = [_manual(1.0, 1.0, 100)]
    b = [_manual(2.0, 2.0, 200)]
    assert len(merge_recent(a, b)) == 2


def test_matched_rows_keep_the_newest_ts_and_the_highest_visit_count():
    a = [_route(25.0, 121.0, 100, visits=5)]
    b = [_route(25.0, 121.0, 300, visits=2)]
    merged = merge_recent(a, b)
    assert len(merged) == 1
    assert merged[0]["ts"] == 300
    assert merged[0]["visit_count"] == 5


def test_a_manual_row_never_merges_with_a_route_row_at_the_same_spot():
    merged = merge_recent([_manual(25.0, 121.0, 100)], [_route(25.0, 121.0, 200)])
    kinds = sorted(e["kind"] for e in merged)
    assert kinds == ["route_stop", "teleport"]


def test_a_non_empty_name_wins_over_an_empty_one():
    merged = merge_recent([_route(25.0, 121.0, 100, name="")],
                          [_route(25.0, 121.0, 200, name="Taipei")])
    assert merged[0]["name"] == "Taipei"


def test_manual_rows_gain_no_visit_count():
    merged = merge_recent([_manual(1.0, 1.0, 100)], [_manual(1.0, 1.0, 200)])
    assert len(merged) == 1
    assert "visit_count" not in merged[0]


def test_result_is_ts_descending_and_capped_per_class():
    a = [_manual(1.0 + i, 2.0 + i, 100 + i) for i in range(25)]
    b = [_route(40.0 + i * 0.5, 100.0 + i * 0.5, 500 + i) for i in range(40)]
    merged = merge_recent(a, b)
    kinds = [e["kind"] for e in merged]
    assert kinds.count("teleport") == MAX_MANUAL_ENTRIES
    assert kinds.count("route_stop") == MAX_ROUTE_STOP_ENTRIES
    ts = [e["ts"] for e in merged]
    assert ts == sorted(ts, reverse=True)


def test_merge_is_commutative():
    a = [_route(25.0, 121.0, 100, visits=5), _manual(1.0, 1.0, 90)]
    b = [_route(25.0, 121.0, 300, visits=2), _manual(2.0, 2.0, 80)]
    assert merge_recent(a, b) == merge_recent(b, a)


def test_merge_is_idempotent():
    a = [_route(25.0, 121.0, 100, visits=5), _manual(1.0, 1.0, 90)]
    once = merge_recent(a, [])
    assert merge_recent(once, once) == once


def test_merge_is_commutative_with_a_genuine_ts_tie_and_differing_names():
    """Two DIFFERENT rows of the same class, within DEDUPE_DIST_M, sharing an
    exact ts. sort_desc's stable sort alone cannot break this tie without
    favoring whichever side was concatenated first, so which row "survives"
    (and whose non-empty name wins) would depend on a-vs-b call order unless
    _fold's internal sort has a deterministic secondary key.
    """
    a = [_route(25.00000, 121.00000, 100, visits=1, name="Alpha")]
    b = [_route(25.00003, 121.00003, 100, visits=1, name="Beta")]  # ~4.5m away, same ts
    assert merge_recent(a, b) == merge_recent(b, a)


def test_chained_proximity_is_not_transitive_and_fold_order_is_deterministic():
    """Proximity is NOT transitive: A is within DEDUPE_DIST_M of B, and B is
    within DEDUPE_DIST_M of C, but A is NOT within DEDUPE_DIST_M of C. Which
    row folds into which then depends entirely on fold order, which is why
    _fold sorts on the deterministic (-ts, lat, lng) secondary key rather than
    input-concatenation order.

    All three rows share an exact ts, so ties break on (lat, lng) ascending:
    A(lng=0) < B(lng=0.0000719) < C(lng=0.0001437). Folding in that order:
    A is kept first; B is within 10m of A, so it merges into A; C is >10m
    from A (its only prior survivor), so it survives as its own row. The
    verified distances below are what makes this deterministic -- if the
    radius or the earth-radius constant in haversine_m ever changes enough to
    flip AB or BC across DEDUPE_DIST_M, or AC under it, this test catches it.
    """
    a_coord = (0.0, 0.0)
    b_coord = (0.0, 0.0000719)  # ~8.0m from A
    c_coord = (0.0, 0.0001437)  # ~8.0m from B, ~16.0m from A

    dist_ab = haversine_m(*a_coord, *b_coord)
    dist_bc = haversine_m(*b_coord, *c_coord)
    dist_ac = haversine_m(*a_coord, *c_coord)
    assert dist_ab == pytest.approx(8.0, abs=0.1)
    assert dist_bc == pytest.approx(8.0, abs=0.1)
    assert dist_ac == pytest.approx(16.0, abs=0.1)
    assert dist_ab < DEDUPE_DIST_M
    assert dist_bc < DEDUPE_DIST_M
    assert dist_ac > DEDUPE_DIST_M  # the chain-breaking fact under test

    a_row = _route(*a_coord, 100, name="A")
    b_row = _route(*b_coord, 100, name="B")
    c_row = _route(*c_coord, 100, name="C")

    merged = merge_recent([a_row, b_row], [c_row])
    coords = [(e["lat"], e["lng"]) for e in merged]
    assert len(merged) == 2
    # B folded into A (survivor keeps A's own coordinates); C survives
    # separately because it is too far from A, B's only prior survivor.
    assert coords == [a_coord, c_coord]

    assert merge_recent([a_row, b_row], [c_row]) == merge_recent([c_row], [a_row, b_row])

    once = merge_recent([a_row, b_row], [c_row])
    assert merge_recent(once, once) == once
