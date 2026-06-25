"""Pure movement math for the simulation engine (clean-arch Phase 3).

This is the pure inner-ring home for referentially-transparent movement
helpers extracted from core/simulation_engine.py. It imports stdlib + pydantic
(models.schemas) ONLY and is guarded by the `no-domain-imports-outer`
import-linter contract.
"""

from __future__ import annotations

import math
import random
import time
from datetime import datetime, timedelta, timezone

from models.schemas import Coordinate

# Earth radius in meters (WGS-84 mean)
_R = 6_371_000.0


class EtaTracker:
    """Tracks progress and estimates time of arrival for route-based movement."""

    def __init__(self) -> None:
        self.total_distance: float = 0.0
        self.traveled: float = 0.0
        self.speed_mps: float = 0.0
        self.start_time: float = 0.0

    def start(self, total_distance: float, speed_mps: float) -> None:
        """Initialise the tracker at the beginning of a route."""
        self.total_distance = total_distance
        self.traveled = 0.0
        self.speed_mps = max(speed_mps, 0.001)  # avoid division by zero
        self.start_time = time.monotonic()

    def update(self, traveled: float) -> None:
        """Update the distance traveled so far."""
        self.traveled = traveled

    @property
    def progress(self) -> float:
        """Return completion as a fraction 0.0 .. 1.0."""
        if self.total_distance <= 0:
            return 1.0
        return min(self.traveled / self.total_distance, 1.0)

    @property
    def eta_seconds(self) -> float:
        """Estimated seconds remaining."""
        remaining = self.distance_remaining
        if self.speed_mps <= 0:
            return 0.0
        return remaining / self.speed_mps

    @property
    def eta_arrival(self) -> str:
        """ISO-8601 estimated arrival time."""
        secs = self.eta_seconds
        if secs <= 0:
            return ""
        arrival = datetime.now(timezone.utc) + timedelta(seconds=secs)
        return arrival.isoformat(timespec="seconds")

    @property
    def distance_remaining(self) -> float:
        """Meters still to travel."""
        return max(self.total_distance - self.traveled, 0.0)


def build_resume_snapshot(
    *,
    kind: str,
    args: dict,
    current_pos: tuple[float, float] | None,
    segment_index: int,
    user_waypoint_next: int,
    lap_count: int,
    distance_traveled: float,
    speed_was_applied: bool,
    random_walk_count: int,
    active_speed_profile: dict | None,
) -> dict:
    """Pure assembly of the resume-snapshot dict.

    Encodes two behaviors that used to live inline in
    ``SimulationEngine.capture_resumable_snapshot``:

    * the ``seg_for_resume`` kind rule — multi_stop / start_loop resume off
      ``user_waypoint_next - 1`` (the stable leg index) because the inner
      ``_move_along_route`` loop clobbers ``segment_index`` with the densified
      coord index; navigate / random_walk keep ``segment_index``;
    * the ``active_speed_profile`` key is present **iff** the profile is truthy
      (preserves the exclude_unset/exclude_none deep-equal contract).

    No engine / running-loop state — primitives in, dict out.
    """
    if kind in ("multi_stop", "start_loop"):
        seg_for_resume = max(0, int(user_waypoint_next) - 1)
    else:
        seg_for_resume = int(segment_index)
    snap = {
        "kind": kind,
        "args": dict(args),
        "current_pos": current_pos,
        "segment_index": seg_for_resume,
        "lap_count": int(lap_count),
        "user_waypoint_next": int(user_waypoint_next),
        "distance_traveled": float(distance_traveled),
        "speed_was_applied": bool(speed_was_applied),
        "random_walk_count": int(random_walk_count),
    }
    if active_speed_profile:
        snap["active_speed_profile"] = dict(active_speed_profile)
    return snap


def match_waypoints_to_coords(
    user_wps: list[Coordinate],
    planned_coords: list[Coordinate],
    start_index: int,
) -> list[int]:
    """For each user waypoint at index >= start_index, find the nearest
    planned_coord index via a MONOTONIC forward scan (each waypoint's match
    must lie strictly after the previous waypoint's match). Stops as soon as
    a waypoint can't be matched further along than the previous one, meaning
    it belongs to a later leg (multi_stop) or isn't on planned_coords.

    Pure extraction of the wp_seg_idx precompute from
    SimulationEngine._move_along_route. Behavior is byte-identical.
    """
    wp_seg_idx: list[int] = []
    last_ci = -1
    for wi in range(start_index, len(user_wps)):
        wp = user_wps[wi]
        start_ci = max(last_ci + 1, 0)
        best_ci = -1
        best_d = float("inf")
        for ci in range(start_ci, len(planned_coords)):
            d = RouteInterpolator.haversine(
                wp.lat, wp.lng,
                planned_coords[ci].lat, planned_coords[ci].lng,
            )
            if d < best_d:
                best_d = d
                best_ci = ci
        if best_ci < 0:
            break
        wp_seg_idx.append(best_ci)
        last_ci = best_ci
    return wp_seg_idx


class RouteInterpolator:
    """Stateless utilities for dense-point interpolation along a polyline."""

    # ------------------------------------------------------------------
    # Distance & bearing
    # ------------------------------------------------------------------

    @staticmethod
    def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Return the great-circle distance in **meters** between two points."""
        rlat1, rlng1 = math.radians(lat1), math.radians(lng1)
        rlat2, rlng2 = math.radians(lat2), math.radians(lng2)

        dlat = rlat2 - rlat1
        dlng = rlng2 - rlng1

        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
        )
        return _R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @staticmethod
    def bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Return the initial bearing in **degrees** (0-360) from point 1 to point 2."""
        rlat1, rlng1 = math.radians(lat1), math.radians(lng1)
        rlat2, rlng2 = math.radians(lat2), math.radians(lng2)

        dlng = rlng2 - rlng1
        x = math.sin(dlng) * math.cos(rlat2)
        y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlng)

        brng = math.degrees(math.atan2(x, y))
        return brng % 360

    # ------------------------------------------------------------------
    # Interpolation
    # ------------------------------------------------------------------

    @staticmethod
    def interpolate(
        coords: list[Coordinate],
        speed_mps: float,
        interval_sec: float = 1.0,
    ) -> list[dict]:
        """Interpolate a sparse polyline into dense, evenly-timed points.

        Walks the polyline by cumulative distance, emitting one point every
        ``step_dist = speed_mps * interval_sec`` metres. This handles three
        edge cases the old per-segment ``carry`` logic got wrong:

        1. ``step_dist > min_seg_dist``: previously a single step that
           crossed a segment boundary skipped the entire next segment, and
           ``carry`` rolled an inflated distance forward, producing emits
           that effectively traveled at ``min_seg_dist`` per tick instead
           of ``step_dist``. At ~180+ km/h with the 25 m straight-line
           densification, this collapsed to zero intermediate emits and
           the route looked frozen at start.
        2. Variable segment lengths from OSRM: same boundary-crossing bug
           skewed effective speed on routes with mixed-length segments.
        3. step_dist < min_seg_dist remains unchanged in behavior.

        Returns
        -------
        list[dict]
            Each dict contains *lat*, *lng*, *timestamp_offset* (seconds
            from start), *bearing* (degrees), and *seg_idx*.
        """
        if not coords:
            return []

        results: list[dict] = []

        # Seed the first point
        results.append(
            {
                "lat": coords[0].lat,
                "lng": coords[0].lng,
                "timestamp_offset": 0.0,
                "bearing": (
                    RouteInterpolator.bearing(
                        coords[0].lat, coords[0].lng,
                        coords[1].lat, coords[1].lng,
                    )
                    if len(coords) > 1
                    else 0.0
                ),
                "seg_idx": 0,
            }
        )

        step_dist = speed_mps * interval_sec  # meters per tick
        if step_dist <= 0 or speed_mps <= 0:
            return results

        # Walk the polyline by cumulative distance from the start. For each
        # segment we know its [start_cum, end_cum] range; any emit target
        # `next_emit_at` that falls inside that range gets interpolated at
        # the corresponding fractional offset within the segment.
        cum_at_seg_start = 0.0
        next_emit_at = step_dist
        last_seg_idx = 0
        last_bearing = results[0]["bearing"]

        for seg_idx in range(len(coords) - 1):
            a = coords[seg_idx]
            b = coords[seg_idx + 1]
            seg_dist = RouteInterpolator.haversine(a.lat, a.lng, b.lat, b.lng)
            if seg_dist <= 0:
                continue
            seg_bearing = RouteInterpolator.bearing(a.lat, a.lng, b.lat, b.lng)
            seg_end_cum = cum_at_seg_start + seg_dist

            while next_emit_at <= seg_end_cum:
                offset_in_seg = next_emit_at - cum_at_seg_start
                frac = offset_in_seg / seg_dist
                lat = a.lat + frac * (b.lat - a.lat)
                lng = a.lng + frac * (b.lng - a.lng)
                results.append(
                    {
                        "lat": lat,
                        "lng": lng,
                        "timestamp_offset": next_emit_at / speed_mps,
                        "bearing": seg_bearing,
                        "seg_idx": seg_idx,
                    }
                )
                next_emit_at += step_dist

            cum_at_seg_start = seg_end_cum
            last_seg_idx = seg_idx
            last_bearing = seg_bearing

        # Always include the final waypoint (its timestamp is the total
        # polyline length divided by speed, regardless of where the last
        # tick happened to land).
        total_distance = cum_at_seg_start
        last = coords[-1]
        prev = results[-1]
        if prev["lat"] != last.lat or prev["lng"] != last.lng:
            results.append(
                {
                    "lat": last.lat,
                    "lng": last.lng,
                    "timestamp_offset": total_distance / speed_mps,
                    "bearing": last_bearing,
                    "seg_idx": last_seg_idx,
                }
            )

        return results

    @staticmethod
    def interpolate_with_timing(
        coords: list["Coordinate"],
        offsets: list[float] | None,
        speed_mps: float,
        interval_sec: float = 1.0,
    ) -> list[dict]:
        """Timing-aware dense interpolation.

        When *offsets* (per-vertex seconds-from-start, same length as
        *coords*, monotonically non-decreasing, non-zero total span) is valid,
        emit one point every *interval_sec* of ORIGINAL time, walking the
        polyline by the fraction of elapsed original time within each segment
        so a recorded trail replays at its original cadence. Otherwise fall
        back to the constant-speed interpolate() (byte-identical output)."""
        if not coords:
            return []
        # Validate the timing track; any defect → constant-speed fallback.
        valid = (
            offsets is not None
            and len(offsets) == len(coords)
            and all(offsets[i] <= offsets[i + 1] for i in range(len(offsets) - 1))
            and len(offsets) >= 2
            and offsets[-1] > offsets[0]
        )
        if not valid:
            return RouteInterpolator.interpolate(coords, speed_mps, interval_sec)

        if offsets is None:  # narrowed by `valid`; defensive guard, never taken in practice
            return RouteInterpolator.interpolate(coords, speed_mps, interval_sec)
        base = offsets[0]
        rel = [o - base for o in offsets]  # 0-based original timeline
        total_time = rel[-1]

        # Seed the first point.
        results: list[dict] = [
            {
                "lat": coords[0].lat,
                "lng": coords[0].lng,
                "timestamp_offset": 0.0,
                "bearing": (
                    RouteInterpolator.bearing(
                        coords[0].lat, coords[0].lng,
                        coords[1].lat, coords[1].lng,
                    )
                    if len(coords) > 1
                    else 0.0
                ),
                "seg_idx": 0,
            }
        ]

        if interval_sec <= 0:
            # Degenerate cadence — just return seed + final vertex.
            last = coords[-1]
            results.append(
                {
                    "lat": last.lat,
                    "lng": last.lng,
                    "timestamp_offset": total_time,
                    "bearing": results[0]["bearing"],
                    "seg_idx": max(len(coords) - 2, 0),
                }
            )
            return results

        # Walk the ORIGINAL time axis. For each emit time t, find the segment
        # whose [rel[i], rel[i+1]] range contains t and interpolate position
        # by the time-fraction within that segment.
        seg = 0
        t = interval_sec
        while t < total_time:
            # Advance seg so rel[seg] <= t <= rel[seg+1].
            while seg < len(rel) - 2 and t > rel[seg + 1]:
                seg += 1
            seg_dt = rel[seg + 1] - rel[seg]
            a = coords[seg]
            b = coords[seg + 1]
            if seg_dt <= 0:
                frac = 0.0
            else:
                frac = (t - rel[seg]) / seg_dt
            lat = a.lat + frac * (b.lat - a.lat)
            lng = a.lng + frac * (b.lng - a.lng)
            results.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "timestamp_offset": t,
                    "bearing": RouteInterpolator.bearing(a.lat, a.lng, b.lat, b.lng),
                    "seg_idx": seg,
                }
            )
            t += interval_sec

        # Always include the final vertex at the total original span.
        # Float-accumulation guard: if the last loop tick landed within epsilon
        # of total_time (e.g. 0.1*120 = 11.999...998 instead of 12.0), its
        # coords already equal the final vertex.  In that case, canonicalize
        # its timestamp_offset to total_time rather than appending a near-duplicate.
        _EPS = 1e-9
        last = coords[-1]
        prev = results[-1]
        _last_offset_close = abs(prev["timestamp_offset"] - total_time) <= _EPS
        if _last_offset_close and prev["lat"] == last.lat and prev["lng"] == last.lng:
            # Snap the float-drifted offset to the canonical end time.
            results[-1]["timestamp_offset"] = total_time
        else:
            last_seg = max(len(coords) - 2, 0)
            a = coords[last_seg]
            b = coords[last_seg + 1] if len(coords) > 1 else coords[last_seg]
            results.append(
                {
                    "lat": last.lat,
                    "lng": last.lng,
                    "timestamp_offset": total_time,
                    "bearing": RouteInterpolator.bearing(a.lat, a.lng, b.lat, b.lng) if len(coords) > 1 else 0.0,
                    "seg_idx": last_seg,
                }
            )
        return results

    # ------------------------------------------------------------------
    # Jitter & movement helpers
    # ------------------------------------------------------------------

    @staticmethod
    def add_jitter(lat: float, lng: float, jitter_meters: float) -> tuple[float, float]:
        """Add random GPS drift within *jitter_meters* of the given point."""
        if jitter_meters <= 0:
            return lat, lng

        angle = random.uniform(0, 2 * math.pi)
        dist = random.uniform(0, jitter_meters)

        dlat = (dist * math.cos(angle)) / _R
        dlng = (dist * math.sin(angle)) / (_R * math.cos(math.radians(lat)))

        return lat + math.degrees(dlat), lng + math.degrees(dlng)

    @staticmethod
    def move_point(
        lat: float,
        lng: float,
        bearing_deg: float,
        distance_m: float,
    ) -> tuple[float, float]:
        """Move a point by *distance_m* along *bearing_deg*.

        Used for joystick-style movement.
        """
        brng = math.radians(bearing_deg)
        rlat = math.radians(lat)
        rlng = math.radians(lng)
        d_over_r = distance_m / _R

        new_lat = math.asin(
            math.sin(rlat) * math.cos(d_over_r)
            + math.cos(rlat) * math.sin(d_over_r) * math.cos(brng)
        )
        new_lng = rlng + math.atan2(
            math.sin(brng) * math.sin(d_over_r) * math.cos(rlat),
            math.cos(d_over_r) - math.sin(rlat) * math.sin(new_lat),
        )

        return math.degrees(new_lat), math.degrees(new_lng)

    @staticmethod
    def random_point_in_radius(
        center_lat: float,
        center_lng: float,
        radius_m: float,
        rng: random.Random | None = None,
    ) -> tuple[float, float]:
        """Generate a uniformly random point within *radius_m* of the centre.

        Uses the square-root trick so points are evenly distributed across the
        circle's area rather than clustering near the centre. When *rng* is
        supplied (a seeded ``random.Random`` instance), two callers that share
        the seed generate the exact same sequence; this enables dual-device
        group mode to keep both phones on the same random walk path.
        """
        r = rng if rng is not None else random
        angle = r.uniform(0, 2 * math.pi)
        dist = radius_m * math.sqrt(r.random())

        return RouteInterpolator.move_point(center_lat, center_lng, math.degrees(angle), dist)
