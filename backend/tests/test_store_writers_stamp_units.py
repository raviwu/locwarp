"""Change G, writer half: every mutation records WHICH units it changed.

The merge (``domain/store_merge.py``) can resolve field by field, but only if
the records reaching it carry per-unit stamps. ``stamp_units`` is the contract:
the units this write changed get ``now``, and every other unit is backfilled
with the record's PREVIOUS ``updated_at``.

The backfill is the part that is easy to mistake for redundant. Without it, a
unit with no stamp falls back to the record's ``updated_at`` — so a peer that
edits one field and stamps only that one has all its *other* units inherit the
fresh record stamp, and they go on clobbering exactly as they did before G.

The end of this file is the acceptance test: two managers over one store file,
disjoint edits, both survive. That is the hazard
``test_bookmark_revert_hazards.py`` used to pin as unfixable.
"""
from __future__ import annotations

import pytest

from bootstrap.factories import make_bookmark_manager, make_route_manager
from domain.store_merge import unit_stamp


@pytest.fixture
def bm_manager(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    return make_bookmark_manager()


@pytest.fixture
def rt_manager(tmp_path, monkeypatch):
    monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
    return make_route_manager()


# ── bookmarks ─────────────────────────────────────────────────────────


def test_create_leaves_every_unit_stamped_at_the_record_stamp(bm_manager):
    bm = bm_manager.create_bookmark(name="A", lat=1.0, lng=2.0)
    for unit in ("name", "coords", "address", "category_id", "last_used_at"):
        assert unit_stamp(bm, unit) == bm.updated_at


def test_update_stamps_only_the_changed_unit_and_backfills_the_rest(bm_manager):
    bm = bm_manager.create_bookmark(name="A", lat=1.0, lng=2.0, address="old")
    first = bm.updated_at

    after = bm_manager.update_bookmark(bm.id, name="B")

    assert after.field_updated_at["name"] == after.updated_at != first
    assert after.field_updated_at["address"] == first, (
        "an untouched unit must keep the PREVIOUS record stamp, not inherit the new one"
    )
    assert after.field_updated_at["coords"] == first


def test_a_coordinate_edit_stamps_coords_not_name(bm_manager):
    bm = bm_manager.create_bookmark(name="A", lat=1.0, lng=2.0)
    first = bm.updated_at

    after = bm_manager.update_bookmark(bm.id, lat=9.0, lng=8.0)

    assert after.field_updated_at["coords"] == after.updated_at
    assert after.field_updated_at["name"] == first


def test_a_no_op_update_stamps_nothing(bm_manager):
    bm = bm_manager.create_bookmark(name="A", lat=1.0, lng=2.0)
    before = dict(bm.field_updated_at)

    after = bm_manager.update_bookmark(bm.id, name="A")

    assert after.updated_at == bm.updated_at
    assert after.field_updated_at == before


def test_move_bookmarks_stamps_only_the_category(bm_manager):
    cat = bm_manager.create_category(name="Trips")
    bm = bm_manager.create_bookmark(name="A", lat=1.0, lng=2.0)
    first = bm.updated_at

    assert bm_manager.move_bookmarks([bm.id], cat.id) == 1

    moved = next(b for b in bm_manager.store.bookmarks if b.id == bm.id)
    assert moved.field_updated_at["category_id"] == moved.updated_at != first
    assert moved.field_updated_at["name"] == first, (
        "dragging a bookmark between categories must not out-vote a peer's rename"
    )


def test_category_update_stamps_only_the_changed_unit(bm_manager):
    cat = bm_manager.create_category(name="Trips", color="#111111")
    first = cat.updated_at

    after = bm_manager.update_category(cat.id, name="Journeys")

    assert after.field_updated_at["name"] == after.updated_at != first
    assert after.field_updated_at["color"] == first


def test_enrichment_never_stamps(bm_manager):
    """The geo fields are deterministic from the coordinate and ride with
    `coords`; giving them stamps would manufacture cross-device conflicts."""
    bm = bm_manager.create_bookmark(name="A", lat=1.0, lng=2.0)
    before_record, before_map = bm.updated_at, dict(bm.field_updated_at)

    bm_manager.enrich_all()

    after = next(b for b in bm_manager.store.bookmarks if b.id == bm.id)
    assert after.updated_at == before_record
    assert after.field_updated_at == before_map


# ── routes ────────────────────────────────────────────────────────────


def test_route_category_update_stamps_only_the_changed_unit(rt_manager):
    cat = rt_manager.create_category(name="Loops", color="#111111")
    first = cat.updated_at

    after = rt_manager.update_category(cat.id, color="#222222")

    assert after.field_updated_at["color"] == after.updated_at != first
    assert after.field_updated_at["name"] == first


# ── the acceptance test ───────────────────────────────────────────────


def test_two_machines_editing_different_fields_both_survive(tmp_path, monkeypatch):
    """The hazard G exists to close, end to end through the real save path.

    Two managers over one store file, mirroring the two-Mac iCloud setup. Each
    holds its own in-memory copy and neither has seen the other's edit, so this
    is not something a sparse request body (fix F) can help with.
    """
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    mac1 = make_bookmark_manager()
    bm = mac1.create_bookmark(name="original", lat=1.0, lng=2.0, address="original addr")

    mac2 = make_bookmark_manager()  # loads the same file
    assert next(b for b in mac2.store.bookmarks if b.id == bm.id).name == "original"

    mac1.update_bookmark(bm.id, name="renamed on mac 1")
    mac2.update_bookmark(bm.id, address="re-addressed on mac 2")

    fresh = make_bookmark_manager()
    final = next(b for b in fresh.store.bookmarks if b.id == bm.id)
    assert final.name == "renamed on mac 1"
    assert final.address == "re-addressed on mac 2"


def test_a_same_field_conflict_still_picks_one_winner_consistently(tmp_path, monkeypatch):
    """G does not invent a merge for a genuine same-field conflict; it just
    stops that conflict from taking the rest of the record with it."""
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    mac1 = make_bookmark_manager()
    bm = mac1.create_bookmark(name="original", lat=1.0, lng=2.0, address="keep me")

    mac2 = make_bookmark_manager()
    mac1.update_bookmark(bm.id, name="mac 1 name")
    mac2.update_bookmark(bm.id, name="mac 2 name")

    fresh = make_bookmark_manager()
    final = next(b for b in fresh.store.bookmarks if b.id == bm.id)
    assert final.name in {"mac 1 name", "mac 2 name"}
    assert final.address == "keep me", "the untouched field must not be collateral damage"
