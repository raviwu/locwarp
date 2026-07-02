"""Pure appearance-selection logic for the usbmux presence watchdog.

Regression: a device already connected on ANY transport (USB or Network) must
never be treated as a 'new' USB device — otherwise the watchdog busy-loops,
re-'detecting' it every poll (~34% of the log in the 2026-07-02 sweep)."""
from services.device_presence import (
    compute_usb_promotion_targets,
    compute_usb_reconnect_targets,
)


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


def test_network_connected_and_present_on_usb_is_promoted():
    # The core bug this fixes: a device connected via Network that is now
    # also visible on USB must be promoted, so the panel switches off WiFi.
    assert compute_usb_promotion_targets(
        connections={"RENEE": "Network"},
        present_usb_serials=["RENEE"],
    ) == ["RENEE"]


def test_already_usb_connected_is_not_promoted():
    # Nothing to promote — it's already on USB.
    assert compute_usb_promotion_targets(
        connections={"RENEE": "USB"},
        present_usb_serials=["RENEE"],
    ) == []


def test_network_connected_but_absent_from_usb_is_not_promoted():
    # Nothing to promote to — the device isn't present on USB at all.
    assert compute_usb_promotion_targets(
        connections={"RENEE": "Network"},
        present_usb_serials=[],
    ) == []


def test_promotion_comparison_is_case_insensitive():
    assert compute_usb_promotion_targets(
        connections={"renee": "Network"},
        present_usb_serials=["RENEE"],
    ) == ["renee"]


def test_promotion_returns_original_casing_from_connections_keys():
    # Caller uses this UDID directly in dm.disconnect()/dm.connect(), which
    # index _connections by the exact casing DeviceManager stored it under —
    # so the returned casing must come from `connections`, not from
    # `present_usb_serials`.
    assert compute_usb_promotion_targets(
        connections={"MixedCase-UDID": "Network"},
        present_usb_serials=["mixedcase-udid"],
    ) == ["MixedCase-UDID"]
