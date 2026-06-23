# P4b-2b-ii — MapView Popovers/Menus — Implementation Plan

> **For agentic workers:** Execute task-by-task via subagent-driven-development. These popovers/menus are
> plain React JSX (jsdom-renderable) → extract each to a presentational component + an RTL char test. No
> behavior change. MapView prop interface + e2e contract FROZEN. MapView stays api-clean + error-gated.

**Goal:** Extract the 5 popovers/menus from `MapView.tsx`, leaving it a thin composition shell — completing
the whole P4b frontend decomposition.

**Spec:** `docs/superpowers/specs/2026-06-22-p4b2bii-mapview-popovers-design.md`

## Global Constraints

- Frontend-only, **no behavior change**. `MapView` prop interface FROZEN (`App.tsx` untouched).
- After every commit: `npx vitest run` green + `npx tsc --noEmit` clean + `npx playwright test` green (7).
- `npx depcruise src --config .dependency-cruiser.cjs` → 0 errors (MapView stays api-clean + error-gated;
  new components import no `services/api` — `MapContextMenu` gets `reverseGeocode` as a prop from MapView's
  `useServices().api`).
- The OPEN/trigger state stays lifted in MapView (conditional render); components take data + callbacks as props.
- Add an RTL char test per component (mock `api.reverseGeocode` / `ResizeObserver` as needed).

---

### Task 1: `S2LevelPicker`

**Files:** Create `frontend/src/components/S2LevelPicker.tsx` + test; modify `MapView.tsx`.

- [ ] Move the S2 level-picker popover JSX (level buttons + the `approxCellSizeMeters` size hint). It reads
  `s2Level`/`setS2Level`/`s2Suppressed` (from `useS2Grid`) + open/close state — pass them as props; keep the
  open state in MapView. RTL test: renders the levels; clicking one calls `setS2Level`.
- [ ] `vitest` + `tsc` + `playwright` green. Commit: `refactor(p4b2bii): extract S2LevelPicker`.

---

### Task 2: `WaypointMenu`

**Files:** Create `frontend/src/components/WaypointMenu.tsx` + test; modify `MapView.tsx`.

- [ ] Move the per-waypoint mini-menu JSX (set-as-start / insert-after / delete) + its dismissal. The
  `wpMenu` state STAYS lifted in MapView (it was lifted in P4b-2b-i); the component reads it via props +
  the action callbacks (sourced from the handler-mirror refs). RTL test: each action fires its callback;
  dismissal closes it.
- [ ] `vitest` + `tsc` + `playwright` green. Commit: `refactor(p4b2bii): extract WaypointMenu (state stays in MapView)`.

---

### Task 3: `CoordInputStrip`

**Files:** Create `frontend/src/components/CoordInputStrip.tsx` + test; modify `MapView.tsx`.

- [ ] Move the coord-input strip: the input state + `parseCoord` + the teleport/navigate/preview submit
  handlers + the status-bar-height `ResizeObserver` (the vertical-offset measure). Move the observer + its
  disconnect cleanup together. Callbacks (onTeleport/onNavigate/onPreview) as props. RTL test (mock
  `ResizeObserver`): a valid coord + submit fires the right callback with parsed lat/lng; bad input rejected.
- [ ] `vitest` + `tsc` + `playwright` green. Commit: `refactor(p4b2bii): extract CoordInputStrip (ResizeObserver moved)`.

---

### Task 4: `RecentPlacesPopover`

**Files:** Create `frontend/src/components/RecentPlacesPopover.tsx` + test; modify `MapView.tsx`.

- [ ] Move the recent-destinations popover: open/close + the draggable header (capture-phase document
  pointer listeners + cleanup — move them together) + the clear-confirm + the per-row rendering (badge /
  bookmark-coord-match / relative-time). Data (`recentPlaces`, the bookmark-by-coord map) + callbacks
  (onSelect/onClear/...) as props. RTL test: rows render; a row click fires onSelect; clear-confirm gates
  onClear; the drag listeners attach on pointerdown + detach on pointerup.
- [ ] `vitest` + `tsc` + `playwright` green. Commit: `refactor(p4b2bii): extract RecentPlacesPopover (draggable)`.

---

### Task 5: `MapContextMenu` (riskiest — LAST)

**Files:** Create `frontend/src/components/MapContextMenu.tsx` + test; modify `MapView.tsx`.

- [ ] Move the right-click context menu: the viewport-clamp layout-effect (**preserve the EXACT dep list —
  it deliberately excludes the menu position; "fixing" it reintroduces the v0.2.38 reposition loop**), the
  reverse-geocode stale-guard (via a `reverseGeocode` prop = MapView's `api.reverseGeocode`), and the 7
  actions (teleport/navigate/goldditto/copy/add-bookmark/add-waypoint/…). Follow the P4b-3
  `BookmarkContextMenu` pattern: the menu component owns its reverse-geocode state + dismissal; MapView keeps
  the open-state (coords) and renders `{contextMenu && <MapContextMenu key={…per-open…} … />}` so each open
  is a fresh mount and the stale-guard reduces to a `mountedRef`.
- [ ] Remove `reverseGeocode` from MapView's inline usage (it's now passed into the menu). Confirm MapView
  still imports nothing from `services/api` (depcruise mapview-no-direct-api stays green).
- [ ] RTL test: opening calls `reverseGeocode` once; closing before it resolves drops the late address
  (stale-guard); each action fires its callback; the clamp effect runs without looping.
- [ ] `vitest` + `tsc` + `playwright` green. Commit: `refactor(p4b2bii): extract MapContextMenu (footgun + stale-guard preserved)`.

---

### Final: MapView thin-shell confirm + whole-branch review + finish

- Confirm MapView is now a thin composition shell (report its final LOC). depcruise 0 errors, MapView
  error-gated. Full `vitest` + `tsc` + `playwright` green.
- Dispatch the adversarial whole-branch review (the context-menu footgun + stale-guard, the draggable, the
  ResizeObserver, the frozen invariants), refute-verified. Fix confirmed findings (one wave).
- `finishing-a-development-branch`: present merge options. **P4b frontend decomposition complete** — note P5
  (gate-probe + origin-constant cleanup) is the remaining roadmap item.
