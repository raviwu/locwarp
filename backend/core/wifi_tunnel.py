"""User-side WiFi tunnel facade.

The original ``TunnelRunner`` body ran the pymobiledevice3 tunnel as
an asyncio task whose completion signalled "tunnel is gone" to the
``_per_tunnel_watchdog`` in ``api/device.py``. After the helper split
the actual tunnel runs in the elevated helper; the facade gives the
watchdog the same task-completion contract by spawning a poll loop
that watches ``helper.list_tunnels()`` for the UDID's disappearance.

Public surface (``start``, ``stop``, ``is_running``, ``info``,
``target_ip``, ``target_port``, ``task``) matches the original so
callers (``device_manager``, the WiFi-tunnel API endpoint, the
watchdog) need no changes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from services.tunnel_helper_client import TunnelHelperClient

logger = logging.getLogger("wifi_tunnel")

# Poll interval for detecting helper-side tunnel death. Shorter than
# the helper's 5s parent-watchdog so the backend reacts to lost
# tunnels before the helper notices a dead backend in the other
# direction.
TUNNEL_LIVENESS_POLL = 2.0

# Singleton, set by main.py's lifespan once the helper client has
# connected. Tests inject a fake via set_helper_client(...). Leaving
# this at module level keeps the facade lightweight — callers don't
# have to thread the client through every TunnelRunner construction.
_helper_client: Optional[TunnelHelperClient] = None


def set_helper_client(client: Optional[TunnelHelperClient]) -> None:
    """Hook for main.py's lifespan to inject the connected client.

    Tests pass a duck-typed fake (any object with the right async
    methods) or ``None`` to reset between cases.
    """
    global _helper_client
    _helper_client = client


class TunnelRunner:
    """Proxy facade — see module docstring."""

    def __init__(self) -> None:
        self.info: Optional[dict] = None
        self.target_ip: Optional[str] = None
        self.target_port: Optional[int] = None
        self.task: Optional[asyncio.Task] = None
        self._udid: Optional[str] = None
        self._stop_event: asyncio.Event = asyncio.Event()

    def is_running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(self, udid: str, ip: str, port: int, timeout: float = 20.0) -> dict:
        if _helper_client is None:
            raise RuntimeError("tunnel helper client is not configured")
        info = await _helper_client.open_wifi_tunnel(udid=udid, ip=ip, port=port)
        self.info = info
        self.target_ip = ip
        self.target_port = port
        self._udid = udid
        self._stop_event = asyncio.Event()
        # Spawn a liveness-poll task. Completion semantics mirror the
        # original in-process TunnelRunner: task done = tunnel gone,
        # via either local stop() or helper-side disappearance.
        self.task = asyncio.create_task(
            self._monitor_liveness(),
            name=f"wifi-tunnel-monitor-{udid}",
        )
        return dict(info)

    async def _monitor_liveness(self) -> None:
        assert self._udid is not None
        client = _helper_client
        if client is None:
            return
        while not self._stop_event.is_set():
            try:
                # Wait either for stop or for the next poll tick.
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=TUNNEL_LIVENESS_POLL,
                )
                # Event fired → caller asked us to stop. Exit cleanly.
                return
            except asyncio.TimeoutError:
                pass  # tick — check helper-side liveness
            try:
                tunnels = await client.list_tunnels()
            except Exception:
                logger.exception(
                    "list_tunnels rpc failed during liveness poll for %s; treating as still-alive",
                    self._udid,
                )
                continue
            if not any(t.get("udid") == self._udid for t in tunnels):
                logger.warning("helper reports tunnel for %s is gone", self._udid)
                return  # task completes; watchdog will restart

    async def stop(self) -> None:
        # Always release facade state, regardless of whether the helper
        # is reachable.
        self._stop_event.set()
        task = self.task
        self.task = None
        udid = self._udid
        self.info = None
        self._udid = None

        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        if udid is not None and _helper_client is not None:
            try:
                await _helper_client.close_tunnel(udid=udid)
            except Exception:
                logger.exception("close_tunnel rpc failed for %s", udid)
