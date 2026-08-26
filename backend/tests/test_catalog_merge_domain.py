"""Pure three-way resolution for the catalog force-sync (domain ring).

One test per row of the merge table: base (the catalog value this machine last
applied) vs ours (the live local value) vs theirs (the incoming catalog value).
Every test asserts ALL FOUR members of Resolution, because two of the rows are
byte-identical on three of them.
"""
from itertools import product

from domain.catalog_merge import (
    BOOKMARK_MERGE_FIELDS,
    CATEGORY_MERGE_FIELDS,
    Resolution,
    resolve_record,
)

FIELDS = ("f",)


def _r(base, ours, theirs):
    return resolve_record(
        {"f": base} if base is not None else None, {"f": ours}, {"f": theirs}, FIELDS
    )


def test_merge_field_lists_match_what_the_catalog_owns():
    assert BOOKMARK_MERGE_FIELDS == ("name", "lat", "lng", "address", "category_id")
    assert CATEGORY_MERGE_FIELDS == (
        "name", "color", "sort_order", "start_date", "end_date",
    )
    # country_code is a cached derivation of lat/lng owned by enrich_bookmark,
    # not user intent — merging it would be a promise the enrich breaks.
    assert "country_code" not in BOOKMARK_MERGE_FIELDS


def test_nobody_touched_anything_is_a_no_op():
    res = _r("B", "B", "B")
    assert res == Resolution(values={"f": "B"}, kept=(), conflicts=(), changed=False)


def test_catalog_correction_lands_when_the_user_never_edited_the_field():
    res = _r("B", "B", "T")
    assert res.values == {"f": "T"}
    assert res.kept == ()
    assert res.conflicts == ()
    assert res.changed is True


def test_only_kept_distinguishes_a_preserved_edit_from_an_untouched_field():
    """The revert this whole design exists to fix, side by side with the row it
    is indistinguishable from on values/conflicts/changed. Without `kept`,
    import_catalog cannot compute kept_local at all."""
    preserved = _r("B", "O", "B")   # user edited it, catalog has nothing new
    untouched = _r("B", "B", "B")   # nobody touched anything

    assert preserved.values == {"f": "O"}
    assert preserved.conflicts == ()
    assert preserved.changed is False
    assert untouched.conflicts == preserved.conflicts
    assert untouched.changed == preserved.changed

    assert preserved.kept == ("f",)
    assert untouched.kept == ()


def test_both_sides_moved_to_the_same_value_is_a_silent_no_op():
    """The state of the SECOND Mac after the first applied a catalog
    correction: its store already carries the new value while its baseline
    still records the old one. Reporting a conflict here would be a phantom
    the user could never clear."""
    res = _r("B", "T", "T")
    assert res == Resolution(values={"f": "T"}, kept=(), conflicts=(), changed=False)


def test_both_sides_moved_apart_keeps_ours_and_reports_a_conflict():
    res = _r("B", "O", "T")
    assert res.values == {"f": "O"}
    assert res.kept == ("f",)
    assert res.conflicts == ("f",)
    assert res.changed is False


def test_bootstrap_without_a_baseline_keeps_a_diverged_local_value():
    """First post-upgrade sync: base := theirs, so every already-diverged
    record is preserved and nothing is reported as a conflict."""
    res = _r(None, "O", "T")
    assert res.values == {"f": "O"}
    assert res.kept == ("f",)
    assert res.conflicts == ()
    assert res.changed is False


def test_a_field_missing_from_the_baseline_bootstraps_on_its_own():
    res = resolve_record(
        {"a": "B"},
        {"a": "B", "b": "O"},
        {"a": "T", "b": "T"},
        ("a", "b"),
    )
    assert res.values == {"a": "T", "b": "O"}   # 'a' takes theirs, 'b' bootstraps
    assert res.kept == ("b",)
    assert res.conflicts == ()
    assert res.changed is True


def test_kept_and_conflicts_are_reported_per_field_name():
    res = resolve_record(
        {"name": "B", "address": "B", "lat": 1.0, "lng": 2.0},
        {"name": "mine", "address": "B", "lat": 1.0, "lng": 9.0},
        {"name": "theirs", "address": "fixed", "lat": 1.0, "lng": 2.0},
        ("name", "address", "lat", "lng"),
    )
    assert res.values == {"name": "mine", "address": "fixed", "lat": 1.0, "lng": 9.0}
    assert res.kept == ("name", "lng")
    assert res.conflicts == ("name",)
    assert res.changed is True   # 'address' was taken from theirs


def test_conflicts_is_always_a_subset_of_kept():
    for base, ours, theirs in product(("B", "X", "Y"), repeat=3):
        res = _r(base, ours, theirs)
        assert set(res.conflicts) <= set(res.kept), (base, ours, theirs)
    for ours, theirs in product(("X", "Y"), repeat=2):
        res = _r(None, ours, theirs)
        assert set(res.conflicts) <= set(res.kept), (None, ours, theirs)


def test_changed_is_true_exactly_when_a_value_came_from_theirs():
    for base, ours, theirs in product(("B", "X", "Y"), repeat=3):
        res = _r(base, ours, theirs)
        assert res.changed is (res.values["f"] != ours), (base, ours, theirs)
