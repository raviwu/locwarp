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
