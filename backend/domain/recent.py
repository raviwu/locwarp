"""Pure policy for the recent-places store (domain ring).

stdlib only. Holds the constants, the distance rule, entry validation, and the
class split that both the live store (services/recent.py) and the backup
restore path depend on, so neither can drift from the other.

Two classes of entry live in one file:

* **manual** — the five user-initiated fly-to kinds. Written by the frontend
  through ``POST /api/recent``.
* **route_stop** — arrivals recorded by the backend while a simulated route
  runs. Written only by the in-process recorder.

They are budgeted and deduped separately; see services/recent.py for why.
"""
from __future__ import annotations

import math

ROUTE_KIND = "route_stop"

MANUAL_KINDS = frozenset(
    {"teleport", "navigate", "search", "coord_teleport", "coord_navigate"}
)
VALID_KINDS = MANUAL_KINDS | {ROUTE_KIND}

DEDUPE_DIST_M = 10.0  # same spot if within 10m
MAX_MANUAL_ENTRIES = 20
MAX_ROUTE_STOP_ENTRIES = 30


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def is_valid_entry(entry: dict) -> bool:
    try:
        lat = float(entry.get("lat"))
        lng = float(entry.get("lng"))
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return False
        if entry.get("kind") not in VALID_KINDS:
            return False
        return True
    except (TypeError, ValueError):
        return False


def sort_desc(entries: list[dict]) -> list[dict]:
    """Newest first. Python's sort is stable, so an exact ts tie preserves the
    caller's input order (manual before route stops in services.recent.list)."""
    return sorted(entries, key=lambda e: e.get("ts", 0), reverse=True)


def split_by_class(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """(manual, route_stops) — invalid entries dropped."""
    manual: list[dict] = []
    routes: list[dict] = []
    for e in entries:
        if not is_valid_entry(e):
            continue
        (routes if e.get("kind") == ROUTE_KIND else manual).append(e)
    return manual, routes
