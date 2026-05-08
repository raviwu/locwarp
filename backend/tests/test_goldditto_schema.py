"""Schema validation tests for GoldDittoCycleRequest."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.schemas import GoldDittoCycleRequest


def _base_payload(**overrides):
    base = {
        "udid": None,
        "target": "auto",
        "lat_a": 25.0,
        "lng_a": 121.5,
        "lat_b": 25.034897,
        "lng_b": 121.545827,
        "wait_seconds": 3.0,
    }
    base.update(overrides)
    return base


def test_valid_payload_parses():
    req = GoldDittoCycleRequest(**_base_payload())
    assert req.target == "auto"
    assert req.wait_seconds == 3.0


def test_target_rejects_unknown_value():
    with pytest.raises(ValidationError):
        GoldDittoCycleRequest(**_base_payload(target="C"))


def test_wait_seconds_rejects_below_min():
    with pytest.raises(ValidationError):
        GoldDittoCycleRequest(**_base_payload(wait_seconds=0.4))


def test_wait_seconds_rejects_above_max():
    with pytest.raises(ValidationError):
        GoldDittoCycleRequest(**_base_payload(wait_seconds=10.5))


def test_lat_out_of_range_rejected():
    with pytest.raises(ValidationError):
        GoldDittoCycleRequest(**_base_payload(lat_a=95.0))
