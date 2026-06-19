"""TunnelRegistry port — abstracts the WiFi tunnel runner table."""

from __future__ import annotations

from typing import Protocol


class TunnelRegistry(Protocol):
    def is_running(self, udid: str) -> bool: ...
    def get_runner(self, udid: str): ...  # TunnelRunner | None
    async def attempt_restart(self, udid: str) -> bool: ...
