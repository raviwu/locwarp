"""Guard: the dead ReconnectManager is gone. Real reconnection lives in
_per_tunnel_watchdog (api/device.py) + the USB presence watchdog (main.py).
"""
from __future__ import annotations

import importlib

import pytest


def test_reconnect_module_is_deleted():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("services.reconnect")


def test_main_has_no_reconnect_manager_attribute():
    import main
    st = main.AppState()
    assert not hasattr(st, "reconnect_manager"), (
        "AppState should no longer carry a reconnect_manager slot"
    )
    assert "ReconnectManager" not in dir(main)
