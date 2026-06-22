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

    from bootstrap.factories import make_route_manager
    rm = make_route_manager()
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

    from bootstrap.factories import make_route_manager
    rm = make_route_manager()
    assert len(rm.list_categories()) == 1


# ── Legacy default-category injection net ─────────────────────────────────────

def test_legacy_file_without_categories_injects_default_and_reparents(tmp_path, monkeypatch):
    """RouteManager._load must inject a 'default' category when the on-disk
    file has NO categories (legacy shape), and reparent any orphan routes to it.

    This locks the post_load behavior that Task 4 must preserve after relocating
    file I/O behind a repository port.
    """
    routes_file = tmp_path / "routes.json"
    # Legacy shape: routes present, no categories key, orphan category_id.
    routes_file.write_text(json.dumps({
        "routes": [
            {
                "id": "r1",
                "name": "Legacy Route",
                "category_id": "ghost",
                "profile": "walking",
                "waypoints": [{"lat": 1.0, "lng": 2.0}],
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    }), encoding="utf-8")

    from bootstrap.factories import make_route_manager
    rm = make_route_manager()

    category_ids = {c.id for c in rm.list_categories()}
    assert "default" in category_ids, (
        f"Expected 'default' category after loading legacy file; got: {category_ids}"
    )

    routes = rm.list_routes()
    assert len(routes) == 1
    assert routes[0].category_id == "default", (
        f"Orphan route was not reparented to 'default'; got category_id={routes[0].category_id!r}"
    )


def test_load_store_or_empty_does_not_inject_default_category(tmp_path, monkeypatch):
    """_load_store_or_empty must NOT inject a default category.

    The merge snapshot read path is a pure read helper used inside _save to
    fold concurrent on-disk writes into the current store.  It must return
    the raw store as parsed — without the post_load default-injection that
    _load() does — otherwise merging against an empty file would silently
    add a phantom 'default' category.

    This asymmetry (post_load hook in _load vs. raw parse in _load_store_or_empty)
    is load-bearing for Task 4; if the repository layer's read path accidentally
    applies the injection everywhere, this test goes red.
    """
    routes_file = tmp_path / "routes.json"
    # A file with no categories field at all.
    routes_file.write_text(json.dumps({"routes": []}), encoding="utf-8")

    from services.route_store import _load_store_or_empty
    store = _load_store_or_empty(routes_file)

    assert store.categories == [], (
        f"_load_store_or_empty should not inject 'default'; got categories: {store.categories}"
    )
