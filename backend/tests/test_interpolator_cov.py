"""Characterization tests for services.interpolator (RouteInterpolator).

PURE math module. Every expected number below was produced by running the
ACTUAL module once and freezing the output — these assert current behavior,
not idealized behavior. Randomness is seeded; no network involved.
"""
from __future__ import annotations

import math
import random

import pytest

from models.schemas import Coordinate
from services.interpolator import RouteInterpolator as R


# ---------------------------------------------------------------------------
# haversine
# ---------------------------------------------------------------------------

def test_haversine_one_degree_equator():
    # 1 degree of longitude at the equator, frozen WGS-84-mean-radius value.
    assert R.haversine(0, 0, 0, 1) == pytest.approx(111194.92664455874, rel=0, abs=1e-6)


def test_haversine_one_degree_meridian_equals_equator():
    # By symmetry of the formula, 1 deg N/S at the equator == 1 deg E/W.
    assert R.haversine(0, 0, 1, 0) == pytest.approx(111194.92664455874, abs=1e-6)


def test_haversine_identical_points_is_zero():
    assert R.haversine(10.0, 20.0, 10.0, 20.0) == 0.0


def test_haversine_is_symmetric():
    d1 = R.haversine(25.03, 121.5, 35.6, 139.7)
    d2 = R.haversine(35.6, 139.7, 25.03, 121.5)
    assert d1 == pytest.approx(d2, abs=1e-9)


# ---------------------------------------------------------------------------
# bearing
# ---------------------------------------------------------------------------

def test_bearing_due_north():
    assert R.bearing(0, 0, 1, 0) == 0.0


def test_bearing_due_east():
    assert R.bearing(0, 0, 0, 1) == pytest.approx(90.0, abs=1e-9)


def test_bearing_due_south_is_180():
    assert R.bearing(1, 0, 0, 0) == pytest.approx(180.0, abs=1e-9)


def test_bearing_due_west_wraps_to_270():
    # atan2 yields -90 which % 360 -> 270.
    assert R.bearing(0, 1, 0, 0) == pytest.approx(270.0, abs=1e-9)


def test_bearing_always_in_0_360():
    b = R.bearing(0, 0, -1, -1)
    assert 0.0 <= b < 360.0


# ---------------------------------------------------------------------------
# interpolate
# ---------------------------------------------------------------------------

def test_interpolate_empty_returns_empty():
    assert R.interpolate([], 10.0) == []


def test_interpolate_single_point_seeds_one_with_zero_bearing():
    out = R.interpolate([Coordinate(lat=5, lng=5)], 10.0)
    assert out == [
        {"lat": 5.0, "lng": 5.0, "timestamp_offset": 0.0, "bearing": 0.0, "seg_idx": 0}
    ]


def test_interpolate_zero_speed_returns_only_seed():
    coords = [Coordinate(lat=0, lng=0), Coordinate(lat=0, lng=0.001)]
    out = R.interpolate(coords, speed_mps=0.0)
    # step_dist <= 0 short-circuits after the seed; seed bearing is the
    # bearing toward the next coord (due east -> 90).
    assert len(out) == 1
    assert out[0]["bearing"] == pytest.approx(90.0, abs=1e-9)
    assert out[0]["timestamp_offset"] == 0.0


def test_interpolate_negative_speed_returns_only_seed():
    coords = [Coordinate(lat=0, lng=0), Coordinate(lat=0, lng=0.001)]
    out = R.interpolate(coords, speed_mps=-5.0)
    assert len(out) == 1


def test_interpolate_single_segment_exact_emits():
    coords = [Coordinate(lat=0, lng=0), Coordinate(lat=0, lng=0.001)]
    out = R.interpolate(coords, speed_mps=10.0, interval_sec=1.0)
    # Seed + 11 dense ticks + final waypoint = 13 points (frozen).
    assert len(out) == 13

    # Seed point.
    assert out[0]["lat"] == 0.0
    assert out[0]["lng"] == 0.0
    assert out[0]["timestamp_offset"] == 0.0
    assert out[0]["bearing"] == pytest.approx(90.0, abs=1e-9)

    # First dense tick: 10 m east at fraction 10/111.19...
    assert out[1]["lng"] == pytest.approx(8.993216059187303e-05, abs=1e-15)
    assert out[1]["timestamp_offset"] == pytest.approx(1.0)
    assert out[1]["seg_idx"] == 0

    # Every dense tick carries the segment bearing (due east).
    for p in out[1:]:
        assert p["bearing"] == pytest.approx(90.0, abs=1e-9)

    # Final waypoint is the exact endpoint with total_distance/speed offset.
    last = out[-1]
    assert last["lat"] == 0.0
    assert last["lng"] == 0.001
    assert last["timestamp_offset"] == pytest.approx(11.119492664455876)


def test_interpolate_timestamp_offsets_are_evenly_spaced():
    coords = [Coordinate(lat=0, lng=0), Coordinate(lat=0, lng=0.001)]
    out = R.interpolate(coords, speed_mps=10.0, interval_sec=1.0)
    dense = out[1:-1]  # drop seed and final waypoint
    offsets = [p["timestamp_offset"] for p in dense]
    assert offsets == [float(i) for i in range(1, 12)]


def test_interpolate_skips_zero_length_segment():
    # Middle coord duplicates the first -> seg 0 has zero distance and is
    # skipped (continue), so all dense emits belong to seg 1.
    coords = [
        Coordinate(lat=0, lng=0),
        Coordinate(lat=0, lng=0),
        Coordinate(lat=0, lng=0.0001),
    ]
    out = R.interpolate(coords, speed_mps=5.0, interval_sec=1.0)
    assert len(out) == 4
    # Seed is seg_idx 0; every subsequent emit lands on seg_idx 1.
    assert out[0]["seg_idx"] == 0
    for p in out[1:]:
        assert p["seg_idx"] == 1


def test_interpolate_final_waypoint_deduped_when_tick_lands_on_end():
    # step_dist == total distance: the loop emits the endpoint exactly, and
    # the dedup guard (prev == last) suppresses an extra final append.
    coords = [Coordinate(lat=0, lng=0), Coordinate(lat=0, lng=0.001)]
    total = R.haversine(0, 0, 0, 0.001)
    out = R.interpolate(coords, speed_mps=total, interval_sec=1.0)
    assert len(out) == 2
    assert out[-1]["lng"] == 0.001
    assert out[-1]["timestamp_offset"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# add_jitter
# ---------------------------------------------------------------------------

def test_add_jitter_zero_returns_input_unchanged():
    assert R.add_jitter(10, 20, 0) == (10, 20)


def test_add_jitter_negative_returns_input_unchanged():
    assert R.add_jitter(10, 20, -5) == (10, 20)


def test_add_jitter_seeded_is_deterministic():
    random.seed(42)
    lat, lng = R.add_jitter(10, 20, 50)
    assert lat == pytest.approx(9.999992800140323, abs=1e-12)
    assert lng == pytest.approx(19.99999122712836, abs=1e-12)


def test_add_jitter_stays_within_radius():
    random.seed(123)
    base_lat, base_lng = 10.0, 20.0
    for _ in range(200):
        lat, lng = R.add_jitter(base_lat, base_lng, 50.0)
        # Drift must never exceed the requested radius (small tolerance for
        # the flat-earth small-angle approximation used in add_jitter).
        d = R.haversine(base_lat, base_lng, lat, lng)
        assert d <= 50.0 + 1e-3


# ---------------------------------------------------------------------------
# move_point
# ---------------------------------------------------------------------------

def test_move_point_north_one_degree():
    # ~111195 m north of the equator -> ~1 degree latitude, longitude unchanged.
    lat, lng = R.move_point(0, 0, 0, 111195.0)
    assert lat == pytest.approx(1.0000006597013325, abs=1e-12)
    assert lng == pytest.approx(0.0, abs=1e-12)


def test_move_point_east_one_degree():
    lat, lng = R.move_point(0, 0, 90, 111195.0)
    assert lat == pytest.approx(0.0, abs=1e-12)
    assert lng == pytest.approx(1.0000006597013325, abs=1e-12)


def test_move_point_zero_distance_is_noop():
    lat, lng = R.move_point(25.0, 121.5, 45.0, 0.0)
    assert lat == pytest.approx(25.0, abs=1e-12)
    assert lng == pytest.approx(121.5, abs=1e-12)


def test_move_point_distance_matches_haversine():
    lat, lng = R.move_point(10.0, 20.0, 37.0, 500.0)
    assert R.haversine(10.0, 20.0, lat, lng) == pytest.approx(500.0, rel=1e-6)


# ---------------------------------------------------------------------------
# random_point_in_radius
# ---------------------------------------------------------------------------

def test_random_point_in_radius_seeded_rng_deterministic():
    rng = random.Random(7)
    lat, lng = R.random_point_in_radius(10, 20, 100, rng)
    assert lat == pytest.approx(9.999843712099795, abs=1e-12)
    assert lng == pytest.approx(20.000317193240452, abs=1e-12)


def test_random_point_in_radius_same_seed_same_sequence():
    # Dual-device group mode relies on shared-seed reproducibility.
    a = random.Random(99)
    b = random.Random(99)
    for _ in range(5):
        assert R.random_point_in_radius(0, 0, 250, a) == R.random_point_in_radius(0, 0, 250, b)


def test_random_point_in_radius_within_radius():
    rng = random.Random(2024)
    for _ in range(300):
        lat, lng = R.random_point_in_radius(35.0, 139.0, 100.0, rng)
        d = R.haversine(35.0, 139.0, lat, lng)
        assert d <= 100.0 + 1e-3


def test_random_point_in_radius_default_rng_runs():
    # No rng -> falls back to module-global random; just exercise the branch.
    random.seed(0)
    lat, lng = R.random_point_in_radius(0, 0, 10, None)
    assert isinstance(lat, float)
    assert isinstance(lng, float)
