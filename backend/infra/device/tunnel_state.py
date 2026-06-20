"""Single home for the WiFi-tunnel registry state.

Previously these three module-level objects lived in api/device.py, forcing
infra/device/wifi_tunnel.py to lazily `from api.device import _tunnels` — the
last infra->api import edge. Hosting them in infra lets both api/device.py and
the WifiTunnelRegistry read them WITHOUT either importing the other.

api/device.py re-binds these as module aliases, so api.device._tunnels IS this
dict (same object) and the ~30 existing call sites — plus every test that does
device_mod._tunnels.clear() — keep working unchanged.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.wifi_tunnel import TunnelRunner

_tunnels: dict[str, "TunnelRunner"] = {}
_tunnel_watchdogs: dict[str, asyncio.Task] = {}
_tunnels_lock = asyncio.Lock()
