import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pathlib import Path

from services.tunnel_helper_client import TunnelHelperClient, HelperError


async def _fake_server(sock_path: Path, handler):
    """In-process Unix-socket JSON-RPC server for testing the client."""
    async def on_conn(reader, writer):
        while not reader.at_eof():
            line = await reader.readline()
            if not line:
                break
            req = json.loads(line.decode())
            resp = await handler(req)
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()
        writer.close()
    server = await asyncio.start_unix_server(on_conn, path=str(sock_path))
    return server


@pytest.mark.asyncio
async def test_ping_round_trips(tmp_path):
    sock = tmp_path / "helper.sock"
    status = tmp_path / "helper.status"

    async def handler(req):
        assert req["method"] == "ping"
        return {"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True, "helper_pid": 4242}}

    server = await _fake_server(sock, handler)
    try:
        status.write_text("READY\n")
        client = TunnelHelperClient(sock_path=sock, status_path=status)
        await client.connect(timeout=2.0)
        result = await client.ping()
        assert result == {"ok": True, "helper_pid": 4242}
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_error_response_raises_helper_error(tmp_path):
    sock = tmp_path / "helper.sock"
    status = tmp_path / "helper.status"

    async def handler(req):
        return {
            "jsonrpc": "2.0",
            "id": req["id"],
            "error": {"code": -32001, "message": "TUN allocation failed"},
        }

    server = await _fake_server(sock, handler)
    try:
        status.write_text("READY\n")
        client = TunnelHelperClient(sock_path=sock, status_path=status)
        await client.connect(timeout=2.0)
        with pytest.raises(HelperError) as ei:
            await client.call("open_wifi_tunnel", udid="x", ip="y", port=1)
        assert ei.value.code == -32001
        assert "TUN allocation failed" in str(ei.value)
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_repair_remote_record_round_trip(tmp_path):
    sock = tmp_path / "helper.sock"
    status = tmp_path / "helper.status"

    captured: list = []

    async def handler(req):
        captured.append(req)
        return {
            "jsonrpc": "2.0", "id": req["id"],
            "result": {"status": "ok", "udid": req["params"]["udid"], "record_path": "/x"},
        }

    server = await _fake_server(sock, handler)
    try:
        status.write_text("READY\n")
        client = TunnelHelperClient(sock_path=sock, status_path=status)
        await client.connect(timeout=2.0)
        result = await client.repair_remote_record("ABC-123")
        assert result["status"] == "ok"
        assert result["udid"] == "ABC-123"
        assert captured[0]["method"] == "repair_remote_record"
        assert captured[0]["params"] == {"udid": "ABC-123"}
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


def test_is_connected_false_when_unbound(tmp_path):
    client = TunnelHelperClient(
        sock_path=tmp_path / "nope.sock",
        status_path=tmp_path / "nope.status",
    )
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_is_connected_true_after_connect(tmp_path):
    sock = tmp_path / "helper.sock"
    status = tmp_path / "helper.status"

    async def handler(req):
        return {"jsonrpc": "2.0", "id": req["id"], "result": {}}

    server = await _fake_server(sock, handler)
    try:
        status.write_text("READY\n")
        client = TunnelHelperClient(sock_path=sock, status_path=status)
        assert client.is_connected is False
        await client.connect(timeout=2.0)
        assert client.is_connected is True
        await client.close()
        assert client.is_connected is False
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_connect_timeout_when_status_missing(tmp_path):
    client = TunnelHelperClient(
        sock_path=tmp_path / "nope.sock",
        status_path=tmp_path / "nope.status",
    )
    with pytest.raises(TimeoutError):
        await client.connect(timeout=0.5)


@pytest.mark.asyncio
async def test_call_times_out_and_drops_connection(tmp_path):
    """A half-open helper that never replies must not hang call() forever.
    readline is bounded by read_timeout; on timeout we raise TimeoutError and
    drop the connection so the next caller reconnects instead of deadlocking
    behind the in-flight _lock."""
    sock = tmp_path / "helper.sock"
    status = tmp_path / "helper.status"

    async def on_conn(reader, writer):
        # Read the request but deliberately never write a response.
        await reader.readline()
        await asyncio.sleep(60)  # hang

    server = await asyncio.start_unix_server(on_conn, path=str(sock))
    try:
        status.write_text("READY\n")
        client = TunnelHelperClient(sock_path=sock, status_path=status)
        await client.connect(timeout=2.0)
        assert client.is_connected is True
        with pytest.raises(TimeoutError):
            await client.call("ping", read_timeout=0.2)
        # connection was dropped so a later caller reconnects, not deadlock
        assert client.is_connected is False
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_call_default_read_timeout_constant():
    """RPC_READ_TIMEOUT_S defaults above the helper-side open bound."""
    from services.tunnel_helper_client import RPC_READ_TIMEOUT_S
    assert RPC_READ_TIMEOUT_S >= 30.0


@pytest.mark.asyncio
async def test_timeout_closes_writer_before_nulling(tmp_path):
    """Fix 2: on readline timeout the writer must be closed (best-effort) BEFORE
    _writer/_reader are set to None — otherwise the transport is leaked and
    asyncio emits 'unclosed transport' warnings on GC."""
    close_called = []
    wait_closed_called = []

    fake_writer = MagicMock()
    fake_writer.write = MagicMock()
    fake_writer.drain = AsyncMock()
    fake_writer.close = MagicMock(side_effect=lambda: close_called.append(True))
    fake_writer.wait_closed = AsyncMock(side_effect=lambda: wait_closed_called.append(True))

    fake_reader = MagicMock()
    # readline never completes — simulate by returning a future that never resolves
    hung_future = asyncio.get_event_loop().create_future()

    async def _slow_readline():
        # This will be cancelled by wait_for on timeout
        await hung_future

    fake_reader.readline = _slow_readline

    client = TunnelHelperClient(
        sock_path=tmp_path / "nope.sock",
        status_path=tmp_path / "nope.status",
    )
    # Inject fake connection directly
    client._reader = fake_reader
    client._writer = fake_writer

    with pytest.raises(TimeoutError):
        await client.call("ping", read_timeout=0.05)

    # Writer.close() must have been called to release the fd/transport.
    assert close_called, "writer.close() must be called on timeout (no leaked transport)"
    # Connection must be dropped.
    assert client.is_connected is False

    # Cleanup: cancel the hung future so asyncio doesn't warn about it
    hung_future.cancel()


@pytest.mark.asyncio
async def test_timeout_close_writer_exception_is_swallowed(tmp_path):
    """Fix 2: if writer.close() itself raises (e.g. BrokenPipeError), the
    exception is swallowed — the timeout error must still propagate and the
    connection must still be dropped."""
    fake_writer = MagicMock()
    fake_writer.write = MagicMock()
    fake_writer.drain = AsyncMock()
    fake_writer.close = MagicMock(side_effect=BrokenPipeError("already dead"))
    fake_writer.wait_closed = AsyncMock()

    fake_reader = MagicMock()
    hung_future = asyncio.get_event_loop().create_future()

    async def _slow_readline():
        await hung_future

    fake_reader.readline = _slow_readline

    client = TunnelHelperClient(
        sock_path=tmp_path / "nope.sock",
        status_path=tmp_path / "nope.status",
    )
    client._reader = fake_reader
    client._writer = fake_writer

    # Must still raise TimeoutError, not BrokenPipeError.
    with pytest.raises(TimeoutError):
        await client.call("ping", read_timeout=0.05)

    assert client.is_connected is False
    hung_future.cancel()


@pytest.mark.asyncio
async def test_connect_recovers_from_stale_ready(tmp_path):
    """A stale READY file whose socket is absent must not abort the connect.

    The client should keep polling until the new helper clears the stale
    READY and writes a fresh one backed by a live socket.
    """
    sock = tmp_path / "helper.sock"
    status = tmp_path / "helper.status"

    async def handler(req):
        return {"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True, "helper_pid": 99}}

    # Write a READY file with NO socket behind it (simulates unclean previous exit).
    status.write_text("READY\n")

    client = TunnelHelperClient(sock_path=sock, status_path=status)

    # After a short delay the "new helper" starts: it clears the stale READY,
    # binds the socket, then writes a fresh READY.
    async def _delayed_start():
        await asyncio.sleep(0.3)
        status.unlink(missing_ok=True)          # helper clears stale status
        server = await _fake_server(sock, handler)
        await asyncio.sleep(0.05)               # brief bind window
        status.write_text("READY\n")            # helper publishes fresh READY
        return server

    start_task = asyncio.create_task(_delayed_start())
    await client.connect(timeout=3.0)
    server = await start_task

    try:
        result = await client.ping()
        assert result == {"ok": True, "helper_pid": 99}
    finally:
        await client.close()
        server.close()
        await server.wait_closed()
