"""LocationServiceDevicePort — DevicePort backed by a device-bound LocationService.

The wrapped location_service is already bound to one device, so udid is ignored.
clear() is a no-op unless the service exposes clear/reset (it does not today).
"""

from __future__ import annotations


class LocationServiceDevicePort:
    def __init__(self, location_service) -> None:
        self._location_service = location_service

    async def set_location(self, udid: str, lat: float, lng: float) -> None:
        await self._location_service.set(lat, lng)

    async def clear(self, udid: str) -> None:
        clear = getattr(self._location_service, "clear", None)
        if clear is not None:
            await clear()
