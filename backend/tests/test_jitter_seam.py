"""Tests for the rng-injectable jitter seam (add_jitter rng param + jitter_speed).

Pure math; deterministic via a seeded random.Random. Asserts seed-determinism,
the ±fraction bound, and the strict-positive speed floor."""
from __future__ import annotations

import random

from domain.movement import RouteInterpolator as R


def test_add_jitter_seed_deterministic():
    a = R.add_jitter(25.0, 121.0, 5.0, rng=random.Random(7))
    b = R.add_jitter(25.0, 121.0, 5.0, rng=random.Random(7))
    assert a == b


def test_add_jitter_zero_meters_is_noop():
    assert R.add_jitter(25.0, 121.0, 0.0, rng=random.Random(7)) == (25.0, 121.0)


def test_jitter_speed_within_fraction_bound():
    base = 10.0
    frac = 0.15
    rng = random.Random(123)
    for _ in range(1000):
        v = R.jitter_speed(base, frac, rng=rng)
        assert base * (1 - frac) - 1e-9 <= v <= base * (1 + frac) + 1e-9


def test_jitter_speed_never_zero_or_negative():
    rng = random.Random(999)
    for _ in range(1000):
        v = R.jitter_speed(0.02, 0.15, rng=rng)
        assert v > 0.0


def test_jitter_speed_seed_deterministic():
    assert R.jitter_speed(10.0, 0.15, rng=random.Random(5)) == R.jitter_speed(10.0, 0.15, rng=random.Random(5))


def test_jitter_speed_zero_fraction_unchanged():
    assert R.jitter_speed(10.0, 0.0, rng=random.Random(5)) == 10.0
