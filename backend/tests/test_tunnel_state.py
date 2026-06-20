"""tunnel_state owns the single _tunnels/_tunnels_lock/_tunnel_watchdogs.

api.device must re-bind those exact objects (not copies)."""
import asyncio

import infra.device.tunnel_state as ts


def test_tunnel_state_exports_the_three_objects():
    assert isinstance(ts._tunnels, dict)
    assert isinstance(ts._tunnel_watchdogs, dict)
    assert isinstance(ts._tunnels_lock, asyncio.Lock)


def test_api_device_aliases_are_the_same_objects():
    import api.device as device_mod
    assert device_mod._tunnels is ts._tunnels
    assert device_mod._tunnel_watchdogs is ts._tunnel_watchdogs
    assert device_mod._tunnels_lock is ts._tunnels_lock


def test_mutation_through_api_alias_is_visible_in_tunnel_state():
    import api.device as device_mod
    sentinel = object()
    device_mod._tunnels["G3_PROBE"] = sentinel
    try:
        assert ts._tunnels.get("G3_PROBE") is sentinel
    finally:
        device_mod._tunnels.pop("G3_PROBE", None)


def test_wifi_tunnel_registry_reads_the_shared_dict():
    import infra.device.tunnel_state as ts_mod
    from infra.device.wifi_tunnel import WifiTunnelRegistry

    class FakeRunner:
        target_ip = "10.0.0.9"
        target_port = 4444

        def is_running(self):
            return True

    runner = FakeRunner()
    ts_mod._tunnels["G3_REG"] = runner
    try:
        reg = WifiTunnelRegistry()
        assert reg.get_runner("G3_REG") is runner
        assert reg.is_running("G3_REG") is True
    finally:
        ts_mod._tunnels.pop("G3_REG", None)
