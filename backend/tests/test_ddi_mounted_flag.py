"""Characterization: _ensure_personalized_ddi_mounted records the DDI status
on the _ActiveConnection (new stored flag) in addition to the existing
transient DdiMounted/DdiNotMounted event. Drives the REAL method; only the
pymobiledevice3 MobileImageMounterService boundary is faked.
"""
from __future__ import annotations

import sys
import types

import pytest

from core.device_manager import DeviceManager, _ActiveConnection


class _FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        payload = event.model_dump(exclude_unset=True, exclude_none=True)
        etype = payload.pop("type")
        self.events.append((etype, payload))


class _FakeMounter:
    def __init__(self, *, lockdown=None, mounted: bool):
        self._mounted = mounted

    async def connect(self):
        return None

    async def is_image_mounted(self, image_type):
        assert image_type == "Personalized"
        return self._mounted

    async def close(self):
        return None


def _install_fake_mounter(monkeypatch, *, mounted: bool):
    """Patch the lazily-imported MobileImageMounterService symbol that
    _ensure_personalized_ddi_mounted does `from pymobiledevice3.services.
    mobile_image_mounter import MobileImageMounterService` against."""
    mod = sys.modules.get("pymobiledevice3.services.mobile_image_mounter")
    if mod is None:
        import pymobiledevice3.services.mobile_image_mounter as mod  # noqa: F811

    def _factory(*, lockdown):
        return _FakeMounter(lockdown=lockdown, mounted=mounted)

    monkeypatch.setattr(mod, "MobileImageMounterService", _factory)


@pytest.mark.asyncio
async def test_ddi_mounted_sets_flag_true_and_emits_event(monkeypatch):
    pub = _FakePublisher()
    dm = DeviceManager(event_publisher=pub)
    conn = _ActiveConnection(udid="UDID-A", lockdown=object(), ios_version="17.0")
    assert conn.ddi_mounted is False  # default
    _install_fake_mounter(monkeypatch, mounted=True)

    await dm._ensure_personalized_ddi_mounted(conn)

    assert conn.ddi_mounted is True
    assert ("ddi_mounted", {"udid": "UDID-A"}) in pub.events


@pytest.mark.asyncio
async def test_ddi_not_mounted_sets_flag_false_and_emits_event(monkeypatch):
    pub = _FakePublisher()
    dm = DeviceManager(event_publisher=pub)
    conn = _ActiveConnection(udid="UDID-B", lockdown=object(), ios_version="17.0")
    conn.ddi_mounted = True  # pretend a stale prior True
    _install_fake_mounter(monkeypatch, mounted=False)

    await dm._ensure_personalized_ddi_mounted(conn)

    assert conn.ddi_mounted is False
    assert any(etype == "ddi_not_mounted" for etype, _ in pub.events)
