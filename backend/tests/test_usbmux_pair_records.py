"""Tests for backend/services/usbmux_pair_records.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_delete_system_pair_record_sends_correct_plist(monkeypatch):
    """The wrapper must send a {MessageType: DeletePairRecord, PairRecordID: udid}
    plist message to usbmuxd via PlistMuxConnection."""
    from services.usbmux_pair_records import delete_system_pair_record

    sent_messages: list[dict] = []

    fake_conn = MagicMock()
    fake_conn._send = AsyncMock(side_effect=lambda msg: sent_messages.append(msg))
    fake_conn._receive = AsyncMock(return_value={"MessageType": "Result", "Number": 0})
    fake_conn._tag = 1
    fake_conn.close = MagicMock()

    async def fake_create_socket():
        return MagicMock()

    fake_plistmux_class = MagicMock()
    fake_plistmux_class.create_usbmux_socket = fake_create_socket
    fake_plistmux_class.return_value = fake_conn

    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection",
        fake_plistmux_class,
    )

    ok = await delete_system_pair_record("00008140-DEADBEEF")

    assert ok is True
    assert len(sent_messages) == 1
    assert sent_messages[0]["MessageType"] == "DeletePairRecord"
    assert sent_messages[0]["PairRecordID"] == "00008140-DEADBEEF"


@pytest.mark.asyncio
async def test_delete_system_pair_record_idempotent_on_missing(monkeypatch):
    """usbmuxd Number=2 means 'no such record' — treat as success (idempotent)."""
    from services.usbmux_pair_records import delete_system_pair_record

    fake_conn = MagicMock()
    fake_conn._send = AsyncMock()
    fake_conn._receive = AsyncMock(return_value={"MessageType": "Result", "Number": 2})
    fake_conn._tag = 1
    fake_conn.close = MagicMock()

    async def fake_create_socket():
        return MagicMock()

    fake_plistmux_class = MagicMock()
    fake_plistmux_class.create_usbmux_socket = fake_create_socket
    fake_plistmux_class.return_value = fake_conn

    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection",
        fake_plistmux_class,
    )

    ok = await delete_system_pair_record("UDID-MISSING")
    assert ok is True


@pytest.mark.asyncio
async def test_delete_system_pair_record_returns_false_on_unexpected_number(monkeypatch):
    """Any Number not in {0, 2} signals an unexpected usbmuxd error.
    Function returns False but does not raise."""
    from services.usbmux_pair_records import delete_system_pair_record

    fake_conn = MagicMock()
    fake_conn._send = AsyncMock()
    fake_conn._receive = AsyncMock(return_value={"MessageType": "Result", "Number": 5})
    fake_conn._tag = 1
    fake_conn.close = MagicMock()

    async def fake_create_socket():
        return MagicMock()

    fake_plistmux_class = MagicMock()
    fake_plistmux_class.create_usbmux_socket = fake_create_socket
    fake_plistmux_class.return_value = fake_conn

    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection",
        fake_plistmux_class,
    )

    ok = await delete_system_pair_record("UDID-X")
    assert ok is False


@pytest.mark.asyncio
async def test_delete_system_pair_record_does_not_raise_on_socket_failure(monkeypatch):
    """If create_usbmux_socket itself raises (usbmuxd down), we log and return False."""
    from services.usbmux_pair_records import delete_system_pair_record

    async def boom():
        raise ConnectionRefusedError("usbmuxd not running")

    fake_plistmux_class = MagicMock()
    fake_plistmux_class.create_usbmux_socket = boom

    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection",
        fake_plistmux_class,
    )

    ok = await delete_system_pair_record("UDID-Y")
    assert ok is False


@pytest.mark.asyncio
async def test_delete_system_pair_record_does_not_raise_on_send_receive_failure(monkeypatch):
    """If _send or _receive raises, the function must return False — never bubble."""
    from services.usbmux_pair_records import delete_system_pair_record

    fake_conn = MagicMock()
    fake_conn._send = AsyncMock(side_effect=RuntimeError("socket dropped mid-write"))
    fake_conn._receive = AsyncMock(return_value={"MessageType": "Result", "Number": 0})
    fake_conn._tag = 1
    fake_conn.close = MagicMock()

    async def fake_create_socket():
        return MagicMock()

    fake_plistmux_class = MagicMock()
    fake_plistmux_class.create_usbmux_socket = fake_create_socket
    fake_plistmux_class.return_value = fake_conn

    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection",
        fake_plistmux_class,
    )

    ok = await delete_system_pair_record("UDID-Z")
    assert ok is False
    fake_conn.close.assert_called_once()  # finally must still close


@pytest.mark.asyncio
async def test_delete_system_pair_record_swallows_close_failure(monkeypatch):
    """If conn.close() itself raises, the function must still return the
    outcome from the send/receive step — close failure is non-fatal."""
    from services.usbmux_pair_records import delete_system_pair_record

    fake_conn = MagicMock()
    fake_conn._send = AsyncMock()
    fake_conn._receive = AsyncMock(return_value={"MessageType": "Result", "Number": 0})
    fake_conn._tag = 1
    fake_conn.close = MagicMock(side_effect=OSError("close blew up"))

    async def fake_create_socket():
        return MagicMock()

    fake_plistmux_class = MagicMock()
    fake_plistmux_class.create_usbmux_socket = fake_create_socket
    fake_plistmux_class.return_value = fake_conn

    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection",
        fake_plistmux_class,
    )

    ok = await delete_system_pair_record("UDID-CLOSE-FAIL")
    assert ok is True  # send/receive succeeded; close failure shouldn't override


from pathlib import Path


def test_delete_local_pair_record_removes_existing_file(tmp_path, monkeypatch):
    """If the local file exists, delete it and return True."""
    from services.usbmux_pair_records import delete_local_pair_record

    fake_home = tmp_path / "pmd3"
    fake_home.mkdir()
    target = fake_home / "00008140-DEADBEEF.plist"
    target.write_bytes(b"<plist><dict/></plist>")

    monkeypatch.setattr(
        "services.usbmux_pair_records._local_pair_record_dir",
        lambda: fake_home,
    )

    ok = delete_local_pair_record("00008140-DEADBEEF")
    assert ok is True
    assert not target.exists()


def test_delete_local_pair_record_idempotent_on_missing(tmp_path, monkeypatch):
    """If the file does not exist, still return True (idempotent)."""
    from services.usbmux_pair_records import delete_local_pair_record

    fake_home = tmp_path / "pmd3"
    fake_home.mkdir()

    monkeypatch.setattr(
        "services.usbmux_pair_records._local_pair_record_dir",
        lambda: fake_home,
    )

    ok = delete_local_pair_record("UDID-NEVER-EXISTED")
    assert ok is True


def test_delete_local_pair_record_does_not_raise_on_permission_error(tmp_path, monkeypatch):
    """Permission error during unlink is logged and returns False, never raises."""
    from services.usbmux_pair_records import delete_local_pair_record

    fake_home = tmp_path / "pmd3"
    fake_home.mkdir()
    target = fake_home / "UDID-LOCKED.plist"
    target.write_bytes(b"data")

    monkeypatch.setattr(
        "services.usbmux_pair_records._local_pair_record_dir",
        lambda: fake_home,
    )

    def boom(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "unlink", boom)

    ok = delete_local_pair_record("UDID-LOCKED")
    assert ok is False


import ssl

from pymobiledevice3.exceptions import (
    ConnectionTerminatedError,
    PairingDialogResponsePendingError,
    UserDeniedPairingError,
)


@pytest.mark.parametrize(
    "exc, expected",
    [
        # Stale-cert whitelist — these signal "host has a record but iPhone
        # has forgotten this Mac" so we should clear and retry.
        (ConnectionTerminatedError(), True),
        (ConnectionResetError("Connection reset by peer"), True),
        (BrokenPipeError(), True),
        (EOFError(), True),
        (ssl.SSLError("handshake failed"), True),
        (ssl.SSLEOFError("EOF during handshake"), True),
        # Deliberately excluded — these are NOT stale cert.
        (ConnectionAbortedError("ECONNABORTED"), False),  # USB unplug mid-flow
        (PairingDialogResponsePendingError(), False),     # user hasn't tapped Trust yet
        (UserDeniedPairingError(), False),                # user tapped Don't Trust
        (RuntimeError("something else"), False),
        (ValueError("nope"), False),
    ],
)
def test_is_stale_cert_error_table(exc, expected):
    from services.usbmux_pair_records import _is_stale_cert_error
    assert _is_stale_cert_error(exc) is expected


def test_is_stale_cert_error_name_based_fallback():
    """A re-wrapped exception whose class name contains a known signal
    must still classify as stale-cert."""
    from services.usbmux_pair_records import _is_stale_cert_error

    class _SomeWrappedConnectionTerminatedError(Exception):
        pass

    class _CustomSSLError(Exception):
        pass

    assert _is_stale_cert_error(_SomeWrappedConnectionTerminatedError()) is True
    assert _is_stale_cert_error(_CustomSSLError()) is True


@pytest.mark.asyncio
async def test_acquire_pair_lock_same_udid_returns_same_lock():
    """Two acquires for the same udid must return the SAME Lock instance —
    otherwise concurrent callers won't serialize."""
    from services.usbmux_pair_records import acquire_pair_lock, _pair_locks

    # Isolate test from any module-level state set by earlier tests.
    _pair_locks.clear()

    lock1 = await acquire_pair_lock("UDID-A")
    lock2 = await acquire_pair_lock("UDID-A")
    assert lock1 is lock2


@pytest.mark.asyncio
async def test_acquire_pair_lock_different_udids_return_distinct_locks():
    """Locks must be per-udid — A's lock must not block B."""
    from services.usbmux_pair_records import acquire_pair_lock, _pair_locks
    _pair_locks.clear()

    lock_a = await acquire_pair_lock("UDID-A")
    lock_b = await acquire_pair_lock("UDID-B")
    assert lock_a is not lock_b


@pytest.mark.timeout(10)
@pytest.mark.asyncio
async def test_pair_lock_serializes_concurrent_acquires_for_same_udid():
    """When two coroutines hold the same udid's lock, the second waits."""
    from services.usbmux_pair_records import acquire_pair_lock, _pair_locks
    _pair_locks.clear()

    order: list[str] = []
    release_first = asyncio.Event()

    async def first():
        lock = await acquire_pair_lock("UDID-S")
        async with lock:
            order.append("first-in")
            await release_first.wait()
            order.append("first-out")

    async def second():
        # Yield once so `first` enters its lock first.
        await asyncio.sleep(0)
        lock = await acquire_pair_lock("UDID-S")
        async with lock:
            order.append("second-in")

    task_first = asyncio.create_task(first())
    task_second = asyncio.create_task(second())
    await asyncio.sleep(0.05)  # let both reach steady state
    # At this point first is in, second is waiting
    assert order == ["first-in"]
    release_first.set()
    await asyncio.gather(task_first, task_second)
    assert order == ["first-in", "first-out", "second-in"]


@pytest.mark.asyncio
async def test_autopair_with_recovery_passes_through_on_success(monkeypatch):
    """When autopair succeeds first try, no clearing happens, stale_cleared=False."""
    from services.usbmux_pair_records import autopair_with_recovery, _pair_locks
    _pair_locks.clear()

    fake_lockdown = MagicMock(name="lockdown")
    calls: list[str] = []

    async def fake_create(serial=None, autopair=True):
        calls.append(f"create({serial}, autopair={autopair})")
        return fake_lockdown

    async def fake_delete_sys(udid):
        calls.append(f"delete_sys({udid})")
        return True

    def fake_delete_local(udid):
        calls.append(f"delete_local({udid})")
        return True

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local)

    lockdown, stale_cleared = await autopair_with_recovery("UDID-OK")
    assert lockdown is fake_lockdown
    assert stale_cleared is False
    assert calls == ["create(UDID-OK, autopair=True)"]  # no deletes ran


@pytest.mark.asyncio
async def test_autopair_with_recovery_clears_then_retries_on_stale_cert(monkeypatch):
    """Stale-cert exception triggers delete_system + delete_local + retry.
    Returns (lockdown, stale_cleared=True) when the retry succeeds."""
    from services.usbmux_pair_records import autopair_with_recovery, _pair_locks
    _pair_locks.clear()

    fake_lockdown = MagicMock(name="lockdown")
    attempts = {"n": 0}
    calls: list[str] = []

    async def fake_create(serial=None, autopair=True):
        attempts["n"] += 1
        calls.append(f"create#{attempts['n']}({serial})")
        if attempts["n"] == 1:
            raise ConnectionResetError("Connection terminated")
        return fake_lockdown

    async def fake_delete_sys(udid):
        calls.append(f"delete_sys({udid})")
        return True

    def fake_delete_local(udid):
        calls.append(f"delete_local({udid})")
        return True

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local)

    lockdown, stale_cleared = await autopair_with_recovery("UDID-STALE")
    assert lockdown is fake_lockdown
    assert stale_cleared is True
    assert calls == [
        "create#1(UDID-STALE)",
        "delete_sys(UDID-STALE)",
        "delete_local(UDID-STALE)",
        "create#2(UDID-STALE)",
    ]


@pytest.mark.asyncio
async def test_autopair_with_recovery_does_not_clear_on_non_stale_exception(monkeypatch):
    """A non-stale exception (e.g. user hasn't tapped Trust yet) must NOT
    trigger pair record deletion. It propagates unchanged."""
    from services.usbmux_pair_records import autopair_with_recovery, _pair_locks
    from pymobiledevice3.exceptions import PairingDialogResponsePendingError
    _pair_locks.clear()

    calls: list[str] = []

    async def fake_create(serial=None, autopair=True):
        calls.append("create")
        raise PairingDialogResponsePendingError()

    async def fake_delete_sys(udid):
        calls.append("delete_sys")
        return True

    def fake_delete_local(udid):
        calls.append("delete_local")
        return True

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local)

    with pytest.raises(PairingDialogResponsePendingError):
        await autopair_with_recovery("UDID-PENDING")
    assert calls == ["create"]


@pytest.mark.asyncio
async def test_autopair_with_recovery_propagates_retry_failure(monkeypatch):
    """If both attempts fail (still stale-cert), propagate the LATEST exception."""
    from services.usbmux_pair_records import autopair_with_recovery, _pair_locks
    _pair_locks.clear()

    attempts = {"n": 0}

    async def fake_create(serial=None, autopair=True):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionResetError("first fail")
        raise EOFError("second fail (different exception type, still stale)")

    async def fake_delete_sys(udid):
        return True

    def fake_delete_local(udid):
        return True

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local)

    with pytest.raises(EOFError, match="second fail"):
        await autopair_with_recovery("UDID-DEAD")


@pytest.mark.asyncio
async def test_autopair_with_recovery_serializes_concurrent_calls_for_same_udid(monkeypatch):
    """Two concurrent autopair_with_recovery calls for the same udid must
    serialize via the per-udid lock — at most one create() is in flight
    at a time."""
    from services.usbmux_pair_records import autopair_with_recovery, _pair_locks
    _pair_locks.clear()

    fake_lockdown = MagicMock()
    in_flight = {"n": 0}
    max_seen = {"n": 0}

    async def fake_create_serial(serial=None, autopair=True):
        in_flight["n"] += 1
        max_seen["n"] = max(max_seen["n"], in_flight["n"])
        await asyncio.sleep(0.02)  # let any concurrent call try to enter
        in_flight["n"] -= 1
        return fake_lockdown

    async def fake_delete_sys(udid):
        return True

    def fake_delete_local(udid):
        return True

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create_serial)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local)

    async def call_one():
        await autopair_with_recovery("UDID-RACE")

    async def call_two():
        await asyncio.sleep(0)  # ensure call1 enters lock first
        await autopair_with_recovery("UDID-RACE")

    await asyncio.gather(call_one(), call_two())
    assert max_seen["n"] == 1, "lock did not serialize — both calls ran concurrently"
