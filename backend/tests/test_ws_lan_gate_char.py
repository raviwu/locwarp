"""Characterization tests for the A2 WebSocket gate in api/websocket.py.

A2-core: a non-loopback ws.client is rejected with close(1008) before
accept() — closes the LAN-peer joystick takeover.

A2-Origin (shipped: the production Electron renderer loads via loadFile,
so its WS Origin is file:// / null / absent — NOT a remote
http(s) origin, NOT in CORS_ORIGINS): a
present REMOTE http(s) Origin not in CORS_ORIGINS is rejected; an absent /
null / file:// / allowlisted Origin is accepted.
"""
from __future__ import annotations

import pytest

from api.websocket import websocket_endpoint

pytestmark = pytest.mark.asyncio


class _State:
    pass


class _Container:
    def __init__(self, engine_registry) -> None:
        self.engine_registry = engine_registry


class _App:
    def __init__(self, container) -> None:
        self.state = _State()
        self.state.container = container


class _Registry:
    simulation_engines: dict = {}

    def get_engine(self, udid):
        return None


class _Addr:
    def __init__(self, host: str) -> None:
        self.host = host


class FakeWS:
    """Direct-call double (same approach as test_ws_joystick_fanout_char).
    Records accept/close and immediately disconnects after accept so the
    receive loop exits cleanly."""

    def __init__(self, host: str, headers: dict | None = None) -> None:
        self.app = _App(_Container(_Registry()))
        self.client = _Addr(host)
        self.headers = headers or {}
        self.accepted = False
        self.closed_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code

    async def receive_text(self) -> str:
        from fastapi import WebSocketDisconnect
        raise WebSocketDisconnect()


# --- A2-core: loopback vs LAN peer ----------------------------------------
async def test_lan_peer_ws_rejected_before_accept():
    ws = FakeWS("192.168.1.50")
    await websocket_endpoint(ws)
    assert ws.accepted is False
    assert ws.closed_code == 1008


async def test_loopback_ws_accepted():
    ws = FakeWS("127.0.0.1")
    await websocket_endpoint(ws)
    assert ws.accepted is True
    assert ws.closed_code is None


# --- A2-Origin: drive-by webpage on the same machine ----------------------
async def test_loopback_ws_with_remote_origin_rejected():
    ws = FakeWS("127.0.0.1", headers={"origin": "http://evil.example.com"})
    await websocket_endpoint(ws)
    assert ws.accepted is False
    assert ws.closed_code == 1008


async def test_loopback_ws_with_file_origin_accepted():
    # The shipped Electron renderer (loadFile) presents file:// / null.
    ws = FakeWS("127.0.0.1", headers={"origin": "file://"})
    await websocket_endpoint(ws)
    assert ws.accepted is True


async def test_loopback_ws_with_null_origin_accepted():
    ws = FakeWS("127.0.0.1", headers={"origin": "null"})
    await websocket_endpoint(ws)
    assert ws.accepted is True


async def test_loopback_ws_with_allowlisted_dev_origin_accepted():
    ws = FakeWS("127.0.0.1", headers={"origin": "http://localhost:5173"})
    await websocket_endpoint(ws)
    assert ws.accepted is True
