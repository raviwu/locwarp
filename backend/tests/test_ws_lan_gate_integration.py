"""Real-Starlette integration tests for the /ws/status security gate.

Unlike test_ws_lan_gate_char.py (which calls websocket_endpoint() directly via
a FakeWS double), these tests use the REAL FastAPI app + Starlette TestClient
so they exercise the full ASGI dispatch path — including the close(1008)-before-
accept(). They prove that the rejection is observable from the client side, not
just from the server-side function perspective.

Exception type note: Starlette 0.47+ raises WebSocketDisconnect (code=1008) when
the server sends websocket.close before websocket.accept. WebSocketDenialResponse
(a subclass of WebSocketDisconnect) is only raised when the server uses the newer
send_denial_response() API — our guard uses ws.close(), so it surfaces as the
base WebSocketDisconnect with code=1008.

The conftest _testclient_defaults_to_loopback autouse fixture patches TestClient
so that TestClient(app) defaults client=("127.0.0.1", 50000). That fixture applies
here automatically, keeping all TestClient() calls loopback unless overridden.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import main


# ---------------------------------------------------------------------------
# Non-loopback peer is rejected
# ---------------------------------------------------------------------------

def test_non_loopback_ws_rejected_real_starlette():
    """A LAN peer (192.168.1.50) cannot upgrade — close(1008) before accept().

    This is the key integration test: it proves the guard actually closes the
    ASGI connection before accepting, observable from the client as
    WebSocketDisconnect(code=1008).
    """
    client = TestClient(main.app, client=("192.168.1.50", 9999))
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/status"):
            pass  # should never enter; guard fires during __enter__
    assert exc_info.value.code == 1008


# ---------------------------------------------------------------------------
# Loopback + remote https Origin is rejected
# ---------------------------------------------------------------------------

def test_loopback_remote_https_origin_rejected_real_starlette():
    """A drive-by browser page (https Origin, same machine) is blocked.

    Even though the client is loopback, the remote https:// Origin header
    is not in CORS_ORIGINS and therefore fails the _ws_origin_allowed() check.
    """
    # conftest default client is 127.0.0.1 — override origin header only
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with TestClient(main.app).websocket_connect(
            "/ws/status", headers={"origin": "https://evil.example.com"}
        ):
            pass
    assert exc_info.value.code == 1008


# ---------------------------------------------------------------------------
# Loopback + no Origin is ACCEPTED
# ---------------------------------------------------------------------------

def test_loopback_no_origin_accepted_real_starlette():
    """The Electron renderer (no Origin header) connects successfully.

    The guard passes, ws.accept() is called, and the test client can enter
    the context block. The connection is closed cleanly when the block exits
    (the endpoint's receive_text() sees a disconnect and exits the while loop),
    so no exception should propagate out.
    """
    # Enter the context — if the guard fires, __enter__ raises WebSocketDisconnect.
    # Reaching the body proves ws.accept() was called.
    with TestClient(main.app).websocket_connect("/ws/status") as _ws:
        pass  # accepted; context exit triggers clean disconnect
