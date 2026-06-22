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
    monkeypatch.setattr(
        "config._DEFAULT_BOOKMARKS_FILE", tmp_path / "bookmarks.json"
    )
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json"
    )
    monkeypatch.setattr(
        "services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    yield
    # Tear down the process-wide observer between tests so the next test
    # starts from a clean state.
    from services.file_watcher import shutdown as _shutdown
    _shutdown()


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

    from bootstrap.factories import make_route_manager
    rm = make_route_manager()
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

    from bootstrap.factories import make_route_manager
    rm = make_route_manager()
    fired: list[None] = []
    rm.start_watcher(lambda: fired.append(None))
    try:
        rm.create_category(name="from-self")
        time.sleep(1.0)  # past the debounce
        assert not fired, "self-write should not trigger external-change callback"
    finally:
        rm.stop_watcher()


def test_stop_watcher_idempotent(tmp_path):
    from bootstrap.factories import make_route_manager
    rm = make_route_manager()
    rm.stop_watcher()  # never started
    rm.start_watcher(lambda: None)
    rm.stop_watcher()
    rm.stop_watcher()  # second call must not raise


def test_route_watcher_fires_when_bookmark_watcher_shares_dir(tmp_path):
    """Regression: when BookmarkManager and RouteManager are both
    watching the same parent dir (the default case — ~/.locwarp/), the
    route watcher must still fire on external route file changes. The
    previous implementation gave each manager its own watchdog Observer,
    which on macOS fsevents triggered ``RuntimeError: Cannot add watch
    ... already scheduled`` for the second emitter, so the route
    watcher silently never fired in production."""
    routes_file = tmp_path / "routes.json"
    _write_routes(routes_file, "initial")

    from bootstrap.factories import make_bookmark_manager, make_route_manager

    bm = make_bookmark_manager()
    rm = make_route_manager()

    bm_fired: list[None] = []
    rm_fired: list[None] = []
    bm.start_watcher(lambda: bm_fired.append(None))
    rm.start_watcher(lambda: rm_fired.append(None))
    try:
        _write_routes(routes_file, "external")
        new_mtime = time.time() + 1.0
        os.utime(routes_file, (new_mtime, new_mtime))

        assert _wait_for(lambda: bool(rm_fired)), "route callback never fired"
        assert not bm_fired, "bookmark callback fired on a route file change"
    finally:
        bm.stop_watcher()
        rm.stop_watcher()


def test_two_route_managers_converge_without_clobber(tmp_path):
    """Two RouteManagers on the same file, each saving a distinct route.

    Reproduces symptom 2 for routes: the second _save must read-merge-write
    so the first manager's route survives instead of being overwritten."""
    from models.schemas import Coordinate, SavedRoute
    from bootstrap.factories import make_route_manager

    def _r(name):
        return SavedRoute(
            name=name,
            waypoints=[Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)],
            profile="walking",
        )

    a = make_route_manager()
    b = make_route_manager()
    a.create_route(_r("from-A"))
    b.create_route(_r("from-B"))
    names = {r.name for r in make_route_manager().list_routes()}
    assert names == {"from-A", "from-B"}
