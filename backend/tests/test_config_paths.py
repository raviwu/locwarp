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
