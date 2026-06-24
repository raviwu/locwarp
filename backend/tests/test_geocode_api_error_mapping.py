"""End-to-end wire-response tests for the GeocodeError -> HTTPException mapping."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from domain.errors import GeocodeError


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


def _raise(exc):
    async def _boom(*args, **kwargs):
        raise exc
    return _boom


def test_search_missing_google_key_maps_to_400(monkeypatch, client):
    import main
    monkeypatch.setattr(main.app.state.container.geocoding_service, "search",
                        _raise(GeocodeError(400, "google_missing_key",
                                            "provider=google requires google_key")))
    res = client.get("/api/geocode/search", params={"q": "x", "provider": "google"})
    assert res.status_code == 400
    assert res.json() == {"detail": "provider=google requires google_key"}


def test_search_google_http_maps_to_502(monkeypatch, client):
    import main
    monkeypatch.setattr(main.app.state.container.geocoding_service, "search",
                        _raise(GeocodeError(502, "google_http",
                                            "Google geocode HTTP 403: Forbidden body text")))
    res = client.get("/api/geocode/search", params={"q": "x"})
    assert res.status_code == 502
    assert res.json() == {"detail": "Google geocode HTTP 403: Forbidden body text"}


def test_search_google_status_maps_to_502(monkeypatch, client):
    import main
    monkeypatch.setattr(main.app.state.container.geocoding_service, "search",
                        _raise(GeocodeError(502, "google_status",
                                            "Google geocode REQUEST_DENIED: The provided API key is invalid.")))
    res = client.get("/api/geocode/search", params={"q": "x"})
    assert res.status_code == 502
    assert res.json() == {"detail": "Google geocode REQUEST_DENIED: The provided API key is invalid."}


def test_search_httpx_error_still_propagates_as_500(monkeypatch):
    # httpx errors are NOT GeocodeError -> not remapped; FastAPI -> 500.
    # Pins that the mapping is SCOPED to GeocodeError only.
    import main
    c = TestClient(main.app, raise_server_exceptions=False)
    monkeypatch.setattr(main.app.state.container.geocoding_service, "search",
                        _raise(httpx.HTTPStatusError("boom", request=None, response=None)))
    res = c.get("/api/geocode/search", params={"q": "x"})
    assert res.status_code == 500


def test_reverse_swallows_geocode_error_into_offline_200(monkeypatch, client):
    import main
    import services.geo_offline as geo_offline
    monkeypatch.setattr(main.app.state.container.geocoding_service, "reverse",
                        _raise(GeocodeError(502, "x", "upstream boom")))
    monkeypatch.setattr(geo_offline, "resolve",
                        lambda _lat, _lng: ("jp", "Asia/Tokyo", "Tokyo", "Tokyo"))
    res = client.get("/api/geocode/reverse", params={"lat": 35.6586, "lng": 139.7454})
    assert res.status_code == 200
    body = res.json()
    assert body["country_code"] == "jp"
    assert "Tokyo" in body["display_name"]
