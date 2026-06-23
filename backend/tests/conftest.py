"""Pytest configuration. Adds the backend/ root to sys.path so tests can
import models.*, core.*, services.* the same way the runtime does.
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _ensure_data_dir():
    """Belt-and-suspenders: guarantee DATA_DIR exists for tests that build
    managers without going through the FastAPI lifespan."""
    import config
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def _isolate_real_data_paths(tmp_path, monkeypatch):
    """HARD GUARD: redirect EVERY data-file path to a per-test tmp dir so no
    test can ever read or WRITE the user's real ~/.locwarp/ or iCloud sync
    folder.

    Rationale: a non-isolated cloud-sync/concurrency test once persisted a
    stale ``sync_folder`` into the real settings.json and dumped thousands of
    ``bm{i}`` fixture bookmarks into the real iCloud bookmarks.json (2026-06).
    Per-test monkeypatching is not enough — one forgotten patch corrupts real
    user data. This autouse runs first; tests that set their own paths simply
    re-monkeypatch over it (using the same tmp_path, so they stay consistent).
    """
    import sys
    bm = tmp_path / "bookmarks.json"
    rt = tmp_path / "routes.json"
    st = tmp_path / "settings.json"

    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(config, "SETTINGS_FILE", st, raising=False)
    monkeypatch.setattr(config, "_DEFAULT_BOOKMARKS_FILE", bm, raising=False)
    monkeypatch.setattr(config, "ROUTES_FILE", rt, raising=False)
    # BACKUP_DIR is derived from DATA_DIR at import time, so patching DATA_DIR
    # alone leaves it pointing at the real ~/.locwarp/backups. Redirect it too,
    # or a backup test would write real user data (the exact hazard above).
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups", raising=False)

    # Module-level copies captured at import time in the runtime modules.
    if "main" in sys.modules:
        monkeypatch.setattr(sys.modules["main"], "SETTINGS_FILE", st, raising=False)
    if "services.bookmarks" in sys.modules:
        sb = sys.modules["services.bookmarks"]
        monkeypatch.setattr(sb, "BOOKMARKS_FILE", bm, raising=False)
        monkeypatch.setattr(sb, "_CONFIG_DEFAULT_BOOKMARKS_FILE", bm, raising=False)
    if "services.route_store" in sys.modules:
        sr = sys.modules["services.route_store"]
        monkeypatch.setattr(sr, "ROUTES_FILE", rt, raising=False)
        monkeypatch.setattr(sr, "_CONFIG_DEFAULT_ROUTES_FILE", rt, raising=False)


@pytest.fixture(autouse=True)
def _reset_wifi_tunnel_globals():
    """Reset core.wifi_tunnel module-level injection seams after each test.

    ``_helper_client`` and ``_in_use_predicate`` are global singletons set via
    set_helper_client / set_in_use_predicate. A test that injects one (e.g. a
    leaked ``set_in_use_predicate(lambda: True)``) would otherwise poison
    unrelated reconcile tests that rely on the always-False / None defaults.
    Mirror the data-path guard above for these injected singletons.
    """
    yield
    if "core.wifi_tunnel" in sys.modules:
        wt = sys.modules["core.wifi_tunnel"]
        wt.set_in_use_predicate(lambda _u: False)
        wt.set_helper_client(None)
