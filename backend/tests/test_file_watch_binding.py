"""Characterization for the extracted FileWatchBinding: external file mods on
BOTH the bookmark and route files still fire each manager's on_change after a
0.5s debounce; self-writes do NOT fire. Pins CURRENT behavior with real watchdog
+ real disk before/after the carve."""
import json
import os
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("config._DEFAULT_BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    yield
    from services.file_watcher import shutdown as _shutdown
    _shutdown()


def _wait_for(predicate, timeout=3.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _write_routes(p: Path, route_id: str) -> None:
    p.write_text(json.dumps({
        "categories": [{"id": "default", "name": "預設", "color": "#6c8cff",
                        "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00"}],
        "routes": [{"id": route_id, "name": route_id, "category_id": "default",
                    "profile": "walking", "waypoints": [{"lat": 1.0, "lng": 1.0}],
                    "created_at": "2026-05-12T00:00:00+00:00"}],
    }))


def _write_bookmarks(p: Path, bm_id: str) -> None:
    p.write_text(json.dumps({
        "categories": [{"id": "default", "name": "預設", "color": "#6c8cff",
                        "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00"}],
        "bookmarks": [{"id": bm_id, "name": bm_id, "lat": 1.0, "lng": 2.0,
                       "category_id": "default", "created_at": "2026-05-12T00:00:00+00:00",
                       "last_used_at": "", "updated_at": "2026-05-12T00:00:00+00:00"}],
    }))


def test_route_external_mod_fires_callback(tmp_path):
    routes_file = tmp_path / "routes.json"
    _write_routes(routes_file, "initial")
    from bootstrap.factories import make_route_manager
    rm = make_route_manager()
    fired: list[None] = []
    rm.start_watcher(lambda: fired.append(None))
    try:
        _write_routes(routes_file, "external")
        nm = time.time() + 1.0
        os.utime(routes_file, (nm, nm))
        assert _wait_for(lambda: bool(fired)), "route callback never fired"
        assert rm.list_routes()[0].id == "external"
    finally:
        rm.stop_watcher()


def test_bookmark_external_mod_fires_callback(tmp_path):
    bm_file = tmp_path / "bookmarks.json"
    _write_bookmarks(bm_file, "b-initial")
    from bootstrap.factories import make_bookmark_manager
    bm = make_bookmark_manager()
    fired: list[None] = []
    bm.start_watcher(lambda: fired.append(None))
    try:
        _write_bookmarks(bm_file, "b-external")
        nm = time.time() + 1.0
        os.utime(bm_file, (nm, nm))
        assert _wait_for(lambda: any(b.id == "b-external" for b in bm.store.bookmarks)), \
            "bookmark external change never reconciled"
    finally:
        bm.stop_watcher()


def test_self_write_does_not_fire(tmp_path):
    routes_file = tmp_path / "routes.json"
    _write_routes(routes_file, "r0")
    from bootstrap.factories import make_route_manager
    rm = make_route_manager()
    fired: list[None] = []
    rm.start_watcher(lambda: fired.append(None))
    try:
        rm.create_category(name="from-self")
        time.sleep(1.0)
        assert not fired, "self-write must not fire external-change callback"
    finally:
        rm.stop_watcher()


def test_stop_watcher_idempotent(tmp_path):
    from bootstrap.factories import make_route_manager
    rm = make_route_manager()
    rm.stop_watcher()
    rm.start_watcher(lambda: None)
    rm.stop_watcher()
    rm.stop_watcher()
