"""Async Unix-socket JSON-RPC client to the LocWarp tunnel helper.

The helper is a separate process running as root that owns the
``/dev/utunN`` device and the ``pymobiledevice3`` tunnel context. The
backend (running as the regular user) calls into it through this
client to open, close, and list tunnels, and to perform the one-shot
ownership migration of ``~/.locwarp/`` state files.

The wire protocol is newline-delimited JSON-RPC 2.0:

    {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}\n
    {"jsonrpc": "2.0", "id": 1, "result": {"ok": true, ...}}\n

A single connection is held for the process lifetime. Calls are
serialised through an asyncio lock — the helper supports one in-flight
RPC per connection, which is sufficient because the backend only issues
helper calls during device connect/disconnect, never on the hot path.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_SOCK_PATH = Path("/tmp/locwarp-helper.sock")
DEFAULT_STATUS_PATH = Path("/tmp/locwarp-helper.status")


class HelperError(Exception):
    """JSON-RPC error returned by the helper."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"helper error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class TunnelHelperClient:
    def __init__(
        self,
        sock_path: Path = DEFAULT_SOCK_PATH,
        status_path: Path = DEFAULT_STATUS_PATH,
    ) -> None:
        self.sock_path = Path(sock_path)
        self.status_path = Path(status_path)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._next_id = 0
        self._lock = asyncio.Lock()

    async def connect(self, timeout: float = 90.0) -> None:
        """Wait for the helper to publish its READY status, then connect.

        The helper writes ``READY\n`` to ``status_path`` only AFTER it
        has bound the socket and chmod'd it for the user. So once the
        status file is visible we can connect without further polling.

        The default timeout is generous (90s) because on macOS the
        privileged helper launch can include a noticeable
        ``osascript`` admin prompt + ``sudo`` bootstrap delay before
        the helper starts writing its status file. Callers that need
        a tighter bound (e.g. tests) should override explicitly.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        ready = False
        while loop.time() < deadline:
            if self.status_path.exists():
                try:
                    if self.status_path.read_text().strip() == "READY":
                        ready = True
                        break
                except OSError:
                    pass  # transient — keep polling
            await asyncio.sleep(0.2)
        if not ready:
            raise TimeoutError(
                f"helper did not become ready at {self.status_path} within {timeout}s"
            )
        self._reader, self._writer = await asyncio.open_unix_connection(
            path=str(self.sock_path)
        )
        logger.info("connected to tunnel helper at %s", self.sock_path)

    @property
    def is_connected(self) -> bool:
        return self._writer is not None and self._reader is not None

    async def close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (OSError, BrokenPipeError, ConnectionError) as exc:
                logger.debug("error closing helper writer: %s", exc)
            self._writer = None
            self._reader = None

    async def call(self, method: str, **params: Any) -> Any:
        if self._writer is None or self._reader is None:
            raise RuntimeError("helper client is not connected")
        async with self._lock:
            self._next_id += 1
            req = {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": method,
                "params": params,
            }
            self._writer.write((json.dumps(req) + "\n").encode("utf-8"))
            await self._writer.drain()

            line = await self._reader.readline()
            if not line:
                raise RuntimeError("helper closed the connection")
            resp = json.loads(line.decode("utf-8"))
            if "error" in resp:
                err = resp["error"]
                raise HelperError(
                    code=err.get("code", -32000),
                    message=err.get("message", "unknown helper error"),
                    data=err.get("data"),
                )
            if "result" not in resp:
                raise RuntimeError(
                    f"helper response has neither result nor error: {resp!r}"
                )
            return resp["result"]

    # ── Typed convenience wrappers ─────────────────────────────────

    async def ping(self) -> dict:
        return await self.call("ping")

    async def shutdown(self) -> dict:
        return await self.call("shutdown")

    async def migrate_user_state(self, home: str, uid: int, gid: int) -> dict:
        return await self.call("migrate_user_state", home=home, uid=uid, gid=gid)

    async def open_wifi_tunnel(self, udid: str, ip: str, port: int) -> dict:
        return await self.call("open_wifi_tunnel", udid=udid, ip=ip, port=port)

    async def open_usb_tunnel(self, udid: str) -> dict:
        return await self.call("open_usb_tunnel", udid=udid)

    async def close_tunnel(self, udid: str) -> dict:
        return await self.call("close_tunnel", udid=udid)

    async def list_tunnels(self) -> list[dict]:
        return await self.call("list_tunnels")

    async def repair_remote_record(self, udid: str) -> dict:
        return await self.call("repair_remote_record", udid=udid)
