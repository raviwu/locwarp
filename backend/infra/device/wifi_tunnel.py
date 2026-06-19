"""WifiTunnelRegistry — adapter over api.device's _tunnels table.

Reads are bare dict.get (atomic in CPython), matching the existing lock-free
reads at device_manager 1135/1200. The async attempt_restart delegates to
api.device._attempt_tunnel_restart, which takes _tunnels_lock internally.

api.device is imported INSIDE the methods to avoid the import cycle at module
load (same pattern the rest of the codebase uses for api<->core).
"""

from __future__ import annotations


class WifiTunnelRegistry:
    def get_runner(self, udid: str):
        from api.device import _tunnels

        return _tunnels.get(udid)

    def is_running(self, udid: str) -> bool:
        runner = self.get_runner(udid)
        return bool(runner is not None and runner.is_running())

    async def attempt_restart(self, udid: str) -> bool:
        from api.device import _attempt_tunnel_restart

        runner = self.get_runner(udid)
        if runner is None or not runner.target_ip or not runner.target_port:
            return False
        ok = await _attempt_tunnel_restart(
            udid, runner.target_ip, runner.target_port, None, runner
        )
        return bool(ok)
