# Route Stops → Recent History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record the stops a simulated route passes through into LocWarp's Recent (history) popover, so any individual stop can be re-flown with one click.

**Architecture:** The simulation engine already emits `stop_reached` with coordinates from `multi_stop`; `route_loop` gains the same emit on both its routed and jump paths. `main.py`'s engine `event_callback` — the composition root, which already carries one non-WebSocket side effect — writes each arrival into the recent store *before* broadcasting, so the renderer's refetch cannot race the write. `core/` never learns the store exists. The store itself splits into two internal lists (manual entries and route stops) merged only on read, so the two classes can neither dedupe against nor evict one another.

**Tech Stack:** Python 3.13 / FastAPI / pydantic (backend); React + TypeScript / Vitest / Testing Library (frontend); pytest + pytest-asyncio; import-linter; dependency-cruiser.

**Spec:** `docs/superpowers/specs/2026-07-10-route-stops-to-history-design.md`

## Global Constraints

- **Baseline to hold green:** backend `1118` pytest tests collected. Re-pin before starting with `cd backend && .venv/bin/python -m pytest --collect-only -q | tail -2`.
- **The full CI gate is `make verify`:** `cd backend && .venv/bin/python -m pytest -q --cov --cov-report=term-missing && .venv/bin/lint-imports` then `cd frontend && npx tsc --noEmit && npx vitest run --coverage && npx depcruise src --config .dependency-cruiser.cjs && npx playwright test`.
- **Import-linter must stay `7 kept, 0 broken`.** `domain/` imports stdlib + pydantic only. `services/` may import `domain/`. `core/` must never import `services/` (doctrine rule; not CI-enforced — do not rely on the gate to catch it). `main.py` is the composition root and may import anything.
- **Every commit leaves the full suite green.** Write the test and the implementation in the same commit; never commit a red test. (This supersedes the spec's C1/C2 red-then-green split, which would have left one commit red.)
- **No new dependencies.**
- **No new HTTP endpoints and no removal or renaming of any existing WebSocket event or payload key.** Adding the `origin` key to `stop_reached` is additive and permitted.
- **Backend pytest is always run as** `cd backend && .venv/bin/python -m pytest <args>`.
- **Frontend vitest is always run as** `cd frontend && npx vitest run <path>`.
- **`route_stop` rows are written only by the backend recorder.** `POST /api/recent` must never accept that kind.
- **`waypoints[0]` is never recorded** on any movement path.
- Git identity is auto-set by `~/.gitconfig` includeIf. Never pass `-c user.email=...`.

---

## File Structure

**Created**

| Path | Responsibility |
|---|---|
| `backend/domain/recent.py` | Pure policy for the recent store: constants, haversine, entry validation, class split, ts-sort, and (Task 9) `merge_recent`. stdlib only. |
| `backend/tests/test_recent_store.py` | Unit tests for the two-list store and the recorder gate. |
| `backend/tests/test_recent_api.py` | HTTP-contract tests for `/api/recent`. |
| `backend/tests/test_recent_recorder_wiring.py` | Integration test: a primary engine's `stop_reached` reaches the store. |
| `backend/tests/test_recent_merge.py` | Unit tests for `merge_recent`. |

**Modified**

| Path | Change |
|---|---|
| `backend/services/recent.py` | Restructured onto two internal lists; gains `push_route_stop`, `snapshot_export`, `record_route_stop`, `should_record_stop`. |
| `backend/core/multi_stop.py` | `stop_reached` gains the additive `origin` key on both paths. |
| `backend/core/route_loop.py` | New `stop_reached` emits on the routed and jump paths. |
| `backend/main.py` | `event_callback` records route stops; `_backup_provider` returns a 3-tuple. |
| `backend/domain/backup.py` | `recent` threaded through the fingerprint and the snapshot payload. |
| `backend/services/backup_service.py` | Provider returns 3 stores; `BackupTickResult` gains `recent_count`. |
| `backend/merge_backup.py` | `restore_combined_snapshot` restores the `recent` sub-store. |
| `backend/tests/test_multi_stop_cov.py` | `origin` assertions. |
| `backend/tests/test_route_loop_cov.py` | `stop_reached` characterization tests. |
| `backend/tests/test_backup_service.py` | 3-tuple provider; `recent` key in the payload. |
| `frontend/src/services/api.ts` | `RecentKind` gains `route_stop`; `RecentEntry` gains `visit_count?`. |
| `frontend/src/components/RecentPlacesPopover.tsx` | Widened kind union; route badge; `×N` chip. |
| `frontend/src/hooks/useRecentPlaces.ts` | Optional `ws` param; coalesced refetch on `stop_reached`. |
| `frontend/src/hooks/useSimActions.ts` | `handleTeleport` / `handleNavigate` take a `record` option and return success. |
| `frontend/src/App.tsx` | Pass `router` to `useRecentPlaces`; `onRecentReFly` suppresses the duplicate row and toasts. |
| `frontend/src/adapters/ws/eventWiring.test.tsx` | `stop_reached` promoted to a required, subscribed type. |
| `frontend/src/i18n/strings.ts` | Three new keys. |

---

## Task 1: The two-list recent store

The current store keeps one list and slices it `[:MAX_ENTRIES]` by position in two places (`services/recent.py:53` and `:105-106`), and dedupes against `entries[0]` without checking `kind` (`:90-103`). Both break the moment a second class of entry shares the list: a manual push would truncate route stops away, and a manual teleport landing within 10 m of a leading route stop would be swallowed into it. Two internal lists remove both failure modes structurally.

**Files:**
- Create: `backend/domain/recent.py`
- Create: `backend/tests/test_recent_store.py`
- Modify: `backend/services/recent.py` (full rewrite of the module body)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `domain.recent.ROUTE_KIND: str = "route_stop"`, `MANUAL_KINDS: frozenset[str]`, `VALID_KINDS: frozenset[str]`, `DEDUPE_DIST_M: float = 10.0`, `MAX_MANUAL_ENTRIES: int = 20`, `MAX_ROUTE_STOP_ENTRIES: int = 30`
  - `domain.recent.haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float`
  - `domain.recent.is_valid_entry(entry: dict) -> bool`
  - `domain.recent.sort_desc(entries: list[dict]) -> list[dict]`
  - `domain.recent.split_by_class(entries: list[dict]) -> tuple[list[dict], list[dict]]` — returns `(manual, route_stops)`
  - `services.recent.RecentPlacesManager.push(lat: float, lng: float, kind: str, name: str | None = None) -> dict` (manual kinds only; raises `ValueError` otherwise)
  - `services.recent.RecentPlacesManager.push_route_stop(lat: float, lng: float, name: str | None = None) -> dict`
  - `services.recent.RecentPlacesManager.list() -> list[dict]`
  - `services.recent.RecentPlacesManager.clear() -> None`
  - `services.recent.RecentPlacesManager.snapshot_export() -> list[dict]`
  - `services.recent.get_manager() -> RecentPlacesManager`
  - `services.recent.record_route_stop(lat: float, lng: float) -> None` (never raises)
  - `services.recent.should_record_stop(event_type: str, data: dict, udid: str, primary_udid: str | None) -> bool`

- [ ] **Step 1: Confirm the baseline and that nothing outside `services/recent.py` uses the symbols being removed**

Run:
```bash
cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest --collect-only -q | tail -2
grep -rn "MAX_ENTRIES" --exclude-dir=.venv --exclude-dir=__pycache__ .
```
Expected: `1118 tests collected`; `MAX_ENTRIES` appears **only** inside `services/recent.py`. If it appears anywhere else, stop and re-scope this task.

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_recent_store.py`:

```python
"""RecentPlacesManager: manual entries and route stops share one file but not
one budget. These tests pin the invariants the old single-list implementation
could not hold — a manual push truncating route stops away, and a manual
teleport deduping into a leading route stop (which also broke the frontend's
reverse-geocode name backfill)."""
from __future__ import annotations

import pytest


class _FakeTime:
    """Stand-in for the `time` module inside services.recent."""

    def __init__(self, values):
        self._it = iter(values)

    def time(self):
        return next(self._it)


@pytest.fixture
def mgr():
    import services.recent as recent
    # The autouse conftest guard redirected RECENT_PLACES_FILE and reset the
    # module singleton, so this builds a manager bound to the per-test tmp file.
    assert recent._singleton is None
    return recent.get_manager()


def test_manual_push_does_not_dedupe_into_a_leading_route_stop(mgr):
    mgr.push_route_stop(25.0, 121.0)
    mgr.push(25.0, 121.0, "teleport")
    entries = mgr.list()
    kinds = [e["kind"] for e in entries]
    assert kinds.count("teleport") == 1
    assert kinds.count("route_stop") == 1
    route = next(e for e in entries if e["kind"] == "route_stop")
    assert route["visit_count"] == 1


def test_manual_name_backfill_survives_a_leading_route_stop(mgr):
    # Mirrors useRecentPlaces' push-twice flow: unnamed push, then a second
    # push carrying the reverse-geocoded name. A route stop inserted between
    # them must not steal the backfill.
    mgr.push(35.0, 139.0, "teleport")
    mgr.push_route_stop(10.0, 20.0)
    mgr.push(35.0, 139.0, "teleport", "Shibuya")
    manual = [e for e in mgr.list() if e["kind"] == "teleport"]
    assert len(manual) == 1
    assert manual[0]["name"] == "Shibuya"
    route = next(e for e in mgr.list() if e["kind"] == "route_stop")
    assert route["name"] == ""


def test_route_stop_dedupes_globally_and_counts_visits(mgr):
    mgr.push_route_stop(25.0, 121.0)
    mgr.push_route_stop(25.1, 121.1)
    mgr.push_route_stop(25.0, 121.0)  # back to the first stop on the next lap
    routes = [e for e in mgr.list() if e["kind"] == "route_stop"]
    assert len(routes) == 2
    assert routes[0]["lat"] == 25.0
    assert routes[0]["visit_count"] == 2
    assert routes[1]["visit_count"] == 1


def test_route_stops_never_evict_manual_entries(mgr):
    for i in range(20):
        mgr.push(1.0 + i, 2.0 + i, "teleport")
    for i in range(40):  # more than MAX_ROUTE_STOP_ENTRIES
        mgr.push_route_stop(40.0 + i * 0.5, 100.0 + i * 0.5)
    kinds = [e["kind"] for e in mgr.list()]
    assert kinds.count("teleport") == 20
    assert kinds.count("route_stop") == 30


def test_manual_push_never_evicts_route_stops(mgr):
    """The old single-list [:MAX_ENTRIES] slice destroyed 11 route stops here."""
    for i in range(30):
        mgr.push_route_stop(40.0 + i * 0.5, 100.0 + i * 0.5)
    mgr.push(1.0, 2.0, "teleport")
    kinds = [e["kind"] for e in mgr.list()]
    assert kinds.count("route_stop") == 30
    assert kinds.count("teleport") == 1


def test_list_is_ts_descending(mgr, monkeypatch):
    import services.recent as recent
    monkeypatch.setattr(recent, "time", _FakeTime([100, 200, 300]))
    mgr.push(1.0, 2.0, "teleport")
    mgr.push_route_stop(40.0, 100.0)
    mgr.push(5.0, 6.0, "search")
    assert [e["ts"] for e in mgr.list()] == [300, 200, 100]


def test_manual_entries_carry_no_visit_count(mgr):
    entry = mgr.push(1.0, 2.0, "teleport")
    assert "visit_count" not in entry


def test_push_rejects_the_route_stop_kind(mgr):
    with pytest.raises(ValueError):
        mgr.push(1.0, 2.0, "route_stop")


def test_clear_empties_both_classes(mgr):
    mgr.push(1.0, 2.0, "teleport")
    mgr.push_route_stop(40.0, 100.0)
    mgr.clear()
    assert mgr.list() == []


def test_legacy_manual_only_file_loads_and_caps(monkeypatch):
    import services.recent as recent
    from pathlib import Path
    from services.json_safe import safe_write_json

    legacy = [
        {"lat": 1.0 + i, "lng": 2.0 + i, "kind": "teleport", "name": "", "ts": 9000 - i}
        for i in range(25)
    ]
    safe_write_json(Path(recent.RECENT_PLACES_FILE), legacy)
    monkeypatch.setattr(recent, "_singleton", None, raising=False)

    entries = recent.get_manager().list()
    assert len(entries) == 20
    assert all(e["kind"] == "teleport" for e in entries)
    assert "visit_count" not in entries[0]


def test_load_caps_each_class_independently(monkeypatch):
    import services.recent as recent
    from pathlib import Path
    from services.json_safe import safe_write_json

    rows = [
        {"lat": 1.0 + i, "lng": 2.0 + i, "kind": "teleport", "name": "", "ts": 9000 - i}
        for i in range(25)
    ] + [
        {"lat": 40.0 + i * 0.5, "lng": 100.0 + i * 0.5, "kind": "route_stop",
         "name": "", "ts": 8000 - i, "visit_count": 3}
        for i in range(40)
    ]
    safe_write_json(Path(recent.RECENT_PLACES_FILE), rows)
    monkeypatch.setattr(recent, "_singleton", None, raising=False)

    kinds = [e["kind"] for e in recent.get_manager().list()]
    assert kinds.count("teleport") == 20
    assert kinds.count("route_stop") == 30


def test_record_route_stop_never_raises(monkeypatch):
    import services.recent as recent

    class Boom:
        def push_route_stop(self, *a, **k):
            raise RuntimeError("disk on fire")

    monkeypatch.setattr(recent, "get_manager", lambda: Boom())
    recent.record_route_stop(1.0, 2.0)  # must not raise


@pytest.mark.parametrize(
    "event_type,data,udid,primary,expected",
    [
        ("stop_reached", {"lat": 1.0, "lng": 2.0, "origin": False}, "a", "a", True),
        ("stop_reached", {"lat": 1.0, "lng": 2.0}, "a", "a", True),
        ("stop_reached", {"lat": 1.0, "lng": 2.0, "origin": True}, "a", "a", False),
        ("stop_reached", {"lat": 1.0, "lng": 2.0, "origin": False}, "b", "a", False),
        ("stop_reached", {"lat": 1.0, "lng": 2.0, "origin": False}, "a", None, False),
        ("stop_reached", {"origin": False}, "a", "a", False),
        ("position_update", {"lat": 1.0, "lng": 2.0}, "a", "a", False),
    ],
)
def test_should_record_stop(event_type, data, udid, primary, expected):
    import services.recent as recent
    assert recent.should_record_stop(event_type, data, udid, primary) is expected
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_recent_store.py -q`
Expected: FAIL — `AttributeError: module 'services.recent' has no attribute 'should_record_stop'` and `AttributeError: 'RecentPlacesManager' object has no attribute 'push_route_stop'`.

- [ ] **Step 4: Create `backend/domain/recent.py`**

```python
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
```

- [ ] **Step 5: Rewrite `backend/services/recent.py`**

Replace the entire file with:

```python
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
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_recent_store.py tests/test_recent_isolation.py -q`
Expected: PASS, 15 passed.

- [ ] **Step 7: Run the full backend suite and the layering gate**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q && .venv/bin/lint-imports`
Expected: all pass; `Contracts: 7 kept, 0 broken.`

- [ ] **Step 8: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/domain/recent.py backend/services/recent.py backend/tests/test_recent_store.py
git commit -m "feat(recent): split the store into manual and route-stop budgets

Adds the route_stop kind, global coordinate dedupe with visit_count, and the
record_route_stop / should_record_stop recorder entry points. Manual entries and
route stops now live in separate internal lists so neither can evict the other,
and push() dedupes against the newest manual entry rather than the head of the
merged list — otherwise a route stop at the front would swallow a user's
teleport and steal the frontend's reverse-geocode name backfill."
```

---

## Task 2: Pin the `/api/recent` HTTP contract

No production change. These tests lock two invariants the rest of the design leans on: the frontend cannot forge a route stop, and `visit_count` reaches the renderer.

**Files:**
- Create: `backend/tests/test_recent_api.py`

**Interfaces:**
- Consumes: `services.recent.get_manager`, `RecentPlacesManager.push_route_stop` (Task 1).
- Produces: nothing.

- [ ] **Step 1: Write the tests**

Create `backend/tests/test_recent_api.py`:

```python
"""HTTP contract for /api/recent.

Two invariants the recorder design depends on:

1. `POST /api/recent` accepts only the five MANUAL kinds, so route stops can be
   written by the backend recorder and nothing else.
2. `GET /api/recent` has no `response_model`, so the optional `visit_count`
   field reaches the renderer untouched. If someone ever adds a response_model
   without listing `visit_count`, this test catches the silent strip.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    import main
    # Instantiated without a `with` block on purpose: that skips the lifespan,
    # so no device watchdogs / backup loop start for a pure routing test.
    return TestClient(main.app)


def test_post_rejects_the_route_stop_kind():
    r = _client().post("/api/recent", json={"lat": 1.0, "lng": 2.0, "kind": "route_stop"})
    assert r.status_code == 422


def test_post_accepts_a_manual_kind():
    r = _client().post("/api/recent", json={"lat": 1.0, "lng": 2.0, "kind": "teleport"})
    assert r.status_code == 200
    assert r.json()["kind"] == "teleport"


def test_get_passes_visit_count_through():
    import services.recent as recent
    recent.get_manager().push_route_stop(25.0, 121.0)
    recent.get_manager().push_route_stop(25.0, 121.0)  # same spot, next lap

    rows = _client().get("/api/recent").json()
    route_rows = [r for r in rows if r["kind"] == "route_stop"]
    assert len(route_rows) == 1
    assert route_rows[0]["visit_count"] == 2


def test_get_omits_visit_count_on_manual_rows():
    import services.recent as recent
    recent.get_manager().push(1.0, 2.0, "teleport")
    rows = _client().get("/api/recent").json()
    assert "visit_count" not in rows[0]


def test_delete_clears_both_classes():
    import services.recent as recent
    recent.get_manager().push(1.0, 2.0, "teleport")
    recent.get_manager().push_route_stop(25.0, 121.0)

    c = _client()
    assert c.delete("/api/recent").status_code == 200
    assert c.get("/api/recent").json() == []
```

- [ ] **Step 2: Run them**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_recent_api.py -q`
Expected: PASS, 5 passed. (These pass immediately — they characterize behavior Task 1 already delivers. If `test_post_rejects_the_route_stop_kind` fails with 200, `RecentPushRequest.kind` was widened; revert that.)

- [ ] **Step 3: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/tests/test_recent_api.py
git commit -m "test(recent): pin the /api/recent contract

POST must reject route_stop (the backend recorder is its only writer) and GET
must pass visit_count through — api/recent.py has no response_model, and adding
one later without the field would silently strip it."
```

---

## Task 3: Flag the origin waypoint on `multi_stop`'s arrivals

`multi_stop`'s routed path never emits for `waypoints[0]` (`core/multi_stop.py:187` iterates `range(leg_start, len(waypoints) - 1)` and emits `wp_b = waypoints[i + 1]`). Its jump path does (`:352` iterates `enumerate(waypoints)`). Adding an additive `origin` key lets the recorder skip the origin without deleting an emit that ships today.

**Files:**
- Modify: `backend/core/multi_stop.py:243-248` and `:375-379`
- Modify: `backend/tests/test_multi_stop_cov.py` (append two tests)

**Interfaces:**
- Consumes: nothing.
- Produces: `stop_reached` payload gains `origin: bool`. Consumed by `should_record_stop` (Task 1) and `main.py` (Task 5).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_multi_stop_cov.py`:

```python
@pytest.mark.asyncio
async def test_routed_stop_reached_never_flags_the_origin():
    """Routed multi-stop walks legs 0..N-2 and reports each leg's DESTINATION,
    so waypoints[0] is never a stop_reached subject. origin is always False."""
    eng, _loc, emitted = make_engine()
    _wire(eng)
    eng.current_position = _wp(25.0, 121.0)
    nav = MultiStopNavigator(eng)

    wps = [_wp(25.0, 121.0), _wp(25.0, 121.001), _wp(25.0, 121.002)]
    await nav.start(wps, MovementMode.WALKING, pause_enabled=False)

    stops = [d for (t, d) in emitted if t == "stop_reached"]
    assert stops == [
        {"index": 1, "total": 3, "lat": 25.0, "lng": 121.001, "origin": False},
        {"index": 2, "total": 3, "lat": 25.0, "lng": 121.002, "origin": False},
    ]


@pytest.mark.asyncio
async def test_jump_stop_reached_flags_the_origin():
    """Jump multi-stop teleports to EVERY waypoint including waypoints[0], so
    the first emit carries origin=True and the recorder skips it — keeping jump
    and routed history identical for the same waypoint list."""
    eng, _loc, emitted = make_engine()
    _wire(eng)
    nav = MultiStopNavigator(eng)

    wps = [_wp(25.0, 121.0), _wp(25.0, 121.001)]
    await nav.start(
        wps, MovementMode.WALKING,
        pause_enabled=False, jump_mode=True, jump_interval=0.0,
    )

    stops = [d for (t, d) in emitted if t == "stop_reached"]
    assert stops == [
        {"index": 1, "total": 2, "lat": 25.0, "lng": 121.0, "origin": True},
        {"index": 2, "total": 2, "lat": 25.0, "lng": 121.001, "origin": False},
    ]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_multi_stop_cov.py -q -k origin`
Expected: FAIL — the emitted dicts lack the `origin` key.

- [ ] **Step 3: Add the key to the routed emit**

In `backend/core/multi_stop.py`, replace lines 242-248:

```python
                # Arrived at a stop
                await engine._emit("stop_reached", {
                    "index": i + 1,
                    "total": len(waypoints),
                    "lat": wp_b.lat,
                    "lng": wp_b.lng,
                })
```

with:

```python
                # Arrived at a stop. The routed leg walk reports each leg's
                # DESTINATION, so waypoints[0] is never a subject here —
                # origin is structurally False. The key exists so the history
                # recorder can apply one rule across every mover path.
                await engine._emit("stop_reached", {
                    "index": i + 1,
                    "total": len(waypoints),
                    "lat": wp_b.lat,
                    "lng": wp_b.lng,
                    "origin": False,
                })
```

- [ ] **Step 4: Add the key to the jump emit**

In `backend/core/multi_stop.py`, replace lines 375-379:

```python
            await engine._emit("stop_reached", {
                "index": i + 1,
                "total": len(waypoints),
                "lat": wp.lat, "lng": wp.lng,
            })
```

with:

```python
            # i == 0 is waypoints[0], the position the device already occupied
            # when Start was pressed. Flag it so the history recorder skips it
            # and jump history matches routed history for the same waypoints.
            await engine._emit("stop_reached", {
                "index": i + 1,
                "total": len(waypoints),
                "lat": wp.lat, "lng": wp.lng,
                "origin": i == 0,
            })
```

- [ ] **Step 5: Run the whole multi_stop file**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_multi_stop_cov.py -q`
Expected: PASS. The pre-existing `test_start_basic_two_legs_completes_to_idle` asserts `types.count("stop_reached") == 2`, which an added payload key does not affect.

- [ ] **Step 6: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/core/multi_stop.py backend/tests/test_multi_stop_cov.py
git commit -m "feat(engine): flag the origin waypoint on multi_stop's stop_reached

Additive payload key. The jump path teleports to waypoints[0] and emits for it;
the routed path never does. Marking it lets the upcoming history recorder apply
one rule to both, without deleting an emit the WS surface already ships."
```

---

## Task 4: Emit `stop_reached` from `route_loop`

`route_loop`'s routed leg walk (`core/route_loop.py:237-277`) is shaped exactly like `multi_stop`'s — its own comment at `:213-215` says it "mirrors multi_stop" — but it never emits a coordinate-bearing arrival. Its jump path emits `user_waypoint_advance` with no coordinates. Without this task, running a route in Loop mode records nothing.

**Files:**
- Modify: `backend/core/route_loop.py` (routed leg loop, around `:268-277`; jump loop, around `:383-386`)
- Modify: `backend/tests/test_route_loop_cov.py` (append two tests)

**Interfaces:**
- Consumes: the `origin` key convention from Task 3.
- Produces: `route_loop` emits `stop_reached {index, total, lat, lng, origin}`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_route_loop_cov.py`:

```python
@pytest.mark.asyncio
async def test_routed_loop_emits_stop_reached_per_leg_and_flags_the_closing_leg():
    """closed_waypoints appends waypoints[0], so the final leg lands back on the
    start. That leg reports origin=True: the loop DOES pass through the start,
    but it is the auto-injected position the user never chose, and multi_stop's
    routed path never records it either."""
    eng, _loc, emitted = make_engine()
    _wire(eng)
    looper = RouteLooper(eng)

    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0), _wp(2.0, 2.0)]
    await looper.start_loop(
        wps, MovementMode.WALKING, pause_enabled=False, lap_count=1,
    )

    stops = [d for (t, d) in emitted if t == "stop_reached"]
    assert stops == [
        {"index": 1, "total": 3, "lat": 1.0, "lng": 1.0, "origin": False},
        {"index": 2, "total": 3, "lat": 2.0, "lng": 2.0, "origin": False},
        {"index": 3, "total": 3, "lat": 0.0, "lng": 0.0, "origin": True},
    ]


@pytest.mark.asyncio
async def test_jump_loop_emits_stop_reached_and_flags_the_origin():
    eng, _loc, emitted = make_engine()
    _wire(eng)
    looper = RouteLooper(eng)

    wps = [_wp(0.0, 0.0), _wp(1.0, 1.0), _wp(2.0, 2.0)]
    await looper.start_loop(
        wps, MovementMode.WALKING, pause_enabled=False, lap_count=1,
        jump_mode=True, jump_interval=0.0,
    )

    stops = [d for (t, d) in emitted if t == "stop_reached"]
    assert stops == [
        {"index": 1, "total": 3, "lat": 0.0, "lng": 0.0, "origin": True},
        {"index": 2, "total": 3, "lat": 1.0, "lng": 1.0, "origin": False},
        {"index": 3, "total": 3, "lat": 2.0, "lng": 2.0, "origin": False},
    ]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_loop_cov.py -q -k stop_reached`
Expected: FAIL — `assert [] == [{...}]`; `route_loop` emits no `stop_reached` today.

- [ ] **Step 3: Emit from the routed leg walk**

In `backend/core/route_loop.py`, replace lines 268-277:

```python
                if engine._stop_event.is_set():
                    break

                # Pause at every stop except the last one of the lap (the
                # closing leg lands back on waypoints[0], which becomes the
                # start of the next lap — no double-pause needed).
                is_last_leg = leg_idx == num_legs - 1
                if not is_last_leg:
                    if await _pause_at_stop(leg_idx + 1):
                        break
```

with:

```python
                if engine._stop_event.is_set():
                    break

                # The closing leg lands back on waypoints[0] (closed_waypoints
                # appends it). That is the position the device already occupied
                # when Start was pressed, so flag it and let the history
                # recorder skip it — matching multi_stop's routed path, which
                # never emits for waypoints[0] at all.
                is_last_leg = leg_idx == num_legs - 1

                # Arrived at a stop. Mirrors multi_stop.py's per-leg emit; the
                # leg walk above was already shaped for it.
                await engine._emit("stop_reached", {
                    "index": leg_idx + 1,
                    "total": num_legs,
                    "lat": wp_b.lat,
                    "lng": wp_b.lng,
                    "origin": is_last_leg,
                })

                # Pause at every stop except the last one of the lap (the
                # closing leg lands back on waypoints[0], which becomes the
                # start of the next lap — no double-pause needed).
                if not is_last_leg:
                    if await _pause_at_stop(leg_idx + 1):
                        break
```

- [ ] **Step 4: Emit from the jump loop**

In `backend/core/route_loop.py`, replace lines 383-388:

```python
            await engine._emit("user_waypoint_advance", {
                "current_index": i,
                "next_index": min(i + 1, len(waypoints) - 1),
            })
            if await _dwell():
                break
```

with:

```python
            await engine._emit("user_waypoint_advance", {
                "current_index": i,
                "next_index": min(i + 1, len(waypoints) - 1),
            })
            # Mirrors _run_jump_multistop: i == 0 is waypoints[0], the start
            # position, flagged so the history recorder skips it. The
            # close_loop teleport back to waypoints[0] below deliberately emits
            # nothing — it is the same place.
            await engine._emit("stop_reached", {
                "index": i + 1,
                "total": len(waypoints),
                "lat": wp.lat, "lng": wp.lng,
                "origin": i == 0,
            })
            if await _dwell():
                break
```

- [ ] **Step 5: Run the whole route_loop file**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_loop_cov.py -q`
Expected: PASS. If a pre-existing test asserts an exact ordered list of ALL emitted types, it will now include `stop_reached` — update that expectation and note it in the commit body.

- [ ] **Step 6: Run the full backend suite**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/core/route_loop.py backend/tests/test_route_loop_cov.py
git commit -m "feat(engine): emit stop_reached from route_loop

The routed leg walk already 'mirrors multi_stop' per its own comment, but never
reported a coordinate-bearing arrival, and the jump path only advanced an index.
Without this, a route run in Loop mode — the common case for a closed circuit —
would record no history at all. The closing leg (and jump's i == 0) carry
origin=True so the start position stays out of history."
```

---

## Task 5: Wire the recorder into the composition root

**Files:**
- Modify: `backend/main.py:476-493` (inside `AppState.create_engine_for_device`)
- Create: `backend/tests/test_recent_recorder_wiring.py`

**Interfaces:**
- Consumes: `services.recent.should_record_stop`, `services.recent.record_route_stop` (Task 1); the `origin` key (Tasks 3–4).
- Produces: route stops appear in the store while a route runs.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_recent_recorder_wiring.py`:

```python
"""main.py's engine event_callback is the ONE place a route arrival becomes a
history row. It records before broadcasting (the renderer refetches when it sees
the broadcast), skips the origin waypoint, and only listens to the primary
device's engine — a fan-out run would otherwise count one physical stop once per
phone."""
from __future__ import annotations

import pytest


class _FakeLoc:
    async def set(self, lat, lng):
        pass

    async def clear(self):
        pass


class _FakeDeviceManager:
    async def get_location_service(self, udid):
        return _FakeLoc()


@pytest.fixture
def wired(monkeypatch):
    import main
    import api.websocket as ws

    broadcasts: list[tuple[str, dict]] = []

    async def fake_broadcast(event_type, data):
        broadcasts.append((event_type, dict(data)))

    # create_engine_for_device imports broadcast INSIDE the function body, so
    # patching the module attribute before the call is enough.
    monkeypatch.setattr(ws, "broadcast", fake_broadcast)
    monkeypatch.setattr(main.app_state, "device_manager", _FakeDeviceManager(), raising=False)
    monkeypatch.setattr(main.app_state, "simulation_engines", {}, raising=False)
    monkeypatch.setattr(main.app_state, "_primary_udid", None, raising=False)
    return main, broadcasts


def _stop(lat, lng, origin=False):
    return {"index": 1, "total": 2, "lat": lat, "lng": lng, "origin": origin}


@pytest.mark.asyncio
async def test_primary_records_secondary_and_origin_do_not(wired):
    import services.recent as recent
    main, broadcasts = wired

    await main.app_state.create_engine_for_device("udid-a")  # first device -> primary
    await main.app_state.create_engine_for_device("udid-b")
    eng_a = main.app_state.simulation_engines["udid-a"]
    eng_b = main.app_state.simulation_engines["udid-b"]

    await eng_a.event_callback("stop_reached", _stop(25.0, 121.0))
    await eng_b.event_callback("stop_reached", _stop(30.0, 131.0))          # not primary
    await eng_a.event_callback("stop_reached", _stop(9.0, 9.0, origin=True))  # origin

    rows = [e for e in recent.get_manager().list() if e["kind"] == "route_stop"]
    assert [(e["lat"], e["lng"]) for e in rows] == [(25.0, 121.0)]

    # Every event still reaches the socket, recorded or not.
    assert [t for (t, _d) in broadcasts].count("stop_reached") == 3


@pytest.mark.asyncio
async def test_the_row_exists_before_the_broadcast_goes_out(wired, monkeypatch):
    import services.recent as recent
    import api.websocket as ws
    main, _ = wired

    seen_during_broadcast: list[int] = []

    async def spy_broadcast(event_type, data):
        if event_type == "stop_reached":
            rows = [e for e in recent.get_manager().list() if e["kind"] == "route_stop"]
            seen_during_broadcast.append(len(rows))

    monkeypatch.setattr(ws, "broadcast", spy_broadcast)
    await main.app_state.create_engine_for_device("udid-a")
    eng = main.app_state.simulation_engines["udid-a"]

    await eng.event_callback("stop_reached", _stop(25.0, 121.0))
    # The renderer refetches when it sees the broadcast; the row must already
    # be there when the broadcast is made.
    assert seen_during_broadcast == [1]


@pytest.mark.asyncio
async def test_a_revisit_bumps_visit_count(wired):
    import services.recent as recent
    main, _ = wired

    await main.app_state.create_engine_for_device("udid-a")
    eng = main.app_state.simulation_engines["udid-a"]

    await eng.event_callback("stop_reached", _stop(25.0, 121.0))
    await eng.event_callback("stop_reached", _stop(25.5, 121.5))
    await eng.event_callback("stop_reached", _stop(25.0, 121.0))  # next lap

    rows = [e for e in recent.get_manager().list() if e["kind"] == "route_stop"]
    assert len(rows) == 2
    assert rows[0]["visit_count"] == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_recent_recorder_wiring.py -q`
Expected: FAIL — `assert [] == [(25.0, 121.0)]`; nothing records yet.

- [ ] **Step 3: Wire it up**

In `backend/main.py`, replace lines 476-488:

```python
            from core.simulation_engine import SimulationEngine
            from api.websocket import broadcast
            from infra.device.location_service_port import LocationServiceDevicePort

            loc_service = await self.device_manager.get_location_service(udid)

            async def event_callback(event_type: str, data: dict):
                # Always tag emissions with udid so the frontend can route per-device.
                if isinstance(data, dict) and "udid" not in data:
                    data = {**data, "udid": udid}
                await broadcast(event_type, data)
                if event_type == "position_update" and "lat" in data:
                    self.update_last_position(data["lat"], data["lng"])
```

with:

```python
            from core.simulation_engine import SimulationEngine
            import api.websocket as ws_api
            from infra.device.location_service_port import LocationServiceDevicePort
            from services import recent as recent_service

            loc_service = await self.device_manager.get_location_service(udid)

            async def event_callback(event_type: str, data: dict):
                # Always tag emissions with udid so the frontend can route per-device.
                if isinstance(data, dict) and "udid" not in data:
                    data = {**data, "udid": udid}
                # Record a route arrival BEFORE the broadcast: the renderer
                # refetches /api/recent when it sees stop_reached, so writing
                # afterwards would let the refetch win the race and miss the
                # row. _primary_udid is read live, so a promotion after the
                # primary disconnects keeps recording. This is the composition
                # root — core/ never learns the recent store exists.
                if recent_service.should_record_stop(event_type, data, udid, self._primary_udid):
                    recent_service.record_route_stop(data["lat"], data["lng"])
                await ws_api.broadcast(event_type, data)
                if event_type == "position_update" and "lat" in data:
                    self.update_last_position(data["lat"], data["lng"])
```

Note: `broadcast` is now called as `ws_api.broadcast` so tests can patch the module attribute. `recent_service` is likewise a module reference, not a bound function.

- [ ] **Step 4: Run the wiring test**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_recent_recorder_wiring.py -q`
Expected: PASS, 3 passed.

- [ ] **Step 5: Run the full backend suite and the layering gate**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q && .venv/bin/lint-imports`
Expected: all pass; `Contracts: 7 kept, 0 broken.`

- [ ] **Step 6: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/main.py backend/tests/test_recent_recorder_wiring.py
git commit -m "feat(recent): record route arrivals from the engine event_callback

The composition root already carried one non-WebSocket side effect on
position_update; stop_reached joins it. Recording happens before the broadcast
so the renderer's refetch cannot outrun the write, skips the origin waypoint,
and is gated on the primary device so a fan-out run counts each physical stop
once. SimulationEngine._emit already swallows callback exceptions, so a recorder
failure cannot abandon a route."
```

---

## Task 6: Show route stops in the popover

**Files:**
- Modify: `frontend/src/services/api.ts:417-418`
- Modify: `frontend/src/components/RecentPlacesPopover.tsx:5-12`, `:273-279`, `:337-348`
- Modify: `frontend/src/i18n/strings.ts` (after line 383)
- Modify: `frontend/src/components/RecentPlacesPopover.test.tsx` (append tests)

**Interfaces:**
- Consumes: backend rows carrying `kind: "route_stop"` and `visit_count` (Tasks 1, 5).
- Produces: `RecentKind` includes `'route_stop'`; `RecentEntry.visit_count?: number`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/RecentPlacesPopover.test.tsx` (reuse the file's existing render helper and default props):

```tsx
  it('renders a route badge for a route_stop row', async () => {
    renderPopover({
      recentPlaces: [
        { lat: 25.0, lng: 121.0, kind: 'route_stop', name: '', ts: 1, visit_count: 1 },
      ],
    })
    await userEvent.click(screen.getByRole('button', { name: /history/i }))
    expect(screen.getByText('Route')).toBeInTheDocument()
  })

  it('shows a visit-count chip only when the stop was reached more than once', async () => {
    renderPopover({
      recentPlaces: [
        { lat: 25.0, lng: 121.0, kind: 'route_stop', name: 'A', ts: 2, visit_count: 3 },
        { lat: 26.0, lng: 122.0, kind: 'route_stop', name: 'B', ts: 1, visit_count: 1 },
      ],
    })
    await userEvent.click(screen.getByRole('button', { name: /history/i }))
    expect(screen.getByText('×3')).toBeInTheDocument()
    expect(screen.queryByText('×1')).not.toBeInTheDocument()
  })
```

If the existing test file's helper is named differently, or the popover is opened another way, match the file's existing pattern exactly rather than the sketch above — read `RecentPlacesPopover.test.tsx` first and copy its `renderPopover` / open-the-popover idiom verbatim.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/RecentPlacesPopover.test.tsx`
Expected: FAIL — `Unable to find an element with the text: Route` (the badge falls back to the raw `route_stop` string), and a TypeScript error on `visit_count`.

- [ ] **Step 3: Widen the API types**

In `frontend/src/services/api.ts`, replace lines 417-418:

```ts
export type RecentKind = 'teleport' | 'navigate' | 'search' | 'coord_teleport' | 'coord_navigate'
export interface RecentEntry { lat: number; lng: number; kind: RecentKind; name: string; ts: number }
```

with:

```ts
// 'route_stop' rows are written ONLY by the backend recorder as a simulated
// route reaches each stop; POST /api/recent rejects that kind. visit_count is
// present on route stops only (absent means 1).
export type RecentKind = 'teleport' | 'navigate' | 'search' | 'coord_teleport' | 'coord_navigate' | 'route_stop'
export interface RecentEntry { lat: number; lng: number; kind: RecentKind; name: string; ts: number; visit_count?: number }
```

- [ ] **Step 4: Widen the popover's local entry type**

In `frontend/src/components/RecentPlacesPopover.tsx`, replace lines 5-12:

```tsx
// One recent-destination entry (last 20 teleport / navigate / search actions).
export interface RecentPlaceEntry {
  lat: number;
  lng: number;
  kind: 'teleport' | 'navigate' | 'search' | 'coord_teleport' | 'coord_navigate';
  name: string;
  ts: number;
}
```

with:

```tsx
// One recent-destination entry. Manual kinds are the user's own fly-to actions;
// 'route_stop' rows are arrivals the backend recorded while a simulated route
// ran, and are the only kind carrying visit_count (absent means 1).
export interface RecentPlaceEntry {
  lat: number;
  lng: number;
  kind: 'teleport' | 'navigate' | 'search' | 'coord_teleport' | 'coord_navigate' | 'route_stop';
  name: string;
  ts: number;
  visit_count?: number;
}
```

- [ ] **Step 5: Add the badge**

In `frontend/src/components/RecentPlacesPopover.tsx`, inside `badgeByKind` (after the `coord_navigate` line, currently `:278`), add:

```tsx
                route_stop:      { label: t('recent.kind_route_stop'), color: '#b085f5', bg: 'rgba(176, 133, 245, 0.16)' },
```

- [ ] **Step 6: Render the visit-count chip**

In `frontend/src/components/RecentPlacesPopover.tsx`, immediately after the badge `<span>` (which currently ends `}}>{badge.label}</span>` at `:348`), add:

```tsx
                    {(entry.visit_count ?? 1) > 1 && (
                      <span
                        title={t('recent.visit_count_tooltip')}
                        style={{
                          flexShrink: 0,
                          fontSize: 10, fontWeight: 700,
                          fontFamily: 'monospace',
                          color: '#9499ac',
                          marginLeft: -4,
                        }}
                      >×{entry.visit_count}</span>
                    )}
```

- [ ] **Step 7: Add the i18n keys**

In `frontend/src/i18n/strings.ts`, after `'recent.kind_coord'` (line 382), add:

```ts
  'recent.kind_route_stop': { zh: '路線', en: 'Route' },
  'recent.visit_count_tooltip': { zh: '路線經過此點的次數', en: 'Times the route passed through' },
```

- [ ] **Step 8: Run the popover tests and the type check**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/RecentPlacesPopover.test.tsx && npx tsc --noEmit`
Expected: PASS; no type errors.

- [ ] **Step 9: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/services/api.ts frontend/src/components/RecentPlacesPopover.tsx frontend/src/i18n/strings.ts frontend/src/components/RecentPlacesPopover.test.tsx
git commit -m "feat(recent): render route stops with a visit-count chip

New purple 'Route' badge, and an x3 chip on stops the route passed more than
once. Both copies of the entry type gain the widened kind union and the optional
visit_count. Rows whose coords match a bookmark keep resolving the bookmark's
name through the existing bookmarkByCoord lookup."
```

---

## Task 7: Refetch history when a stop is reached

The backend now writes rows the renderer never asks for again — `useRecentPlaces` refetches only on mount and on the WebSocket reconnecting. Subscribing to `stop_reached` closes that gap. The hook stays read-only: it never POSTs a route stop.

**Files:**
- Modify: `frontend/src/hooks/useRecentPlaces.ts`
- Modify: `frontend/src/App.tsx:345`
- Modify: `frontend/src/adapters/ws/eventWiring.test.tsx`
- Modify: `frontend/src/hooks/useRecentPlaces.test.ts` (append one test)

**Interfaces:**
- Consumes: `WsRouter` from `frontend/src/ports/WsRouter.ts` — `subscribe(type: WsEventType, handler: (e: WsEvent) => void): () => void`.
- Produces: `useRecentPlaces(api: ApiGateway, connected: boolean, ws?: WsRouter)`. The third parameter is **optional**, so the five existing test call sites compile unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/hooks/useRecentPlaces.test.ts`:

```ts
  it('coalesces a burst of stop_reached events into one refetch', async () => {
    vi.useFakeTimers()
    try {
      const { api, stub } = makeStubApi()
      const handlers: Record<string, (e: any) => void> = {}
      const ws = {
        subscribe: (type: string, h: (e: any) => void) => {
          handlers[type] = h
          return () => { delete handlers[type] }
        },
      }
      renderHook(() => useRecentPlaces(api, true, ws as any))
      await act(async () => { await Promise.resolve() })   // flush the mount fetch
      const afterMount = stub.getRecent.mock.calls.length

      // A 3-device fan-out emits the same physical stop three times.
      act(() => {
        handlers['stop_reached']({ type: 'stop_reached' })
        handlers['stop_reached']({ type: 'stop_reached' })
        handlers['stop_reached']({ type: 'stop_reached' })
      })
      expect(stub.getRecent.mock.calls.length).toBe(afterMount)  // nothing yet

      await act(async () => { vi.advanceTimersByTime(500); await Promise.resolve() })
      expect(stub.getRecent.mock.calls.length).toBe(afterMount + 1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('never posts a route stop', async () => {
    const { api, stub } = makeStubApi()
    const handlers: Record<string, (e: any) => void> = {}
    const ws = {
      subscribe: (type: string, h: (e: any) => void) => { handlers[type] = h; return () => {} },
    }
    renderHook(() => useRecentPlaces(api, true, ws as any))
    await waitFor(() => expect(stub.getRecent).toHaveBeenCalled())
    act(() => { handlers['stop_reached']({ type: 'stop_reached', lat: 1, lng: 2 }) })
    expect(stub.pushRecent).not.toHaveBeenCalled()
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useRecentPlaces.test.ts`
Expected: FAIL — `handlers['stop_reached'] is not a function` (the hook subscribes to nothing).

- [ ] **Step 3: Subscribe in the hook**

In `frontend/src/hooks/useRecentPlaces.ts`, change the import block and signature, and add the effect. Replace the first line:

```ts
import { useState, useCallback, useEffect } from 'react'
```

with:

```ts
import { useState, useCallback, useEffect, useRef } from 'react'
import type { WsRouter } from '../ports/WsRouter'
```

Replace the signature line:

```ts
export function useRecentPlaces(api: ApiGateway, connected: boolean) {
```

with:

```ts
export function useRecentPlaces(api: ApiGateway, connected: boolean, ws?: WsRouter) {
```

Then, immediately after the existing mount/`connected` effect (`useEffect(() => { void refreshRecent() }, [refreshRecent, connected])`), add:

```ts
  // The backend records a route stop on every `stop_reached` and broadcasts the
  // same event, so the popover would otherwise show stale data until the next
  // reconnect. This is a READ-path subscription only — the hook never POSTs a
  // route stop (POST /api/recent rejects that kind; the backend is the sole
  // writer). A fan-out run emits one event per device for the same physical
  // stop, and stops on a fast jump loop land back-to-back, so the refetch is
  // coalesced onto a trailing timer instead of firing per event.
  const refreshRef = useRef(refreshRecent)
  refreshRef.current = refreshRecent
  useEffect(() => {
    if (!ws) return
    let timer: ReturnType<typeof setTimeout> | null = null
    const off = ws.subscribe('stop_reached', () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => { timer = null; void refreshRef.current() }, 500)
    })
    return () => { off(); if (timer) clearTimeout(timer) }
  }, [ws])
```

- [ ] **Step 4: Pass the router from App**

In `frontend/src/App.tsx`, replace line 345:

```tsx
  const recent = useRecentPlaces(api, connected)
```

with:

```tsx
  const recent = useRecentPlaces(api, connected, router)
```

- [ ] **Step 5: Promote `stop_reached` in the eventWiring gate**

In `frontend/src/adapters/ws/eventWiring.test.tsx`:

(a) Add the import next to the other hook imports:

```tsx
import { useRecentPlaces } from '../../hooks/useRecentPlaces'
import type { ApiGateway } from '../../contract/apiGateway'
```

(b) Delete this line from `UI_IGNORED_BY_DESIGN`:

```tsx
  'stop_reached', // multi-stop intermediate progress, not surfaced
```

(c) Inside `collectSubscribedTypes()`, after the `useGoldDittoSubscription` mount, add:

```tsx
  // useRecentPlaces refetches the history list when a simulated route reaches a
  // stop (the backend writes the row; this hook only invalidates its cache).
  const apiStub = {
    getRecent: async () => [],
    pushRecent: async (e: unknown) => e,
    clearRecent: async () => ({ status: 'ok' }),
    reverseGeocode: async () => ({}),
  } as unknown as ApiGateway
  renderHook(() => useRecentPlaces(apiStub, true, recordingRouter))
```

- [ ] **Step 6: Run the frontend gates**

Run:
```bash
cd /Users/raviwu/personal/locwarp/frontend
npx vitest run src/hooks/useRecentPlaces.test.ts src/adapters/ws/eventWiring.test.tsx
npx tsc --noEmit
npx depcruise src --config .dependency-cruiser.cjs
```
Expected: all pass; depcruise reports `no dependency violations found`.

- [ ] **Step 7: Run the whole frontend suite**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/hooks/useRecentPlaces.ts frontend/src/hooks/useRecentPlaces.test.ts frontend/src/App.tsx frontend/src/adapters/ws/eventWiring.test.tsx
git commit -m "feat(recent): refetch history when a route reaches a stop

stop_reached moves out of the eventWiring not-surfaced allowlist and into a real
subscription. Read-path only: the backend owns the write, the hook only
invalidates its cache. The refetch is coalesced on a trailing 500ms timer
because a fan-out run emits the same physical stop once per device."
```

---

## Task 8: Fix re-fly — no duplicate row, no silent route kill

Clicking any history row calls `handleTeleport`, which unconditionally pushes a manual `teleport` entry (`useSimActions.ts:195`) and stops any running simulation server-side (`core/teleport.py:29` calls `engine.stop()`). Neither was route-stop-specific, but route stops now appear mid-run, so both became easy to hit by accident.

**Files:**
- Modify: `frontend/src/hooks/useSimActions.ts:158-199` and `:201-224`
- Modify: `frontend/src/App.tsx:1146-1151`
- Modify: `frontend/src/i18n/strings.ts` (after line 563)
- Modify: `frontend/src/hooks/useSimActions.test.ts` if it exists, else create `frontend/src/App.recentReFly.test.tsx`

**Interfaces:**
- Consumes: `RecentEntry` with `kind: 'route_stop'` (Task 6).
- Produces:
  - `handleTeleport(latIn: number, lngIn: number, source?: 'menu' | 'coord', opts?: { record?: boolean }) => Promise<boolean>` — resolves `true` when at least one device actually moved.
  - `handleNavigate(latIn: number, lngIn: number, source?: 'menu' | 'coord', opts?: { record?: boolean }) => Promise<boolean>`

- [ ] **Step 1: Check whether a useSimActions test file exists**

Run: `ls /Users/raviwu/personal/locwarp/frontend/src/hooks/useSimActions.test.ts 2>/dev/null || echo MISSING`

If it exists, append the tests from Step 2 to it. If `MISSING`, create `frontend/src/App.recentReFly.test.tsx` and write them against `onRecentReFly` through a rendered `App`, following the mock-list pattern used by the other `App.*.test.tsx` files (they all stub the same `'getSavedRoutes', 'getRecent', 'listRouteCategories', 'listBookmarks'` api surface — copy that list verbatim from `frontend/src/App.smoke.test.tsx`).

- [ ] **Step 2: Write the failing tests**

```ts
  it('re-flying a route stop does not create a duplicate manual entry', async () => {
    const { result, pushRecent } = renderSimActions()
    await act(async () => {
      await result.current.handleTeleport(25.0, 121.0, 'menu', { record: false })
    })
    expect(pushRecent).not.toHaveBeenCalled()
  })

  it('re-flying a manual row still records it', async () => {
    const { result, pushRecent } = renderSimActions()
    await act(async () => {
      await result.current.handleTeleport(25.0, 121.0)
    })
    expect(pushRecent).toHaveBeenCalledWith(25.0, 121.0, 'teleport')
  })

  it('handleTeleport resolves false when the single-device teleport throws', async () => {
    const { result } = renderSimActions({ teleport: async () => { throw new Error('boom') } })
    let ok: boolean | undefined
    await act(async () => { ok = await result.current.handleTeleport(1, 2) })
    expect(ok).toBe(false)
  })
```

`renderSimActions` is a helper you write in the test file: it calls `renderHook(() => useSimActions(...))` with the same argument shape `App.tsx:368` passes (`{ sim, device, showToast, t, pushRecent, api }`), using `vi.fn()` for `pushRecent` and a `sim` stub whose `connectedDevices` has one entry. Read `App.tsx:360-370` for the exact argument object before writing it.

- [ ] **Step 3: Run them to verify they fail**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useSimActions.test.ts`
Expected: FAIL — `handleTeleport` ignores the 4th argument and resolves `undefined`.

- [ ] **Step 4: Make `handleTeleport` optional-record and boolean-returning**

In `frontend/src/hooks/useSimActions.ts`, change the signature at line 158:

```ts
  const handleTeleport = useCallback(async (latIn: number, lngIn: number, source: 'menu' | 'coord' = 'menu') => {
```

to:

```ts
  // `opts.record` exists for the Recent popover's re-fly: a route_stop row is
  // already in history, and pushing a manual 'teleport' for it would mint a
  // duplicate row the backend cannot dedupe (manual and route entries live in
  // separate classes). Resolves true when at least one device actually moved.
  const handleTeleport = useCallback(async (
    latIn: number,
    lngIn: number,
    source: 'menu' | 'coord' = 'menu',
    opts: { record?: boolean } = {},
  ): Promise<boolean> => {
```

In the dual-device branch, replace:

```ts
      if (outcome.ok.length === 0 && outcome.failed.length > 0) {
        sim.setCurrentPosition(prevPos ?? null)
      }
      showToast(toastForFanout(t, t('mode.teleport'), outcome, device.connectedDevices))
```

with:

```ts
      if (outcome.ok.length === 0 && outcome.failed.length > 0) {
        sim.setCurrentPosition(prevPos ?? null)
        showToast(toastForFanout(t, t('mode.teleport'), outcome, device.connectedDevices))
        return false
      }
      showToast(toastForFanout(t, t('mode.teleport'), outcome, device.connectedDevices))
```

In the single-device branch, replace:

```ts
      } catch {
        showToast(t('toast.teleport_failed'))
        return
      }
```

with:

```ts
      } catch {
        showToast(t('toast.teleport_failed'))
        return false
      }
```

And replace the tail:

```ts
    void pushRecent(lat, lng, source === 'coord' ? 'coord_teleport' : 'teleport')
```

with:

```ts
    if (opts.record !== false) {
      void pushRecent(lat, lng, source === 'coord' ? 'coord_teleport' : 'teleport')
    }
    return true
```

- [ ] **Step 5: Do the same for `handleNavigate`**

In `frontend/src/hooks/useSimActions.ts`, change line 201's signature to:

```ts
  const handleNavigate = useCallback(async (
    latIn: number,
    lngIn: number,
    source: 'menu' | 'coord' = 'menu',
    opts: { record?: boolean } = {},
  ): Promise<boolean> => {
```

Replace:

```ts
      } catch {
        showToast(t('toast.navigate_failed'))
        return
      }
```

with:

```ts
      } catch {
        showToast(t('toast.navigate_failed'))
        return false
      }
```

And replace the tail:

```ts
    void pushRecent(lat, lng, source === 'coord' ? 'coord_navigate' : 'navigate')
```

with:

```ts
    if (opts.record !== false) {
      void pushRecent(lat, lng, source === 'coord' ? 'coord_navigate' : 'navigate')
    }
    return true
```

- [ ] **Step 6: Update `onRecentReFly`**

In `frontend/src/App.tsx`, replace lines 1146-1151:

```tsx
  // MapView stable handlers
  const onRecentReFly = useCallback((entry: any) => {
    const isNavigate = entry.kind === 'navigate' || entry.kind === 'coord_navigate'
    if (isNavigate) handleNavigate(entry.lat, entry.lng)
    else handleTeleport(entry.lat, entry.lng)
  }, [handleNavigate, handleTeleport])
```

with:

```tsx
  // MapView stable handlers
  const onRecentReFly = useCallback(async (entry: any) => {
    const isNavigate = entry.kind === 'navigate' || entry.kind === 'coord_navigate'
    // A route stop already has its own history row; re-flying it must not mint
    // a duplicate manual 'teleport' entry alongside it.
    const isRouteStop = entry.kind === 'route_stop'
    const ok = isNavigate
      ? await handleNavigate(entry.lat, entry.lng)
      : await handleTeleport(entry.lat, entry.lng, 'menu', { record: !isRouteStop })
    // Any fly-to stops a running simulation server-side (core/teleport.py's
    // engine.stop()). That was always true, but route stops now surface mid-run,
    // so say it out loud instead of killing the route silently.
    if (ok && isRunning) showToast(t('toast.sim_stopped_by_refly'))
  }, [handleNavigate, handleTeleport, isRunning, showToast, t])
```

`isRunning` is already declared at `App.tsx:955` (`const isRunning = sim.status.running`), above this callback.

- [ ] **Step 7: Add the toast string**

In `frontend/src/i18n/strings.ts`, after `'toast.navigate_failed'` (line 563), add:

```ts
  'toast.sim_stopped_by_refly': { zh: '已中斷進行中的模擬', en: 'Interrupted the running simulation' },
```

- [ ] **Step 8: Run the frontend gates**

Run:
```bash
cd /Users/raviwu/personal/locwarp/frontend
npx vitest run
npx tsc --noEmit
npx depcruise src --config .dependency-cruiser.cjs
```
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/hooks/useSimActions.ts frontend/src/App.tsx frontend/src/i18n/strings.ts frontend/src/hooks/useSimActions.test.ts frontend/src/App.recentReFly.test.tsx 2>/dev/null
git commit -m "fix(recent): re-fly no longer duplicates a row or kills a route silently

handleTeleport/handleNavigate take an opt-out for the recent push and resolve a
success boolean. Re-flying a route_stop skips the push (the row already exists,
and manual entries cannot dedupe into route entries), and any re-fly that
interrupts a running simulation now says so. Both defects predate route stops;
they only became easy to hit once route rows started appearing mid-run."
```

---

## Task 9: Add the recent store to the rotating backup

Bookmarks and routes snapshot to `~/.locwarp/backups/` every five minutes; the recent store does not. With `visit_count` accumulating over months, that asymmetry now costs real data.

**Files:**
- Modify: `backend/domain/recent.py` (add `merge_recent`)
- Modify: `backend/domain/backup.py:20-27` and `:60-76`
- Modify: `backend/services/backup_service.py`
- Modify: `backend/main.py:209-220` (`_backup_provider`)
- Modify: `backend/merge_backup.py` (`restore_combined_snapshot`)
- Modify: `backend/tests/test_backup_service.py`
- Create: `backend/tests/test_recent_merge.py`
- Modify: `docs/superpowers/specs/2026-07-10-route-stops-to-history-design.md` (record the restore caveat found below)

**Interfaces:**
- Consumes: `RecentPlacesManager.snapshot_export()` (Task 1).
- Produces:
  - `domain.recent.merge_recent(a: list[dict], b: list[dict]) -> list[dict]` — commutative, idempotent, class-scoped, capped, ts-desc.
  - `domain.backup.data_fingerprint(bookmarks: dict, routes: dict, recent: list) -> str`
  - `domain.backup.build_snapshot(bookmarks: dict, routes: dict, recent: list, now: datetime, source: str) -> dict`
  - `BackupTickResult.recent_count: int`
  - The combined snapshot's top-level keys become `{_backup_meta, bookmarks, routes, recent}`.

- [ ] **Step 1: Check whether the manual backup script builds its own payload**

Run: `grep -n "build_snapshot\|bookmarks\|routes" /Users/raviwu/personal/locwarp/scripts/desktop_backup.py | head -20`

If it calls `domain.backup.build_snapshot`, it picks up `recent` for free. If it constructs the dict itself, add `recent` there too in Step 8 so `make backup` and the in-process task keep writing interchangeable files.

- [ ] **Step 2: Write the failing merge tests**

Create `backend/tests/test_recent_merge.py`:

```python
"""merge_recent folds a backup snapshot into the live recent store.

The store is not a CRDT set — no tombstones, nothing deleted except by the
user's explicit Clear — so restoring means UNION, not replace. Like
domain.store_merge.merge_stores, the operation must be commutative and
idempotent, or `make restore-backup` run twice would not be a no-op.
"""
from __future__ import annotations

from domain.recent import MAX_MANUAL_ENTRIES, MAX_ROUTE_STOP_ENTRIES, merge_recent


def _manual(lat, lng, ts, name=""):
    return {"lat": lat, "lng": lng, "kind": "teleport", "name": name, "ts": ts}


def _route(lat, lng, ts, visits=1, name=""):
    return {"lat": lat, "lng": lng, "kind": "route_stop", "name": name,
            "ts": ts, "visit_count": visits}


def test_union_keeps_rows_present_in_either_side():
    a = [_manual(1.0, 1.0, 100)]
    b = [_manual(2.0, 2.0, 200)]
    assert len(merge_recent(a, b)) == 2


def test_matched_rows_keep_the_newest_ts_and_the_highest_visit_count():
    a = [_route(25.0, 121.0, 100, visits=5)]
    b = [_route(25.0, 121.0, 300, visits=2)]
    merged = merge_recent(a, b)
    assert len(merged) == 1
    assert merged[0]["ts"] == 300
    assert merged[0]["visit_count"] == 5


def test_a_manual_row_never_merges_with_a_route_row_at_the_same_spot():
    merged = merge_recent([_manual(25.0, 121.0, 100)], [_route(25.0, 121.0, 200)])
    kinds = sorted(e["kind"] for e in merged)
    assert kinds == ["route_stop", "teleport"]


def test_a_non_empty_name_wins_over_an_empty_one():
    merged = merge_recent([_route(25.0, 121.0, 100, name="")],
                          [_route(25.0, 121.0, 200, name="Taipei")])
    assert merged[0]["name"] == "Taipei"


def test_manual_rows_gain_no_visit_count():
    merged = merge_recent([_manual(1.0, 1.0, 100)], [_manual(1.0, 1.0, 200)])
    assert len(merged) == 1
    assert "visit_count" not in merged[0]


def test_result_is_ts_descending_and_capped_per_class():
    a = [_manual(1.0 + i, 2.0 + i, 100 + i) for i in range(25)]
    b = [_route(40.0 + i * 0.5, 100.0 + i * 0.5, 500 + i) for i in range(40)]
    merged = merge_recent(a, b)
    kinds = [e["kind"] for e in merged]
    assert kinds.count("teleport") == MAX_MANUAL_ENTRIES
    assert kinds.count("route_stop") == MAX_ROUTE_STOP_ENTRIES
    ts = [e["ts"] for e in merged]
    assert ts == sorted(ts, reverse=True)


def test_merge_is_commutative():
    a = [_route(25.0, 121.0, 100, visits=5), _manual(1.0, 1.0, 90)]
    b = [_route(25.0, 121.0, 300, visits=2), _manual(2.0, 2.0, 80)]
    assert merge_recent(a, b) == merge_recent(b, a)


def test_merge_is_idempotent():
    a = [_route(25.0, 121.0, 100, visits=5), _manual(1.0, 1.0, 90)]
    once = merge_recent(a, [])
    assert merge_recent(once, once) == once
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_recent_merge.py -q`
Expected: FAIL — `ImportError: cannot import name 'merge_recent'`.

- [ ] **Step 4: Implement `merge_recent`**

Append to `backend/domain/recent.py`:

```python
def _fold(rows: list[dict], cap: int, keep_visits: bool) -> list[dict]:
    """Collapse rows within DEDUPE_DIST_M of each other, newest first."""
    kept: list[dict] = []
    for row in sort_desc(rows):
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
```

- [ ] **Step 5: Run the merge tests**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_recent_merge.py -q`
Expected: PASS, 8 passed.

If `test_merge_is_commutative` fails, the cause is the tie-break inside `_fold`: with equal `ts`, `sort_desc` preserves input order, so `a + b` and `b + a` fold onto different survivors. Fix by sorting each class's input with a deterministic secondary key before folding — change `sort_desc(rows)` inside `_fold` to `sorted(rows, key=lambda e: (-e.get("ts", 0), e["lat"], e["lng"]))`.

- [ ] **Step 6: Thread `recent` through the backup domain policy**

In `backend/domain/backup.py`, replace `data_fingerprint`:

```python
def data_fingerprint(bookmarks: dict, routes: dict) -> str:
    """Canonical JSON of the DATA only (excludes _backup_meta) — so 'changed'
    means the bookmarks/routes changed, not merely that a tick passed.
    Mirrors desktop_backup._content_of."""
    return json.dumps(
        {"bookmarks": bookmarks, "routes": routes}, sort_keys=True, ensure_ascii=False
    )
```

with:

```python
def data_fingerprint(bookmarks: dict, routes: dict, recent: list) -> str:
    """Canonical JSON of the DATA only (excludes _backup_meta) — so 'changed'
    means the stores changed, not merely that a tick passed.
    Mirrors desktop_backup._content_of."""
    return json.dumps(
        {"bookmarks": bookmarks, "routes": routes, "recent": recent},
        sort_keys=True, ensure_ascii=False,
    )
```

and replace `build_snapshot`:

```python
def build_snapshot(bookmarks: dict, routes: dict, now: datetime, source: str) -> dict:
```

with:

```python
def build_snapshot(
    bookmarks: dict, routes: dict, recent: list, now: datetime, source: str
) -> dict:
```

adding to its returned `_backup_meta` dict, after `"route_count"`:

```python
            "recent_count": len(recent),
```

and to the returned payload, after `"routes": routes,`:

```python
        "recent": recent,
```

- [ ] **Step 7: Update the service**

In `backend/services/backup_service.py`:

Add `recent_count: int = 0` to `BackupTickResult`, after `route_count`.

Change the constructor annotation `snapshot_provider: Callable[[], tuple[dict, dict]]` to `Callable[[], tuple[dict, dict, list]]`.

Replace the body of `tick` up to the `payload` line:

```python
    def tick(self, now: datetime) -> BackupTickResult:
        bookmarks, routes = self._snapshot_provider()
        bm = len(bookmarks.get("bookmarks", []))
        rt = len(routes.get("routes", []))

        # Never let a transient empty state (iCloud eviction, startup) clobber
        # a good backup — write nothing at all.
        if bm == 0 and rt == 0:
            return BackupTickResult(skipped="empty")

        prev = self._repo.read_latest()
        changed = prev is None or backup.data_fingerprint(bookmarks, routes) != backup.data_fingerprint(
            prev.get("bookmarks", {}), prev.get("routes", {})
        )

        payload = backup.build_snapshot(bookmarks, routes, now, self._source)
```

with:

```python
    def tick(self, now: datetime) -> BackupTickResult:
        bookmarks, routes, recent = self._snapshot_provider()
        bm = len(bookmarks.get("bookmarks", []))
        rt = len(routes.get("routes", []))

        # Never let a transient empty state (iCloud eviction, startup) clobber
        # a good backup — write nothing at all. Recent is deliberately NOT part
        # of this guard: it is the least valuable store, and an empty
        # bookmarks+routes state is the signal that the data dir is not ready.
        if bm == 0 and rt == 0:
            return BackupTickResult(skipped="empty")

        prev = self._repo.read_latest()
        # `prev.get("recent", [])` keeps snapshots written before recent joined
        # the payload comparable — they simply look like an empty recent store.
        changed = prev is None or backup.data_fingerprint(bookmarks, routes, recent) != backup.data_fingerprint(
            prev.get("bookmarks", {}), prev.get("routes", {}), prev.get("recent", [])
        )

        payload = backup.build_snapshot(bookmarks, routes, recent, now, self._source)
```

and the return:

```python
        return BackupTickResult(bm, rt, changed, len(deleted))
```

becomes:

```python
        return BackupTickResult(bm, rt, len(recent), changed, len(deleted))
```

(`BackupTickResult`'s field order must be `bookmark_count, route_count, recent_count, changed, pruned`.)

- [ ] **Step 8: Update the provider and, if needed, the manual script**

In `backend/main.py`, replace lines 209-220's provider:

```python
        def _backup_provider():
            return (
                self.bookmark_manager.snapshot_export(),
                self.route_manager.snapshot_export(),
            )
```

with:

```python
        def _backup_provider():
            from services.recent import get_manager as _recent_manager
            return (
                self.bookmark_manager.snapshot_export(),
                self.route_manager.snapshot_export(),
                _recent_manager().snapshot_export(),
            )
```

If Step 1 showed `scripts/desktop_backup.py` builds its own payload dict, add a `"recent"` key there reading `~/.locwarp/recent_places.json` directly, plus `recent_count` in its `_backup_meta`.

- [ ] **Step 9: Restore the recent sub-store**

In `backend/merge_backup.py`, inside `restore_combined_snapshot`, after the routes sub-store is folded into its live path, add the recent restore. It does **not** go through `detect_store_cls` (recent is a flat list, not a pydantic store):

```python
    # `recent` is a flat list, not a pydantic store, so it bypasses
    # detect_store_cls / merge_stores and uses its own pure union.
    # Absent on snapshots written before recent joined the payload.
    from pathlib import Path

    from domain.recent import merge_recent
    from services.json_safe import safe_load_json, safe_write_json

    incoming = raw.get("recent")
    if isinstance(incoming, list):
        live_path = Path(config.RECENT_PLACES_FILE)
        live = safe_load_json(live_path)
        merged = merge_recent(live if isinstance(live, list) else [], incoming)
        if not dry_run:
            safe_write_json(live_path, merged)
        summary["recent"] = {"merged": len(merged), "incoming": len(incoming)}
```

Match the surrounding function's local names for `summary` / `dry_run` / the config import — read `merge_backup.py:174-230` first and adapt. `is_combined_snapshot` needs no change: it keys off `_backup_meta` plus dict-shaped `bookmarks`/`routes`, and `recent` is a list.

- [ ] **Step 10: Update the backup service tests**

In `backend/tests/test_backup_service.py`, change the helper:

```python
def _svc(repo, bms, rts, retention=72):
    return BackupService(repo, lambda: (bms, rts), retention)
```

to:

```python
def _svc(repo, bms, rts, recent=None, retention=72):
    return BackupService(repo, lambda: (bms, rts, recent or []), retention)
```

Then update the payload-shape assertion `set(r.latest) == {'_backup_meta', 'bookmarks', 'routes'}` to `{'_backup_meta', 'bookmarks', 'routes', 'recent'}`, and add:

```python
def test_a_recent_only_change_archives_a_new_snapshot():
    repo = FakeRepo()
    bms = {"categories": [], "bookmarks": [{"id": "b1"}]}
    rts = {"categories": [], "routes": []}
    _svc(repo, bms, rts, recent=[]).tick(datetime(2026, 1, 1, 0, 0, 0))
    before = len(repo.snaps)
    row = [{"lat": 1.0, "lng": 2.0, "kind": "route_stop", "name": "", "ts": 1, "visit_count": 1}]
    _svc(repo, bms, rts, recent=row).tick(datetime(2026, 1, 1, 0, 5, 0))
    assert len(repo.snaps) == before + 1


def test_a_pre_recent_latest_file_still_compares():
    """A 'latest' written before recent joined the payload has no 'recent' key;
    it must read as an empty recent store, not crash."""
    repo = FakeRepo()
    repo.latest = {"_backup_meta": {}, "bookmarks": {"bookmarks": [{"id": "b1"}]},
                   "routes": {"routes": []}}
    bms = {"categories": [], "bookmarks": [{"id": "b1"}]}
    rts = {"categories": [], "routes": []}
    r = _svc(repo, bms, rts, recent=[]).tick(datetime(2026, 1, 1, 0, 0, 0))
    assert r.changed is False
```

Fix any other call site of `_svc` / `build_snapshot` / `data_fingerprint` the compiler or the test run surfaces.

- [ ] **Step 11: Run the full backend suite and the layering gate**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q && .venv/bin/lint-imports`
Expected: all pass; `Contracts: 7 kept, 0 broken.` (`domain/recent.py` imports `math` only, so `no-domain-imports-outer` holds.)

- [ ] **Step 12: Record the restore caveat in the spec**

`BookmarkManager` and `RouteManager` run file watchers that pick up an external write; `RecentPlacesManager` does **not**. Restoring while LocWarp is running would leave the in-memory lists stale, and the next push would overwrite the restored file.

In `docs/superpowers/specs/2026-07-10-route-stops-to-history-design.md`, under **§10 Known limitations**, add:

```markdown
- **`make restore-backup` must be run with LocWarp stopped** for the recent
  store. Bookmarks and routes have file watchers that pick up an external write;
  the recent store does not, so a restore into a running app would be overwritten
  by the next push.
```

- [ ] **Step 13: Run the whole gate**

Run: `cd /Users/raviwu/personal/locwarp && make verify`
Expected: backend pytest green, `lint-imports` 7/0, `tsc` clean, vitest green, `depcruise` clean, playwright green.

- [ ] **Step 14: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/domain/recent.py backend/domain/backup.py backend/services/backup_service.py backend/main.py backend/merge_backup.py backend/tests/test_recent_merge.py backend/tests/test_backup_service.py docs/superpowers/specs/2026-07-10-route-stops-to-history-design.md
git commit -m "feat(backup): include the recent store in the rotating snapshot

visit_count accumulates over months, so route history is now worth as much as a
bookmark. merge_recent gives restore the union semantics the store needs: it has
no tombstones, so a restore must fold rather than replace. visit_count merges
with max(), not a sum — the snapshots overlap in time and adding them would
double-count. Snapshots written before this change read as an empty recent store.
Restore requires LocWarp stopped: the recent store has no file watcher."
```

---

## Self-Review

**Spec coverage.** §5.1 store → Task 1. §5.2 origin marking → Tasks 3–4. §5.3 wiring → Task 5. §5.4 API → Task 2. §5.5 frontend → Tasks 6–8. §5.6 backup → Task 9. §7 invariants: 1–2 (Task 1), 3 (Task 1), 4 (Task 2), 5 (Tasks 3–4), 6 (Task 5), 7 (Task 1). §8 testing: every listed test has a home. §10 limitations: unchanged, plus the restore caveat added in Task 9 Step 12.

**Two spec corrections found while planning.**
1. The spec's commit plan listed `C1 | Store tests (red)` as its own commit, which contradicts its own "each commit leaves the full suite green." This plan folds test and implementation into one commit per task.
2. The spec claimed the five `useRecentPlaces.test.ts` call sites need updating. They do not: `ws` is an optional third parameter, so they compile unchanged. Only `App.tsx:345` passes it.

**Type consistency.** `record_route_stop(lat, lng)` and `should_record_stop(event_type, data, udid, primary_udid)` are named identically in Tasks 1 and 5. `push_route_stop(lat, lng, name=None)` is used with two positional args in Tasks 1, 2, 5 and 9. `merge_recent(a, b)` is defined in Task 9 Step 4 and used in Step 9. `handleTeleport(lat, lng, source, opts)` returns `Promise<boolean>` in Task 8 and is awaited in the same task. `RecentEntry.visit_count?` (Task 6) matches the backend's optional field (Task 1). `data_fingerprint` / `build_snapshot` take `recent` in the same position at every call site in Task 9.

**Risk register.**
- Task 4 Step 5 may surface a route_loop test asserting a full ordered event list. Handle it there; do not weaken the assertion — extend it.
- Task 9 Step 5 names the exact commutativity failure mode and its fix, because `sort_desc` alone is not a total order.
- Task 8 Step 1 branches on whether `useSimActions.test.ts` exists; both branches are specified.
