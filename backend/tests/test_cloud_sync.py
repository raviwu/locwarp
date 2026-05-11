from pathlib import Path

import pytest

from services.cloud_sync import detect_icloud_path


def test_detect_icloud_path_macos_returns_path_when_folder_exists(tmp_path, monkeypatch):
    monkeypatch.setattr("services.cloud_sync.sys.platform", "darwin")
    fake_home = tmp_path / "home"
    icloud = fake_home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    icloud.mkdir(parents=True)
    monkeypatch.setattr("services.cloud_sync.Path.home", staticmethod(lambda: fake_home))
    assert detect_icloud_path() == icloud


def test_detect_icloud_path_macos_returns_none_when_folder_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("services.cloud_sync.sys.platform", "darwin")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr("services.cloud_sync.Path.home", staticmethod(lambda: fake_home))
    assert detect_icloud_path() is None


def test_detect_icloud_path_windows_returns_path_when_folder_exists(tmp_path, monkeypatch):
    monkeypatch.setattr("services.cloud_sync.sys.platform", "win32")
    fake_home = tmp_path / "home"
    icloud = fake_home / "iCloudDrive"
    icloud.mkdir(parents=True)
    monkeypatch.setattr("services.cloud_sync.Path.home", staticmethod(lambda: fake_home))
    assert detect_icloud_path() == icloud


def test_detect_icloud_path_unsupported_platform_returns_none(monkeypatch):
    monkeypatch.setattr("services.cloud_sync.sys.platform", "linux")
    assert detect_icloud_path() is None
