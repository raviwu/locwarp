import asyncio
import pytest

from core.wifi_tunnel import TunnelRunner, set_helper_client


@pytest.mark.asyncio
async def test_start_delegates_to_helper_client():
    calls: list[tuple] = []

    class FakeClient:
        def __init__(self) -> None:
            self._open_udid: str | None = None

        async def open_wifi_tunnel(self, udid, ip, port):
            calls.append(("open", udid, ip, port))
            self._open_udid = udid
            return {
                "rsd_address": "fd7d::1",
                "rsd_port": 9999,
                "interface": "utun3",
                "protocol": "quic",
            }

        async def close_tunnel(self, udid):
            calls.append(("close", udid))
            self._open_udid = None
            return {"closed": True}

        async def list_tunnels(self):
            if self._open_udid:
                return [{"udid": self._open_udid}]
            return []

    set_helper_client(FakeClient())
    try:
        runner = TunnelRunner()
        assert not runner.is_running()
        assert runner.info is None
        assert runner.task is None
        info = await runner.start(udid="xyz", ip="192.168.1.1", port=12345)
        assert info["rsd_address"] == "fd7d::1"
        assert info["rsd_port"] == 9999
        assert runner.is_running()
        assert runner.task is not None
        assert runner.target_ip == "192.168.1.1"
        assert runner.target_port == 12345
        assert runner.info is not None

        await runner.stop()
        assert not runner.is_running()
        assert runner.task is None
        assert runner.info is None
        assert calls == [
            ("open", "xyz", "192.168.1.1", 12345),
            ("close", "xyz"),
        ]
    finally:
        set_helper_client(None)


@pytest.mark.asyncio
async def test_start_raises_when_helper_client_not_configured():
    set_helper_client(None)
    runner = TunnelRunner()
    with pytest.raises(RuntimeError, match="not configured"):
        await runner.start(udid="x", ip="y", port=1)


@pytest.mark.asyncio
async def test_stop_is_idempotent_when_never_started():
    """stop() on a never-started runner should be a no-op, not crash."""
    set_helper_client(None)
    runner = TunnelRunner()
    await runner.stop()  # should not raise
    assert not runner.is_running()
    assert runner.task is None


@pytest.mark.asyncio
async def test_task_completes_when_helper_drops_tunnel(monkeypatch):
    """If list_tunnels stops reporting our UDID, the monitor task should
    complete on its own — this is the signal _per_tunnel_watchdog awaits
    to trigger an auto-restart."""
    import core.wifi_tunnel as wt
    monkeypatch.setattr(wt, "TUNNEL_LIVENESS_POLL", 0.05)

    fake_state = {"present": True}

    class FakeClient:
        async def open_wifi_tunnel(self, udid, ip, port):
            return {
                "rsd_address": "fd7d::1",
                "rsd_port": 1,
                "interface": "utun0",
                "protocol": "quic",
            }

        async def close_tunnel(self, udid):
            return {"closed": True}

        async def list_tunnels(self):
            return [{"udid": "x"}] if fake_state["present"] else []

    wt.set_helper_client(FakeClient())
    try:
        runner = wt.TunnelRunner()
        await runner.start(udid="x", ip="1", port=1)
        # Simulate helper dropping the tunnel.
        fake_state["present"] = False
        # Task should self-complete within ~150ms (3x poll interval).
        await asyncio.wait_for(runner.task, timeout=1.0)
        assert runner.task.done()
        # is_running() now returns False because the task is done.
        assert not runner.is_running()
    finally:
        await runner.stop()
        wt.set_helper_client(None)
