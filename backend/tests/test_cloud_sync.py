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


from services.cloud_sync import setup_sync_folder


def test_setup_sync_folder_creates_subfolder(tmp_path):
    result = setup_sync_folder(tmp_path)
    assert result == tmp_path / "LocWarp"
    assert result.is_dir()


def test_setup_sync_folder_is_idempotent(tmp_path):
    first = setup_sync_folder(tmp_path)
    second = setup_sync_folder(tmp_path)
    assert first == second
    assert second.is_dir()


def test_setup_sync_folder_rejects_non_writable_parent(tmp_path, monkeypatch):
    not_exists = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        setup_sync_folder(not_exists)


from services.cloud_sync import migrate_bookmarks


def test_migrate_bookmarks_copies_and_deletes_source(tmp_path):
    src = tmp_path / "src" / "bookmarks.json"
    src.parent.mkdir()
    src.write_text('{"categories":[],"bookmarks":[]}', encoding="utf-8")
    dst = tmp_path / "dst" / "bookmarks.json"
    dst.parent.mkdir()

    migrate_bookmarks(src=src, dst=dst)

    assert dst.read_text(encoding="utf-8") == '{"categories":[],"bookmarks":[]}'
    assert not src.exists()


def test_migrate_bookmarks_noop_when_source_missing(tmp_path):
    src = tmp_path / "missing.json"
    dst = tmp_path / "dst.json"
    migrate_bookmarks(src=src, dst=dst)
    assert not dst.exists()


def test_migrate_bookmarks_rollback_on_post_copy_failure(tmp_path, monkeypatch):
    src = tmp_path / "src.json"
    src.write_text("payload", encoding="utf-8")
    dst = tmp_path / "dst.json"

    original_unlink = Path.unlink

    def fail_unlink(self, missing_ok=False):
        if self == src:
            raise OSError("simulated failure deleting source")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(OSError):
        migrate_bookmarks(src=src, dst=dst)

    assert src.exists()
    assert not dst.exists()
