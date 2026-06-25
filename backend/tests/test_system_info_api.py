"""GET /api/system/info exposes helper-aliveness, per-device {ios, ddi_mounted},
and offline_geo_ok — the otherwise restart-only health states, made queryable.
Mirrors the TestClient + app.state.container harness used by test_geocode_api.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


def test_info_shape_and_offline_geo_ok_true(monkeypatch, client):
    import main
    import services.geo_offline as geo_offline
    from core.device_manager import _ActiveConnection

    dm = main.app.state.container.device_manager
    # Seed one fake connected device with the new ddi_mounted flag set.
    conn = _ActiveConnection(udid="UDID-1", lockdown=object(), ios_version="17.0")
    conn.ddi_mounted = True
    conn.connection_type = "USB"
    monkeypatch.setattr(dm, "_connections", {"UDID-1": conn})

    # offline geo probe returns a real country/timezone -> ok True.
    monkeypatch.setattr(
        geo_offline, "resolve", lambda _lat, _lng: ("us", "America/New_York", "New York", "New York")
    )

    res = client.get("/api/system/info")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["version"], str) and body["version"]
    assert body["offline_geo_ok"] is True
    assert isinstance(body["helper_alive"], bool)
    assert body["devices"] == [
        {"udid": "UDID-1", "ios": "17.0", "ddi_mounted": True, "connection_type": "USB"}
    ]


def test_info_offline_geo_ok_false_when_resolver_blank(monkeypatch, client):
    import main
    import services.geo_offline as geo_offline

    monkeypatch.setattr(geo_offline, "resolve", lambda _lat, _lng: ("", "", "", ""))
    res = client.get("/api/system/info")
    assert res.status_code == 200
    assert res.json()["offline_geo_ok"] is False


def test_info_offline_geo_ok_false_when_resolver_raises(monkeypatch, client):
    """The probe must catch its own failure -> offline_geo_ok False, never 500."""
    import main
    import services.geo_offline as geo_offline

    def boom(_lat, _lng):
        raise RuntimeError("simulated geo crash")

    monkeypatch.setattr(geo_offline, "resolve", boom)
    res = client.get("/api/system/info")
    assert res.status_code == 200
    assert res.json()["offline_geo_ok"] is False


def test_info_helper_alive_false_when_not_connected(monkeypatch, client):
    import main

    helper = main.app.state.container.helper_client
    # Force is_connected False so ping is never attempted and helper_alive=False.
    monkeypatch.setattr(type(helper), "is_connected", property(lambda self: False))
    res = client.get("/api/system/info")
    assert res.status_code == 200
    assert res.json()["helper_alive"] is False
