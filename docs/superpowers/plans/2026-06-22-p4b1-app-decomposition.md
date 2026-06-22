# P4b-1 — App.tsx Decomposition — Implementation Plan

> **For agentic workers:** Execute task-by-task via subagent-driven-development. Refactor tasks =
> read the real file → ensure characterization tests green → extract one seam → `vitest` + `tsc`
> green → commit. No behavior change. Child component prop interfaces are FROZEN.

**Goal:** Reduce `App.tsx` (2639 LOC) to a thin composition shell by extracting hooks + presentational
components; close App's view-rule violation; danger-zone handlers extracted LAST on top of tests.

**Spec:** `docs/superpowers/specs/2026-06-22-p4b1-app-decomposition-design.md`

## Global Constraints

- Frontend-only, **no behavior / API / WS change**. Child prop interfaces (`ControlPanel`, `MapView`,
  `BookmarkList`, `StatusBar`, …) FROZEN — internal-to-App decomposition + new hooks only.
- After every commit: `cd frontend && npx vitest run` green + `npx tsc --noEmit` clean.
  `App.singleConnection.test.tsx` + `adapters/ws/router.test.ts` stay green.
- **Single-WebSocket invariant**: no extracted hook calls `useWebSocket()`/`useWsRouter()`. They take
  `ws`/`sendMessage`/`connected` as args (App sources them from `useServices()`).
- **WsRouter fan-out** preserved: extracted subscribers use `ws.subscribe('type', handler)` → unsubscribe;
  multiple hooks may subscribe to one type; never centralize.
- **api inversion folded in**: each extracted hook takes `api` as an arg; only App reads
  `useServices()`. Convert App's `import * as api` to `const { api } = useServices()` incrementally;
  at the end App imports nothing from `services/api`.
- Preserve: `showToast` single-shared-timer + its TDZ resolution; sticky-primary-udid → `useSimulation`;
  the CloudSyncBusy combined post-toggle refresh closure (single `useCloudSyncAfter`); the sim fan-out
  `udids>=2 ? *All+toastForFanout : single` rule AND the deliberate go-around-`sim.teleport` paths.
- dependency-cruiser stays 0 errors throughout; App tightened to a scoped `error` rule at exit.

---

### Task 1: Branch + baseline + App render-smoke characterization test

**Files:** Create `frontend/src/App.smoke.test.tsx`.

- [ ] Branch `feat/p4b1-app` off main; `cd frontend && npx vitest run 2>&1 | tail -2` (pin count) and
  `npx vitest run --coverage 2>&1 | grep -i app.tsx` (record App baseline %).
- [ ] Write `App.smoke.test.tsx` reusing `App.singleConnection.test.tsx`'s `importOriginal` api-mock +
  MapView-null-stub: render `<App/>` inside its providers and assert the composed structure (sidebar
  panels present; a WS `position_update`/banner-triggering event surfaces its banner). This pins App's
  rendered output, which nothing does today.
- [ ] `vitest` + `tsc` green. Commit: `test(p4b1): App render-smoke characterization before decomposition`.

---

### Task 2: Danger-zone characterization tests (write FIRST, against the monolith)

**Files:** Create `frontend/src/App.simActions.test.tsx` + `frontend/src/App.mapClick.test.tsx` (or a
combined `App.dangerzone.test.tsx`).

Read the current sim-action handlers (App.tsx:220-249, 655-690, 957-1237) + `handleMapClick`
(App.tsx:536-589). Render `<App/>` (smoke harness) or drive the handlers via the rendered UI; pin:

- [ ] Single-device vs dual-device branch for start / stop / pause / resume / teleport / navigate:
  asserts the `*All` variant + `toastForFanout(...)` string fire when `connectedDevices.length >= 2`,
  single-device variant otherwise.
- [ ] The go-around-`sim.teleport` paths (route-paste submit, set-waypoint-as-start, waypoint-fly):
  assert they call raw `api`/`sim.setCurrentPosition` and do NOT flip `sim.mode` or clear
  `sim.waypoints`.
- [ ] `handleMapClick`: insert-after mode → inserts at index + fans out; click-to-add-waypoint toggle →
  appends; default (no mode) → teleport/preview per current behavior; all gated on `sim.mode`/status.
- [ ] `vitest` green. Commit: `test(p4b1): danger-zone char tests (sim fan-out + handleMapClick)`.

> These + Task 1 must stay green through every later task. They are the safety net for Tasks 9-10.

---

### Task 3: Extract `useToast()` (+ resolve the TDZ)

**Files:** Create `frontend/src/hooks/useToast.ts` + test; move `toastForFanout` to a pure util
(`frontend/src/utils/`); modify `App.tsx`.

- [ ] `useToast()` → `{ toastMsg, showToast }` preserving the single-shared-timer cancel (App.tsx:197-212).
- [ ] Wire it so `showToast` is stable BEFORE `useSimulation` runs, eliminating the TDZ forward-ref
  (App.tsx:94-98). Assert the tunnel-recovered toast still fires (it flows through the `useSimulation`
  callback).
- [ ] Keep `toastForFanout` pure (util) + a unit test. `vitest` + `tsc` green.
  Commit: `refactor(p4b1): extract useToast + toastForFanout util (resolves the useSimulation TDZ)`.

---

### Task 4: Extract `useRoutes(api)`

**Files:** Create `frontend/src/hooks/useRoutes.ts` + test; modify `App.tsx`.

- [ ] Move `savedRoutes`/`routeCategories` state + the ~14 handlers: load on mount (App.tsx:317),
  save/rename/delete/bulk-delete/move + 4 route-category ops + GPX import/export + import-all
  (App.tsx:111-129, 1000-1165, 1328-1347). Takes `api` (from `useServices()`); raises nothing new.
- [ ] **Keep the combined cloud-sync-after closure at App level** (`useCloudSyncAfter`, App.tsx:130-132):
  App assembles `bm.refresh` + `routes.refresh` into one closure and registers it once. Do NOT add a
  second `useCloudSyncAfter`.
- [ ] `renderHook` test (stub api) for save/delete/move + the import-all path. `vitest` + `tsc` green.
  Commit: `refactor(p4b1): extract useRoutes hook (api via useServices; cloud-sync closure stays at App)`.

---

### Task 5: Extract `useRecentPlaces` + `useLocationMeta` + `useCatalog`

**Files:** Create `frontend/src/hooks/useRecentPlaces.ts`, `useLocationMeta.ts`, `useCatalog.ts` (+ tests);
modify `App.tsx`. (Three small, independent leaf hooks — one task.)

- [ ] `useRecentPlaces(api, connected)` → recent list + `refreshRecent`/`pushRecent`/`clearRecentList`
  incl. background reverse-geocode-and-re-push (App.tsx:607-641).
- [ ] `useLocationMeta(api, position, simState)` → `{ locMeta }`, preserving the 100m + sim-quiescent
  gate (App.tsx:174-191, 334-377).
- [ ] `useCatalog(api, bookmarks)` → catalog state + `fetchCatalog` + `catalogNewCount` memo +
  `handleCatalogRefresh` (App.tsx:1271-1326).
- [ ] `renderHook` tests for each (gate behavior, change detection). `vitest` + `tsc` green.
  Commit: `refactor(p4b1): extract useRecentPlaces + useLocationMeta + useCatalog hooks`.

---

### Task 6: Extract `useWifiAutoConnect(connected, device)`

**Files:** Create `frontend/src/hooks/useWifiAutoConnect.ts` + test; modify `App.tsx`.

- [ ] Move the ~95-line once-per-session WiFi auto-connect effect (App.tsx:403-499): the savedips
  localStorage parse + dedupe + cap-at-3 + parallel tunnel attempts, guarded by
  `wifiAutoConnectAttemptedRef`.
- [ ] Char-test the parse/dedupe/cap logic with a stub device API. `vitest` + `tsc` green.
  Commit: `refactor(p4b1): extract useWifiAutoConnect hook`.

---

### Task 7: Extract `<WaypointEditor>`

**Files:** Create `frontend/src/components/WaypointEditor.tsx` + test; modify `App.tsx`.

- [ ] Lift the ~210-line inline `modeExtraSection` JSX (App.tsx:1670-1883) into a controlled component
  consuming its existing prop set (`sim.waypoints`, `waypointProgress`, lap state, wpGen radius/count,
  handlers). Preserve every per-button `disabled={sim.status?.running}` guard and the inline
  `api.routeOptimize` call (route it via a prop/`api` arg, not a direct import).
- [ ] Component test (render + a couple of handler clicks). `vitest` + `tsc` green.
  Commit: `refactor(p4b1): extract WaypointEditor component`.

---

### Task 8: Extract the 5 modal components

**Files:** Create `AddBookmarkDialog` (App-level), `BulkPasteDialog`, `WaypointFlyDialog`,
`RouteLoadDialog`, `RoutePasteDialog` under `components/` (+ tests); modify `App.tsx`.

- [ ] Convert the 5 `createPortal` blocks (App.tsx:2109/2187/2282/2361/2436) to controlled components;
  parse/validation stays inside each, emitting the same shapes to the App callbacks. Preserve the
  add-bookmark async reverse-geocode pre-fill behavior.
- [ ] A focused test per dialog (render → fill → submit fires the right callback). `vitest` + `tsc` green.
  Commit: `refactor(p4b1): extract the 5 App modals into controlled components`.

---

### Task 9: Extract `useSimActions` (DANGER — on top of Task 2 tests)

**Files:** Create `frontend/src/hooks/useSimActions.ts` + test; modify `App.tsx`.

- [ ] Consolidate the fan-out handlers (App.tsx:220-249, 655-690, 957-1237) behind
  `useSimActions(sim, device, showToast, t, pushRecent, api)`. The `udids>=2 ? *All+toastForFanout :
  single` rule lives in ONE place. **Preserve the deliberate go-around-`sim.teleport` paths verbatim**
  (route-paste, set-as-start, waypoint-fly) — they must not flip `sim.mode`/wipe waypoints.
- [ ] The Task 2 char tests MUST stay green (they are the net). Add hook-level tests for each action's
  single/dual branch. `vitest` + `tsc` green.
  Commit: `refactor(p4b1): extract useSimActions (dual-device fan-out; teleport-bypass preserved)`.

---

### Task 10: Extract `handleMapClick` (DANGER — on top of Task 2 tests)

**Files:** Modify `App.tsx` (+ a hook `useMapClick` or a colocated handler) + test.

- [ ] Extract `handleMapClick` (App.tsx:536-589) preserving the three-way behavior (insert-after /
  click-to-add-waypoint / default) + the `sim.mode` gating + the live insertWaypoint fan-out + the ESC
  insert-mode listener (App.tsx:526). The Task 2 map-click char tests MUST stay green.
- [ ] `vitest` + `tsc` green. Commit: `refactor(p4b1): extract handleMapClick (three-mode behavior preserved)`.

---

### Task 11: Residual api inversion + tighten App gate + final verify

**Files:** modify `App.tsx`, `frontend/.dependency-cruiser.cjs`.

- [ ] Convert any remaining App-level `api.*` (direct import) call sites to `useServices().api`; remove
  `import * as api`. Confirm `App.tsx` imports nothing from `services/api`/`adapters`
  (`npx depcruise` no longer warns on App.tsx).
- [ ] Add `App.tsx` to a scoped dependency-cruiser **error** rule (extend the BookmarkList-style scoped
  rule, or add an `app-no-direct-api` rule). `npx depcruise` exits 0; verify it fails on an injected
  `services/api` import into App.tsx (then revert).
- [ ] Full `vitest run` + `tsc --noEmit` + `vitest run --coverage` (App coverage ≥ baseline) + e2e
  (`sim.spec`/`ws.spec`) once. Commit: `chore(p4b1): App api-clean + enforce no-direct-api for App`.

---

### Final: whole-branch review + finish

- Dispatch the adversarial whole-branch review (dimensions: behavior-equivalence — esp. the fan-out
  teleport-bypass + handleMapClick + the TDZ/showToast + the cloud-sync closure; gate/DI correctness;
  test quality; invariants). Fix confirmed findings (one fix wave).
- `finishing-a-development-branch`: full `vitest` + `tsc` + e2e green → present merge options to Ravi.
