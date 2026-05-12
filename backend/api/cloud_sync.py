"""Top-level cloud-sync router covering bookmarks + routes.

Single toggle, single synced folder under <iCloud Drive>/LocWarp/.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

import config as _config
from models.schemas import (
    CloudSyncEnableRequest, CloudSyncResource, CloudSyncStatusUnified,
)
from services.cloud_sync import (
    detect_icloud_path, migrate_pair, setup_sync_folder,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cloud-sync", tags=["cloud-sync"])


def _resource(path: Path, count: int, category_count: int) -> CloudSyncResource:
    return CloudSyncResource(
        path=str(path), count=count, category_count=category_count,
    )


def _build_status() -> CloudSyncStatusUnified:
    from main import app_state
    bm = app_state.bookmark_manager
    rm = app_state.route_manager
    bm_path = bm._bookmarks_path()
    rt_path = rm._routes_path()
    icloud = detect_icloud_path()
    return CloudSyncStatusUnified(
        enabled=app_state._sync_folder is not None,
        sync_folder=app_state._sync_folder,
        detected_icloud_path=str(icloud) if icloud else None,
        prompt_dismissed=app_state._cloud_sync_dismissed,
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


@router.get("/status", response_model=CloudSyncStatusUnified)
async def cloud_sync_status():
    return _build_status()


@router.post("/enable", response_model=CloudSyncStatusUnified)
async def cloud_sync_enable(req: CloudSyncEnableRequest):
    from main import app_state
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

    try:
        migrate_pair(_config.DATA_DIR, target_folder)
    except Exception as exc:
        logger.exception("cloud-sync enable: migrate_pair failed")
        raise HTTPException(500, f"Migration failed: {exc}")

    app_state._sync_folder = str(target_folder)
    app_state.save_settings()

    # Re-init managers so they pick up the new path; rebind watchers.
    from services.bookmarks import BookmarkManager
    from services.route_store import RouteManager
    app_state.bookmark_manager = BookmarkManager()
    app_state.route_manager = RouteManager()
    # restart_*_watcher calls asyncio.get_running_loop() which requires a
    # running event loop. Under FastAPI in production this is always present.
    # Under TestClient (which uses a sync ASGI transport without a live loop)
    # it raises RuntimeError — catch that case and skip the rebind gracefully.
    try:
        app_state.restart_bookmark_watcher()
    except RuntimeError:
        logger.debug("cloud-sync enable: no running loop; skipping bookmark watcher rebind")
    try:
        app_state.restart_route_watcher()
    except RuntimeError:
        logger.debug("cloud-sync enable: no running loop; skipping route watcher rebind")

    return _build_status()


@router.post("/disable", response_model=CloudSyncStatusUnified)
async def cloud_sync_disable():
    from main import app_state
    if app_state._sync_folder is None:
        return _build_status()

    current = Path(app_state._sync_folder)
    try:
        migrate_pair(current, _config.DATA_DIR)
    except Exception as exc:
        logger.exception("cloud-sync disable: migrate_pair failed")
        raise HTTPException(500, f"Migration failed: {exc}")

    app_state._sync_folder = None
    app_state.save_settings()

    from services.bookmarks import BookmarkManager
    from services.route_store import RouteManager
    app_state.bookmark_manager = BookmarkManager()
    app_state.route_manager = RouteManager()
    try:
        app_state.restart_bookmark_watcher()
    except RuntimeError:
        logger.debug("cloud-sync disable: no running loop; skipping bookmark watcher rebind")
    try:
        app_state.restart_route_watcher()
    except RuntimeError:
        logger.debug("cloud-sync disable: no running loop; skipping route watcher rebind")

    return _build_status()


@router.post("/dismiss-prompt", response_model=CloudSyncStatusUnified)
async def cloud_sync_dismiss_prompt():
    from main import app_state
    app_state._cloud_sync_dismissed = True
    app_state.save_settings()
    return _build_status()
