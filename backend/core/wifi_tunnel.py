"""User-side WiFi tunnel facade — see Task 6.

This module currently delegates to the helper via TunnelRunner being
re-exported from _tunnel_runner. Task 6 swaps in a thin facade that
calls helper_client.open_wifi_tunnel/close_tunnel instead. For Task 4
we just re-export so nothing breaks at import time.
"""

from core._tunnel_runner import TunnelRunner  # noqa: F401
