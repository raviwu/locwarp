"""FastAPI dependency providers — one per service, reading app.state.container."""

from __future__ import annotations

from fastapi import Request


def get_container(request: Request):
    return request.app.state.container


def get_device_manager(request: Request):
    return request.app.state.container.device_manager


def get_device_service(request: Request):
    # DeviceService is added in Task 7; until then this provider is unused.
    return request.app.state.container.device_service
