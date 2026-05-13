"""DeviceManager.get_display_name resolves the user-friendly DeviceName
for WiFi-only sessions where no USB enumeration is currently active."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config import DEVICE_NAMES_FILE
from core.device_manager import DeviceManager, _ActiveConnection


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DEVICE_NAMES_FILE", tmp_path / "device_names.json")
    monkeypatch.setattr(
        "core.device_manager.DEVICE_NAMES_FILE", tmp_path / "device_names.json"
    )
    yield


def _make_dm() -> DeviceManager:
    """Build a DeviceManager that won't crash without real iOS hardware."""
    dm = DeviceManager.__new__(DeviceManager)
    dm._connections = {}
    dm._lock = MagicMock()
    return dm


def test_returns_live_connection_name(tmp_path):
    dm = _make_dm()
    dm._connections["abc"] = _ActiveConnection(
        udid="abc",
        lockdown=MagicMock(),
        ios_version="17.0",
        connection_type="Network",
        name="Ravi's iPhone",
        rsd=MagicMock(),
    )
    assert dm.get_display_name("abc") == "Ravi's iPhone"


def test_falls_back_to_persisted_cache_when_no_live_connection(tmp_path):
    (tmp_path / "device_names.json").write_text(
        json.dumps({"abc": "Cached Phone"})
    )
    dm = _make_dm()
    assert dm.get_display_name("abc") == "Cached Phone"


def test_falls_back_to_persisted_cache_when_live_name_is_generic(tmp_path):
    """If the live connection only has a generic 'iPhone' / 'Unknown',
    prefer the persisted cache which may carry the user's real name."""
    (tmp_path / "device_names.json").write_text(
        json.dumps({"abc": "Cached Phone"})
    )
    dm = _make_dm()
    dm._connections["abc"] = _ActiveConnection(
        udid="abc",
        lockdown=MagicMock(),
        ios_version="17.0",
        connection_type="Network",
        name="iPhone",  # generic — should NOT win over the cache
        rsd=MagicMock(),
    )
    assert dm.get_display_name("abc") == "Cached Phone"


def test_returns_none_when_nothing_known(tmp_path):
    dm = _make_dm()
    assert dm.get_display_name("abc") is None


def test_returns_none_for_empty_udid(tmp_path):
    dm = _make_dm()
    assert dm.get_display_name("") is None
