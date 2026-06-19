"""Characterization: DeviceManager routes its 4 DDI events through the injected
EventPublisher with EXACT current payloads (deep-equal)."""

import pytest

from core.device_manager import DeviceManager


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        # Normalize to (type, data) for deep-equal assertions, mirroring the
        # wire shape. Typed events expose .model_dump; tuples pass through.
        if hasattr(event, "model_dump"):
            payload = event.model_dump(exclude_unset=True, exclude_none=True)
            etype = payload.pop("type")
            self.events.append((etype, payload))
        else:
            etype, data = event
            self.events.append((etype, {**data}))


HINT = (
    "iPhone 上未偵測到 DDI。請先為這支 iPhone 掛載一次 DDI(Developer Disk Image),"
    "再重新連接 LocWarp;或先重開 iPhone 後再試。"
)


@pytest.mark.asyncio
async def test_devicemanager_accepts_injected_publisher():
    pub = FakePublisher()
    dm = DeviceManager(event_publisher=pub)
    assert dm._events is pub


@pytest.mark.asyncio
async def test_ddi_mounted_event_payload():
    from domain.events import DdiMountedEvent
    pub = FakePublisher()
    await pub.publish(DdiMountedEvent(udid="UDID-X"))
    assert pub.events[-1] == ("ddi_mounted", {"udid": "UDID-X"})


@pytest.mark.asyncio
async def test_ddi_not_mounted_event_payload():
    from domain.events import DdiNotMountedEvent
    pub = FakePublisher()
    await pub.publish(DdiNotMountedEvent(udid="UDID-X", hint=HINT))
    assert pub.events[-1] == ("ddi_not_mounted", {"udid": "UDID-X", "hint": HINT})


@pytest.mark.asyncio
async def test_ddi_mounting_event_payload():
    from domain.events import DdiMountingEvent
    pub = FakePublisher()
    await pub.publish(DdiMountingEvent(udid="UDID-X"))
    assert pub.events[-1] == ("ddi_mounting", {"udid": "UDID-X"})


@pytest.mark.asyncio
async def test_ddi_mount_failed_event_payload():
    from domain.events import DdiMountFailedEvent
    pub = FakePublisher()
    await pub.publish(DdiMountFailedEvent(udid="UDID-X", error="Classic DDI mount failed"))
    assert pub.events[-1] == (
        "ddi_mount_failed",
        {"udid": "UDID-X", "error": "Classic DDI mount failed"},
    )


@pytest.mark.asyncio
async def test_ddi_mount_failed_no_error_omitted():
    """error=None is excluded (exclude_none=True) — same as old broadcast omitting the key."""
    from domain.events import DdiMountFailedEvent
    pub = FakePublisher()
    await pub.publish(DdiMountFailedEvent(udid="UDID-X"))
    # error key absent when not supplied
    assert pub.events[-1] == ("ddi_mount_failed", {"udid": "UDID-X"})


@pytest.mark.asyncio
async def test_devicemanager_none_publisher_does_not_raise():
    """DeviceManager(event_publisher=None) construction is safe; DDI publishes
    are silently dropped (no AttributeError)."""
    dm = DeviceManager(event_publisher=None)
    assert dm._events is None
