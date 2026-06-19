"""WsEventPublisher: typed-event path and tuple path must produce identical
broadcast(event_type, data) calls for the same logical event."""

import pytest

from domain.events import DdiMountFailedEvent
from infra.events.ws_event_publisher import WsEventPublisher


@pytest.mark.asyncio
async def test_tuple_path_calls_broadcast_with_type_and_data():
    calls: list = []

    async def fake_broadcast(event_type, data):
        calls.append((event_type, data))

    pub = WsEventPublisher(broadcast=fake_broadcast)
    await pub.publish(("ddi_mount_failed", {"udid": "U1", "error": "Classic DDI mount failed"}))

    assert calls == [("ddi_mount_failed", {"udid": "U1", "error": "Classic DDI mount failed"})]


@pytest.mark.asyncio
async def test_typed_path_matches_tuple_path():
    typed_calls: list = []
    tuple_calls: list = []

    async def cap_typed(event_type, data):
        typed_calls.append((event_type, data))

    async def cap_tuple(event_type, data):
        tuple_calls.append((event_type, data))

    ev = DdiMountFailedEvent(udid="U1", error="Classic DDI mount failed")

    await WsEventPublisher(broadcast=cap_typed).publish(ev)
    await WsEventPublisher(broadcast=cap_tuple).publish(
        ("ddi_mount_failed", {"udid": "U1", "error": "Classic DDI mount failed"})
    )

    # Same logical event -> identical broadcast call (deep-equal parsed dicts).
    assert typed_calls == tuple_calls
    assert typed_calls == [
        ("ddi_mount_failed", {"udid": "U1", "error": "Classic DDI mount failed"})
    ]


@pytest.mark.asyncio
async def test_typed_path_omits_unset_optional():
    calls: list = []

    async def cap(event_type, data):
        calls.append((event_type, data))

    # error unset -> must not appear.
    await WsEventPublisher(broadcast=cap).publish(DdiMountFailedEvent(udid="U1"))
    assert calls == [("ddi_mount_failed", {"udid": "U1"})]


@pytest.mark.asyncio
async def test_publish_is_order_preserving():
    seen: list = []

    async def cap(event_type, data):
        seen.append(event_type)

    pub = WsEventPublisher(broadcast=cap)
    await pub.publish(("a", {}))
    await pub.publish(("b", {}))
    await pub.publish(("c", {}))
    assert seen == ["a", "b", "c"]
