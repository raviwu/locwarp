import asyncio
import json
import os
import pytest
from pathlib import Path

from tunnel_helper_main import HelperServer


@pytest.mark.asyncio
async def test_ping_responds_ok(tmp_path):
    sock = tmp_path / "h.sock"
    status = tmp_path / "h.status"
    server = HelperServer(
        sock_path=sock,
        status_path=status,
        parent_pid=os.getpid(),
        parent_uid=os.getuid(),
    )
    await server.start()
    try:
        assert status.read_text().strip() == "READY"
        reader, writer = await asyncio.open_unix_connection(path=str(sock))
        writer.write(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
        await writer.drain()
        line = await reader.readline()
        resp = json.loads(line.decode())
        assert resp["result"]["ok"] is True
        assert resp["result"]["helper_pid"] == os.getpid()
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_shutdown_closes_server(tmp_path):
    sock = tmp_path / "h.sock"
    status = tmp_path / "h.status"
    server = HelperServer(
        sock_path=sock,
        status_path=status,
        parent_pid=os.getpid(),
        parent_uid=os.getuid(),
    )
    await server.start()
    reader, writer = await asyncio.open_unix_connection(path=str(sock))
    writer.write(b'{"jsonrpc":"2.0","id":1,"method":"shutdown"}\n')
    await writer.drain()
    await reader.readline()  # consume response
    writer.close()
    await writer.wait_closed()
    # The shutdown task drops the listening server within ~100ms
    await asyncio.wait_for(server.wait_stopped(), timeout=2.0)
    assert not sock.exists()
    assert not status.exists()


@pytest.mark.asyncio
async def test_unknown_method_returns_error(tmp_path):
    sock = tmp_path / "h.sock"
    status = tmp_path / "h.status"
    server = HelperServer(
        sock_path=sock,
        status_path=status,
        parent_pid=os.getpid(),
        parent_uid=os.getuid(),
    )
    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(path=str(sock))
        writer.write(b'{"jsonrpc":"2.0","id":1,"method":"nope"}\n')
        await writer.drain()
        line = await reader.readline()
        resp = json.loads(line.decode())
        assert resp["error"]["code"] == -32601
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()
