"""FastAPI dependency providers — one per service, reading app.state.container."""

from __future__ import annotations

from fastapi import HTTPException, Request


def get_container(request: Request):
    return request.app.state.container


def get_device_manager(request: Request):
    return request.app.state.container.device_manager


def get_device_service(request: Request):
    # DeviceService is added in Task 7; until then this provider is unused.
    return request.app.state.container.device_service


def get_engine_registry(request: Request):
    return request.app.state.container.engine_registry


def get_cooldown_timer(request: Request):
    return request.app.state.container.cooldown_timer


def get_coord_formatter(request: Request):
    return request.app.state.container.coord_formatter


def get_helper_client(request: Request):
    return request.app.state.container.helper_client


def get_geocoding_service(request: Request):
    return request.app.state.container.geocoding_service


def get_route_service(request: Request):
    return request.app.state.container.route_service


def get_gpx_service(request: Request):
    return request.app.state.container.gpx_service


def get_bookmark_manager(request: Request):
    mgr = request.app.state.container.bookmark_manager
    if mgr is None:
        raise HTTPException(status_code=503, detail="Bookmark manager not ready")
    return mgr


def get_route_manager(request: Request):
    mgr = request.app.state.container.route_manager
    if mgr is None:
        raise HTTPException(status_code=503, detail="Route manager not ready")
    return mgr


def get_event_publisher(request: Request):
    return request.app.state.container.event_publisher


def _engine_registry_or_main(registry):
    """Return the injected registry when provided; fall back to main.app_state
    for call-sites that cannot receive a Depends (e.g. internal closures)."""
    if registry is not None:
        return registry
    return __import__("main").app_state
