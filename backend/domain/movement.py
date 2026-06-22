"""Pure movement math for the simulation engine (clean-arch Phase 3).

This is the pure inner-ring home for referentially-transparent movement
helpers extracted from core/simulation_engine.py. It imports stdlib + pydantic
(models.schemas) ONLY and is guarded by the `no-domain-imports-outer`
import-linter contract.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone


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
