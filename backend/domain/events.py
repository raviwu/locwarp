"""Typed WebSocket event models (pydantic v2).

Serialize with .model_dump(exclude_unset=True, exclude_none=True) so that
conditionally-present keys (declared Optional[...] = None) are omitted when
they were never set — preserving the exact wire shape device_manager.py
broadcasts today.

Imports: stdlib + pydantic ONLY (no fastapi, no core/services/api imports).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator


class WsEvent(BaseModel):
    """Base for every typed WS event. `type` is the wire discriminator.

    The model_validator ensures `type` is always included in model_fields_set
    so that model_dump(exclude_unset=True) never silently drops it — even when
    subclasses supply it via a class-level default and the caller never passes
    it explicitly.
    """

    model_config = ConfigDict()

    type: str

    @model_validator(mode="after")
    def _ensure_type_set(self) -> "WsEvent":
        self.model_fields_set.add("type")
        return self


class DdiMountedEvent(WsEvent):
    type: str = "ddi_mounted"
    udid: str


class DdiNotMountedEvent(WsEvent):
    type: str = "ddi_not_mounted"
    udid: str
    hint: str


class DdiMountingEvent(WsEvent):
    type: str = "ddi_mounting"
    udid: str


class DdiMountFailedEvent(WsEvent):
    type: str = "ddi_mount_failed"
    udid: str
    error: Optional[str] = None
