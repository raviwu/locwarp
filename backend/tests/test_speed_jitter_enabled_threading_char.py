"""Characterization: speed_jitter_enabled=false threads end-to-end through all
four movement-start modes (navigate / loop / multistop / randomwalk).

Contract pinned: when a movement-start request carries speed_jitter_enabled=false,
the corresponding engine method is called with speed_jitter_enabled=False; and
when the field is absent (default true), the engine method is called with True.

Uses a fake async engine injected via the _engine resolver — same pattern as
test_loop_timestamps_threading_char.py.  The fake engine captures every kwarg
passed to the engine method so we can assert the threading without running real
mover/routing machinery.

Also pins the schema default (additive / backward-compatible): omitting the
field keeps speed_jitter on (True).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app  # noqa: WPS433
    return TestClient(app)


def _make_fake_engine():
    fake = MagicMock()
    fake.navigate = AsyncMock(return_value=None)
    fake.start_loop = AsyncMock(return_value=None)
    fake.multi_stop = AsyncMock(return_value=None)
    fake.random_walk = AsyncMock(return_value=None)
    return fake


def _fake_resolver_for(fake_engine):
    async def _resolver(udid=None, registry=None):
        return fake_engine
    return _resolver


# ── navigate ─────────────────────────────────────────────────────────────────

def test_navigate_jitter_disabled_threads_flag(client):
    """POST /navigate with speed_jitter_enabled=false → engine.navigate receives
    speed_jitter_enabled=False."""
    fake = _make_fake_engine()
    with patch("api.location._engine", _fake_resolver_for(fake)):
        resp = client.post("/api/location/navigate", json={
            "lat": 25.034, "lng": 121.564,
            "mode": "walking",
            "speed_jitter_enabled": False,
        })
    assert resp.status_code == 200
    fake.navigate.assert_awaited_once()
    _, kwargs = fake.navigate.await_args
    assert kwargs.get("speed_jitter_enabled") is False, (
        f"Expected speed_jitter_enabled=False, got {kwargs.get('speed_jitter_enabled')!r}"
    )


def test_navigate_jitter_default_threads_true(client):
    """POST /navigate without speed_jitter_enabled → engine.navigate receives
    speed_jitter_enabled=True (backward-compatible default)."""
    fake = _make_fake_engine()
    with patch("api.location._engine", _fake_resolver_for(fake)):
        resp = client.post("/api/location/navigate", json={
            "lat": 25.034, "lng": 121.564,
        })
    assert resp.status_code == 200
    fake.navigate.assert_awaited_once()
    _, kwargs = fake.navigate.await_args
    assert kwargs.get("speed_jitter_enabled") is True, (
        f"Expected speed_jitter_enabled=True, got {kwargs.get('speed_jitter_enabled')!r}"
    )


# ── loop ─────────────────────────────────────────────────────────────────────

_LOOP_WPS = [
    {"lat": 25.0, "lng": 121.0},
    {"lat": 25.001, "lng": 121.001},
    {"lat": 25.002, "lng": 121.002},
]


def test_loop_jitter_disabled_threads_flag(client):
    """POST /loop with speed_jitter_enabled=false → engine.start_loop receives
    speed_jitter_enabled=False."""
    fake = _make_fake_engine()
    with patch("api.location._engine", _fake_resolver_for(fake)):
        resp = client.post("/api/location/loop", json={
            "waypoints": _LOOP_WPS,
            "mode": "walking",
            "speed_jitter_enabled": False,
        })
    assert resp.status_code == 200
    fake.start_loop.assert_awaited_once()
    _, kwargs = fake.start_loop.await_args
    assert kwargs.get("speed_jitter_enabled") is False


def test_loop_jitter_default_threads_true(client):
    """POST /loop without speed_jitter_enabled → engine.start_loop receives True."""
    fake = _make_fake_engine()
    with patch("api.location._engine", _fake_resolver_for(fake)):
        resp = client.post("/api/location/loop", json={
            "waypoints": _LOOP_WPS,
        })
    assert resp.status_code == 200
    fake.start_loop.assert_awaited_once()
    _, kwargs = fake.start_loop.await_args
    assert kwargs.get("speed_jitter_enabled") is True


# ── multistop ────────────────────────────────────────────────────────────────

_MS_WPS = [
    {"lat": 25.0, "lng": 121.0},
    {"lat": 25.005, "lng": 121.005},
]


def test_multistop_jitter_disabled_threads_flag(client):
    """POST /multistop with speed_jitter_enabled=false → engine.multi_stop receives
    speed_jitter_enabled=False."""
    fake = _make_fake_engine()
    with patch("api.location._engine", _fake_resolver_for(fake)):
        resp = client.post("/api/location/multistop", json={
            "waypoints": _MS_WPS,
            "mode": "walking",
            "speed_jitter_enabled": False,
        })
    assert resp.status_code == 200
    fake.multi_stop.assert_awaited_once()
    _, kwargs = fake.multi_stop.await_args
    assert kwargs.get("speed_jitter_enabled") is False


def test_multistop_jitter_default_threads_true(client):
    """POST /multistop without speed_jitter_enabled → engine.multi_stop receives True."""
    fake = _make_fake_engine()
    with patch("api.location._engine", _fake_resolver_for(fake)):
        resp = client.post("/api/location/multistop", json={
            "waypoints": _MS_WPS,
        })
    assert resp.status_code == 200
    fake.multi_stop.assert_awaited_once()
    _, kwargs = fake.multi_stop.await_args
    assert kwargs.get("speed_jitter_enabled") is True


# ── randomwalk ────────────────────────────────────────────────────────────────

def test_randomwalk_jitter_disabled_threads_flag(client):
    """POST /randomwalk with speed_jitter_enabled=false → engine.random_walk
    receives speed_jitter_enabled=False."""
    fake = _make_fake_engine()
    with patch("api.location._engine", _fake_resolver_for(fake)):
        resp = client.post("/api/location/randomwalk", json={
            "center": {"lat": 25.034, "lng": 121.564},
            "radius_m": 300.0,
            "mode": "walking",
            "speed_jitter_enabled": False,
        })
    assert resp.status_code == 200
    fake.random_walk.assert_awaited_once()
    _, kwargs = fake.random_walk.await_args
    assert kwargs.get("speed_jitter_enabled") is False


def test_randomwalk_jitter_default_threads_true(client):
    """POST /randomwalk without speed_jitter_enabled → engine.random_walk receives True."""
    fake = _make_fake_engine()
    with patch("api.location._engine", _fake_resolver_for(fake)):
        resp = client.post("/api/location/randomwalk", json={
            "center": {"lat": 25.034, "lng": 121.564},
            "radius_m": 300.0,
        })
    assert resp.status_code == 200
    fake.random_walk.assert_awaited_once()
    _, kwargs = fake.random_walk.await_args
    assert kwargs.get("speed_jitter_enabled") is True


# ── schema backward-compatibility ────────────────────────────────────────────

def test_navigate_request_default_is_true():
    from models.schemas import NavigateRequest
    req = NavigateRequest(lat=25.0, lng=121.0)
    assert req.speed_jitter_enabled is True


def test_loop_request_default_is_true():
    from models.schemas import LoopRequest, Coordinate
    req = LoopRequest(
        waypoints=[Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.001, lng=121.001)],
    )
    assert req.speed_jitter_enabled is True


def test_multistop_request_default_is_true():
    from models.schemas import MultiStopRequest, Coordinate
    req = MultiStopRequest(
        waypoints=[Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.001, lng=121.001)],
    )
    assert req.speed_jitter_enabled is True


def test_randomwalk_request_default_is_true():
    from models.schemas import RandomWalkRequest, Coordinate
    req = RandomWalkRequest(center=Coordinate(lat=25.0, lng=121.0))
    assert req.speed_jitter_enabled is True


def test_navigate_request_accepts_false():
    from models.schemas import NavigateRequest
    req = NavigateRequest(lat=25.0, lng=121.0, speed_jitter_enabled=False)
    assert req.speed_jitter_enabled is False
