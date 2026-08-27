"""config.py must not read LOCWARP_* env vars at import time.

Every fresh import here goes through the ``reimport_config`` fixture
(``conftest.reimport_config_module``), which restores the original module
object afterwards — see that helper for why leaving a new one behind silently
disables the suite's real-data isolation.
"""
import sys


def test_config_module_has_no_os_import_and_no_csp_mode(reimport_config):
    with reimport_config() as cfg:
        assert not hasattr(cfg, "_os"), "config still imports os as _os for env reads"
        assert not hasattr(cfg, "CSP_MODE"), "config still owns CSP_MODE env read"
        assert cfg.CORS_ORIGINS == [
            "http://127.0.0.1:8777", "http://localhost:8777",
            "http://127.0.0.1:5173", "http://localhost:5173",
        ]


def test_importing_config_ignores_lan_origin_env(reimport_config, monkeypatch):
    monkeypatch.setenv("LOCWARP_LAN_ORIGIN", "http://192.168.1.50:8777")
    with reimport_config() as cfg:
        assert "http://192.168.1.50:8777" not in cfg.CORS_ORIGINS


def test_reimport_puts_the_original_config_module_object_back(reimport_config):
    """Regression pin for the leak documented on ``reimport_config_module``.

    Asserts the state AFTER the context exits — the half a re-import-based
    teardown gets wrong, and the half the rest of the suite depends on.
    """
    import bootstrap.factories as factories

    before = sys.modules["config"]
    assert factories.config is before, "precondition: factories holds the live object"

    with reimport_config() as cfg:
        assert cfg is not before, "the context is supposed to hand out a fresh module"
        assert sys.modules["config"] is cfg

    assert sys.modules["config"] is before
    assert factories.config is sys.modules["config"], (
        "a stale factories.config makes conftest's path isolation a no-op and "
        "lets tests write the user's real ~/.locwarp files"
    )
