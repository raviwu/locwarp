"""Endpoint tests for GET /api/device/wifi/tunnel/discover.

The endpoint browses RemotePairing over mDNS and labels each result. The
critical bit we exercise here: when the alias cache has a previously
remembered DeviceName for a Bonjour id, the picker shows that name —
not the raw IPv6 link-local address or the opaque hex id the user
reported seeing on main.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_alias_file(tmp_path, monkeypatch):
    path = tmp_path / "wifi_aliases.json"
    monkeypatch.setattr("config.WIFI_ALIASES_FILE", path)
    monkeypatch.setattr("core.device_manager.WIFI_ALIASES_FILE", path)
    yield path


def _bonjour_instance(*, instance, host, port, addresses):
    """Build a stand-in for pymobiledevice3.bonjour.ServiceInstance.

    Addresses are passed as objects with an ``.ip`` attribute to match the
    newer pymobiledevice3 shape; the endpoint also tolerates plain strings
    but we exercise the realistic path here.
    """
    return SimpleNamespace(
        instance=instance,
        host=host,
        port=port,
        addresses=[SimpleNamespace(ip=ip) for ip in addresses],
        properties={},
    )


def test_discover_returns_cached_devicename_when_alias_hit(client, isolated_alias_file):
    isolated_alias_file.write_text(
        json.dumps({"ABCDEF1234567890": {"udid": "udid-1", "name": "Ravi's iPhone"}})
    )

    async def fake_browse(timeout):
        return [
            _bonjour_instance(
                instance="ABCDEF1234567890._remotepairing._tcp.local.",
                host="ABCDEF1234567890.local",
                port=49152,
                addresses=["192.168.0.42"],
            )
        ]

    with patch("pymobiledevice3.bonjour.browse_remotepairing", side_effect=fake_browse):
        res = client.get("/api/device/wifi/tunnel/discover")

    assert res.status_code == 200
    devices = res.json()["devices"]
    assert len(devices) == 1
    assert devices[0]["name"] == "Ravi's iPhone"
    assert devices[0]["bonjour_id"] == "ABCDEF1234567890"
    assert devices[0]["ip"] == "192.168.0.42"


def test_discover_falls_back_to_bonjour_id_when_no_alias(client, isolated_alias_file):
    """Pre-pair (or post-uninstall) state — no alias yet. The stripped
    bonjour_id is still way more useful than the full PTR or an IPv6
    link-local, so that's what the picker should surface."""

    async def fake_browse(timeout):
        return [
            _bonjour_instance(
                instance="DEADBEEFDEADBEEF._remotepairing._tcp.local.",
                host="DEADBEEFDEADBEEF.local",
                port=49152,
                addresses=["192.168.0.42"],
            )
        ]

    with patch("pymobiledevice3.bonjour.browse_remotepairing", side_effect=fake_browse):
        res = client.get("/api/device/wifi/tunnel/discover")

    devices = res.json()["devices"]
    assert len(devices) == 1
    assert devices[0]["name"] == "DEADBEEFDEADBEEF"
    assert devices[0]["bonjour_id"] == "DEADBEEFDEADBEEF"


def test_discover_handles_ipv6_only_advertisement(client, isolated_alias_file):
    """When the iPhone only advertises an IPv6 link-local address (the
    actual user-reported scenario), the alias still rescues the picker
    from showing fe80:: in place of the device's name."""
    isolated_alias_file.write_text(
        json.dumps({"BONJ-IPv6": {"udid": "udid-2", "name": "WiFi-only iPhone"}})
    )

    async def fake_browse(timeout):
        return [
            _bonjour_instance(
                instance="BONJ-IPv6._remotepairing._tcp.local.",
                host="BONJ-IPv6.local",
                port=49152,
                addresses=["fe80::70f0:c3ff:fef7:9691"],
            )
        ]

    with patch("pymobiledevice3.bonjour.browse_remotepairing", side_effect=fake_browse):
        res = client.get("/api/device/wifi/tunnel/discover")

    devices = res.json()["devices"]
    assert len(devices) == 1
    assert devices[0]["name"] == "WiFi-only iPhone"
    assert devices[0]["bonjour_id"] == "BONJ-IPv6"
    # IPv6 still surfaces as the IP — that's the only thing the user can
    # actually connect to. The name field is what improves; the address
    # is unchanged.
    assert devices[0]["ip"] == "fe80::70f0:c3ff:fef7:9691"


def test_discover_returns_each_iphone_with_its_own_alias(client, isolated_alias_file):
    """Two iPhones discovered at the same time should both get their own
    cached name resolved independently — this is the exact scenario the
    bug report described ("找到 2 台, 選擇要連的")."""
    isolated_alias_file.write_text(
        json.dumps(
            {
                "PHONE-A": {"udid": "u-a", "name": "Ravi's iPhone"},
                "PHONE-B": {"udid": "u-b", "name": "Backup iPhone"},
            }
        )
    )

    async def fake_browse(timeout):
        return [
            _bonjour_instance(
                instance="PHONE-A._remotepairing._tcp.local.",
                host="PHONE-A.local",
                port=49152,
                addresses=["192.168.0.10"],
            ),
            _bonjour_instance(
                instance="PHONE-B._remotepairing._tcp.local.",
                host="PHONE-B.local",
                port=49153,
                addresses=["192.168.0.11"],
            ),
        ]

    with patch("pymobiledevice3.bonjour.browse_remotepairing", side_effect=fake_browse):
        res = client.get("/api/device/wifi/tunnel/discover")

    devices = res.json()["devices"]
    names_by_ip = {d["ip"]: d["name"] for d in devices}
    assert names_by_ip == {
        "192.168.0.10": "Ravi's iPhone",
        "192.168.0.11": "Backup iPhone",
    }


def test_discover_prefers_ipv4_when_both_families_advertised(client, isolated_alias_file):
    """Existing v4-preference behavior must not regress — when both v4
    and v6 are broadcast, the picker uses v4 so connect-to-link-local
    doesn't fail later for lack of a scope id."""

    async def fake_browse(timeout):
        return [
            _bonjour_instance(
                instance="DUAL._remotepairing._tcp.local.",
                host="DUAL.local",
                port=49152,
                addresses=[
                    "fe80::70f0:c3ff:fef7:9691",
                    "192.168.0.50",
                ],
            )
        ]

    with patch("pymobiledevice3.bonjour.browse_remotepairing", side_effect=fake_browse):
        res = client.get("/api/device/wifi/tunnel/discover")

    devices = res.json()["devices"]
    assert [d["ip"] for d in devices] == ["192.168.0.50"]
