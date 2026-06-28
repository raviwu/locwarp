# Route Distance Estimate (直線 + 沿路) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a route is added / edited / imported, show 直線 (straight-line) and 沿路 (road-following) total km efficiently and **without ever sticking on "計算中"** — the road badge always shows the exact value or a `≈` estimate.

**Architecture:** Inline straight distance (pure haversine) on every save; a deferred orchestrator computes the exact road distance as **one multi-waypoint request** to FOSSGIS OSRM with bounded retry, and **always writes a terminal state** (`road_distance_status` ok|unavailable) + broadcasts `routes_changed`. The frontend shows a client-side `≈` estimate (straight × profile detour factor) whenever the exact value is absent, so the UI is never blank and never spins.

**Tech Stack:** Python 3.13 / FastAPI / pydantic / pytest; React + TypeScript / Vitest. Routing via the already-wired `route_service` engines (OSRM/FOSSGIS/Valhalla/BRouter).

## Global Constraints

- **Behavior/API freeze otherwise:** no new HTTP / WS / IPC endpoint; reuse the existing `routes_changed` WS event (payload `{"reason": ...}`) and the existing route handlers. The route-distance feature is purely additive.
- **Clean-arch import rules (import-linter, 7 contracts must stay `7 kept, 0 broken`):** `domain/` imports stdlib + pydantic only (route_distance.py may import `domain.movement` + `models.schemas`, nothing outer). `services/` must NOT import `api/` — the road orchestrator takes the WS **publisher injected** (never `from api.websocket import broadcast`). `services/` raises domain errors, not `HTTPException`.
- **Frontend hexagon-lite:** view imports from `utils/` / `hooks/`, never `adapters/api` or `services/api`. `dependency-cruiser` must stay `0 errors`.
- **Test baselines (pinned 2026-06-28):** backend **1074** pytest collected; frontend **895** vitest across **111** files. Keep both green after every commit; `npx tsc --noEmit` clean.
- **Default routing engine:** `config.DEFAULT_ROUTE_ENGINE = ROUTE_ENGINE_OSRM_FOSSGIS` (off the no-SLA demo server). FOSSGIS requests carry an `X-Client-Id: LocWarp` header.
- **Detour factors (frontend estimate):** driving/car 1.4, walking/running/foot 1.3, cycling/bike 1.35, default 1.4.
- **CRDT safety:** every distance write stamps a real `updated_at` (an empty `updated_at` loses the LWW merge).
- **Working dirs:** backend `cd /Users/raviwu/personal/locwarp/backend` then `.venv/bin/python -m pytest <args>`; frontend `cd /Users/raviwu/personal/locwarp/frontend` then `npx vitest run <args>` / `npx tsc --noEmit` / `npm run depcruise`.
- **Git:** identity is auto-set by the repo includeIf — NEVER pass `-c user.email=...`. End every commit message with the two trailers shown in the commit steps. Stage only the files each task names.

---

### Task 1: SavedRoute distance fields + pure domain helpers

**Files:**
- Modify: `backend/models/schemas.py` (SavedRoute, after the `timestamps` field ~line 218)
- Create: `backend/domain/route_distance.py`
- Test: `backend/tests/test_route_distance_domain.py`

**Interfaces:**
- Consumes: `RouteInterpolator.haversine` (`domain/movement.py`), `Coordinate` (`models/schemas.py`).
- Produces (later tasks rely on these):
  - SavedRoute fields: `straight_distance_m: float | None`, `road_distance_m: float | None`, `road_distance_status: str` (default `"pending"`), `dist_fingerprint: str`.
  - `straight_line_distance_m(waypoints: list[Coordinate]) -> float`
  - `route_distance_fingerprint(waypoints: list[Coordinate], profile: str) -> str`
  - `decimate_waypoints(waypoints: list, max_n: int) -> list` (keeps endpoints, evenly samples to ≤ max_n)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_route_distance_domain.py`:

```python
from domain.route_distance import (
    straight_line_distance_m,
    route_distance_fingerprint,
    decimate_waypoints,
)
from models.schemas import Coordinate


def _wp(lat, lng):
    return Coordinate(lat=lat, lng=lng)


def test_straight_line_distance_sums_haversine():
    # 0/1 waypoint -> 0.0
    assert straight_line_distance_m([]) == 0.0
    assert straight_line_distance_m([_wp(25.0, 121.0)]) == 0.0
    # Two points ~157 km apart (1 deg lat ~111 km, plus lng) -> positive, sane
    d = straight_line_distance_m([_wp(25.0, 121.0), _wp(26.0, 122.0)])
    assert 100_000 < d < 200_000


def test_fingerprint_stable_and_path_sensitive():
    a = [_wp(25.0, 121.0), _wp(26.0, 122.0)]
    assert route_distance_fingerprint(a, "walking") == route_distance_fingerprint(a, "walking")
    # profile change flips it
    assert route_distance_fingerprint(a, "walking") != route_distance_fingerprint(a, "driving")
    # waypoint move flips it
    b = [_wp(25.0, 121.0), _wp(26.1, 122.0)]
    assert route_distance_fingerprint(a, "walking") != route_distance_fingerprint(b, "walking")


def test_decimate_keeps_endpoints_and_caps_count():
    pts = [_wp(0.0, float(i)) for i in range(100)]
    out = decimate_waypoints(pts, 25)
    assert len(out) <= 25
    assert out[0] is pts[0] and out[-1] is pts[-1]
    # short routes pass through unchanged
    short = [_wp(0.0, 0.0), _wp(0.0, 1.0)]
    assert decimate_waypoints(short, 25) == short
    # degenerate max_n guard -> returns all
    assert decimate_waypoints(pts, 1) == pts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_distance_domain.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'domain.route_distance'`.

- [ ] **Step 3: Create the pure domain module**

Create `backend/domain/route_distance.py`:

```python
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
```

- [ ] **Step 4: Add the SavedRoute fields**

In `backend/models/schemas.py`, inside `class SavedRoute`, immediately AFTER the `timestamps: list[float] = []` field, add:

```python
    # Cached distance preview (additive; legacy routes.json loads with the
    # defaults). straight = inline haversine sum; road = exact routed total
    # (None until status == 'ok'); status replaces an overloaded None so
    # "pending" and "unavailable" are distinguishable; fingerprint = staleness
    # signal (hash of waypoints + profile).
    straight_distance_m: float | None = None
    road_distance_m: float | None = None
    road_distance_status: str = "pending"  # 'pending' | 'ok' | 'unavailable'
    dist_fingerprint: str = ""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_distance_domain.py -q`
Expected: PASS — 3 tests.

- [ ] **Step 6: Confirm the full suite still collects + passes**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q`
Expected: all green (baseline 1074 + 3 new). No collection errors from the schema change.

- [ ] **Step 7: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/models/schemas.py backend/domain/route_distance.py backend/tests/test_route_distance_domain.py
git commit -m "feat(route): SavedRoute distance fields + pure distance helpers

Additive straight/road/status/fingerprint fields on SavedRoute, plus a pure
domain module: straight_line_distance_m (haversine sum), route_distance_fingerprint
(staleness hash), decimate_waypoints (cap road-request coords). Domain ring only.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

### Task 2: Engine config (FOSSGIS default) + X-Client-Id header

**Files:**
- Modify: `backend/config.py` (route engine block ~line 107-128)
- Modify: `backend/services/route_service.py` (`_fetch_osrm` ~line 254-298; add a pure header helper)
- Test: `backend/tests/test_route_engine_config.py`

**Interfaces:**
- Produces: `config.DEFAULT_ROUTE_ENGINE == config.ROUTE_ENGINE_OSRM_FOSSGIS`; `config.ROAD_MAX_WAYPOINTS: int`, `config.ROAD_COMPUTE_TIMEOUT_S: float`, `config.ROAD_RETRY_BACKOFF_S: tuple[float, ...]` (consumed by Task 3 + Task 5); `route_service._osrm_headers(engine) -> dict`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_route_engine_config.py`:

```python
import config
from services.route_service import _osrm_headers


def test_default_engine_is_fossgis_not_demo():
    assert config.DEFAULT_ROUTE_ENGINE == config.ROUTE_ENGINE_OSRM_FOSSGIS
    assert config.DEFAULT_ROUTE_ENGINE != config.ROUTE_ENGINE_OSRM


def test_road_compute_tunables_present():
    assert isinstance(config.ROAD_MAX_WAYPOINTS, int) and config.ROAD_MAX_WAYPOINTS >= 2
    assert config.ROAD_COMPUTE_TIMEOUT_S > 0
    assert len(config.ROAD_RETRY_BACKOFF_S) >= 1


def test_fossgis_requests_carry_x_client_id():
    assert _osrm_headers(config.ROUTE_ENGINE_OSRM_FOSSGIS) == {"X-Client-Id": "LocWarp"}
    # the no-SLA demo path adds no identifying header
    assert _osrm_headers(config.ROUTE_ENGINE_OSRM) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_engine_config.py -q`
Expected: FAIL — `ImportError: cannot import name '_osrm_headers'` (and the default-engine assertion would fail).

- [ ] **Step 3: Update config**

In `backend/config.py`, change the default engine line (currently `DEFAULT_ROUTE_ENGINE = ROUTE_ENGINE_OSRM` ~line 125) to:

```python
# Default to the FOSSGIS-hosted OSRM (production-oriented, fair-use policy)
# rather than the public OSRM *demo* server (no SLA, 1 req/s, withdrawable) —
# the demo server's flakiness was the physical trigger for the old "計算中"
# stuck bug.
DEFAULT_ROUTE_ENGINE = ROUTE_ENGINE_OSRM_FOSSGIS
```

Then, immediately AFTER the `BROUTER_BASE_URL = "https://brouter.de"` line (~line 128), add:

```python
# Deferred road-distance compute tunables (consumed by services.route_distance_service
# + the main.py startup sweep).
ROAD_MAX_WAYPOINTS = 25            # decimate longer routes before routing
ROAD_COMPUTE_TIMEOUT_S = 30.0      # outer bound on one get_multi_route attempt
ROAD_RETRY_BACKOFF_S = (2.0, 8.0)  # backoff between attempts; total attempts = len+1
```

- [ ] **Step 4: Add the header helper + wire it into the FOSSGIS request**

In `backend/services/route_service.py`, add this module-level pure helper just above `class RouteService` / the `get_route` method area (e.g. right after `_normalise_engine`, ~line 163):

```python
def _osrm_headers(engine: str) -> dict:
    """Identifying header for the FOSSGIS OSRM endpoint per its app usage
    guidance. The no-SLA demo server gets no header."""
    if engine == ROUTE_ENGINE_OSRM_FOSSGIS:
        return {"X-Client-Id": "LocWarp"}
    return {}
```

Then in `_fetch_osrm`, change the request call (currently `resp = await client.get(url)` ~line 280) to pass the header:

```python
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers=_osrm_headers(engine))
            resp.raise_for_status()
            data = resp.json()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_engine_config.py -q`
Expected: PASS — 3 tests.

- [ ] **Step 6: Confirm the full suite still passes**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q`
Expected: all green. (If any existing route_service test asserted the demo default, update it to the FOSSGIS default — that is an intended behavior change, not a regression.)

- [ ] **Step 7: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/config.py backend/services/route_service.py backend/tests/test_route_engine_config.py
git commit -m "feat(route): default to FOSSGIS OSRM + X-Client-Id; road-compute tunables

Switch DEFAULT_ROUTE_ENGINE off the no-SLA OSRM demo server to FOSSGIS
(routing.openstreetmap.de) and send an X-Client-Id header per its app policy.
Add ROAD_MAX_WAYPOINTS / ROAD_COMPUTE_TIMEOUT_S / ROAD_RETRY_BACKOFF_S tunables.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

### Task 3: Deferred road-distance orchestrator (never-stuck core)

**Files:**
- Create: `backend/services/route_distance_service.py`
- Test: `backend/tests/test_route_distance_service.py`

**Interfaces:**
- Consumes: `domain.route_distance.{route_distance_fingerprint, decimate_waypoints}`; `config.{ROAD_MAX_WAYPOINTS, ROAD_COMPUTE_TIMEOUT_S, ROAD_RETRY_BACKOFF_S}`; a `route_manager` with `_find_route(id)` + `_save()`; a `route_service` with `async get_multi_route(coords, profile) -> dict` (dict has `distance` or `fallback: True`); a `publisher` with `async publish((event, data))`.
- Produces: `async compute_road_distance(route_id, *, route_manager, route_service, publisher, sleep=asyncio.sleep) -> None` — ALWAYS settles the route to status `ok` or `unavailable` (never leaves `pending`) unless the route was edited/deleted under it.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_route_distance_service.py`:

```python
import asyncio
import pytest

from models.schemas import Coordinate, SavedRoute
from services.route_distance_service import compute_road_distance


class _RM:
    """Minimal route_manager stub: holds one route, records _save() calls."""
    def __init__(self, route):
        self._route = route
        self.saves = 0

    def _find_route(self, rid):
        return self._route if self._route and self._route.id == rid else None

    def _save(self):
        self.saves += 1


class _RS:
    """route_service stub returning a queued sequence of get_multi_route results.
    A result is a dict; an Exception instance is raised instead."""
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    async def get_multi_route(self, coords, profile):
        self.calls += 1
        r = self._results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class _Pub:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _route():
    return SavedRoute(id="r1", name="R", waypoints=[Coordinate(lat=25.0, lng=121.0),
                                                    Coordinate(lat=26.0, lng=122.0)],
                      profile="walking", road_distance_status="pending")


async def _noop_sleep(_):
    return None


@pytest.mark.asyncio
async def test_success_writes_ok_and_broadcasts():
    rt = _route()
    rm, rs, pub = _RM(rt), _RS([{"distance": 12345.0}]), _Pub()
    await compute_road_distance("r1", route_manager=rm, route_service=rs,
                                publisher=pub, sleep=_noop_sleep)
    assert rt.road_distance_status == "ok"
    assert rt.road_distance_m == 12345.0
    assert rt.updated_at != ""
    assert rm.saves == 1
    assert pub.events == [("routes_changed", {"reason": "distance"})]


@pytest.mark.asyncio
async def test_all_attempts_fail_writes_unavailable_not_pending():
    rt = _route()
    # 1 initial + len(backoff) retries, all fallback -> unavailable
    rm, rs, pub = _RM(rt), _RS([{"fallback": True}] * 5), _Pub()
    await compute_road_distance("r1", route_manager=rm, route_service=rs,
                                publisher=pub, sleep=_noop_sleep)
    assert rt.road_distance_status == "unavailable"
    assert rt.road_distance_m is None
    assert rm.saves == 1
    assert pub.events == [("routes_changed", {"reason": "distance"})]


@pytest.mark.asyncio
async def test_retry_then_success():
    rt = _route()
    rm, rs, pub = _RM(rt), _RS([{"fallback": True}, {"distance": 999.0}]), _Pub()
    await compute_road_distance("r1", route_manager=rm, route_service=rs,
                                publisher=pub, sleep=_noop_sleep)
    assert rt.road_distance_status == "ok" and rt.road_distance_m == 999.0
    assert rs.calls == 2


@pytest.mark.asyncio
async def test_exception_attempt_counts_as_failure():
    rt = _route()
    rm, rs, pub = _RM(rt), _RS([ValueError("bad json"), {"distance": 5.0}]), _Pub()
    await compute_road_distance("r1", route_manager=rm, route_service=rs,
                                publisher=pub, sleep=_noop_sleep)
    assert rt.road_distance_status == "ok" and rt.road_distance_m == 5.0


@pytest.mark.asyncio
async def test_path_changed_under_us_discards_result():
    rt = _route()
    rm, rs, pub = _RM(rt), _RS([{"distance": 12345.0}]), _Pub()

    # Mutate the route's path AFTER the fingerprint is captured but before the
    # write, by swapping get_multi_route to also edit the route.
    orig = rs.get_multi_route
    async def _editing(coords, profile):
        rt.waypoints = [Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)]
        return await orig(coords, profile)
    rs.get_multi_route = _editing

    await compute_road_distance("r1", route_manager=rm, route_service=rs,
                                publisher=pub, sleep=_noop_sleep)
    assert rt.road_distance_status == "pending"  # untouched
    assert rm.saves == 0 and pub.events == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_distance_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.route_distance_service'`.

- [ ] **Step 3: Create the orchestrator**

Create `backend/services/route_distance_service.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_distance_service.py -q`
Expected: PASS — 5 tests. (If `pytest-asyncio` needs an explicit mode, the repo already runs async tests — match the existing `@pytest.mark.asyncio` usage in `backend/tests/`.)

- [ ] **Step 5: Confirm import-linter still passes**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q && .venv/bin/lint-imports`
Expected: full suite green; import contracts `7 kept, 0 broken` (the service imports only `config` + `domain`, never `api`).

- [ ] **Step 6: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/services/route_distance_service.py backend/tests/test_route_distance_service.py
git commit -m "feat(route): deferred road-distance orchestrator (always-terminal state)

Single multi-waypoint request via get_multi_route, decimated, with bounded
retry. ALWAYS writes a terminal road_distance_status (ok|unavailable) + a
routes_changed broadcast — never leaves a route 'pending' (kills the old 計算中
stuck bug). Staleness-guards its write so a racing edit is not clobbered.
Publisher injected (no api import). Never-stuck invariants tested.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

### Task 4: API wiring — stamp + spawn on save / replace / GPX / import

**Files:**
- Modify: `backend/api/route.py`
- Test: `backend/tests/test_route_distance_api.py`

**Interfaces:**
- Consumes: `domain.route_distance.{straight_line_distance_m, route_distance_fingerprint}`; `services.route_distance_service.compute_road_distance`; the existing `get_event_publisher` dep (`api/deps.py:63`) for the injected publisher; `get_route_service`, `get_route_manager`.
- Produces: every route create / replace / GPX-import / bulk-import path stamps straight + fingerprint + `road_distance_status="pending"` before the store save, then spawns the deferred road compute. **Bulk import is wired (fixes the C4 gap).**

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_route_distance_api.py`:

```python
import asyncio
import pytest

import api.route as route_api
from models.schemas import Coordinate, SavedRoute


class _RM:
    def __init__(self):
        self.routes = []

    def create_route(self, route):
        route.id = route.id or "rid"
        self.routes.append(route)
        return route

    def list_routes(self):
        return self.routes


@pytest.mark.asyncio
async def test_stamp_sets_straight_fingerprint_pending():
    route = SavedRoute(name="R", waypoints=[Coordinate(lat=25.0, lng=121.0),
                                            Coordinate(lat=26.0, lng=122.0)],
                       profile="walking")
    route_api._stamp_distance_fields(route)
    assert route.straight_distance_m is not None and route.straight_distance_m > 0
    assert route.dist_fingerprint != ""
    assert route.road_distance_m is None
    assert route.road_distance_status == "pending"


@pytest.mark.asyncio
async def test_save_route_stamps_and_spawns(monkeypatch):
    spawned = []
    monkeypatch.setattr(route_api, "_spawn", lambda coro: spawned.append(coro) or coro.close())
    rm = _RM()
    route = SavedRoute(name="R", waypoints=[Coordinate(lat=25.0, lng=121.0),
                                            Coordinate(lat=26.0, lng=122.0)],
                       profile="walking")
    saved = await route_api.save_route(route, rm=rm, route_service=object(), publisher=object())
    assert saved.road_distance_status == "pending"
    assert saved.straight_distance_m is not None
    assert len(spawned) == 1  # a road compute was scheduled


@pytest.mark.asyncio
async def test_bulk_import_spawns_for_pending_routes(monkeypatch):
    spawned = []
    monkeypatch.setattr(route_api, "_spawn", lambda coro: spawned.append(coro) or coro.close())

    class _ImportRM(_RM):
        def import_json(self, data):
            # Simulate the store landing two pending imported routes.
            self.routes = [
                SavedRoute(id="a", name="A",
                           waypoints=[Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)],
                           road_distance_status="pending"),
                SavedRoute(id="b", name="B",
                           waypoints=[Coordinate(lat=3.0, lng=3.0), Coordinate(lat=4.0, lng=4.0)],
                           road_distance_status="ok", road_distance_m=1.0),
            ]
            return 2

    rm = _ImportRM()
    body = route_api._RouteImportBody(routes=[], categories=[])
    res = await route_api.import_all_saved_routes(body, rm=rm, route_service=object(), publisher=object())
    assert res == {"imported": 2}
    assert len(spawned) == 1  # only the 'pending' route 'a' is scheduled, not the 'ok' one
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_distance_api.py -q`
Expected: FAIL — `AttributeError: module 'api.route' has no attribute '_stamp_distance_fields'`.

- [ ] **Step 3: Add imports + helpers to `api/route.py`**

In `backend/api/route.py`, extend the imports. Change the top import block:

```python
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from api.deps import (
    get_event_publisher,
    get_gpx_service,
    get_route_manager,
    get_route_service,
)
from domain.route_distance import route_distance_fingerprint, straight_line_distance_m
from models.schemas import (
    Coordinate,
    RouteCategory,
    RouteMoveRequest,
    RoutePlanRequest,
    SavedRoute,
)
from services.route_distance_service import compute_road_distance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/route", tags=["route"])

# Strong refs so a fire-and-forget road-distance compute is not GC'd
# mid-flight (asyncio keeps only weak refs). Mirrors api/location.py:_spawn.
_bg_tasks: set = set()


def _spawn(coro):
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)

    def _on_done(t):
        _bg_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.exception("route bg task crashed: %s", exc, exc_info=exc)

    task.add_done_callback(_on_done)
    return task


def _stamp_distance_fields(route: SavedRoute) -> None:
    """Fill straight_distance_m + dist_fingerprint, reset road to pending, BEFORE
    the store mutation so the single _save() persists the correct values with no
    intermediate stale-distance window."""
    route.straight_distance_m = straight_line_distance_m(route.waypoints)
    route.dist_fingerprint = route_distance_fingerprint(route.waypoints, route.profile)
    route.road_distance_m = None
    route.road_distance_status = "pending"


def _spawn_road_compute(saved: SavedRoute, rm, route_service, publisher) -> None:
    _spawn(compute_road_distance(
        saved.id, route_manager=rm, route_service=route_service, publisher=publisher,
    ))
```

- [ ] **Step 4: Wire save / replace into the handlers**

Replace `save_route` and `replace_saved` (current lines 37-53) with:

```python
@router.post("/saved", response_model=SavedRoute)
async def save_route(route: SavedRoute, rm=Depends(get_route_manager),
                     route_service=Depends(get_route_service),
                     publisher=Depends(get_event_publisher)):
    _stamp_distance_fields(route)
    saved = rm.create_route(route)
    _spawn_road_compute(saved, rm, route_service, publisher)
    return saved


@router.put("/saved/{route_id}", response_model=SavedRoute)
async def replace_saved(route_id: str, route: SavedRoute, rm=Depends(get_route_manager),
                        route_service=Depends(get_route_service),
                        publisher=Depends(get_event_publisher)):
    """Overwrite an existing saved route's payload. The path changed, so the
    straight distance is recomputed inline and the road distance is recomputed
    deferred."""
    _stamp_distance_fields(route)
    updated = rm.replace_route(route_id, route)
    if updated is None:
        raise HTTPException(status_code=404, detail="Route not found")
    _spawn_road_compute(updated, rm, route_service, publisher)
    return updated
```

- [ ] **Step 5: Wire bulk import + GPX import**

Replace `import_all_saved_routes` (current lines 100-108) with:

```python
@router.post("/saved/import")
async def import_all_saved_routes(body: _RouteImportBody, rm=Depends(get_route_manager),
                                  route_service=Depends(get_route_service),
                                  publisher=Depends(get_event_publisher)):
    import json as _json
    # Stamp straight + fingerprint + pending on each incoming route so the
    # imported records persist correct values; the store still applies its own
    # id/name-collision rules.
    for r in body.routes:
        _stamp_distance_fields(r)
    payload = _json.dumps({
        "routes": [r.model_dump(mode="json") for r in body.routes],
        "categories": [c.model_dump(mode="json") for c in body.categories],
    })
    imported = rm.import_json(payload)
    # Spawn a road compute for every route that still needs one (the freshly
    # imported pending routes, plus any older pending/failed ones — self-heal).
    for r in rm.list_routes():
        if r.road_distance_status != "ok":
            _spawn_road_compute(r, rm, route_service, publisher)
    return {"imported": imported}
```

Replace the `import_gpx` handler signature + body (current lines 142-156) with:

```python
@router.post("/gpx/import")
async def import_gpx(file: UploadFile = File(...), rm=Depends(get_route_manager),
                     gpx_service=Depends(get_gpx_service),
                     route_service=Depends(get_route_service),
                     publisher=Depends(get_event_publisher)):
    content = await file.read()
    text = content.decode("utf-8")
    coords, offsets = gpx_service.parse_gpx_timed(text)
    raw_name = file.filename or "Imported GPX"
    base_name = raw_name.rsplit(".", 1)[0] if raw_name.lower().endswith(".gpx") else raw_name
    route = SavedRoute(
        name=base_name or "Imported GPX",
        waypoints=coords,
        profile="walking",
        timestamps=offsets,
    )
    _stamp_distance_fields(route)
    saved = rm.create_route(route)
    _spawn_road_compute(saved, rm, route_service, publisher)
    return {"status": "imported", "id": saved.id, "points": len(coords)}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_distance_api.py -q`
Expected: PASS — 3 tests.

- [ ] **Step 7: Confirm the full suite + import-linter pass**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q && .venv/bin/lint-imports`
Expected: all green; `7 kept, 0 broken`.

- [ ] **Step 8: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/api/route.py backend/tests/test_route_distance_api.py
git commit -m "feat(route): stamp distances + spawn road compute on save/replace/gpx/import

Every route mutation stamps straight + fingerprint + status=pending before the
single store save, then fires the deferred road compute. Bulk import is now
wired too (was the C4 stuck gap). Publisher injected via get_event_publisher.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

### Task 5: Lifespan startup sweep + watcher recompute

**Files:**
- Modify: `backend/main.py` (add `_run_route_distance_sweep`; spawn it in `lifespan`; recompute in `_on_route_change`)
- Test: `backend/tests/test_route_distance_sweep.py`

**Interfaces:**
- Consumes: `domain.route_distance.{route_distance_fingerprint, straight_line_distance_m}`; `services.route_distance_service.compute_road_distance`; `bootstrap.runtime.get_container` (for `route_service` + `event_publisher`); the existing `_spawn_bg` helper (`main.py:862`) and the lifespan route watcher (`main.py:~1037-1053`).
- Produces: `async _run_route_distance_sweep(route_manager) -> None` — backfills stale routes (status != 'ok' OR fingerprint mismatch); fills straight inline (one batch save), then runs the deferred road compute per stale route.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_route_distance_sweep.py`:

```python
import asyncio
import pytest

import main as main_mod
from models.schemas import Coordinate, SavedRoute


class _Store:
    def __init__(self, routes):
        self.routes = routes


class _RM:
    def __init__(self, routes):
        self.store = _Store(routes)
        self.saves = 0

    def _find_route(self, rid):
        return next((r for r in self.store.routes if r.id == rid), None)

    def _save(self):
        self.saves += 1


class _Pub:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


class _RS:
    async def get_multi_route(self, coords, profile):
        return {"distance": 4242.0}


class _Container:
    def __init__(self, rs, pub):
        self.route_service = rs
        self.event_publisher = pub


@pytest.mark.asyncio
async def test_sweep_backfills_stale_and_skips_fresh(monkeypatch):
    fresh = SavedRoute(id="ok", name="OK",
                       waypoints=[Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)],
                       profile="walking", road_distance_status="ok", road_distance_m=1.0)
    # make the fresh route's fingerprint match so it is skipped
    from domain.route_distance import route_distance_fingerprint
    fresh.dist_fingerprint = route_distance_fingerprint(fresh.waypoints, fresh.profile)

    stale = SavedRoute(id="legacy", name="Legacy",
                       waypoints=[Coordinate(lat=3.0, lng=3.0), Coordinate(lat=4.0, lng=4.0)],
                       profile="walking")  # status defaults to 'pending', no fingerprint

    rm, pub = _RM([fresh, stale]), _Pub()
    # _run_route_distance_sweep does `from bootstrap.runtime import get_container`
    # INSIDE the function, so patch it at its source module, not on `main`.
    monkeypatch.setattr("bootstrap.runtime.get_container", lambda: _Container(_RS(), pub))

    await main_mod._run_route_distance_sweep(rm)

    assert stale.straight_distance_m is not None  # straight backfilled
    assert stale.road_distance_status == "ok" and stale.road_distance_m == 4242.0
    assert fresh.road_distance_m == 1.0  # fresh untouched value
    # at least the straight-backfill broadcast + the per-route distance broadcast
    assert ("routes_changed", {"reason": "distance_backfill"}) in pub.events
    assert ("routes_changed", {"reason": "distance"}) in pub.events
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_distance_sweep.py -q`
Expected: FAIL — `AttributeError: module 'main' has no attribute '_run_route_distance_sweep'`.

- [ ] **Step 3: Add the sweep function**

In `backend/main.py`, add this function immediately AFTER the `_spawn_bg` helper (which ends ~line 873):

```python
async def _run_route_distance_sweep(route_manager) -> None:
    """Backfill missing/stale route distances at startup and on external route
    changes. A route is stale unless road_distance_status == 'ok' AND its stored
    dist_fingerprint matches its current waypoints+profile. For each stale route:
    fill straight inline (instant, one batch _save()), then run the deferred road
    compute (which always settles to ok/unavailable + broadcasts). Re-attempting
    'unavailable' routes here makes a transient outage self-heal on the next
    restart / file change. Runs on the event loop (single-threaded → safe vs CRUD)."""
    from datetime import datetime, timezone

    from domain.route_distance import route_distance_fingerprint, straight_line_distance_m
    from services.route_distance_service import compute_road_distance
    from bootstrap.runtime import get_container

    container = get_container()
    route_service = container.route_service
    publisher = container.event_publisher
    now = datetime.now(timezone.utc).isoformat()
    stale_ids: list[str] = []
    changed_straight = False
    for r in list(route_manager.store.routes):
        fp = route_distance_fingerprint(r.waypoints, r.profile)
        if r.road_distance_status == "ok" and r.dist_fingerprint == fp:
            continue  # fresh exact value — trust the synced/computed result
        if r.dist_fingerprint != fp:
            # Path changed (legacy/synced/edited) — old road value is for the
            # old path; reset to a fresh pending state.
            r.straight_distance_m = straight_line_distance_m(r.waypoints)
            r.road_distance_m = None
            r.road_distance_status = "pending"
            r.dist_fingerprint = fp
            r.updated_at = now  # CRDT-merge-safe stamp
            changed_straight = True
        elif r.straight_distance_m is None:
            r.straight_distance_m = straight_line_distance_m(r.waypoints)
            r.updated_at = now
            changed_straight = True
        stale_ids.append(r.id)
    if changed_straight:
        route_manager._save()
        await publisher.publish(("routes_changed", {"reason": "distance_backfill"}))
    for rid in stale_ids:
        await compute_road_distance(
            rid, route_manager=route_manager, route_service=route_service, publisher=publisher,
        )
    logger.info("route-distance sweep processed %d stale route(s)", len(stale_ids))
```

- [ ] **Step 4: Run the unit test to verify it passes**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_distance_sweep.py -q`
Expected: PASS — 1 test.

- [ ] **Step 5: Spawn the sweep at startup**

In `backend/main.py`, in `lifespan`, immediately BEFORE the `_spawn_bg(_startup_autoconnect())` call (the "Startup auto-connect" block, ~line 1024), add:

```python
    # ── Deferred route-distance backfill ──
    # Legacy routes and paths synced from an old client have no cached distances.
    # Sweep them off the awaited critical path: straight fills inline, road via
    # the deferred orchestrator (always settling ok/unavailable + broadcast).
    if app_state.route_manager is not None:
        _spawn_bg(_run_route_distance_sweep(app_state.route_manager))
```

- [ ] **Step 6: Recompute on external route change**

In `backend/main.py`, find `_on_route_change` (the route watcher callback in `lifespan`, ~line 1040, currently only `run_coroutine_threadsafe(_bc("routes_changed", {"reason": "external_update"}), loop)`). Replace it with:

```python
    def _on_route_change():
        asyncio.run_coroutine_threadsafe(
            _bc("routes_changed", {"reason": "external_update"}),
            loop,
        )
        # A path synced in from a device that did not compute its distances is
        # recomputed here. The sweep fingerprint-checks every route, so this is
        # a near-no-op when nothing is stale (the common case).
        if app_state.route_manager is not None:
            _fut = asyncio.run_coroutine_threadsafe(
                _run_route_distance_sweep(app_state.route_manager),
                loop,
            )
            _fut.add_done_callback(
                lambda f: f.exception() and logger.error(
                    "route-distance watcher sweep failed: %s", f.exception()
                )
            )
```

- [ ] **Step 7: Confirm the full suite + import-linter pass**

Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q && .venv/bin/lint-imports`
Expected: all green; `7 kept, 0 broken`.

- [ ] **Step 8: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/main.py backend/tests/test_route_distance_sweep.py
git commit -m "feat(route): startup + watcher route-distance sweep (self-healing backfill)

Backfill stale routes (status != ok or fingerprint mismatch) off the boot
critical path: straight inline, road deferred. Re-attempting 'unavailable'
routes makes a transient routing outage self-heal on the next restart / file
change. Wired into lifespan + the external-route-change watcher.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

### Task 6: Frontend — road estimate util + RouteList distance badges

**Files:**
- Create: `frontend/src/utils/roadEstimate.ts`
- Create: `frontend/src/utils/roadEstimate.test.ts`
- Modify: `frontend/src/components/RouteList.tsx` (SavedRoute interface ~line 13; add `formatKm` + badges in `renderRouteRow` ~line 1122)
- Test: `frontend/src/components/RouteList.test.tsx` (add a `describe` block)

**Interfaces:**
- Produces: `roadEstimateM(straightM: number, profile?: string): number` (straight × detour factor).

- [ ] **Step 1: Write the failing util test**

Create `frontend/src/utils/roadEstimate.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { roadEstimateM } from './roadEstimate'

describe('roadEstimateM', () => {
  it('applies a per-profile detour factor', () => {
    expect(roadEstimateM(1000, 'driving')).toBe(1400)
    expect(roadEstimateM(1000, 'walking')).toBe(1300)
    expect(roadEstimateM(1000, 'cycling')).toBe(1350)
  })
  it('maps engine-profile aliases', () => {
    expect(roadEstimateM(1000, 'car')).toBe(1400)
    expect(roadEstimateM(1000, 'foot')).toBe(1300)
    expect(roadEstimateM(1000, 'running')).toBe(1300)
  })
  it('defaults to 1.4 for unknown/absent profile', () => {
    expect(roadEstimateM(1000, undefined)).toBe(1400)
    expect(roadEstimateM(1000, 'spaceship')).toBe(1400)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/utils/roadEstimate.test.ts`
Expected: FAIL — cannot resolve `./roadEstimate`.

- [ ] **Step 3: Create the util**

Create `frontend/src/utils/roadEstimate.ts`:

```ts
// Client-side road-distance estimate: straight-line meters × a per-profile
// detour factor. Shown as "≈" while the exact routed value is pending or
// unavailable, so the road badge is never blank and never shows a spinner.
const DETOUR_FACTORS: Record<string, number> = {
  driving: 1.4, car: 1.4,
  walking: 1.3, foot: 1.3, running: 1.3,
  cycling: 1.35, bike: 1.35,
};
const DEFAULT_FACTOR = 1.4;

export function roadEstimateM(straightM: number, profile?: string): number {
  const factor = (profile && DETOUR_FACTORS[profile]) || DEFAULT_FACTOR;
  return straightM * factor;
}
```

- [ ] **Step 4: Run the util test to verify it passes**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/utils/roadEstimate.test.ts`
Expected: PASS — 3 tests.

- [ ] **Step 5: Extend the frontend SavedRoute type**

In `frontend/src/components/RouteList.tsx`, inside `export interface SavedRoute` (after the `timestamps?: number[];` field, ~line 24), add:

```ts
  // Cached distance preview (backend-populated). Road exact value present only
  // when road_distance_status === 'ok'; otherwise the UI shows a ≈ estimate.
  straight_distance_m?: number | null;
  road_distance_m?: number | null;
  road_distance_status?: 'pending' | 'ok' | 'unavailable';
  dist_fingerprint?: string;
```

- [ ] **Step 6: Add `formatKm` + the badges**

In `frontend/src/components/RouteList.tsx`, add the import near the other `../utils/...` imports at the top:

```ts
import { roadEstimateM } from '../utils/roadEstimate';
```

Add the `formatKm` helper just above the `const COLOR_PALETTE` declaration (~line 61):

```ts
// Meters -> "X.XX km".
function formatKm(meters: number): string {
  return `${(meters / 1000).toFixed(2)} km`;
}
```

Then in `renderRouteRow`, replace the meta `<span>` (currently lines ~1122-1125):

```tsx
            <span style={{ fontSize: 10, opacity: 0.5, fontFamily: 'monospace' }}>
              {route.waypoints.length} {t('route.points_unit')}
              {route.profile ? ` · ${route.profile}` : ''}
            </span>
```

with (adds the two distance badges; road is exact when `ok`, else a `≈` estimate — never "計算中"):

```tsx
            <span style={{ fontSize: 10, opacity: 0.5, fontFamily: 'monospace' }}>
              {route.waypoints.length} {t('route.points_unit')}
              {route.profile ? ` · ${route.profile}` : ''}
              {route.straight_distance_m != null
                ? ` · 直線 ${formatKm(route.straight_distance_m)}`
                : ''}
              {route.straight_distance_m != null
                ? (route.road_distance_m != null && route.road_distance_status === 'ok'
                    ? ` · 沿路 ${formatKm(route.road_distance_m)}`
                    : ` · 沿路 ≈ ${formatKm(roadEstimateM(route.straight_distance_m, route.profile))}`)
                : ''}
            </span>
```

- [ ] **Step 7: Write the failing RouteList badge test**

Append to `frontend/src/components/RouteList.test.tsx` a new `describe` block (use the file's existing render/props helpers; pass routes via the `routes` prop):

```tsx
describe('RouteList distance badges', () => {
  function routeWith(over: any) {
    return {
      id: 'r1', name: 'Route 1',
      waypoints: [{ lat: 25, lng: 121 }, { lat: 26, lng: 122 }],
      profile: 'walking', category_id: 'default',
      ...over,
    };
  }

  it('shows the exact 沿路 value when status is ok', () => {
    renderRouteList(makeProps({ routes: [routeWith({
      straight_distance_m: 10000, road_distance_m: 12000, road_distance_status: 'ok',
    })] }));
    expect(screen.getByText(/直線 10\.00 km/)).toBeInTheDocument();
    expect(screen.getByText(/沿路 12\.00 km/)).toBeInTheDocument();
    expect(screen.queryByText(/計算中/)).toBeNull();
    expect(screen.queryByText(/≈/)).toBeNull();
  });

  it('shows a ≈ estimate (never 計算中) while road is pending', () => {
    renderRouteList(makeProps({ routes: [routeWith({
      straight_distance_m: 10000, road_distance_m: null, road_distance_status: 'pending',
    })] }));
    // walking factor 1.3 -> 13.00 km
    expect(screen.getByText(/沿路 ≈ 13\.00 km/)).toBeInTheDocument();
    expect(screen.queryByText(/計算中/)).toBeNull();
  });

  it('shows a ≈ estimate when road is unavailable', () => {
    renderRouteList(makeProps({ routes: [routeWith({
      straight_distance_m: 10000, road_distance_m: null, road_distance_status: 'unavailable',
    })] }));
    expect(screen.getByText(/沿路 ≈ 13\.00 km/)).toBeInTheDocument();
    expect(screen.queryByText(/計算中/)).toBeNull();
  });
});
```

> Implementer note: open `RouteList.test.tsx` and reuse its existing render helper + `makeProps` (named as in that file — e.g. a `renderRouteList(...)`/`render(...)` wrapper and a props factory). Match the existing import of `screen` from `@testing-library/react`. If routes must be expanded to render rows, follow the file's existing expand pattern.

- [ ] **Step 8: Run the RouteList tests + tsc**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/RouteList.test.tsx src/utils/roadEstimate.test.ts && npx tsc --noEmit`
Expected: PASS (incl. the 3 new badge tests); tsc clean.

- [ ] **Step 9: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/utils/roadEstimate.ts frontend/src/utils/roadEstimate.test.ts frontend/src/components/RouteList.tsx frontend/src/components/RouteList.test.tsx
git commit -m "feat(route): RouteList 直線/沿路 badges with ≈ estimate (never 計算中)

Road badge shows the exact routed km when road_distance_status==='ok', else a
client-side ≈ estimate (straight × profile detour factor). The 計算中 spinner
string is gone entirely. New roadEstimate util.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

### Task 7: Frontend resilience — reconnect re-fetch + refresh retry

**Files:**
- Modify: `frontend/src/hooks/useRoutes.ts` (`refreshSavedRoutes` ~line 28-33)
- Modify: `frontend/src/App.tsx` (add a WS reconnect catch-up effect near the `useExternalChangeSubscriptions` call ~line 199)
- Test: `frontend/src/hooks/useRoutes.test.ts` (or co-located) for the refresh retry

**Interfaces:**
- Consumes: `useWebSocket()`'s `connected` boolean (already returned, `useWebSocket.ts:126`), `onRoutesChanged` / `onBookmarksChanged` (already defined in App).

- [ ] **Step 1: Write the failing refresh-retry test**

Create `frontend/src/hooks/useRoutes.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useRoutes } from './useRoutes'

function makeApi(getSavedRoutes: any) {
  return {
    getSavedRoutes,
    getRouteCategories: vi.fn().mockResolvedValue([]),
  } as any
}

describe('useRoutes refresh resilience', () => {
  it('retries getSavedRoutes once on a transient failure, then sets routes', async () => {
    const rs = [{ id: 'a', name: 'A', waypoints: [] }]
    const getSavedRoutes = vi.fn()
      .mockResolvedValueOnce([])            // initial mount load
      .mockRejectedValueOnce(new Error('net'))  // first refresh attempt fails
      .mockResolvedValueOnce(rs)            // retry succeeds
    const { result } = renderHook(() => useRoutes(makeApi(getSavedRoutes)))
    await act(async () => { await result.current.refresh() })
    await waitFor(() => expect(result.current.savedRoutes).toEqual(rs))
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useRoutes.test.ts`
Expected: FAIL — current `refreshSavedRoutes` swallows the rejection and never retries, so `savedRoutes` stays `[]`.

- [ ] **Step 3: Add the retry to `refreshSavedRoutes`**

In `frontend/src/hooks/useRoutes.ts`, replace `refreshSavedRoutes` (lines ~28-33):

```ts
  const refreshSavedRoutes = useCallback(async () => {
    try {
      const rs = await api.getSavedRoutes()
      if (mountedRef.current) setSavedRoutes(rs)
    } catch { /* swallow */ }
  }, [api])
```

with a one-retry version (so a transient HTTP blip on a routes_changed re-fetch does not silently leave a stale "≈"/old value):

```ts
  const refreshSavedRoutes = useCallback(async () => {
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const rs = await api.getSavedRoutes()
        if (mountedRef.current) setSavedRoutes(rs)
        return
      } catch {
        if (attempt === 0) await new Promise((r) => setTimeout(r, 400))
      }
    }
    // both attempts failed — leave the last good state; a later
    // routes_changed or the reconnect catch-up will refresh again.
  }, [api])
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useRoutes.test.ts`
Expected: PASS.

- [ ] **Step 5: Add the WS reconnect catch-up effect**

In `frontend/src/App.tsx`, just after the `useExternalChangeSubscriptions(...)` call (~line 199), add a reconnect catch-up effect. (`connected` comes from the existing `useWebSocket()` usage in App; if it is not already destructured in scope, read it from the same hook result that feeds the router.)

```tsx
  // WS reconnect catch-up: a routes_changed / bookmarks_changed broadcast that
  // fired while the socket was down is lost (no server replay). On a
  // disconnected→connected transition, re-fetch so a distance computed during
  // the outage is not stuck behind a missed broadcast. Skips the initial
  // connect (the mount-time load already fetched).
  const wasConnectedRef = useRef(false);
  useEffect(() => {
    if (connected && wasConnectedRef.current === false) {
      // first connect — just record it, the mount load already ran
      wasConnectedRef.current = true;
      return;
    }
    if (connected && wasConnectedRef.current) {
      onRoutesChanged();
      onBookmarksChanged();
    }
    if (!connected) wasConnectedRef.current = true;
  }, [connected, onRoutesChanged, onBookmarksChanged]);
```

> Implementer note: confirm `connected` is in scope in App (from `useWebSocket()`); if App currently only keeps the router, also destructure `connected` from the same hook call. Ensure `useEffect` / `useRef` are imported (App already imports React hooks). If `onBookmarksChanged` is not in scope at this point, call only `onRoutesChanged()` — the route distance is the feature under change.

- [ ] **Step 6: Run frontend gates**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run && npm run depcruise`
Expected: tsc clean; all vitest green; depcruise `0 errors`.

- [ ] **Step 7: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/hooks/useRoutes.ts frontend/src/hooks/useRoutes.test.ts frontend/src/App.tsx
git commit -m "fix(route): WS reconnect re-fetch + refresh retry (no dropped-broadcast stick)

refreshSavedRoutes retries once on a transient HTTP failure instead of
swallowing it; App re-fetches on a disconnected→connected WS transition so a
distance computed during an outage is not stuck behind a missed routes_changed.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

## Self-Review Notes (for the implementer)

- **The never-stuck guarantee lives in Task 3:** `compute_road_distance` always settles to `ok` or `unavailable` and broadcasts — never returns leaving `pending`. Tasks 4/5 only *trigger* it; Task 6 makes the UI show `≈` whenever the exact value is absent. Together: no path shows a permanent "計算中".
- **Type/name consistency:** `road_distance_status` values `'pending' | 'ok' | 'unavailable'` are identical across backend (Task 1 schema, Task 3 writes, Task 5 sweep) and frontend (Task 6 type + badge). `get_multi_route` road meters = `result["distance"]`, guarded by `result.get("fallback")`.
- **Engine behavior change is intended:** Task 2 flips the default to FOSSGIS; if a pre-existing test asserts the demo default, update it (call it out to the reviewer as intended, not a silent test edit).
- **Decimation makes long-route road distance approximate** — by design (the spec's accepted tradeoff). The straight distance always uses all waypoints.
