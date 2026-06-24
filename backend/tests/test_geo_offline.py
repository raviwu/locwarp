"""Offline geo resolver — known coordinates and graceful failure.

country_code and timezone are asserted exactly: timezonefinder and the
zone_to_country table are deterministic. city / region are only checked
non-empty (plus one substring sanity check) because the exact GeoNames
string depends on the snapshot the generator pulled.
"""
import logging

import services.geo_offline as geo
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
    # (-40, -140) is in the Etc/GMT+9 ocean band; the nearest city is
    # Adamstown (Pitcairn), so cc == "pn".
    cc, zone, city, region = resolve(-40.0, -140.0)
    assert zone == "Etc/GMT+9"
    assert cc == "pn"


def test_resolve_returns_empty_when_data_unavailable(monkeypatch):
    # The one branch every enrich_bookmark caller relies on: when the
    # offline tables can't load, resolve() degrades to all-empty rather
    # than raising. monkeypatch auto-restores module state afterwards.
    monkeypatch.setattr(geo, "_loaded", False)
    monkeypatch.setattr(geo, "_ensure_loaded", lambda: False)
    assert geo.resolve(25.0339, 121.5645) == ("", "", "", "")


def test_transient_load_failure_does_not_latch_forever(monkeypatch):
    """A11: a first failed _ensure_loaded must not permanently blank geo.
    Once the underlying cause clears, the very next resolve() succeeds."""
    # Force a cold module state.
    monkeypatch.setattr(geo, "_loaded", False)
    assert not hasattr(geo, "_load_failed")  # latch removed entirely

    calls = {"n": 0}
    real_ensure = geo._ensure_loaded

    # First _ensure_loaded attempt fails (simulated transient), second succeeds.
    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return False
        return real_ensure()

    monkeypatch.setattr(geo, "_ensure_loaded", flaky)

    # First call: transient failure -> all-empty.
    assert geo.resolve(25.0339, 121.5645) == ("", "", "", "")
    # Second call retries and now resolves for real (no permanent latch).
    cc, zone, city, region = geo.resolve(25.0339, 121.5645)
    assert cc == "tw"
    assert zone == "Asia/Taipei"


def test_resolve_warns_throttled_when_tables_unavailable(monkeypatch, caplog):
    """resolve() logs a single throttled WARNING (not one per call) when the
    offline tables are unavailable."""
    monkeypatch.setattr(geo, "_loaded", False)
    monkeypatch.setattr(geo, "_ensure_loaded", lambda: False)
    monkeypatch.setattr(geo, "_last_warn_ts", 0.0)
    monkeypatch.setattr(geo, "_WARN_THROTTLE_S", 60.0)

    with caplog.at_level(logging.WARNING, logger="services.geo_offline"):
        assert geo.resolve(0.0, 0.0) == ("", "", "", "")
        assert geo.resolve(1.0, 1.0) == ("", "", "", "")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    # Throttled: the two back-to-back calls produce exactly one WARNING.
    assert len(warnings) == 1
    assert "geo" in warnings[0].getMessage().lower()
