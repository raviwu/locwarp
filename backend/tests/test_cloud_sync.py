# Removed: test_migrate_bookmarks_rollback_on_post_copy_failure — it asserted
# that migrate_bookmarks rolled back *dst* when *src.unlink* raised after the
# copy. That behaviour was already absent from the implementation (the old
# code logged and swallowed the error) and is intentionally absent from the
# post-tunnel-helper-split implementation (unlink failure now propagates so
# the user sees the real OS error; the data is safe in *dst*).
#
# Removed: simulated EPERM on iCloud reads in migrate_bookmarks — no longer
# possible now that the backend runs as the file owner (not root), so the
# silent-adopt branch was deleted from cloud_sync.py.
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


def test_migrate_bookmarks_unlink_failure_propagates(tmp_path, monkeypatch):
    """After copy succeeds, an unlink OSError must surface to the caller —
    the data is safe in *dst* but the user needs to see the real OS error
    rather than have it silently swallowed."""
    src = tmp_path / "src" / "bookmarks.json"
    src.parent.mkdir()
    src.write_text('{"categories":[],"bookmarks":[]}', encoding="utf-8")
    dst = tmp_path / "dst" / "bookmarks.json"
    dst.parent.mkdir()

    original_unlink = Path.unlink

    def boom(self, *args, **kwargs):
        if self == src:
            raise PermissionError(f"simulated unlink failure on {self}")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", boom)

    with pytest.raises(PermissionError, match="simulated unlink failure"):
        migrate_bookmarks(src=src, dst=dst)

    # Data is safe in dst, src remains (unlink failed).
    assert dst.read_text(encoding="utf-8") == '{"categories":[],"bookmarks":[]}'
    assert src.exists()
