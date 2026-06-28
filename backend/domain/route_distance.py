"""Pure cached-distance helpers for saved routes (clean-arch domain ring).

Stdlib (math/hashlib) + domain/movement + models only — guarded by the
no-domain-imports-outer import-linter contract. Used by the route create /
replace / import handlers (straight inline), the deferred road orchestrator
(fingerprint + decimation), and the startup sweep.
"""

from __future__ import annotations

import hashlib

from domain.movement import RouteInterpolator
from models.schemas import Coordinate

# 1e-6 deg ~= 0.11 m at the equator — finer than GPS noise, so a real path
# edit flips the fingerprint while float round-trip noise does not.
_FP_PRECISION = 6


def straight_line_distance_m(waypoints: list[Coordinate]) -> float:
    """Great-circle (haversine) meters summed over consecutive waypoints.
    0 or 1 waypoint -> 0.0. Reuses RouteInterpolator.haversine so there is a
    single meters-haversine source of truth."""
    if len(waypoints) < 2:
        return 0.0
    total = 0.0
    for a, b in zip(waypoints, waypoints[1:]):
        total += RouteInterpolator.haversine(a.lat, a.lng, b.lat, b.lng)
    return total


def route_distance_fingerprint(waypoints: list[Coordinate], profile: str) -> str:
    """Stable sha1 of the rounded waypoint coords + profile. Any waypoint move,
    reorder, or profile change flips the hash. The staleness signal: a cached
    road_distance_m is valid iff its stored fingerprint == this hash."""
    parts = [
        f"{round(c.lat, _FP_PRECISION)},{round(c.lng, _FP_PRECISION)}"
        for c in waypoints
    ]
    payload = "|".join(parts) + f"|profile={profile}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def decimate_waypoints(waypoints: list, max_n: int) -> list:
    """Down-sample a long waypoint list to at most max_n points for the road
    request, always keeping the first and last. Used so a 50+-point GPX does
    not fan out into dozens of routed coordinates. Returns the input unchanged
    when max_n < 2 or the route is already short enough (road distance for a
    decimated route is therefore approximate — an accepted tradeoff)."""
    n = len(waypoints)
    if max_n < 2 or n <= max_n:
        return list(waypoints)
    idxs = [round(i * (n - 1) / (max_n - 1)) for i in range(max_n)]
    seen: set[int] = set()
    out = []
    for i in idxs:
        if i not in seen:
            seen.add(i)
            out.append(waypoints[i])
    return out
