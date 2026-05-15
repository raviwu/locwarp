"""enrich_bookmark — offline geo-field fill and force-refresh semantics."""
import pytest

from models.schemas import Bookmark
from services.bookmarks import BookmarkManager, enrich_bookmark


def test_enrich_fills_blank_fields():
    bm = Bookmark(name="x", lat=25.0339, lng=121.5645)
    changed = enrich_bookmark(bm)
    assert changed is True
    assert bm.country_code == "tw"
    assert bm.timezone == "Asia/Taipei"
    assert bm.city != ""
    assert bm.region != ""


def test_enrich_noop_when_all_filled():
    bm = Bookmark(name="x", lat=25.0339, lng=121.5645,
                  country_code="zz", timezone="Z/Z", city="C", region="R")
    changed = enrich_bookmark(bm)
    assert changed is False
    assert bm.country_code == "zz"  # untouched


def test_enrich_force_overwrites_existing():
    bm = Bookmark(name="x", lat=25.0339, lng=121.5645,
                  country_code="zz", timezone="Z/Z", city="C", region="R")
    changed = enrich_bookmark(bm, force=True)
    assert changed is True
    assert bm.country_code == "tw"
    assert bm.timezone == "Asia/Taipei"


def test_enrich_leaves_fields_untouched_when_resolve_empty(monkeypatch):
    # resolve() returns all-empty only when the offline tables fail to load.
    # enrich_bookmark must never write an empty value over a blank field
    # (and must report no change), so a transient load failure can't wipe
    # data. monkeypatch auto-restores _geo_resolve afterwards.
    monkeypatch.setattr("services.bookmarks._geo_resolve",
                        lambda lat, lng: ("", "", "", ""))
    bm = Bookmark(name="x", lat=25.0339, lng=121.5645)
    changed = enrich_bookmark(bm)
    assert changed is False
    assert bm.country_code == "" and bm.timezone == ""
    assert bm.city == "" and bm.region == ""


def test_enrich_does_not_touch_updated_at():
    bm = Bookmark(name="x", lat=25.0339, lng=121.5645, updated_at="2020-01-01")
    enrich_bookmark(bm)
    assert bm.updated_at == "2020-01-01"


def test_enrich_partial_fill_only_blank_fields(monkeypatch):
    # The common enrich_all() case: a legacy bookmark with some fields set
    # and some blank. force=False fills only the blanks, preserves the rest.
    monkeypatch.setattr("services.bookmarks._geo_resolve",
                        lambda lat, lng: ("tw", "Asia/Taipei", "Taipei", "Taipei City"))
    bm = Bookmark(name="x", lat=25.0, lng=121.5,
                  country_code="zz", timezone="", city="", region="")
    changed = enrich_bookmark(bm)
    assert changed is True
    assert bm.country_code == "zz"       # existing value preserved
    assert bm.timezone == "Asia/Taipei"  # blank filled
    assert bm.city == "Taipei"
    assert bm.region == "Taipei City"


def test_enrich_partial_resolve_skips_empty_fields(monkeypatch):
    # resolve() can return a partial tuple (e.g. region empty when the
    # admin1 lookup misses). The "never write empty" rule is per-field:
    # non-empty fields are filled, empty ones stay blank.
    monkeypatch.setattr("services.bookmarks._geo_resolve",
                        lambda lat, lng: ("tw", "Asia/Taipei", "Taipei", ""))
    bm = Bookmark(name="x", lat=25.0, lng=121.5)
    changed = enrich_bookmark(bm)
    assert changed is True
    assert bm.country_code == "tw"
    assert bm.timezone == "Asia/Taipei"
    assert bm.city == "Taipei"
    assert bm.region == ""  # empty resolve value not written


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """A BookmarkManager with its store redirected to tmp_path.

    Mirrors the fixture in test_list_ordering.py: patch BOOKMARKS_FILE and
    replace the captured config default so _bookmarks_path() honours it.
    """
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", object())
    return BookmarkManager()


def test_create_bookmark_enriches(manager):
    bm = manager.create_bookmark(name="Taipei 101", lat=25.0339, lng=121.5645)
    assert bm.country_code == "tw"
    assert bm.timezone == "Asia/Taipei"
    assert bm.city != ""
    assert bm.region != ""


def test_update_bookmark_reresolves_on_coord_change(manager):
    bm = manager.create_bookmark(name="x", lat=25.0339, lng=121.5645)
    assert bm.country_code == "tw"
    updated = manager.update_bookmark(bm.id, lat=35.6762, lng=139.6503)  # Tokyo
    assert updated.country_code == "jp"
    assert updated.timezone == "Asia/Tokyo"


def test_update_bookmark_keeps_geo_when_coords_unchanged(manager):
    bm = manager.create_bookmark(name="x", lat=25.0339, lng=121.5645)
    tz_before, city_before = bm.timezone, bm.city
    updated = manager.update_bookmark(bm.id, name="renamed")
    assert updated.timezone == tz_before
    assert updated.city == city_before
    assert updated.name == "renamed"


def test_update_bookmark_lat_only_change_triggers_reresolve(manager, monkeypatch):
    # A real user action: vertical drag changes only lat. The disjunction
    # in update_bookmark's change-detection must fire on either side, and
    # the resolver must be called with the new lat + the original lng.
    bm = manager.create_bookmark(name="x", lat=25.0339, lng=121.5645)
    calls: list[tuple[float, float]] = []

    def fake_resolve(lat, lng):
        calls.append((lat, lng))
        return ("xx", "Test/Zone", "TestCity", "TestRegion")

    monkeypatch.setattr("services.bookmarks._geo_resolve", fake_resolve)
    updated = manager.update_bookmark(bm.id, lat=35.6762)  # lng unchanged
    assert calls == [(35.6762, 121.5645)]
    assert updated.country_code == "xx"
    assert updated.timezone == "Test/Zone"


def test_import_json_enriches_bookmarks(manager):
    payload = (
        '{"categories": [], "bookmarks": ['
        '{"id": "imp1", "name": "Tokyo Tower", "lat": 35.6586, "lng": 139.7454, '
        '"category_id": "default"}]}'
    )
    manager.import_json(payload)
    bm = next(b for b in manager.store.bookmarks if b.id == "imp1")
    assert bm.country_code == "jp"
    assert bm.timezone == "Asia/Tokyo"
    assert bm.city != ""


def test_import_geojson_enriches_bookmarks(manager):
    from services.bookmark_import import detect_and_import

    payload = (
        '{"type": "FeatureCollection", "name": "trip", "features": ['
        '{"type": "Feature", "geometry": {"type": "Point", '
        '"coordinates": [121.5645, 25.0339]}, "properties": {"name": "Taipei 101"}}]}'
    )
    detect_and_import(manager, payload)
    bm = next(b for b in manager.store.bookmarks if b.name == "Taipei 101")
    assert bm.country_code == "tw"
    assert bm.timezone == "Asia/Taipei"


def test_import_single_category_enriches_bookmarks(manager):
    # The third import path: _meta / category / bookmarks shape (single-
    # category export). Symmetric assertion-level coverage with the other
    # two import paths so the enrich call there cannot regress silently.
    from services.bookmark_import import detect_and_import

    payload = (
        '{"_meta": {"scope": "category"}, '
        '"category": {"name": "trip", "color": "#6c8cff"}, '
        '"bookmarks": [{"name": "Taipei 101", "lat": 25.0339, "lng": 121.5645}]}'
    )
    detect_and_import(manager, payload)
    bm = next(b for b in manager.store.bookmarks if b.name == "Taipei 101")
    assert bm.country_code == "tw"
    assert bm.timezone == "Asia/Taipei"
    assert bm.city != ""


def test_enrich_all_fills_legacy_bookmarks(manager):
    manager.store.bookmarks = [
        Bookmark(id="a", name="Taipei", lat=25.0339, lng=121.5645),
        Bookmark(id="b", name="Tokyo", lat=35.6762, lng=139.6503),
    ]
    n = manager.enrich_all()
    assert n == 2
    assert manager.store.bookmarks[0].country_code == "tw"
    assert manager.store.bookmarks[1].country_code == "jp"


def test_enrich_all_idempotent(manager):
    manager.store.bookmarks = [Bookmark(id="a", name="x", lat=25.0339, lng=121.5645)]
    assert manager.enrich_all() == 1
    assert manager.enrich_all() == 0  # second sweep changes nothing


def test_enrich_all_does_not_bump_updated_at(manager):
    manager.store.bookmarks = [
        Bookmark(id="a", name="x", lat=25.0339, lng=121.5645, updated_at="2020-01-01"),
    ]
    manager.enrich_all()
    assert manager.store.bookmarks[0].updated_at == "2020-01-01"
