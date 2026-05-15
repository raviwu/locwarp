"""Offline geo resolver — known coordinates and graceful failure.

country_code and timezone are asserted exactly: timezonefinder and the
zone_to_country table are deterministic. city / region are only checked
non-empty (plus one substring sanity check) because the exact GeoNames
string depends on the snapshot the generator pulled.
"""
from services.geo_offline import resolve


def test_resolve_taipei():
    cc, zone, city, region = resolve(25.0339, 121.5645)
    assert cc == "tw"
    assert zone == "Asia/Taipei"
    assert "taipei" in city.lower()
    assert region != ""


def test_resolve_new_york():
    cc, zone, city, region = resolve(40.7580, -73.9855)
    assert cc == "us"
    assert zone == "America/New_York"
    assert city != ""
    assert region != ""


def test_resolve_london():
    cc, zone, city, region = resolve(51.5074, -0.1278)
    assert cc == "gb"
    assert zone == "Europe/London"
    assert city != ""


def test_resolve_tokyo():
    cc, zone, city, region = resolve(35.6762, 139.6503)
    assert cc == "jp"
    assert zone == "Asia/Tokyo"


def test_resolve_open_ocean_returns_etc_zone():
    # Middle of the South Pacific — TimezoneFinderL covers all ocean areas
    # with Etc/GMT±N zones (it never returns None for a valid coordinate).
    # (-40, -140) falls in the Pitcairn Islands timezone polygon.
    cc, zone, city, region = resolve(-40.0, -140.0)
    assert zone == "Etc/GMT+9"
    assert cc == "pn"
