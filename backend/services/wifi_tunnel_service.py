"""WiFi-tunnel use-case orchestration carved out of api/device.py.

Pure candidate computation lives here (no I/O); the api layer resolves the
live collaborators (dm connections, cached pair records) and delegates.
"""
from __future__ import annotations

import asyncio

from services.location_service import DeviceLostError


def build_tunnel_udid_candidates(
    req_udid: str | None,
    req_ip: str,
    req_port: int,
    *,
    connected_udids: list[str],
    pair_record_idents: list[str],
) -> list[str]:
    """Return udids to try for an incoming /wifi/tunnel/start request, in
    priority order: explicit udid > USB-tracked > cached pair-record idents
    (already mtime-sorted by the caller). De-duped, order preserved. Falls
    back to a ``pending:ip:port`` placeholder when nothing else is known.

    Pure: the caller supplies connected_udids (dm._connections.keys()) and
    pair_record_idents (stripped from ~/.pymobiledevice3 stems).
    """
    candidates: list[str] = []

    def _add(c: str | None) -> None:
        if c and c not in candidates:
            candidates.append(c)

    _add(req_udid)
    for u in connected_udids:
        _add(u)
    for ident in pair_record_idents:
        _add(ident)

    if not candidates:
        candidates.append(f"pending:{req_ip}:{req_port}")
    return candidates


async def run_usb_fallback(
    was_network_udids,
    *,
    device_manager,
    engine_registry,
    discover_devices,
    publish,
    logger,
) -> None:
    """After a WiFi tunnel stop, re-attach via USB any udid that (a) was just
    in WiFi, (b) is NOT sticky-denied, and (c) shows up as USB right now.
    On engine-creation failure, roll the connection back and emit device_error.
    Collaborators injected so this never imports api/main."""
    try:
        devices = await discover_devices()
        for udid in was_network_udids:
            if udid in device_manager.sticky_user_denied:
                logger.info("USB fallback: skipping %s (sticky_user_denied)", udid)
                continue
            usb_dev = next(
                (d for d in devices if d.udid == udid and d.connection_type == "USB"),
                None,
            )
            if usb_dev is None:
                logger.info(
                    "USB fallback: skipping %s (not visible as USB after tunnel stop)",
                    udid,
                )
                continue
            try:
                await device_manager.connect(usb_dev.udid)
            except Exception:
                logger.exception("USB fallback: connect failed for %s", usb_dev.udid)
                continue
            try:
                await engine_registry.create_engine_for_device(usb_dev.udid, force=True)
                logger.info("Switched back to USB connection: %s", usb_dev.udid)
            except Exception:
                logger.exception(
                    "USB fallback: engine creation failed for %s; rolling back",
                    usb_dev.udid,
                )
                try:
                    await device_manager.disconnect(usb_dev.udid)
                except Exception:
                    pass
                await engine_registry.remove_engine(usb_dev.udid)
                try:
                    await publish(("device_error", {
                        "udid": usb_dev.udid,
                        "stage": "usb_fallback",
                        "error": "USB fallback engine creation failed",
                    }))
                except Exception:
                    pass
    except Exception:
        logger.exception("USB fallback after tunnel stop failed")


class WifiTunnelService:
    def __init__(self, *, tunnels, tunnels_lock, tunnel_watchdogs, engines_for,
                 attempt_restart, cleanup_wifi, publish, logger,
                 sim_state_disconnected, restart_backoff):
        self._tunnels = tunnels
        self._tunnels_lock = tunnels_lock
        self._tunnel_watchdogs = tunnel_watchdogs
        self._engines_for = engines_for
        self._attempt_restart = attempt_restart
        self._cleanup_wifi = cleanup_wifi
        self._publish = publish
        self._logger = logger
        self._sim_state_disconnected = sim_state_disconnected
        self._restart_backoff = restart_backoff

    async def run_watchdog(self, udid, runner) -> None:
        """Watch a single device's tunnel. If the runner's task dies (WiFi
        blip, iPhone locked, admin revoked), capture the sim state, then try
        up to len(self._restart_backoff) restarts with backoff. Each restart
        rebuilds the device manager connection (the new TUN interface gets a
        fresh RSD address) and resumes the sim from snapshot so the iPhone
        keeps moving across the blip. Other tunnels stay isolated."""
        try:
            task = runner.task
            if task is None:
                return
            exit_exc: BaseException | None = None
            try:
                await task
            except asyncio.CancelledError:
                return
            except BaseException as _e:
                exit_exc = _e

            # Classify the exit cause for the WS payload. A clean tunnel-poll
            # return keeps the legacy reason='task_exited' (no last_error). A
            # DeviceLostError carries the richer classification + last_error.
            _reason_payload: dict = {"reason": "task_exited"}
            if isinstance(exit_exc, DeviceLostError):
                _reason_payload = {"reason": exit_exc.reason}
                if exit_exc.last_error is not None:
                    _reason_payload["last_error"] = exit_exc.last_error

            # If the registry was already updated (explicit stop, re-key on
            # reconnect, etc.) this watchdog is stale.
            if self._tunnels.get(udid) is not runner:
                return

            ip = runner.target_ip
            port = runner.target_port

            self._logger.warning(
                "Tunnel for %s exited unexpectedly (target=%s:%s); will attempt %d restart(s)",
                udid, ip, port, len(self._restart_backoff),
            )
            _degraded_payload: dict = {"udid": udid, **_reason_payload}
            if self._restart_backoff:
                # Announce the first upcoming retry so the UI can render
                # "attempt 1/N, retrying in <next_delay_s>s" + a live countdown.
                # This event fires ONCE, before the retry loop; attempt is the
                # first attempt and next_delay_s is the seconds until it runs.
                _degraded_payload["attempt"] = 1
                _degraded_payload["max_attempts"] = len(self._restart_backoff)
                _degraded_payload["next_delay_s"] = self._restart_backoff[0]
            try:
                await self._publish(("tunnel_degraded", _degraded_payload))
            except Exception:
                self._logger.exception("Failed to emit tunnel_degraded event")

            if ip is None or port is None:
                # No target captured; we have nothing to retry against. Fall
                # through to teardown.
                self._logger.warning(
                    "Tunnel for %s has no captured target ip/port; skipping retries",
                    udid,
                )
            else:
                snapshot: dict | None = None
                old_eng = self._engines_for(udid)
                if old_eng is not None:
                    try:
                        snapshot = old_eng.capture_resumable_snapshot()
                        if snapshot:
                            self._logger.info(
                                "Captured resumable snapshot for %s before tunnel restart (kind=%s)",
                                udid, snapshot.get("kind"),
                            )
                    except Exception:
                        self._logger.exception("capture_resumable_snapshot failed for %s", udid)

                    # Park the engine while we restart. Without this, multi-stop /
                    # loop / random-walk keep iterating to the next leg, each call
                    # burning ~3s in DvtLocationService._reconnect retries against
                    # the dead RSD before raising DeviceLostError, then the handler
                    # immediately tries the next leg. The log fills with "Giving up
                    # on this route after repeated push failures" every ~6s for as
                    # long as the watchdog is mid-restart. Cancelling the active
                    # task here halts the thrash; on a successful restart, the
                    # snapshot we just captured drives resume_from_snapshot back to
                    # the same leg / segment.
                    try:
                        if self._sim_state_disconnected is not None:
                            old_eng.state = self._sim_state_disconnected
                            try:
                                await old_eng._emit("state_change", {"state": old_eng.state.value})
                            except Exception:
                                self._logger.debug(
                                    "Disconnected state_change emit failed during watchdog pause",
                                    exc_info=True,
                                )
                        old_eng._stop_event.set()
                        old_eng._pause_event.set()  # unstick anyone awaiting pause_event
                        active = getattr(old_eng, "_active_task", None)
                        if active is not None and not active.done():
                            active.cancel()
                    except Exception:
                        self._logger.exception(
                            "Failed to park engine for %s before tunnel restart", udid,
                        )

                for attempt, delay in enumerate(self._restart_backoff, start=1):
                    try:
                        await asyncio.sleep(delay)
                    except asyncio.CancelledError:
                        return

                    # User may have explicitly stopped or replaced this tunnel
                    # during the sleep; if so, abort the retry loop.
                    if self._tunnels.get(udid) is not runner:
                        self._logger.info(
                            "Tunnel for %s no longer registered (user stop?); aborting retries",
                            udid,
                        )
                        return

                    self._logger.info(
                        "Tunnel restart attempt %d/%d for %s (after %.0fs backoff)",
                        attempt, len(self._restart_backoff), udid, delay,
                    )
                    ok = await self._attempt_restart(udid, ip, port, snapshot, runner)
                    if ok:
                        # On success the new watchdog has been armed and this
                        # one's job is done.
                        return

            # All retries exhausted (or no target to retry against).
            self._logger.warning(
                "Tunnel for %s could not be restarted; tearing down WiFi connection",
                udid,
            )
            async with self._tunnels_lock:
                current = self._tunnels.get(udid)
                if current is runner:
                    self._tunnels.pop(udid, None)
                wd = self._tunnel_watchdogs.pop(udid, None)
                if wd is not None and wd is not asyncio.current_task() and not wd.done():
                    wd.cancel()
                await self._cleanup_wifi(udid, caller="watchdog_tunnel_died")
                try:
                    await self._publish(("tunnel_lost", {"udid": udid, **_reason_payload}))
                except Exception:
                    self._logger.exception("Failed to emit tunnel_lost event")
        except asyncio.CancelledError:
            raise
