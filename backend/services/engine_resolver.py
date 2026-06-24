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

_log = logging.getLogger("locwarp")


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
