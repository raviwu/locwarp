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

    async def fake_resolver(udid, registry=None):
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

    async def fake_resolver(udid, registry=None):
        return fake_engine

    with patch("api.location._engine", fake_resolver):
        resp = client.post("/api/location/goldditto/cycle", json=_payload())
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "cycle_in_progress"


def test_endpoint_recovers_from_device_lost_and_retries(client):
    """H1 fix: the cycle is now wrapped in _try_with_recovery_retry, so a
    DeviceLostError on the first push triggers full_reconnect + one retry.
    First attempt raises DeviceLostError, reconnect succeeds, retry returns the
    result → 200 (a plain /teleport already self-heals this way; gold ditto used
    to hard-503)."""
    from main import app_state
    from services.location_service import DeviceLostError

    udid = "UDID-GD-RECOVER"
    fake_result = {"target_used": "A", "lat": 25.0, "lng": 121.5, "duration_ms": 10}
    fake_engine = MagicMock()
    fake_engine.goldditto_cycle = AsyncMock(
        side_effect=[DeviceLostError("gone"), fake_result]
    )

    async def fake_resolver(u=None, registry=None):
        return fake_engine

    with (
        patch("api.location._engine", fake_resolver),
        patch.object(app_state.device_manager, "full_reconnect",
                     new=AsyncMock(return_value=True)),
        patch.object(app_state, "simulation_engines", {}),
        patch.object(app_state, "_primary_udid", udid),
    ):
        resp = client.post("/api/location/goldditto/cycle", json=_payload(udid=udid))

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert fake_engine.goldditto_cycle.await_count == 2


def test_endpoint_device_lost_unrecoverable_surfaces_frozen_503(client):
    """If full_reconnect cannot recover, the cycle surfaces the frozen 503
    device_lost body (same contract as /teleport)."""
    from main import app_state
    from services.location_service import DeviceLostError

    udid = "UDID-GD-LOST"
    dm = app_state.device_manager
    fake_engine = MagicMock()
    fake_engine.goldditto_cycle = AsyncMock(
        side_effect=DeviceLostError("gone", reason=DeviceLostError.REASON_USB_GONE)
    )

    async def fake_resolver(u=None, registry=None):
        return fake_engine

    fake_connections = {udid: object()}

    async def _fake_disconnect(u):
        fake_connections.pop(u, None)

    class _CapPublisher:
        async def publish(self, event):
            pass

    with (
        patch("api.location._engine", fake_resolver),
        patch.object(dm, "_connections", fake_connections),
        patch.object(dm, "_events", _CapPublisher()),
        patch.object(dm, "disconnect", side_effect=_fake_disconnect),
        patch.object(dm, "full_reconnect", new=AsyncMock(return_value=False)),
        patch.object(app_state, "remove_engine", new=AsyncMock(return_value=None)),
        patch.object(app_state, "simulation_engines", {}),
        patch.object(app_state, "_primary_udid", udid),
    ):
        resp = client.post("/api/location/goldditto/cycle", json=_payload(udid=udid))

    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "device_lost"
