"""Tests for surfacing devices that fail USB lockdown pair validation."""

import pytest

from core.device_manager import _classify_pair_error


class _FakePairingPending(Exception):
    """Stand-in for pymobiledevice3.exceptions.PairingDialogResponsePendingError."""


class _FakeNotPaired(Exception):
    """Stand-in for pymobiledevice3.exceptions.PairingError ('not paired')."""


class _FakeNotPairedNoMsg(Exception):
    """Stand-in for pymobiledevice3.exceptions.NotPairedError() raised with no args."""


class _FakeUserDeniedPairing(Exception):
    """Stand-in for pymobiledevice3.exceptions.UserDeniedPairingError."""


class _FakeInvalidHostID(Exception):
    """Stand-in for pymobiledevice3.exceptions.InvalidHostIDError."""


@pytest.mark.parametrize(
    "exc,expected_status,expected_substring",
    [
        # ConnectionTerminatedError is the most common signal for a stale
        # pair record (iPhone has forgotten this host). Mapped to "trust_required".
        (ConnectionResetError("Connection terminated"), "trust_required", "重新信任"),
        # PairingDialogResponsePending: user hasn't tapped Trust yet.
        (_FakePairingPending("PairingDialogResponsePending"), "trust_required", "信任"),
        # "not paired" text from PairingError variants.
        (_FakeNotPaired("device is not paired with this host"), "trust_required", "USB"),
        # Anything else falls through to "error" with the raw message.
        (RuntimeError("unexpected backend explosion"), "error", "unexpected backend explosion"),
        # Empty-message NotPairedError — must match by class name, not text
        (_FakeNotPairedNoMsg(), "trust_required", "配對"),
        # User explicitly tapped "Don't Trust" — re-trust will re-prompt them
        (_FakeUserDeniedPairing(), "trust_required", "配對"),
        # Host ID mismatch — pair record on device side doesn't recognize this Mac
        (_FakeInvalidHostID(), "trust_required", "配對"),
    ],
)
def test_classify_pair_error_maps_known_signals(exc, expected_status, expected_substring):
    status, message = _classify_pair_error(exc)
    assert status == expected_status
    assert expected_substring in message


def test_classify_pair_error_trims_long_message():
    long = "x" * 500
    status, message = _classify_pair_error(RuntimeError(long))
    assert status == "error"
    assert len(message) <= 200


import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.device_manager import DeviceManager


def _make_dm() -> DeviceManager:
    """Build a DeviceManager without touching real iOS hardware."""
    dm = DeviceManager.__new__(DeviceManager)
    dm._connections = {}
    dm._lock = MagicMock()
    return dm


def _raw_mux(serial: str, connection_type: str = "USB"):
    raw = MagicMock()
    raw.serial = serial
    raw.connection_type = connection_type
    return raw


@pytest.fixture(autouse=True)
def isolated_device_cache(tmp_path, monkeypatch):
    """device_manager._load_device_name_cache reads DEVICE_NAMES_FILE — keep
    that file isolated per test so no host state leaks in."""
    fake = tmp_path / "device_names.json"
    monkeypatch.setattr("core.device_manager.DEVICE_NAMES_FILE", fake)
    yield


def test_discover_surfaces_pair_failed_device(monkeypatch):
    """A USB device whose create_using_usbmux raises should still appear
    in the returned list — with pair_status set, not silently dropped."""
    raw = _raw_mux("00008140-DEADBEEF")

    async def _fake_list_devices():
        return [raw]

    async def _exploding_lockdown(serial):
        raise ConnectionResetError("Connection terminated")

    monkeypatch.setattr("core.device_manager.list_devices", _fake_list_devices)
    monkeypatch.setattr("core.device_manager.create_using_usbmux", _exploding_lockdown)

    dm = _make_dm()
    devices = asyncio.run(dm.discover_devices())

    assert len(devices) == 1
    info = devices[0]
    assert info.udid == "00008140-DEADBEEF"
    assert info.pair_status == "trust_required"
    assert "重新信任" in info.pair_error
    assert info.is_connected is False


def test_discover_mixes_healthy_and_failed(monkeypatch):
    """Two devices: one passes lockdown, one explodes. Both must surface."""
    healthy = _raw_mux("00008110-GOOD")
    broken = _raw_mux("00008140-BAD")

    async def _fake_list_devices():
        return [healthy, broken]

    healthy_lockdown = MagicMock()
    healthy_lockdown.all_values = {
        "DeviceName": "Healthy iPhone",
        "ProductVersion": "17.5",
    }
    healthy_lockdown.get_developer_mode_status = AsyncMock(return_value=True)

    async def _conditional_lockdown(serial):
        if serial == "00008110-GOOD":
            return healthy_lockdown
        raise ConnectionResetError("Connection terminated")

    monkeypatch.setattr("core.device_manager.list_devices", _fake_list_devices)
    monkeypatch.setattr("core.device_manager.create_using_usbmux", _conditional_lockdown)

    dm = _make_dm()
    devices = asyncio.run(dm.discover_devices())

    assert len(devices) == 2
    by_udid = {d.udid: d for d in devices}

    assert by_udid["00008110-GOOD"].pair_status == "ok"
    assert by_udid["00008110-GOOD"].name == "Healthy iPhone"
    assert by_udid["00008110-GOOD"].pair_error is None

    assert by_udid["00008140-BAD"].pair_status == "trust_required"
    assert by_udid["00008140-BAD"].name == "iPhone"  # cache miss → generic fallback
    assert by_udid["00008140-BAD"].pair_error is not None


def test_discover_uses_cached_name_for_failed_device(monkeypatch, tmp_path):
    """When a previously-paired device fails this round, surface the cached
    DeviceName instead of the generic 'iPhone' fallback so the user knows
    which physical phone is in trouble."""
    import json
    (tmp_path / "device_names.json").write_text(
        json.dumps({"00008140-BAD": "Ravi's iPhone"})
    )

    raw = _raw_mux("00008140-BAD")

    async def _fake_list_devices():
        return [raw]

    async def _exploding_lockdown(serial):
        raise ConnectionResetError("Connection terminated")

    monkeypatch.setattr("core.device_manager.list_devices", _fake_list_devices)
    monkeypatch.setattr("core.device_manager.create_using_usbmux", _exploding_lockdown)

    dm = _make_dm()
    devices = asyncio.run(dm.discover_devices())

    assert len(devices) == 1
    assert devices[0].name == "Ravi's iPhone"


def test_discover_surfaces_failure_after_lockdown_open(monkeypatch):
    """When create_using_usbmux succeeds but a follow-up call raises, the
    device should still surface — and pair_error should reflect the REAL
    exception, not a synthetic placeholder string."""
    raw = _raw_mux("00008140-LATE-FAIL")

    async def _fake_list_devices():
        return [raw]

    # all_values is a property that throws when read — simulates a lockdown
    # that opened but is now half-dead.
    class _BadLockdown:
        @property
        def all_values(self):
            raise ConnectionResetError("Connection terminated after handshake")

        async def close(self):
            pass

    async def _open_lockdown(serial):
        return _BadLockdown()

    monkeypatch.setattr("core.device_manager.list_devices", _fake_list_devices)
    monkeypatch.setattr("core.device_manager.create_using_usbmux", _open_lockdown)

    dm = _make_dm()
    devices = asyncio.run(dm.discover_devices())

    assert len(devices) == 1
    info = devices[0]
    assert info.udid == "00008140-LATE-FAIL"
    # Real ConnectionResetError reached the classifier → trust_required.
    # If the synthetic RuntimeError path were still in play this would be "error".
    assert info.pair_status == "trust_required"
    assert "重新信任" in info.pair_error
