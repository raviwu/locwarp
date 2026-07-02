"""Pure appearance-selection logic for the usbmux presence watchdog.

Regression: a device already connected on ANY transport (USB or Network) must
never be treated as a 'new' USB device — otherwise the watchdog busy-loops,
re-'detecting' it every poll (~34% of the log in the 2026-07-02 sweep)."""
from services.device_presence import compute_usb_reconnect_targets


def test_device_already_connected_any_transport_is_not_new():
    # Already-connected UDID present on USB must be excluded; only the truly
    # new device is returned. (Renee reproduced this: connected yet re-flagged.)
    assert compute_usb_reconnect_targets(
        connected_udids=["RENEE"],
        present_usb_serials=["RENEE", "NEWDEV"],
    ) == ["NEWDEV"]


def test_comparison_is_case_insensitive():
    assert compute_usb_reconnect_targets(
        connected_udids=["renee"],
        present_usb_serials=["RENEE"],
    ) == []


def test_respects_device_cap():
    assert compute_usb_reconnect_targets(
        connected_udids=["A", "B", "C"],
        present_usb_serials=["D"],
        max_devices=3,
    ) == []


def test_truly_new_device_is_returned_with_original_casing():
    assert compute_usb_reconnect_targets(
        connected_udids=[],
        present_usb_serials=["New1"],
    ) == ["New1"]
