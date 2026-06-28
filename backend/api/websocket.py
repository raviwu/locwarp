import asyncio
import ipaddress
import json
import logging

import config
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from models.schemas import JoystickInput

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)

# Active WebSocket connections
_connections: list[WebSocket] = []


def _ws_origin_allowed(origin: str | None) -> bool:
    """Drive-by-webpage guard. The shipped Electron renderer loads via
    loadFile() -> WS Origin is absent / 'null' / 'file://' (NOT a remote
    http(s) origin, NOT in CORS_ORIGINS). Allow those plus any allowlisted
    origin; reject a present REMOTE http(s) origin (a malicious local page
    in the user's own browser — loopback, so the client-host check alone
    cannot stop it)."""
    if not origin or origin == "null" or origin.startswith("file:"):
        return True
    if origin in config.CORS_ORIGINS:
        return True
    return False


def _ws_client_is_loopback(ws: WebSocket) -> bool:
    host = ws.client.host if ws.client else None
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def broadcast(event_type: str, data: dict):
    """Broadcast event to all connected WebSocket clients."""
    message = json.dumps({"type": event_type, "data": data})
    dead = []
    for ws in _connections:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections.remove(ws)


@router.websocket("/ws/status")
async def websocket_endpoint(ws: WebSocket):
    # Security gate (before accept): the joystick WS is loopback-only — the
    # desktop UI is a 127.0.0.1 client; the phone uses /api/phone/*. A LAN
    # peer or a drive-by remote-Origin page must never drive the device.
    if not _ws_client_is_loopback(ws) or not _ws_origin_allowed(ws.headers.get("origin")):
        await ws.close(code=1008)
        return
    await ws.accept()
    _connections.append(ws)
    logger.info("WebSocket client connected (%d total)", len(_connections))

    # Bind the engine registry from the DI container once per connection.
    # Engines are read fresh per message so newly-connected devices join the
    # fan-out, but the registry handle itself never changes.
    engine_registry = ws.app.state.container.engine_registry

    try:
        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "joystick_input":
                data = msg.get("data", {})
                # Route per-udid if provided; otherwise fan out to all engines.
                udid = msg.get("udid") or data.get("udid")
                inp = JoystickInput(
                    direction=data.get("direction", 0),
                    intensity=data.get("intensity", 0),
                )
                if udid:
                    engine = engine_registry.get_engine(udid)
                    if engine:
                        engine.joystick_move(inp)
                else:
                    for engine in list(engine_registry.simulation_engines.values()):
                        engine.joystick_move(inp)

            elif msg_type == "joystick_stop":
                udid = msg.get("udid") or msg.get("data", {}).get("udid")
                if udid:
                    engine = engine_registry.get_engine(udid)
                    if engine:
                        await engine.joystick_stop()
                else:
                    for engine in list(engine_registry.simulation_engines.values()):
                        await engine.joystick_stop()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        if ws in _connections:
            _connections.remove(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(_connections))
