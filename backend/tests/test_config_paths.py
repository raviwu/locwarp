import json
from pathlib import Path

from services.json_safe import safe_write_json


def test_get_bookmarks_path_default(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    from config import get_bookmarks_path
    assert get_bookmarks_path() == tmp_path / "bookmarks.json"


def test_get_bookmarks_path_uses_settings_override(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    settings = tmp_path / "settings.json"
    monkeypatch.setattr("config.SETTINGS_FILE", settings)
    override = tmp_path / "cloud" / "LocWarp" / "bookmarks.json"
    override.parent.mkdir(parents=True)
    safe_write_json(settings, {"bookmarks_path": str(override)})
    from config import get_bookmarks_path
    assert get_bookmarks_path() == override


def test_get_bookmarks_path_falls_back_when_settings_malformed(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    settings = tmp_path / "settings.json"
    settings.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr("config.SETTINGS_FILE", settings)
    from config import get_bookmarks_path
    assert get_bookmarks_path() == tmp_path / "bookmarks.json"


def test_get_routes_path_default_when_no_sync_folder(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    from config import get_routes_path
    assert get_routes_path() == tmp_path / "routes.json"


def test_get_routes_path_honours_sync_folder(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    sync_dir = tmp_path / "iCloud" / "LocWarp"
    sync_dir.mkdir(parents=True)
    (tmp_path / "settings.json").write_text(
        '{"sync_folder": "%s"}' % sync_dir
    )
    from config import get_routes_path
    assert get_routes_path() == sync_dir / "routes.json"


def test_get_routes_path_falls_back_when_sync_folder_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text(
        '{"sync_folder": "/no/such/dir"}'
    )
    from config import get_routes_path
    assert get_routes_path() == tmp_path / "routes.json"


def test_get_routes_path_legacy_bookmarks_path_honoured(tmp_path, monkeypatch):
    # During the migration window, legacy bookmarks_path's parent acts as
    # the sync folder so routes co-locate with bookmarks even before the
    # AppState migration runs.
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    sync_dir = tmp_path / "legacy" / "LocWarp"
    sync_dir.mkdir(parents=True)
    (tmp_path / "settings.json").write_text(
        '{"bookmarks_path": "%s"}' % (sync_dir / "bookmarks.json")
    )
    from config import get_routes_path
    assert get_routes_path() == sync_dir / "routes.json"
