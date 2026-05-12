"""AppState: sync_folder field + legacy bookmarks_path auto-migration."""

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config._DEFAULT_BOOKMARKS_FILE",
                        tmp_path / "bookmarks.json")
    monkeypatch.setattr("config.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("main.SETTINGS_FILE", tmp_path / "settings.json")
    yield


def _write_settings(tmp_path, data):
    (tmp_path / "settings.json").write_text(json.dumps(data))


def test_appstate_loads_sync_folder(tmp_path):
    sync_dir = tmp_path / "iCloud" / "LocWarp"
    sync_dir.mkdir(parents=True)
    _write_settings(tmp_path, {"sync_folder": str(sync_dir)})

    import main
    # Reset persisted-state fields on the existing app_state and re-run
    # the loader. We do NOT reload the module nor replace the app_state
    # instance — other test files (test_lifespan.py) bind `app_state` /
    # `helper_client` at module import time, and rebinding either breaks
    # their monkeypatches and runs the real 90s helper handshake.
    main.app_state._sync_folder = None
    main.app_state._cloud_sync_dismissed = False
    main.app_state._load_persisted_state()
    assert main.app_state._sync_folder == str(sync_dir)


def test_legacy_bookmarks_path_auto_migrates(tmp_path):
    sync_dir = tmp_path / "iCloud" / "LocWarp"
    sync_dir.mkdir(parents=True)
    # Legacy: pre-migration user had bookmarks synced to iCloud, routes local.
    (sync_dir / "bookmarks.json").write_text(json.dumps({
        "categories": [{
            "id": "default", "name": "預設", "color": "#6c8cff",
            "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
        }],
        "bookmarks": [],
    }))
    # NOTE: route payload must match SavedRoute schema — adjust as needed
    # (waypoints are list of {lat,lng} dicts; no engine/geometry/duration/distance).
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
    _write_settings(tmp_path, {
        "bookmarks_path": str(sync_dir / "bookmarks.json"),
        "cloud_sync_dismissed": False,
    })

    import main
    # Reset persisted-state fields on the existing app_state and re-run
    # the loader. We do NOT reload the module nor replace the app_state
    # instance — other test files (test_lifespan.py) bind `app_state` /
    # `helper_client` at module import time, and rebinding either breaks
    # their monkeypatches and runs the real 90s helper handshake.
    main.app_state._sync_folder = None
    main.app_state._cloud_sync_dismissed = False
    main.app_state._load_persisted_state()
    state = main.app_state

    # Setting was upgraded.
    assert state._sync_folder == str(sync_dir)
    assert getattr(state, "_bookmarks_path", None) in (None, "")  # legacy gone
    persisted = json.loads((tmp_path / "settings.json").read_text())
    assert persisted.get("sync_folder") == str(sync_dir)
    assert "bookmarks_path" not in persisted

    # Local routes.json was migrated into the sync folder.
    assert (sync_dir / "routes.json").exists()
    moved = json.loads((sync_dir / "routes.json").read_text())
    assert [r["id"] for r in moved["routes"]] == ["r1"]
    assert not (tmp_path / "routes.json").exists()


def test_legacy_bookmarks_path_with_missing_folder_keeps_setting(tmp_path):
    _write_settings(tmp_path, {
        "bookmarks_path": "/no/such/dir/bookmarks.json",
    })

    import main
    # Reset persisted-state fields on the existing app_state and re-run
    # the loader. We do NOT reload the module nor replace the app_state
    # instance — other test files (test_lifespan.py) bind `app_state` /
    # `helper_client` at module import time, and rebinding either breaks
    # their monkeypatches and runs the real 90s helper handshake.
    main.app_state._sync_folder = None
    main.app_state._cloud_sync_dismissed = False
    main.app_state._load_persisted_state()

    # Folder doesn't exist; migration must not crash, must not silently
    # delete legacy setting (user can re-enable later).
    persisted = json.loads((tmp_path / "settings.json").read_text())
    assert persisted.get("bookmarks_path") == "/no/such/dir/bookmarks.json"
    assert persisted.get("sync_folder") is None
