"""Characterization tests for phone_control DI sweep (Task 24).

Pins three invariants:
1. Auth token gate: endpoint 401s without a token.
2. No-device 503 ({"detail": {"code": "no_device"}}) via the injected registry.
3. /api/phone/geocode calls container.geocoding_service.search (not a fresh instance).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

import main
import api.phone_control as pc


# ── helpers ────────────────────────────────────────────────────────────────────


def _authed_client():
    """TestClient whose default headers carry the live phone token."""
    client = TestClient(main.app)
    client.headers.update({"X-LocWarp-Token": pc._auth.token})
    return client


# ── Test 1: auth token gate ────────────────────────────────────────────────────


def test_auth_gate_rejects_missing_token():
    """Token-protected phone endpoints return 401 when no token is sent."""
    client = TestClient(main.app)
    r = client.get("/api/phone/status")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "phone_auth_required"


# ── Test 2: no-device 503 via injected registry ───────────────────────────────


def test_teleport_503_when_no_engines():
    """POST /api/phone/teleport returns 503 with code=no_device when no engine
    is registered in the engine_registry (simulation_engines is empty)."""
    # Clear all engines in the live app_state (the engine_registry).
    original_engines = dict(main.app_state.simulation_engines)
    original_primary = main.app_state._primary_udid
    try:
        main.app_state.simulation_engines.clear()
        main.app_state._primary_udid = None
        client = _authed_client()
        r = client.post("/api/phone/teleport", json={"lat": 1.0, "lng": 2.0})
        assert r.status_code == 503
        assert r.json()["detail"]["code"] == "no_device"
    finally:
        main.app_state.simulation_engines.update(original_engines)
        main.app_state._primary_udid = original_primary


# ── Test 3: geocode uses the injected service ─────────────────────────────────


@pytest.mark.asyncio
async def test_geocode_uses_injected_service():
    """/api/phone/geocode must call container.geocoding_service.search (the
    singleton injected via get_geocoding_service), not a freshly constructed
    GeocodingService() instance.

    Pre-DI (current code): svc = GeocodingService() is a fresh instance, so
    patching container.geocoding_service.search has no effect and the mock is
    never awaited → this test FAILS.

    Post-DI (after Task 24): svc is the injected singleton and the patch IS
    called → PASSES.
    """
    from unittest.mock import MagicMock

    fake_result = MagicMock()
    fake_result.display_name = "Test Place"
    fake_result.short_name = "Test"
    fake_result.lat = 1.0
    fake_result.lng = 2.0
    fake_result.country_code = "TW"

    mock_search = AsyncMock(return_value=[fake_result])
    container = main.app.state.container
    original_search = container.geocoding_service.search
    try:
        container.geocoding_service.search = mock_search
        client = _authed_client()
        r = client.get("/api/phone/geocode", params={"q": "Taipei"})
        assert r.status_code == 200
        mock_search.assert_awaited_once()
    finally:
        container.geocoding_service.search = original_search
