"""Characterization tests for api/location.py — pin the externally-observable
contract BEFORE the DI swap (Task 21).  These tests MUST pass against the
current (pre-swap) code AND continue to pass after the swap.

Five pinned contracts:
1. GET /status resolves the engine via _engine and stitches cooldown_remaining.
2. GET /cooldown/status reads the live timer.
3. PUT+GET /settings/coord-format round-trip mutates the live formatter.
4. GET+PUT+DELETE /settings/initial-position persist+clear.
5. Single-device cooldown 429 guard returns {"detail": {"code": "cooldown_active"}}
   without reaching the engine.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


# ── 1. /status resolves engine + stitches cooldown_remaining ─────────────────

def test_get_status_stitches_cooldown_remaining(client):
    """GET /status must return a body with cooldown_remaining from the live timer."""
    from models.schemas import SimulationStatus

    fake_status = SimulationStatus()  # all defaults
    fake_engine = MagicMock()
    fake_engine.get_status = MagicMock(return_value=fake_status)

    async def fake_resolver(udid=None, registry=None):
        return fake_engine

    with patch("api.location._engine", fake_resolver):
        resp = client.get("/api/location/status")

    assert resp.status_code == 200
    body = resp.json()
    assert "cooldown_remaining" in body


# ── 2. /cooldown/status reads live timer ─────────────────────────────────────

def test_cooldown_status_reads_live_timer(client):
    """GET /cooldown/status must return enabled/remaining from the live timer."""
    resp = client.get("/api/location/cooldown/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "enabled" in body
    assert "remaining_seconds" in body


# ── 3. /settings/coord-format PUT→GET round-trip ─────────────────────────────

def test_coord_format_put_get_roundtrip(client):
    """PUT then GET /settings/coord-format must reflect the new value."""
    from models.schemas import CoordinateFormat

    # PUT a specific format
    resp_put = client.put("/api/location/settings/coord-format",
                          json={"format": CoordinateFormat.DMS.value})
    assert resp_put.status_code == 200
    assert resp_put.json()["format"] == CoordinateFormat.DMS.value

    resp_get = client.get("/api/location/settings/coord-format")
    assert resp_get.status_code == 200
    assert resp_get.json()["format"] == CoordinateFormat.DMS.value

    # Restore original (DD)
    client.put("/api/location/settings/coord-format",
               json={"format": CoordinateFormat.DD.value})


# ── 4. /settings/initial-position persist+clear ──────────────────────────────

def test_initial_position_persist_and_clear(client):
    """PUT persists and GET returns the position; PUT null clears it."""
    # Set a position
    resp = client.put("/api/location/settings/initial-position",
                      json={"lat": 25.034, "lng": 121.545})
    assert resp.status_code == 200
    body = resp.json()
    assert body["position"]["lat"] == pytest.approx(25.034)
    assert body["position"]["lng"] == pytest.approx(121.545)

    resp_get = client.get("/api/location/settings/initial-position")
    assert resp_get.status_code == 200
    assert resp_get.json()["position"] is not None

    # Clear it
    resp_clear = client.put("/api/location/settings/initial-position",
                            json={"lat": None, "lng": None})
    assert resp_clear.status_code == 200
    assert resp_clear.json()["position"] is None


# ── 5. Single-device cooldown 429 guard ──────────────────────────────────────

def test_teleport_cooldown_429_without_reaching_engine(client):
    """When cooldown is active in single-device mode, POST /teleport returns
    429 with {"detail": {"code": "cooldown_active"}} before calling the engine."""
    from main import app_state
    from unittest.mock import MagicMock, AsyncMock

    cooldown = app_state.cooldown_timer
    fake_engine = MagicMock()
    fake_engine.teleport = AsyncMock()

    async def fake_resolver(udid=None, registry=None):
        return fake_engine

    original_enabled = cooldown.enabled
    original_is_active = cooldown.is_active
    original_remaining = cooldown.remaining

    # Force single-device mode: no engines → dual_mode=False
    with (
        patch("api.location._engine", fake_resolver),
        patch.object(cooldown, "enabled", True),
        patch.object(cooldown, "is_active", True),
        patch.object(cooldown, "remaining", 30.0),
        patch.object(app_state, "simulation_engines", {}),
    ):
        resp = client.post("/api/location/teleport",
                           json={"lat": 25.034, "lng": 121.545})

    assert resp.status_code == 429
    body = resp.json()
    assert body["detail"]["code"] == "cooldown_active"
    # Engine was never called
    fake_engine.teleport.assert_not_awaited()
