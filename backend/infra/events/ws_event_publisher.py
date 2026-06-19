"""WsEventPublisher — concrete EventPublisher backed by api.websocket.broadcast.

publish() is awaited in-line and order-preserving. It does NOT touch the WS
connection-manager lock directly: broadcast() iterates the module-global
_connections list with no lock (existing behavior), so there is no lock to
contend with device_manager._lock — preserving the contract's lock-ordering rule.

The broadcast callable is injected via __init__ to keep infra/ free of any
api/ import at module-load time. The composition root wires in the real
api.websocket.broadcast; tests supply a fake.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Union

from domain.events import WsEvent


class WsEventPublisher:
    def __init__(
        self,
        broadcast: Callable[[str, dict], Awaitable[None]] | None = None,
    ) -> None:
        # broadcast is injected; None triggers lazy import of the real one so
        # the composition root can construct WsEventPublisher() without args.
        self._broadcast = broadcast

    async def _resolve_broadcast(self) -> Callable[[str, dict], Awaitable[None]]:
        if self._broadcast is not None:
            return self._broadcast
        # Lazy import — only reached in production (composition root), never in
        # unit tests (which always inject a fake). This avoids an import-time
        # api/ dependency inside infra/.
        from api.websocket import broadcast as real_broadcast  # noqa: PLC0415

        return real_broadcast

    async def publish(self, event: "Union[WsEvent, tuple[str, dict]]") -> None:
        broadcast = await self._resolve_broadcast()
        if isinstance(event, WsEvent):
            payload = event.model_dump(exclude_unset=True, exclude_none=True)
            # "type" is always present (guaranteed by WsEvent._ensure_type_set).
            event_type = payload.pop("type")
            await broadcast(event_type, payload)
            return
        # (type, data) tuple passthrough
        event_type, data = event
        await broadcast(event_type, dict(data))
