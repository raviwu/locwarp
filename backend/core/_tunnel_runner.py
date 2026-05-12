"""Helper-internal TunnelRunner.

This holds /dev/utunN open via pymobiledevice3.remote.tunnel_service.
The user-context backend MUST NOT import this module — the leading
underscore signals "helper-only". The user-side facade lives in
core/wifi_tunnel.py.
"""

import asyncio
import logging

logger = logging.getLogger("wifi_tunnel")


class TunnelRunner:
    """Owns the tunnel asyncio task and its RSD info."""

    def __init__(self) -> None:
        self.info: dict | None = None
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self._stop: asyncio.Event = asyncio.Event()
        self._ready: asyncio.Event = asyncio.Event()
        self._error: BaseException | None = None
        # Original (ip, port) the runner was launched against. Useful so
        # callers can tell "is the running tunnel actually for the same
        # iPhone the user is trying to connect to right now?" without
        # having to re-resolve the udid.
        self.target_ip: str | None = None
        self.target_port: int | None = None

    def is_running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def _run(self, udid: str, ip: str, port: int) -> None:
        from pymobiledevice3.remote.tunnel_service import (
            create_core_device_tunnel_service_using_remotepairing,
        )
        try:
            logger.info("Connecting to RemotePairing service at %s:%d", ip, port)
            service = await create_core_device_tunnel_service_using_remotepairing(
                udid, ip, port,
            )
            logger.info("RemotePairing connected (identifier=%s)", service.remote_identifier)

            async with service.start_tcp_tunnel() as tunnel:
                self.info = {
                    "rsd_address": tunnel.address,
                    "rsd_port": tunnel.port,
                    "interface": tunnel.interface,
                    "protocol": str(tunnel.protocol),
                }
                logger.info(
                    "WiFi tunnel established: %s:%d iface=%s",
                    tunnel.address, tunnel.port, tunnel.interface,
                )
                self._ready.set()

                # Wait until either (a) the user requests stop, or (b) the
                # underlying TCP socket dies. pymobiledevice3's sock_read_task
                # exits silently on OSError / ConnectionReset and does NOT
                # propagate out of the start_tcp_tunnel context, so without
                # this wait_closed() race the runner task hangs forever even
                # after the iPhone has gone away. _per_tunnel_watchdog only
                # restarts when runner.task ends, so detecting tunnel death
                # here is what wires up the existing auto-restart machinery.
                stop_task = asyncio.create_task(self._stop.wait())
                closed_task = asyncio.create_task(tunnel.client.wait_closed())
                try:
                    _, pending = await asyncio.wait(
                        [stop_task, closed_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    for t in (stop_task, closed_task):
                        if not t.done():
                            t.cancel()
                            try:
                                await t
                            except (asyncio.CancelledError, Exception):
                                pass

                if self._stop.is_set():
                    logger.info("Tunnel stop signal received; closing context")
                else:
                    logger.warning(
                        "Tunnel underlying TCP socket died (sock_read_task exited); "
                        "exiting runner so watchdog can restart"
                    )
        except BaseException as exc:
            self._error = exc
            self._ready.set()
            raise
        finally:
            self.info = None

    async def start(self, udid: str, ip: str, port: int, timeout: float = 20.0) -> dict:
        """Start the tunnel and wait until RSD info is ready.

        Raises asyncio.TimeoutError on timeout or the underlying exception
        if the tunnel setup failed before becoming ready.
        """
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._error = None
        self.info = None
        self.target_ip = ip
        self.target_port = port
        self.task = asyncio.create_task(self._run(udid, ip, port))
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._stop.set()
            try:
                await asyncio.wait_for(self.task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass
            self.task = None
            raise
        if self._error is not None:
            exc = self._error
            self.task = None
            raise exc
        return dict(self.info or {})

    async def stop(self) -> None:
        if not self.is_running():
            self.task = None
            self.info = None
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self.task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Tunnel task did not exit in 5s; cancelling")
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        except (asyncio.CancelledError, Exception):
            pass
        self.task = None
        self.info = None


class UsbTunnelRunner:
    """USB iOS 17+ tunnel runner, helper-internal.

    Symmetric to TunnelRunner but uses CoreDeviceTunnelProxy over a
    usbmux-backed lockdown connection. The helper constructs the
    lockdown itself — the backend does not share state with the helper.
    """

    def __init__(self) -> None:
        self.info: dict | None = None
        self._lockdown = None
        self._proxy = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._error: BaseException | None = None

    async def _run(self, udid: str) -> None:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.remote.tunnel_service import CoreDeviceTunnelProxy
        try:
            # create_using_usbmux is async in pymobiledevice3 — mirror
            # device_manager._connect_tunnel's prior usage which awaited
            # create_using_usbmux(serial=udid).
            self._lockdown = await create_using_usbmux(serial=udid)
            self._proxy = await CoreDeviceTunnelProxy.create(self._lockdown)
            async with self._proxy.start_tcp_tunnel() as tun:
                self.info = {
                    "rsd_address": tun.address,
                    "rsd_port": tun.port,
                    "interface": tun.interface,
                    "protocol": str(tun.protocol),
                }
                logger.info(
                    "USB tunnel established for %s: %s:%d iface=%s",
                    udid, tun.address, tun.port, tun.interface,
                )
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
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass
            self._task = None
            raise
        if self._error is not None:
            exc = self._error
            self._task = None
            raise exc
        return dict(self.info or {})

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            self._task = None
            self.info = None
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("USB tunnel task did not exit in 5s; cancelling")
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None
        self.info = None
