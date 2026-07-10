"""Recent places API: the rows behind the map's Recent button, each re-flyable
with one click.

Two classes share one store. Manual rows (teleport / navigate / search / the two
coord-input buttons, capped at 20) are pushed here by the frontend. `route_stop`
rows (capped at 30) are arrivals the backend records as a simulated route passes
each waypoint — `RecentPushRequest.kind` deliberately excludes that kind, so the
recorder is their only writer.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.recent import get_manager

router = APIRouter(prefix="/api/recent", tags=["recent"])


class RecentPushRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    kind: Literal["teleport", "navigate", "search", "coord_teleport", "coord_navigate"]
    name: str | None = None


@router.get("")
async def list_recent():
    return get_manager().list()


@router.post("")
async def push_recent(req: RecentPushRequest):
    try:
        entry = get_manager().push(req.lat, req.lng, req.kind, req.name)
        return entry
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("")
async def clear_recent():
    get_manager().clear()
    return {"status": "ok"}
