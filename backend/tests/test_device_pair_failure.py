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
    """device_manager reads DEVICE_NAMES_FILE and STICKY_DENIED_FILE — keep
    both isolated per test so no host state leaks in or out."""
    fake = tmp_path / "device_names.json"
    monkeypatch.setattr("core.device_manager.DEVICE_NAMES_FILE", fake)
    monkeypatch.setattr(
        "core.device_manager.STICKY_DENIED_FILE", tmp_path / "sticky_denied.json"
    )
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


# ---------------------------------------------------------------------------
# Task 8: sticky_user_denied + connect() recovery + watchdog gate
# ---------------------------------------------------------------------------

from pymobiledevice3.exceptions import UserDeniedPairingError


def test_device_manager_has_empty_sticky_user_denied_set():
    """DeviceManager must expose an instance-level set for sticky 'don't trust' udids."""
    from core.device_manager import DeviceManager
    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()
    assert hasattr(dm, "sticky_user_denied")
    assert dm.sticky_user_denied == set()


def test_connect_auto_clears_stale_cert_and_retries(monkeypatch):
    """DeviceManager.connect() should use autopair_with_recovery; on a
    stale-cert first failure, the recovery helper clears and retries, and
    connect() proceeds as if the first attempt had succeeded."""
    from core.device_manager import DeviceManager

    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()

    attempts = {"n": 0}
    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {
        "DeviceName": "Stale iPhone",
        "ProductVersion": "16.5",
    }
    fake_lockdown.get_developer_mode_status = AsyncMock(return_value=False)

    async def fake_create(serial=None, autopair=True):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionResetError("Connection terminated")
        return fake_lockdown

    async def fake_delete_sys(udid):
        return True

    def fake_delete_local(udid):
        return True

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local)

    asyncio.run(dm.connect("00008140-STALE"))

    assert attempts["n"] == 2
    assert "00008140-STALE" in dm._connections


def test_connect_marks_user_denied_sticky(monkeypatch):
    """When create_using_usbmux raises UserDeniedPairingError, connect() must
    add the udid to dm.sticky_user_denied and re-raise."""
    from core.device_manager import DeviceManager
    from pymobiledevice3.exceptions import UserDeniedPairingError

    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()

    async def fake_create(serial=None, autopair=True):
        raise UserDeniedPairingError()

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("core.device_manager.create_using_usbmux", fake_create)

    with pytest.raises(UserDeniedPairingError):
        asyncio.run(dm.connect("00008140-DENIED"))

    assert "00008140-DENIED" in dm.sticky_user_denied


def test_watchdog_sticky_gate_predicate():
    """The watchdog's gate condition is `udid in dm.sticky_user_denied`.
    This test pins that predicate so a future refactor that drops the
    gate (or renames the attribute) breaks loudly."""
    from core.device_manager import DeviceManager

    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()

    # Empty set: a fresh udid is NOT skipped.
    assert "FRESH-UDID" not in dm.sticky_user_denied

    # After marking: gate IS true.
    dm.sticky_user_denied.add("DENIED-UDID")
    assert "DENIED-UDID" in dm.sticky_user_denied

    # discard removes the flag (the wifi/repair clear path).
    dm.sticky_user_denied.discard("DENIED-UDID")
    assert "DENIED-UDID" not in dm.sticky_user_denied


def test_sticky_persists_across_manager_instances(tmp_path):
    """mark_user_denied writes the file; a fresh DeviceManager loads it;
    clear_user_denied updates the file."""
    from core.device_manager import DeviceManager

    dm1 = DeviceManager.__new__(DeviceManager)
    dm1.__init__()
    dm1.mark_user_denied("UDID-PERSIST")

    sticky_file = tmp_path / "sticky_denied.json"
    assert sticky_file.exists()
    import json
    assert json.loads(sticky_file.read_text()) == ["UDID-PERSIST"]

    dm2 = DeviceManager.__new__(DeviceManager)
    dm2.__init__()
    assert "UDID-PERSIST" in dm2.sticky_user_denied

    dm2.clear_user_denied("UDID-PERSIST")
    assert json.loads(sticky_file.read_text()) == []

    dm3 = DeviceManager.__new__(DeviceManager)
    dm3.__init__()
    assert dm3.sticky_user_denied == set()


def test_sticky_load_tolerates_missing_or_corrupt_file(tmp_path):
    """No file → empty set. Garbage JSON → empty set. Wrong shape → empty
    set (or string-filtered). Never raises."""
    from core.device_manager import DeviceManager

    # Missing file
    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()
    assert dm.sticky_user_denied == set()

    sticky_file = tmp_path / "sticky_denied.json"

    # Corrupt JSON
    sticky_file.write_text("{not json[")
    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()
    assert dm.sticky_user_denied == set()

    # Wrong shape (dict instead of list)
    sticky_file.write_text('{"udid": true}')
    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()
    assert dm.sticky_user_denied == set()

    # Mixed list — non-strings dropped
    sticky_file.write_text('["GOOD-UDID", 42, null]')
    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()
    assert dm.sticky_user_denied == {"GOOD-UDID"}


def test_connect_user_denied_persists_to_file(monkeypatch, tmp_path):
    """connect()'s UserDenied branch must go through mark_user_denied so
    the sticky flag survives a restart."""
    from core.device_manager import DeviceManager
    from pymobiledevice3.exceptions import UserDeniedPairingError

    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()

    async def fake_create(serial=None, autopair=True):
        raise UserDeniedPairingError()

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)

    with pytest.raises(UserDeniedPairingError):
        asyncio.run(dm.connect("UDID-DENY-PERSIST"))

    import json
    sticky_file = tmp_path / "sticky_denied.json"
    assert sticky_file.exists()
    assert "UDID-DENY-PERSIST" in json.loads(sticky_file.read_text())
