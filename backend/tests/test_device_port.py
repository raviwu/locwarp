"""DevicePort: LocationServiceDevicePort.set_location forwards (lat, lng) to the
wrapped location_service.set, ignoring udid (the service is already device-bound)."""

import pytest

from infra.device.location_service_port import LocationServiceDevicePort


class FakeLocationService:
    def __init__(self):
        self.sets = []

    async def set(self, lat, lng):
        self.sets.append((lat, lng))


@pytest.mark.asyncio
async def test_set_location_forwards_lat_lng():
    svc = FakeLocationService()
    port = LocationServiceDevicePort(svc)
    await port.set_location("any-udid", 25.0375, 121.5637)
    assert svc.sets == [(25.0375, 121.5637)]


@pytest.mark.asyncio
async def test_set_location_ignores_udid():
    svc = FakeLocationService()
    port = LocationServiceDevicePort(svc)
    await port.set_location("UDID-A", 1.0, 2.0)
    await port.set_location("UDID-B", 3.0, 4.0)
    assert svc.sets == [(1.0, 2.0), (3.0, 4.0)]


@pytest.mark.asyncio
async def test_clear_is_noop_when_service_has_no_clear():
    svc = FakeLocationService()
    port = LocationServiceDevicePort(svc)
    # Must not raise; service has no clear/reset.
    await port.clear("any-udid")
