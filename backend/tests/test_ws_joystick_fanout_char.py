"""Characterization test for the WebSocket joystick handler fan-out.

Freezes the routing semantics of the `joystick_input` / `joystick_stop`
inner-loop sites in `api/websocket.py`:

- A no-udid `joystick_input` fans out to ALL engines (multi-subscriber
  broadcast — every connected device's engine receives the move).
- A udid'd `joystick_stop` routes to EXACTLY ONE engine.

The handler reads the engine registry from the DI container bound to the
WebSocket's app (`ws.app.state.container.engine_registry`), not from a
module-level `from main import app_state`. The registry handle is bound once
per connection but engines are read fresh per message.
"""
from __future__ import annotations

import json

import pytest

from api.websocket import websocket_endpoint

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------
class FakeEngine:
    """Minimal engine double recording joystick fan-out hits."""

    def __init__(self) -> None:
        self.moves: list = []
        self.stops: int = 0

    def joystick_move(self, inp) -> None:  # sync, per spec
        self.moves.append(inp)

    async def joystick_stop(self) -> None:  # async, per spec
        self.stops += 1


class FakeRegistry:
    """Mimics AppState's engine registry surface used by the handler."""

    def __init__(self, engines: dict) -> None:
        self.simulation_engines = engines

    def get_engine(self, udid):
        return self.simulation_engines.get(udid)


class _State:
    pass


class _Container:
    def __init__(self, engine_registry) -> None:
        self.engine_registry = engine_registry


class _App:
    def __init__(self, container) -> None:
        self.state = _State()
        self.state.container = container


class FakeWebSocket:
    """Feeds a scripted list of inbound text frames, then disconnects."""

    def __init__(self, app, messages: list[str]) -> None:
        self.app = app
        self._messages = list(messages)
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if not self._messages:
            # Mimic a client disconnect to break the receive loop.
            from fastapi import WebSocketDisconnect

            raise WebSocketDisconnect()
        return self._messages.pop(0)

    async def send_text(self, text: str) -> None:  # pragma: no cover - unused
        pass


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
async def test_no_udid_joystick_input_fans_out_to_all_engines():
    eng_a = FakeEngine()
    eng_b = FakeEngine()
    registry = FakeRegistry({"udid-a": eng_a, "udid-b": eng_b})
    app = _App(_Container(registry))

    msg = json.dumps(
        {"type": "joystick_input", "data": {"direction": 90, "intensity": 0.5}}
    )
    ws = FakeWebSocket(app, [msg])

    await websocket_endpoint(ws)

    # Fan-out: BOTH engines received the move.
    assert len(eng_a.moves) == 1
    assert len(eng_b.moves) == 1
    assert eng_a.moves[0].direction == 90
    assert eng_a.moves[0].intensity == 0.5
    assert eng_b.moves[0].direction == 90
    assert eng_b.moves[0].intensity == 0.5


async def test_udid_joystick_stop_routes_to_exactly_one_engine():
    eng_a = FakeEngine()
    eng_b = FakeEngine()
    registry = FakeRegistry({"udid-a": eng_a, "udid-b": eng_b})
    app = _App(_Container(registry))

    msg = json.dumps({"type": "joystick_stop", "udid": "udid-a"})
    ws = FakeWebSocket(app, [msg])

    await websocket_endpoint(ws)

    # Routed: only udid-a stopped.
    assert eng_a.stops == 1
    assert eng_b.stops == 0
