"""Bookmark schema carries the offline geo-metadata fields."""
from models.schemas import Bookmark


def test_bookmark_geo_fields_default_empty():
    bm = Bookmark(name="x", lat=25.03, lng=121.56)
    assert bm.timezone == ""
    assert bm.city == ""
    assert bm.region == ""


def test_bookmark_geo_fields_round_trip():
    bm = Bookmark(
        name="x", lat=25.03, lng=121.56,
        timezone="Asia/Taipei", city="Taipei", region="Taipei",
    )
    dumped = bm.model_dump()
    assert dumped["timezone"] == "Asia/Taipei"
    assert dumped["city"] == "Taipei"
    assert dumped["region"] == "Taipei"
    assert Bookmark(**dumped).timezone == "Asia/Taipei"
