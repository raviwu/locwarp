"""DevicePort — the per-coordinate device-push seam the engine drives."""

from __future__ import annotations

from typing import Protocol


class DevicePort(Protocol):
    async def set_location(self, udid: str, lat: float, lng: float) -> None: ...
    async def clear(self, udid: str) -> None: ...
