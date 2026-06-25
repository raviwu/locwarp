"""EngineResolver — resolve/rebuild the active SimulationEngine.

Lifted from api/location.py::_engine so the controller becomes a thin
boundary (it maps EngineUnavailableError -> HTTPException(400)). Behavior is
byte-identical: the same direct-hit -> primary -> discover -> attempt-1
rebuild -> attempt-2 hard-reset ladder, with the same two verbatim 400
messages (both carrying code "no_device").
"""
from __future__ import annotations

import asyncio
import logging

from domain.errors import EngineUnavailableError
from services.location_service import DeviceLostError

_log = logging.getLogger("locwarp")

_DEVICE_LOST_REASON_MESSAGES: dict[str, str] = {
    DeviceLostError.REASON_TUNNEL_DEAD: "WiFi 連線中斷,請確認手機 WiFi 與電腦同網段、解鎖手機後再試",
    DeviceLostError.REASON_LOCKDOWN_DEAD: "裝置回應停止,請解鎖手機螢幕後再試",
    DeviceLostError.REASON_DDI_MISSING: "Developer Disk Image 未掛載,請重新插拔 USB 或重新啟動裝置",
    DeviceLostError.REASON_USB_GONE: "USB 已拔除,請重新插上後再操作",
    DeviceLostError.REASON_UNKNOWN: "裝置連線中斷(USB 拔除或 Tunnel 死亡),請重新插上 USB 後再操作",
}


def _device_lost_message(exc: Exception) -> tuple[str, str]:
    cause: Exception | None = exc
    seen: set[int] = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, DeviceLostError):
            reason = getattr(cause, "reason", DeviceLostError.REASON_UNKNOWN) or DeviceLostError.REASON_UNKNOWN
            return reason, _DEVICE_LOST_REASON_MESSAGES.get(
                reason, _DEVICE_LOST_REASON_MESSAGES[DeviceLostError.REASON_UNKNOWN],
            )
        cause = cause.__cause__
    return (DeviceLostError.REASON_UNKNOWN, _DEVICE_LOST_REASON_MESSAGES[DeviceLostError.REASON_UNKNOWN])


class EngineResolver:
    def __init__(self, engine_registry, device_manager) -> None:
        self._reg = engine_registry
        self._dm = device_manager

    async def resolve_engine(self, udid: str | None = None):
        app_state = self._reg
        # Direct hit on the requested udid.
        if udid is not None:
            eng = app_state.get_engine(udid)
            if eng is not None:
                return eng
        if udid is None and app_state.simulation_engine is not None:
            return app_state.simulation_engine

        dm = self._dm
        target_udid = udid or next(iter(dm._connections.keys()), None)
        if target_udid is None:
            for attempt in range(10):
                try:
                    discovered = await dm.discover_devices()
                    if discovered:
                        target_udid = discovered[0].udid
                        if attempt > 0:
                            _log.info("discover_devices returned device on attempt %d", attempt + 1)
                        break
                except Exception:
                    _log.exception("discover_devices failed during lazy rebuild (attempt %d)", attempt + 1)
                await asyncio.sleep(1.0)

        if target_udid is None:
            raise EngineUnavailableError(
                "no_device", "尚未連接任何 iOS 裝置,請先透過 USB 連線",
            )

        # Attempt 1: rebuild engine on top of existing connection
        _log.info("simulation_engine missing; attempt 1 (rebuild) for %s", target_udid)
        try:
            await app_state.create_engine_for_device(target_udid)
            rebuilt = app_state.get_engine(target_udid) if udid is not None else app_state.simulation_engine
            if rebuilt is not None:
                _log.info("Engine rebuild succeeded on attempt 1")
                return rebuilt
        except Exception:
            _log.exception("Engine rebuild (attempt 1) failed for %s", target_udid)

        # Attempt 2: hard reset — disconnect + reconnect + rebuild
        _log.info("attempt 2 (hard reset) for %s", target_udid)
        try:
            try:
                await dm.disconnect(target_udid)
            except Exception:
                _log.warning("disconnect during hard reset failed; proceeding", exc_info=True)
            await dm.connect(target_udid)
            await app_state.create_engine_for_device(target_udid)
            rebuilt = app_state.get_engine(target_udid) if udid is not None else app_state.simulation_engine
            if rebuilt is not None:
                _log.info("Engine rebuild succeeded on attempt 2")
                return rebuilt
        except Exception:
            _log.exception("Engine rebuild (attempt 2, hard reset) failed for %s", target_udid)

        raise EngineUnavailableError(
            "no_device",
            "裝置連線已失效,請嘗試重新插拔 USB 或重新啟動 LocWarp(詳見 ~/.locwarp/logs/backend.log)",
        )

    async def with_recovery(self, udid: str | None, op):
        try:
            return await op()
        except DeviceLostError:
            if not udid:
                raise
            _log.warning("DeviceLostError on %s; attempting full_reconnect safety-net retry", udid)

            # Capture a resumable snapshot BEFORE the reconnect tears down and
            # replaces the engine.  Mirrors the watchdog path exactly:
            # wifi_tunnel_service.py::run_watchdog calls capture_resumable_snapshot
            # then passes the snapshot to attempt_restart.  Here we do the same so
            # a running navigate / loop / multi-stop / random_walk route survives
            # the WiFi-tunnel restart that full_reconnect triggers.
            snapshot: dict | None = None
            old_eng = self._reg.simulation_engines.get(udid)
            if old_eng is not None:
                try:
                    snapshot = old_eng.capture_resumable_snapshot()
                    if snapshot:
                        _log.info(
                            "Captured resumable snapshot for %s before full_reconnect "
                            "(kind=%s)",
                            udid, snapshot.get("kind"),
                        )
                except Exception:
                    _log.exception("capture_resumable_snapshot failed for %s", udid)

            try:
                recovered = await self._dm.full_reconnect(udid)
            except Exception:
                _log.exception("full_reconnect raised during safety-net retry")
                recovered = False
            if not recovered:
                _log.warning("full_reconnect failed for %s; surfacing original error", udid)
                raise

            # Resume any in-flight simulation on the NEW engine, exactly as
            # tunnel_restart.py::attempt_tunnel_restart does (lines 110-117).
            if snapshot is not None:
                new_eng = self._reg.simulation_engines.get(udid)
                if new_eng is not None:
                    _log.info(
                        "Resuming sim from snapshot after full_reconnect for %s (kind=%s)",
                        udid, snapshot.get("kind"),
                    )
                    asyncio.create_task(new_eng.resume_from_snapshot(snapshot))

            _log.info("full_reconnect succeeded for %s; retrying op once", udid)
            return await op()

    async def cleanup_device_lost(self, exc: Exception, udid: str) -> tuple[str, str]:
        app_state = self._reg
        dm = self._dm
        lost_udids = [udid] if udid in dm._connections else []
        if not lost_udids:
            _log.info("device_lost: udid %s no longer in _connections; nothing to clean", udid)
        for u in lost_udids:
            old_eng = app_state.simulation_engines.get(u)
            if old_eng is not None:
                try:
                    old_eng._stop_event.set()
                    old_eng._pause_event.set()
                    active = getattr(old_eng, "_active_task", None)
                    if active is not None and not active.done():
                        active.cancel()
                except Exception:
                    _log.debug("device_lost: failed to stop old engine %s", u, exc_info=True)
            try:
                await dm.disconnect(u)
                _log.info("device_lost cleanup: disconnected %s", u)
            except Exception:
                _log.exception("device_lost cleanup: disconnect failed for %s", u)
            await app_state.remove_engine(u)
        try:
            await dm._events.publish(("device_disconnected", {
                "udids": lost_udids,
                "reason": "device_lost",
                "error": str(exc),
                "remaining_count": len(dm._connections),
            }))
        except Exception:
            _log.exception("Failed to broadcast device_disconnected")
        return _device_lost_message(exc)
