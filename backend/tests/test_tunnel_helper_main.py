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


@pytest.mark.asyncio
async def test_repair_remote_record_invokes_handshake(tmp_path, monkeypatch):
    """The new ``repair_remote_record`` RPC routes through
    ``run_repair_handshake``, passes the helper's ``parent_uid``, and does
    NOT register a tunnel — repair is a one-shot side-effect call.
    """
    captured: dict = {}

    async def fake_handshake(udid: str, parent_uid: int) -> dict:
        captured["udid"] = udid
        captured["parent_uid"] = parent_uid
        return {"status": "ok", "udid": udid, "record_path": "/fake/path"}

    monkeypatch.setattr("tunnel_helper_main._run_repair_handshake", fake_handshake)

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
        req = {
            "jsonrpc": "2.0", "id": 1,
            "method": "repair_remote_record",
            "params": {"udid": "abc-123"},
        }
        writer.write((json.dumps(req) + "\n").encode())
        await writer.drain()
        resp = json.loads((await reader.readline()).decode())
        assert resp["result"]["status"] == "ok"
        assert resp["result"]["udid"] == "abc-123"
        assert captured == {"udid": "abc-123", "parent_uid": os.getuid()}
        # Crucially: the transient handshake must not leak into the persistent
        # tunnel registry.
        assert server._tunnels == {}
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_repair_remote_record_rejects_bad_params(tmp_path, monkeypatch):
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
        req = {
            "jsonrpc": "2.0", "id": 1,
            "method": "repair_remote_record",
            "params": {"udid": 123},  # wrong type
        }
        writer.write((json.dumps(req) + "\n").encode())
        await writer.drain()
        resp = json.loads((await reader.readline()).decode())
        assert resp["error"]["code"] == -32602
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_repair_remote_record_propagates_handshake_failure(tmp_path, monkeypatch):
    async def fake_handshake(udid: str, parent_uid: int) -> dict:
        raise RuntimeError("Failed to create any utun interface")

    monkeypatch.setattr("tunnel_helper_main._run_repair_handshake", fake_handshake)

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
        req = {
            "jsonrpc": "2.0", "id": 1,
            "method": "repair_remote_record",
            "params": {"udid": "abc"},
        }
        writer.write((json.dumps(req) + "\n").encode())
        await writer.drain()
        resp = json.loads((await reader.readline()).decode())
        assert resp["error"]["code"] == -32002
        assert "utun" in resp["error"]["message"]
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_open_usb_tunnel_uses_usb_runner(tmp_path, monkeypatch):
    fake_started: list[str] = []

    class FakeUsbRunner:
        def __init__(self):
            self.info = None

        async def start(self, udid, timeout=20.0):
            fake_started.append(udid)
            self.info = {
                "rsd_address": "fd7d::2",
                "rsd_port": 22222,
                "interface": "utun4",
                "protocol": "quic",
            }
            return dict(self.info)

        async def stop(self):
            self.info = None

    monkeypatch.setattr("tunnel_helper_main._UsbTunnelRunner", FakeUsbRunner)

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
        req = {"jsonrpc": "2.0", "id": 1, "method": "open_usb_tunnel", "params": {"udid": "abc"}}
        writer.write((json.dumps(req) + "\n").encode())
        await writer.drain()
        resp = json.loads((await reader.readline()).decode())
        assert resp["result"]["rsd_address"] == "fd7d::2"
        assert fake_started == ["abc"]
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()
