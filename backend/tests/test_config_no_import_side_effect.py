"""config.py must not create ~/.locwarp at import time."""
import importlib
import sys
from pathlib import Path


def test_importing_config_does_not_mkdir_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.modules.pop("config", None)
    cfg = importlib.import_module("config")
    try:
        expected = Path(tmp_path) / ".locwarp"
        assert cfg.DATA_DIR == expected
        assert not expected.exists(), "importing config created DATA_DIR — import-time mkdir leaked back in"
    finally:
        sys.modules.pop("config", None)
        importlib.import_module("config")
