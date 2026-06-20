"""WifiTunnelRegistry — adapter over the infra.device.tunnel_state _tunnels table.

Reads are bare dict.get (atomic in CPython), matching the existing lock-free
reads at device_manager 1135/1200. The async attempt_restart delegates to
infra.device.tunnel_restart.attempt_tunnel_restart, which takes _tunnels_lock
internally.

The five api/main collaborators that attempt_tunnel_restart needs
(engine_registry, device_manager, broadcast, auto_sync, watchdog_factory) are
supplied by a ctor-injected ``restart_collaborators`` resolver — a zero-arg
callable wired in main.py (the composition root). The resolver is called lazily
per-restart so the registry imports zero api/main modules.
"""

from __future__ import annotations


class WifiTunnelRegistry:
    def __init__(self, *, restart_collaborators=None):
        """``restart_collaborators`` is a zero-arg callable returning a mapping
        with keys engine_registry / device_manager / broadcast / auto_sync /
        watchdog_factory. Optional so plain reads (get_runner / is_running)
        work without wiring; attempt_restart requires it."""
        self._restart_collaborators = restart_collaborators

    def get_runner(self, udid: str):
        from infra.device.tunnel_state import _tunnels
        return _tunnels.get(udid)

    def is_running(self, udid: str) -> bool:
        runner = self.get_runner(udid)
        return bool(runner is not None and runner.is_running())

    async def attempt_restart(self, udid: str) -> bool:
        from infra.device.tunnel_restart import attempt_tunnel_restart

        runner = self.get_runner(udid)
        if runner is None or not runner.target_ip or not runner.target_port:
            return False

        collaborators = self._restart_collaborators()
        ok = await attempt_tunnel_restart(
            udid, runner.target_ip, runner.target_port, None, runner,
            **collaborators,
        )
        return bool(ok)
