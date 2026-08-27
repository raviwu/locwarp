"""config.py must not create ~/.locwarp at import time."""
from pathlib import Path


def test_importing_config_does_not_mkdir_data_dir(tmp_path, monkeypatch, reimport_config):
    monkeypatch.setenv("HOME", str(tmp_path))
    with reimport_config() as cfg:
        expected = Path(tmp_path) / ".locwarp"
        assert cfg.DATA_DIR == expected
        assert not expected.exists(), (
            "importing config created DATA_DIR — import-time mkdir leaked back in"
        )
