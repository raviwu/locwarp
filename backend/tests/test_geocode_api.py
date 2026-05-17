"""Tests for /api/geocode/reverse fallback to offline DB when Nominatim fails."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


def test_reverse_falls_back_to_offline_when_nominatim_raises(monkeypatch, client):
    """When the upstream Nominatim call throws, the handler must compose
    a GeocodingResult from the offline DB instead of returning HTTP 500.
    """
    import api.geocode as geo_api
    import services.geo_offline as geo_offline

    async def boom(_lat, _lng):
        raise RuntimeError("simulated Nominatim outage")

    monkeypatch.setattr(geo_api.geocoding_service, "reverse", boom)
    # Stub the offline DB so the test does not depend on the
    # timezonefinder/numpy bundle being installed in the test env.
    monkeypatch.setattr(
        geo_offline, "resolve", lambda _lat, _lng: ("jp", "Asia/Tokyo", "Tokyo", "Tokyo")
    )

    # Tokyo Tower coordinates — the offline DB has Japan / Tokyo data.
    res = client.get("/api/geocode/reverse", params={"lat": 35.6586, "lng": 139.7454})
    assert res.status_code == 200
    body = res.json()
    assert body is not None
    assert body["country_code"] == "jp"
    assert "Tokyo" in body["display_name"]
    assert body["short_name"]  # non-empty
    assert body["lat"] == pytest.approx(35.6586)
    assert body["lng"] == pytest.approx(139.7454)


def test_reverse_returns_none_when_nominatim_raises_and_offline_empty(monkeypatch, client):
    """If both Nominatim and the offline DB have nothing, the handler
    returns ``null`` (HTTP 200) rather than raising — the frontend
    already handles the null path with the "no address found" message.
    """
    import api.geocode as geo_api
    import services.geo_offline as geo_offline

    async def boom(_lat, _lng):
        raise RuntimeError("simulated Nominatim outage")

    monkeypatch.setattr(geo_api.geocoding_service, "reverse", boom)
    monkeypatch.setattr(geo_offline, "resolve", lambda _lat, _lng: ("", "", "", ""))

    res = client.get("/api/geocode/reverse", params={"lat": 0, "lng": 0})
    assert res.status_code == 200
    assert res.json() is None


def test_reverse_returns_nominatim_result_when_nominatim_succeeds(monkeypatch, client):
    """Happy path: Nominatim returns a result, the handler returns it
    unchanged. (Regression guard against the fallback short-circuiting
    on a successful call.)
    """
    import api.geocode as geo_api
    from models.schemas import GeocodingResult

    async def ok(_lat, _lng):
        return GeocodingResult(
            display_name="Real street, Real district, Real country",
            lat=35.6586,
            lng=139.7454,
            country_code="jp",
            short_name="Real POI",
        )

    monkeypatch.setattr(geo_api.geocoding_service, "reverse", ok)

    res = client.get("/api/geocode/reverse", params={"lat": 35.6586, "lng": 139.7454})
    assert res.status_code == 200
    body = res.json()
    assert body["display_name"] == "Real street, Real district, Real country"
    assert body["short_name"] == "Real POI"
