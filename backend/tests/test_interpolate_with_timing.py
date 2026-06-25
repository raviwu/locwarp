"""Tests for RouteInterpolator.interpolate_with_timing (timing-aware replay).

Pure math — no network, no clock. Asserts (a) timing-present honors the
original cadence (timestamp_offset reflects the recorded timeline), and
(b) timing-absent/invalid falls back to the byte-identical constant-speed path.
"""
from __future__ import annotations

from models.schemas import Coordinate
from domain.movement import RouteInterpolator as R


def _two_point() -> list[Coordinate]:
    return [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]


def test_none_offsets_falls_back_to_constant_speed():
    coords = _two_point()
    with_timing = R.interpolate_with_timing(coords, None, speed_mps=20.0, interval_sec=1.0)
    plain = R.interpolate(coords, speed_mps=20.0, interval_sec=1.0)
    assert with_timing == plain


def test_wrong_length_offsets_falls_back():
    coords = _two_point()
    out = R.interpolate_with_timing(coords, [0.0], speed_mps=20.0, interval_sec=1.0)
    assert out == R.interpolate(coords, speed_mps=20.0, interval_sec=1.0)


def test_non_monotonic_offsets_falls_back():
    coords = _two_point()
    out = R.interpolate_with_timing(coords, [5.0, 1.0], speed_mps=20.0, interval_sec=1.0)
    assert out == R.interpolate(coords, speed_mps=20.0, interval_sec=1.0)


def test_zero_span_offsets_falls_back():
    coords = _two_point()
    out = R.interpolate_with_timing(coords, [3.0, 3.0], speed_mps=20.0, interval_sec=1.0)
    assert out == R.interpolate(coords, speed_mps=20.0, interval_sec=1.0)


def test_empty_coords_returns_empty():
    assert R.interpolate_with_timing([], [0.0], speed_mps=20.0) == []


def test_single_point_returns_one_seed():
    out = R.interpolate_with_timing([Coordinate(lat=5.0, lng=5.0)], [0.0], speed_mps=20.0)
    assert len(out) == 1
    assert out[0]["timestamp_offset"] == 0.0
    assert out[0]["seg_idx"] == 0
    assert out[0]["bearing"] == 0.0
    assert (out[0]["lat"], out[0]["lng"]) == (5.0, 5.0)

def test_timing_present_honors_original_cadence():
    # Two segments with DIFFERENT original durations: first leg took 10s,
    # second leg took 2s (so the device should move fast on leg 2).
    coords = [
        Coordinate(lat=25.0, lng=121.0),
        Coordinate(lat=25.0, lng=121.001),
        Coordinate(lat=25.0, lng=121.002),
    ]
    offsets = [0.0, 10.0, 12.0]
    out = R.interpolate_with_timing(coords, offsets, speed_mps=20.0, interval_sec=1.0)
    # Seed + final vertex present with the ORIGINAL timeline offsets.
    assert out[0]["timestamp_offset"] == 0.0
    assert out[-1]["timestamp_offset"] == 12.0
    assert (out[-1]["lat"], out[-1]["lng"]) == (25.0, 121.002)
    # Monotonic non-decreasing timestamp_offset.
    offs = [p["timestamp_offset"] for p in out]
    assert offs == sorted(offs)
    # The total original span is 12s sampled every 1s → ~13 points
    # (seed at 0, ticks at 1..11, final at 12). The dense tick at offset 11
    # lands on leg 2 (offsets[1]=10..offsets[2]=12), so its seg_idx is 1.
    tick_at_11 = next(p for p in out if p["timestamp_offset"] == 11.0)
    assert tick_at_11["seg_idx"] == 1

def test_timing_present_dense_points_interpolate_position():
    coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]
    offsets = [0.0, 4.0]  # one 4-second segment
    out = R.interpolate_with_timing(coords, offsets, speed_mps=20.0, interval_sec=1.0)
    # offset 0,1,2,3 then final at 4. Point at offset 2.0 is halfway across.
    mid = next(p for p in out if p["timestamp_offset"] == 2.0)
    assert mid["lat"] == 25.0
    assert abs(mid["lng"] - 121.0005) < 1e-9
    assert mid["seg_idx"] == 0
