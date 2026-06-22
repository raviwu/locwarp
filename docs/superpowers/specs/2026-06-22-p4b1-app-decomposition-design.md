# P4b-1 — App.tsx Decomposition (Design)

**Date:** 2026-06-22
**Status:** Design — awaiting review
**Author:** Ravi + Claude

## Problem

`App.tsx` is the orchestrator god-component: **2639 LOC**, 33 `useState`, 9 `useEffect`, 61 `useCallback`, 5 `createPortal` modals, mixing ~10 distinct concerns. Test coverage is ~23% with effectively one meaningful test (`App.singleConnection.test.tsx`, which only pins the single-WebSocket fact and stubs MapView to null). It also violates the hexagon-lite view-rule: `import * as api` with ~59 direct `api.*` call sites (it correctly consumes `ws`/`sendMessage`/`connected` via `useServices()`, but not `api`). Several of its handlers — the dual-device simulation fan-out and `handleMapClick` — have **zero tests** and contain subtle, load-bearing logic.

## Decisions (locked with Ravi, 2026-06-22)

| Decision | Choice |
|----------|--------|
| **Scope** | **Full App.tsx decomposition in one round**, including the high-risk `useSimActions` fan-out + `handleMapClick`. |
| **Test discipline** | **Danger-zone characterization tests FIRST** for the untested handlers, then extract; the danger-zone extractions land LAST, on top of their tests. |
| **api inversion** | Fold the `services/api` → `useServices().api` inversion **into each hook extraction** (not a separate 59-site sweep). Convention: hooks take `api`/`ws` as **arguments**; only `App` reads `useServices()`. At round exit App imports nothing from `services/api`, and its dependency-cruiser rule is tightened to **error**. |

This is P4b-1 of the P4b roadmap (P4b-0 gate + P4b-3 BookmarkList already merged; P4b-2 MapView deferred).

## Goals

1. Reduce `App.tsx` from a 2639-LOC orchestrator to a thin composition shell that wires hooks + child components.
2. Extract self-contained concerns into `useBookmarks`-style state hooks and presentational components, each independently testable.
3. Close App's view-rule violation (route all `api.*` through `useServices().api` / injected hooks); tighten App's dependency-cruiser rule to `error` at exit.
4. **No behavior change.** No external HTTP/WS/IPC change. Child component prop interfaces (`ControlPanel`, `MapView`, `BookmarkList`, `StatusBar`, …) stay **stable** — this is internal-to-App decomposition plus new hooks.
5. Lift App coverage materially (esp. the currently-untested danger-zone handlers).

## Non-negotiable invariants

- **Single-WebSocket** (`App.singleConnection.test.tsx`): no extracted hook may call `useWebSocket()`/`useWsRouter()` — they consume `ws`/`sendMessage`/`connected` from args sourced from App's `useServices()`.
- **WsRouter fan-out** preserved (Set/forEach broadcast, per-handler try/catch). Every extracted subscriber uses `ws.subscribe('type', handler)` returning its own unsubscribe; multiple hooks may subscribe to the same type. Never centralize into one dispatcher.
- **`showToast` single-shared-timer** semantic (a newer toast cancels the prior auto-clear). A `useToast()` extraction must preserve this, and must resolve the documented TDZ forward-reference where `useSimulation` captures a `() => showToast(...)` declared after it (eliminate the TDZ by making `useToast`'s `showToast` stable **before** `useSimulation` runs).
- **Sticky-primary-udid** filtering (`useDevice`) feeds `useSimulation`'s per-device event filter — do not move `primaryDevice` derivation or break the udid passed into `useSimulation` (or dual-device markers ping-pong).
- **CloudSyncBusy post-toggle refresh**: `useCloudSyncAfter` registers a *combined* `bm.refresh` + route-refresh closure (single last-writer-wins `afterRef`). If routes move to `useRoutes()`, the combined closure must still be assembled at App level and registered once — never split into two competing `useCloudSyncAfter` calls.
- **Sim fan-out semantics**: the action handlers branch `udids.length >= 2 ? *All + toastForFanout : single`, and several paths (route-paste, set-waypoint-as-start, waypoint-fly) deliberately call raw `api` + `sim.setCurrentPosition` **instead of** `sim.teleport` to avoid flipping `sim.mode` and wiping waypoints. This nuance MUST survive extraction.

## Architecture (extend the existing hexagon-lite; no new patterns)

New code lands in `frontend/src/hooks/` (state + subscriber hooks) and `frontend/src/components/` (presentational). Same DI as the BookmarkList round: App reads `useServices()`; hooks receive `api`/`ws` as args (unit-testable with a stub router/api). `dependency-cruiser` already gates this; at exit App's subtree flips to a scoped `error` rule.

### Decomposition seams (sequenced low → high risk)

**Hooks (state/data — mirror `useBookmarks`):**
1. `useToast()` → `{ toastMsg, showToast }` (App.tsx:197-212; keep `toastForFanout` as a pure util). Resolves the TDZ; smallest, unblocks the rest.
2. `useRecentPlaces(api, connected)` → recent list + `refreshRecent`/`pushRecent`/`clearRecentList` (App.tsx:607-641, incl. background reverse-geocode-and-re-push).
3. `useLocationMeta(api, position, simState)` → `{ locMeta }` (App.tsx:174-191, 334-377; the 100m + sim-quiescent gated lookup).
4. `useCatalog(api, bookmarks)` → catalog state + `fetchCatalog` + `catalogNewCount` + `handleCatalogRefresh` (App.tsx:1271-1326).
5. `useRoutes(api)` → `savedRoutes`/`routeCategories` + the ~14 load/save/rename/delete/bulk-delete/move + 4 category ops + GPX import/export + import-all (App.tsx:111-129, 1000-1165, 1328-1347). Keep the combined cloud-sync-after closure assembled at App.
6. `useWifiAutoConnect(connected, device)` → the ~95-line once-per-session effect (App.tsx:404-499) — char-test the savedips parse + dedupe + cap-at-3.

**Presentational (pure render — biggest LOC win):**
7. `<WaypointEditor>` for the ~210-line inline `modeExtraSection` JSX (App.tsx:1670-1883).
8. The 5 `createPortal` modals → `AddBookmarkDialog`*, `BulkPasteDialog`, `WaypointFlyDialog`, `RouteLoadDialog`, `RoutePasteDialog` (App.tsx:2109/2187/2282/2361/2436). (*App-level add-bookmark dialog, distinct from the BookmarkList one.)

**⚠️ Danger zone (LAST, on top of char tests):**
9. `useSimActions(sim, device, showToast, t, pushRecent)` — consolidate the fan-out handlers (App.tsx:220-249, 655-690, 957-1237) so the `udids>=2 ? *All+toastForFanout : single` rule + the deliberate go-around-`sim.teleport` paths live in ONE tested place.
10. `handleMapClick` (App.tsx:536-589) — couples insert-after mode, click-to-add-waypoint, sim.mode gating, AND live insertWaypoint fan-out. Extract into a focused handler/hook last.

### Danger-zone characterization tests (written FIRST, before seams 9-10)

Before touching the fan-out/map-click code, pin current behavior with `renderHook`/render + a stub `ws` router (`createWsRouter`) + a stub `api`, asserting exact ordered effects:
- Single-device vs dual-device branch for start/stop/pause/resume/teleport/navigate (asserts `*All` vs single + `toastForFanout` string).
- The go-around-`sim.teleport` paths (route-paste, set-as-start, waypoint-fly) call raw `api`/`setCurrentPosition` and do NOT flip `sim.mode` / wipe `sim.waypoints`.
- `handleMapClick`: insert-after mode vs click-to-add-waypoint vs default, gated on `sim.mode`, fanning insertWaypoint to all devices.
- An **App render-smoke** test (reuse `App.singleConnection.test.tsx`'s `importOriginal` api-mock + MapView-null-stub) asserting the composed structure (panels present, banners appear on WS events) — today nothing pins App's rendered output.

## Testing & verification

- After every commit: `cd frontend && npx vitest run` green + `npx tsc --noEmit` clean. `App.singleConnection.test.tsx` + `adapters/ws/router.test.ts` stay green (load-bearing).
- `npx depcruise src --config .dependency-cruiser.cjs` → 0 errors; App's `no-view-imports-api` warning shrinks to 0 as the inversion completes, then App is added to the scoped **error** set at round exit.
- Coverage on `App.tsx` must not drop; capture a baseline first.
- e2e (`sim.spec.ts` / `ws.spec.ts`) — these exercise App→MapView→sim end-to-end; run at the end (and after the danger-zone extractions) as the cross-cutting net.
- Final adversarial whole-branch review (behavior-equivalence focus on the fan-out + map-click + TDZ + cloud-sync closure), refute-verified, before merge.

## Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Fan-out extraction reintroduces the mode-flip-wipes-waypoints bug | Char-test the go-around-`sim.teleport` paths FIRST; extract `useSimActions` last on top of them |
| TDZ break (showToast captured by useSimulation before declared) | `useToast` first; make `showToast` stable before `useSimulation` runs; assert the tunnel-recovered toast still fires |
| 59-site api inversion is high-blast-radius in one sweep | Fold inversion into each hook extraction; residual App calls switch to `useServices().api` only at the end |
| Single-WebSocket regression | No extracted hook calls `useWebSocket`/`useWsRouter`; `App.singleConnection.test` after every commit |
| Cloud-sync post-toggle refresh clobbered when routes move | Keep the combined closure + single `useCloudSyncAfter` registration at App level |
| Child prop interfaces drift → ripples to ControlPanel/MapView | Freeze child prop interfaces; decomposition is internal-to-App + new hooks |
| App is Leaflet/heavy → hard to render-test | Reuse the `importOriginal` api-mock + MapView-null-stub smoke pattern; push logic into hooks (renderHook-testable) over view |
