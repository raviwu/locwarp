"""Regression: get_fresh_dvt_provider must RETRY a transient DvtProvider open
failure (not raise NameError), and on permanent failure raise
DeviceLostError(REASON_LOCKDOWN_DEAD). Locks the device_manager.py:1155 fix.
"""
import asyncio
import time

import pytest

from core.device_manager import DeviceManager
from services.location_service import DeviceLostError


class _FakeConn:
    """Stand-in for a Connection: USB so the WiFi tunnel branch is skipped."""
    connection_type = "USB"

    def __init__(self, udid: str):
        self.udid = udid
        self.lockdown = object()       # opaque; only handed to DvtProvider(...)
        self.dvt_provider = None


class _FakeDvt:
    """A DvtProvider whose __aenter__ fails the first N times, then succeeds."""
    instances: list["_FakeDvt"] = []

    def __init__(self, lockdown):
        self.lockdown = lockdown
        _FakeDvt.instances.append(self)

    async def __aenter__(self):
        if _FakeDvt.fail_remaining > 0:
            _FakeDvt.fail_remaining -= 1
            raise OSError("transient lockdown open failure")
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _reset_fake_dvt():
    _FakeDvt.instances = []
    _FakeDvt.fail_remaining = 0
    yield


@pytest.mark.asyncio
async def test_retry_then_success_no_nameerror(monkeypatch):
    """First open raises OSError, second succeeds → no NameError, returns the
    second provider, and exactly two DvtProvider opens were attempted."""
    dm = DeviceManager()
    conn = _FakeConn("UDID-RETRY")
    dm._connections["UDID-RETRY"] = conn

    monkeypatch.setattr("core.device_manager.DvtProvider", _FakeDvt)

    # Make the inter-retry sleep instant so the test does not wait 0.5s.
    async def _instant_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

    _FakeDvt.fail_remaining = 1  # fail once, then succeed

    provider = await dm.get_fresh_dvt_provider("UDID-RETRY", timeout=15.0)

    assert provider is _FakeDvt.instances[-1]
    assert len(_FakeDvt.instances) == 2          # one failed open + one good open
    assert conn.dvt_provider is provider


@pytest.mark.asyncio
async def test_permanent_failure_raises_devicelost(monkeypatch):
    """Every open fails → loop exhausts the deadline and raises
    DeviceLostError(REASON_LOCKDOWN_DEAD), NOT NameError."""
    dm = DeviceManager()
    conn = _FakeConn("UDID-DEAD")
    dm._connections["UDID-DEAD"] = conn

    monkeypatch.setattr("core.device_manager.DvtProvider", _FakeDvt)

    # FakeClock: a controlled, monotonically increasing time source. Each call
    # advances 0.4s so the deadline (now + timeout) is crossed deterministically.
    base = time.monotonic()
    ticks = {"n": 0}

    def _fake_monotonic():
        ticks["n"] += 1
        return base + ticks["n"] * 0.4

    monkeypatch.setattr(time, "monotonic", _fake_monotonic)

    async def _instant_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

    _FakeDvt.fail_remaining = 10_000  # never succeed

    with pytest.raises(DeviceLostError) as ei:
        await dm.get_fresh_dvt_provider("UDID-DEAD", timeout=1.0)

    assert ei.value.reason == DeviceLostError.REASON_LOCKDOWN_DEAD
    # The cause chain carries the underlying OSError ("from exc").
    assert isinstance(ei.value.__cause__, OSError)
