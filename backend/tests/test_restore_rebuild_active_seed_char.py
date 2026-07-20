"""Characterization test for the "phone stays simulated after restore" bug.

Root cause (adversarially confirmed): DvtLocationService._active is per
INSTANCE (starts False) but represents DEVICE truth. clear() hard-guards
``if not self._active: return``. When create_engine_for_device(force=True)
rebuilds DeviceManager's cached DvtLocationService (e.g. across a WiFi tunnel
restart / USB<->WiFi transition / USB promotion) while the phone is STILL
simulating, the fresh instance starts with _active=False and the next
restore's clear() silently no-ops — the API still reports success, but the
device is left simulated.

Fix under test (Option B): DeviceManager keeps a durable per-udid "believed
simulating" flag (``self._device_simulating``) fed by an ``on_active_change``
callback wired into each DvtLocationService/LegacyLocationService it builds.
A freshly rebuilt service is seeded with ``initial_active`` from that flag,
so a rebuild-after-set() no longer loses track of device truth.

This test uses the same fake-DVT patterns as test_device_manager_fresh_dvt.py
(``_ActiveConnection`` directly, a fake ``DvtProvider`` monkeypatched onto
``core.device_manager``, and a fake ``LocationSimulation`` monkeypatched onto
``services.location_service`` since ``DvtLocationService._ensure_instrument``
constructs one internally per-instance).
"""
from __future__ import annotations

import pytest

import core.device_manager as device_manager_module
import services.location_service as location_service_module
from core.device_manager import DeviceManager, _ActiveConnection
from services.location_service import DvtLocationService

pytestmark = pytest.mark.asyncio


class _StubLockdown:
    """Opaque lockdown stand-in; only ever handed to fakes below."""

    def __init__(self) -> None:
        self.all_values = {"ProductVersion": "17.4", "DeviceName": "Renee"}


class _FakeDvtProvider:
    """Stand-in for pymobiledevice3's DvtProvider — just an async context
    manager wrapping whatever lockdown it was built from."""

    def __init__(self, lockdown):
        self.lockdown = lockdown

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeLocationSimulation:
    """Stand-in for pymobiledevice3's DVT LocationSimulation instrument.

    Records every set()/clear() call on a class-level ledger, tagged with
    the owning fake DVT provider's identity, so tests can tell whether a
    given DvtLocationService instance's clear() actually reached "the
    device" (this fake) or short-circuited on the ``_active`` guard before
    ever constructing an instrument.
    """

    ledger: list[tuple[str, object]] = []

    def __init__(self, dvt):
        self._dvt = dvt

    async def connect(self):
        pass

    async def set(self, lat, lng):
        _FakeLocationSimulation.ledger.append(("set", self._dvt))

    async def clear(self):
        _FakeLocationSimulation.ledger.append(("clear", self._dvt))


@pytest.fixture(autouse=True)
def _reset_ledger():
    _FakeLocationSimulation.ledger = []
    yield


@pytest.fixture(autouse=True)
def _patch_dvt(monkeypatch):
    monkeypatch.setattr(device_manager_module, "DvtProvider", _FakeDvtProvider)
    monkeypatch.setattr(location_service_module, "LocationSimulation", _FakeLocationSimulation)
    yield


async def test_rebuilt_dvt_service_clear_reaches_device_not_active_guard_noop():
    """The scenario from the bug report, end to end through DeviceManager:

    1. Device connects; get_location_service builds service instance A.
    2. A.set(lat, lng) succeeds -> phone is now simulating.
    3. A force=True rebuild happens (main.py nulls conn.location_service and
       calls get_location_service again) -> instance B (B is not A).
    4. B.clear() must actually reach the fake DVT's clear() — NOT
       short-circuit on B._active being freshly-False.
    """
    udid = "UDID-REBUILD"
    dm = DeviceManager()
    conn = _ActiveConnection(
        udid=udid,
        lockdown=_StubLockdown(),
        ios_version="17.4",
        connection_type="USB",
    )
    dm._connections[udid] = conn

    service_a = await dm.get_location_service(udid)
    assert isinstance(service_a, DvtLocationService)

    await service_a.set(37.7749, -122.4194)
    assert ("set", service_a._dvt) in _FakeLocationSimulation.ledger

    # force=True rebuild: main.py's create_engine_for_device nulls
    # conn.location_service before calling get_location_service again.
    conn.location_service = None
    service_b = await dm.get_location_service(udid)
    assert service_b is not service_a
    assert isinstance(service_b, DvtLocationService)

    ledger_before = list(_FakeLocationSimulation.ledger)
    await service_b.clear()
    ledger_after = _FakeLocationSimulation.ledger

    new_entries = ledger_after[len(ledger_before):]
    assert ("clear", service_b._dvt) in new_entries, (
        "clear() on the rebuilt service never reached the fake DVT device — "
        f"it short-circuited on the _active guard instead. "
        f"ledger before={ledger_before!r} after={ledger_after!r}"
    )


class _RecordingSim:
    def __init__(self):
        self.clear_calls = 0
        self.set_calls = 0

    async def clear(self):
        self.clear_calls += 1

    async def set(self, lat, lng):
        self.set_calls += 1


async def test_dvt_location_service_initial_active_true_clear_reaches_sim_and_fires_callback():
    """Focused unit test: initial_active=True -> clear() takes the real
    path (fake sim.clear() invoked) and on_active_change(False) fires."""
    changes: list[bool] = []
    service = DvtLocationService(
        object(),
        initial_active=True,
        on_active_change=changes.append,
    )
    fake_sim = _RecordingSim()

    async def _fake_ensure_instrument():
        return fake_sim

    service._ensure_instrument = _fake_ensure_instrument  # type: ignore[method-assign]

    await service.clear()

    assert fake_sim.clear_calls == 1
    assert changes == [False]


async def test_dvt_location_service_initial_active_false_clear_is_noop():
    """Focused unit test: initial_active=False -> clear() stays a no-op;
    the fake sim's clear() is never called and no callback fires."""
    changes: list[bool] = []
    service = DvtLocationService(
        object(),
        initial_active=False,
        on_active_change=changes.append,
    )
    fake_sim = _RecordingSim()

    async def _fake_ensure_instrument():
        return fake_sim

    service._ensure_instrument = _fake_ensure_instrument  # type: ignore[method-assign]

    await service.clear()

    assert fake_sim.clear_calls == 0
    assert changes == []
