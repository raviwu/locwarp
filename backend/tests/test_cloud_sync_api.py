from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    # Patch config paths so all file I/O stays inside tmp_path
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config._DEFAULT_BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    # Patch main.SETTINGS_FILE so save_settings() writes to tmp_path
    monkeypatch.setattr("main.SETTINGS_FILE", tmp_path / "settings.json")
    # Patch services.bookmarks module-level names so _bookmarks_path() delegates
    # to get_bookmarks_path() (reads from settings).  Both must be the SAME
    # Path object so the ``BOOKMARKS_FILE is not _CONFIG_DEFAULT_BOOKMARKS_FILE``
    # guard evaluates to False and the settings-based lookup is used.
    _default_bm_path = tmp_path / "bookmarks.json"
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", _default_bm_path)
    monkeypatch.setattr(
        "services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE",
        _default_bm_path,
    )
    # Reset app_state so it reads from the patched paths
    import main
    from services.bookmarks import BookmarkManager
    main.app_state.bookmark_manager = BookmarkManager()
    main.app_state._bookmarks_path = None
    main.app_state._cloud_sync_dismissed = False
    return TestClient(main.app)


def test_cloud_sync_status_default(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/bookmarks/cloud-sync/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["current_path"].endswith("bookmarks.json")
    assert body["prompt_dismissed"] is False


def test_cloud_sync_enable_with_custom_folder(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    custom = tmp_path / "fake-icloud"
    custom.mkdir()
    r = client.post(
        "/api/bookmarks/cloud-sync/enable",
        json={"folder": str(custom)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["sync_folder"] == str(custom / "LocWarp")
    assert Path(body["current_path"]).parent == custom / "LocWarp"


def test_cloud_sync_disable_resets_path(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    custom = tmp_path / "fake-icloud"
    custom.mkdir()
    client.post("/api/bookmarks/cloud-sync/enable", json={"folder": str(custom)})
    r = client.post("/api/bookmarks/cloud-sync/disable")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False


def test_cloud_sync_dismiss_prompt(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.post("/api/bookmarks/cloud-sync/dismiss-prompt")
    assert r.status_code == 200
    assert r.json()["prompt_dismissed"] is True
