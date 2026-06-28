# Route Distance Estimate (直線 + 沿路) — Redesign

**Date:** 2026-06-28
**Status:** Approved (pending spec review)
**Area:** Backend route service + frontend RouteList. Frontend display + backend compute; no new HTTP endpoint.

## Goal

When a route is added (or edited / imported), show two total-distance figures efficiently and **without ever getting stuck on a "計算中" spinner**:

1. **直線 (straight-line)** — sum of haversine over the waypoints. Instant, pure, never fails.
2. **沿路 (road-following)** — total routed distance from an external routing engine. Computed in the background; the UI shows a labeled estimate (`≈`) immediately and replaces it with the exact value when it arrives.

The road badge always shows a number — the exact routed value when available, otherwise a `≈` estimate. The string "計算中" is removed entirely.

## Why a redesign — the "計算中" stuck root cause

A prior implementation (abandoned, orphan commit `9846759`) left the road badge stuck on "計算中" indefinitely. A code-verified investigation found:

- **C1 (dominant):** road distance was computed as N-1 **sequential** HTTP calls to the **public OSRM demo server** (`router.project-osrm.org`, no SLA, **1 req/s** limit). Any one leg that timed out / was rate-limited / 5xx'd fell back to straight-line, which made the whole-route `plan_full_distance` return `None` (`route_service.py:247-250`). The deferred writer then **early-returned with no write, no broadcast, no failure sentinel** (`route_distance_service.py:58-61`). `road_distance_m` stayed `None` forever.
- **C2:** no in-session retry — single-shot per save; recovery only on restart or an iCloud file-change sweep.
- **C3:** `None` was overloaded ("never computed" = "in flight" = "failed"); the frontend mapped both `null` and `undefined` to "計算中…" (`RouteList.tsx:1138`). A permanent failure looked identical to a pending compute.
- **C4:** bulk import (`api/route.py:153-161`) never stamped distances nor spawned the compute — freshly imported routes sat at "計算中" with nothing computing them.
- **C5:** the frontend never re-fetched on WS reconnect, and `refreshSavedRoutes` swallowed a failed re-fetch — a `routes_changed` broadcast dropped during a disconnect was never replayed.

**Refuted (do not chase):** the CRDT empty-`updated_at` tombstone pitfall (all distance writes already stamp a real timestamp); a per-leg hang (every request has an 8s httpx timeout).

The fix attacks all of these: an always-resolving compute contract, an explicit status, an instant `≈` placeholder so the UI is never blank, a reliable default engine, and frontend catch-up.

## Decisions (approved)

| Decision | Choice |
|---|---|
| Pending / unavailable display | **Instant `≈` estimate, refined to exact in background.** Never blank, never "計算中". |
| Routing engine default | **Switch `osrm` (demo) → `osrm_fossgis`** (FOSSGIS `routing.openstreetmap.de`), with an `X-Client-Id` header. |
| Road request shape | **One multi-waypoint request** (`route_service.get_multi_route`), not N-1 per-leg calls. |
| Long routes | **Decimate / sample waypoints** before the road request. |
| Status field | Add explicit `road_distance_status: 'pending' \| 'ok' \| 'unavailable'`. |

## Existing surface to reuse (no duplication)

- The route HTTP surface is 15 endpoints under `/api/route` (`backend/api/route.py`). **No new endpoint** — distances are stamped inside the existing create / replace / GPX / import handlers.
- The only route WS event is `routes_changed` with a `reason` payload. Off-event-loop broadcasts must go through `run_coroutine_threadsafe` (the watcher does this at `main.py:410`); the deferred compute runs on the loop and awaits the injected publisher in-line.
- **The route service already supports four engines** (`config.py:115-128`): `osrm`, `osrm_fossgis`, `valhalla`, `brouter`, each fully wired in `route_service.py`. Engine selection is config-level (`DEFAULT_ROUTE_ENGINE`). `get_multi_route(waypoints, profile, engine)` (`route_service.py:197`) already issues **one** request for all waypoints.
- Haversine: `RouteInterpolator.haversine` (`domain/movement.py:163`) — pure, synchronous, the single source of truth. Reuse it; do not re-implement.
- The CRDT-safe write pattern: `force_seed_items` on import (`route_store.py`), and stamping a real `updated_at` before `_save()`.

## Data model

Add four additive, optional fields to `SavedRoute` (`backend/models/schemas.py`) — defaults keep legacy `routes.json` loading:

```python
straight_distance_m: float | None = None      # inline haversine sum; instant
road_distance_m: float | None = None          # exact routed total; None until 'ok'
road_distance_status: str = "pending"          # 'pending' | 'ok' | 'unavailable'
dist_fingerprint: str = ""                     # hash(waypoints + profile)
```

- `road_distance_status` replaces the overloaded `None` (fixes C3). The backend uses it to decide retries; the UI does **not** depend on it (it shows exact-vs-estimate from `road_distance_m`).
- `dist_fingerprint` drives staleness: `""` (legacy / fresh import) and a mismatch both count as stale.

## Routing engine

- **Default → FOSSGIS OSRM.** `config.py:125` `DEFAULT_ROUTE_ENGINE = ROUTE_ENGINE_OSRM` → `ROUTE_ENGINE_OSRM_FOSSGIS`. FOSSGIS (`routing.openstreetmap.de`) runs the same OSRM software (the `osrm_fossgis` path already exists in `route_service._fetch_osrm`), is production-oriented, and follows a fair-use policy — vs. the demo server's explicit "no SLA, 1 req/s, access withdrawable at any time."
- **Identify the client.** Per FOSSGIS's app guidance, send an `X-Client-Id: LocWarp` header on FOSSGIS requests (mirrors the app's existing custom-User-Agent pattern for OSM tiles). *Manual follow-up (not code): announce the app via FOSSGIS GitHub Discussions as their policy requests.*
- The single multi-waypoint request keeps request volume at **1 per route compute**, well within fair use.

Sources: [OSRM demo API usage policy](https://github.com/Project-OSRM/osrm-backend/wiki/Api-usage-policy) · [About routing.openstreetmap.de](https://routing.openstreetmap.de/about.html)

## Compute lifecycle

### Inline, on every mutation (create / replace / GPX / import)
Before the single `_save()`, stamp: `straight_distance_m` (haversine sum over **all** waypoints), `dist_fingerprint`, `road_distance_m = None`, `road_distance_status = "pending"`. Then spawn the deferred road compute (fire-and-forget `asyncio.create_task` held in a strong-ref set with an exception-logging done-callback). The HTTP response returns immediately. **Bulk import is wired the same way (fixes C4).**

### Deferred `compute_road_distance(route_id)` — always resolves to a terminal state
1. Capture the route's current `dist_fingerprint`.
2. **Decimate** waypoints to at most `ROAD_MAX_WAYPOINTS` (e.g. 25) before routing — straight distance already used all points; the road request uses the sampled set. Road distance for very long routes is therefore approximate (accepted tradeoff).
3. **Bounded retry** (e.g. 3 attempts, backoff ~2s / 8s / 30s), the whole thing under an outer `asyncio.wait_for` bound: `await get_multi_route(decimated, profile, engine)`. The result is a dict; **road meters = `result["distance"]`** (OSRM's total for the whole multi-waypoint route). **Guard:** if `result.get("fallback")` is truthy, the engine was unreachable and `result["distance"]` is a straight-line stand-in — treat that attempt as a **failure**, never store it as the road value.
4. Re-read the route; recompute the live fingerprint from its **current** waypoints. If it changed (route edited mid-compute), abort — a newer compute owns the result.
5. **Terminal write (always):**
   - Success → `road_distance_m = <meters>`, `road_distance_status = "ok"`.
   - All retries failed → `road_distance_m = None`, `road_distance_status = "unavailable"`.
   - Either way: stamp `updated_at = now()` (CRDT-safe), `_save()`, and `broadcast("routes_changed", {"reason": "distance"})`. **There is no path that leaves the route `pending` and silent** (fixes C1, C2).

### Startup + watcher sweep
Stale = `road_distance_status != "ok"` **OR** `dist_fingerprint != current_hash`. The sweep fills straight inline in one batch `_save()`, then runs `compute_road_distance` per stale route. Because `unavailable` is re-attempted on each sweep, a route that failed during a network outage **self-heals** on the next restart / file change (cheap: one bounded compute; a genuinely unroutable route simply settles back to `unavailable`). Launched at startup and on every route-file change via `run_coroutine_threadsafe`.

## Frontend

- **Road badge (`RouteList.tsx`)** — never "計算中":
  - `road_distance_m != null && road_distance_status === "ok"` → `沿路 {formatKm(road_distance_m)}`
  - otherwise → `沿路 ≈ {formatKm(roadEstimateM(straight_distance_m, profile))}`
- **Straight badge:** `直線 {formatKm(straight_distance_m)}` (omitted only if straight is null — transient, pre-first-save).
- **New pure util** `frontend/src/utils/roadEstimate.ts`: `roadEstimateM(straightM, profile)` = `straightM × DETOUR_FACTOR[profile]`, with `DETOUR_FACTORS = { driving: 1.4, walking: 1.3, cycling: 1.35 }` (default 1.4). Tunable constants.
- **WS catch-up (fixes C5):** call `routes.refresh()` in `useWebSocket` `onopen` (replay after a dropped broadcast); make `refreshSavedRoutes` retry once on a transient HTTP error instead of silently swallowing it.
- The existing `reason`-threading that suppresses the cloud-sync toast for `reason === "distance"` is preserved.

## "Never stuck" invariants (each maps to a root cause)

| Root cause | Fix | Testable invariant |
|---|---|---|
| C1 silent `None` | terminal-state write on every path | after `compute_road_distance`, status ∈ {ok, unavailable}; never pending |
| C1 / C2 | bounded retry + sweep re-attempts `unavailable` | a transient failure then success ends in `ok` |
| C2 | terminal write always broadcasts | failure path emits exactly one `routes_changed` |
| C3 | explicit status; UI shows exact-or-`≈` | UI never renders "計算中" |
| C4 | import stamps + spawns compute | importing routes leaves them non-pending after compute |
| C5 | reconnect re-fetch + refresh retry | (frontend) reconnect triggers `routes.refresh()` |
| demo server | default FOSSGIS + single request | (config) default engine is `osrm_fossgis` |

## Clean architecture

- **`domain/route_distance.py` (pure, reuse the orphan's tested helpers where they fit):** `straight_line_distance_m(waypoints)`, `route_fingerprint(waypoints, profile)`, `decimate_waypoints(waypoints, max_n)`. Stdlib only; no I/O.
- **`services/route_distance_service.py`:** `compute_road_distance(...)` deferred orchestrator (retry + terminal write + injected broadcast + injected RouteManager + RouteService engine). Raises domain errors only.
- **`api/route.py`:** stamp + spawn inside create / replace / GPX / import handlers.
- **`bootstrap` / `main.py`:** wire the service; lifespan startup sweep + watcher recompute.
- The road-estimate detour factors live on the frontend (`roadEstimate.ts`) since the estimate is computed client-side from the persisted straight distance + profile.

## Testing

- **Pin baselines first:** `cd backend && .venv/bin/python -m pytest --collect-only -q` and the frontend `vitest` count (prior notes disagree — trust only the live count).
- **Characterization tests (danger zone — write before touching):** the deferred `compute_road_distance` (driven by an injected clock + stubbed engine returning success / fallback / exception), the `api/route` stamp+spawn on all four mutation paths incl. import, and the startup/watcher sweep — asserting ordered, exact terminal states and broadcasts.
- **Never-stuck invariant tests:** engine returns fallback on every attempt → status ends `unavailable`, `road_distance_m` None, exactly one broadcast; engine fails then succeeds within the retry budget → status `ok`; route edited mid-compute → stale result discarded.
- **Pure util tests:** `straight_line_distance_m`, `route_fingerprint` (stable + sensitive to waypoint/profile change), `decimate_waypoints` (caps count, keeps endpoints); frontend `roadEstimateM` (per-profile factor, null-safe).
- **Frontend RouteList tests:** exact value when `ok`; `≈` estimate when pending/unavailable; never renders "計算中"; reconnect triggers refresh.
- Full backend pytest + frontend vitest + tsc + import-linter (7 contracts) + dependency-cruiser all green after every commit.

## Non-goals

- No new HTTP / WS / IPC endpoint (stamp inside existing handlers; reuse `routes_changed`).
- No offline / bundled routing graph — the design tolerates network flakiness via the `≈` estimate + retry + terminal state rather than removing the network.
- No change to the simulation / movement engine.
- No per-leg routing — one multi-waypoint request per compute.

## Files (anticipated)

| File | Change |
|---|---|
| `backend/models/schemas.py` | +4 SavedRoute fields |
| `backend/domain/route_distance.py` | new pure helpers (straight, fingerprint, decimate) |
| `backend/services/route_distance_service.py` | new deferred orchestrator (retry + terminal write + broadcast) |
| `backend/api/route.py` | stamp + spawn on create / replace / GPX / import |
| `backend/main.py` (+ bootstrap) | wire service; startup sweep + watcher recompute |
| `backend/config.py` | default engine → `osrm_fossgis`; `ROAD_MAX_WAYPOINTS`; retry/backoff constants |
| `backend/services/route_service.py` | `X-Client-Id` header on FOSSGIS requests |
| `frontend/src/utils/roadEstimate.ts` (+ test) | road `≈` estimate util |
| `frontend/src/components/RouteList.tsx` (+ test) | distance badges (exact vs `≈`); never "計算中" |
| `frontend/src/hooks/useWebSocket*` / route refresh | reconnect re-fetch + refresh retry |
