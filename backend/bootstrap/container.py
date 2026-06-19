"""Composition root. Thin DI holder that wraps the singletons AppState owns.

Container is NOT a factory — it never constructs DeviceManager,
WsEventPublisher, WifiTunnelRegistry, or asyncio.Lock on its own.
The real instances live in AppState (main.py); this class just exposes
them under dependency-injection-friendly names so api/deps.py can
resolve them from app.state.container.
"""

from __future__ import annotations

import asyncio
import time


class MonotonicClock:
    """Callable returning a monotonic float — the production clock seam."""

    def __call__(self) -> float:
        return time.monotonic()


class Container:
    def __init__(
        self,
        *,
        device_manager,
        event_publisher,
        tunnel_registry,
        engines_lock: asyncio.Lock,
    ) -> None:
        self.clock = MonotonicClock()
        self.device_manager = device_manager
        self.event_publisher = event_publisher
        self.tunnel_registry = tunnel_registry
        # The SAME lock AppState uses for create_engine_for_device and the
        # watchdog pop/promote — one lock, shared by reference.
        self._engines_lock = engines_lock

    @property
    def device_service(self):
        raise NotImplementedError("DeviceService wired in Task 7")
