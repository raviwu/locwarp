"""Characterize the phone-control PIN/token gate that protects LAN-reachable
endpoints. Locks: token-gated endpoint 401s without a token; bad PIN 401s;
correct PIN mints the live token which then satisfies the gate."""
import main
import api.phone_control as pc
from fastapi.testclient import TestClient


def _client():
    return TestClient(main.app)


def test_token_gated_endpoint_rejects_missing_token():
    """A token-protected phone endpoint returns 401 with no token.
    /api/phone/status calls _check_token and is not localhost-gated."""
    c = _client()
    r = c.get("/api/phone/status")  # no X-LocWarp-Token, no ?t=
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "phone_auth_required"


def test_bad_pin_rejected():
    c = _client()
    real_pin = pc._auth.pin
    wrong_pin = "000001" if real_pin == "000000" else "000000"
    r = c.post("/api/phone/auth", json={"pin": wrong_pin})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "bad_pin"


def test_correct_pin_mints_token_that_passes_gate():
    """Read the live PIN from the in-process singleton, exchange it for a token,
    and prove that token satisfies _check_token on a gated endpoint."""
    c = _client()
    pin = pc._auth.pin                      # in-process; not exposed over the wire
    r = c.post("/api/phone/auth", json={"pin": pin})
    assert r.status_code == 200
    token = r.json()["token"]
    assert token == pc._auth.token

    # The minted token now satisfies the gate (header form).
    r2 = c.get("/api/phone/status", headers={"X-LocWarp-Token": token})
    assert r2.status_code != 401


def test_api_host_stays_lan_reachable():
    """phone.html serves a real phone over WiFi -> bind must stay 0.0.0.0.
    Loopback would silently break LAN reachability; this is intentional."""
    from config import API_HOST
    assert API_HOST == "0.0.0.0"
