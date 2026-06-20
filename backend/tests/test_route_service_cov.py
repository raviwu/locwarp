"""Characterization tests for services.route_service.

These freeze the ACTUAL current behavior of the multi-engine route
planner: pure helpers (haversine, polyline6 decode, straight-line
fallback, engine normalisation) and the async engine parsers + fallback
chain. httpx is mocked everywhere — no real network is touched.
"""

from __future__ import annotations

import math

import httpx
import pytest

import config
from services import route_service as rs
from services.route_service import (
    RouteService,
    _decode_polyline6,
    _haversine_m,
    _normalise_engine,
    _straight_line_fallback,
)


# ----------------------------------------------------------------------
# httpx mock plumbing
# ----------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, json_data, raise_exc=None):
        self._json = json_data
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._json


class _FakeClient:
    """Records the last URL/body and returns a canned response (or raises).

    Supports `async with httpx.AsyncClient(...) as client` and
    `await client.get(url)` / `await client.post(url, json=...)`.
    """

    last = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        _FakeClient.last = {"method": "GET", "url": url}
        return _resolve(url)

    async def post(self, url, json=None):
        _FakeClient.last = {"method": "POST", "url": url, "json": json}
        return _resolve(url)


# Per-test programmable behavior. Tests set `_BEHAVIOR` to either a
# _FakeResponse, an Exception (to raise on get/post), or a callable(url).
_BEHAVIOR = None


def _resolve(url):
    behavior = _BEHAVIOR
    if callable(behavior) and not isinstance(behavior, BaseException):
        behavior = behavior(url)
    if isinstance(behavior, BaseException):
        raise behavior
    return behavior


@pytest.fixture
def patch_client(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    yield


def _set(behavior):
    global _BEHAVIOR
    _BEHAVIOR = behavior


# ----------------------------------------------------------------------
# _haversine_m
# ----------------------------------------------------------------------

def test_haversine_zero_distance():
    assert _haversine_m(40.0, -74.0, 40.0, -74.0) == 0.0


def test_haversine_known_distance():
    # ~1 degree of latitude ~= 111.19 km at the equator.
    d = _haversine_m(0.0, 0.0, 1.0, 0.0)
    assert abs(d - 111194.9) < 5.0


def test_haversine_symmetric():
    a = _haversine_m(48.8566, 2.3522, 51.5074, -0.1278)
    b = _haversine_m(51.5074, -0.1278, 48.8566, 2.3522)
    assert a == pytest.approx(b)


# ----------------------------------------------------------------------
# _decode_polyline6
# ----------------------------------------------------------------------

def test_decode_polyline6_empty():
    assert _decode_polyline6("") == []


def test_decode_polyline6_roundtrip_known():
    # Encoded with precision 6. Decode a hand-known sample produced by
    # the standard polyline6 algorithm for points
    # (38.5, -120.2), (40.7, -120.95), (43.252, -126.453).
    # We instead verify decode is self-consistent by encoding here.
    pts = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    encoded = _encode_polyline6(pts)
    decoded = _decode_polyline6(encoded)
    assert len(decoded) == 3
    for (elat, elng), (dlat, dlng) in zip(pts, decoded):
        assert dlat == pytest.approx(elat, abs=1e-6)
        assert dlng == pytest.approx(elng, abs=1e-6)


def _encode_polyline6(coords):
    """Reference polyline6 encoder (precision 6) for test fixtures."""
    def _enc(value):
        value = int(round(value * 1e6))
        value <<= 1
        if value < 0:
            value = ~value
        chunks = []
        while value >= 0x20:
            chunks.append(chr((0x20 | (value & 0x1f)) + 63))
            value >>= 5
        chunks.append(chr(value + 63))
        return "".join(chunks)

    out = []
    prev_lat = 0
    prev_lng = 0
    for lat, lng in coords:
        ilat = int(round(lat * 1e6))
        ilng = int(round(lng * 1e6))
        out.append(_enc((ilat - prev_lat) / 1e6))
        out.append(_enc((ilng - prev_lng) / 1e6))
        prev_lat = ilat
        prev_lng = ilng
    return "".join(out)


# ----------------------------------------------------------------------
# _straight_line_fallback
# ----------------------------------------------------------------------

def test_straight_line_fallback_shape_and_flag():
    wps = [(0.0, 0.0), (0.0, 1.0)]
    out = _straight_line_fallback(wps)
    assert out["fallback"] is True
    assert out["coords"][0] == [0.0, 0.0]
    # Last densified point lands on the destination.
    assert out["coords"][-1] == pytest.approx([0.0, 1.0])
    # distance == haversine of the single segment
    seg = _haversine_m(0.0, 0.0, 0.0, 1.0)
    assert out["distance"] == pytest.approx(seg)
    # default walking speed 1.4 m/s
    assert out["duration"] == pytest.approx(seg / 1.4)
    assert out["leg_durations"] == pytest.approx([seg / 1.4])


def test_straight_line_fallback_densifies_at_25m_steps():
    # ~100m segment → steps = int(100/25) = 4 → 5 coords (incl. start).
    wps = [(0.0, 0.0), (0.0, 0.0009)]  # ~100.2m east
    out = _straight_line_fallback(wps)
    seg = _haversine_m(0.0, 0.0, 0.0, 0.0009)
    expected_steps = max(1, int(seg / 25.0))
    assert len(out["coords"]) == expected_steps + 1


def test_straight_line_fallback_short_segment_min_one_step():
    # Sub-25m segment still yields at least one step (so 2 coords).
    wps = [(0.0, 0.0), (0.0, 0.0001)]  # ~11m
    out = _straight_line_fallback(wps)
    assert len(out["coords"]) == 2


def test_straight_line_fallback_custom_speed():
    wps = [(0.0, 0.0), (0.0, 1.0)]
    out = _straight_line_fallback(wps, walking_speed_mps=2.0)
    seg = _haversine_m(0.0, 0.0, 0.0, 1.0)
    assert out["duration"] == pytest.approx(seg / 2.0)


def test_straight_line_fallback_multi_waypoint_legs():
    wps = [(0.0, 0.0), (0.0, 0.5), (0.0, 1.0)]
    out = _straight_line_fallback(wps)
    assert len(out["leg_durations"]) == 2


# ----------------------------------------------------------------------
# _normalise_engine
# ----------------------------------------------------------------------

def test_normalise_engine_none_returns_default():
    assert _normalise_engine(None) == config.DEFAULT_ROUTE_ENGINE


def test_normalise_engine_unknown_returns_default():
    assert _normalise_engine("teleporter") == config.DEFAULT_ROUTE_ENGINE


def test_normalise_engine_valid_passthrough():
    assert _normalise_engine(config.ROUTE_ENGINE_VALHALLA) == config.ROUTE_ENGINE_VALHALLA
    assert _normalise_engine(config.ROUTE_ENGINE_BROUTER) == config.ROUTE_ENGINE_BROUTER


def test_normalise_engine_empty_string_returns_default():
    assert _normalise_engine("") == config.DEFAULT_ROUTE_ENGINE


# ----------------------------------------------------------------------
# get_route / get_multi_route force_straight + waypoint normalisation
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_route_force_straight_skips_engine():
    svc = RouteService()
    out = await svc.get_route(0.0, 0.0, 0.0, 1.0, force_straight=True)
    assert out["fallback"] is True


@pytest.mark.asyncio
async def test_get_multi_route_force_straight():
    svc = RouteService()
    out = await svc.get_multi_route([(0.0, 0.0), (0.0, 1.0)], force_straight=True)
    assert out["fallback"] is True


@pytest.mark.asyncio
async def test_get_multi_route_requires_two_waypoints():
    svc = RouteService()
    with pytest.raises(ValueError, match="At least two waypoints"):
        await svc.get_multi_route([(0.0, 0.0)])


@pytest.mark.asyncio
async def test_get_multi_route_accepts_dicts_lists_tuples(patch_client):
    # Mix dict, list, tuple. OSRM (default engine) parse path.
    _set(_FakeResponse(_OSRM_OK))
    svc = RouteService()
    out = await svc.get_multi_route(
        [{"lat": 1.0, "lng": 2.0}, [3.0, 4.0], (5.0, 6.0)],
        engine=config.ROUTE_ENGINE_OSRM,
    )
    assert "coords" in out and out.get("fallback") is None
    # Three waypoints → coords_str has three lon,lat pairs in the URL.
    assert _FakeClient.last["url"].count(";") == 2


# ----------------------------------------------------------------------
# OSRM parse
# ----------------------------------------------------------------------

_OSRM_OK = {
    "code": "Ok",
    "routes": [
        {
            "geometry": {"coordinates": [[2.0, 1.0], [4.0, 3.0]]},  # [lon, lat]
            "duration": 123.0,
            "distance": 456.0,
            "legs": [{"duration": 100.0}, {"duration": 23.0}],
        }
    ],
}


@pytest.mark.asyncio
async def test_osrm_parse_demo(patch_client):
    _set(_FakeResponse(_OSRM_OK))
    svc = RouteService()
    out = await svc._fetch_osrm([(1.0, 2.0), (3.0, 4.0)], "foot", config.ROUTE_ENGINE_OSRM)
    # coords swapped from [lon,lat] to [lat,lng]
    assert out["coords"] == [[1.0, 2.0], [3.0, 4.0]]
    assert out["duration"] == 123.0
    assert out["distance"] == 456.0
    assert out["leg_durations"] == [100.0, 23.0]
    # demo base + car/foot profile, lon,lat ordering in url
    assert _FakeClient.last["url"].startswith(config.OSRM_BASE_URL)
    assert "/foot/" in _FakeClient.last["url"]
    assert "2.0,1.0;4.0,3.0" in _FakeClient.last["url"]


@pytest.mark.asyncio
async def test_osrm_demo_profile_mapping_driving_to_car(patch_client):
    _set(_FakeResponse(_OSRM_OK))
    svc = RouteService()
    await svc._fetch_osrm([(1.0, 2.0), (3.0, 4.0)], "driving", config.ROUTE_ENGINE_OSRM)
    assert "/car/" in _FakeClient.last["url"]


@pytest.mark.asyncio
async def test_osrm_demo_unknown_profile_passthrough(patch_client):
    _set(_FakeResponse(_OSRM_OK))
    svc = RouteService()
    await svc._fetch_osrm([(1.0, 2.0), (3.0, 4.0)], "hovercraft", config.ROUTE_ENGINE_OSRM)
    # Unknown profile passes through verbatim into the URL.
    assert "/hovercraft/" in _FakeClient.last["url"]


@pytest.mark.asyncio
async def test_osrm_fossgis_profile_and_base(patch_client):
    _set(_FakeResponse(_OSRM_OK))
    svc = RouteService()
    await svc._fetch_osrm([(1.0, 2.0), (3.0, 4.0)], "driving", config.ROUTE_ENGINE_OSRM_FOSSGIS)
    url = _FakeClient.last["url"]
    assert url.startswith(f"{config.OSRM_FOSSGIS_BASE_URL}/routed-car")
    assert "/driving/" in url


@pytest.mark.asyncio
async def test_osrm_fossgis_unknown_profile_defaults_foot(patch_client):
    _set(_FakeResponse(_OSRM_OK))
    svc = RouteService()
    await svc._fetch_osrm([(1.0, 2.0), (3.0, 4.0)], "spaceship", config.ROUTE_ENGINE_OSRM_FOSSGIS)
    url = _FakeClient.last["url"]
    assert "/routed-foot/" in url
    assert "/foot/" in url


@pytest.mark.asyncio
async def test_osrm_code_not_ok_raises_runtime(patch_client):
    _set(_FakeResponse({"code": "NoRoute", "message": "no path"}))
    svc = RouteService()
    with pytest.raises(RuntimeError, match="OSRM error: no path"):
        await svc._fetch_osrm([(1.0, 2.0), (3.0, 4.0)], "foot", config.ROUTE_ENGINE_OSRM)


@pytest.mark.asyncio
async def test_osrm_code_not_ok_default_message(patch_client):
    _set(_FakeResponse({"code": "Error"}))
    svc = RouteService()
    with pytest.raises(RuntimeError, match="Unknown OSRM error"):
        await svc._fetch_osrm([(1.0, 2.0), (3.0, 4.0)], "foot", config.ROUTE_ENGINE_OSRM)


# ----------------------------------------------------------------------
# Valhalla parse
# ----------------------------------------------------------------------

def _valhalla_resp(legs, trip_summary=None, status=0):
    trip = {"status": status, "legs": legs}
    if trip_summary is not None:
        trip["summary"] = trip_summary
    return {"trip": trip}


@pytest.mark.asyncio
async def test_valhalla_parse_single_leg(patch_client):
    pts = [(38.5, -120.2), (40.7, -120.95)]
    shape = _encode_polyline6(pts)
    resp = _valhalla_resp(
        legs=[{"shape": shape, "summary": {"time": 60.0, "length": 2.0}}],
    )
    _set(_FakeResponse(resp))
    svc = RouteService()
    out = await svc._fetch_valhalla([(38.5, -120.2), (40.7, -120.95)], "walking")
    assert len(out["coords"]) == 2
    assert out["duration"] == 60.0
    assert out["distance"] == pytest.approx(2000.0)  # 2 km → m
    assert out["leg_durations"] == [60.0]
    # walking → pedestrian costing in body
    assert _FakeClient.last["json"]["costing"] == "pedestrian"


@pytest.mark.asyncio
async def test_valhalla_two_legs_drops_seam_point(patch_client):
    leg1 = [(38.5, -120.2), (40.7, -120.95)]
    leg2 = [(40.7, -120.95), (43.252, -126.453)]
    resp = _valhalla_resp(legs=[
        {"shape": _encode_polyline6(leg1), "summary": {"time": 10.0, "length": 1.0}},
        {"shape": _encode_polyline6(leg2), "summary": {"time": 20.0, "length": 2.0}},
    ])
    _set(_FakeResponse(resp))
    svc = RouteService()
    out = await svc._fetch_valhalla(leg1[:1] + [leg2[1]], "driving")
    # 2 + (2-1) seam-dropped = 3 coords
    assert len(out["coords"]) == 3
    assert out["leg_durations"] == [10.0, 20.0]
    assert out["duration"] == 30.0
    assert _FakeClient.last["json"]["costing"] == "auto"


@pytest.mark.asyncio
async def test_valhalla_trip_summary_overrides(patch_client):
    pts = [(38.5, -120.2), (40.7, -120.95)]
    resp = _valhalla_resp(
        legs=[{"shape": _encode_polyline6(pts), "summary": {"time": 5.0, "length": 1.0}}],
        trip_summary={"time": 999.0, "length": 50.0},
    )
    _set(_FakeResponse(resp))
    svc = RouteService()
    out = await svc._fetch_valhalla(pts, "foot")
    assert out["duration"] == 999.0
    assert out["distance"] == pytest.approx(50000.0)


@pytest.mark.asyncio
async def test_valhalla_no_trip_raises(patch_client):
    _set(_FakeResponse({}))
    svc = RouteService()
    with pytest.raises(RuntimeError, match="no trip"):
        await svc._fetch_valhalla([(1.0, 2.0), (3.0, 4.0)], "foot")


@pytest.mark.asyncio
async def test_valhalla_bad_status_raises(patch_client):
    _set(_FakeResponse({"trip": {"status": 1, "status_message": "broken", "legs": [{}]}}))
    svc = RouteService()
    with pytest.raises(RuntimeError, match="Valhalla error: broken"):
        await svc._fetch_valhalla([(1.0, 2.0), (3.0, 4.0)], "foot")


@pytest.mark.asyncio
async def test_valhalla_no_legs_raises(patch_client):
    _set(_FakeResponse({"trip": {"status": 0, "legs": []}}))
    svc = RouteService()
    with pytest.raises(RuntimeError, match="no legs"):
        await svc._fetch_valhalla([(1.0, 2.0), (3.0, 4.0)], "foot")


@pytest.mark.asyncio
async def test_valhalla_legs_without_shape_empty_geometry_raises(patch_client):
    # A leg present but with no shape → decoded geometry empty.
    _set(_FakeResponse({"trip": {"status": 0, "legs": [{"summary": {"time": 1.0}}]}}))
    svc = RouteService()
    with pytest.raises(RuntimeError, match="decoded geometry was empty"):
        await svc._fetch_valhalla([(1.0, 2.0), (3.0, 4.0)], "foot")


@pytest.mark.asyncio
async def test_valhalla_status_none_allowed(patch_client):
    # status None is whitelisted (not an error).
    pts = [(38.5, -120.2), (40.7, -120.95)]
    resp = {"trip": {"legs": [{"shape": _encode_polyline6(pts), "summary": {"time": 1.0, "length": 0.5}}]}}
    _set(_FakeResponse(resp))
    svc = RouteService()
    out = await svc._fetch_valhalla(pts, "bike")
    assert out["duration"] == 1.0
    assert _FakeClient.last["json"]["costing"] == "bicycle"


# ----------------------------------------------------------------------
# BRouter parse
# ----------------------------------------------------------------------

def _brouter_resp(coordinates, props):
    return {
        "features": [
            {"geometry": {"coordinates": coordinates}, "properties": props}
        ]
    }


@pytest.mark.asyncio
async def test_brouter_parse(patch_client):
    resp = _brouter_resp(
        coordinates=[[2.0, 1.0, 10.0], [4.0, 3.0, 20.0]],  # [lon, lat, ele]
        props={"track-length": "500", "total-time": "300"},
    )
    _set(_FakeResponse(resp))
    svc = RouteService()
    out = await svc._fetch_brouter([(1.0, 2.0), (3.0, 4.0)], "bike")
    assert out["coords"] == [[1.0, 2.0], [3.0, 4.0]]  # swapped, elevation dropped
    assert out["distance"] == 500.0
    assert out["duration"] == 300.0
    assert out["leg_durations"] == [300.0]
    # bike → trekking profile in URL
    assert "profile=trekking" in _FakeClient.last["url"]
    assert _FakeClient.last["url"].startswith(config.BROUTER_BASE_URL)


@pytest.mark.asyncio
async def test_brouter_no_features_raises(patch_client):
    _set(_FakeResponse({"features": []}))
    svc = RouteService()
    with pytest.raises(RuntimeError, match="no features"):
        await svc._fetch_brouter([(1.0, 2.0), (3.0, 4.0)], "foot")


@pytest.mark.asyncio
async def test_brouter_empty_geometry_raises(patch_client):
    _set(_FakeResponse(_brouter_resp(coordinates=[], props={})))
    svc = RouteService()
    with pytest.raises(RuntimeError, match="empty geometry"):
        await svc._fetch_brouter([(1.0, 2.0), (3.0, 4.0)], "foot")


@pytest.mark.asyncio
async def test_brouter_bad_props_default_to_zero(patch_client):
    resp = _brouter_resp(
        coordinates=[[2.0, 1.0, 0.0]],
        props={"track-length": "notanum", "total-time": None},
    )
    _set(_FakeResponse(resp))
    svc = RouteService()
    out = await svc._fetch_brouter([(1.0, 2.0)], "foot")
    assert out["distance"] == 0.0
    assert out["duration"] == 0.0


@pytest.mark.asyncio
async def test_brouter_nonnumeric_total_time_excepted(patch_client):
    # total-time a non-numeric truthy string → float() raises ValueError
    # → caught → 0.0 (covers the total-time except clause).
    resp = _brouter_resp(
        coordinates=[[2.0, 1.0, 0.0]],
        props={"track-length": "100", "total-time": "abc"},
    )
    _set(_FakeResponse(resp))
    svc = RouteService()
    out = await svc._fetch_brouter([(1.0, 2.0)], "foot")
    assert out["distance"] == 100.0
    assert out["duration"] == 0.0


@pytest.mark.asyncio
async def test_brouter_default_profile_for_unknown(patch_client):
    _set(_FakeResponse(_brouter_resp([[2.0, 1.0, 0.0]], {})))
    svc = RouteService()
    await svc._fetch_brouter([(1.0, 2.0)], "submarine")
    assert "profile=shortest" in _FakeClient.last["url"]


# ----------------------------------------------------------------------
# _fetch_route dispatch + fallback chain
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_route_dispatches_valhalla(patch_client):
    pts = [(38.5, -120.2), (40.7, -120.95)]
    resp = _valhalla_resp(legs=[{"shape": _encode_polyline6(pts), "summary": {"time": 1.0, "length": 0.1}}])
    _set(_FakeResponse(resp))
    svc = RouteService()
    out = await svc._fetch_route(pts, "foot", config.ROUTE_ENGINE_VALHALLA)
    assert out.get("fallback") is None
    assert _FakeClient.last["method"] == "POST"


@pytest.mark.asyncio
async def test_fetch_route_dispatches_brouter(patch_client):
    _set(_FakeResponse(_brouter_resp([[2.0, 1.0, 0.0], [4.0, 3.0, 0.0]], {"track-length": "1", "total-time": "1"})))
    svc = RouteService()
    out = await svc._fetch_route([(1.0, 2.0), (3.0, 4.0)], "foot", config.ROUTE_ENGINE_BROUTER)
    assert out.get("fallback") is None
    assert "/brouter?" in _FakeClient.last["url"]


@pytest.mark.asyncio
async def test_fetch_route_falls_back_on_http_error(patch_client):
    # raise_for_status raises an HTTPStatusError → caught → straight line.
    err = httpx.HTTPStatusError("502", request=None, response=None)
    _set(_FakeResponse(None, raise_exc=err))
    svc = RouteService()
    out = await svc._fetch_route([(0.0, 0.0), (0.0, 1.0)], "foot", config.ROUTE_ENGINE_OSRM)
    assert out["fallback"] is True
    seg = _haversine_m(0.0, 0.0, 0.0, 1.0)
    assert out["distance"] == pytest.approx(seg)


@pytest.mark.asyncio
async def test_fetch_route_falls_back_on_timeout(patch_client):
    _set(httpx.TimeoutException("slow"))
    svc = RouteService()
    out = await svc._fetch_route([(0.0, 0.0), (0.0, 1.0)], "foot", config.ROUTE_ENGINE_OSRM)
    assert out["fallback"] is True


@pytest.mark.asyncio
async def test_fetch_route_falls_back_on_runtime_error(patch_client):
    # OSRM code != Ok raises RuntimeError inside _fetch_osrm → caught.
    _set(_FakeResponse({"code": "NoRoute", "message": "x"}))
    svc = RouteService()
    out = await svc._fetch_route([(0.0, 0.0), (0.0, 1.0)], "foot", config.ROUTE_ENGINE_OSRM)
    assert out["fallback"] is True


@pytest.mark.asyncio
async def test_fetch_route_does_not_catch_value_error(patch_client):
    # A non-whitelisted exception (ValueError) propagates out.
    def boom(url):
        raise ValueError("unexpected")
    _set(boom)
    svc = RouteService()
    with pytest.raises(ValueError):
        await svc._fetch_route([(0.0, 0.0), (0.0, 1.0)], "foot", config.ROUTE_ENGINE_OSRM)


@pytest.mark.asyncio
async def test_get_route_end_to_end_osrm(patch_client):
    _set(_FakeResponse(_OSRM_OK))
    svc = RouteService()
    out = await svc.get_route(1.0, 2.0, 3.0, 4.0, profile="foot", engine=config.ROUTE_ENGINE_OSRM)
    assert out["coords"] == [[1.0, 2.0], [3.0, 4.0]]
    assert out.get("fallback") is None


@pytest.mark.asyncio
async def test_get_route_unknown_engine_normalised_to_default(patch_client):
    _set(_FakeResponse(_OSRM_OK))
    svc = RouteService()
    # engine="bogus" → normalised to default (osrm) → GET to OSRM base.
    await svc.get_route(1.0, 2.0, 3.0, 4.0, engine="bogus")
    assert _FakeClient.last["method"] == "GET"
    assert _FakeClient.last["url"].startswith(config.OSRM_BASE_URL)
