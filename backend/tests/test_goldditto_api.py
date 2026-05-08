"""FastAPI integration tests for /api/location/goldditto/cycle."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Build a TestClient against a fresh app with mocked engine resolver."""
    from main import app  # noqa: WPS433
    return TestClient(app)


def _payload(**overrides):
    base = {
        "target": "A",
        "lat_a": 25.034897, "lng_a": 121.545827,
        "lat_b": 25.10, "lng_b": 121.60,
        "wait_seconds": 0.5,
    }
    base.update(overrides)
    return base


def test_endpoint_validates_payload(client):
    resp = client.post("/api/location/goldditto/cycle",
                        json=_payload(target="bad"))
    assert resp.status_code == 422


def test_endpoint_validates_wait_lower_bound(client):
    resp = client.post("/api/location/goldditto/cycle",
                        json=_payload(wait_seconds=0.1))
    # 0.1 < 0.5 lower bound → validation error
    assert resp.status_code == 422


def test_endpoint_returns_completed_when_engine_succeeds(client):
    fake_result = {"target_used": "A", "lat": 25.0, "lng": 121.5, "duration_ms": 50}
    fake_engine = MagicMock()
    fake_engine.goldditto_cycle = AsyncMock(return_value=fake_result)

    async def fake_resolver(udid):
        return fake_engine

    with patch("api.location._engine", fake_resolver):
        resp = client.post("/api/location/goldditto/cycle", json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["target_used"] == "A"
    fake_engine.goldditto_cycle.assert_awaited_once()


def test_endpoint_returns_409_on_locked_error(client):
    from core.goldditto import GoldDittoLockedError
    fake_engine = MagicMock()
    fake_engine.goldditto_cycle = AsyncMock(side_effect=GoldDittoLockedError("busy"))

    async def fake_resolver(udid):
        return fake_engine

    with patch("api.location._engine", fake_resolver):
        resp = client.post("/api/location/goldditto/cycle", json=_payload())
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "cycle_in_progress"
