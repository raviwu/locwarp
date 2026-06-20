"""Top-level cloud-sync router covering bookmarks + routes.

Single toggle, single synced folder under <iCloud Drive>/LocWarp/.

The endpoint bodies live in ``services.cloud_sync_service.CloudSyncService``;
the routes thin to constructing that service from the injected engine registry
(AppState) + event publisher and delegating.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.deps import get_engine_registry, get_event_publisher
from models.schemas import CloudSyncEnableRequest, CloudSyncStatus
from services.cloud_sync_service import CloudSyncService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cloud-sync", tags=["cloud-sync"])


def _service(app_state, publisher) -> CloudSyncService:
    return CloudSyncService(app_state=app_state, broadcast=publisher.publish)


@router.get("/status", response_model=CloudSyncStatus)
async def cloud_sync_status(
    app_state=Depends(get_engine_registry),
    publisher=Depends(get_event_publisher),
):
    return _service(app_state, publisher).build_status()


@router.post("/enable", response_model=CloudSyncStatus)
async def cloud_sync_enable(
    req: CloudSyncEnableRequest,
    app_state=Depends(get_engine_registry),
    publisher=Depends(get_event_publisher),
):
    return await _service(app_state, publisher).enable(req)


@router.post("/disable", response_model=CloudSyncStatus)
async def cloud_sync_disable(
    app_state=Depends(get_engine_registry),
    publisher=Depends(get_event_publisher),
):
    return await _service(app_state, publisher).disable()


@router.post("/dismiss-prompt", response_model=CloudSyncStatus)
async def cloud_sync_dismiss_prompt(
    app_state=Depends(get_engine_registry),
    publisher=Depends(get_event_publisher),
):
    return _service(app_state, publisher).dismiss_prompt()
