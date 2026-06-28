"""Deferred road-distance orchestrator (services ring).

Computes the 沿路 (road-following) total distance for one saved route as a
single multi-waypoint request, OFF the save critical path, and ALWAYS writes a
terminal state (road_distance_status 'ok' or 'unavailable') + broadcasts — so
the UI badge never sticks on a pending value. Clean-arch: services may not
import api, so the WS publisher is INJECTED (its .publish() is the api
WsEventPublisher). Spawned by api/route.py after an inline save, and by the
main.py startup/watcher sweep.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

import config
from domain.route_distance import decimate_waypoints, route_distance_fingerprint

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _road_meters_once(route_service, waypoints, profile) -> float | None:
    """One road attempt. Returns meters, or None on ANY failure (timeout /
    engine offline / straight-line fallback / malformed response). Never
    raises (except on cancellation, which is BaseException)."""
    coords = [(c.lat, c.lng) for c in waypoints]
    try:
        result = await asyncio.wait_for(
            route_service.get_multi_route(coords, profile),
            timeout=config.ROAD_COMPUTE_TIMEOUT_S,
        )
    except Exception:
        logger.warning("road-distance attempt failed", exc_info=True)
        return None
    if not result or result.get("fallback"):
        return None
    dist = result.get("distance")
    return float(dist) if dist is not None else None


async def _compute_with_retry(route_service, waypoints, profile, sleep) -> float | None:
    """Bounded retry with backoff. Total attempts = len(ROAD_RETRY_BACKOFF_S)+1.
    Returns meters on the first success, or None once the budget is exhausted."""
    backoff = config.ROAD_RETRY_BACKOFF_S
    for attempt in range(len(backoff) + 1):
        meters = await _road_meters_once(route_service, waypoints, profile)
        if meters is not None:
            return meters
        if attempt < len(backoff):
            await sleep(backoff[attempt])
    return None


async def compute_road_distance(
    route_id: str,
    *,
    route_manager,
    route_service,
    publisher,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Compute one route's road distance and ALWAYS write a terminal state.

    Never leaves the route 'pending': success -> ('ok', meters); after the
    bounded retry budget -> ('unavailable', None). Either way the route is
    restamped (CRDT-safe updated_at), saved, and a routes_changed broadcast
    fires — UNLESS the route was deleted, edited under us (fingerprint moved →
    a newer compute owns the write), or the result is identical to what is
    already stored (idempotent re-sweep no-op)."""
    route = route_manager._find_route(route_id)
    if route is None:
        return
    captured_fp = route_distance_fingerprint(route.waypoints, route.profile)
    profile = route.profile
    decimated = decimate_waypoints(route.waypoints, config.ROAD_MAX_WAYPOINTS)

    road_m = await _compute_with_retry(route_service, decimated, profile, sleep)

    current = route_manager._find_route(route_id)
    if current is None:
        return  # deleted under us
    if route_distance_fingerprint(current.waypoints, current.profile) != captured_fp:
        logger.info("road-distance for route %s discarded (path changed under us)", route_id)
        return
    new_status = "ok" if road_m is not None else "unavailable"
    if (
        current.road_distance_status == new_status
        and current.road_distance_m == road_m
        and current.dist_fingerprint == captured_fp
    ):
        return  # idempotent no-op — skip write + broadcast
    current.road_distance_m = road_m
    current.road_distance_status = new_status
    current.dist_fingerprint = captured_fp
    current.updated_at = _now_iso()  # CRDT-merge-safe stamp
    route_manager._save()
    await publisher.publish(("routes_changed", {"reason": "distance"}))
