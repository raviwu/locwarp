"""SimulationEngine pushes coordinates through DevicePort.set_location.

_set_position is the single choke point; after wiring it must call the injected
device port (not location_service directly) and keep current_position in sync."""

import pytest

from core.simulation_engine import SimulationEngine


class FakeLocationService:
    def __init__(self):
        self.sets = []

    async def set(self, lat, lng):
        self.sets.append((lat, lng))


@pytest.mark.asyncio
async def test_set_position_pushes_through_location_service():
    svc = FakeLocationService()
    engine = SimulationEngine(svc)
    await engine._set_position(10.0, 20.0)
    assert svc.sets == [(10.0, 20.0)]
    assert engine.current_position is not None
    assert engine.current_position.lat == 10.0
    assert engine.current_position.lng == 20.0


@pytest.mark.asyncio
async def test_set_position_uses_injected_device_port():
    class FakePort:
        def __init__(self):
            self.calls = []

        async def set_location(self, udid, lat, lng):
            self.calls.append((udid, lat, lng))

        async def clear(self, udid):
            pass

    svc = FakeLocationService()  # must NOT be called directly when a port is injected
    port = FakePort()
    engine = SimulationEngine(svc, device_port=port)
    await engine._set_position(10.0, 20.0)
    assert port.calls == [("", 10.0, 20.0)]
    assert svc.sets == []  # location_service.set NOT called directly when a port is injected
