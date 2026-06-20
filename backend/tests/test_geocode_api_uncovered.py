"""Characterization tests for the two previously-uncovered geocode endpoints
(/real-location, /route-optimize) and the reverse offline-swallow of an
httpx.HTTPStatusError. Pins CURRENT behavior before the GeocodeError migration.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


class _RLResponse:
    def __init__(self, *, json_data=None, raise_exc=None):
        self._json = json_data
        self._raise_exc = raise_exc

    def json(self):
        return self._json

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc


class _RLClient:
    """Async ctx-manager whose .get() returns canned responses in call order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        self.urls.append(url)
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _patch_rl(monkeypatch, responses):
    import api.geocode as geo_api

    def _factory(*args, **kwargs):
        return _RLClient(responses)

    monkeypatch.setattr(geo_api.httpx, "AsyncClient", _factory)


def test_real_location_happy_first_provider(monkeypatch, client):
    _patch_rl(monkeypatch, [_RLResponse(json_data={
        "success": True, "latitude": 25.04, "longitude": 121.56,
        "city": "Taipei", "country": "Taiwan"})])
    res = client.get("/api/geocode/real-location")
    assert res.status_code == 200
    assert res.json() == {"lat": 25.04, "lng": 121.56, "city": "Taipei", "country": "Taiwan"}


def test_real_location_first_provider_403_continues_to_second(monkeypatch, client):
    _patch_rl(monkeypatch, [
        httpx.HTTPStatusError("403", request=None, response=None),
        _RLResponse(json_data={"status": "success", "lat": 35.68, "lon": 139.76,
                               "city": "Tokyo", "country": "Japan"})])
    res = client.get("/api/geocode/real-location")
    assert res.status_code == 200
    assert res.json() == {"lat": 35.68, "lng": 139.76, "city": "Tokyo", "country": "Japan"}


def test_real_location_no_coords_continues_to_next(monkeypatch, client):
    _patch_rl(monkeypatch, [
        _RLResponse(json_data={"success": False}),
        _RLResponse(json_data={"status": "fail"}),
        _RLResponse(json_data={"latitude": 1.5, "longitude": 2.5,
                               "city": "X", "country_name": "Country X"})])
    res = client.get("/api/geocode/real-location")
    assert res.status_code == 200
    assert res.json() == {"lat": 1.5, "lng": 2.5, "city": "X", "country": "Country X"}


def test_real_location_all_providers_fail_raises_502(monkeypatch, client):
    _patch_rl(monkeypatch, [
        httpx.HTTPStatusError("a", request=None, response=None),
        httpx.HTTPStatusError("b", request=None, response=None),
        httpx.HTTPStatusError("c", request=None, response=None)])
    res = client.get("/api/geocode/real-location")
    assert res.status_code == 502
    assert "All IP geolocation providers failed" in res.json()["detail"]


def _wps(n):
    return [{"lat": 25.0 + i * 0.001, "lng": 121.5 + i * 0.001} for i in range(n)]


def test_route_optimize_under_two_waypoints_raises_400(client):
    res = client.post("/api/geocode/route-optimize", json={"waypoints": _wps(1)})
    assert res.status_code == 400
    assert res.json()["detail"] == "need >=2 waypoints"


def test_route_optimize_happy_used_estimate_false(monkeypatch, client):
    import api.geocode as geo_api

    async def fake_osrm(coords, profile="foot"):
        n = len(coords)
        return [[0.0 if i == j else 100.0 for j in range(n)] for i in range(n)]

    monkeypatch.setattr(geo_api, "osrm_table", fake_osrm)
    res = client.post("/api/geocode/route-optimize",
                      json={"waypoints": _wps(3), "engine": "osrm"})
    assert res.status_code == 200
    body = res.json()
    assert body["used_estimate"] is False
    assert len(body["waypoints"]) == 3
    assert body["total_duration_s"] >= 0.0
    assert body["total_distance_m"] >= 0.0


def test_route_optimize_happy_used_estimate_true_haversine_fallback(monkeypatch, client):
    import api.geocode as geo_api

    async def fake_none(coords, profile="foot"):
        return None

    monkeypatch.setattr(geo_api, "osrm_table", fake_none)
    monkeypatch.setattr(geo_api, "valhalla_matrix", fake_none)
    res = client.post("/api/geocode/route-optimize",
                      json={"waypoints": _wps(3), "engine": "osrm"})
    assert res.status_code == 200
    body = res.json()
    assert body["used_estimate"] is True
    assert len(body["waypoints"]) == 3
