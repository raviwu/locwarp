"""Characterization: POST /loop threads the optional `timestamps` field into
engine.start_loop(timestamps=...) exactly — activating the timed-replay branch
when present and leaving it None when absent.

Uses a fake async engine injected via the _engine resolver (same pattern as
test_goldditto_api.py and test_location_di_char.py).  The fake engine captures
every kwarg passed to start_loop so we can assert the threading without running
real looper machinery.

Two pinned contracts:
1. POST /loop WITH timestamps → engine.start_loop receives timestamps=<list>.
2. POST /loop WITHOUT timestamps → engine.start_loop receives timestamps=None.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app  # noqa: WPS433
    return TestClient(app)


def _base_payload(**overrides):
    base = {
        "waypoints": [
            {"lat": 25.0, "lng": 121.0},
            {"lat": 25.001, "lng": 121.001},
            {"lat": 25.002, "lng": 121.002},
        ],
        "mode": "walking",
    }
    base.update(overrides)
    return base


def _make_fake_engine():
    fake_engine = MagicMock()
    # start_loop must be an AsyncMock so the handler can await it via _spawn.
    fake_engine.start_loop = AsyncMock(return_value=None)
    return fake_engine


async def _fake_resolver(udid=None, registry=None):
    pass  # replaced per test via patch("api.location._engine", ...)


# ── 1. timestamps present → threaded into start_loop ─────────────────────────

def test_loop_with_timestamps_threads_them_into_start_loop(client):
    """POST /loop with timestamps → engine.start_loop(timestamps=[...])."""
    ts = [0.0, 4.5, 9.0]
    fake_engine = _make_fake_engine()

    async def fake_resolver(udid=None, registry=None):
        return fake_engine

    with patch("api.location._engine", fake_resolver):
        resp = client.post(
            "/api/location/loop",
            json=_base_payload(timestamps=ts),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "started"

    fake_engine.start_loop.assert_awaited_once()
    _, kwargs = fake_engine.start_loop.await_args
    assert "timestamps" in kwargs, "start_loop must be called with timestamps= kwarg"
    assert kwargs["timestamps"] == ts, (
        f"Expected timestamps={ts!r}, got {kwargs['timestamps']!r}"
    )


# ── 2. timestamps absent → start_loop receives timestamps=None ───────────────

def test_loop_without_timestamps_passes_none_to_start_loop(client):
    """POST /loop without timestamps field → engine.start_loop(timestamps=None)."""
    fake_engine = _make_fake_engine()

    async def fake_resolver(udid=None, registry=None):
        return fake_engine

    with patch("api.location._engine", fake_resolver):
        resp = client.post(
            "/api/location/loop",
            json=_base_payload(),  # no timestamps key
        )

    assert resp.status_code == 200

    fake_engine.start_loop.assert_awaited_once()
    _, kwargs = fake_engine.start_loop.await_args
    assert kwargs.get("timestamps") is None, (
        f"Expected timestamps=None, got {kwargs.get('timestamps')!r}"
    )


# ── 3. LoopRequest schema accepts timestamps; default is None ─────────────────

def test_loop_request_timestamps_field_defaults_to_none():
    """LoopRequest.timestamps defaults to None (additive / backward-compatible)."""
    from models.schemas import LoopRequest, Coordinate, MovementMode

    req = LoopRequest(
        waypoints=[Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.001, lng=121.001)],
        mode=MovementMode.WALKING,
    )
    assert req.timestamps is None


def test_loop_request_accepts_timestamps_list():
    """LoopRequest.timestamps accepts a list[float]."""
    from models.schemas import LoopRequest, Coordinate, MovementMode

    ts = [0.0, 10.5, 20.0]
    req = LoopRequest(
        waypoints=[
            Coordinate(lat=25.0, lng=121.0),
            Coordinate(lat=25.001, lng=121.001),
            Coordinate(lat=25.002, lng=121.002),
        ],
        mode=MovementMode.WALKING,
        timestamps=ts,
    )
    assert req.timestamps == ts
