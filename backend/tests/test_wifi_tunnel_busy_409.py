"""Endpoint: POST /api/device/wifi/tunnel/start refuses to tear down a live
connection on another transport (in-use udid) — returns a clean 409, not the
prior misleading 500. End-to-end check of the B' in-use guard through the
handler's error mapping.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core import wifi_tunnel as wt
from services.tunnel_helper_client import HelperError


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


class _BusyHelper:
    """open_wifi_tunnel always reports the one-per-udid -32003 (and records which
    udids were attempted); close_tunnel must NEVER be called — the guard refuses
    to tear the live tunnel down."""

    def __init__(self):
        self.open_wifi_calls: list[str] = []

    async def open_wifi_tunnel(self, udid, ip, port):
        self.open_wifi_calls.append(udid)
        raise HelperError(code=-32003, message=f"tunnel already exists for {udid}")

    async def close_tunnel(self, udid):
        raise AssertionError("close_tunnel must NOT be called for an in-use udid")

    async def list_tunnels(self):
        return []


def test_wifi_tunnel_start_returns_409_when_device_in_use(client):
    udid = "00008140-IN-USE"
    wt.set_helper_client(_BusyHelper())
    wt.set_in_use_predicate(lambda u: u == udid)
    try:
        resp = client.post(
            "/api/device/wifi/tunnel/start",
            json={"udid": udid, "ip": "192.168.1.50", "port": 49152},
        )
    finally:
        wt.set_in_use_predicate(lambda _u: False)
        wt.set_helper_client(None)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "tunnel_busy_other_transport"


def test_wifi_tunnel_start_bails_409_on_first_in_use_candidate(client, monkeypatch):
    # Multi-candidate (the dual-device / IP-only flow): candidate A is a live USB
    # device (in-use), B is some other udid. The handler must bail with a clean
    # 409 on the in-use A WITHOUT closing its tunnel and WITHOUT churning B — a
    # deliberate choice (a fast clear 409 beats a slow multi-candidate 500, and
    # never destroys A's live USB tunnel the way the pre-guard close+retry did).
    a_in_use, b_other = "AAAA-USB-IN-USE", "BBBB-OTHER"
    monkeypatch.setattr(
        "api.device._build_tunnel_udid_candidates",
        lambda req: [a_in_use, b_other],
    )
    helper = _BusyHelper()
    wt.set_helper_client(helper)
    wt.set_in_use_predicate(lambda u: u == a_in_use)
    try:
        resp = client.post(
            "/api/device/wifi/tunnel/start",
            json={"ip": "192.168.1.77", "port": 49152},
        )
    finally:
        wt.set_in_use_predicate(lambda _u: False)
        wt.set_helper_client(None)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "tunnel_busy_other_transport"
    assert helper.open_wifi_calls == [a_in_use]  # bailed on A; B never attempted
