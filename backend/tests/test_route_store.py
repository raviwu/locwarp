import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config.ROUTES_FILE", tmp_path / "routes.json")
    yield


def test_route_manager_writes_to_sync_folder_when_configured(tmp_path, monkeypatch):
    sync_dir = tmp_path / "iCloud" / "LocWarp"
    sync_dir.mkdir(parents=True)
    (tmp_path / "settings.json").write_text(
        json.dumps({"sync_folder": str(sync_dir)})
    )

    from services.route_store import RouteManager
    rm = RouteManager()
    cat = rm.create_category(name="Test")
    expected_path = sync_dir / "routes.json"
    assert expected_path.exists()
    payload = json.loads(expected_path.read_text())
    assert any(c["id"] == cat.id for c in payload["categories"])


def test_route_manager_reads_from_sync_folder(tmp_path, monkeypatch):
    sync_dir = tmp_path / "iCloud" / "LocWarp"
    sync_dir.mkdir(parents=True)
    (tmp_path / "settings.json").write_text(
        json.dumps({"sync_folder": str(sync_dir)})
    )
    (sync_dir / "routes.json").write_text(json.dumps({
        "categories": [
            {"id": "default", "name": "預設", "color": "#6c8cff",
             "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00"}
        ],
        "routes": [],
    }))

    from services.route_store import RouteManager
    rm = RouteManager()
    assert len(rm.list_categories()) == 1
