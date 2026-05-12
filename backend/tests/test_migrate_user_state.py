import os
import pytest
from pathlib import Path

from migrate_user_state import migrate_user_state


def _seed(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "bookmarks.json").write_text("{}")
    (root / "logs").mkdir(exist_ok=True)
    (root / "logs" / "backend.log").write_text("hello")


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root to seed root-owned files")
def test_migrate_chowns_root_files_to_caller_uid(tmp_path):
    home = tmp_path
    locwarp = home / ".locwarp"
    _seed(locwarp)
    target_uid = int(os.environ.get("SUDO_UID", os.getuid()))
    target_gid = int(os.environ.get("SUDO_GID", os.getgid()))
    result = migrate_user_state(home=str(home), uid=target_uid, gid=target_gid)
    assert result["chowned"] >= 3
    assert result["failed"] == 0
    for path in [locwarp, locwarp / "bookmarks.json", locwarp / "logs", locwarp / "logs" / "backend.log"]:
        assert path.stat().st_uid == target_uid


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
