"""WsEventPublisher — concrete EventPublisher backed by an injected broadcast callable.

publish() is awaited in-line and order-preserving. The broadcast callable
is REQUIRED (injected by the composition root, which wires in
api.websocket.broadcast) so infra/ never imports api/ — keeping the
inward-only dependency rule intact.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Union

from domain.events import WsEvent


class WsEventPublisher:
    """Concrete EventPublisher backed by an injected broadcast callable.

    publish() is awaited in-line and order-preserving. The broadcast callable
    is REQUIRED (injected by the composition root, which wires in
    api.websocket.broadcast) so infra/ never imports api/ — keeping the
    inward-only dependency rule intact.
    """

    def __init__(self, broadcast: Callable[[str, dict], Awaitable[None]]) -> None:
        self._broadcast = broadcast

    async def publish(self, event: "Union[WsEvent, tuple[str, dict]]") -> None:
        if isinstance(event, WsEvent):
            payload = event.model_dump(exclude_unset=True, exclude_none=True)
            event_type = payload.pop("type")
            await self._broadcast(event_type, payload)
            return
        event_type, data = event
        await self._broadcast(event_type, dict(data))
