"""Characterization test for the relocated infra.device.tunnel_restart
.attempt_tunnel_restart.

Pins the SUCCESS-path ordered effects:
  new runner start -> registry swap under lock -> device_manager connect ->
  engine rebuild -> watchdog re-arm -> broadcasts (tunnel_recovered then
  device_connected) -> snapshot resume.
And the start-failure-returns-False path.

Every injected collaborator is a fake; TunnelRunner is monkeypatched at the
infra module so no real tunnel is started.
"""

import asyncio

import pytest

import infra.device.tunnel_state as ts


@pytest.fixture(autouse=True)
def clear_tunnels():
    ts._tunnels.clear()
    ts._tunnel_watchdogs.clear()
    yield
    ts._tunnels.clear()
    ts._tunnel_watchdogs.clear()


class _FakeDevInfo:
    def __init__(self, udid):
        self.udid = udid
        self.name = "iPhone"
        self.ios_version = "17.0"


class _FakeEngine:
    def __init__(self):
        self.resumed_with = None

    async def resume_from_snapshot(self, snap):
        self.resumed_with = snap


class _FakeEngineRegistry:
    """Stands in for app_state."""

    def __init__(self):
        self.simulation_engines = {}
        self.force_calls = []

    async def create_engine_for_device(self, udid, force=False):
        self.force_calls.append((udid, force))
        self.simulation_engines[udid] = _FakeEngine()


class _FakeDeviceManager:
    def __init__(self, udid):
        self._udid = udid
        self.connect_calls = []

    async def connect_wifi_tunnel(self, rsd_address, rsd_port):
        self.connect_calls.append((rsd_address, rsd_port))
        return _FakeDevInfo(self._udid)


class _FakeRunner:
    def __init__(self, info=None, fail=False):
        self.target_ip = "10.0.0.5"
        self.target_port = 5555
        self.start_args = None
        self._info = info
        self._fail = fail
        self.stopped = False

    async def start(self, udid, ip, port, timeout=20.0):
        self.start_args = (udid, ip, port, timeout)
        if self._fail:
            raise RuntimeError("boom")
        return self._info

    async def stop(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_success_path_ordered_effects(monkeypatch):
    from infra.device import tunnel_restart

    udid, ip, port = "U1", "10.0.0.5", 5555
    rsd_address, rsd_port = "fd00::1", 49152
    snapshot = {"kind": "navigate", "leg": 2}

    original_runner = _FakeRunner()
    ts._tunnels[udid] = original_runner

    new_runner = _FakeRunner(info={"rsd_address": rsd_address, "rsd_port": rsd_port})
    monkeypatch.setattr(tunnel_restart, "TunnelRunner", lambda: new_runner)

    reg = _FakeEngineRegistry()
    dm = _FakeDeviceManager(udid)
    broadcasts = []

    async def broadcast(etype, data):
        broadcasts.append((etype, data))

    auto_sync_calls = []

    async def auto_sync(u):
        auto_sync_calls.append(u)

    watchdog_made = []

    def watchdog_factory(u, runner):
        watchdog_made.append((u, runner))
        return asyncio.create_task(asyncio.sleep(0))

    ok = await tunnel_restart.attempt_tunnel_restart(
        udid, ip, port, snapshot, original_runner,
        engine_registry=reg, device_manager=dm, broadcast=broadcast,
        auto_sync=auto_sync, watchdog_factory=watchdog_factory,
    )
    # Let the resume_from_snapshot task (scheduled via create_task) run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert ok is True
    assert new_runner.start_args == (udid, ip, port, 10.0)
    assert ts._tunnels[udid] is new_runner
    assert dm.connect_calls == [(rsd_address, rsd_port)]
    assert [b[0] for b in broadcasts] == ["tunnel_recovered", "device_connected"]
    assert reg.simulation_engines[udid].resumed_with == snapshot
    # snapshot present -> no auto-sync follower path
    assert auto_sync_calls == []
    assert watchdog_made and watchdog_made[0][1] is new_runner


@pytest.mark.asyncio
async def test_start_failure_returns_false(monkeypatch):
    from infra.device import tunnel_restart

    udid, ip, port = "U1", "10.0.0.5", 5555
    original_runner = _FakeRunner()
    ts._tunnels[udid] = original_runner

    new_runner = _FakeRunner(fail=True)
    monkeypatch.setattr(tunnel_restart, "TunnelRunner", lambda: new_runner)

    reg = _FakeEngineRegistry()
    dm = _FakeDeviceManager(udid)

    async def broadcast(etype, data):  # pragma: no cover - must not be called
        raise AssertionError("broadcast must not fire on start failure")

    async def auto_sync(u):  # pragma: no cover
        raise AssertionError("auto_sync must not fire on start failure")

    def watchdog_factory(u, runner):  # pragma: no cover
        raise AssertionError("watchdog must not be re-armed on start failure")

    ok = await tunnel_restart.attempt_tunnel_restart(
        udid, ip, port, None, original_runner,
        engine_registry=reg, device_manager=dm, broadcast=broadcast,
        auto_sync=auto_sync, watchdog_factory=watchdog_factory,
    )

    assert ok is False
    assert dm.connect_calls == []
    # original runner left in place; no swap happened
    assert ts._tunnels[udid] is original_runner
