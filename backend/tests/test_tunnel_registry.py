"""WifiTunnelRegistry: is_running/get_runner read api.device._tunnels;
attempt_restart delegates to api.device._attempt_tunnel_restart."""

import pytest

from infra.device.wifi_tunnel import WifiTunnelRegistry


@pytest.fixture(autouse=True)
def clear_tunnels():
    import api.device as device_mod
    device_mod._tunnels.clear()
    yield
    device_mod._tunnels.clear()


def test_get_runner_returns_none_when_absent():
    reg = WifiTunnelRegistry()
    assert reg.get_runner("NOPE") is None


def test_get_runner_and_is_running_read_live_dict():
    import api.device as device_mod

    class FakeRunner:
        target_ip = "10.0.0.5"
        target_port = 5555

        def is_running(self):
            return True

    runner = FakeRunner()
    device_mod._tunnels["U1"] = runner

    reg = WifiTunnelRegistry()
    assert reg.get_runner("U1") is runner
    assert reg.is_running("U1") is True


def test_is_running_false_when_runner_absent():
    reg = WifiTunnelRegistry()
    assert reg.is_running("U1") is False


@pytest.mark.asyncio
async def test_attempt_restart_delegates(monkeypatch):
    import api.device as device_mod

    class FakeRunner:
        target_ip = "10.0.0.5"
        target_port = 5555

        def is_running(self):
            return False

    device_mod._tunnels["U1"] = FakeRunner()

    calls = []

    async def fake_restart(udid, ip, port, snapshot, original_runner):
        calls.append((udid, ip, port, snapshot))
        return True

    monkeypatch.setattr("api.device._attempt_tunnel_restart", fake_restart)

    reg = WifiTunnelRegistry()
    ok = await reg.attempt_restart("U1")
    assert ok is True
    assert calls == [("U1", "10.0.0.5", 5555, None)]


@pytest.mark.asyncio
async def test_attempt_restart_false_when_no_runner():
    reg = WifiTunnelRegistry()
    assert await reg.attempt_restart("NOPE") is False
