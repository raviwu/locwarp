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


def _fold(rows: list[dict], cap: int, keep_visits: bool) -> list[dict]:
    """Collapse rows within DEDUPE_DIST_M of each other, newest first.

    Sorts with a deterministic secondary key (lat, lng) rather than plain
    sort_desc: sort_desc's stable sort alone preserves the CALLER's input
    order on an exact ts tie, so merge_recent(a, b) and merge_recent(b, a)
    could fold onto different survivors (and thus different non-empty
    `name` winners) purely because of which side was concatenated first.
    Breaking the tie on the rows' own coordinates makes the fold — and
    therefore merge_recent — order-independent, i.e. genuinely commutative.
    """
    ordered = sorted(rows, key=lambda e: (-e.get("ts", 0), e["lat"], e["lng"]))
    kept: list[dict] = []
    for row in ordered:
        match = None
        for k in kept:
            if haversine_m(k["lat"], k["lng"], row["lat"], row["lng"]) < DEDUPE_DIST_M:
                match = k
                break
        if match is None:
            entry = dict(row)
            if not keep_visits:
                entry.pop("visit_count", None)
            kept.append(entry)
            continue
        match["ts"] = max(match.get("ts", 0), row.get("ts", 0))
        if not match.get("name") and row.get("name"):
            match["name"] = row["name"]
        if keep_visits:
            match["visit_count"] = max(
                int(match.get("visit_count", 1)), int(row.get("visit_count", 1))
            )
    return sort_desc(kept)[:cap]


def merge_recent(a: list[dict], b: list[dict]) -> list[dict]:
    """Union two recent-store snapshots. Commutative and idempotent.

    Rows are matched WITHIN a class (a manual entry never merges into a route
    stop) and by proximity, mirroring the live store's dedupe rule. A matched
    pair keeps the newest ts, the non-empty name, and — for route stops only —
    the highest visit_count, because a restored backup may hold visits the live
    store lost. Each class is capped exactly as the live store caps it, so the
    merged output already satisfies the store's invariants.

    ``visit_count`` uses max(), not a sum: the two snapshots overlap in time, so
    adding them would double-count every visit already present in both.
    """
    manual_a, route_a = split_by_class(a)
    manual_b, route_b = split_by_class(b)
    manual = _fold(manual_a + manual_b, MAX_MANUAL_ENTRIES, keep_visits=False)
    routes = _fold(route_a + route_b, MAX_ROUTE_STOP_ENTRIES, keep_visits=True)
    return sort_desc(manual + routes)
