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


def test_fallback_path_single_coord_returns_seed():
    """Single-point coord list → len(offsets) < 2, so falls back to interpolate().
    (Was misleadingly named test_single_point_returns_one_seed; tests the FALLBACK
    path because len([0.0]) == 1 which is < 2, so `valid` is False.)"""
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


def test_timing_aware_two_coord_exact_boundary():
    """Two-coord route with a single interval at the exact boundary.

    offsets=[0.0, 1.0], interval_sec=1.0 → the loop emits no ticks
    (t=1.0 is NOT < total_time=1.0), so the result is seed + final vertex only.
    Both points honour the original timing offsets (0.0 and 1.0).
    This tests the genuine timing-aware path (valid offsets, len >= 2), not the
    fallback. (M2 coverage gap: the old test_single_point_returns_one_seed was
    exercising the fallback path.)
    """
    coords = [Coordinate(lat=10.0, lng=20.0), Coordinate(lat=10.001, lng=20.001)]
    offsets = [0.0, 1.0]
    out = R.interpolate_with_timing(coords, offsets, speed_mps=20.0, interval_sec=1.0)
    # seed at 0.0, final at 1.0 (no intermediate ticks because t=1.0 is not < 1.0)
    assert out[0]["timestamp_offset"] == 0.0
    assert out[-1]["timestamp_offset"] == 1.0
    assert (out[-1]["lat"], out[-1]["lng"]) == (10.001, 20.001)
    # monotonic
    offs = [p["timestamp_offset"] for p in out]
    assert offs == sorted(offs)


def test_no_near_duplicate_final_point_with_float_interval():
    """I1 regression: non-integer interval_sec accumulates float error.

    With offsets=[0.0, 12.0] and interval_sec=0.1, the 120th accumulated step
    lands at 0.1 * 120 = 11.999999999999998 (float drift), which is within 1e-9
    of total_time=12.0. Without the epsilon guard the final vertex was appended a
    SECOND time (the exact-equality coordinate check did not fire because the loop
    tick's coords already equalled the final vertex at such a tiny offset). The fix
    guards on timestamp_offset within _EPS=1e-9 of total_time.

    Asserts:
    - no two consecutive points have timestamp_offsets within 1e-9 AND identical coords
    - the final point has timestamp_offset == total_time (12.0 exactly)
    """
    coords = [Coordinate(lat=35.0, lng=135.0), Coordinate(lat=35.001, lng=135.001)]
    offsets = [0.0, 12.0]
    out = R.interpolate_with_timing(coords, offsets, speed_mps=20.0, interval_sec=0.1)

    # Final point must be exactly total_time
    assert out[-1]["timestamp_offset"] == 12.0, (
        f"final offset {out[-1]['timestamp_offset']} != 12.0"
    )

    # No near-duplicate consecutive points (offset within 1e-9 AND same coords)
    EPS = 1e-9
    for i in range(len(out) - 1):
        p, q = out[i], out[i + 1]
        offsets_close = abs(p["timestamp_offset"] - q["timestamp_offset"]) <= EPS
        coords_same = p["lat"] == q["lat"] and p["lng"] == q["lng"]
        assert not (offsets_close and coords_same), (
            f"near-duplicate at indices {i}/{i+1}: "
            f"offsets {p['timestamp_offset']}/{q['timestamp_offset']}, "
            f"coords ({p['lat']},{p['lng']})"
        )
