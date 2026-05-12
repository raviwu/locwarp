# Elevated Tunnel Helper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the LocWarp backend so the FastAPI process runs as the regular user (regaining iCloud Drive / clipboard access) and only a small `--tunnel-helper` subprocess runs as root to own `/dev/utunN` and the `pymobiledevice3` QUIC tunnel.

**Architecture:** Same `locwarp-backend` PyInstaller binary, two modes selected by the `--tunnel-helper` CLI flag. Backend (user) → JSON-RPC over Unix socket → Helper (root). After helper opens TUN, backend talks to iOS via plain TCP to the kernel-routed RSD IPv6 address. See `docs/plans/2026-05-12-elevated-tunnel-helper.md` for the full design.

**Tech Stack:** Python 3.11 (FastAPI, asyncio, `pymobiledevice3`, `pytun_pmd3`), Electron `main.js` (Node 20), bash dev launcher.

---

## File Structure

**New files (backend):**
- `backend/services/tunnel_helper_client.py` — async Unix-socket JSON-RPC client used from the user-context backend
- `backend/core/_tunnel_runner.py` — original `pymobiledevice3`-using `TunnelRunner` body, helper-only
- `backend/tunnel_helper_main.py` — helper-mode entrypoint: socket bind, RPC dispatch, PID watchdog
- `backend/tests/test_tunnel_helper_client.py`
- `backend/tests/test_tunnel_helper_main.py`
- `backend/tests/test_migrate_user_state.py`

**Modified files (backend):**
- `backend/main.py` — branch on `--tunnel-helper`; otherwise connect helper client at startup, call `migrate_user_state`, route shutdown through helper
- `backend/core/wifi_tunnel.py` — `TunnelRunner` becomes a thin facade calling the helper client; drops `pymobiledevice3.remote.tunnel_service` import
- `backend/core/device_manager.py:_connect_tunnel` — uses helper client for iOS 17+ USB
- `backend/services/cloud_sync.py` — remove chmod-for-root and the `OSError`/`EPERM` workarounds in `setup_sync_folder` and `migrate_bookmarks`
- `backend/locwarp-backend.spec` — verify the helper imports are picked up (one PyInstaller binary; helper mode imports `pymobiledevice3` but so does the existing backend, so no spec change is expected)

**Modified files (frontend / dev):**
- `frontend/electron/main.js` — spawn backend (user) + helper (admin) in parallel; reconcile shutdown
- `start.sh` — drop `exec sudo`; run user-context launcher
- `start.py` — spawn the privileged helper internally (sudo)

**Test conventions:**
- Tests requiring root for fixtures (`chown` of root-owned files, real TUN opens) gate with `@pytest.mark.skipif(os.geteuid() != 0, ...)`.
- The RPC client and the RPC dispatcher are unit-tested against in-process fakes; no root needed.

---

## Task 1: Helper client skeleton (TDD)

**Files:**
- Create: `backend/services/tunnel_helper_client.py`
- Create: `backend/tests/test_tunnel_helper_client.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_tunnel_helper_client.py
import asyncio
import json
import os
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_tunnel_helper_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.tunnel_helper_client'`

- [ ] **Step 3: Implement the client**

```python
# backend/services/tunnel_helper_client.py
"""Async Unix-socket JSON-RPC client to the LocWarp tunnel helper.

The helper is a separate process running as root that owns the
``/dev/utunN`` device and the ``pymobiledevice3`` tunnel context. The
backend (running as the regular user) calls into it through this
client to open, close, and list tunnels, and to perform the one-shot
ownership migration of ``~/.locwarp/`` state files.

The wire protocol is newline-delimited JSON-RPC 2.0:

    {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}\\n
    {"jsonrpc": "2.0", "id": 1, "result": {"ok": true, ...}}\\n

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

    async def connect(self, timeout: float = 30.0) -> None:
        """Wait for the helper to publish its READY status, then connect.

        The helper writes ``READY\\n`` to ``status_path`` only AFTER it
        has bound the socket and chmod'd it for the user. So once the
        status file is visible we can connect without further polling.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self.status_path.exists():
                try:
                    if self.status_path.read_text().strip() == "READY":
                        break
                except OSError:
                    pass  # transient — keep polling
            await asyncio.sleep(0.2)
        else:
            raise TimeoutError(
                f"helper did not become ready at {self.status_path} within {timeout}s"
            )
        self._reader, self._writer = await asyncio.open_unix_connection(
            path=str(self.sock_path)
        )
        logger.info("connected to tunnel helper at %s", self.sock_path)

    async def close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
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
            self._writer.write((json.dumps(req) + "\n").encode())
            await self._writer.drain()

            line = await self._reader.readline()
            if not line:
                raise RuntimeError("helper closed the connection")
            resp = json.loads(line.decode())
            if "error" in resp:
                err = resp["error"]
                raise HelperError(
                    code=err.get("code", -32000),
                    message=err.get("message", "unknown helper error"),
                    data=err.get("data"),
                )
            return resp.get("result")

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_tunnel_helper_client.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/tunnel_helper_client.py backend/tests/test_tunnel_helper_client.py
git commit -m "feat(backend): add tunnel helper IPC client"
```

---

## Task 2: Helper mode entrypoint with `ping`/`shutdown`/`migrate_user_state`

**Files:**
- Create: `backend/tunnel_helper_main.py`
- Create: `backend/tests/test_tunnel_helper_main.py`
- Create: `backend/tests/test_migrate_user_state.py`
- Modify: `backend/main.py` — branch on `--tunnel-helper`

- [ ] **Step 1: Write the failing test for the dispatcher**

```python
# backend/tests/test_tunnel_helper_main.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_tunnel_helper_main.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tunnel_helper_main'`

- [ ] **Step 3: Implement helper main**

```python
# backend/tunnel_helper_main.py
"""LocWarp tunnel helper — runs as root, hosts /dev/utunN and the
pymobiledevice3 tunnel context for the user-context backend.

The helper is the same ``locwarp-backend`` binary invoked with
``--tunnel-helper``. Backend speaks newline-delimited JSON-RPC 2.0
to it over a Unix socket; see ``services/tunnel_helper_client.py``.

Lifecycle:

1. ``run()`` parses CLI flags (``--parent-pid``, ``--parent-uid``).
2. ``HelperServer.start()`` binds the socket, chmod/chgrps it for the
   user, starts accepting, then atomically publishes ``READY\\n`` to
   the status file via tmp-and-rename.
3. A background watchdog polls the parent PID every 5s; if gone, the
   helper closes all tunnels and exits.
4. ``shutdown`` RPC (or signal) tears the server down cleanly.

The tunnel-specific methods (``open_wifi_tunnel``, etc.) are added in
later tasks; this task ships ping/shutdown/migrate_user_state only so
the IPC machinery can be exercised without root.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import grp
import json
import logging
import os
import pwd
import signal
import sys
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger("tunnel_helper")

DEFAULT_SOCK_PATH = Path("/tmp/locwarp-helper.sock")
DEFAULT_STATUS_PATH = Path("/tmp/locwarp-helper.status")
PARENT_POLL_INTERVAL = 5.0


def _rpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _rpc_result(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


class HelperServer:
    def __init__(
        self,
        sock_path: Path,
        status_path: Path,
        parent_pid: int,
        parent_uid: int,
    ) -> None:
        self.sock_path = Path(sock_path)
        self.status_path = Path(status_path)
        self.parent_pid = parent_pid
        self.parent_uid = parent_uid
        self._server: asyncio.AbstractServer | None = None
        self._stopped: asyncio.Event = asyncio.Event()
        self._watchdog: asyncio.Task | None = None
        # Method registry — later tasks add tunnel methods here.
        self._methods: dict[str, Callable[[dict], Awaitable[Any]]] = {
            "ping": self._handle_ping,
            "shutdown": self._handle_shutdown,
            "migrate_user_state": self._handle_migrate_user_state,
        }

    # ── lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        # Clean up any stale socket from a previous unclean exit.
        if self.sock_path.exists():
            try:
                self.sock_path.unlink()
            except OSError:
                pass
        if self.status_path.exists():
            try:
                self.status_path.unlink()
            except OSError:
                pass

        self._server = await asyncio.start_unix_server(
            self._handle_connection, path=str(self.sock_path)
        )
        self._apply_socket_permissions()
        self._publish_ready()
        self._watchdog = asyncio.create_task(self._parent_watchdog())
        logger.info("helper listening on %s (parent pid=%d)", self.sock_path, self.parent_pid)

    def _apply_socket_permissions(self) -> None:
        """Make the socket connectable by the parent user.

        Backend runs as ``parent_uid``; helper runs as root. The socket
        is created mode 0600 root:wheel by default. Relax to 0660 and
        chgrp to the parent's primary group so the backend can
        ``connect()``.
        """
        try:
            pw = pwd.getpwuid(self.parent_uid)
            os.chown(self.sock_path, 0, pw.pw_gid)
            os.chmod(self.sock_path, 0o660)
        except (KeyError, OSError) as exc:
            logger.warning(
                "could not relax socket permissions: %s (backend may fail to connect)",
                exc,
            )

    def _publish_ready(self) -> None:
        """Atomically write ``READY\\n`` to the status file.

        We tmp-and-rename so the file appearing on disk implies a fully
        written ``READY`` marker, never a half-empty file the backend
        might race against.
        """
        tmp = self.status_path.with_suffix(self.status_path.suffix + ".tmp")
        tmp.write_text("READY\n")
        tmp.replace(self.status_path)
        # Status file is informational; keep default permissions.

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None
        if self._watchdog is not None:
            self._watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._watchdog
            self._watchdog = None
        for path in (self.sock_path, self.status_path):
            with contextlib.suppress(OSError):
                path.unlink()
        self._stopped.set()

    async def wait_stopped(self) -> None:
        await self._stopped.wait()

    async def _parent_watchdog(self) -> None:
        while True:
            await asyncio.sleep(PARENT_POLL_INTERVAL)
            try:
                os.kill(self.parent_pid, 0)
            except ProcessLookupError:
                logger.info("parent pid=%d gone; helper exiting", self.parent_pid)
                asyncio.create_task(self._self_terminate())
                return
            except PermissionError:
                # Parent still exists, we just can't signal it. Fine.
                pass

    async def _self_terminate(self) -> None:
        await self.stop()
        # Exit the process; PyInstaller wraps a normal Python interpreter.
        os._exit(0)

    # ── connection / dispatch ─────────────────────────────────────

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername") or "<unix>"
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                try:
                    req = json.loads(line.decode())
                except json.JSONDecodeError as exc:
                    resp = _rpc_error(None, -32700, f"parse error: {exc}")
                else:
                    resp = await self._dispatch(req)
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        except Exception:
            logger.exception("connection handler crashed for peer %s", peer)
        finally:
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    async def _dispatch(self, req: dict) -> dict:
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        if not isinstance(params, dict):
            return _rpc_error(req_id, -32602, "params must be an object")
        handler = self._methods.get(method)
        if handler is None:
            return _rpc_error(req_id, -32601, f"method not found: {method}")
        try:
            result = await handler(params)
            return _rpc_result(req_id, result)
        except _HelperRpcError as exc:
            return _rpc_error(req_id, exc.code, exc.message, exc.data)
        except Exception as exc:
            logger.exception("handler %s raised", method)
            import traceback
            return _rpc_error(
                req_id,
                -32099,
                f"internal helper error: {exc}",
                data={"traceback": traceback.format_exc()},
            )

    # ── handlers ──────────────────────────────────────────────────

    async def _handle_ping(self, params: dict) -> dict:
        return {"ok": True, "helper_pid": os.getpid()}

    async def _handle_shutdown(self, params: dict) -> dict:
        # Schedule the teardown after we send the response.
        asyncio.create_task(self._delayed_stop())
        return {"ok": True}

    async def _delayed_stop(self) -> None:
        await asyncio.sleep(0.05)  # let the response flush
        await self.stop()

    async def _handle_migrate_user_state(self, params: dict) -> dict:
        from migrate_user_state import migrate_user_state

        home = params.get("home")
        uid = params.get("uid")
        gid = params.get("gid")
        if not (isinstance(home, str) and isinstance(uid, int) and isinstance(gid, int)):
            raise _HelperRpcError(-32602, "migrate_user_state needs home:str, uid:int, gid:int")
        return migrate_user_state(home=home, uid=uid, gid=gid)


class _HelperRpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def run() -> int:
    parser = argparse.ArgumentParser(prog="locwarp-backend --tunnel-helper")
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--parent-uid", type=int, required=True)
    parser.add_argument("--sock-path", default=str(DEFAULT_SOCK_PATH))
    parser.add_argument("--status-path", default=str(DEFAULT_STATUS_PATH))
    args, _ = parser.parse_known_args(sys.argv[1:])

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [tunnel_helper] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    server = HelperServer(
        sock_path=Path(args.sock_path),
        status_path=Path(args.status_path),
        parent_pid=args.parent_pid,
        parent_uid=args.parent_uid,
    )

    async def _main() -> None:
        await server.start()
        # SIGTERM → graceful stop.
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(server.stop()))
        await server.wait_stopped()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
```

- [ ] **Step 4: Write the failing test for the migration helper**

```python
# backend/tests/test_migrate_user_state.py
import os
import pytest
from pathlib import Path

from migrate_user_state import migrate_user_state


def _seed(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "bookmarks.json").write_text("{}")
    (root / "logs").mkdir(exist_ok=True)
    (root / "logs" / "backend.log").write_text("hello")


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root to seed root-owned files")
def test_migrate_chowns_root_files_to_caller_uid(tmp_path):
    home = tmp_path
    locwarp = home / ".locwarp"
    _seed(locwarp)
    # Seed is already root-owned because we are running as root.
    target_uid = int(os.environ.get("SUDO_UID", os.getuid()))
    target_gid = int(os.environ.get("SUDO_GID", os.getgid()))
    result = migrate_user_state(home=str(home), uid=target_uid, gid=target_gid)
    assert result["chowned"] >= 3  # dir, file, subdir, file
    assert result["failed"] == 0
    for path in [locwarp, locwarp / "bookmarks.json", locwarp / "logs", locwarp / "logs" / "backend.log"]:
        assert path.stat().st_uid == target_uid


def test_migrate_no_op_when_already_owned(tmp_path):
    home = tmp_path
    _seed(home / ".locwarp")
    # Already owned by current uid (test process).
    result = migrate_user_state(home=str(home), uid=os.getuid(), gid=os.getgid())
    assert result["chowned"] == 0
    assert result["failed"] == 0
    assert result["skipped"] >= 3


def test_migrate_missing_home_dirs_returns_zeros(tmp_path):
    result = migrate_user_state(home=str(tmp_path), uid=os.getuid(), gid=os.getgid())
    assert result == {"chowned": 0, "skipped": 0, "failed": 0}
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_migrate_user_state.py tests/test_tunnel_helper_main.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'migrate_user_state'` and `'tunnel_helper_main'`.

- [ ] **Step 6: Implement migration helper**

```python
# backend/migrate_user_state.py
"""One-shot ownership repair for LocWarp state directories.

Older versions of LocWarp ran the entire backend as root, so files in
``~/.locwarp/`` and ``~/Library/Mobile Documents/com~apple~CloudDocs/
LocWarp/`` got created with root ownership. After the user/helper
split, the backend runs as the regular user and cannot rewrite those
files; chown of root-owned files requires root. The helper exposes
this function via the ``migrate_user_state`` RPC so the backend can
trigger the repair once at startup.

Best-effort: per-entry failures are counted and logged, never raised.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("tunnel_helper.migrate")


def migrate_user_state(*, home: str, uid: int, gid: int) -> dict:
    home_path = Path(home)
    targets = [
        home_path / ".locwarp",
        home_path / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "LocWarp",
    ]
    chowned = skipped = failed = 0
    for root in targets:
        if not root.exists():
            continue
        for entry in [root, *root.rglob("*")]:
            try:
                st = entry.stat()
                if st.st_uid == uid:
                    skipped += 1
                    continue
                os.chown(entry, uid, gid)
                chowned += 1
            except OSError as exc:
                failed += 1
                logger.warning("could not chown %s: %s", entry, exc)
    return {"chowned": chowned, "skipped": skipped, "failed": failed}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_migrate_user_state.py tests/test_tunnel_helper_main.py -v`
Expected: `test_migrate_chowns_root_files_to_caller_uid` is skipped (not root); the other 5 tests pass.

- [ ] **Step 8: Wire `--tunnel-helper` into `main.py`**

Open `backend/main.py`. After the imports block but before any other top-level work (i.e. before `class AppState:`), add:

```python
# Early branch: when run with --tunnel-helper, behave as the elevated
# tunnel helper and skip all FastAPI / BookmarkManager initialisation.
if "--tunnel-helper" in __import__("sys").argv:
    from tunnel_helper_main import run as _tunnel_helper_run
    raise SystemExit(_tunnel_helper_run())
```

This must run *before* `class AppState`. The class instantiation at module level (`app_state = AppState()`) would otherwise load `BookmarkManager()` and friends in the helper, which we don't want.

- [ ] **Step 9: Smoke-test the helper binary manually**

```bash
cd backend && source .venv/bin/activate
sudo python3 main.py --tunnel-helper --parent-pid=$$ --parent-uid=$(id -u) &
sleep 1
cat /tmp/locwarp-helper.status        # expect: READY
nc -U /tmp/locwarp-helper.sock <<< '{"jsonrpc":"2.0","id":1,"method":"ping"}'
# expect: {"jsonrpc": "2.0", "id": 1, "result": {"ok": true, "helper_pid": <N>}}
nc -U /tmp/locwarp-helper.sock <<< '{"jsonrpc":"2.0","id":2,"method":"shutdown"}'
```

Expected: helper process exits cleanly within 1s; `/tmp/locwarp-helper.sock` and `/tmp/locwarp-helper.status` are removed.

- [ ] **Step 10: Commit**

```bash
git add backend/tunnel_helper_main.py backend/migrate_user_state.py \
        backend/main.py \
        backend/tests/test_tunnel_helper_main.py \
        backend/tests/test_migrate_user_state.py
git commit -m "feat(backend): tunnel helper with ping/shutdown/migrate_user_state"
```

---

## Task 3: Backend startup connects to helper and runs migration

**Files:**
- Modify: `backend/main.py` — call `helper_client.connect()` + `migrate_user_state` before `BookmarkManager()`

- [ ] **Step 1: Identify where AppState is constructed**

Read `backend/main.py:43-218`. `app_state = AppState()` runs at module top level. `AppState.__init__` instantiates `BookmarkManager()` and `RouteManager()` which immediately touch `~/.locwarp/`.

- [ ] **Step 2: Defer state-loading until after helper migration**

Refactor `AppState.__init__` to *not* eagerly load state, and add a new `async load_state()` method. Edit `backend/main.py` (the class definition around line 42):

```python
class AppState:
    """Central application state — shared across API endpoints."""

    def __init__(self):
        self.device_manager = DeviceManager()
        self.simulation_engines: dict = {}
        self._primary_udid: str | None = None
        self.cooldown_timer = CooldownTimer()
        self.bookmark_manager: BookmarkManager | None = None
        self.route_manager: RouteManager | None = None
        self.coord_formatter = CoordinateFormatter()
        self.reconnect_manager = None
        self._last_position = None
        self._initial_map_position: dict | None = None
        self._bookmark_expanded_categories: list[str] | None = None
        self._bookmarks_path: str | None = None
        self._cloud_sync_dismissed: bool = False
        # Do NOT call _load_settings() or BookmarkManager() here.

    async def load_state(self) -> None:
        """Load on-disk state. Must run after the helper has migrated
        any root-owned files back to the user."""
        self._load_settings()
        self.bookmark_manager = BookmarkManager()
        self.route_manager = RouteManager()
```

- [ ] **Step 3: Hook helper connect + migrate into the FastAPI lifespan**

Locate the lifespan / startup hook in `backend/main.py`. If `app = FastAPI(lifespan=...)` exists, extend it; otherwise add one. Add:

```python
from services.tunnel_helper_client import TunnelHelperClient

helper_client = TunnelHelperClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Wait for the helper to publish READY, then migrate any root-owned
    # state files back to the user so the BookmarkManager / RouteManager
    # we construct next can read and write them.
    try:
        await helper_client.connect(timeout=30.0)
        result = await helper_client.migrate_user_state(
            home=str(Path.home()),
            uid=os.getuid(),
            gid=os.getgid(),
        )
        logger.info("helper migrate_user_state: %s", result)
    except Exception:
        logger.exception("helper connect/migrate failed — bookmarks may not load")
    await app_state.load_state()
    yield
    try:
        await helper_client.shutdown()
    except Exception:
        logger.exception("helper shutdown call failed")
    await helper_client.close()


app = FastAPI(lifespan=lifespan)
```

(Adjust to existing app construction. `import os` must be added at the top of `main.py` if not already present.)

- [ ] **Step 4: Update callers that assumed eager BookmarkManager**

Anywhere in `backend/main.py` (and API routers) that calls `app_state.bookmark_manager.xyz()` at *module load time* needs to move into request handlers. Skim `app.include_router(...)` site and confirm — routers should already access bookmark_manager lazily inside their handlers; if not, this task fails fast at first request and we add a TODO and continue.

```bash
grep -n "app_state.bookmark_manager" backend/api/*.py
```

Each match must be inside a function, not at module level. If any are at module level, hoist them into the handler.

- [ ] **Step 5: Run the full backend test suite to catch regressions from the lazy init**

```bash
cd backend && pytest -x -q
```

Expected: existing tests pass. Tests that constructed `AppState()` and immediately used `bookmark_manager` need a one-liner `await app_state.load_state()` before use; fix in place.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py
git commit -m "refactor(backend): defer bookmark/route load until after helper migration"
```

---

## Task 4: Move `TunnelRunner` to helper-internal module

**Files:**
- Create: `backend/core/_tunnel_runner.py`
- Modify: `backend/core/wifi_tunnel.py` (drops the body, keeps a stub facade for Task 6)

- [ ] **Step 1: Verify existing wifi_tunnel tests catch behavior**

```bash
grep -rln "TunnelRunner\|wifi_tunnel" backend/tests/
```

Run any matches green first: `cd backend && pytest <files> -v`. Establish the baseline.

- [ ] **Step 2: Copy `TunnelRunner` verbatim to `_tunnel_runner.py`**

```python
# backend/core/_tunnel_runner.py
"""Helper-internal TunnelRunner.

This holds /dev/utunN open via pymobiledevice3.remote.tunnel_service.
The user-context backend MUST NOT import this module — the leading
underscore signals "helper-only". The user-side facade lives in
core/wifi_tunnel.py.
"""

# ... contents of current backend/core/wifi_tunnel.py verbatim ...
```

Copy the file body from `backend/core/wifi_tunnel.py` as-is (logger name stays `"wifi_tunnel"`; class stays `TunnelRunner`).

- [ ] **Step 3: Empty out `wifi_tunnel.py` to a minimal stub**

```python
# backend/core/wifi_tunnel.py
"""User-side WiFi tunnel facade — see Task 6.

This module currently delegates to the helper via TunnelRunner being
re-exported from _tunnel_runner. Task 6 swaps in a thin facade that
calls helper_client.open_wifi_tunnel/close_tunnel instead. For Task 4
we just re-export so nothing breaks at import time."""

from core._tunnel_runner import TunnelRunner  # noqa: F401
```

- [ ] **Step 4: Run the test baseline again**

```bash
cd backend && pytest -x -q
```

Expected: same as Step 1 — no regressions.

- [ ] **Step 5: Commit**

```bash
git add backend/core/_tunnel_runner.py backend/core/wifi_tunnel.py
git commit -m "refactor(core): move TunnelRunner to helper-internal module"
```

---

## Task 5: Helper exposes `open_wifi_tunnel` / `close_tunnel` / `list_tunnels` RPCs

**Files:**
- Modify: `backend/tunnel_helper_main.py` — add the three methods and a per-UDID `TunnelRunner` registry
- Modify: `backend/tests/test_tunnel_helper_main.py` — exercise the new methods with a fake `_tunnel_runner` (no real TUN)

- [ ] **Step 1: Write the failing test (fake runner injected)**

Add to `backend/tests/test_tunnel_helper_main.py`:

```python
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
        assert r2["result"] == [{"udid": "abc", "rsd_address": "fd7d::1", "rsd_port": 12345, "interface": "utun9"}]

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_tunnel_helper_main.py::test_open_and_close_wifi_tunnel_via_fake_runner -v`
Expected: FAIL — `AttributeError: module 'tunnel_helper_main' has no attribute '_TunnelRunner'`.

- [ ] **Step 3: Extend the helper**

Edit `backend/tunnel_helper_main.py`. Add at module top, alongside existing imports:

```python
from core._tunnel_runner import TunnelRunner as _TunnelRunner
```

Add three methods to `HelperServer`, and register them:

```python
# inside HelperServer.__init__, after the existing _methods dict:
self._tunnels: dict[str, _TunnelRunner] = {}
self._methods.update({
    "open_wifi_tunnel": self._handle_open_wifi_tunnel,
    "open_usb_tunnel": self._handle_open_usb_tunnel,
    "close_tunnel": self._handle_close_tunnel,
    "list_tunnels": self._handle_list_tunnels,
})

# new handlers:

async def _handle_open_wifi_tunnel(self, params: dict) -> dict:
    udid = params.get("udid")
    ip = params.get("ip")
    port = params.get("port")
    if not (isinstance(udid, str) and isinstance(ip, str) and isinstance(port, int)):
        raise _HelperRpcError(-32602, "open_wifi_tunnel needs udid:str, ip:str, port:int")
    if udid in self._tunnels:
        raise _HelperRpcError(-32003, f"tunnel already exists for {udid}")
    runner = _TunnelRunner()
    try:
        info = await runner.start(udid=udid, ip=ip, port=port)
    except Exception as exc:
        raise _HelperRpcError(-32002, f"RemotePairing handshake failed: {exc}")
    self._tunnels[udid] = runner
    return info

async def _handle_open_usb_tunnel(self, params: dict) -> dict:
    udid = params.get("udid")
    if not isinstance(udid, str):
        raise _HelperRpcError(-32602, "open_usb_tunnel needs udid:str")
    if udid in self._tunnels:
        raise _HelperRpcError(-32003, f"tunnel already exists for {udid}")
    info = await _open_usb_tunnel_in_helper(udid)
    # _open_usb_tunnel_in_helper returns (info, runner_handle) — see Task 7
    raise _HelperRpcError(-32099, "open_usb_tunnel not yet implemented (Task 7)")

async def _handle_close_tunnel(self, params: dict) -> dict:
    udid = params.get("udid")
    if not isinstance(udid, str):
        raise _HelperRpcError(-32602, "close_tunnel needs udid:str")
    runner = self._tunnels.pop(udid, None)
    if runner is None:
        raise _HelperRpcError(-32004, f"unknown tunnel: {udid}")
    await runner.stop()
    return {"closed": True}

async def _handle_list_tunnels(self, params: dict) -> list[dict]:
    out = []
    for udid, runner in self._tunnels.items():
        info = runner.info or {}
        out.append({
            "udid": udid,
            "rsd_address": info.get("rsd_address"),
            "rsd_port": info.get("rsd_port"),
            "interface": info.get("interface"),
        })
    return out
```

Update `stop()` to also close active tunnels:

```python
async def stop(self) -> None:
    for udid, runner in list(self._tunnels.items()):
        try:
            await runner.stop()
        except Exception:
            logger.exception("error stopping tunnel for %s during shutdown", udid)
    self._tunnels.clear()
    # ... existing server.close()/watchdog cancel/path cleanup ...
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `cd backend && pytest tests/test_tunnel_helper_main.py -v`
Expected: 4 tests pass (3 from Task 2, 1 new). `open_usb_tunnel` still errors with -32099, which Task 7 handles.

- [ ] **Step 5: Commit**

```bash
git add backend/tunnel_helper_main.py backend/tests/test_tunnel_helper_main.py
git commit -m "feat(helper): open_wifi_tunnel/close_tunnel/list_tunnels RPCs"
```

---

## Task 6: User-side `wifi_tunnel.py` becomes a helper-client facade

**Files:**
- Modify: `backend/core/wifi_tunnel.py` — replace re-export with a real facade
- Update: any existing test that imported `TunnelRunner` from `core.wifi_tunnel`

- [ ] **Step 1: Read the existing user-side callers**

```bash
grep -rln "from core.wifi_tunnel\|from core import wifi_tunnel\|TunnelRunner(" backend/ | grep -v __pycache__
```

Document the call sites: `start(udid, ip, port)`, `stop()`, `is_running()`, `info` property, `target_ip`/`target_port`. The facade must keep those.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_wifi_tunnel_facade.py
import asyncio
import pytest

from core.wifi_tunnel import TunnelRunner


@pytest.mark.asyncio
async def test_start_delegates_to_helper_client(monkeypatch):
    calls = []

    class FakeClient:
        async def open_wifi_tunnel(self, udid, ip, port):
            calls.append(("open", udid, ip, port))
            return {
                "rsd_address": "fd7d::1",
                "rsd_port": 9999,
                "interface": "utun3",
                "protocol": "quic",
            }

        async def close_tunnel(self, udid):
            calls.append(("close", udid))
            return {"closed": True}

    monkeypatch.setattr("core.wifi_tunnel._helper_client", FakeClient())

    runner = TunnelRunner()
    info = await runner.start(udid="xyz", ip="192.168.1.1", port=12345)
    assert info["rsd_address"] == "fd7d::1"
    assert runner.is_running()
    assert runner.target_ip == "192.168.1.1"
    assert runner.target_port == 12345

    await runner.stop()
    assert not runner.is_running()
    assert calls == [
        ("open", "xyz", "192.168.1.1", 12345),
        ("close", "xyz"),
    ]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_wifi_tunnel_facade.py -v`
Expected: FAIL — `_helper_client` attribute missing.

- [ ] **Step 4: Replace `wifi_tunnel.py` with the facade**

```python
# backend/core/wifi_tunnel.py
"""User-side WiFi tunnel facade.

The original ``TunnelRunner`` body — which imports
``pymobiledevice3.remote.tunnel_service`` and opens ``/dev/utunN`` —
now lives in the helper-only module ``core/_tunnel_runner.py``. The
user-context backend cannot open a TUN, so the class here proxies to
the elevated helper via ``services.tunnel_helper_client``.

The public surface (``start``, ``stop``, ``is_running``, ``info``,
``target_ip``, ``target_port``) matches the original so callers
(``device_manager``, the WiFi-tunnel API endpoint, watchdogs) need no
changes.
"""

from __future__ import annotations

import logging

from services.tunnel_helper_client import TunnelHelperClient

logger = logging.getLogger("wifi_tunnel")

# Singleton; tests monkeypatch this with a fake.
_helper_client: TunnelHelperClient | None = None


def set_helper_client(client: TunnelHelperClient) -> None:
    """Hook used by main.py's lifespan to inject the connected client."""
    global _helper_client
    _helper_client = client


class TunnelRunner:
    def __init__(self) -> None:
        self.info: dict | None = None
        self.target_ip: str | None = None
        self.target_port: int | None = None
        self._udid: str | None = None
        self._open: bool = False

    def is_running(self) -> bool:
        return self._open

    async def start(self, udid: str, ip: str, port: int, timeout: float = 20.0) -> dict:
        if _helper_client is None:
            raise RuntimeError("tunnel helper client is not configured")
        info = await _helper_client.open_wifi_tunnel(udid=udid, ip=ip, port=port)
        self.info = info
        self.target_ip = ip
        self.target_port = port
        self._udid = udid
        self._open = True
        return dict(info)

    async def stop(self) -> None:
        if not self._open or _helper_client is None or self._udid is None:
            self._open = False
            self.info = None
            return
        try:
            await _helper_client.close_tunnel(udid=self._udid)
        except Exception:
            logger.exception("close_tunnel rpc failed for %s", self._udid)
        finally:
            self._open = False
            self.info = None
            self._udid = None
```

- [ ] **Step 5: Wire `set_helper_client` from `main.py` lifespan**

In `backend/main.py`, inside the `lifespan` async context manager (added in Task 3), after `await helper_client.connect(...)`:

```python
from core.wifi_tunnel import set_helper_client
set_helper_client(helper_client)
```

- [ ] **Step 6: Run the new test plus the wifi-tunnel suite**

Run: `cd backend && pytest tests/test_wifi_tunnel_facade.py -v && pytest -x -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/core/wifi_tunnel.py backend/tests/test_wifi_tunnel_facade.py backend/main.py
git commit -m "refactor(core): wifi_tunnel TunnelRunner becomes helper-client facade"
```

---

## Task 7: Helper `open_usb_tunnel` — build lockdown + tunnel in-process

**Files:**
- Modify: `backend/tunnel_helper_main.py` — flesh out `_handle_open_usb_tunnel`
- Modify: `backend/core/device_manager.py:_connect_tunnel` — use helper client
- Modify: `backend/tests/test_tunnel_helper_main.py` — fake USB tunnel path

- [ ] **Step 1: Add a USB-tunnel runner inside the helper**

The current `core/device_manager.py:_connect_tunnel` (lines ~297-330) builds a `CoreDeviceTunnelProxy(lockdown=lockdown)` and calls `start_tcp_tunnel()`. Move that constructor pattern into a helper-side function that owns the proxy:

```python
# backend/core/_tunnel_runner.py — append below TunnelRunner

import asyncio
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.tunnel_service import CoreDeviceTunnelProxy


class UsbTunnelRunner:
    """USB iOS 17+ tunnel runner, helper-internal.

    Symmetric to TunnelRunner but uses CoreDeviceTunnelProxy over a
    usbmux-backed lockdown connection. Constructs lockdown itself —
    backend does not share state with the helper.
    """

    def __init__(self) -> None:
        self.info: dict | None = None
        self._lockdown = None
        self._proxy: CoreDeviceTunnelProxy | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._error: BaseException | None = None

    async def _run(self, udid: str) -> None:
        try:
            self._lockdown = create_using_usbmux(serial=udid)
            self._proxy = CoreDeviceTunnelProxy(lockdown=self._lockdown)
            async with self._proxy.start_tcp_tunnel() as tun:
                self.info = {
                    "rsd_address": tun.address,
                    "rsd_port": tun.port,
                    "interface": tun.interface,
                    "protocol": str(tun.protocol),
                }
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:
            self._error = exc
            self._ready.set()
            raise
        finally:
            self.info = None
            if self._proxy is not None:
                try:
                    self._proxy.close()
                except Exception:
                    pass
            self._proxy = None

    async def start(self, udid: str, timeout: float = 20.0) -> dict:
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._error = None
        self.info = None
        self._task = asyncio.create_task(self._run(udid))
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._stop.set()
            raise
        if self._error is not None:
            raise self._error
        return dict(self.info or {})

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except (asyncio.TimeoutError, Exception):
            self._task.cancel()
        self._task = None
        self.info = None
```

- [ ] **Step 2: Wire `_UsbTunnelRunner` into the helper**

Edit `backend/tunnel_helper_main.py`:

```python
from core._tunnel_runner import UsbTunnelRunner as _UsbTunnelRunner
```

Replace `_handle_open_usb_tunnel` body:

```python
async def _handle_open_usb_tunnel(self, params: dict) -> dict:
    udid = params.get("udid")
    if not isinstance(udid, str):
        raise _HelperRpcError(-32602, "open_usb_tunnel needs udid:str")
    if udid in self._tunnels:
        raise _HelperRpcError(-32003, f"tunnel already exists for {udid}")
    runner = _UsbTunnelRunner()
    try:
        info = await runner.start(udid=udid)
    except Exception as exc:
        raise _HelperRpcError(-32002, f"USB tunnel failed: {exc}")
    self._tunnels[udid] = runner
    return info
```

Both `_TunnelRunner` and `_UsbTunnelRunner` expose the same `info` / `stop()` shape, so `close_tunnel` and `list_tunnels` work unchanged.

- [ ] **Step 3: Write the failing test**

Add to `backend/tests/test_tunnel_helper_main.py`:

```python
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
```

- [ ] **Step 4: Run the test**

Run: `cd backend && pytest tests/test_tunnel_helper_main.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Update `device_manager._connect_tunnel`**

In `backend/core/device_manager.py`, locate `_connect_tunnel` (around line 297). Replace the body that constructs `CoreDeviceTunnelProxy` and calls `start_tcp_tunnel` with a helper call:

```python
async def _connect_tunnel(
    self, udid: str, lockdown, ios_version: str,
) -> DeviceConnection:
    """TCP tunnel for iOS 17+ over USB, served by the elevated helper."""
    from services.tunnel_helper_client import TunnelHelperClient
    from core.wifi_tunnel import _helper_client  # set by lifespan

    if _helper_client is None:
        raise RuntimeError("tunnel helper client is not configured")

    logger.debug("Requesting USB tunnel from helper for %s (iOS %s)", udid, ios_version)
    info = await _helper_client.open_usb_tunnel(udid=udid)

    rsd = RemoteServiceDiscoveryService((info["rsd_address"], info["rsd_port"]))
    await rsd.connect()
    return DeviceConnection(
        udid=udid,
        connection_type=ConnectionType.USB,
        lockdown=lockdown,
        rsd=rsd,
        ios_version=ios_version,
        # The proxy + tunnel_context live in the helper now; we no longer
        # hold them locally. close() will call helper.close_tunnel(udid).
        tunnel_proxy=None,
        tunnel_context=None,
    )
```

And update the connection-close path (around line 380) to call helper close instead of `tunnel_proxy.close()`:

```python
# Close tunnel: previously closed tunnel_context + tunnel_proxy locally;
# now the helper owns both and exits via close_tunnel RPC.
from core.wifi_tunnel import _helper_client
if conn.connection_type == ConnectionType.USB and _helper_client is not None:
    try:
        await _helper_client.close_tunnel(udid=conn.udid)
    except Exception:
        logger.exception("Error closing helper-owned USB tunnel for %s", conn.udid)
```

Remove the now-dead `tunnel_proxy.close()` / `tunnel_context.__aexit__()` blocks.

- [ ] **Step 6: Run the full test suite**

```bash
cd backend && pytest -x -q
```

Expected: all green. Any failure should be addressed before commit; if a test is genuinely now-irrelevant (e.g. an old test that asserted on `tunnel_proxy` being set), delete it with a one-line commit message.

- [ ] **Step 7: Commit**

```bash
git add backend/tunnel_helper_main.py backend/core/_tunnel_runner.py \
        backend/core/device_manager.py backend/tests/test_tunnel_helper_main.py
git commit -m "feat: route iOS 17+ USB tunnels through the helper"
```

---

## Task 8: Drop root-only chmod from `cloud_sync.py`

**Files:**
- Modify: `backend/services/cloud_sync.py`
- Modify: `backend/tests/test_cloud_sync.py` (and `test_cloud_sync_api.py` if it asserts on chmod)

- [ ] **Step 1: Inspect existing tests**

```bash
grep -n "chmod\|EPERM\|0o644\|0o755" backend/tests/test_cloud_sync.py backend/tests/test_cloud_sync_api.py
```

Document any test that asserts chmod was called; those go away.

- [ ] **Step 2: Simplify `setup_sync_folder`**

Replace `setup_sync_folder` in `backend/services/cloud_sync.py`:

```python
def setup_sync_folder(parent: Path) -> Path:
    """Create (or reuse) the LocWarp subfolder under *parent*.

    Raises FileNotFoundError if *parent* itself does not exist (we never
    create the cloud-drive root for the user).
    """
    if not parent.exists():
        raise FileNotFoundError(f"Parent folder does not exist: {parent}")
    sub = parent / LOCWARP_SUBFOLDER
    sub.mkdir(exist_ok=True)
    return sub
```

- [ ] **Step 3: Simplify `migrate_bookmarks`**

Replace `migrate_bookmarks`:

```python
def migrate_bookmarks(src: Path, dst: Path) -> None:
    """Move *src* to *dst*. No-op if *src* does not exist.

    Refuses to overwrite *dst* if both files exist with different
    content (caller resolves via the merge code path).
    """
    if not src.exists():
        return
    if dst.exists():
        if dst.read_bytes() == src.read_bytes():
            try:
                src.unlink()
            except OSError as exc:
                logger.warning("migrate_bookmarks: %s and %s match but src unlink failed: %s",
                               src, dst, exc)
            return
        raise FileExistsError(f"Destination already has different content: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    src.unlink()
```

- [ ] **Step 4: Update tests**

Remove or rewrite any test that:
- Patched `OSError` into `read_bytes` to simulate root-EPERM.
- Asserted that `chmod` was called.
- Tested the silent-adopt branch.

For each removal, add a one-line comment in the test file at the top of the test class explaining what was removed and why ("removed: simulates EPERM on iCloud reads — no longer possible now that the backend runs as the file owner"). This makes the removal auditable.

- [ ] **Step 5: Run tests**

```bash
cd backend && pytest tests/test_cloud_sync.py tests/test_cloud_sync_api.py -v
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add backend/services/cloud_sync.py backend/tests/test_cloud_sync.py backend/tests/test_cloud_sync_api.py
git commit -m "refactor(cloud-sync): drop root-only chmod and EPERM workarounds"
```

---

## Task 9: Electron `main.js` spawns backend + helper in parallel

**Files:**
- Modify: `frontend/electron/main.js`

- [ ] **Step 1: Read the current `startBackend`/`stopBackend` (lines 248-296)**

Already inspected. The packaged-mac branch elevates via `osascript`. We split that into two children.

- [ ] **Step 2: Edit `startBackend`**

Replace the function body (lines 248-280):

```js
function startBackend() {
  const exe = resolveBackendExe()
  if (!exe) return

  // Dev / non-Mac builds: single child, no elevation.
  if (!(process.platform === 'darwin' && app.isPackaged)) {
    console.log('[electron] spawning backend (no elevation):', exe)
    backendProc = spawn(exe, [], {
      cwd: path.dirname(exe),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })
    backendProc.stdout.on('data', (d) => process.stdout.write(`[backend] ${d}`))
    backendProc.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`))
    backendProc.on('exit', (code) => {
      console.log('[electron] backend exited with code', code)
      backendProc = null
    })
    return
  }

  // Packaged macOS: spawn backend as the user, and helper as root via
  // osascript. They run in parallel; the backend waits inside its own
  // lifespan for the helper's READY status file before doing I/O.
  console.log('[electron] spawning backend (user) + helper (root via osascript)')
  backendProc = spawn(exe, [], {
    cwd: path.dirname(exe),
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  backendProc.stdout.on('data', (d) => process.stdout.write(`[backend] ${d}`))
  backendProc.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`))
  backendProc.on('exit', (code) => {
    console.log('[electron] backend exited with code', code)
    backendProc = null
  })

  const escaped = exe.replace(/'/g, "'\\''")
  const cwd = path.dirname(exe).replace(/'/g, "'\\''")
  const parentPid = backendProc.pid
  const parentUid = process.getuid ? process.getuid() : 501
  const script =
    `do shell script "cd '${cwd}' && '${escaped}' --tunnel-helper ` +
    `--parent-pid=${parentPid} --parent-uid=${parentUid} ` +
    `</dev/null >/tmp/locwarp-helper-stdout.log 2>/tmp/locwarp-helper-stderr.log &" ` +
    `with administrator privileges ` +
    `with prompt "LocWarp needs administrator access to communicate with iOS 17+ devices over USB."`
  spawn('osascript', ['-e', script], { stdio: 'ignore' })
}
```

- [ ] **Step 3: Edit `stopBackend`**

Replace (lines 282-296):

```js
function stopBackend() {
  // Backend is always a direct child now (user-context), so SIGTERM works.
  if (backendProc) {
    try { backendProc.kill('SIGTERM') } catch {}
    backendProc = null
  }
  // The helper (when present) sees the backend pid disappear via its
  // watchdog and exits within ~5s. As a belt-and-braces signal, also
  // POST to the backend's shutdown endpoint so the backend explicitly
  // calls helper.shutdown() before exiting.
  if (process.platform === 'darwin' && app.isPackaged) {
    try {
      http.request({ hostname: '127.0.0.1', port: 8777, path: '/api/system/shutdown', method: 'POST' }).end()
    } catch {}
  }
}
```

- [ ] **Step 4: Rebuild and manually verify**

```bash
make build-install
# Watch for the admin prompt — it should appear ONCE, for the helper only.
# After install, ps auxww | grep locwarp-backend should show two procs:
#   raviwu  ... locwarp-backend
#   root    ... locwarp-backend --tunnel-helper ...
ls -la /tmp/locwarp-helper.sock /tmp/locwarp-helper.status
# expect: socket file (srw-rw---- root:staff), status file containing "READY"
```

If `ps` only shows the helper or only the backend, see the troubleshooting note in §11 of the design spec.

- [ ] **Step 5: Commit**

```bash
git add frontend/electron/main.js
git commit -m "feat(electron): spawn backend as user and helper as root in parallel"
```

---

## Task 10: Dev launcher mirrors the split

**Files:**
- Modify: `start.sh`
- Modify: `start.py`

- [ ] **Step 1: Strip `sudo` from `start.sh`**

```bash
# start.sh
#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "  LocWarp macOS Launcher"
echo "  iOS 17+ 需要 root 權限建立裝置通道 (sudo prompt for helper only)"
echo

exec python3 "$SCRIPT_DIR/start.py" "$@"
```

- [ ] **Step 2: Spawn the helper from `start.py`**

Read `start.py` and identify where the FastAPI app starts. Before that, spawn the helper:

```python
# start.py — near the top, before importing main / uvicorn
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent / "backend"
HELPER_SOCK = Path("/tmp/locwarp-helper.sock")
HELPER_STATUS = Path("/tmp/locwarp-helper.status")


def _spawn_helper() -> None:
    if HELPER_SOCK.exists():
        # Likely a stale socket from a prior crash — try to ping it via
        # `nc`. If responsive, reuse; otherwise unlink and respawn.
        try:
            r = subprocess.run(
                ["bash", "-c", f"echo '{{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"ping\"}}' | nc -U {HELPER_SOCK} -w 1"],
                capture_output=True, timeout=2,
            )
            if b'"result"' in r.stdout:
                print("[start] reusing existing helper")
                return
        except Exception:
            pass
        for p in (HELPER_SOCK, HELPER_STATUS):
            try:
                p.unlink()
            except OSError:
                pass

    parent_pid = os.getpid()
    parent_uid = os.getuid()
    print(f"[start] spawning tunnel helper as root (parent pid={parent_pid})")
    subprocess.Popen(
        [
            "sudo", "-n" if os.environ.get("LOCWARP_DEV_NO_PROMPT") else "--",
            sys.executable, str(BACKEND_DIR / "main.py"),
            "--tunnel-helper",
            f"--parent-pid={parent_pid}",
            f"--parent-uid={parent_uid}",
        ],
        cwd=str(BACKEND_DIR),
    )


_spawn_helper()
```

(Adapt to whatever `start.py` already does — the key invariant is: the helper is spawned via `sudo`, and the backend continues to run as the regular user.)

- [ ] **Step 3: Test dev mode**

```bash
./start.sh
# expect one sudo prompt for the helper; the FastAPI server runs as you
ps -p $$ -o user=  # shows raviwu
ps auxww | grep tunnel-helper | grep -v grep  # shows root
```

- [ ] **Step 4: Commit**

```bash
git add start.sh start.py
git commit -m "feat(dev): split sudo-only helper from user-mode dev launcher"
```

---

## Task 11: Acceptance — verify the six spec criteria end-to-end

**Files:** none (manual / observational)

- [ ] **Step 1: Fresh `make build-install`**

```bash
make build-install
```

Confirm the admin prompt fires once. Cancelling produces a clear error (Q2.a behaviour).

- [ ] **Step 2: Inspect process tree**

```bash
ps auxww | grep -E "locwarp-backend" | grep -v grep
```

Expect exactly two rows:
- `raviwu ... .../Resources/backend/locwarp-backend` (no `--tunnel-helper`)
- `root   ... .../Resources/backend/locwarp-backend --tunnel-helper ...`

- [ ] **Step 3: Verify file ownership migration**

```bash
ls -la ~/.locwarp/
ls -la "~/Library/Mobile Documents/com~apple~CloudDocs/LocWarp/"
```

Expect `raviwu staff` for every entry. If you started this task with root-owned files, the helper's `migrate_user_state` reclaim should have run on first launch.

- [ ] **Step 4: Bookmark load smoke**

Open the app. Open the bookmarks panel. Expect to see 81 bookmarks in 30 categories (matching the count from the last known-good `backend.log`).

- [ ] **Step 5: Check `backend.log` for EPERM**

```bash
grep -E "Operation not permitted|EPERM" ~/.locwarp/logs/backend.log | tail
```

Expect: empty.

- [ ] **Step 6: iOS 17+ connect**

USB-connect an iOS 17+ device. Confirm the device appears in the UI. Pick a bookmark; confirm location simulation works. Disconnect; confirm the device drops cleanly.

Repeat with the same device over WiFi (after the initial USB pair).

- [ ] **Step 7: Helper liveness**

```bash
# Force-kill backend; helper should exit within 10s.
pkill -KILL -f "Resources/backend/locwarp-backend$"
sleep 12
ps auxww | grep locwarp-backend | grep -v grep
```

Expect: no rows.

- [ ] **Step 8: Commit acceptance record**

If any of the above fail, file a follow-up bug, but do not block the PR if the failure is unrelated to this work (e.g. an iOS 17+ tunneling issue that pre-dates the split). Otherwise:

```bash
git log --oneline -15  # eyeball the commits before pushing
```

No file changes here; commit step is implicit (no diff).

---

## Self-Review

**Spec coverage check:**

| Spec section | Implementing task(s) |
|---|---|
| §3 TUN routing rationale | n/a — informational |
| §4 Process model | Tasks 9, 10 |
| §5.1 Startup sequence | Tasks 2, 3, 9 |
| §5.2 Steady state (helper PID watch) | Task 2 |
| §5.3 Shutdown | Tasks 2, 3, 9 |
| §6 RPC protocol | Tasks 1, 2, 5, 7 |
| §6.2 Socket permissions | Task 2 |
| §6.3 RPC method table | Tasks 2, 5, 7 (all methods accounted for) |
| §7 File-by-file backend changes | Tasks 3, 4, 5, 6, 7, 8 |
| §7 Electron changes | Task 9 |
| §7 Dev mode | Task 10 |
| §8 Migration | Task 2 (helper-side `migrate_user_state` + test) |
| §9 Testing | Each task ships TDD; §9.3 BAT lives in Task 11 |
| §10 Rollback | n/a — single revert |
| §12 Acceptance criteria | Task 11 |

**Placeholder scan:** no "TBD", "TODO", or vague "handle errors" steps. The `--tunnel-helper` early branch and the helper PID watchdog are spelled out in code.

**Type consistency:** `TunnelHelperClient` exposes `open_wifi_tunnel`, `open_usb_tunnel`, `close_tunnel`, `list_tunnels`, `ping`, `shutdown`, `migrate_user_state` — referenced consistently by callers in Tasks 3, 6, 7. `HelperServer._tunnels: dict[str, _TunnelRunner | _UsbTunnelRunner]` — both runners share `info` / `stop()` so `close_tunnel`/`list_tunnels` don't need to distinguish them. The user-side `TunnelRunner` facade exposes `start(udid, ip, port)`, `stop()`, `is_running()`, `info`, `target_ip`, `target_port` — matches the original surface.

---

**Plan complete and saved to `docs/plans/2026-05-12-elevated-tunnel-helper-implementation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
