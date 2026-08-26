"""Service-level matrix for E1: the catalog force-sync resolves per field.

``import_catalog`` no longer copies the catalog's values onto an existing
record wholesale. It compares three sides per field — ``base`` (the catalog
values this machine last applied, from ~/.locwarp/catalog_baseline.json),
``ours`` (the live record) and ``theirs`` (the incoming catalog) — and only
takes the catalog's value for a field the user never edited.

The pure rule lives in domain/catalog_merge.py and is unit-tested in
test_catalog_merge_domain.py. This file pins the WIRING: that both the
bookmark loop and the category loop go through it, that the live record is
re-stamped only when something actually changed, that country_code is left to
the geo resolver, and that two machines converge instead of fighting.

Design: docs/superpowers/plans/2026-08-26-bookmark-edit-durability-e1-f.md §4.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bootstrap.factories import make_bookmark_manager
from domain.catalog_merge import BOOKMARK_MERGE_FIELDS, CATEGORY_MERGE_FIELDS
from models.schemas import Tombstone
from services.bookmarks import _now_iso


# ── payload helpers ───────────────────────────────────────────────────────

def _cat(name="Event", color="#111111", sort_order=1, start_date="", end_date=""):
    return {
        "id": "seed-cat",
        "name": name,
        "color": color,
        "sort_order": sort_order,
        "start_date": start_date,
        "end_date": end_date,
        "created_at": "2026-05-23T00:00:00+00:00",
    }


def _bm(bm_id="seed-1", name="Shop", lat=25.0, lng=121.0, address="", country_code=""):
    return {
        "id": bm_id,
        "name": name,
        "lat": lat,
        "lng": lng,
        "address": address,
        "category_id": "seed-cat",
        "country_code": country_code,
        "created_at": "2026-05-23T00:00:00+00:00",
        "last_used_at": "2026-05-23T00:00:00+00:00",
    }


def _catalog(bookmarks=None, categories=None, compiled_at="2026-05-23"):
    return json.dumps(
        {
            "_meta": {"compiled_at": compiled_at},
            "categories": categories if categories is not None else [_cat()],
            "bookmarks": bookmarks if bookmarks is not None else [_bm()],
        }
    )


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    return make_bookmark_manager()


def _stub_geo(monkeypatch, result):
    """Pin the offline resolver so enrich_bookmark's contribution is known.

    The real resolver works in this venv, which would otherwise make every
    'was the record re-stamped?' assertion depend on GeoNames data.
    """
    monkeypatch.setattr("services.bookmarks._geo_resolve", lambda lat, lng: result)


_TW = ("tw", "Asia/Taipei", "Taipei", "Taiwan")


# ── §4.2 rule table — bookmarks ───────────────────────────────────────────

def test_catalog_correction_lands_when_the_user_never_edited_the_field(manager, monkeypatch):
    """ours == base, theirs != base -> take theirs. This is what c748fef
    promised and the Refresh button exists to deliver."""
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    before = manager._find_bookmark("seed-1").updated_at

    res = manager.import_catalog(_catalog([_bm(name="Shop (corrected)", lat=26.0)]))

    bm = manager._find_bookmark("seed-1")
    assert bm.name == "Shop (corrected)"
    assert bm.lat == 26.0
    assert res["kept_local"] == 0 and res["conflicts"] == 0
    # A field came from theirs, so the record genuinely changed (§4.4 cond. 1).
    assert bm.updated_at > before


def test_local_rename_survives_a_catalog_that_has_nothing_new_to_say(manager, monkeypatch):
    """ours != base, theirs == base -> keep ours. THIS is the revert being
    fixed: before E1 the catalog copy overwrote the rename outright."""
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    manager.update_bookmark("seed-1", name="My Renamed Spot")
    before = manager._find_bookmark("seed-1").updated_at

    res = manager.import_catalog(_catalog())

    bm = manager._find_bookmark("seed-1")
    assert bm.name == "My Renamed Spot"
    assert res["kept_local"] == 1
    assert res["conflicts"] == 0
    # Nothing was taken from theirs, so a force-sync here cannot out-vote a
    # fresher edit sitting un-synced on the other Mac (§4.4).
    assert bm.updated_at == before


def test_both_sides_moved_apart_keeps_ours_and_reports_a_conflict(manager, monkeypatch):
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    manager.update_bookmark("seed-1", name="Mine")
    before = manager._find_bookmark("seed-1").updated_at

    res = manager.import_catalog(_catalog([_bm(name="Theirs v2")]))

    bm = manager._find_bookmark("seed-1")
    assert bm.name == "Mine"
    assert res["conflicts"] == 1
    assert res["kept_local"] == 1  # conflicts is a subset of kept_local
    assert bm.updated_at == before


def test_both_sides_moved_to_the_same_value_is_a_silent_no_op(manager, monkeypatch):
    """ours != base, theirs != base, ours == theirs -> nothing to arbitrate.

    Without this row the machine that received the peer's applied correction
    through iCloud would report a conflict it could never clear.
    """
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    manager.update_bookmark("seed-1", name="Agreed Name")
    before = manager._find_bookmark("seed-1").updated_at

    res = manager.import_catalog(_catalog([_bm(name="Agreed Name")]))

    bm = manager._find_bookmark("seed-1")
    assert bm.name == "Agreed Name"
    assert res["conflicts"] == 0
    assert res["kept_local"] == 0
    assert bm.updated_at == before


def test_an_unchanged_resync_does_not_re_stamp_the_record(manager, monkeypatch):
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    before = manager._find_bookmark("seed-1").updated_at

    res = manager.import_catalog(_catalog())

    assert manager._find_bookmark("seed-1").updated_at == before
    assert res["updated"] == 2   # id collisions still count as updates (Q4)
    assert res["kept_local"] == 0 and res["conflicts"] == 0


def test_bootstrap_without_a_baseline_keeps_a_diverged_local_value(manager, monkeypatch):
    """First post-upgrade sync: base := theirs, so every already-diverged
    field reads as a local edit and is preserved with zero conflicts."""
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    manager.update_bookmark("seed-1", name="Diverged Before The Upgrade")
    # Throw the baseline away — this is a machine that has never run E1.
    Path(manager._catalog_baseline._path_provider()).unlink()

    res = manager.import_catalog(_catalog())

    assert manager._find_bookmark("seed-1").name == "Diverged Before The Upgrade"
    assert res["kept_local"] == 1
    assert res["conflicts"] == 0


def test_a_deleted_seed_is_resurrected_through_the_add_branch(manager, monkeypatch):
    """Resurrection never consults the merge — the id is absent from the store,
    so _upsert_items takes the ADD branch (§4.5)."""
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    manager.delete_bookmark("seed-1")
    assert manager._find_bookmark("seed-1") is None

    res = manager.import_catalog(_catalog())

    assert manager._find_bookmark("seed-1") is not None
    assert res["resurrected"] == 1
    assert res["added"] == 1


def test_a_second_sync_detects_a_correction_the_first_one_recorded(manager, monkeypatch):
    """The baseline written by sync 1 is what lets sync 2 tell a genuine
    catalog move from a local edit."""
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    manager.update_bookmark("seed-1", address="My address")

    res = manager.import_catalog(_catalog([_bm(name="Renamed by the catalog")]))

    bm = manager._find_bookmark("seed-1")
    assert bm.name == "Renamed by the catalog"   # never edited locally -> take theirs
    assert bm.address == "My address"            # edited locally -> keep ours
    assert res["kept_local"] == 1 and res["conflicts"] == 0


# ── §4.2 rule table — categories (a separate loop, R2) ────────────────────

def test_category_correction_lands_when_the_user_never_edited_the_field(manager, monkeypatch):
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    before = manager._find_category("seed-cat").updated_at

    res = manager.import_catalog(_catalog(categories=[_cat(name="Event 2026", color="#222222")]))

    cat = manager._find_category("seed-cat")
    assert cat.name == "Event 2026" and cat.color == "#222222"
    assert res["kept_local"] == 0 and res["conflicts"] == 0
    assert cat.updated_at > before


def test_category_local_rename_survives_an_unchanged_catalog(manager, monkeypatch):
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    manager.update_category("seed-cat", name="My Event Name")
    before = manager._find_category("seed-cat").updated_at

    res = manager.import_catalog(_catalog())

    cat = manager._find_category("seed-cat")
    assert cat.name == "My Event Name"
    assert res["kept_local"] == 1 and res["conflicts"] == 0
    assert cat.updated_at == before


def test_category_both_sides_moved_apart_reports_a_conflict(manager, monkeypatch):
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    manager.update_category("seed-cat", color="#abcdef")

    res = manager.import_catalog(_catalog(categories=[_cat(color="#999999")]))

    assert manager._find_category("seed-cat").color == "#abcdef"
    assert res["conflicts"] == 1 and res["kept_local"] == 1


def test_category_both_sides_moved_to_the_same_value_is_a_silent_no_op(manager, monkeypatch):
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    manager.update_category("seed-cat", name="Agreed")
    before = manager._find_category("seed-cat").updated_at

    res = manager.import_catalog(_catalog(categories=[_cat(name="Agreed")]))

    cat = manager._find_category("seed-cat")
    assert cat.name == "Agreed"
    assert res["conflicts"] == 0 and res["kept_local"] == 0
    assert cat.updated_at == before


def test_an_unchanged_category_is_not_re_stamped(manager, monkeypatch):
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    before = manager._find_category("seed-cat").updated_at

    manager.import_catalog(_catalog())

    assert manager._find_category("seed-cat").updated_at == before


# ── Step 1b — the three edges §4.2 / §4.4 rest on ─────────────────────────

def _seed_with_local_country(manager, monkeypatch):
    """A record whose local country_code ('tw') differs from the catalog's
    ('jp'), with lat/lng untouched. The catalog ships 'jp'; enrich_bookmark on
    the ADD branch (force=False) leaves the non-empty incoming value alone, so
    the local edit is applied by hand afterwards — the shape a hand-set or
    previously-resolved flag has in the live store."""
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog([_bm(country_code="jp")]))
    rec = manager._find_bookmark("seed-1")
    rec.country_code = "tw"
    manager._save()
    return manager._find_bookmark("seed-1").updated_at


def test_country_code_comes_from_the_resolver_not_the_catalog(manager, monkeypatch):
    before = _seed_with_local_country(manager, monkeypatch)
    _stub_geo(monkeypatch, ("xx", "Asia/Taipei", "Taipei", "Taiwan"))

    manager.import_catalog(_catalog([_bm(country_code="jp")]))

    bm = manager._find_bookmark("seed-1")
    assert bm.country_code == "xx"      # the resolver's
    assert bm.country_code != "jp"      # not the catalog's
    assert bm.country_code != "tw"      # not the prior local value
    # enrich reported a change, which is §4.4 condition 2.
    assert bm.updated_at > before


def test_country_code_keeps_the_local_value_when_the_resolver_returns_empty(manager, monkeypatch):
    """The discriminating half of the pair: with the resolve empty (ocean
    point, or a venv missing numpy/timezonefinder) enrich writes nothing, so a
    lingering `old.country_code = bm.country_code` would be the last word — and
    would never propagate, because nothing re-stamps the record."""
    before = _seed_with_local_country(manager, monkeypatch)
    _stub_geo(monkeypatch, ("", "", "", ""))

    manager.import_catalog(_catalog([_bm(country_code="jp")]))

    bm = manager._find_bookmark("seed-1")
    assert bm.country_code == "tw"      # the local value survives
    assert bm.country_code != "jp"      # the catalog never writes this field
    assert bm.updated_at == before


def test_an_off_machine_tombstone_still_resurrects_an_unchanged_record(manager, monkeypatch):
    """The tombstone set is the UNION of memory and disk (§4.4).

    A tombstone written by the other Mac and not yet reconciled is invisible in
    self.store.tombstones. Leaving the record unstamped would let _alive() kill
    it inside the very _save() this sync performs.
    """
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())

    # Write the peer's deletion straight into the file, bypassing memory.
    path = Path(manager._bookmarks_path())
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    # deleted_at must be newer than the record's own stamp (so it would win)
    # but older than the sync's `now` (so the re-stamp can out-vote it).
    on_disk["tombstones"] = [
        Tombstone(id="seed-1", kind="bookmark", deleted_at=_now_iso()).model_dump()
    ]
    path.write_text(json.dumps(on_disk), encoding="utf-8")
    assert not any(t.id == "seed-1" for t in manager.store.tombstones)

    res = manager.import_catalog(_catalog())

    assert manager._find_bookmark("seed-1") is not None
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert any(b["id"] == "seed-1" for b in reloaded["bookmarks"])
    # The same union feeds the count, which memory alone would under-report.
    assert res["resurrected"] == 1


# ── Step 1c / 1c-ii — two machines, one store, two baselines ─────────────

def _two_macs(tmp_path, monkeypatch):
    """The repo's two-Mac idiom (one shared store file) plus §5's per-machine
    baseline seam. `seed-edited` is renamed on Mac 1; `seed-clean` is untouched
    by either machine, so the two records exercise different rows."""
    _stub_geo(monkeypatch, _TW)
    store = tmp_path / "shared-bookmarks.json"
    mac1 = make_bookmark_manager(lambda: store, lambda: tmp_path / "baseline-mac1.json")
    mac1.import_catalog(_CATALOG_V1)
    mac1.update_bookmark("seed-edited", name="Renamed On Mac 1")
    mac2 = make_bookmark_manager(lambda: store, lambda: tmp_path / "baseline-mac2.json")
    return store, mac1, mac2


_CATALOG_V1 = _catalog(
    [_bm("seed-edited", name="Catalog Edited"), _bm("seed-clean", name="Catalog Clean")]
)
_CATALOG_V2 = _catalog(
    [_bm("seed-edited", name="Catalog Edited"), _bm("seed-clean", name="Catalog Clean v2")]
)


def test_two_machines_converge_over_three_rounds_and_stay_idempotent(tmp_path, monkeypatch):
    store, mac1, mac2 = _two_macs(tmp_path, monkeypatch)

    for round_no in (1, 2, 3):
        for mac in (mac1, mac2):
            mac._reconcile_from_disk()
            res = mac.import_catalog(_CATALOG_V1)
            assert res["conflicts"] == 0, f"round {round_no}"
            assert res["kept_local"] == 1, f"round {round_no}"  # seed-edited only
        for mac in (mac1, mac2):
            mac._reconcile_from_disk()
            names = {b.id: b.name for b in mac.list_bookmarks()}
            assert names["seed-edited"] == "Renamed On Mac 1", f"round {round_no}"
            assert names["seed-clean"] == "Catalog Clean", f"round {round_no}"

    # (c) each machine wrote its OWN baseline — the file is per machine.
    for name in ("baseline-mac1.json", "baseline-mac2.json"):
        payload = json.loads((tmp_path / name).read_text(encoding="utf-8"))
        assert payload["bookmarks"]["seed-clean"]["name"] == "Catalog Clean"

    # Idempotence: one more sync each changes nothing on disk.
    before = store.read_bytes()
    mac1.import_catalog(_CATALOG_V1)
    mac2._reconcile_from_disk()
    mac2.import_catalog(_CATALOG_V1)
    assert store.read_bytes() == before


def test_the_second_mac_reports_no_conflict_after_the_peer_applied_a_correction(tmp_path, monkeypatch):
    """The `ours == theirs` row, fired by a catalog that MOVES.

    Without that row Mac 2 sees ours != base and theirs != base and reports a
    conflict on a record nobody edited — one the user could never clear,
    because the resolution already equals the catalog.
    """
    store, mac1, mac2 = _two_macs(tmp_path, monkeypatch)
    mac1.import_catalog(_CATALOG_V1)
    mac2._reconcile_from_disk()
    mac2.import_catalog(_CATALOG_V1)

    # 4a — Mac 1 takes the genuine correction (ours == base, theirs != base).
    mac1._reconcile_from_disk()
    before_1 = mac1._find_bookmark("seed-clean").updated_at
    res1 = mac1.import_catalog(_CATALOG_V2)
    clean_1 = mac1._find_bookmark("seed-clean")
    assert clean_1.name == "Catalog Clean v2"
    assert clean_1.updated_at > before_1
    assert res1["conflicts"] == 0

    # 4b — Mac 2 received v2's value through the shared store, not through a
    # sync, while its own baseline still records v1.
    mac2._reconcile_from_disk()
    assert mac2._find_bookmark("seed-clean").name == "Catalog Clean v2"
    before_2 = mac2._find_bookmark("seed-clean").updated_at
    res2 = mac2.import_catalog(_CATALOG_V2)

    clean_2 = mac2._find_bookmark("seed-clean")
    assert res2["conflicts"] == 0
    assert res2["kept_local"] == 1                 # seed-edited only
    assert clean_2.name == "Catalog Clean v2"
    assert clean_2.updated_at == before_2          # nothing was taken from theirs

    # 5 — re-sync v2 on both: a true no-op, bytes unchanged.
    before_bytes = store.read_bytes()
    mac1._reconcile_from_disk()
    assert mac1.import_catalog(_CATALOG_V2)["conflicts"] == 0
    mac2._reconcile_from_disk()
    assert mac2.import_catalog(_CATALOG_V2)["conflicts"] == 0
    assert store.read_bytes() == before_bytes


# ── Step 1d + the port's call contract ───────────────────────────────────

def test_baseline_written_matches_format_version_1_shape(manager, monkeypatch):
    """What import_catalog HANDS the store (Task 3's round-trip proves the
    store persists whatever it is handed)."""
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())

    payload = json.loads(Path(manager._catalog_baseline._path_provider()).read_text(encoding="utf-8"))
    assert set(payload) == {"_meta", "categories", "bookmarks"}
    assert payload["_meta"]["format_version"] == 1
    assert payload["_meta"]["compiled_at"] == "2026-05-23"
    assert payload["_meta"]["applied_at"]
    for entry in payload["bookmarks"].values():
        assert set(entry) == set(BOOKMARK_MERGE_FIELDS)
    for entry in payload["categories"].values():
        assert set(entry) == set(CATEGORY_MERGE_FIELDS)


def test_the_baseline_is_read_once_and_written_once_per_sync(tmp_path, monkeypatch):
    _stub_geo(monkeypatch, _TW)

    class _CountingBaseline:
        def __init__(self):
            self.reads = self.writes = 0
            self.payload = None

        def read(self):
            self.reads += 1
            return self.payload

        def write(self, payload):
            self.writes += 1
            self.payload = payload

    fake = _CountingBaseline()
    mgr = make_bookmark_manager(lambda: tmp_path / "bookmarks.json")
    mgr._catalog_baseline = fake

    mgr.import_catalog(_catalog())

    assert (fake.reads, fake.writes) == (1, 1)


def test_a_manager_without_a_baseline_port_still_syncs(tmp_path, monkeypatch, caplog):
    """R4: the None default degrades to permanent bootstrap, loudly."""
    _stub_geo(monkeypatch, _TW)
    mgr = make_bookmark_manager(lambda: tmp_path / "bookmarks.json")
    mgr._catalog_baseline = None

    with caplog.at_level("WARNING"):
        res = mgr.import_catalog(_catalog())

    assert res["added"] == 2
    assert res["kept_local"] == 0 and res["conflicts"] == 0
    assert any("baseline" in r.message for r in caplog.records)


def test_invalid_catalog_json_returns_all_five_keys_as_zero(manager):
    assert manager.import_catalog("not-json") == {
        "added": 0, "updated": 0, "resurrected": 0, "kept_local": 0, "conflicts": 0,
    }


# ── R1 boundary: the resolver is opt-in per call site ────────────────────

def test_force_seed_still_overwrites_a_diverged_local_record(manager, monkeypatch):
    """force_seed passes no resolver, so its update branch is byte-identical to
    today's blind overwrite. Guarding this is what keeps E1 from leaking into
    the primitive's other two callers (R1)."""
    _stub_geo(monkeypatch, _TW)
    manager.import_catalog(_catalog())
    manager.update_bookmark("seed-1", name="My Renamed Spot")

    from models.schemas import Bookmark
    manager.force_seed([Bookmark(**_bm(name="Seeded Over The Top"))])

    assert manager._find_bookmark("seed-1").name == "Seeded Over The Top"
