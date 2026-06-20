"""Characterization tests for services.geocoding.

Freezes the ACTUAL current behavior of GeocodingService (forward search via
Nominatim/Google, reverse geocoding) and the _pick_short_name helper.

All network access is mocked by replacing httpx.AsyncClient inside the
geocoding module with a fake async-context-manager client. No real HTTP.

NOTE on the "known smell": the service raises fastapi.HTTPException from a
non-HTTP service layer (e.g. missing google_key -> 400, Google upstream
errors -> 502). These tests assert the ACTUAL HTTPException + status code,
not what "should" happen architecturally.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException

import services.geocoding as geocoding
from domain.errors import GeocodeError
from services.geocoding import GeocodingService, _pick_short_name


# ---------------------------------------------------------------------------
# Fake httpx client plumbing
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, *, json_data=None, status_code=200, text="", raise_exc=None):
        self._json = json_data
        self.status_code = status_code
        self.text = text
        self._raise_exc = raise_exc

    def json(self):
        return self._json

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc


class _FakeClient:
    """Async context manager that records the last GET and returns a canned response."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self._response


def _patch_client(monkeypatch, response):
    """Patch httpx.AsyncClient inside the geocoding module to yield a fake client.

    Returns a holder whose .client attribute is the constructed fake (so tests
    can inspect the recorded request).
    """
    holder = {}

    def _factory(*args, **kwargs):
        c = _FakeClient(response)
        holder["client"] = c
        return c

    monkeypatch.setattr(geocoding.httpx, "AsyncClient", _factory)
    return holder


@pytest.fixture
def svc():
    return GeocodingService()


# ---------------------------------------------------------------------------
# search() dispatcher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_google_without_key_raises_geocode_error_400(svc):
    with pytest.raises(GeocodeError) as ei:
        await svc.search("anywhere", provider="google", google_key=None)
    assert ei.value.status_code == 400
    assert ei.value.detail == "provider=google requires google_key"


@pytest.mark.asyncio
async def test_search_default_provider_uses_nominatim(monkeypatch, svc):
    resp = _FakeResponse(json_data=[])
    holder = _patch_client(monkeypatch, resp)
    out = await svc.search("Taipei")
    assert out == []
    # Hit the nominatim /search endpoint, not Google.
    assert holder["client"].calls[0]["url"].endswith("/search")


# ---------------------------------------------------------------------------
# _search_nominatim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nominatim_parses_results(monkeypatch, svc):
    resp = _FakeResponse(
        json_data=[
            {
                "display_name": "Taipei 101, Xinyi, Taipei, Taiwan",
                "lat": "25.0339",
                "lon": "121.5645",
                "type": "attraction",
                "importance": "0.85",
            }
        ]
    )
    holder = _patch_client(monkeypatch, resp)

    out = await svc.search("Taipei 101", limit=5)
    assert len(out) == 1
    r = out[0]
    assert r.display_name == "Taipei 101, Xinyi, Taipei, Taiwan"
    assert r.lat == pytest.approx(25.0339)
    assert r.lng == pytest.approx(121.5645)
    assert r.type == "attraction"
    assert r.importance == pytest.approx(0.85)
    # country_code / short_name are not populated by forward nominatim search.
    assert r.country_code == ""
    assert r.short_name == ""

    # limit is clamped to min(limit, 40) and format=json is set.
    params = holder["client"].calls[0]["params"]
    assert params["limit"] == 5
    assert params["format"] == "json"
    assert params["q"] == "Taipei 101"


@pytest.mark.asyncio
async def test_nominatim_clamps_limit_to_40(monkeypatch, svc):
    resp = _FakeResponse(json_data=[])
    holder = _patch_client(monkeypatch, resp)
    await svc.search("x", limit=999)
    assert holder["client"].calls[0]["params"]["limit"] == 40


@pytest.mark.asyncio
async def test_nominatim_skips_malformed_items(monkeypatch, svc):
    resp = _FakeResponse(
        json_data=[
            {"display_name": "good", "lat": "1.0", "lon": "2.0"},
            {"display_name": "missing lat/lon"},  # KeyError -> skipped
            {"display_name": "bad lat", "lat": "notnum", "lon": "2.0"},  # ValueError
        ]
    )
    _patch_client(monkeypatch, resp)
    out = await svc.search("mix")
    assert len(out) == 1
    assert out[0].display_name == "good"
    # defaults applied for missing optional fields
    assert out[0].type == ""
    assert out[0].importance == 0.0


@pytest.mark.asyncio
async def test_nominatim_raise_for_status_propagates(monkeypatch, svc):
    exc = httpx.HTTPStatusError("boom", request=None, response=None)
    resp = _FakeResponse(raise_exc=exc)
    _patch_client(monkeypatch, resp)
    with pytest.raises(httpx.HTTPStatusError) as ei:
        await svc.search("anything")
    # The httpx error is NOT remapped to a domain/HTTP error in the service
    # layer — it propagates verbatim (mapped at the api boundary instead).
    assert ei.value is exc
    assert str(ei.value) == "boom"


# ---------------------------------------------------------------------------
# _search_google
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_parses_results_and_slices_to_limit(monkeypatch, svc):
    resp = _FakeResponse(
        json_data={
            "status": "OK",
            "results": [
                {
                    "formatted_address": "Addr One",
                    "geometry": {"location": {"lat": 10.0, "lng": 20.0}},
                    "types": ["street_address", "premise"],
                },
                {
                    "formatted_address": "Addr Two",
                    "geometry": {"location": {"lat": 11.0, "lng": 21.0}},
                    "types": [],
                },
            ],
        }
    )
    holder = _patch_client(monkeypatch, resp)

    out = await svc.search("somewhere", limit=1, provider="google", google_key="KEY")
    # Sliced to limit=1.
    assert len(out) == 1
    r = out[0]
    assert r.display_name == "Addr One"
    assert r.lat == pytest.approx(10.0)
    assert r.lng == pytest.approx(20.0)
    assert r.type == "street_address"  # first of types
    assert r.importance == 0.0  # Google doesn't expose importance

    # Hit the google URL with address/key/language params.
    call = holder["client"].calls[0]
    assert call["url"] == geocoding._GOOGLE_GEOCODE_URL
    assert call["params"]["address"] == "somewhere"
    assert call["params"]["key"] == "KEY"
    assert call["params"]["language"] == "zh-TW"


@pytest.mark.asyncio
async def test_google_zero_results_returns_empty_list(monkeypatch, svc):
    resp = _FakeResponse(json_data={"status": "ZERO_RESULTS", "results": []})
    _patch_client(monkeypatch, resp)
    out = await svc.search("nowhere", provider="google", google_key="KEY")
    assert out == []


@pytest.mark.asyncio
async def test_google_empty_types_yields_empty_type(monkeypatch, svc):
    resp = _FakeResponse(
        json_data={
            "status": "OK",
            "results": [
                {
                    "formatted_address": "No Types",
                    "geometry": {"location": {"lat": 1.0, "lng": 2.0}},
                    "types": [],
                }
            ],
        }
    )
    _patch_client(monkeypatch, resp)
    out = await svc.search("x", provider="google", google_key="KEY")
    assert out[0].type == ""


@pytest.mark.asyncio
async def test_google_skips_malformed_result(monkeypatch, svc):
    resp = _FakeResponse(
        json_data={
            "status": "OK",
            "results": [
                {"formatted_address": "no geometry"},  # KeyError -> skipped
                {
                    "formatted_address": "ok",
                    "geometry": {"location": {"lat": 1.0, "lng": 2.0}},
                    "types": ["x"],
                },
            ],
        }
    )
    _patch_client(monkeypatch, resp)
    out = await svc.search("x", provider="google", google_key="KEY")
    assert len(out) == 1
    assert out[0].display_name == "ok"


@pytest.mark.asyncio
async def test_google_missing_results_key_returns_empty(monkeypatch, svc):
    resp = _FakeResponse(json_data={"status": "OK"})  # no "results"
    _patch_client(monkeypatch, resp)
    out = await svc.search("x", provider="google", google_key="KEY")
    assert out == []


@pytest.mark.asyncio
async def test_google_non_200_raises_geocode_error_502(monkeypatch, svc):
    resp = _FakeResponse(json_data=None, status_code=403, text="Forbidden body text")
    _patch_client(monkeypatch, resp)
    with pytest.raises(GeocodeError) as ei:
        await svc.search("x", provider="google", google_key="KEY")
    assert ei.value.status_code == 502
    assert ei.value.detail == "Google geocode HTTP 403: Forbidden body text"


@pytest.mark.asyncio
async def test_google_error_status_raises_geocode_error_502_with_error_message(monkeypatch, svc):
    resp = _FakeResponse(
        json_data={
            "status": "REQUEST_DENIED",
            "error_message": "The provided API key is invalid.",
        }
    )
    _patch_client(monkeypatch, resp)
    with pytest.raises(GeocodeError) as ei:
        await svc.search("x", provider="google", google_key="BAD")
    assert ei.value.status_code == 502
    assert ei.value.detail == "Google geocode REQUEST_DENIED: The provided API key is invalid."


@pytest.mark.asyncio
async def test_google_error_status_without_error_message_falls_back_to_status(
    monkeypatch, svc
):
    resp = _FakeResponse(json_data={"status": "OVER_QUERY_LIMIT"})
    _patch_client(monkeypatch, resp)
    with pytest.raises(GeocodeError) as ei:
        await svc.search("x", provider="google", google_key="KEY")
    assert ei.value.status_code == 502
    assert ei.value.detail == "Google geocode OVER_QUERY_LIMIT: OVER_QUERY_LIMIT"


# ---------------------------------------------------------------------------
# reverse()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reverse_parses_full_result(monkeypatch, svc):
    resp = _FakeResponse(
        json_data={
            "display_name": "Tokyo Tower, Minato, Tokyo, Japan",
            "lat": "35.6586",
            "lon": "139.7454",
            "type": "attraction",
            "importance": "0.7",
            "name": "Tokyo Tower",
            "address": {"country_code": "JP", "tourism": "Tokyo Tower"},
        }
    )
    holder = _patch_client(monkeypatch, resp)

    r = await svc.reverse(35.6586, 139.7454)
    assert r is not None
    assert r.display_name == "Tokyo Tower, Minato, Tokyo, Japan"
    assert r.lat == pytest.approx(35.6586)
    assert r.lng == pytest.approx(139.7454)
    assert r.type == "attraction"
    assert r.importance == pytest.approx(0.7)
    assert r.country_code == "jp"  # lowercased
    assert r.short_name == "Tokyo Tower"  # from top-level name

    # reverse hits /reverse with addressdetails=1
    call = holder["client"].calls[0]
    assert call["url"].endswith("/reverse")
    assert call["params"]["addressdetails"] == 1
    assert call["params"]["lat"] == 35.6586
    assert call["params"]["lon"] == 139.7454


@pytest.mark.asyncio
async def test_reverse_returns_none_on_error_field(monkeypatch, svc):
    resp = _FakeResponse(json_data={"error": "Unable to geocode"})
    _patch_client(monkeypatch, resp)
    r = await svc.reverse(0.0, 0.0)
    assert r is None


@pytest.mark.asyncio
async def test_reverse_returns_none_when_lat_missing(monkeypatch, svc):
    # No "lat"/"lon" keys -> KeyError caught -> None.
    resp = _FakeResponse(json_data={"display_name": "somewhere", "address": {}})
    _patch_client(monkeypatch, resp)
    r = await svc.reverse(1.0, 2.0)
    assert r is None


@pytest.mark.asyncio
async def test_reverse_empty_country_code_defaults_to_empty(monkeypatch, svc):
    resp = _FakeResponse(
        json_data={
            "display_name": "Mid Ocean, Nowhere",
            "lat": "1.0",
            "lon": "2.0",
            "address": {"road": "Long Road"},
        }
    )
    _patch_client(monkeypatch, resp)
    r = await svc.reverse(1.0, 2.0)
    assert r is not None
    assert r.country_code == ""
    assert r.short_name == "Long Road"  # falls through to road


@pytest.mark.asyncio
async def test_reverse_raise_for_status_propagates(monkeypatch, svc):
    exc = httpx.HTTPStatusError("boom", request=None, response=None)
    resp = _FakeResponse(raise_exc=exc)
    _patch_client(monkeypatch, resp)
    with pytest.raises(httpx.HTTPStatusError) as ei:
        await svc.reverse(1.0, 2.0)
    assert ei.value is exc
    assert str(ei.value) == "boom"


# ---------------------------------------------------------------------------
# _pick_short_name
# ---------------------------------------------------------------------------


def test_pick_short_name_prefers_top_level_name():
    assert _pick_short_name({"tourism": "POI"}, "Named Place", "a, b") == "Named Place"


def test_pick_short_name_single_char_name_is_ignored():
    # name length must be > 1; single char falls through to POI key.
    assert _pick_short_name({"tourism": "Museum"}, "X", "a, b") == "Museum"


def test_pick_short_name_poi_key_order():
    # tourism beats amenity (tourism comes earlier in poi_keys).
    addr = {"amenity": "Cafe", "tourism": "Attraction"}
    assert _pick_short_name(addr, "", "d") == "Attraction"


def test_pick_short_name_non_string_poi_value_skipped():
    # building value is non-str -> skipped; falls to road.
    addr = {"building": 123, "road": "Main St"}
    assert _pick_short_name(addr, "", "d") == "Main St"


def test_pick_short_name_falls_to_region():
    addr = {"city": "Kyoto"}
    assert _pick_short_name(addr, "", "x") == "Kyoto"


def test_pick_short_name_neighbourhood_before_city():
    addr = {"suburb": "Shibuya", "city": "Tokyo"}
    assert _pick_short_name(addr, "", "x") == "Shibuya"


def test_pick_short_name_display_name_segment_fallback():
    # No name, no usable address tags -> first comma seg with len>2 and not digits.
    assert _pick_short_name({}, "", "6號, Real Street, City") == "Real Street"


def test_pick_short_name_digit_house_number_segment_skipped():
    # "6號" is digit-ish (號 stripped -> "6") so skipped; "Block A" is len>2.
    assert _pick_short_name({}, "", "6號, Block A") == "Block A"


def test_pick_short_name_last_resort_first_segment():
    # All segments are short/digit-ish; returns first comma segment.
    assert _pick_short_name({}, "", "6, 7") == "6"


def test_pick_short_name_empty_everything_returns_empty():
    assert _pick_short_name({}, "", "") == ""


def test_pick_short_name_strips_whitespace():
    assert _pick_short_name({"tourism": "  Spaced POI  "}, "", "d") == "Spaced POI"


# ---------------------------------------------------------------------------
# _headers
# ---------------------------------------------------------------------------


def test_headers_contains_user_agent(svc):
    h = svc._headers()
    assert h["Accept"] == "application/json"
    assert h["User-Agent"] == geocoding.NOMINATIM_USER_AGENT
