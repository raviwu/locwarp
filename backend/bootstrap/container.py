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
        engine_registry,
        cooldown_timer,
        coord_formatter,
        helper_client,
        geocoding_service,
        route_service,
        gpx_service,
        bookmark_manager,
        route_manager,
    ) -> None:
        self.clock = MonotonicClock()
        self.device_manager = device_manager
        self.event_publisher = event_publisher
        self.tunnel_registry = tunnel_registry
        self._engines_lock = engines_lock
        # engine_registry (AppState) is now a first-class attribute so api/deps.py
        # can inject it into endpoints — not just forwarded into DeviceService.
        self.engine_registry = engine_registry
        self.cooldown_timer = cooldown_timer
        self.coord_formatter = coord_formatter
        self.helper_client = helper_client
        self.geocoding_service = geocoding_service
        self.route_service = route_service
        self.gpx_service = gpx_service
        # bookmark_manager / route_manager are stored for the fallback (unit tests
        # that pass a fake engine_registry without these attrs). In production the
        # properties below delegate live to engine_registry so they always reflect
        # post-load_state() values.
        self._bookmark_manager = bookmark_manager
        self._route_manager = route_manager

        from services.device_service import DeviceService
        self.device_service = DeviceService(
            device_manager=self.device_manager,
            tunnel_registry=self.tunnel_registry,
            engine_registry=engine_registry,
        )

    @property
    def bookmark_manager(self):
        """Live read from engine_registry so the manager built inside
        load_state() (AFTER this Container is constructed at import time) is
        returned without rebuilding the Container. The _bookmark_manager
        fallback is ONLY for unit tests that inject a bare fake registry with
        no bookmark_manager attribute; in production engine_registry is the
        AppState and always carries it (None until load_state, real after).
        The 503 guard in api.deps.get_bookmark_manager covers the None window."""
        reg = self.engine_registry
        if reg is not None and hasattr(reg, "bookmark_manager"):
            return reg.bookmark_manager
        return self._bookmark_manager

    @property
    def route_manager(self):
        """Live read from engine_registry so the manager built inside
        load_state() (AFTER this Container is constructed at import time) is
        returned without rebuilding the Container. The _route_manager
        fallback is ONLY for unit tests that inject a bare fake registry with
        no route_manager attribute; in production engine_registry is the
        AppState and always carries it (None until load_state, real after).
        The 503 guard in api.deps.get_route_manager covers the None window."""
        reg = self.engine_registry
        if reg is not None and hasattr(reg, "route_manager"):
            return reg.route_manager
        return self._route_manager
