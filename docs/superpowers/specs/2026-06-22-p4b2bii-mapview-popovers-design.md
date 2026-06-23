# P4b-2b-ii — MapView Popovers/Menus — Design

**Date:** 2026-06-23
**Status:** Design — awaiting review
**Author:** Ravi + Claude

## Problem

After P4b-2a (map instance/base-layers/buttons/pure helpers) and P4b-2b-i (the 8 per-layer Leaflet hooks),
`MapView.tsx` (1793 LOC) is a thin shell of layer-hook calls **plus 5 presentational popovers/menus**.
Unlike the Leaflet layers, these are plain React JSX (portals / absolute-positioned divs over the map by
screen coords) — **jsdom-renderable**, so they get proper RTL component tests. This is the FINAL MapView
round; after it the whole P4b frontend god-component decomposition is complete.

## Decisions (locked with Ravi, 2026-06-23)

| Decision | Choice |
|----------|--------|
| **Scope** | Full P4b-2b-ii in one round — all 5 popovers/menus: `S2LevelPicker`, `WaypointMenu`, `CoordInputStrip`, `RecentPlacesPopover`, `MapContextMenu`. |
| **Test strategy** | RTL component tests in jsdom (mock `api.reverseGeocode` / `ResizeObserver`; the stale-guard + draggable listeners + viewport-clamp are jsdom-drivable) + the existing e2e net (7) for integration. |

## Goals

1. Extract the 5 popovers/menus from `MapView.tsx` into presentational components, leaving MapView a thin
   composition shell (layer hooks + child components).
2. No behavior change. `MapView` prop interface FROZEN (`App.tsx` untouched). e2e CSS contract + localStorage
   keys FROZEN. MapView stays api-clean + error-gated.
3. Add RTL char tests for the tricky bits (the context-menu stale-guard, viewport-clamp, the draggable popover).

## Non-negotiable invariants

- **`MapContextMenu` viewport-clamp footgun**: the clamp layout-effect's dependency list **deliberately
  excludes the menu position** (a documented infinite-loop guard, v0.2.38 reposition loop). Preserve the
  exact dep list — do not "fix" it.
- **`MapContextMenu` reverse-geocode stale-guard**: a late `api.reverseGeocode` result from a since-closed/
  reopened menu must be dropped — same 3-mechanism pattern as P4b-3's `BookmarkContextMenu` (per-open mount
  + a `mountedRef`/snapshot guard). The open-state (coords) stays lifted in MapView (conditional render +
  key-per-open); the menu component owns its reverse-geocode state + dismissal.
- **`RecentPlacesPopover` draggable**: the capture-phase document drag listeners (pointerdown/move/up) +
  their cleanup move together; the clear-confirm + per-row badge/bookmark-match/relative-time rendering
  preserved.
- **`CoordInputStrip`**: the coord `parseCoord` + teleport/navigate/preview submit + the status-bar-height
  `ResizeObserver` (vertical offset) preserved; its cleanup moves with it.
- **`S2LevelPicker`**: reads the `useS2Grid` state/setters (`s2Level`/`setS2Level`/…) passed in; the
  `locwarp.s2_level` write stays in `useS2Grid` (the picker only sets via the setter).
- **`WaypointMenu`**: the lifted `wpMenu` state stays in MapView; the menu reads it + the handler-mirror
  refs (`onSetWpAsStartRef`/`onRemoveWaypointRef`/`onInsertAfterWpRef`) — move the JSX + its dismissal,
  keep the state lifted.
- e2e CSS contract FROZEN; MapView prop interface FROZEN (App untouched); MapView stays api-clean
  (`reverseGeocode` reaches `MapContextMenu` via `api.reverseGeocode` passed as a prop / `useServices()`).
- single-WebSocket / WsRouter fan-out untouched.

## Architecture

Each popover/menu → a presentational component in `frontend/src/components/`. The OPEN/trigger state
(which menu is open + its coords) stays lifted in MapView (conditional render). Components take data +
callbacks as props; `MapContextMenu` takes `reverseGeocode` as a prop (MapView sources it from
`useServices().api`). Same dependency-cruiser gate (MapView already error-gated); new components import no
`services/api`. RTL tests under `frontend/src/components/`.

## Extraction sequence (low → high risk)

1. **`S2LevelPicker`** — the S2 level popover (level buttons + size hint). Reads `s2Level`/`setS2Level`/
   `s2Suppressed`/`approxCellSizeMeters` via props. Pure presentational. RTL test: renders levels, clicking
   one calls `setS2Level`.
2. **`WaypointMenu`** — the per-waypoint mini-menu (set-as-start / insert-after / delete). Reads the lifted
   `wpMenu` state + the handler-mirror refs via props/callbacks; the state STAYS in MapView. RTL test:
   renders the actions, each fires its callback; dismissal works.
3. **`CoordInputStrip`** — coord input + `parseCoord` + teleport/navigate/preview + the status-bar
   `ResizeObserver`. Move the ResizeObserver + its cleanup into the component. RTL test (mock
   `ResizeObserver`): typing a coord + submit fires teleport/navigate/preview with parsed coords; bad input
   rejected.
4. **`RecentPlacesPopover`** — open/close + draggable header (capture-phase doc listeners + cleanup) +
   clear-confirm + per-row rendering (badge / bookmark-coord-match / relative-time). RTL test: rows render,
   a row click fires the callback, clear-confirm gates the clear, the drag listeners attach/detach.
5. **`MapContextMenu`** (riskiest, LAST) — the right-click menu: the viewport-clamp layout-effect (preserve
   the exact dep list — the footgun), the reverse-geocode stale-guard (via `api.reverseGeocode` prop), the 7
   actions (teleport/navigate/goldditto/copy/add-bookmark/add-waypoint/…). Follow the P4b-3
   `BookmarkContextMenu` pattern: per-open mount + `mountedRef` stale-guard; open-state (coords) stays in
   MapView (conditional render + key-per-open). RTL test: opening calls `reverseGeocode`; closing before it
   resolves drops the late address (stale-guard); each action fires its callback; the clamp doesn't loop.

After this round MapView is a thin composition shell (layer hooks + popover/menu components + the JSX
skeleton). **P4b is complete.**

## Testing & verification

- After every commit: `npx vitest run` green (grows with the RTL tests) + `npx tsc --noEmit` clean +
  `npx playwright test` green (7). `npx depcruise` → 0 errors (MapView stays api-clean + error-gated; new
  components import no `services/api`).
- Final adversarial whole-branch review (behavior-equivalence on the context-menu footgun + stale-guard,
  the draggable, the ResizeObserver, the frozen invariants), refute-verified, before merge.

## Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Context-menu viewport-clamp infinite-loop reintroduced | Preserve the exact dep list (footgun); RTL test asserts no reposition loop |
| Context-menu stale-address leak | Per-open mount + `mountedRef` guard (BookmarkContextMenu pattern); RTL test drops a late reverseGeocode |
| Draggable capture-phase listeners leak | Move listeners + cleanup together; RTL test asserts attach/detach |
| ResizeObserver leak (CoordInputStrip) | Move the observer + disconnect cleanup together; mock it in the RTL test |
| MapView prop interface drift → ripples to App | Freeze the prop interface; App.tsx untouched |
| MapView re-imports services/api for reverseGeocode | Pass `api.reverseGeocode` as a prop from MapView's `useServices()`; depcruise error rule guards it |
