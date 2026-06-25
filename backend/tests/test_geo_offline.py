"""Offline geo resolver — known coordinates and graceful failure.

country_code and timezone are asserted exactly: timezonefinder and the
zone_to_country table are deterministic. city / region are only checked
non-empty (plus one substring sanity check) because the exact GeoNames
string depends on the snapshot the generator pulled.
"""
import logging
import time

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


# ── Fix 3: time-based retry gate tests ────────────────────────────────────────

def test_failed_load_short_circuits_within_window(monkeypatch):
    """Fix 3: when load fails, subsequent calls within _RETRY_AFTER_S must
    NOT re-attempt the import — they must short-circuit and return False without
    calling the loader again. This prevents N failed imports + N tracebacks on
    bulk bookmark imports."""
    load_call_count = [0]

    def _failing_loader():
        load_call_count[0] += 1
        raise ImportError("numpy not available")

    # Cold module state + a very wide retry window.
    monkeypatch.setattr(geo, "_loaded", False)
    monkeypatch.setattr(geo, "_last_attempt_ts", 0.0)
    monkeypatch.setattr(geo, "_RETRY_AFTER_S", 3600.0)  # 1 hour — never expires in test

    # Patch the inner loader (numpy import) by patching _ensure_loaded directly,
    # BUT we need to test the real _ensure_loaded (the retry gate). So instead
    # we patch the inner_loader by patching numpy import via the module global.
    # Simpler: reset state then patch the inner try block via the module-level
    # _loaded=False + inject a fake "already failed" timestamp after first call.

    # We'll test via resolve() calling _ensure_loaded() multiple times.
    # Patch numpy to make the load fail deterministically.
    import builtins
    real_import = builtins.__import__

    def _bad_import(name, *args, **kwargs):
        if name == "numpy":
            load_call_count[0] += 1
            raise ImportError("numpy unavailable for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _bad_import)

    # First call: should attempt load, fail, record timestamp, return ("","","","").
    result1 = geo.resolve(25.0, 121.0)
    assert result1 == ("", "", "", "")
    count_after_first = load_call_count[0]
    assert count_after_first >= 1, "loader must be attempted on first call"

    # Second call: within the retry window → must NOT re-attempt the import.
    result2 = geo.resolve(26.0, 122.0)
    assert result2 == ("", "", "", "")
    assert load_call_count[0] == count_after_first, (
        f"load was re-attempted within the window (call count rose from "
        f"{count_after_first} to {load_call_count[0]})"
    )


def test_failed_load_retries_after_window(monkeypatch):
    """Fix 3: once _RETRY_AFTER_S has elapsed, _ensure_loaded must retry the
    import (the underlying issue may have been fixed — venv updated, file
    re-materialized from iCloud). The success path still self-recovers."""
    load_call_count = [0]

    import builtins
    real_import = builtins.__import__

    def _bad_import(name, *args, **kwargs):
        if name == "numpy":
            load_call_count[0] += 1
            raise ImportError("numpy unavailable for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _bad_import)
    monkeypatch.setattr(geo, "_loaded", False)
    monkeypatch.setattr(geo, "_last_attempt_ts", 0.0)
    monkeypatch.setattr(geo, "_RETRY_AFTER_S", 0.05)  # 50ms window — expires fast

    # First call: attempt + fail.
    geo.resolve(25.0, 121.0)
    count_after_first = load_call_count[0]

    # Still within window → no retry.
    geo.resolve(25.0, 121.0)
    assert load_call_count[0] == count_after_first

    # Advance past the window by sleeping longer than 50ms.
    time.sleep(0.1)

    # Now: the window has expired, should retry.
    geo.resolve(25.0, 121.0)
    assert load_call_count[0] > count_after_first, (
        "load must be retried after the window expires"
    )


def test_load_failure_logs_at_most_once_per_window(monkeypatch, caplog):
    """Fix 3: the logger.exception inside the failing load must not fire once
    per call — it must be throttled (at most once per retry window)."""
    import builtins
    real_import = builtins.__import__

    def _bad_import(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("numpy unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _bad_import)
    monkeypatch.setattr(geo, "_loaded", False)
    monkeypatch.setattr(geo, "_last_attempt_ts", 0.0)
    monkeypatch.setattr(geo, "_RETRY_AFTER_S", 3600.0)

    with caplog.at_level(logging.ERROR, logger="services.geo_offline"):
        for _ in range(5):
            geo.resolve(float(_ * 10), float(_ * 10))

    # Only the first call should produce an exception/error log.
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) <= 1, (
        f"Expected at most 1 error log within window, got {len(error_records)}: "
        + "; ".join(r.getMessage() for r in error_records)
    )
