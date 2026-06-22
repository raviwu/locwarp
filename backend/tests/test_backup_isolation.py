"""Pins that the autouse conftest guard redirects config.BACKUP_DIR to the
per-test tmp dir — so a backup test can never write the real ~/.locwarp/backups.
"""


def test_backup_dir_isolated_to_tmp(tmp_path):
    import config

    assert config.BACKUP_DIR == tmp_path / "backups"
