"""End-to-end tests for /api/cloud-sync/*."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config._DEFAULT_BOOKMARKS_FILE",
                        tmp_path / "bookmarks.json")
    monkeypatch.setattr("config.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("main.SETTINGS_FILE", tmp_path / "settings.json")

    # Force services.bookmarks to fall through to get_bookmarks_path()
    _default_bm = tmp_path / "bookmarks.json"
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", _default_bm)
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE",
                        _default_bm)
    _default_rt = tmp_path / "routes.json"
    monkeypatch.setattr("services.route_store.ROUTES_FILE", _default_rt)
    monkeypatch.setattr("services.route_store._CONFIG_DEFAULT_ROUTES_FILE",
                        _default_rt)

    import main
    # Reset persisted-state fields on the existing app_state and re-run
    # the loader, instead of reloading the module or replacing the
    # instance. test_lifespan.py imports `app_state` / `helper_client` at
    # module collection time; rebinding either makes its monkeypatches
    # target a stale instance and the real 90s helper handshake runs.
    main.app_state._sync_folder = None
    main.app_state._cloud_sync_dismissed = False
    main.app_state._load_persisted_state()
    # Stop any watcher left from a previous test before swapping managers,
    # otherwise watchdog raises "Cannot add watch ... already scheduled".
    if main.app_state.bookmark_manager is not None:
        main.app_state.bookmark_manager.stop_watcher()
    if main.app_state.route_manager is not None:
        main.app_state.route_manager.stop_watcher()
    # app_state.bookmark_manager / route_manager are None until load_state
    # runs (only inside the FastAPI lifespan; TestClient without `with` does
    # not trigger it). Initialize them directly so the router's
    # _build_status() has non-None managers to call.
    from bootstrap.factories import make_bookmark_manager, make_route_manager
    main.app_state.bookmark_manager = make_bookmark_manager()
    main.app_state.route_manager = make_route_manager()
    # Write an initial settings.json so tests that read it after a failed
    # operation can rely on the file existing (even if sync_folder is absent).
    main.app_state.save_settings()
    return TestClient(main.app)


def test_status_default(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/cloud-sync/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["sync_folder"] is None
    assert body["bookmarks"]["count"] == 0
    assert body["routes"]["count"] == 0


def test_enable_with_custom_folder(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    custom = tmp_path / "fake-icloud"
    custom.mkdir()

    r = client.post("/api/cloud-sync/enable", json={"folder": str(custom)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["sync_folder"] == str(custom / "LocWarp")
    assert body["bookmarks"]["path"] == str(custom / "LocWarp" / "bookmarks.json")
    assert body["routes"]["path"] == str(custom / "LocWarp" / "routes.json")
    assert (custom / "LocWarp").exists()


def test_enable_migrates_local_routes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    # Seed a local route via the regular file shape. Use the schema fields
    # SavedRoute actually requires (waypoints = list of {lat, lng}).
    (tmp_path / "routes.json").write_text(json.dumps({
        "categories": [{
            "id": "default", "name": "預設", "color": "#6c8cff",
            "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
        }],
        "routes": [{
            "id": "r1", "name": "Loop", "category_id": "default",
            "waypoints": [{"lat": 1.0, "lng": 1.0}],
            "created_at": "2026-05-12T00:00:00+00:00",
        }],
    }))

    custom = tmp_path / "fake-icloud"
    custom.mkdir()
    r = client.post("/api/cloud-sync/enable", json={"folder": str(custom)})
    assert r.status_code == 200, r.text
    assert (custom / "LocWarp" / "routes.json").exists()
    assert not (tmp_path / "routes.json").exists()


def test_disable_moves_back(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    custom = tmp_path / "fake-icloud"
    custom.mkdir()
    client.post("/api/cloud-sync/enable", json={"folder": str(custom)})
    r = client.post("/api/cloud-sync/disable")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["sync_folder"] is None


def test_enable_rollback_on_failure(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    # Seed local bookmarks so migrate_pair has work to do.
    (tmp_path / "bookmarks.json").write_text(json.dumps({
        "categories": [{
            "id": "default", "name": "預設", "color": "#6c8cff",
            "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
        }],
        "bookmarks": [{
            "id": "a", "name": "A", "lat": 1.0, "lng": 1.0,
            "category_id": "default",
            "created_at": "2026-05-12T00:00:00+00:00",
        }],
    }))
    # Inject failure in migrate_pair.
    import services.cloud_sync as cs
    orig = cs._move_or_merge_file
    def boom(src, dst, kind):
        if kind == "routes":
            raise OSError("boom")
        return orig(src, dst, kind)
    monkeypatch.setattr(cs, "_move_or_merge_file", boom)

    custom = tmp_path / "fake-icloud"
    custom.mkdir()
    r = client.post("/api/cloud-sync/enable", json={"folder": str(custom)})
    assert r.status_code == 500, r.text

    # Settings must not record the failed enable.
    settings = json.loads((tmp_path / "settings.json").read_text())
    assert settings.get("sync_folder") is None
    # Local file must still be intact.
    assert (tmp_path / "bookmarks.json").exists()


def test_dismiss_prompt(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.post("/api/cloud-sync/dismiss-prompt")
    assert r.status_code == 200
    assert r.json()["prompt_dismissed"] is True
