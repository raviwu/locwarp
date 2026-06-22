# P4b-2a — MapView.tsx Decomposition (safe structural + test net) — Design

**Date:** 2026-06-22
**Status:** Design — awaiting review
**Author:** Ravi + Claude

## Problem

`MapView.tsx` is the last and hardest god-component: **2867 LOC** of **imperative Leaflet** (38 `useRef`, 28 `useEffect`, 15 `useState`), held together by ~12 wire-once `*Ref` mirrors. It **cannot be unit-tested in jsdom** (no WebGL/canvas) — today only 2 Playwright e2e specs pin 3 selectors. It carries ~200 LOC of dead `dualMode = false` code and 2 direct `services/api` imports (`reverseGeocode` line 3, dynamic `getInitialPosition` line 868).

Because the Leaflet-bound code is e2e-only-testable, MapView is split into two rounds. **This round (P4b-2a)** does the genuinely-safe structural work + builds the test net; **P4b-2b** (deferred) does the risky per-layer Leaflet hooks + popovers on top of that net.

## Decisions (locked with Ravi, 2026-06-22)

| Decision | Choice |
|----------|--------|
| **Scope (this round)** | P4b-2a: extend e2e net → delete dead dual-mode → extract pure helpers (unit-tested) → `useMapInstance` + `useBaseLayers` + `LeafletBarButton` → route api via `useServices()` + tighten MapView gate. |
| **Deferred (P4b-2b)** | The per-layer Leaflet hooks (`CurrentPositionLayer`/`DestinationLayer`/`PreviewPinLayer`/`WaypointMarkersLayer`/`BookmarkMarkersLayer`/`RoutePolylineLayer`/`RandomWalkCircleLayer`/`useS2Grid`) + presentational popovers (`RecentPlacesPopover`/`MapContextMenu`/`CoordInputStrip`/`S2LevelPicker`). |
| **Test strategy** | Extend Playwright e2e to pin the Leaflet artifacts; extract pure algorithmic code into jsdom-unit-testable modules. **No fragile jsdom Leaflet mock.** |

## Goals

1. Shrink + de-risk MapView without changing behavior (frozen e2e CSS contract + localStorage keys + prop interface).
2. Build the **test net first** so the structural moves (and P4b-2b's layer carve-outs) have coverage.
3. Close MapView's view-rule violation (route `reverseGeocode`/`getInitialPosition` through `useServices().api`); tighten MapView's dependency-cruiser rule to `error`.

## Non-negotiable invariants

- **e2e CSS contract FROZEN**: `.leaflet-container`, `.current-pos-marker`, `path.route-flow-dash` keep exact class names + DOM presence/absence semantics (`e2e/sim.spec.ts` + `ws.spec.ts`).
- **localStorage keys FROZEN**: `locwarp.s2_enabled`, `locwarp.s2_level`, `locwarp.tile_layer`.
- **MapView's prop interface FROZEN** (App passes ~40 props) — internal decomposition only; `App.tsx` untouched.
- **Wire-once + `*Ref`-mirror pattern preserved**: map-init, button, and per-marker handlers are wired ONCE and read fresh props via `*Ref` mirrors (`tRef`, `onMapClickRef`, follow/wp/library/s2 handler refs). A hook extraction must keep this pattern, or the documented stale-closure bugs regress.
- **`onMapReady({ panTo })`** external imperative contract (StatusBar Locate-PC) must still be exposed by the map-instance hook.
- **Leaflet layer ownership**: each effect's single owner ref + add/remove discipline stays intact (no double-remove/orphan).
- **single-WebSocket / WsRouter fan-out**: MapView doesn't subscribe to WS (fed via props) — must not start.

## Architecture

Pure helpers → `frontend/src/utils/` or `frontend/src/services/` (jsdom-unit-testable). Hooks → `frontend/src/hooks/`. The `LeafletBarButton` primitive → `frontend/src/components/`. MapView reads `useServices().api` and passes `api` into `useMapInstance`. Same dependency-cruiser gate; MapView tightened to a scoped `error` rule at round exit.

## P4b-2a scope (sequenced)

1. **Extend the e2e net FIRST.** Add Playwright assertions to `e2e/sim.spec.ts` / `ws.spec.ts` (or a new spec) pinning the Leaflet artifacts a refactor could move: the destination marker, a bookmark pin / cluster, the route polyline base+arrow, and the recenter/follow/library/S2 leaflet-bar buttons existing. Keep the exact selectors as the frozen contract. This is the danger-zone-test-first gate for everything below.
2. **Delete dead dual-mode** (~200 LOC): the `dualMode = false` constant (line 317), the per-device overlay effect/renderer, and the `if (dualMode)` branches inside the single-device effects (current-position/destination/route/circle). Also stop App from threading `devices`/`runtimes` into MapView if they become unused (verify — keep MapView's prop interface stable if App still passes them; prefer no-op acceptance over a prop-interface change this round). Standalone first commit, `sim.spec`/`ws.spec` as the net.
3. **Extract pure helpers + unit tests** (jsdom-safe): the bookmark-pin **clustering** algorithm (px-distance grouping), `haversineM`, `escapeHtml`, the **icon-HTML builders** (divIcon HTML strings), and any S2 paint math not already in `services/s2grid.ts`. Each → a pure module + a colocated `*.test.ts`. (The S2 geometry already lives in `services/s2grid.ts` with tests — mirror that pattern.)
4. **Extract `useMapInstance(containerRef, { onMapClick, onContextMenu, onMapCenterChange, onMapReady, api })`**: the once-per-mount `L.map()` creation, default center, persisted initial-position fetch (`api.getInitialPosition` via `useServices()`), teardown, the map-level click/contextmenu/moveend/dragstart wiring, and `onMapReady({ panTo })`. Preserve the wire-once + `*Ref`-mirror pattern verbatim. Returns `{ mapRef }` consumed by everything else.
5. **Extract `useBaseLayers(mapRef)`**: the 6 tile-layer definitions, `L.control.layers` switcher, and `baselayerchange ↔ localStorage` persistence (`locwarp.tile_layer`).
6. **Extract a `LeafletBarButton` primitive**: collapse the 4 near-identical raw-DOM button builders (recenter/follow/library/S2) + their 4 React→DOM sync effects into one reusable primitive (`icon`, `title`, `active`, `onClick`), preserving the leaflet-bar markup the extended e2e pins.
7. **api inversion + gate**: MapView reads `const { api } = useServices()`; `reverseGeocode` (used by the still-inline context menu) + `getInitialPosition` (via `useMapInstance`) go through `api.*`; remove both direct `services/api` imports. Add MapView to a scoped dependency-cruiser **error** rule; verify it fires on an injected violation.

## Deferred to P4b-2b (NOT this round)

The per-layer Leaflet hooks + the presentational popovers/menus (`RecentPlacesPopover`, `MapContextMenu`, `CoordInputStrip`, `S2LevelPicker`, the per-marker layers). These are the riskiest carve-outs (Leaflet-only-testable, stale-closure-prone) and land on top of P4b-2a's extended e2e net in their own round + brainstorm.

## Testing & verification

- After every commit: `cd frontend && npx vitest run` green (the new pure-helper unit tests grow it) + `npx tsc --noEmit` clean. `npx playwright test` (the extended e2e net) green after the dead-code delete + each structural extraction.
- `npx depcruise src --config .dependency-cruiser.cjs` → 0 errors; MapView's warning drops to 0 as the api inversion completes, then MapView flips to the scoped `error` set.
- Final adversarial whole-branch review (behavior-equivalence on the map-init order + the wire-once `*Ref` pattern + the dead-code removal + the clustering helper), refute-verified, before merge.

## Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Leaflet is e2e-only-testable → blind refactor | Extend e2e net FIRST (step 1); extract pure algorithmic code to jsdom unit tests |
| Stale-closure regression (the ~12 `*Ref` mirrors) | Preserve wire-once + `*Ref`-mirror pattern verbatim in `useMapInstance`; e2e covers language-switch / follow-disable / toast routing |
| Dead-mode removal touches live single-device effects | Delete only `dualMode`-gated branches; `sim.spec`/`ws.spec` as the net; verify `dualMode` truly makes every branch unreachable |
| Map-init order (control corners, button stack, initial-position race) | Move the init effect verbatim; e2e pins the leaflet-bar buttons + initial marker |
| api inversion changes when initial-position fetch fires | Route via `useServices().api`; e2e confirms the initial pan still precedes the first position |
| MapView prop interface drift → ripples to App | Freeze the prop interface; App.tsx untouched |
