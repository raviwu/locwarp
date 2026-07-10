"""Characterization tests for scripts/desktop_backup.py's recent-places path.

desktop_backup.py lives outside the backend package (repo-root scripts/) and
is import-safe (``if __name__ == "__main__"``), so it is loaded here by file
path via importlib rather than mutating sys.path. RECENT_PLACES_FILE is a
module-level constant read at call time inside _read_recent, so it can be
monkeypatched on the loaded module object.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "desktop_backup.py"


@pytest.fixture
def desktop_backup():
    spec = importlib.util.spec_from_file_location("desktop_backup_under_test", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_read_recent_returns_empty_list_when_file_missing(desktop_backup, tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_backup, "RECENT_PLACES_FILE", str(tmp_path / "missing.json"))
    assert desktop_backup._read_recent() == []


def test_read_recent_returns_empty_list_on_invalid_json(desktop_backup, tmp_path, monkeypatch):
    p = tmp_path / "recent.json"
    p.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(desktop_backup, "RECENT_PLACES_FILE", str(p))
    assert desktop_backup._read_recent() == []


def test_read_recent_returns_empty_list_when_file_holds_a_json_object(desktop_backup, tmp_path, monkeypatch):
    p = tmp_path / "recent.json"
    p.write_text(json.dumps({"lat": 25.0, "lng": 121.0}), encoding="utf-8")
    monkeypatch.setattr(desktop_backup, "RECENT_PLACES_FILE", str(p))
    assert desktop_backup._read_recent() == []


def test_read_recent_returns_the_array_verbatim(desktop_backup, tmp_path, monkeypatch):
    entries = [{"lat": 25.0, "lng": 121.0, "kind": "route_stop"}]
    p = tmp_path / "recent.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(desktop_backup, "RECENT_PLACES_FILE", str(p))
    assert desktop_backup._read_recent() == entries


def test_content_of_includes_recent_and_excludes_backup_meta(desktop_backup):
    snapshot = {
        "_backup_meta": {"captured_at": "2026-07-10T00:00:00"},
        "bookmarks": {"bookmarks": []},
        "routes": {"routes": []},
        "recent": [{"lat": 1.0, "lng": 2.0}],
    }
    content = json.loads(desktop_backup._content_of(snapshot))
    assert content["recent"] == [{"lat": 1.0, "lng": 2.0}]
    assert "_backup_meta" not in content


def test_payload_changed_flips_true_when_only_recent_data_differs(desktop_backup, tmp_path):
    shared_bookmarks = {"bookmarks": [{"id": "b1"}]}
    shared_routes = {"routes": [{"id": "r1"}]}

    on_disk = {
        "_backup_meta": {"captured_at": "2026-07-10T00:00:00"},
        "bookmarks": shared_bookmarks,
        "routes": shared_routes,
        "recent": [{"lat": 25.0, "lng": 121.0}],
    }
    latest_path = tmp_path / "latest.json"
    latest_path.write_text(json.dumps(on_disk), encoding="utf-8")

    # Same bookmarks/routes, same recent -> unchanged.
    identical_snapshot = {
        "bookmarks": shared_bookmarks,
        "routes": shared_routes,
        "recent": [{"lat": 25.0, "lng": 121.0}],
    }
    assert desktop_backup._payload_changed(identical_snapshot, str(latest_path)) is False

    # Same bookmarks/routes, DIFFERENT recent -> changed.
    recent_differs_snapshot = {
        "bookmarks": shared_bookmarks,
        "routes": shared_routes,
        "recent": [{"lat": 30.0, "lng": 130.0}],
    }
    assert desktop_backup._payload_changed(recent_differs_snapshot, str(latest_path)) is True
