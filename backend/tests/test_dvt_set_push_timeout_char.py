"""Characterization: DvtLocationService.set() must bound the DTX push.

Real-world bug (finding #7, 12h log 2026-07-03): when USB dropped mid-run, the
next setLocation push hung on the DTX ``_wait_for_reply`` (the
``simulateLocationWithLatitude:longitude:`` call uses ``expects_reply=True``)
with no bound — so the phone froze and nothing surfaced for ~2.7s until the
usbmux presence watchdog cancelled the task. No "DVT channel dropped" fired
because a hung reply raises nothing.

This locks in: a hung ``sim.set`` surfaces promptly (times out → reconnect →
DeviceLostError) instead of blocking indefinitely.
"""
import asyncio

import pytest

import services.location_service as ls_mod
from services.location_service import DvtLocationService, DeviceLostError


class _HangingSim:
    """A LocationSimulation whose set()/clear() never return (dead channel)."""

    async def set(self, lat, lng):
        await asyncio.sleep(3600)

    async def clear(self):
        await asyncio.sleep(3600)


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_set_hung_push_surfaces_promptly_not_indefinite(monkeypatch):
    async def _factory_dead():
        raise DeviceLostError("device gone", reason=DeviceLostError.REASON_LOCKDOWN_DEAD)

    svc = DvtLocationService(dvt_provider=object(), lockdown=None, dvt_factory=_factory_dead)

    async def _fake_ensure():
        return _HangingSim()

    monkeypatch.setattr(svc, "_ensure_instrument", _fake_ensure)
    # Shrink the push bound so the test does not wait the full timeout.
    monkeypatch.setattr(ls_mod, "DVT_SET_TIMEOUT_S", 0.1, raising=False)

    # A hung push must NOT block forever: it times out, reconnect is attempted,
    # and (the device being dead) surfaces DeviceLostError — all well within the
    # 10s pytest-timeout guard.
    with pytest.raises(DeviceLostError):
        await svc.set(25.0, 121.0)
