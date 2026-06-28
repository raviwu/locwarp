"""Characterization tests for the A1 fail-closed LAN HTTP gate.

Locks the contract BEFORE the middleware exists:
  - non-loopback caller -> 403 {"code": "lan_forbidden"} on the main API
    (mutating routes AND GET /api/system/info, which leaks udid/iOS).
  - loopback caller -> unaffected (existing behavior preserved).
  - /api/phone* and /phone reach the router from ANY host (the token /
    _is_localhost gate inside the router then applies) — the LAN surface.
"""
import main
from fastapi.testclient import TestClient

LAN = ("192.168.1.50", 9999)  # a non-loopback peer on the same WiFi


def _lan_client():
    return TestClient(main.app, client=LAN)


def _loopback_client():
    # Task-1 fixture already defaults to 127.0.0.1, but be explicit here.
    return TestClient(main.app, client=("127.0.0.1", 50000))


# --- non-loopback is rejected fail-closed ---------------------------------
def test_lan_peer_blocked_on_mutating_route():
    r = _lan_client().post("/api/location/teleport", json={"lat": 1.0, "lng": 2.0})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "lan_forbidden"


def test_lan_peer_blocked_on_system_info_leak():
    r = _lan_client().get("/api/system/info")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "lan_forbidden"


def test_lan_peer_blocked_on_system_shutdown():
    r = _lan_client().post("/api/system/shutdown")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "lan_forbidden"


def test_lan_peer_blocked_on_root():
    # Fail-closed: even the harmless banner route is gated for LAN peers.
    r = _lan_client().get("/")
    assert r.status_code == 403


# --- loopback is unaffected ------------------------------------------------
def test_loopback_reaches_root():
    r = _loopback_client().get("/")
    assert r.status_code == 200
    assert r.json()["name"] == "LocWarp"


def test_loopback_reaches_system_info():
    r = _loopback_client().get("/api/system/info")
    assert r.status_code == 200
    assert "devices" in r.json()


# --- phone surface stays LAN-reachable from any host -----------------------
def test_lan_peer_reaches_phone_token_gate_not_lan_gate():
    """A LAN peer hitting a token-gated phone endpoint must pass the A1 gate
    and be rejected by the phone TOKEN gate (401), NOT the LAN gate (403)."""
    r = _lan_client().get("/api/phone/status")  # no token
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "phone_auth_required"


def test_lan_peer_reaches_phone_page():
    r = _lan_client().get("/phone")
    assert r.status_code == 200


def test_lan_peer_reaches_phone_reach_probe():
    r = _lan_client().get("/api/phone/_reach")
    assert r.status_code == 200
