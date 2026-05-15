"""enrich_bookmark — offline geo-field fill and force-refresh semantics."""
from models.schemas import Bookmark
from services.bookmarks import enrich_bookmark


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
