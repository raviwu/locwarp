"""FastAPI integration tests for /api/bookmarks endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient with the bookmark store redirected to tmp_path."""
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    # Force a fresh BookmarkManager so the patched path takes effect.
    import main
    from services.bookmarks import BookmarkManager
    main.app_state.bookmark_manager = BookmarkManager()
    return TestClient(main.app)


def _create_category(client, name="evt"):
    resp = client.post("/api/bookmarks/categories", json={"name": name})
    assert resp.status_code == 200
    return resp.json()


def _create_bookmark(client, cat_id, name="x", lat=0.0, lng=0.0):
    resp = client.post("/api/bookmarks", json={
        "name": name, "lat": lat, "lng": lng, "category_id": cat_id,
    })
    assert resp.status_code == 200
    return resp.json()


def test_delete_category_cascade_false_default(client):
    cat = _create_category(client)
    bm = _create_bookmark(client, cat["id"])
    resp = client.delete(f"/api/bookmarks/categories/{cat['id']}")
    assert resp.status_code == 200
    assert resp.json()["deleted_bookmarks"] == 0
    # Bookmark still present, in default
    listing = client.get("/api/bookmarks").json()
    surviving = [b for b in listing["bookmarks"] if b["id"] == bm["id"]]
    assert surviving and surviving[0]["category_id"] == "default"


def test_delete_category_cascade_true_removes_bookmarks(client):
    cat = _create_category(client)
    bm = _create_bookmark(client, cat["id"])
    resp = client.delete(f"/api/bookmarks/categories/{cat['id']}?cascade=true")
    assert resp.status_code == 200
    assert resp.json()["deleted_bookmarks"] == 1
    listing = client.get("/api/bookmarks").json()
    assert not any(b["id"] == bm["id"] for b in listing["bookmarks"])


def test_delete_default_category_with_cascade_blocked(client):
    resp = client.delete("/api/bookmarks/categories/default?cascade=true")
    assert resp.status_code == 400


def test_export_default_full_store_json(client):
    cat = _create_category(client)
    _create_bookmark(client, cat["id"])
    resp = client.get("/api/bookmarks/export")
    assert resp.status_code == 200
    body = resp.json()
    assert "categories" in body and "bookmarks" in body


def test_export_single_category_json(client):
    cat = _create_category(client, name="京都散步")
    _create_bookmark(client, cat["id"], name="常照皇寺", lat=35.200425, lng=135.685626)
    resp = client.get(f"/api/bookmarks/export?category_id={cat['id']}&format=json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["_meta"]["scope"] == "category"
    assert body["category"]["name"] == "京都散步"
    assert body["bookmarks"][0]["name"] == "常照皇寺"


def test_export_markdown(client):
    cat = _create_category(client, name="京都散步")
    _create_bookmark(client, cat["id"], name="常照皇寺", lat=35.200425, lng=135.685626)
    resp = client.get(f"/api/bookmarks/export?category_id={cat['id']}&format=markdown")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    text = resp.text
    assert text.startswith("## 京都散步\n")
    assert "常照皇寺\n35.200425,135.685626\n" in text


def test_export_geojson(client):
    cat = _create_category(client, name="京都散步")
    _create_bookmark(client, cat["id"], name="常照皇寺", lat=35.200425, lng=135.685626)
    resp = client.get(f"/api/bookmarks/export?category_id={cat['id']}&format=geojson")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/geo+json")
    body = resp.json()
    assert body["type"] == "FeatureCollection"


def test_export_csv(client):
    cat = _create_category(client, name="京都散步")
    _create_bookmark(client, cat["id"], name="常照皇寺", lat=35.200425, lng=135.685626)
    resp = client.get(f"/api/bookmarks/export?category_id={cat['id']}&format=csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "name,lat,lng,category" in resp.text


def test_export_unknown_category_404(client):
    resp = client.get("/api/bookmarks/export?category_id=nope&format=json")
    assert resp.status_code == 404


def test_export_invalid_format_422(client):
    resp = client.get("/api/bookmarks/export?format=yaml")
    assert resp.status_code == 422


def test_import_full_store_via_api(client):
    payload = {
        "categories": [
            {"id": "cat-x", "name": "X", "color": "#ef4444", "sort_order": 1, "created_at": ""},
        ],
        "bookmarks": [
            {"id": "b1", "name": "p", "lat": 1.0, "lng": 2.0, "category_id": "cat-x",
             "created_at": "", "last_used_at": ""},
        ],
    }
    resp = client.post("/api/bookmarks/import", json=payload)
    assert resp.status_code == 200
    assert resp.json()["imported"] == 1


def test_import_single_category_via_api(client):
    payload = {
        "_meta": {"exported_at": "2026-05-09T08:30:00Z", "format_version": 1, "scope": "category"},
        "category": {"id": "shared-id", "name": "京都散步", "color": "#ef4444",
                     "sort_order": 1, "created_at": ""},
        "bookmarks": [
            {"id": "b1", "name": "常照皇寺", "lat": 35.2, "lng": 135.7,
             "category_id": "shared-id", "created_at": "", "last_used_at": ""},
        ],
    }
    resp = client.post("/api/bookmarks/import", json=payload)
    assert resp.status_code == 200
    assert resp.json()["scope"] == "category"
    assert resp.json()["imported"] == 1


def test_import_geojson_via_api(client):
    payload = {
        "type": "FeatureCollection",
        "name": "from-geojson",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [121.5, 25.0]},
             "properties": {"name": "x"}},
        ],
    }
    resp = client.post("/api/bookmarks/import", json=payload)
    assert resp.status_code == 200
    assert resp.json()["scope"] == "geojson"
    assert resp.json()["imported"] == 1


def test_import_garbage_returns_400(client):
    resp = client.post("/api/bookmarks/import", json={"random": True})
    assert resp.status_code == 400


# ── UI state: hidden categories ───────────────────────────────────────────

@pytest.fixture
def ui_state_client(tmp_path, monkeypatch):
    """TestClient with settings.json redirected to tmp_path so the ui-state
    endpoint's save_settings() does not touch the real ~/.locwarp/."""
    settings = tmp_path / "settings.json"
    monkeypatch.setattr("main.SETTINGS_FILE", settings)
    monkeypatch.setattr("config.SETTINGS_FILE", settings)
    import main
    # Go through monkeypatch so pytest auto-restores the singleton's state
    # after the test — consistent with the SETTINGS_FILE patches above.
    monkeypatch.setattr(main.app_state, "_bookmark_expanded_categories", None)
    monkeypatch.setattr(main.app_state, "_bookmark_hidden_categories", None)
    return TestClient(main.app)


def test_ui_state_get_returns_expanded_and_hidden(ui_state_client):
    resp = ui_state_client.get("/api/bookmarks/ui-state")
    assert resp.status_code == 200
    body = resp.json()
    assert "expanded_categories" in body
    assert "hidden_categories" in body


def test_ui_state_post_hidden_persists(ui_state_client):
    resp = ui_state_client.post(
        "/api/bookmarks/ui-state", json={"hidden_categories": ["私人", "測試"]}
    )
    assert resp.status_code == 200
    assert resp.json()["hidden_categories"] == ["私人", "測試"]
    # survives a fresh GET
    assert ui_state_client.get("/api/bookmarks/ui-state").json()["hidden_categories"] == ["私人", "測試"]


def test_ui_state_post_hidden_does_not_clobber_expanded(ui_state_client):
    ui_state_client.post("/api/bookmarks/ui-state", json={"expanded_categories": ["工作"]})
    ui_state_client.post("/api/bookmarks/ui-state", json={"hidden_categories": ["私人"]})
    body = ui_state_client.get("/api/bookmarks/ui-state").json()
    assert body["expanded_categories"] == ["工作"]
    assert body["hidden_categories"] == ["私人"]


def test_ui_state_post_expanded_does_not_clobber_hidden(ui_state_client):
    ui_state_client.post("/api/bookmarks/ui-state", json={"hidden_categories": ["私人"]})
    ui_state_client.post("/api/bookmarks/ui-state", json={"expanded_categories": ["工作"]})
    body = ui_state_client.get("/api/bookmarks/ui-state").json()
    assert body["hidden_categories"] == ["私人"]
    assert body["expanded_categories"] == ["工作"]


def test_ui_state_hidden_round_trips_through_settings(tmp_path, monkeypatch):
    """AppState writes bookmark_hidden_categories to settings.json and
    _load_settings reads it back."""
    import json
    settings = tmp_path / "settings.json"
    monkeypatch.setattr("main.SETTINGS_FILE", settings)
    monkeypatch.setattr("config.SETTINGS_FILE", settings)
    import main
    main.app_state._bookmark_hidden_categories = ["私人", "舊資料"]
    main.app_state.save_settings()
    assert json.loads(settings.read_text())["bookmark_hidden_categories"] == ["私人", "舊資料"]
    main.app_state._bookmark_hidden_categories = None
    main.app_state._load_settings()
    assert main.app_state._bookmark_hidden_categories == ["私人", "舊資料"]


# ── Geo fields: API-layer wire-contract checks ───────────────────────────


def test_create_bookmark_api_returns_geo_fields(client):
    """POST /api/bookmarks resolves geo fields offline before responding —
    locks the wire contract the frontend depends on."""
    cat = _create_category(client)
    resp = client.post(
        "/api/bookmarks",
        json={"name": "Taipei 101", "lat": 25.0339, "lng": 121.5645, "category_id": cat["id"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["country_code"] == "tw"
    assert body["timezone"] == "Asia/Taipei"
    assert body["city"] != ""
    assert body["region"] != ""


def test_list_bookmarks_api_carries_geo_fields(client):
    """GET /api/bookmarks lists each bookmark with its resolved geo fields."""
    cat = _create_category(client)
    _create_bookmark(client, cat["id"], lat=25.0339, lng=121.5645)
    body = client.get("/api/bookmarks").json()
    bms = [b for b in body["bookmarks"] if b["category_id"] == cat["id"]]
    assert len(bms) == 1
    assert bms[0]["country_code"] == "tw"
    assert bms[0]["timezone"] == "Asia/Taipei"
