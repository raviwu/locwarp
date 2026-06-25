"""resolve_speed_profile(jitter_enabled=False) zeroes speed_jitter without
mutating the shared SPEED_PROFILES table."""
from __future__ import annotations

import config


def test_default_keeps_speed_jitter():
    p = config.resolve_speed_profile("walking")
    assert p["speed_jitter"] == 0.12


def test_disabled_zeroes_speed_jitter():
    p = config.resolve_speed_profile("walking", jitter_enabled=False)
    assert p["speed_jitter"] == 0.0


def test_disabled_does_not_mutate_shared_table():
    _ = config.resolve_speed_profile("walking", jitter_enabled=False)
    assert config.SPEED_PROFILES["walking"]["speed_jitter"] == 0.12


def test_custom_speed_with_jitter_disabled():
    p = config.resolve_speed_profile("walking", speed_kmh=18.0, jitter_enabled=False)
    assert p["speed_jitter"] == 0.0
    # speed still derives from the custom km/h
    assert abs(p["speed_mps"] - 18.0 / 3.6) < 1e-9
