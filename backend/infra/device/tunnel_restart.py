"""Relocated home for attempt_tunnel_restart — the one-shot WiFi-tunnel
restart used by the per-tunnel watchdog and the WifiTunnelRegistry.

Previously this body lived in api/device.py, forcing infra/device/wifi_tunnel.py
to lazily import _attempt_tunnel_restart out of api.device — an infra->api edge.
Hosting it here, with every api/main collaborator INJECTED (engine_registry,
device_manager, broadcast, auto_sync, watchdog_factory), lets both api/device.py
(via a thin wrapper) and the WifiTunnelRegistry (via a ctor resolver) drive it
WITHOUT importing api. The registry state (_tunnels / _tunnel_watchdogs /
_tunnels_lock) already lives in infra.device.tunnel_state.

Behavior is identical to the pre-relocation api/device._attempt_tunnel_restart.
"""

from __future__ import annotations

import asyncio
import logging

from core.wifi_tunnel import TunnelRunner
from infra.device.tunnel_state import _tunnels, _tunnel_watchdogs, _tunnels_lock

_tunnel_logger = logging.getLogger("wifi_tunnel")


async def attempt_tunnel_restart(
    udid: str,
    ip: str,
    port: int,
    snapshot: dict | None,
    original_runner,
    *,
    engine_registry,
    device_manager,
    broadcast,
    auto_sync,
    watchdog_factory,
) -> bool:
    """Try one restart of the tunnel. On success, swaps in the new runner,
    rebuilds dm._connections + sim engine (since the new RSD interface gets
    a fresh address), and resumes any captured snapshot. Returns True on
    success, False otherwise. Caller decides whether to retry.

    Collaborators are injected so this module never imports api/main:
    ``engine_registry`` is app_state (create_engine_for_device +
    simulation_engines); ``device_manager`` is the live DeviceManager;
    ``broadcast`` is api.websocket.broadcast; ``auto_sync`` is
    main._auto_sync_new_device_to_primary; ``watchdog_factory(udid, runner)``
    creates and returns the per-tunnel watchdog task (api._per_tunnel_watchdog).
    """
    new_runner = TunnelRunner()
    try:
        info = await new_runner.start(udid, ip, port, timeout=10.0)
    except Exception as exc:
        _tunnel_logger.warning(
            "Tunnel restart failed for %s: %s: %s",
            udid, type(exc).__name__, exc,
        )
        return False

    new_rsd_address = info.get("rsd_address")
    new_rsd_port = info.get("rsd_port")
    if not new_rsd_address or not new_rsd_port:
        _tunnel_logger.warning(
            "Tunnel restart for %s returned no RSD info; treating as failure",
            udid,
        )
        try:
            await new_runner.stop()
        except Exception:
            pass
        return False

    try:
        async with _tunnels_lock:
            # User may have stopped this tunnel during our async window.
            if _tunnels.get(udid) is not original_runner:
                _tunnel_logger.info(
                    "Tunnel restart for %s racing user stop; discarding new runner",
                    udid,
                )
                try:
                    await new_runner.stop()
                except Exception:
                    pass
                return True  # not really success, but caller should NOT retry
            _tunnels[udid] = new_runner

        # connect_wifi_tunnel internally calls disconnect(udid) if udid
        # already exists, so the old (now-dead) RSD lockdown gets torn
        # down correctly.
        dev_info = await device_manager.connect_wifi_tunnel(new_rsd_address, new_rsd_port)

        # Rebuild the sim engine bound to the new location service. The
        # old engine pointed at the dead RSD and would throw
        # ConnectionTerminatedError on the next teleport / position push.
        await engine_registry.create_engine_for_device(dev_info.udid, force=True)

        # Re-arm the watchdog on the new runner so subsequent blips get
        # the same recovery treatment.
        old_wd = _tunnel_watchdogs.pop(udid, None)
        if old_wd is not None and old_wd is not asyncio.current_task() and not old_wd.done():
            old_wd.cancel()
        _tunnel_watchdogs[udid] = watchdog_factory(udid, new_runner)

        # Resume any in-flight simulation (navigate / loop / multi-stop /
        # random_walk) so the iPhone keeps moving instead of stopping at
        # the blip point. Snapshot only exists when this device was the
        # one driving the sim — followers don't capture one.
        if snapshot is not None:
            new_eng = engine_registry.simulation_engines.get(dev_info.udid)
            if new_eng is not None:
                _tunnel_logger.info(
                    "Resuming sim from snapshot after tunnel restart for %s (kind=%s)",
                    dev_info.udid, snapshot.get("kind"),
                )
                asyncio.create_task(new_eng.resume_from_snapshot(snapshot))
        else:
            # Group-mode: if this WiFi device was a follower of some other
            # primary (USB or WiFi), restart broke the follower task. Re-
            # arm the same teleport-to-primary + attach-as-follower flow
            # the USB watchdog uses for re-plugged USB devices, so dual /
            # triple-device groups stay locked together across a blip.
            try:
                asyncio.create_task(auto_sync(dev_info.udid))
            except Exception:
                _tunnel_logger.exception(
                    "Auto-sync after tunnel restart failed for %s", dev_info.udid,
                )

        try:
            await broadcast("tunnel_recovered", {
                "udid": dev_info.udid,
                "rsd_address": new_rsd_address,
                "rsd_port": new_rsd_port,
            })
            await broadcast("device_connected", {
                "udid": dev_info.udid,
                "name": dev_info.name,
                "ios_version": dev_info.ios_version,
                "connection_type": "Network",
            })
        except Exception:
            _tunnel_logger.exception("Failed to broadcast tunnel_recovered for %s", udid)

        _tunnel_logger.info(
            "Tunnel restart succeeded for %s (rsd %s:%d)",
            udid, new_rsd_address, new_rsd_port,
        )
        return True
    except Exception:
        _tunnel_logger.exception(
            "Tunnel restart for %s started but post-setup failed; rolling back",
            udid,
        )
        # Roll back the new runner we registered. Leave the old runner
        # entry empty so the outer retry loop tries a fresh new one.
        async with _tunnels_lock:
            if _tunnels.get(udid) is new_runner:
                _tunnels.pop(udid, None)
        try:
            await new_runner.stop()
        except Exception:
            pass
        return False
