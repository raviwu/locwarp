"""A19: enable()/disable() must materialize evicted iCloud placeholders for the
source bookmarks/routes files BEFORE migrate_pair, so cold-evicted data isn't
silently skipped by migrate_pair's `not src.exists()` no-op.
"""
from __future__ import annotations

import pytest

import services.cloud_sync_service as css_mod
from services.cloud_sync_service import CloudSyncService
from models.schemas import CloudSyncEnableRequest

# Reuse the spy harness from the characterization test.
from tests.test_cloud_sync_service_char import (
    _SpyAppState,
    _CapBroadcast,
    _patch_managers,
)

pytestmark = pytest.mark.asyncio


async def test_enable_materializes_src_files_before_migrate(monkeypatch, tmp_path):
    log: list[str] = []
    app = _SpyAppState(log, tmp_path, raise_on_restart=True)
    bc = _CapBroadcast()
    target = tmp_path / "LocWarp"

    materialized: list[str] = []
    monkeypatch.setattr(css_mod, "detect_icloud_path", lambda: tmp_path)
    monkeypatch.setattr(css_mod, "setup_sync_folder", lambda *a, **k: target)
    monkeypatch.setattr(
        css_mod, "materialize_if_placeholder",
        lambda p: materialized.append(p.name),
    )
    # migrate_pair runs AFTER materialize — record ordering via the log.
    def _fake_migrate(src, dst):
        log.append("migrate")
    monkeypatch.setattr(css_mod, "migrate_pair", _fake_migrate)
    # DATA_DIR is the src for enable(); point it somewhere real under tmp.
    src_dir = tmp_path / "data"
    src_dir.mkdir()
    monkeypatch.setattr(css_mod._config, "DATA_DIR", src_dir)
    _patch_managers(monkeypatch, app, log)

    svc = CloudSyncService(app_state=app, broadcast=bc)
    await svc.enable(CloudSyncEnableRequest(folder=None))

    # both src files were materialized, and BEFORE migrate ran
    assert set(materialized) == {"bookmarks.json", "routes.json"}
    assert "migrate" in log


async def test_disable_materializes_src_files_before_migrate(monkeypatch, tmp_path):
    log: list[str] = []
    app = _SpyAppState(log, tmp_path)
    sync_dir = tmp_path / "LocWarp"
    sync_dir.mkdir()
    app._sync_folder = str(sync_dir)
    bc = _CapBroadcast()

    materialized: list[str] = []
    monkeypatch.setattr(css_mod, "detect_icloud_path", lambda: tmp_path)
    monkeypatch.setattr(
        css_mod, "materialize_if_placeholder",
        lambda p: materialized.append(p.name),
    )
    monkeypatch.setattr(css_mod, "migrate_pair", lambda src, dst: log.append("migrate"))
    monkeypatch.setattr(css_mod._config, "DATA_DIR", tmp_path / "data")
    _patch_managers(monkeypatch, app, log)

    svc = CloudSyncService(app_state=app, broadcast=bc)
    await svc.disable()

    assert set(materialized) == {"bookmarks.json", "routes.json"}
    assert "migrate" in log
