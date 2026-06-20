"""config.py must not read LOCWARP_* env vars at import time."""
import importlib
import sys


def test_config_module_has_no_os_import_and_no_csp_mode():
    sys.modules.pop("config", None)
    cfg = importlib.import_module("config")
    try:
        assert not hasattr(cfg, "_os"), "config still imports os as _os for env reads"
        assert not hasattr(cfg, "CSP_MODE"), "config still owns CSP_MODE env read"
        assert cfg.CORS_ORIGINS == [
            "http://127.0.0.1:8777", "http://localhost:8777",
            "http://127.0.0.1:5173", "http://localhost:5173",
        ]
    finally:
        sys.modules.pop("config", None)
        importlib.import_module("config")


def test_importing_config_ignores_lan_origin_env(monkeypatch):
    monkeypatch.setenv("LOCWARP_LAN_ORIGIN", "http://192.168.1.50:8777")
    sys.modules.pop("config", None)
    cfg = importlib.import_module("config")
    try:
        assert "http://192.168.1.50:8777" not in cfg.CORS_ORIGINS
    finally:
        sys.modules.pop("config", None)
        importlib.import_module("config")
