"""DeviceService — connect/disconnect/repair use-cases.

Constructor-injected device_manager + tunnel_registry + engine_registry
(the object exposing create_engine_for_device, i.e. AppState today / Container
later). Keeps thick device internals (pymobiledevice3/usbmux/SIP) behind the
existing narrow helpers; this service only orchestrates ordering.

Forget orchestration is NOT here — its pair-lock-wrapping-_tunnels_lock
ordering and the SIP record-delete async/sync split are coupled to
api/device.py's module-level helpers and deferred to a follow-up.
"""

from __future__ import annotations


class DeviceService:
    def __init__(self, device_manager, tunnel_registry, engine_registry) -> None:
        self._dm = device_manager
        self._tunnels = tunnel_registry
        self._engines = engine_registry

    async def connect(self, udid: str) -> None:
        """Connect via USB (dm.connect) and create a simulation engine."""
        await self._dm.connect(udid)
        await self._engines.create_engine_for_device(udid)

    async def disconnect(self, udid: str) -> None:
        """Disconnect device (USB path) and drop the simulation engine.

        Teardown goes through engine_registry.remove_engine so the pop+promote
        runs under _engines_lock — a concurrent create_engine_for_device cannot
        race the registry mutation.
        """
        await self._dm.disconnect(udid)
        await self._engines.remove_engine(udid)

    async def repair(self, udid: str) -> None:
        """Clear the sticky-denied flag (matches wifi_repair clear_user_denied call)."""
        self._dm.clear_user_denied(udid)
