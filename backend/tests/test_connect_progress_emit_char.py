"""Characterization: the connect path emits connect_progress phases in exact
order, awaited in-line through the injected EventPublisher (never stubbed).
We drive the REAL DeviceManager.connect_wifi_tunnel with a fake RSD (succeeds
on the first connect) and the REAL _create_dvt_location_service with a fake
DvtProvider, asserting the ordered (type, payload) tuples.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

import core.device_manager as dm_mod
from core.device_manager import DeviceManager, _ActiveConnection

pytestmark = pytest.mark.asyncio


class _CapPublisher:
    def __init__(self):
        self.events: list[tuple] = []

    async def publish(self, event):
        # Normalize typed events to (type, payload) deep-equal tuples.
        payload = event.model_dump(exclude_unset=True, exclude_none=True)
        etype = payload.pop("type")
        self.events.append((etype, payload))


class _FakeRSD:
    """Fake RemoteServiceDiscoveryService: connect() succeeds immediately."""

    def __init__(self, _addr):
        self.peer_info = {"Properties": {"UniqueDeviceID": "UDID-CP", "OSVersion": "17.4", "DeviceClass": "iPhone"}}
        self.all_values = {"DeviceName": "Ravi iPhone"}

    async def connect(self):
        return None

    async def close(self):
        return None


async def test_connect_wifi_tunnel_emits_opening_then_rsd_attempt(monkeypatch):
    pub = _CapPublisher()
    dm = DeviceManager(event_publisher=pub)

    monkeypatch.setattr(dm_mod, "RemoteServiceDiscoveryService", _FakeRSD)
    # Suppress device-name cache side effects (file I/O) — they don't affect emits.
    monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)
    monkeypatch.setattr(dm_mod, "_load_device_name_cache", lambda: {})

    info = await dm.connect_wifi_tunnel("fd00::1", 49152)
    assert info.udid == "UDID-CP"

    progress = [(e, d) for e, d in pub.events if e == "connect_progress"]
    # opening_tunnel first, then the single successful rsd_attempt (1/10).
    assert progress[0] == ("connect_progress", {"phase": "opening_tunnel"})
    assert progress[1] == ("connect_progress", {"phase": "rsd_attempt", "attempt": 1, "max": 10})


async def test_connect_progress_emit_failure_does_not_abort_connect(monkeypatch):
    class _BoomPublisher:
        async def publish(self, event):
            raise RuntimeError("publish boom")

    dm = DeviceManager(event_publisher=_BoomPublisher())
    monkeypatch.setattr(dm_mod, "RemoteServiceDiscoveryService", _FakeRSD)
    monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)
    monkeypatch.setattr(dm_mod, "_load_device_name_cache", lambda: {})

    # A publish() that always raises must NOT abort the connect.
    info = await dm.connect_wifi_tunnel("fd00::1", 49152)
    assert info.udid == "UDID-CP"


async def test_ddi_and_dvt_phases_emit_in_order(monkeypatch):
    pub = _CapPublisher()
    dm = DeviceManager(event_publisher=pub)

    # Fake DvtProvider so _create_dvt_location_service opens "DVT" cleanly.
    class _FakeDvt:
        def __init__(self, _lockdown):
            pass

        async def __aenter__(self):
            return self

    monkeypatch.setattr(dm_mod, "DvtProvider", _FakeDvt)

    # Make the DDI check a no-op that still emits checking_ddi (real method,
    # but MobileImageMounter import path short-circuits to return). We drive
    # the REAL _create_dvt_location_service, which calls the REAL
    # _ensure_personalized_ddi_mounted.
    async def _no_mounter(*a, **k):
        raise ImportError("no mounter in test")
    # Force the early ImportError return in _ensure_personalized_ddi_mounted
    # so it emits checking_ddi then returns without touching real hardware.
    import sys
    import types as _types
    fake_mod = _types.ModuleType("pymobiledevice3.services.mobile_image_mounter")
    monkeypatch.setitem(sys.modules, "pymobiledevice3.services.mobile_image_mounter", fake_mod)

    conn = _ActiveConnection(udid="UDID-CP", lockdown=object(), ios_version="17.4", connection_type="Network")
    loc = await dm._create_dvt_location_service(conn)
    assert loc is not None

    progress = [(e, d) for e, d in pub.events if e == "connect_progress"]
    phases = [d["phase"] for _, d in progress]
    # checking_ddi (from _ensure_personalized_ddi_mounted) → opening_dvt → connected
    assert phases == ["checking_ddi", "opening_dvt", "connected"]
    assert all(d.get("udid") == "UDID-CP" for _, d in progress)
