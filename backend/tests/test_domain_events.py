"""Characterization tests for domain/events.py typed WS events.

Each typed event must serialize (exclude_unset, exclude_none) to EXACTLY the
dict that device_manager.py broadcasts today. Deep-equal on parsed dicts.
"""

import pytest

from domain.events import (
    WsEvent,
    DdiMountedEvent,
    DdiNotMountedEvent,
    DdiMountingEvent,
    DdiMountFailedEvent,
)

# The exact zh hint string device_manager.py lines 723-726 broadcasts.
HINT = (
    "iPhone 上未偵測到 DDI。請先為這支 iPhone 掛載一次 DDI(Developer Disk Image),"
    "再重新連接 LocWarp;或先重開 iPhone 後再試。"
)


def _dump(ev: WsEvent) -> dict:
    return ev.model_dump(exclude_unset=True, exclude_none=True)


def test_base_is_pydantic_with_type_field():
    # WsEvent is the base; subclasses set a literal default type.
    ev = DdiMountedEvent(udid="U1")
    assert isinstance(ev, WsEvent)
    assert ev.type == "ddi_mounted"


def test_ddi_mounted_payload_exact():
    ev = DdiMountedEvent(udid="U1")
    assert _dump(ev) == {"type": "ddi_mounted", "udid": "U1"}


def test_ddi_mounting_payload_exact():
    ev = DdiMountingEvent(udid="U1")
    assert _dump(ev) == {"type": "ddi_mounting", "udid": "U1"}


def test_ddi_not_mounted_payload_exact():
    ev = DdiNotMountedEvent(udid="U1", hint=HINT)
    assert _dump(ev) == {"type": "ddi_not_mounted", "udid": "U1", "hint": HINT}


def test_ddi_mount_failed_payload_exact():
    ev = DdiMountFailedEvent(udid="U1", error="Classic DDI mount failed")
    assert _dump(ev) == {
        "type": "ddi_mount_failed",
        "udid": "U1",
        "error": "Classic DDI mount failed",
    }


def test_optional_keys_absent_when_unset():
    # error is conditional; if not passed it must NOT appear in the dump.
    ev = DdiMountFailedEvent(udid="U1")
    assert _dump(ev) == {"type": "ddi_mount_failed", "udid": "U1"}
