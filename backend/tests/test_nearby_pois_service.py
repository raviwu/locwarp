"""Tests for the nearby-POI service wrapper (geo_extras.nearby_pois_checked).

The wrapper validates bounds (raising a domain error) and otherwise delegates
to the existing nearby_pois, which returns [] on any upstream failure. Pure /
offline — the Overpass call is monkeypatched so no network is touched.
"""
from __future__ import annotations

import pytest

from domain.errors import NearbyPoiError
from models.schemas import NearbyPoi
import services.geo_extras as geo_extras


pytestmark = pytest.mark.asyncio


async def test_returns_pois_from_underlying_nearby_pois(monkeypatch):
    sample = [
        NearbyPoi(id="1", name="Cafe A", category="amenity", subcategory="cafe",
                  lat=25.0, lng=121.0, distance_m=12.5),
    ]

    async def fake_nearby(lat, lng, radius_m=200, limit=40):
        assert (lat, lng, radius_m, limit) == (25.0, 121.0, 300, 10)
        return sample

    monkeypatch.setattr(geo_extras, "nearby_pois", fake_nearby)
    out = await geo_extras.nearby_pois_checked(25.0, 121.0, radius_m=300, limit=10)
    assert out == sample


async def test_upstream_failure_yields_empty_list_not_raise(monkeypatch):
    async def fake_nearby(lat, lng, radius_m=200, limit=40):
        return []  # _overpass_post returned None upstream

    monkeypatch.setattr(geo_extras, "nearby_pois", fake_nearby)
    out = await geo_extras.nearby_pois_checked(0.0, 0.0)
    assert out == []


async def test_radius_zero_raises_domain_error():
    with pytest.raises(NearbyPoiError) as ei:
        await geo_extras.nearby_pois_checked(25.0, 121.0, radius_m=0)
    assert ei.value.status_code == 400
    assert ei.value.code == "invalid_bounds"


async def test_radius_too_large_raises_domain_error():
    with pytest.raises(NearbyPoiError) as ei:
        await geo_extras.nearby_pois_checked(25.0, 121.0, radius_m=5001)
    assert ei.value.status_code == 400


async def test_limit_zero_raises_domain_error():
    with pytest.raises(NearbyPoiError) as ei:
        await geo_extras.nearby_pois_checked(25.0, 121.0, limit=0)
    assert ei.value.status_code == 400


async def test_limit_too_large_raises_domain_error():
    with pytest.raises(NearbyPoiError) as ei:
        await geo_extras.nearby_pois_checked(25.0, 121.0, limit=201)
    assert ei.value.status_code == 400
