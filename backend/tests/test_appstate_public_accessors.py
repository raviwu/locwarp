"""Characterization: initial-position + bookmark ui-state endpoints return the
exact JSON before/after AppState gains public accessors. Behavior freeze."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("main.SETTINGS_FILE", tmp_path / "settings.json")
    import main
    # Reset the persisted UI fields on the live app_state (do NOT rebind the
    # module-level app_state — other test files bind it at import time).
    main.app_state._initial_map_position = None
    main.app_state._bookmark_expanded_categories = None
    main.app_state._bookmark_hidden_categories = None
    return TestClient(main.app)


def test_initial_position_roundtrip(client):
    assert client.get("/api/location/settings/initial-position").json() == {"position": None}
    r = client.put("/api/location/settings/initial-position", json={"lat": 25.0, "lng": 121.5})
    assert r.status_code == 200
    assert r.json() == {"position": {"lat": 25.0, "lng": 121.5}}
    assert client.get("/api/location/settings/initial-position").json() == {
        "position": {"lat": 25.0, "lng": 121.5}
    }
    # Clear with null lat/lng.
    r = client.put("/api/location/settings/initial-position", json={"lat": None, "lng": None})
    assert r.json() == {"position": None}


def test_initial_position_rejects_out_of_range(client):
    r = client.put("/api/location/settings/initial-position", json={"lat": 200.0, "lng": 0.0})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_coord"


def test_bookmark_ui_state_per_field_update(client):
    assert client.get("/api/bookmarks/ui-state").json() == {
        "expanded_categories": None, "hidden_categories": None
    }
    # POST only expanded -> hidden stays None.
    r = client.post("/api/bookmarks/ui-state", json={"expanded_categories": ["a", "b"]})
    assert r.json() == {"status": "ok", "expanded_categories": ["a", "b"], "hidden_categories": None}
    # POST only hidden -> expanded unchanged (per-field, no clobber).
    r = client.post("/api/bookmarks/ui-state", json={"hidden_categories": ["c"]})
    assert r.json() == {"status": "ok", "expanded_categories": ["a", "b"], "hidden_categories": ["c"]}
    assert client.get("/api/bookmarks/ui-state").json() == {
        "expanded_categories": ["a", "b"], "hidden_categories": ["c"]
    }
