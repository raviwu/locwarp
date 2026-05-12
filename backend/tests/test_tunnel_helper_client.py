import asyncio
import json
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
async def test_connect_timeout_when_status_missing(tmp_path):
    client = TunnelHelperClient(
        sock_path=tmp_path / "nope.sock",
        status_path=tmp_path / "nope.status",
    )
    with pytest.raises(TimeoutError):
        await client.connect(timeout=0.5)
