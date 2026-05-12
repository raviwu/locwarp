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


@pytest.mark.asyncio
async def test_open_and_close_wifi_tunnel_via_fake_runner(tmp_path, monkeypatch):
    """The helper's tunnel methods are tested with a fake TunnelRunner
    so we don't need root or a real iPhone."""
    fake_started: list[tuple] = []
    fake_stopped: list[str] = []

    class FakeRunner:
        def __init__(self):
            self.info = None

        async def start(self, udid, ip, port, timeout=20.0):
            fake_started.append((udid, ip, port))
            self.info = {
                "rsd_address": "fd7d::1",
                "rsd_port": 12345,
                "interface": "utun9",
                "protocol": "quic",
            }
            return dict(self.info)

        async def stop(self):
            fake_stopped.append("called")
            self.info = None

    monkeypatch.setattr("tunnel_helper_main._TunnelRunner", FakeRunner)

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

        async def rpc(method, **params):
            req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            writer.write((json.dumps(req) + "\n").encode())
            await writer.drain()
            return json.loads((await reader.readline()).decode())

        r1 = await rpc("open_wifi_tunnel", udid="abc", ip="192.168.1.10", port=49152)
        assert r1["result"]["rsd_address"] == "fd7d::1"
        assert fake_started == [("abc", "192.168.1.10", 49152)]

        r2 = await rpc("list_tunnels")
        assert r2["result"] == [
            {"udid": "abc", "rsd_address": "fd7d::1", "rsd_port": 12345, "interface": "utun9"}
        ]

        r3 = await rpc("open_wifi_tunnel", udid="abc", ip="192.168.1.10", port=49152)
        assert r3["error"]["code"] == -32003  # already exists

        r4 = await rpc("close_tunnel", udid="abc")
        assert r4["result"] == {"closed": True}
        assert fake_stopped == ["called"]

        r5 = await rpc("close_tunnel", udid="missing")
        assert r5["error"]["code"] == -32004

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()
