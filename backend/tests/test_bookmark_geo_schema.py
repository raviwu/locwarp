"""Bookmark schema carries the offline geo-metadata fields."""
from __future__ import annotations

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
    rehydrated = Bookmark(**dumped)
    assert rehydrated.timezone == "Asia/Taipei"
    assert rehydrated.city == "Taipei"
    assert rehydrated.region == "Taipei"
