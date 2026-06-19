"""TimezoneDB key is injected, not hardcoded; empty key short-circuits to None
without any network call. Never asserts the real key value."""
import pytest

import services.geo_extras as geo_extras


@pytest.mark.asyncio
async def test_no_key_returns_none_without_http(monkeypatch):
    """With an empty key, get_timezone returns None and never builds a client."""
    def _boom(*a, **k):
        raise AssertionError("httpx.AsyncClient must not be constructed with no key")
    monkeypatch.setattr(geo_extras.httpx, "AsyncClient", _boom)

    result = await geo_extras.get_timezone(25.0, 121.0, api_key="")
    assert result is None


@pytest.mark.asyncio
async def test_key_is_passed_through_to_params(monkeypatch):
    """The injected key reaches params['key'] — verified via a capturing fake
    client, without hardcoding/printing any real key."""
    captured = {}

    class _FakeResp:
        def raise_for_status(self): return None
        def json(self): return {"status": "OK", "zoneName": "Asia/Taipei",
                                "gmtOffset": 28800, "abbreviation": "CST"}

    class _FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *e): return False
        async def get(self, url, params=None):
            captured["params"] = params
            return _FakeResp()

    monkeypatch.setattr(geo_extras.httpx, "AsyncClient", _FakeClient)

    sentinel = "TEST_INJECTED_KEY_NOT_REAL"
    await geo_extras.get_timezone(25.0, 121.0, api_key=sentinel)
    assert captured["params"]["key"] == sentinel


def test_timezonedb_key_not_in_source():
    """Assert the hardcoded literal is gone from geo_extras module source."""
    import inspect
    src = inspect.getsource(geo_extras)
    assert "7JDL6A118RWJ" not in src
