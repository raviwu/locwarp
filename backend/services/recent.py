"""Recently visited places: the map's Recent popover, persisted to
RECENT_PLACES_FILE so the list survives LocWarp restarts.

Manual entries (teleport / navigate / search / coord_*) and route stops share
one file but are held in TWO internal lists, because they must not interfere:

* **Budgets.** A single list capped by a positional ``[:N]`` slice lets one
  class evict the other — thirty freshly-written route stops plus one manual
  teleport would truncate to twenty and persist the loss.
* **Dedupe.** ``push`` compares against the newest MANUAL entry, never the head
  of the merged list. Otherwise a manual teleport landing within 10 m of a
  leading route stop would be folded into that row (silently keeping its kind),
  and the frontend's push-twice reverse-geocode name backfill would write the
  resolved name onto the route row instead.

``list()`` merges them ts-descending for the read path; the on-disk format stays
a flat ts-descending array, so an older LocWarp build still loads the file (it
drops the unknown ``route_stop`` kind in its own validator).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from config import RECENT_PLACES_FILE
from domain.recent import (
    DEDUPE_DIST_M,
    MANUAL_KINDS,
    MAX_MANUAL_ENTRIES,
    MAX_ROUTE_STOP_ENTRIES,
    ROUTE_KIND,
    haversine_m,
    sort_desc,
    split_by_class,
)
from services.json_safe import safe_load_json, safe_write_json

logger = logging.getLogger(__name__)


class RecentPlacesManager:
    """Two in-memory lists, mirrored to one JSON file on every write."""

    def __init__(self) -> None:
        self._manual: list[dict] = []
        self._route_stops: list[dict] = []
        self._load()

    # ── persistence ──────────────────────────────────────────────────────
    def _load(self) -> None:
        data = safe_load_json(Path(RECENT_PLACES_FILE))
        if not isinstance(data, list):
            return
        manual, routes = split_by_class(data)
        self._manual = sort_desc(manual)[:MAX_MANUAL_ENTRIES]
        self._route_stops = sort_desc(routes)[:MAX_ROUTE_STOP_ENTRIES]
        logger.info(
            "Loaded %d recent places (%d manual, %d route stops)",
            len(self._manual) + len(self._route_stops),
            len(self._manual),
            len(self._route_stops),
        )

    def _save(self) -> None:
        safe_write_json(Path(RECENT_PLACES_FILE), self.list())

    # ── read ─────────────────────────────────────────────────────────────
    def list(self) -> list[dict]:
        """Both classes merged, newest first."""
        return sort_desc(self._manual + self._route_stops)

    def snapshot_export(self) -> list[dict]:
        """Consistent read for the rotating backup. No lock is needed: every
        writer (the three HTTP handlers and main.py's stop_reached recorder)
        runs on the FastAPI event loop, and list() builds a fresh list, so the
        backup tick can never capture a torn write."""
        return self.list()

    # ── write ────────────────────────────────────────────────────────────
    def push(self, lat: float, lng: float, kind: str, name: str | None = None) -> dict:
        """Add a manual entry to the front of the manual list.

        Dedupes against the newest MANUAL entry. With no route stops present
        that entry IS the head of the merged list, so this is byte-for-byte the
        pre-route-stop behavior.
        """
        if kind not in MANUAL_KINDS:
            raise ValueError(f"push() accepts manual kinds only, got {kind!r}")
        now = int(time.time())
        new_entry = {
            "lat": float(lat),
            "lng": float(lng),
            "kind": kind,
            "name": (name or "").strip(),
            "ts": now,
        }
        if self._manual:
            top = self._manual[0]
            if haversine_m(top["lat"], top["lng"], lat, lng) < DEDUPE_DIST_M:
                top["ts"] = now
                if new_entry["name"] and not top.get("name"):
                    top["name"] = new_entry["name"]
                # Intentionally preserve the original kind. Re-flying a
                # search result via the map's Recent popover calls
                # handleTeleport under the hood, and if we overwrote
                # kind we'd silently demote "地址" rows to "瞬移" on
                # every re-fly.
                self._save()
                return top
        self._manual.insert(0, new_entry)
        del self._manual[MAX_MANUAL_ENTRIES:]
        self._save()
        return new_entry

    def push_route_stop(self, lat: float, lng: float, name: str | None = None) -> dict:
        """Record an arrival at a simulated route's stop.

        Dedupes against EVERY route stop, not just the newest, because a loop
        returns to earlier stops on every lap. A hit refreshes the timestamp,
        bumps visit_count and floats the row to the head of its own class.
        Manual entries are never examined.
        """
        now = int(time.time())
        nearest, best = None, DEDUPE_DIST_M
        for e in self._route_stops:
            d = haversine_m(e["lat"], e["lng"], lat, lng)
            if d < best:
                nearest, best = e, d
        if nearest is not None:
            nearest["ts"] = now
            nearest["visit_count"] = int(nearest.get("visit_count", 1)) + 1
            if name and not nearest.get("name"):
                nearest["name"] = name.strip()
            self._route_stops.remove(nearest)
            self._route_stops.insert(0, nearest)
            self._save()
            return nearest
        entry = {
            "lat": float(lat),
            "lng": float(lng),
            "kind": ROUTE_KIND,
            "name": (name or "").strip(),
            "ts": now,
            "visit_count": 1,
        }
        self._route_stops.insert(0, entry)
        del self._route_stops[MAX_ROUTE_STOP_ENTRIES:]
        self._save()
        return entry

    def clear(self) -> None:
        self._manual = []
        self._route_stops = []
        self._save()


_singleton: RecentPlacesManager | None = None


def get_manager() -> RecentPlacesManager:
    global _singleton
    if _singleton is None:
        _singleton = RecentPlacesManager()
    return _singleton


def should_record_stop(
    event_type: str, data: dict, udid: str, primary_udid: str | None
) -> bool:
    """True when an engine event is a route arrival worth recording.

    Skips non-arrival events; the auto-injected origin waypoint (which the user
    never chose — it is wherever the device stood when Start was pressed); every
    engine that is not the primary device's (a fan-out run emits one
    ``stop_reached`` per device for the same physical stop); and malformed
    payloads.
    """
    return (
        event_type == "stop_reached"
        and isinstance(data, dict)
        and not data.get("origin")
        and udid == primary_udid
        and "lat" in data
        and "lng" in data
    )


def record_route_stop(lat: float, lng: float) -> None:
    """The backend's only write path for route arrivals; called from main.py's
    engine event_callback. Never raises — SimulationEngine._emit already
    swallows callback exceptions, but letting one escape here would log a full
    traceback on every stop of a broken run."""
    try:
        get_manager().push_route_stop(lat, lng)
    except Exception:
        logger.exception("failed to record route stop (%s, %s)", lat, lng)
