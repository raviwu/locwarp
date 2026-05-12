"""Tests for RouteManager file-watcher (external mtime → on_change callback)."""

import json
import os
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config.ROUTES_FILE", tmp_path / "routes.json")
    yield


def _write_routes(p: Path, route_id: str) -> None:
    p.write_text(json.dumps({
        "categories": [{
            "id": "default", "name": "預設", "color": "#6c8cff",
            "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
        }],
        "routes": [{
            "id": route_id, "name": route_id, "category_id": "default",
            "profile": "walking",
            "waypoints": [{"lat": 1.0, "lng": 1.0}],
            "created_at": "2026-05-12T00:00:00+00:00",
        }],
    }))


def _wait_for(predicate, timeout: float = 3.0, interval: float = 0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_external_modification_triggers_callback(tmp_path):
    routes_file = tmp_path / "routes.json"
    _write_routes(routes_file, "initial")

    from services.route_store import RouteManager
    rm = RouteManager()
    assert len(rm.list_routes()) == 1

    fired: list[None] = []
    rm.start_watcher(lambda: fired.append(None))
    try:
        _write_routes(routes_file, "external")
        # Force a distinctly newer mtime so the watcher tick does not
        # mistake it for a self-write.
        new_mtime = time.time() + 1.0
        os.utime(routes_file, (new_mtime, new_mtime))

        assert _wait_for(lambda: bool(fired)), "callback never fired"
        assert rm.list_routes()[0].id == "external"
    finally:
        rm.stop_watcher()


def test_self_write_does_not_trigger_callback(tmp_path):
    routes_file = tmp_path / "routes.json"
    _write_routes(routes_file, "r0")

    from services.route_store import RouteManager
    rm = RouteManager()
    fired: list[None] = []
    rm.start_watcher(lambda: fired.append(None))
    try:
        rm.create_category(name="from-self")
        time.sleep(1.0)  # past the debounce
        assert not fired, "self-write should not trigger external-change callback"
    finally:
        rm.stop_watcher()


def test_stop_watcher_idempotent(tmp_path):
    from services.route_store import RouteManager
    rm = RouteManager()
    rm.stop_watcher()  # never started
    rm.start_watcher(lambda: None)
    rm.stop_watcher()
    rm.stop_watcher()  # second call must not raise
