"""CloudSyncService — enable/disable/dismiss/status use-case for cloud-sync.

Extracted verbatim from the four ``api/cloud_sync.py`` endpoint bodies. The
router now thins to constructing this service from the injected engine
registry (AppState) + event publisher and delegating.

``enable``/``disable`` deliberately raise ``HTTPException`` (400/500) to keep
the frozen HTTP status surface unchanged — that is the one retained fastapi
import in ``services/`` (whitelisted in ``.importlinter``). The danger-zone
stop -> replace -> restart ordering and the ``try/except RuntimeError`` around
the watcher rebind (TestClient has no running loop) are preserved exactly.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException

import config as _config
from models.schemas import (
    CloudSyncEnableRequest, CloudSyncResource, CloudSyncStatus,
)
from services.cloud_sync import (
    detect_icloud_path, materialize_if_placeholder, migrate_pair, setup_sync_folder,
)

logger = logging.getLogger(__name__)


def _resource(path: Path, count: int, category_count: int) -> CloudSyncResource:
    return CloudSyncResource(
        path=str(path), count=count, category_count=category_count,
    )


class CloudSyncService:
    """Use-case for the unified cloud-sync toggle (bookmarks + routes)."""

    def __init__(self, *, app_state, broadcast):
        self._app = app_state
        self._broadcast = broadcast

    def build_status(self) -> CloudSyncStatus:
        bm = self._app.bookmark_manager
        rm = self._app.route_manager
        bm_path = bm._bookmarks_path()
        rt_path = rm._routes_path()
        icloud = detect_icloud_path()
        return CloudSyncStatus(
            enabled=self._app._sync_folder is not None,
            sync_folder=self._app._sync_folder,
            detected_icloud_path=str(icloud) if icloud else None,
            prompt_dismissed=self._app._cloud_sync_dismissed,
            bookmarks=_resource(
                bm_path,
                count=len(bm.list_bookmarks()),
                category_count=len(bm.list_categories()),
            ),
            routes=_resource(
                rt_path,
                count=len(rm.list_routes()),
                category_count=len(rm.list_categories()),
            ),
        )

    @staticmethod
    def _materialize_src(src_dir: Path) -> None:
        """Force-download any iCloud-evicted bookmarks/routes placeholder under
        *src_dir* before a migrate, so cold-evicted data is not silently
        skipped by migrate_pair's `not src.exists()` no-op. No-op when the
        files are already local / not under iCloud / brctl is unavailable."""
        for name in ("bookmarks.json", "routes.json"):
            materialize_if_placeholder(src_dir / name)

    async def enable(self, req: CloudSyncEnableRequest) -> CloudSyncStatus:
        if req.folder:
            parent = Path(req.folder)
        else:
            parent = detect_icloud_path()
        if parent is None:
            raise HTTPException(
                400, "No iCloud Drive detected and no custom folder provided"
            )
        try:
            target_folder = setup_sync_folder(parent)
        except (FileNotFoundError, OSError) as exc:
            raise HTTPException(400, str(exc))

        # Pull any iCloud-evicted source files local first, else migrate_pair
        # silently skips a placeholder it sees as a missing src.
        self._materialize_src(_config.DATA_DIR)
        try:
            migrate_pair(_config.DATA_DIR, target_folder)
        except Exception as exc:
            logger.exception("cloud-sync enable: migrate_pair failed")
            raise HTTPException(500, f"Migration failed: {exc}")

        self._app._sync_folder = str(target_folder)
        self._app.save_settings()

        # Re-init managers so they pick up the new path; rebind watchers.
        # Stop the OUTGOING managers' watches first — otherwise their handles
        # on the shared file_watcher Observer outlive the manager objects and
        # we leak one watch per toggle.
        if self._app.bookmark_manager is not None:
            self._app.bookmark_manager.stop_watcher()
        if self._app.route_manager is not None:
            self._app.route_manager.stop_watcher()
        from bootstrap.factories import make_bookmark_manager, make_route_manager
        self._app.bookmark_manager = make_bookmark_manager()
        self._app.route_manager = make_route_manager()
        # restart_*_watcher calls asyncio.get_running_loop() which requires a
        # running event loop. Under FastAPI in production this is always present.
        # Under TestClient (which uses a sync ASGI transport without a live loop)
        # it raises RuntimeError — catch that case and skip the rebind gracefully.
        try:
            self._app.restart_bookmark_watcher()
        except RuntimeError:
            logger.debug("cloud-sync enable: no running loop; skipping bookmark watcher rebind")
        try:
            self._app.restart_route_watcher()
        except RuntimeError:
            logger.debug("cloud-sync enable: no running loop; skipping route watcher rebind")

        # Tell every WS-connected client to re-fetch — managers were rebuilt and
        # the in-memory store may differ from what the user last saw.
        await self._broadcast(("bookmarks_changed", {"reason": "cloud_sync_enabled"}))
        await self._broadcast(("routes_changed", {"reason": "cloud_sync_enabled"}))

        return self.build_status()

    async def disable(self) -> CloudSyncStatus:
        if self._app._sync_folder is None:
            return self.build_status()

        # Stop the OUTGOING managers' watches first — otherwise their live
        # handles on the shared file_watcher Observer fire on files that
        # migrate_pair is moving back to DATA_DIR (symmetric with enable()).
        if self._app.bookmark_manager is not None:
            self._app.bookmark_manager.stop_watcher()
        if self._app.route_manager is not None:
            self._app.route_manager.stop_watcher()

        current = Path(self._app._sync_folder)
        # Pull any iCloud-evicted files in the sync folder local first, else
        # the migrate-back silently drops a cloud-only-evicted store and the
        # canonical link is cut with _sync_folder=None below (A19).
        self._materialize_src(current)
        try:
            migrate_pair(current, _config.DATA_DIR)
        except Exception as exc:
            logger.exception("cloud-sync disable: migrate_pair failed")
            raise HTTPException(500, f"Migration failed: {exc}")

        self._app._sync_folder = None
        self._app.save_settings()

        from bootstrap.factories import make_bookmark_manager, make_route_manager
        self._app.bookmark_manager = make_bookmark_manager()
        self._app.route_manager = make_route_manager()
        try:
            self._app.restart_bookmark_watcher()
        except RuntimeError:
            logger.debug("cloud-sync disable: no running loop; skipping bookmark watcher rebind")
        try:
            self._app.restart_route_watcher()
        except RuntimeError:
            logger.debug("cloud-sync disable: no running loop; skipping route watcher rebind")

        await self._broadcast(("bookmarks_changed", {"reason": "cloud_sync_disabled"}))
        await self._broadcast(("routes_changed", {"reason": "cloud_sync_disabled"}))

        return self.build_status()

    def dismiss_prompt(self) -> CloudSyncStatus:
        self._app._cloud_sync_dismissed = True
        self._app.save_settings()
        return self.build_status()
