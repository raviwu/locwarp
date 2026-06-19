"""Composition root. Builds the wired object graph for the app."""

from __future__ import annotations

import asyncio
import time


class MonotonicClock:
    """Callable returning a monotonic float — the production clock seam."""

    def __call__(self) -> float:
        return time.monotonic()


class Container:
    def __init__(self) -> None:
        from api.websocket import broadcast as _ws_broadcast
        from infra.events.ws_event_publisher import WsEventPublisher
        from infra.device.wifi_tunnel import WifiTunnelRegistry
        from core.device_manager import DeviceManager

        self.clock = MonotonicClock()
        self.event_publisher = WsEventPublisher(broadcast=_ws_broadcast)
        self.tunnel_registry = WifiTunnelRegistry()
        self.device_manager = DeviceManager(
            event_publisher=self.event_publisher,
            tunnel_registry=self.tunnel_registry,
        )
        # Guards create_engine_for_device's check->await->assign and the
        # watchdog pop/promote (used via app_state in this phase).
        self._engines_lock = asyncio.Lock()

    def engine_factory(self, location_service, event_callback=None):
        from core.simulation_engine import SimulationEngine

        return SimulationEngine(location_service, event_callback)

    @property
    def device_service(self):
        raise NotImplementedError("DeviceService wired in Task 7")
