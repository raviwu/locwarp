"""Characterization tests for "forced clear must rebuild the DVT provider
before re-sending stopLocationSimulation".

Root cause (device-confirmed against production logs on a rebuilt app):
iOS's InstrumentsServer silently ignores a REPEATED stopLocationSimulation
issued over a REUSED DVT connection. That DTX method is fire-and-forget
(expects_reply=False), so LocWarp never sees it get ignored — the log shows
"DVT simulated location cleared (forced)" every press while the phone stays
simulated after the FIRST successful clear per process.

Every proven-reliable implementation opens a FRESH connection per clear:
the pymobiledevice3 CLI opens a new DvtProvider + LocationSimulation per
invocation; go-ios (including its long-lived REST server) opens a brand-new
DTX connection per clear and closes it. LocWarp instead reused one
long-lived DvtProvider + cached LocationSimulation across all set/clear
cycles.

Fix under test: DvtLocationService.clear(force=True) rebuilds the whole
DvtProvider (via ``_reconnect()``, which defers to ``_dvt_factory`` when
present) BEFORE re-issuing the stop, so the stop lands on a virgin
connection + instrument — matching the pmd3 CLI / go-ios pattern.
Non-forced clears (internal teardown) keep reusing the cached connection.
"""
from __future__ import annotations

import pytest

from services.location_service import DvtLocationService

pytestmark = pytest.mark.asyncio


class _FakeLocationSimulation:
    """Stand-in for the DVT LocationSimulation instrument. Records which
    provider it was built on and every clear() call against it."""

    def __init__(self, provider) -> None:
        self.provider = provider
        self.clear_calls = 0
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def clear(self) -> None:
        self.clear_calls += 1

    async def set(self, lat, lng) -> None:  # pragma: no cover - unused here
        pass


class _FakeDvtProvider:
    """Stand-in for pymobiledevice3's DvtProvider — an async context
    manager identified by a monotonically increasing id so tests can tell
    providers apart by identity."""

    _next_id = 0

    def __init__(self) -> None:
        _FakeDvtProvider._next_id += 1
        self.id = _FakeDvtProvider._next_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _make_service(*, initial_active: bool, with_factory: bool):
    """Build a DvtLocationService wired so ``_ensure_instrument`` returns a
    fresh ``_FakeLocationSimulation`` bound to whatever ``self._dvt``
    currently is — mirroring the real ``_ensure_instrument`` (which builds
    ``LocationSimulation(self._dvt)`` lazily and caches it per-instance, so
    it naturally picks up a rebuilt provider after ``_reconnect()`` nulls
    ``self._location_sim``).
    """
    first_provider = _FakeDvtProvider()
    factory_calls = {"n": 0}

    async def _dvt_factory():
        factory_calls["n"] += 1
        provider = _FakeDvtProvider()
        await provider.__aenter__()
        return provider

    service = DvtLocationService(
        first_provider,
        lockdown=None,
        dvt_factory=_dvt_factory if with_factory else None,
        initial_active=initial_active,
    )

    # Real _ensure_instrument constructs LocationSimulation(self._dvt) and
    # caches it on self._location_sim, connecting once. Swap in the fake
    # class instead of monkeypatching the real pymobiledevice3 class so this
    # test does not depend on the real DVT wire protocol.
    async def _ensure_instrument():
        if service._location_sim is None:
            sim = _FakeLocationSimulation(service._dvt)
            await sim.connect()
            service._location_sim = sim
        return service._location_sim

    service._ensure_instrument = _ensure_instrument  # type: ignore[method-assign]

    return service, first_provider, factory_calls


async def test_forced_clear_rebuilds_provider_before_sending_stop():
    """(a) set() then clear(force=True): the factory must be invoked (the
    provider is rebuilt via _reconnect BEFORE the stop is sent), self._dvt
    must become a DIFFERENT object than the one set() used, and the stop
    must land on a LocationSimulation built on that fresh provider."""
    service, first_provider, factory_calls = _make_service(
        initial_active=False, with_factory=True
    )

    # set() runs first on the original (cached) provider/instrument, mirroring
    # the real set->clear cycle.
    await service.set(25.0, 121.0)
    sim_used_for_set = service._location_sim
    assert sim_used_for_set.provider is first_provider

    await service.clear(force=True)

    assert factory_calls["n"] >= 1, "forced clear must rebuild via the dvt_factory"
    assert service._dvt is not first_provider, "self._dvt must be a fresh provider after forced clear"

    sim_used_for_clear = service._location_sim
    assert sim_used_for_clear is not sim_used_for_set, (
        "forced clear must build a fresh LocationSimulation instrument, "
        "not reuse the one bound to the old provider"
    )
    assert sim_used_for_clear.provider is service._dvt, (
        "the stop must be issued on the rebuilt (fresh) provider"
    )
    assert sim_used_for_clear.clear_calls == 1, "the stop must actually be sent"
    assert service._active is False


async def test_nonforced_clear_does_not_rebuild_provider():
    """(b) clear(force=False) on an _active service must NOT invoke the
    factory / rebuild the provider — non-forced (internal teardown) clears
    stay on the cached connection."""
    service, first_provider, factory_calls = _make_service(
        initial_active=True, with_factory=True
    )

    await service.clear()

    assert factory_calls["n"] == 0, "non-forced clear must not reconnect"
    assert service._dvt is first_provider
    assert service._location_sim.clear_calls == 1
    assert service._active is False


async def test_forced_clear_without_factory_falls_back_to_cached_provider():
    """(c) clear(force=True) when self._dvt_factory is None must NOT raise
    (there is no factory to rebuild via) and must still issue the stop on
    the cached provider — the legacy/no-factory fallback path."""
    service, first_provider, factory_calls = _make_service(
        initial_active=False, with_factory=False
    )

    await service.clear(force=True)

    assert factory_calls["n"] == 0
    assert service._dvt is first_provider
    assert service._location_sim.provider is first_provider
    assert service._location_sim.clear_calls == 1
    assert service._active is False
