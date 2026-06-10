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


@pytest.fixture(autouse=True)
def isolated_sticky_file(tmp_path, monkeypatch):
    """wifi_repair → dm.clear_user_denied persists; keep the file in tmp."""
    monkeypatch.setattr(
        "core.device_manager.STICKY_DENIED_FILE", tmp_path / "sticky_denied.json"
    )
    yield


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
        patch("services.usbmux_pair_records.create_using_usbmux", side_effect=fake_create_using_usbmux),
        patch("pymobiledevice3.usbmux.list_devices", side_effect=fake_list_devices),
        patch("main.helper_client", helper_mock),
    ), helper_mock


def test_repair_success_uses_helper(client):
    ctxs, helper_mock = _patch_usb_world()
    with ctxs[0], ctxs[1], ctxs[2], ctxs[3]:
        resp = client.post("/api/device/wifi/repair")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "paired"
    assert body["udid"] == "ABC-UDID"
    assert body["remote_record_regenerated"] is True
    helper_mock.repair_remote_record.assert_awaited_once_with("ABC-UDID")


def test_repair_helper_disconnected_returns_503(client):
    ctxs, _ = _patch_usb_world(helper_connected=False)
    with ctxs[0], ctxs[1], ctxs[2], ctxs[3]:
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
    with ctxs[0], ctxs[1], ctxs[2], ctxs[3]:
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
    with ctxs[0], ctxs[1], ctxs[2], ctxs[3]:
        resp = client.post("/api/device/wifi/repair")
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "信任" in detail["message"]


def test_repair_generic_error_preserves_message(client):
    from services.tunnel_helper_client import HelperError
    ctxs, _ = _patch_usb_world(
        helper_side_effect=HelperError(-32002, "something weird"),
    )
    with ctxs[0], ctxs[1], ctxs[2], ctxs[3]:
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
        patch("services.usbmux_pair_records.create_using_usbmux", side_effect=fake_create_using_usbmux),
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
        patch("services.usbmux_pair_records.create_using_usbmux", side_effect=fake_create_using_usbmux),
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


# ── Task 7: autopair_with_recovery wiring tests ──


def test_wifi_repair_clears_stale_cert_and_retries(monkeypatch):
    """A stale-cert exception on first autopair triggers cleanup + retry;
    successful retry returns 200 with stale_cleared=True in the response."""
    from fastapi.testclient import TestClient
    from main import app

    raw_dev = MagicMock(serial="UDID-STALE", connection_type="USB")

    async def fake_mux_list():
        return [raw_dev]

    attempts = {"n": 0}
    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {"ProductVersion": "16.5", "DeviceName": "Stale iPhone"}

    async def fake_create(serial=None, autopair=True):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionResetError("Connection terminated")
        return fake_lockdown

    deletes: list[str] = []

    async def fake_delete_sys(udid):
        deletes.append(f"sys:{udid}")
        return True

    def fake_delete_local(udid):
        deletes.append(f"local:{udid}")
        return True

    monkeypatch.setattr("pymobiledevice3.usbmux.list_devices", fake_mux_list, raising=False)
    monkeypatch.setattr("pymobiledevice3.lockdown.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": "UDID-STALE"})

    # Body of the response varies slightly depending on the iOS-17+ branch;
    # we only assert what's relevant to recovery.
    assert resp.status_code == 200
    body = resp.json()
    assert body["udid"] == "UDID-STALE"
    assert body.get("stale_cleared") is True
    # Both clear paths fired exactly once during recovery.
    assert "sys:UDID-STALE" in deletes
    assert "local:UDID-STALE" in deletes
    # Exactly two autopair attempts.
    assert attempts["n"] == 2


def test_wifi_repair_does_not_clear_on_pairing_pending(monkeypatch):
    """A PairingDialogResponsePendingError must NOT trigger pair record
    deletion. Response is 500 with `trust_failed` code and the specific
    'tap Trust' message."""
    from fastapi.testclient import TestClient
    from main import app

    raw_dev = MagicMock(serial="UDID-PEND", connection_type="USB")

    async def fake_mux_list():
        return [raw_dev]

    async def fake_create(serial=None, autopair=True):
        raise PairingDialogResponsePendingError()

    deletes: list[str] = []

    async def fake_delete_sys(udid):
        deletes.append(udid)
        return True

    def fake_delete_local(udid):
        deletes.append(udid)
        return True

    monkeypatch.setattr("pymobiledevice3.usbmux.list_devices", fake_mux_list, raising=False)
    monkeypatch.setattr("pymobiledevice3.lockdown.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": "UDID-PEND"})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["code"] == "trust_failed"
    assert detail["stale_cleared"] is False
    assert "請在 iPhone 解鎖畫面" in detail["message"]
    # Critically: NO deletion fired.
    assert deletes == []


def test_wifi_repair_user_denied_message_mentions_reset(monkeypatch):
    """UserDeniedPairingError produces the 'Reset Location & Privacy' message."""
    from fastapi.testclient import TestClient
    from main import app

    raw_dev = MagicMock(serial="UDID-DENY", connection_type="USB")

    async def fake_mux_list():
        return [raw_dev]

    async def fake_create(serial=None, autopair=True):
        raise UserDeniedPairingError()

    monkeypatch.setattr("pymobiledevice3.usbmux.list_devices", fake_mux_list, raising=False)
    monkeypatch.setattr("pymobiledevice3.lockdown.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": "UDID-DENY"})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["code"] == "trust_failed"
    assert "重置位置與隱私權" in detail["message"]


def test_wifi_repair_retry_failure_uses_clearer_message(monkeypatch):
    """When clearing + retry both fail, response uses
    `trust_prompt_unavailable` code with the post-retry humanized message."""
    from fastapi.testclient import TestClient
    from main import app

    raw_dev = MagicMock(serial="UDID-DEAD", connection_type="USB")

    async def fake_mux_list():
        return [raw_dev]

    async def fake_create(serial=None, autopair=True):
        raise ConnectionResetError("still stale")

    async def fake_delete_sys(udid):
        return True

    def fake_delete_local(udid):
        return True

    monkeypatch.setattr("pymobiledevice3.usbmux.list_devices", fake_mux_list, raising=False)
    monkeypatch.setattr("pymobiledevice3.lockdown.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": "UDID-DEAD"})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["code"] == "trust_prompt_unavailable"
    assert detail["stale_cleared"] is True
    assert "已重置配對紀錄" in detail["message"]


def test_wifi_repair_clears_sticky_user_denied_flag(monkeypatch):
    """When the user clicks Re-trust on a previously-denied device, wifi/repair
    must discard the udid from dm.sticky_user_denied BEFORE attempting the
    autopair. Otherwise the watchdog would keep skipping the device even
    after a successful re-pair."""
    from fastapi.testclient import TestClient
    from main import app, app_state

    udid = "UDID-STICKY"
    # Pre-populate the sticky set as if the user had previously tapped Don't Trust.
    app_state.device_manager.sticky_user_denied.add(udid)
    assert udid in app_state.device_manager.sticky_user_denied

    raw_dev = MagicMock(serial=udid, connection_type="USB")

    async def fake_mux_list():
        return [raw_dev]

    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {"ProductVersion": "16.5", "DeviceName": "Re-trusted iPhone"}

    async def fake_create(serial=None, autopair=True):
        return fake_lockdown

    monkeypatch.setattr("pymobiledevice3.usbmux.list_devices", fake_mux_list, raising=False)
    monkeypatch.setattr("pymobiledevice3.lockdown.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": udid})

    assert resp.status_code == 200
    # Most important: the sticky flag is gone, so watchdog will resume normal behavior.
    assert udid not in app_state.device_manager.sticky_user_denied


def test_wifi_repair_trust_failed_reports_stale_cleared_when_retry_raised_non_stale(monkeypatch):
    """If the first autopair raised stale-cert (records cleared) but the
    retry raised UserDeniedPairing (non-stale), the response code is
    trust_failed (correct) and stale_cleared in the detail must be True
    (records WERE cleared, even though the final error is non-stale)."""
    from fastapi.testclient import TestClient
    from main import app

    raw_dev = MagicMock(serial="UDID-CLEARED-THEN-DENIED", connection_type="USB")

    async def fake_mux_list():
        return [raw_dev]

    attempts = {"n": 0}

    async def fake_create(serial=None, autopair=True):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionResetError("Connection terminated")
        raise UserDeniedPairingError()

    async def fake_delete_sys(udid):
        return True

    def fake_delete_local(udid):
        return True

    monkeypatch.setattr("pymobiledevice3.usbmux.list_devices", fake_mux_list, raising=False)
    monkeypatch.setattr("pymobiledevice3.lockdown.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": "UDID-CLEARED-THEN-DENIED"})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    # User-denied → trust_failed (not trust_prompt_unavailable, because it's not a stale-cert retry)
    assert detail["code"] == "trust_failed"
    # But records WERE cleared on the first attempt — telemetry should reflect that
    assert detail["stale_cleared"] is True
    # Message should be the UserDenied one
    assert "重置位置與隱私權" in detail["message"]
    assert attempts["n"] == 2


def test_wifi_repair_clear_persists_to_file(monkeypatch, tmp_path):
    """wifi_repair's sticky clear must go through clear_user_denied so the
    removal survives a restart (file updated, not just in-memory set)."""
    from fastapi.testclient import TestClient
    from main import app, app_state

    udid = "UDID-STICKY-PERSIST"
    dm = app_state.device_manager
    dm.mark_user_denied(udid)  # writes tmp file via the autouse fixture
    import json
    sticky_file = tmp_path / "sticky_denied.json"
    assert udid in json.loads(sticky_file.read_text())

    raw_dev = MagicMock(serial=udid, connection_type="USB")

    async def fake_mux_list():
        return [raw_dev]

    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {"ProductVersion": "16.5", "DeviceName": "P"}

    async def fake_create(serial=None, autopair=True):
        return fake_lockdown

    monkeypatch.setattr("pymobiledevice3.usbmux.list_devices", fake_mux_list, raising=False)
    monkeypatch.setattr("pymobiledevice3.lockdown.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": udid})

    assert resp.status_code == 200
    assert udid not in dm.sticky_user_denied
    assert udid not in json.loads(sticky_file.read_text())
