import os
import pytest
from pathlib import Path

from migrate_user_state import migrate_user_state


def _seed(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "bookmarks.json").write_text("{}")
    (root / "logs").mkdir(exist_ok=True)
    (root / "logs" / "backend.log").write_text("hello")


def test_migrate_chowns_mismatched_entries(tmp_path, monkeypatch):
    """Whenever an entry's uid does not match the requested target, the
    migration must call ``os.chown(path, uid, gid, follow_symlinks=False)``
    on it. We stub ``os.chown`` so the test runs without root and asserts
    the call set, not the on-disk ownership (which is the kernel's job)."""
    home = tmp_path
    locwarp = home / ".locwarp"
    _seed(locwarp)

    calls: list[tuple[str, int, int, bool]] = []

    def fake_chown(path, uid, gid, *, follow_symlinks=True):
        calls.append((os.fspath(path), uid, gid, follow_symlinks))

    monkeypatch.setattr("migrate_user_state.os.chown", fake_chown)

    # Pass a uid the seeded files don't have (the test runner owns them),
    # forcing every entry through the chown branch.
    fake_uid = os.getuid() + 1000
    fake_gid = os.getgid() + 1000
    result = migrate_user_state(home=str(home), uid=fake_uid, gid=fake_gid)

    assert result["failed"] == 0
    # locwarp dir + bookmarks.json + logs dir + logs/backend.log == 4
    assert result["chowned"] == 4
    assert len(calls) == 4

    # Every call must use follow_symlinks=False (the LPE-safety invariant).
    assert all(fs is False for *_, fs in calls), calls
    # Every call targets the requested (uid, gid).
    assert all(u == fake_uid and g == fake_gid for _, u, g, _ in calls), calls

    expected_paths = {
        str(locwarp),
        str(locwarp / "bookmarks.json"),
        str(locwarp / "logs"),
        str(locwarp / "logs" / "backend.log"),
    }
    assert {p for p, *_ in calls} == expected_paths


def test_migrate_no_op_when_already_owned(tmp_path):
    home = tmp_path
    _seed(home / ".locwarp")
    result = migrate_user_state(home=str(home), uid=os.getuid(), gid=os.getgid())
    assert result["chowned"] == 0
    assert result["failed"] == 0
    assert result["skipped"] >= 3


def test_migrate_missing_home_dirs_returns_zeros(tmp_path):
    result = migrate_user_state(home=str(tmp_path), uid=os.getuid(), gid=os.getgid())
    assert result == {"chowned": 0, "skipped": 0, "failed": 0}


def test_migrate_does_not_follow_symlinks(tmp_path):
    """Security regression: symlinks inside the migrated tree must be
    skipped, not chowned and not descended through. If we followed
    them, a local attacker could plant ``~/.locwarp/evil -> /etc/sudoers``
    and have root rewrite sudoers ownership for them — textbook LPE."""
    home = tmp_path
    locwarp = home / ".locwarp"
    _seed(locwarp)
    outside = tmp_path / "outside.txt"
    outside.write_text("untouchable")
    # Plant a symlink inside .locwarp pointing at an outside file.
    (locwarp / "evil").symlink_to(outside)
    # Plant a symlink to a directory that we must NOT descend into.
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "should_not_chown.txt").write_text("hands off")
    (locwarp / "evil_dir").symlink_to(outside_dir)

    result = migrate_user_state(home=str(home), uid=os.getuid(), gid=os.getgid())
    # We already own everything in the tree, so nothing needed chowning.
    assert result["chowned"] == 0
    # At minimum the two symlinks should be counted as skipped, on top
    # of the seeded real files that were already owned by us.
    assert result["skipped"] >= 2
    # The symlinks must still exist and still resolve where they did.
    assert (locwarp / "evil").is_symlink()
    assert (locwarp / "evil").resolve() == outside
    assert (locwarp / "evil_dir").is_symlink()
    # File behind the dir-symlink must still be there, untouched.
    assert (outside_dir / "should_not_chown.txt").read_text() == "hands off"
