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
