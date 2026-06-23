"""DeviceManager.is_usb_connected — the transport-specific signal wired into the
WiFi-tunnel in-use guard (core/wifi_tunnel.open_tunnel_with_reconcile).

Must be True ONLY for a USB connection. The WiFi-tunnel auto-restart
(infra/device/tunnel_restart) re-opens the WiFi tunnel while the device is STILL
in _connections as "Network" (the disconnect runs after the re-open), so a plain
is_connected here would wrongly refuse the restart's self-heal close+retry.
"""
from core.device_manager import DeviceManager, _ActiveConnection


def _dm_with(conn_type=None):
    dm = DeviceManager.__new__(DeviceManager)  # bypass __init__ (no real hardware)
    dm._connections = {}
    if conn_type is not None:
        dm._connections["udid-1"] = _ActiveConnection(
            udid="udid-1",
            lockdown=object(),
            ios_version="17.0",
            connection_type=conn_type,
        )
    return dm


def test_is_usb_connected_true_for_usb():
    assert _dm_with("USB").is_usb_connected("udid-1") is True


def test_is_usb_connected_false_for_network():
    # The WiFi-restart non-refusal hinges on this: a Network device must read
    # False so the reconcile's self-heal close+retry is left alone.
    assert _dm_with("Network").is_usb_connected("udid-1") is False


def test_is_usb_connected_false_when_absent():
    assert _dm_with(None).is_usb_connected("udid-1") is False
