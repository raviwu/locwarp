"""Endpoint tests for POST /api/device/wifi/repair.

Mocks usbmux + lockdown + helper client so the test never touches a real
iPhone. Verifies the new flow:

- helper not connected → 503 with friendly hint
- helper connected, repair_remote_record success → 200 + remote_record_regenerated
- helper raises HelperError(utun) → 500 with utun-classified message
- helper raises HelperError(trust) → 500 with Trust hint
- helper raises HelperError(generic) → 500 with raw message preserved
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _patch_usb_world(*, ios_version="17.5", helper_connected=True, helper_side_effect=None):
    """Set up the common mock chain for one /wifi/repair call.

    Returns a list of `with` context managers the caller activates.
    """
    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {
        "ProductVersion": ios_version,
        "DeviceName": "Test iPhone",
    }

    async def fake_create_using_usbmux(*a, **kw):
        return fake_lockdown

    async def fake_list_devices():
        return [SimpleNamespace(serial="ABC-UDID", connection_type="USB")]

    helper_mock = MagicMock()
    helper_mock.is_connected = helper_connected
    if helper_side_effect is not None:
        helper_mock.repair_remote_record = AsyncMock(side_effect=helper_side_effect)
    else:
        helper_mock.repair_remote_record = AsyncMock(
            return_value={"status": "ok", "udid": "ABC-UDID", "record_path": "/x"}
        )

    return (
        patch("pymobiledevice3.lockdown.create_using_usbmux", side_effect=fake_create_using_usbmux),
        patch("pymobiledevice3.usbmux.list_devices", side_effect=fake_list_devices),
        patch("main.helper_client", helper_mock),
    ), helper_mock


def test_repair_success_uses_helper(client):
    ctxs, helper_mock = _patch_usb_world()
    with ctxs[0], ctxs[1], ctxs[2]:
        resp = client.post("/api/device/wifi/repair")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "paired"
    assert body["udid"] == "ABC-UDID"
    assert body["remote_record_regenerated"] is True
    helper_mock.repair_remote_record.assert_awaited_once_with("ABC-UDID")


def test_repair_helper_disconnected_returns_503(client):
    ctxs, _ = _patch_usb_world(helper_connected=False)
    with ctxs[0], ctxs[1], ctxs[2]:
        resp = client.post("/api/device/wifi/repair")
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["code"] == "remote_pair_failed"
    assert "Tunnel helper" in detail["message"]


def test_repair_utun_error_classified(client):
    from services.tunnel_helper_client import HelperError
    ctxs, _ = _patch_usb_world(
        helper_side_effect=HelperError(-32002, "repair_remote_record failed: [Errno 0] Failed to create any utun interface"),
    )
    with ctxs[0], ctxs[1], ctxs[2]:
        resp = client.post("/api/device/wifi/repair")
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["code"] == "remote_pair_failed"
    assert "utun" in detail["message"]
    assert "管理員" in detail["message"]


def test_repair_trust_error_classified(client):
    from services.tunnel_helper_client import HelperError
    ctxs, _ = _patch_usb_world(
        helper_side_effect=HelperError(-32002, "PairingDialogResponsePending"),
    )
    with ctxs[0], ctxs[1], ctxs[2]:
        resp = client.post("/api/device/wifi/repair")
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "信任" in detail["message"]


def test_repair_generic_error_preserves_message(client):
    from services.tunnel_helper_client import HelperError
    ctxs, _ = _patch_usb_world(
        helper_side_effect=HelperError(-32002, "something weird"),
    )
    with ctxs[0], ctxs[1], ctxs[2]:
        resp = client.post("/api/device/wifi/repair")
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "RemotePairing 握手失敗" in detail["message"]
    assert "something weird" in detail["message"]


def test_wifi_repair_targets_requested_udid(client):
    """When the request body carries a udid, wifi_repair must use that
    specific device instead of defaulting to the first USB entry."""
    from types import SimpleNamespace

    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {"ProductVersion": "16.5", "DeviceName": "Target"}

    seen_serial = {}

    async def fake_create_using_usbmux(serial, autopair=False):
        seen_serial["serial"] = serial
        return fake_lockdown

    async def fake_list_devices():
        return [
            SimpleNamespace(serial="UDID-FIRST", connection_type="USB"),
            SimpleNamespace(serial="UDID-TARGET", connection_type="USB"),
        ]

    helper_mock = MagicMock()
    helper_mock.is_connected = True

    with (
        patch("pymobiledevice3.lockdown.create_using_usbmux", side_effect=fake_create_using_usbmux),
        patch("pymobiledevice3.usbmux.list_devices", side_effect=fake_list_devices),
        patch("main.helper_client", helper_mock),
    ):
        resp = client.post("/api/device/wifi/repair", json={"udid": "UDID-TARGET"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["udid"] == "UDID-TARGET"
    assert seen_serial["serial"] == "UDID-TARGET"


def test_wifi_repair_without_udid_keeps_legacy_first_usb(client):
    """Omitting udid (or sending an empty body) preserves legacy behavior:
    pick the first USB device. Existing UI button must keep working."""
    from types import SimpleNamespace

    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {"ProductVersion": "16.5", "DeviceName": "First"}

    seen_serial = {}

    async def fake_create_using_usbmux(serial, autopair=False):
        seen_serial["serial"] = serial
        return fake_lockdown

    async def fake_list_devices():
        return [
            SimpleNamespace(serial="UDID-FIRST", connection_type="USB"),
            SimpleNamespace(serial="UDID-OTHER", connection_type="USB"),
        ]

    helper_mock = MagicMock()
    helper_mock.is_connected = True

    with (
        patch("pymobiledevice3.lockdown.create_using_usbmux", side_effect=fake_create_using_usbmux),
        patch("pymobiledevice3.usbmux.list_devices", side_effect=fake_list_devices),
        patch("main.helper_client", helper_mock),
    ):
        resp = client.post("/api/device/wifi/repair")

    assert resp.status_code == 200
    body = resp.json()
    assert body["udid"] == "UDID-FIRST"
    assert seen_serial["serial"] == "UDID-FIRST"


def test_wifi_repair_unknown_udid_returns_404(client):
    """When the body names a udid that doesn't appear among USB devices,
    wifi_repair must return 404 with code=device_not_found and echo the
    udid in detail — not silently fall back to the first USB device."""
    from types import SimpleNamespace

    fake_lockdown = MagicMock()

    async def fake_create_using_usbmux(serial, autopair=False):
        # Should NOT be called — we expect to bail before reaching lockdown.
        raise AssertionError(f"unexpected lockdown call for {serial}")

    async def fake_list_devices():
        return [SimpleNamespace(serial="UDID-FIRST", connection_type="USB")]

    helper_mock = MagicMock()
    helper_mock.is_connected = True

    with (
        patch("pymobiledevice3.lockdown.create_using_usbmux", side_effect=fake_create_using_usbmux),
        patch("pymobiledevice3.usbmux.list_devices", side_effect=fake_list_devices),
        patch("main.helper_client", helper_mock),
    ):
        resp = client.post("/api/device/wifi/repair", json={"udid": "DOES-NOT-EXIST"})

    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["code"] == "device_not_found"
    assert detail["udid"] == "DOES-NOT-EXIST"
    assert "DOES-NOT-EXIST" in detail["message"]


# ── _humanize_pair_error tests ──

import pytest as _pytest

from pymobiledevice3.exceptions import (
    PairingDialogResponsePendingError,
    UserDeniedPairingError,
    ConnectionTerminatedError,
)


@_pytest.mark.parametrize(
    "exc, stale_cleared, expected_substring",
    [
        (PairingDialogResponsePendingError(), False, "請在 iPhone 解鎖畫面"),
        (UserDeniedPairingError(), False, "重置位置與隱私權"),
        (ConnectionTerminatedError(), True, "已重置配對紀錄"),
        (RuntimeError("某種未知錯誤"), False, "USB 配對失敗"),
    ],
)
def test_humanize_pair_error_table(exc, stale_cleared, expected_substring):
    from api.device import _humanize_pair_error
    msg = _humanize_pair_error(exc, stale_cleared=stale_cleared)
    assert expected_substring in msg
