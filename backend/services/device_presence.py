"""Pure helper for the usbmux presence watchdog's appearance logic."""
from __future__ import annotations

from collections.abc import Iterable


def compute_usb_reconnect_targets(
    connected_udids: Iterable[str],
    present_usb_serials: Iterable[str],
    *,
    max_devices: int = 3,
) -> list[str]:
    """USB serials with NO active connection on ANY transport, under the cap.

    A device already in ``connected_udids`` — regardless of its connection_type
    (USB *or* Network) — is never 'new'. Comparison is case-insensitive because
    usbmux and connect() may store the serial in different casing. Original
    casing from ``present_usb_serials`` is preserved so the caller can hand the
    result straight to ``dm.connect()``.
    """
    all_connected_lc = {u.lower() for u in connected_udids}
    if len(all_connected_lc) >= max_devices:
        return []
    present_map: dict[str, str] = {}
    for s in present_usb_serials:
        present_map[s.lower()] = s
    new_lc = set(present_map) - all_connected_lc
    return [present_map[lc] for lc in sorted(new_lc)]
