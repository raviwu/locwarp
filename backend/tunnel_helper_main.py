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
import json
import logging
import os
import pwd
import signal
import sys
from pathlib import Path
from typing import Any, Callable, Awaitable

from core._tunnel_runner import TunnelRunner as _TunnelRunner

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


class _HelperRpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


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
        # Set by the ``shutdown`` RPC handler — the connection loop
        # checks this after flushing the response and triggers a clean
        # ``stop()`` once the bytes have made it to the peer. Avoids the
        # previous ``asyncio.sleep(0.05)`` race where the server might
        # tear down before the response had flushed.
        self._stop_after_drain: bool = False
        self._methods: dict[str, Callable[[dict], Awaitable[Any]]] = {
            "ping": self._handle_ping,
            "shutdown": self._handle_shutdown,
            "migrate_user_state": self._handle_migrate_user_state,
        }
        self._tunnels: dict[str, _TunnelRunner] = {}
        self._methods.update({
            "open_wifi_tunnel": self._handle_open_wifi_tunnel,
            "open_usb_tunnel": self._handle_open_usb_tunnel,
            "close_tunnel": self._handle_close_tunnel,
            "list_tunnels": self._handle_list_tunnels,
        })

    # ── lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        # Clear stale socket / status nodes from a previous unclean exit.
        # Use try/except over exists()+unlink — exists() returns False
        # for dangling symlinks, which would then leak through and
        # confuse bind() / write later.
        for path in (self.sock_path, self.status_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.debug("could not remove stale %s: %s", path, exc)

        # Bind with a restrictive umask so the socket node is born
        # 0o600, closing the window where any local user could
        # connect() before _apply_socket_permissions chmods it. The
        # subsequent chmod relaxes to 0o660 for the parent user/group
        # only.
        old_umask = os.umask(0o077)
        try:
            self._server = await asyncio.start_unix_server(
                self._handle_connection, path=str(self.sock_path)
            )
        finally:
            os.umask(old_umask)
        self._apply_socket_permissions()
        self._publish_ready()
        self._watchdog = asyncio.create_task(self._parent_watchdog())
        logger.info("helper listening on %s (parent pid=%d)", self.sock_path, self.parent_pid)

    def _apply_socket_permissions(self) -> None:
        """Make the socket connectable by the parent user.

        Backend runs as ``parent_uid``; helper runs as root. Default
        ``bind()`` produces mode 0600 root:wheel — backend cannot
        connect. Relax to 0660 and chgrp to the parent's primary group.
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

        Tmp-and-rename so the file appearing on disk implies a fully
        written ``READY`` marker, never a half-empty file the backend
        might race against. The tmp file is opened with
        ``O_EXCL|O_NOFOLLOW`` so a pre-existing symlink at the tmp path
        can't trick us into writing through it as root — without these
        flags an attacker could plant ``/tmp/locwarp-helper.status.tmp
        -> /etc/sudoers`` and have the helper clobber sudoers on every
        start.
        """
        tmp = self.status_path.with_suffix(self.status_path.suffix + ".tmp")
        # Best-effort cleanup of a stale .tmp from a prior unclean exit.
        # O_EXCL below catches any race where we lose this cleanup.
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("could not clear stale %s: %s", tmp, exc)
        fd = os.open(
            tmp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o644,
        )
        try:
            os.write(fd, b"READY\n")
        finally:
            os.close(fd)
        os.replace(tmp, self.status_path)

    async def stop(self) -> None:
        # Close any active tunnels first so TUN devices are released cleanly
        # before we tear down the IPC machinery.
        for udid, runner in list(self._tunnels.items()):
            try:
                await runner.stop()
            except Exception:
                logger.exception("error stopping tunnel for %s during shutdown", udid)
        self._tunnels.clear()
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
                # Parent still exists; we just can't signal it. Fine.
                pass

    async def _self_terminate(self) -> None:
        await self.stop()
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
                    req = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    resp = _rpc_error(None, -32700, f"parse error: {exc}")
                else:
                    resp = await self._dispatch(req)
                writer.write((json.dumps(resp) + "\n").encode("utf-8"))
                await writer.drain()
                if self._stop_after_drain:
                    # shutdown RPC asked us to stop after this response
                    # flushed — schedule stop() and return so we don't
                    # try to read more from the about-to-close socket.
                    asyncio.create_task(self.stop())
                    return
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
        # Flag the connection loop — it will call stop() after the
        # current response has been flushed. Deterministic: no sleep
        # racing the writer.drain().
        self._stop_after_drain = True
        return {"ok": True}

    async def _handle_migrate_user_state(self, params: dict) -> dict:
        from migrate_user_state import migrate_user_state

        home = params.get("home")
        uid = params.get("uid")
        gid = params.get("gid")
        if not (isinstance(home, str) and isinstance(uid, int) and isinstance(gid, int)):
            raise _HelperRpcError(-32602, "migrate_user_state needs home:str, uid:int, gid:int")
        # The helper trusts only the parent_uid passed on its argv at
        # launch. Reject any RPC that tries to chown for a different
        # user, or against a home directory that doesn't match that
        # uid's actual pwent. Combined with the socket-permission fix
        # (I3) this prevents even a hijacked connection from triggering
        # arbitrary chown.
        if uid != self.parent_uid:
            raise _HelperRpcError(
                -32602,
                f"uid {uid} does not match parent_uid {self.parent_uid}",
            )
        try:
            pw = pwd.getpwuid(self.parent_uid)
        except KeyError:
            raise _HelperRpcError(
                -32099,
                f"could not resolve parent_uid {self.parent_uid}",
            )
        if Path(home) != Path(pw.pw_dir):
            raise _HelperRpcError(
                -32602,
                f"home {home} does not match parent home {pw.pw_dir}",
            )
        return migrate_user_state(home=home, uid=uid, gid=gid)

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
        # Task 7 fills this in; for now reject cleanly so the wire protocol
        # is exercised end-to-end without a hidden NotImplementedError.
        raise _HelperRpcError(-32099, "open_usb_tunnel not yet implemented (Task 7)")

    async def _handle_close_tunnel(self, params: dict) -> dict:
        udid = params.get("udid")
        if not isinstance(udid, str):
            raise _HelperRpcError(-32602, "close_tunnel needs udid:str")
        runner = self._tunnels.pop(udid, None)
        if runner is None:
            raise _HelperRpcError(-32004, f"unknown tunnel: {udid}")
        try:
            await runner.stop()
        except Exception as exc:
            # The runner is already popped from the registry; log but do
            # not re-raise so the caller sees a clean close response.
            logger.exception("error stopping tunnel for %s: %s", udid, exc)
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
        loop = asyncio.get_running_loop()
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
