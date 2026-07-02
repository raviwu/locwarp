"""Regression: get_fresh_dvt_provider must RETRY a transient DvtProvider open
failure (not raise NameError), and on permanent failure raise
DeviceLostError(REASON_LOCKDOWN_DEAD). Locks the device_manager.py:1155 fix.
"""
import asyncio
import time

import pytest
from pymobiledevice3.exceptions import ConnectionTerminatedError

from core.device_manager import DeviceManager
from services.location_service import DeviceLostError, DvtLocationService


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

    # W1: the first DvtProvider-open failure now also escalates to
    # full_reconnect (see get_fresh_dvt_provider). This test's _FakeConn is
    # not a real _ActiveConnection, so the REAL full_reconnect would blow up
    # trying to actually disconnect/reconnect a fake USB device — stub it out
    # so this test stays focused on its original regression: a transient
    # open failure that succeeds on the very next retry, without needing a
    # full reconnect.
    async def _fake_full_reconnect(_udid):
        return False
    monkeypatch.setattr(dm, "full_reconnect", _fake_full_reconnect)

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

    # W1: same fragility as test_retry_then_success_no_nameerror — the first
    # DvtProvider-open failure now also escalates to full_reconnect. This
    # test's _FakeConn is not a real _ActiveConnection, so the REAL
    # full_reconnect would pop the connection (via disconnect()) then fail to
    # re-add it (connect() against a fake UDID raises DeviceNotFoundError),
    # leaving self._connections empty. Without stubbing this out, the test
    # only "passes" by the fake clock below coincidentally crossing the
    # deadline before the loop's next iteration would see the popped
    # connection and raise DeviceLostError(REASON_USB_GONE) instead of the
    # asserted REASON_LOCKDOWN_DEAD. Stub it so this test robustly exercises
    # deadline exhaustion on a LIVE connection, as intended.
    async def _fake_full_reconnect(_udid):
        return False
    monkeypatch.setattr(dm, "full_reconnect", _fake_full_reconnect)

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


class _StubLockdownFR:
    def __init__(self):
        self.all_values = {"ProductVersion": "26.5", "DeviceName": "Renee"}


class _StaleDvt:
    """Stand-in for the OLD DvtProvider that DvtLocationService._reconnect
    closes via __aexit__ before rebuilding. Its IDENTITY (not its type) is
    what _FakeSim below uses to tell whether the rebuild has actually
    happened yet — mirroring production, where ``self._dvt`` is only
    reassigned to the freshly-opened provider after the whole
    ``dvt_factory()`` call has returned.
    """

    async def __aexit__(self, *exc):
        return False


class _FakeSim:
    """Stand-in for the DVT LocationSimulation instrument. Its ``.clear()``
    keeps raising ``ConnectionTerminatedError`` (a dropped-channel error
    DvtLocationService treats as reconnect-worthy) for as long as the owning
    service's ``self._dvt`` is still the STALE provider — i.e. for every call
    made before the escalation's ``full_reconnect()`` has actually swapped in
    a rebuilt connection. This lets the SAME failure recur on a re-entrant
    nested ``clear()`` call, which is exactly the condition that (pre-fix)
    drives a second, deadlocking ``_reconnect()`` call.
    """

    def __init__(self, service: DvtLocationService, stale_dvt: _StaleDvt):
        self._service = service
        self._stale_dvt = stale_dvt

    async def clear(self):
        if self._service._dvt is self._stale_dvt:
            raise ConnectionTerminatedError("DTX reader exiting: connection terminated")


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_get_fresh_dvt_usb_escalation_no_reentrant_deadlock(monkeypatch):
    """Regression (Task 4): the USB escalation in get_fresh_dvt_provider must
    NOT re-enter DvtLocationService._reconnect() on the SAME instance that is
    already running it.

    Drives the REAL production call chain end-to-end — only DeviceManager
    .connect() is stubbed (to simulate a successful reconnect without a real
    device); full_reconnect()/disconnect()/_teardown_connection() all run for
    real, so the reentrancy chain is genuinely exercised, not assumed:

        DvtLocationService.clear() [dropped channel]
          -> _reconnect() [acquires self._reconnect_lock]
            -> dvt_factory() == dm.get_fresh_dvt_provider(udid)
              -> DvtProvider(conn.lockdown).__aenter__() fails (stale lockdown)
              -> escalates: full_reconnect(udid)
                -> disconnect(udid) -> _teardown_connection(udid, conn)
                  -> (PRE-FIX) conn.location_service is still the SAME
                     DvtLocationService instance -> .clear() re-entered
                    -> sees the channel still dropped -> _reconnect() AGAIN
                       -> tries to re-acquire self._reconnect_lock, already
                          held by the outer call on the SAME task ->
                          asyncio.Lock is non-reentrant -> blocks forever.

    Pre-fix this test hangs; the pytest-timeout marker turns that hang into a
    fast, clear failure instead of wedging the whole suite. Post-fix,
    get_fresh_dvt_provider nulls conn.location_service before calling
    full_reconnect, so _teardown_connection's guard skips the re-entrant
    clear() entirely, the escalation's disconnect()+connect() rebuilds the
    connection, and the next loop iteration's DvtProvider open succeeds via
    the normal fall-through path.
    """
    from core.device_manager import DeviceManager, _ActiveConnection

    _FakeDvt.instances = []
    _FakeDvt.fail_remaining = 1  # first open (stale lockdown) fails; rebuilt one succeeds
    monkeypatch.setattr("core.device_manager.DvtProvider", _FakeDvt)

    dm = DeviceManager()
    conn = _ActiveConnection(
        udid="UDID-USB",
        lockdown=_StubLockdownFR(),
        ios_version="26.5",
        connection_type="USB",
    )
    dm._connections["UDID-USB"] = conn

    connect_calls: list[str] = []

    async def _fake_connect(udid: str) -> None:
        """Stand-in for the real connect() half of full_reconnect's USB path:
        installs a fresh _ActiveConnection, as connect()/_connect_locked()
        would. Deliberately does NOT populate dvt_provider or
        location_service — matching reality (only
        _create_dvt_location_service, called from get_location_service, ever
        does that)."""
        connect_calls.append(udid)
        dm._connections[udid] = _ActiveConnection(
            udid=udid,
            lockdown=_StubLockdownFR(),
            ios_version="26.5",
            connection_type="USB",
        )

    monkeypatch.setattr(dm, "connect", _fake_connect)

    stale_dvt = _StaleDvt()
    factory_calls: list[None] = []

    async def _tracked_factory() -> object:
        factory_calls.append(None)
        return await dm.get_fresh_dvt_provider("UDID-USB", timeout=1.0)

    service = DvtLocationService(stale_dvt, lockdown=None, dvt_factory=_tracked_factory)
    # The exact scenario Task 4 describes: conn.location_service IS the
    # instance whose _reconnect() is on the call stack.
    conn.location_service = service
    service._active = True  # a simulation was active when the channel dropped
    fake_sim = _FakeSim(service, stale_dvt)

    async def _fake_ensure_instrument():
        return fake_sim
    monkeypatch.setattr(service, "_ensure_instrument", _fake_ensure_instrument)

    await service.clear()

    assert len(factory_calls) == 1        # escalated/reconnected exactly once
    assert connect_calls == ["UDID-USB"]
    assert service._active is False       # clear() actually completed
    assert service._dvt is not stale_dvt  # swapped to the rebuilt provider


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_get_fresh_dvt_usb_escalates_to_full_reconnect(monkeypatch):
    """On USB, when the cached lockdown is dead (DvtProvider.__aenter__ keeps
    failing on it), get_fresh_dvt_provider must escalate to full_reconnect
    exactly once, then fall through to the normal retry-and-succeed path on
    the freshly rebuilt connection.

    full_reconnect's USB path is disconnect()+connect(), which never
    populates conn.dvt_provider directly — only _create_dvt_location_service
    (invoked from get_location_service) does that. So there is no
    full_reconnect-injected early return to exercise here: the real recovery
    is the fall-through retry, which is what this test now asserts (Task 4 —
    the previous version of this test asserted a postcondition the real
    full_reconnect never establishes, because it only exercised a dead
    early-return branch that has since been removed)."""
    from core.device_manager import DeviceManager, _ActiveConnection

    _FakeDvt.instances = []
    _FakeDvt.fail_remaining = 1  # first open (stale lockdown) fails; rebuilt one succeeds
    monkeypatch.setattr("core.device_manager.DvtProvider", _FakeDvt)

    dm = DeviceManager()
    conn = _ActiveConnection(
        udid="UDID-USB",
        lockdown=_StubLockdownFR(),
        ios_version="26.5",
        connection_type="USB",
    )
    dm._connections["UDID-USB"] = conn

    reconnect_calls = []

    async def _fake_full_reconnect(udid):
        reconnect_calls.append(udid)
        # Simulate the real full_reconnect's USB path: disconnect()+connect()
        # rebuilds the lockdown but never touches conn.dvt_provider.
        conn.lockdown = _StubLockdownFR()
        return True
    monkeypatch.setattr(dm, "full_reconnect", _fake_full_reconnect)

    provider = await dm.get_fresh_dvt_provider("UDID-USB", timeout=1.0)

    assert reconnect_calls == ["UDID-USB"]         # escalated exactly once
    assert provider is _FakeDvt.instances[-1]      # normal-path success, not a sentinel
    assert conn.dvt_provider is provider
