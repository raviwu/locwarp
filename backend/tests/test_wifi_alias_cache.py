"""Bonjour-id → {udid, DeviceName} alias cache used by /wifi/tunnel/discover
so the picker can show "Ravi's iPhone" instead of the bare RemotePairing
hex id or an IPv6 link-local address.

The cache is intentionally tolerant — corrupt / partial entries are dropped
silently (best-effort UX polish, not authoritative state). Generic
DeviceClass fallbacks ("iPhone" / "Unknown") are not written, so a once-known
real name is never overwritten by a degraded read.
"""

import json

import pytest

from core.device_manager import (
    _load_wifi_alias_cache,
    _remember_wifi_alias,
    strip_bonjour_suffix,
)


@pytest.fixture(autouse=True)
def isolated_alias_file(tmp_path, monkeypatch):
    path = tmp_path / "wifi_aliases.json"
    monkeypatch.setattr("config.WIFI_ALIASES_FILE", path)
    monkeypatch.setattr("core.device_manager.WIFI_ALIASES_FILE", path)
    yield path


# ---------------------------------------------------------------------------
# strip_bonjour_suffix
# ---------------------------------------------------------------------------


def test_strip_bonjour_suffix_removes_remotepairing_ptr():
    assert (
        strip_bonjour_suffix("ABCDEF1234567890._remotepairing._tcp.local.")
        == "ABCDEF1234567890"
    )


def test_strip_bonjour_suffix_handles_missing_trailing_dot():
    # Some pymobiledevice3 paths normalize away the trailing dot; either
    # form must yield the same stable id so the cache key is consistent.
    assert (
        strip_bonjour_suffix("ABCDEF1234567890._remotepairing._tcp.local")
        == "ABCDEF1234567890"
    )


def test_strip_bonjour_suffix_returns_empty_for_falsy():
    assert strip_bonjour_suffix("") == ""
    assert strip_bonjour_suffix(None) == ""


def test_strip_bonjour_suffix_keeps_input_when_suffix_absent():
    # Defensive: if the PTR ever changes shape we still produce *something*
    # usable as a cache key rather than silently nuking it.
    assert strip_bonjour_suffix("weird-id.local.") == "weird-id.local"


# ---------------------------------------------------------------------------
# _load_wifi_alias_cache
# ---------------------------------------------------------------------------


def test_load_returns_empty_when_file_missing(isolated_alias_file):
    assert _load_wifi_alias_cache() == {}


def test_load_parses_valid_entries(isolated_alias_file):
    isolated_alias_file.write_text(
        json.dumps({"BONJ1": {"udid": "udid-1", "name": "Ravi's iPhone"}})
    )
    cache = _load_wifi_alias_cache()
    assert cache == {"BONJ1": {"udid": "udid-1", "name": "Ravi's iPhone"}}


def test_load_drops_malformed_entries(isolated_alias_file):
    isolated_alias_file.write_text(
        json.dumps(
            {
                "good": {"udid": "u", "name": "Real Phone"},
                "no-name": {"udid": "u"},
                "no-udid": {"name": "x"},
                "wrong-shape": "not a dict",
                "empty-name": {"udid": "u", "name": ""},
            }
        )
    )
    cache = _load_wifi_alias_cache()
    assert list(cache.keys()) == ["good"]


def test_load_returns_empty_on_corrupt_file(isolated_alias_file):
    isolated_alias_file.write_text("{not json")
    assert _load_wifi_alias_cache() == {}


# ---------------------------------------------------------------------------
# _remember_wifi_alias
# ---------------------------------------------------------------------------


def test_remember_writes_new_entry(isolated_alias_file):
    _remember_wifi_alias("BONJ1", "udid-1", "Ravi's iPhone")
    assert json.loads(isolated_alias_file.read_text()) == {
        "BONJ1": {"udid": "udid-1", "name": "Ravi's iPhone"}
    }


def test_remember_skips_generic_devicename(isolated_alias_file):
    # If we cached "iPhone" we'd mislabel every entry as "iPhone" on
    # subsequent discovers — worse than showing the bonjour_id.
    _remember_wifi_alias("BONJ1", "udid-1", "iPhone")
    assert not isolated_alias_file.exists()


def test_remember_skips_empty_inputs(isolated_alias_file):
    _remember_wifi_alias("", "udid-1", "Ravi's iPhone")
    _remember_wifi_alias("BONJ1", "", "Ravi's iPhone")
    _remember_wifi_alias("BONJ1", "udid-1", "")
    assert not isolated_alias_file.exists()


def test_remember_is_idempotent(isolated_alias_file):
    _remember_wifi_alias("BONJ1", "udid-1", "Ravi's iPhone")
    first_mtime = isolated_alias_file.stat().st_mtime_ns
    # Second identical write should not touch the file at all.
    _remember_wifi_alias("BONJ1", "udid-1", "Ravi's iPhone")
    assert isolated_alias_file.stat().st_mtime_ns == first_mtime


def test_remember_overwrites_on_rename(isolated_alias_file):
    _remember_wifi_alias("BONJ1", "udid-1", "Old Name")
    _remember_wifi_alias("BONJ1", "udid-1", "Renamed Phone")
    assert json.loads(isolated_alias_file.read_text()) == {
        "BONJ1": {"udid": "udid-1", "name": "Renamed Phone"}
    }


def test_remember_keeps_other_aliases(isolated_alias_file):
    _remember_wifi_alias("BONJ1", "udid-1", "Phone A")
    _remember_wifi_alias("BONJ2", "udid-2", "Phone B")
    data = json.loads(isolated_alias_file.read_text())
    assert data == {
        "BONJ1": {"udid": "udid-1", "name": "Phone A"},
        "BONJ2": {"udid": "udid-2", "name": "Phone B"},
    }
