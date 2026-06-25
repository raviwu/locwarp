"""Characterization: ConnectProgressEvent serializes with exclude_unset/
exclude_none so absent optional keys (udid/attempt/max) stay absent — same
discipline as the DDI events in test_device_manager_events.py."""

import pytest


class FakePublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        if hasattr(event, "model_dump"):
            payload = event.model_dump(exclude_unset=True, exclude_none=True)
            etype = payload.pop("type")
            self.events.append((etype, payload))
        else:
            etype, data = event
            self.events.append((etype, {**data}))


@pytest.mark.asyncio
async def test_connect_progress_minimal_phase_only():
    from domain.events import ConnectProgressEvent
    pub = FakePublisher()
    await pub.publish(ConnectProgressEvent(phase="opening_tunnel"))
    assert pub.events[-1] == ("connect_progress", {"phase": "opening_tunnel"})


@pytest.mark.asyncio
async def test_connect_progress_rsd_attempt_carries_attempt_and_max():
    from domain.events import ConnectProgressEvent
    pub = FakePublisher()
    await pub.publish(ConnectProgressEvent(phase="rsd_attempt", attempt=2, max=10))
    assert pub.events[-1] == (
        "connect_progress",
        {"phase": "rsd_attempt", "attempt": 2, "max": 10},
    )


@pytest.mark.asyncio
async def test_connect_progress_with_udid():
    from domain.events import ConnectProgressEvent
    pub = FakePublisher()
    await pub.publish(ConnectProgressEvent(phase="connected", udid="UDID-Z"))
    assert pub.events[-1] == (
        "connect_progress",
        {"phase": "connected", "udid": "UDID-Z"},
    )


def test_connect_progress_type_default_is_connect_progress():
    from domain.events import ConnectProgressEvent
    ev = ConnectProgressEvent(phase="checking_ddi")
    assert ev.type == "connect_progress"
