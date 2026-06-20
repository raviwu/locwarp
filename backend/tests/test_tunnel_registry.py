"""WifiTunnelRegistry: is_running/get_runner read infra.device.tunnel_state._tunnels;
attempt_restart delegates to infra.device.tunnel_restart.attempt_tunnel_restart
with collaborators supplied by the ctor-injected restart_collaborators resolver."""

import pytest

import infra.device.tunnel_state as ts
from infra.device.wifi_tunnel import WifiTunnelRegistry


@pytest.fixture(autouse=True)
def clear_tunnels():
    ts._tunnels.clear()
    yield
    ts._tunnels.clear()


def test_get_runner_returns_none_when_absent():
    reg = WifiTunnelRegistry()
    assert reg.get_runner("NOPE") is None


def test_get_runner_and_is_running_read_live_dict():
    class FakeRunner:
        target_ip = "10.0.0.5"
        target_port = 5555

        def is_running(self):
            return True

    runner = FakeRunner()
    ts._tunnels["U1"] = runner

    reg = WifiTunnelRegistry()
    assert reg.get_runner("U1") is runner
    assert reg.is_running("U1") is True


def test_is_running_false_when_runner_absent():
    reg = WifiTunnelRegistry()
    assert reg.is_running("U1") is False


@pytest.mark.asyncio
async def test_attempt_restart_delegates(monkeypatch):
    class FakeRunner:
        target_ip = "10.0.0.5"
        target_port = 5555

        def is_running(self):
            return False

    ts._tunnels["U1"] = FakeRunner()

    calls = []

    async def fake_restart(udid, ip, port, snapshot, original_runner, **collaborators):
        calls.append((udid, ip, port, snapshot))
        return True

    monkeypatch.setattr(
        "infra.device.tunnel_restart.attempt_tunnel_restart", fake_restart
    )

    sentinel_collabs = {
        "engine_registry": object(),
        "device_manager": object(),
        "broadcast": object(),
        "auto_sync": object(),
        "watchdog_factory": object(),
    }
    reg = WifiTunnelRegistry(restart_collaborators=lambda: sentinel_collabs)
    ok = await reg.attempt_restart("U1")
    assert ok is True
    assert calls == [("U1", "10.0.0.5", 5555, None)]


@pytest.mark.asyncio
async def test_attempt_restart_false_when_no_runner():
    reg = WifiTunnelRegistry()
    assert await reg.attempt_restart("NOPE") is False


@pytest.mark.asyncio
async def test_attempt_restart_false_when_runner_has_no_target(monkeypatch):
    """Runner present but target_ip/target_port empty — short-circuits before delegating."""
    class FakeRunner:
        target_ip = ""
        target_port = None

        def is_running(self):
            return False

    ts._tunnels["U2"] = FakeRunner()

    calls = []

    async def fake_restart(udid, ip, port, snapshot, original_runner, **collaborators):
        calls.append((udid, ip, port))
        return True

    monkeypatch.setattr(
        "infra.device.tunnel_restart.attempt_tunnel_restart", fake_restart
    )

    reg = WifiTunnelRegistry(restart_collaborators=lambda: {})
    ok = await reg.attempt_restart("U2")
    assert ok is False
    assert calls == [], "attempt_restart must not delegate when target_ip/target_port absent"
