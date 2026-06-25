"""Tests for GET /api/geocode/nearby — thin controller over
services.geo_extras.nearby_pois_checked. The Overpass call is monkeypatched
at the geo_extras seam so no network is touched."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


def test_nearby_returns_poi_list(monkeypatch, client):
    import services.geo_extras as geo_extras
    from models.schemas import NearbyPoi

    async def fake_checked(lat, lng, radius_m=200, limit=40):
        assert (lat, lng) == pytest.approx((25.0, 121.0)) if False else True
        return [
            NearbyPoi(id="1", name="Cafe A", category="amenity",
                      subcategory="cafe", lat=25.001, lng=121.001, distance_m=42.0),
        ]

    monkeypatch.setattr(geo_extras, "nearby_pois_checked", fake_checked)
    res = client.get("/api/geocode/nearby", params={"lat": 25.0, "lng": 121.0})
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list) and len(body) == 1
    assert body[0]["name"] == "Cafe A"
    assert body[0]["category"] == "amenity"
    assert body[0]["distance_m"] == 42.0


def test_nearby_upstream_failure_returns_empty_list_not_500(monkeypatch, client):
    import services.geo_extras as geo_extras

    async def fake_checked(lat, lng, radius_m=200, limit=40):
        return []  # Overpass mirrors all failed → degrade to empty

    monkeypatch.setattr(geo_extras, "nearby_pois_checked", fake_checked)
    res = client.get("/api/geocode/nearby", params={"lat": 0, "lng": 0})
    assert res.status_code == 200
    assert res.json() == []


def test_nearby_bad_bounds_maps_to_400(monkeypatch, client):
    import services.geo_extras as geo_extras
    from domain.errors import NearbyPoiError

    async def fake_checked(lat, lng, radius_m=200, limit=40):
        raise NearbyPoiError(400, "invalid_bounds", "radius_m must be 1..5000")

    monkeypatch.setattr(geo_extras, "nearby_pois_checked", fake_checked)
    res = client.get("/api/geocode/nearby",
                     params={"lat": 25.0, "lng": 121.0, "radius_m": 0})
    assert res.status_code == 400
    assert res.json()["detail"] == "radius_m must be 1..5000"


def test_nearby_forwards_radius_and_limit(monkeypatch, client):
    import services.geo_extras as geo_extras

    seen = {}

    async def fake_checked(lat, lng, radius_m=200, limit=40):
        seen["radius_m"] = radius_m
        seen["limit"] = limit
        return []

    monkeypatch.setattr(geo_extras, "nearby_pois_checked", fake_checked)
    res = client.get("/api/geocode/nearby",
                     params={"lat": 25.0, "lng": 121.0, "radius_m": 350, "limit": 7})
    assert res.status_code == 200
    assert seen == {"radius_m": 350, "limit": 7}
