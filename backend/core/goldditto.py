"""Pull-Gold-Ditto handler.

Runs a three-step cycle (teleport → asyncio.sleep → restore) atomically.
The whole cycle is serialized by an internal asyncio.Lock so two concurrent
calls cannot interleave and cause undefined device state.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Literal

from models.schemas import Coordinate

logger = logging.getLogger(__name__)


class GoldDittoLockedError(Exception):
    """Raised when a cycle is requested while another is already running."""


def _great_circle_m(p1: Coordinate, p2: tuple[float, float]) -> float:
    """Approximate great-circle distance in meters. Used only to compare two
    distances, so trig precision is not load-bearing."""
    lat1, lng1 = math.radians(p1.lat), math.radians(p1.lng)
    lat2, lng2 = math.radians(p2[0]), math.radians(p2[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


class GoldDittoHandler:
    def __init__(self, engine):
        self.engine = engine
        self._lock = asyncio.Lock()

    def _pick(
        self,
        target: Literal["A", "B", "auto"],
        a: tuple[float, float],
        b: tuple[float, float],
    ) -> tuple[str, float, float]:
        """Return (label, lat, lng) for the chosen teleport target."""
        if target == "A":
            return ("A", a[0], a[1])
        if target == "B":
            return ("B", b[0], b[1])
        # auto: closer to A → return B; closer to B → return A; None → A
        cur = self.engine.current_position
        if cur is None:
            return ("A", a[0], a[1])
        dist_a = _great_circle_m(cur, a)
        dist_b = _great_circle_m(cur, b)
        if dist_a < dist_b:
            return ("B", b[0], b[1])
        return ("A", a[0], a[1])

    async def cycle(
        self,
        *,
        target: Literal["A", "B", "auto"],
        lat_a: float,
        lng_a: float,
        lat_b: float,
        lng_b: float,
        wait_seconds: float,
    ) -> dict:
        if self._lock.locked():
            raise GoldDittoLockedError("cycle already in progress")

        async with self._lock:
            label, lat, lng = self._pick(target, (lat_a, lng_a), (lat_b, lng_b))
            t0 = time.monotonic()

            await self.engine.teleport(lat, lng)
            await self.engine._emit("goldditto_cycle", {
                "phase": "teleported",
                "target": label,
                "lat": lat,
                "lng": lng,
            })
            logger.info("Gold Ditto: teleported to %s (%.6f, %.6f); waiting %.2fs",
                        label, lat, lng, wait_seconds)

            await asyncio.sleep(wait_seconds)

            await self.engine.restore()
            await self.engine._emit("goldditto_cycle", {
                "phase": "restored",
                "target": label,
            })
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.info("Gold Ditto: cycle complete (%dms)", duration_ms)

            return {
                "target_used": label,
                "lat": lat,
                "lng": lng,
                "duration_ms": duration_ms,
            }
