"""Characterize EngineResolver.resolve_engine — the resolve/rebuild ladder
lifted verbatim from api/location.py::_engine. REAL resolver over a fake
registry/device_manager; asserts exact engine identity + exact domain-error
code/message. The 10x discover loop is NOT exercised with real sleeps; the
no_device test monkeypatches asyncio.sleep + discover_devices so it returns
instantly.
"""
import pytest

from domain.errors import EngineUnavailableError
from services.engine_resolver import EngineResolver

pytestmark = pytest.mark.asyncio


class _FakeDM:
    def __init__(self, connections):
        self._connections = connections


class _FakeRegistry:
    """Minimal stand-in for AppState's resolve surface."""
    def __init__(self, engines, primary, connections):
        self.simulation_engines = engines
        self._primary_udid = primary
        self.device_manager = _FakeDM(connections)
        self._created = []

    @property
    def simulation_engine(self):
        if self._primary_udid and self._primary_udid in self.simulation_engines:
            return self.simulation_engines[self._primary_udid]
        return None

    def get_engine(self, udid):
        if udid is None:
            return self.simulation_engine
        return self.simulation_engines.get(udid)

    async def create_engine_for_device(self, udid, force=False):
        self._created.append(udid)
        # Simulate a successful rebuild: register a sentinel engine.
        self.simulation_engines[udid] = object()
        if self._primary_udid is None:
            self._primary_udid = udid


async def test_direct_hit_returns_engine_for_udid():
    eng = object()
    reg = _FakeRegistry({"U1": eng}, "U1", {"U1": object()})
    resolver = EngineResolver(reg, reg.device_manager)
    assert await resolver.resolve_engine("U1") is eng


async def test_udid_none_returns_primary_engine():
    eng = object()
    reg = _FakeRegistry({"U1": eng}, "U1", {"U1": object()})
    resolver = EngineResolver(reg, reg.device_manager)
    assert await resolver.resolve_engine(None) is eng


async def test_rebuild_attempt1_when_engine_missing_but_connection_present():
    # No engine registered yet, but a connection exists -> attempt-1 rebuild.
    reg = _FakeRegistry({}, None, {"U1": object()})
    resolver = EngineResolver(reg, reg.device_manager)
    out = await resolver.resolve_engine("U1")
    assert reg._created == ["U1"]
    assert out is reg.simulation_engines["U1"]


async def test_no_device_raises_engine_unavailable_with_verbatim_message():
    reg = _FakeRegistry({}, None, {})  # no connections, no engines
    resolver = EngineResolver(reg, reg.device_manager)

    async def _no_discover():
        return []
    reg.device_manager.discover_devices = _no_discover

    import asyncio as _a
    orig_sleep = _a.sleep
    async def _instant(_s):
        return None
    _a.sleep = _instant
    try:
        with pytest.raises(EngineUnavailableError) as ei:
            await resolver.resolve_engine(None)
    finally:
        _a.sleep = orig_sleep
    assert ei.value.code == "no_device"
    assert ei.value.message == "尚未連接任何 iOS 裝置,請先透過 USB 連線"
