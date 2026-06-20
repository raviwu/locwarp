"""Characterization: CloudSyncService enable/disable/dismiss/status.

Pins the danger-zone stop -> replace -> restart ordering of the extracted
cloud-sync use-case, verbatim from the pre-move ``api/cloud_sync.py`` endpoint
bodies:

  (a) the OUTGOING bookmark + route watchers are stopped BEFORE the managers
      are rebuilt, and the watchers are restarted AFTER the rebuild
      (``stop:bm-old`` < ``restart:bm``, ``stop:rm-old`` < ``restart:rm``);
  (b) ``save_settings()`` runs AFTER ``_sync_folder`` is set, so the persisted
      line carries the NEW sync folder;
  (c) enable/disable broadcast exactly ``["bookmarks_changed",
      "routes_changed"]`` (in that order) via the injected publisher;
  (d) the manager instances are swapped (new BookmarkManager / RouteManager);
  (e) the ``try/except RuntimeError`` around the restart calls is preserved —
      a no-running-loop RuntimeError is swallowed and the flow still completes.

These four endpoint bodies had no direct service-level test before the
extraction.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import services.cloud_sync_service as css_mod
from services.cloud_sync_service import CloudSyncService

pytestmark = pytest.mark.asyncio


class _FakeManager:
    """Stands in for BookmarkManager / RouteManager."""

    def __init__(self, kind: str, log: list[str], path: Path):
        self._kind = kind
        self._log = log
        self._path = path

    def stop_watcher(self) -> None:
        self._log.append(f"stop:{self._kind}")

    # status-building reads
    def _bookmarks_path(self) -> Path:
        return self._path

    def _routes_path(self) -> Path:
        return self._path

    def list_bookmarks(self):
        return []

    def list_routes(self):
        return []

    def list_categories(self):
        return []


class _SpyAppState:
    """Spy double of AppState that records the ordered watcher / save log."""

    def __init__(self, log: list[str], tmp_path: Path, *, raise_on_restart=False):
        self._log = log
        self._tmp = tmp_path
        self._raise_on_restart = raise_on_restart
        self._sync_folder: str | None = None
        self._cloud_sync_dismissed = False
        self.bookmark_manager = _FakeManager("bm-old", log, tmp_path / "bm.json")
        self.route_manager = _FakeManager("rm-old", log, tmp_path / "rm.json")

    def save_settings(self) -> None:
        self._log.append(f"save:{self._sync_folder}")

    def restart_bookmark_watcher(self) -> None:
        self._log.append("restart:bm")
        if self._raise_on_restart:
            raise RuntimeError("no running event loop")

    def restart_route_watcher(self) -> None:
        self._log.append("restart:rm")
        if self._raise_on_restart:
            raise RuntimeError("no running event loop")


class _CapBroadcast:
    """Captures the (type, payload) tuples the service publishes."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def __call__(self, event):
        etype, data = event
        self.events.append((etype, {**data}))


def _patch_managers(monkeypatch, app, log):
    """Make the service rebuild new fake managers (and record the swap)."""

    def _new_bm():
        log.append("new:bm")
        m = _FakeManager("bm-new", log, app._tmp / "bm.json")
        return m

    def _new_rm():
        log.append("new:rm")
        m = _FakeManager("rm-new", log, app._tmp / "rm.json")
        return m

    # The service lazily imports these inside enable()/disable(), so patch the
    # source modules rather than the service module namespace.
    monkeypatch.setattr("services.bookmarks.BookmarkManager", _new_bm)
    monkeypatch.setattr("services.route_store.RouteManager", _new_rm)


async def test_enable_orders_stop_before_restart_saves_new_folder_broadcasts(
    monkeypatch, tmp_path
):
    log: list[str] = []
    app = _SpyAppState(log, tmp_path, raise_on_restart=True)
    bc = _CapBroadcast()

    target = tmp_path / "LocWarp"
    monkeypatch.setattr(css_mod, "detect_icloud_path", lambda: tmp_path)
    monkeypatch.setattr(css_mod, "setup_sync_folder", lambda *a, **k: target)
    monkeypatch.setattr(css_mod, "migrate_pair", lambda *a, **k: (0, 0))
    _patch_managers(monkeypatch, app, log)

    svc = CloudSyncService(app_state=app, broadcast=bc)
    from models.schemas import CloudSyncEnableRequest

    status = await svc.enable(CloudSyncEnableRequest(folder=None))

    # stop the OLD watchers before restarting the rebuilt ones
    assert log.index("stop:bm-old") < log.index("restart:bm")
    assert log.index("stop:rm-old") < log.index("restart:rm")
    # managers were swapped (new instances built) before restart
    assert log.index("new:bm") < log.index("restart:bm")
    assert log.index("new:rm") < log.index("restart:rm")
    # save carries the NEW sync_folder (save AFTER _sync_folder set)
    assert f"save:{target}" in log
    # the RuntimeError from restart was swallowed; flow completed and returned
    assert app._sync_folder == str(target)
    assert status.enabled is True
    assert status.sync_folder == str(target)
    # broadcasts: bookmarks then routes, exact payloads
    assert bc.events == [
        ("bookmarks_changed", {"reason": "cloud_sync_enabled"}),
        ("routes_changed", {"reason": "cloud_sync_enabled"}),
    ]
    # managers actually swapped to new instances
    assert app.bookmark_manager._kind == "bm-new"
    assert app.route_manager._kind == "rm-new"


async def test_disable_orders_and_broadcasts(monkeypatch, tmp_path):
    log: list[str] = []
    app = _SpyAppState(log, tmp_path)
    app._sync_folder = str(tmp_path / "LocWarp")
    bc = _CapBroadcast()

    monkeypatch.setattr(css_mod, "detect_icloud_path", lambda: tmp_path)
    monkeypatch.setattr(css_mod, "migrate_pair", lambda *a, **k: (0, 0))
    _patch_managers(monkeypatch, app, log)

    svc = CloudSyncService(app_state=app, broadcast=bc)
    status = await svc.disable()

    assert log.index("new:bm") < log.index("restart:bm")
    assert log.index("new:rm") < log.index("restart:rm")
    assert "save:None" in log
    assert app._sync_folder is None
    assert status.enabled is False
    assert bc.events == [
        ("bookmarks_changed", {"reason": "cloud_sync_disabled"}),
        ("routes_changed", {"reason": "cloud_sync_disabled"}),
    ]


async def test_disable_noop_when_not_enabled(monkeypatch, tmp_path):
    log: list[str] = []
    app = _SpyAppState(log, tmp_path)
    app._sync_folder = None
    bc = _CapBroadcast()
    monkeypatch.setattr(css_mod, "detect_icloud_path", lambda: tmp_path)

    svc = CloudSyncService(app_state=app, broadcast=bc)
    status = await svc.disable()

    # no rebuild, no broadcast — just current status
    assert "new:bm" not in log
    assert bc.events == []
    assert status.enabled is False


def test_dismiss_prompt_sets_flag_and_saves(tmp_path):
    log: list[str] = []
    app = _SpyAppState(log, tmp_path)
    bc = _CapBroadcast()
    svc = CloudSyncService(app_state=app, broadcast=bc)

    status = svc.dismiss_prompt()

    assert app._cloud_sync_dismissed is True
    assert "save:None" in log
    assert status.prompt_dismissed is True


def test_build_status_reflects_app_state(tmp_path):
    log: list[str] = []
    app = _SpyAppState(log, tmp_path)
    app._sync_folder = str(tmp_path / "LocWarp")
    bc = _CapBroadcast()
    svc = CloudSyncService(app_state=app, broadcast=bc)

    status = svc.build_status()
    assert status.enabled is True
    assert status.sync_folder == str(tmp_path / "LocWarp")
