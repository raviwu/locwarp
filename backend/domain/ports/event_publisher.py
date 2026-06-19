"""EventPublisher port — the seam device_manager pushes WS events through."""

from __future__ import annotations

from typing import Protocol, Union

from domain.events import WsEvent


class EventPublisher(Protocol):
    async def publish(self, event: "Union[WsEvent, tuple[str, dict]]") -> None: ...
