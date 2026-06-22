# P4b-0 (FE layering gate) + P4b-3 (BookmarkList decomposition) — Implementation Plan

> **For agentic workers:** Execute task-by-task. Refactor tasks = read the real file → ensure
> characterization tests green → extract one seam → `vitest` + `tsc` green → commit. No behavior change.

**Goal:** Add a report-only frontend layering gate + coverage baseline, then decompose
`BookmarkList.tsx` (2109 LOC) into focused, tested units with a frozen public prop interface.

**Spec:** `docs/superpowers/specs/2026-06-22-p4b-frontend-decomposition-design.md`

## Global Constraints

- Frontend-only, **no behavior / API / WS change**. `BookmarkListProps` (the `ControlPanel`/`App`
  contract) is **frozen** — internal decomposition only. Children keep the **name-shape** patch
  (`{name}` / `{name,lat,lng,category}`).
- After every commit: `cd frontend && npx vitest run` green + `npx tsc --noEmit` clean.
  `App.singleConnection.test.tsx` and `adapters/ws/router.test.ts` stay green (load-bearing).
- Route the 3 direct `services/api` imports in BookmarkList through `useServices().api` — **no new
  `ApiGateway` methods** (it is `typeof api`). Component reads `useServices()`; extracted hooks take
  `api` as an arg.
- Preserve: `locwarp.bookmark_fly_gps` (default `true`) + `locwarp.bookmark_sort` keys; the
  two-separate-POST partial UI-state semantics + debounce(expanded 400ms)/immediate(hidden) + load
  gates; the `el.indeterminate` ref-callback for tri-state checkboxes; no new `useWebSocket`/`useWsRouter`.
- dependency-cruiser is **report-only (warn)** this round except the BookmarkList-scoped error rule added at the end.

---

### Task 1: Branch + dependency-cruiser (report-only) + coverage baseline

**Files:** Create `frontend/.dependency-cruiser.cjs`; modify `frontend/package.json` (devDep + script);
modify `.github/workflows/ci.yml` (report-only step).

- [ ] **Step 1** — branch `feat/p4b-bookmarklist` off main; `cd frontend && npx vitest run 2>&1 | tail -2`
  (pin the test count) and `npx vitest run --coverage 2>&1 | grep -i bookmarklist` (record BookmarkList
  baseline % in the commit message). Note: `npm i -D dependency-cruiser` (no runtime dep).
- [ ] **Step 2** — `.dependency-cruiser.cjs` (all rules `severity: "warn"`):
```js
module.exports = {
  forbidden: [
    {
      name: "no-view-imports-api",
      severity: "warn",
      comment: "View (components/* + App.tsx) must reach the backend via useServices().api, not direct import.",
      from: { path: "^src/(components/|App\\.tsx)" },
      to: { path: "^src/(services/api|adapters)" },
    },
    {
      name: "only-root-opens-socket",
      severity: "warn",
      comment: "Only main.tsx may open the WebSocket (single-connection invariant).",
      from: { pathNot: "^src/main\\.tsx$" },
      to: { path: "^src/(adapters/ws/useWsRouter|hooks/useWebSocket)" },
    },
  ],
  options: { doNotFollow: { path: "node_modules" }, tsConfig: { fileName: "tsconfig.json" } },
};
```
- [ ] **Step 3** — `package.json` script: `"depcruise": "depcruise src --config .dependency-cruiser.cjs"`.
  Run it; confirm it reports the known ~7 view-rule warnings (the baseline debt) and exits 0 (warn).
- [ ] **Step 4** — `ci.yml` frontend job: add a non-failing step `npx depcruise src --config .dependency-cruiser.cjs --no-config-checks || true` (visible, never blocks).
- [ ] **Step 5** — commit: `chore(p4b): dependency-cruiser report-only gate + coverage baseline`.

---

### Task 2: BookmarkList characterization tests (write FIRST, against the monolith)

**Files:** Create `frontend/src/components/BookmarkList.test.tsx`.

Read the real `BookmarkList.tsx` first. Build a `makeProps()` factory (mock `../i18n` `useT`→identity,
stub heavy children, wrap in `ServicesProvider` with a stub `api`, stub `localStorage`/`window.confirm`).
Pin (each a separate `it`):

- [ ] collapse **cross-threshold** (AUTO_COLLAPSE_THRESHOLD=30): >30 bookmarks auto-collapses per the
  rule; toggling one open then crossing back <30 restores the live choice (not the start snapshot).
- [ ] hidden-categories: hide persists immediately (one `setBookmarkUiState({hidden_categories})` call,
  no `expanded_categories` key); the initial fetch is NOT echoed back as a write (load gate).
- [ ] expanded persist is debounced (advance fake timers 400ms → one `{expanded_categories}` call).
- [ ] context-menu reverse-geocode: opening on a bm calls `api.reverseGeocode`; closing before it
  resolves drops the late address (stale-guard).
- [ ] multi-select batch delete: select-all → delete → `window.confirm` + N `onBookmarkDelete` calls.
- [ ] search-vs-grouped **row parity**: a query rendering the flat list shows the same bm name/row as
  the grouped list (guards the BookmarkRow de-dup in Task 4).
- [ ] Run `npx vitest run src/components/BookmarkList.test.tsx` green. Commit:
  `test(p4b): characterization tests for BookmarkList before decomposition`.

> These tests must stay green through Tasks 3-9 unchanged (except where a test references an
> implementation detail that legitimately moves — note any such edit explicitly in its commit).

---

### Task 3: Extract `useBookmarkUiState(api)` hook

**Files:** Create `frontend/src/hooks/useBookmarkUiState.ts` + `useBookmarkUiState.test.tsx`; modify
`BookmarkList.tsx`.

- [ ] Read the collapse/hidden logic in `BookmarkList.tsx` (the threshold rule + `getBookmarkUiState`
  on mount + the expanded-debounce + immediate-hidden persistence + the `savedExpandedRef` /
  `prevOverThresholdRef` / `hiddenLoadedRef` / `uiStateLoaded` refs).
- [ ] Move it verbatim into `useBookmarkUiState({ api, bookmarks, categories, categoryDates })`
  returning `{ collapsed, setCollapsed/toggle, hidden, hide, unhide, uiStateLoaded }`. The hook takes
  `api` (from `useServices()` at the BookmarkList call site) — closes the UI-state view-rule violation.
- [ ] `renderHook` test (template: `useSimulation.router.test.tsx`) pinning the cross-threshold reset +
  the two-POST gating with a stub api + fake timers.
- [ ] BookmarkList calls `const { api } = useServices(); const ui = useBookmarkUiState({api, ...})`.
- [ ] `vitest` + `tsc` green (incl. the Task 2 tests). Commit: `refactor(p4b): extract useBookmarkUiState hook (routes UI-state via useServices)`.

---

### Task 4: Extract `BookmarkRow` (kill grouped/search markup duplication)

**Files:** Create `frontend/src/components/BookmarkRow.tsx` + `BookmarkRow.test.tsx`; modify `BookmarkList.tsx`.

- [ ] Diff the two row copies (grouped vs search-mode) line-by-line; the grouped copy additionally
  carries the inline-rename branch + a bookmark SVG. Build one `BookmarkRow` covering both via props
  (`bm, isSelected, multiSelect, flashedId, editing{Id,Name}, onClick, onContextMenu, on*` + an
  `allowRename` flag for the grouped path).
- [ ] Replace BOTH call sites with `<BookmarkRow .../>`. The Task 2 row-parity test must stay green.
- [ ] Leaf test (template: `BookmarkGeoLine.test.tsx`). `vitest` + `tsc` green. Commit:
  `refactor(p4b): single BookmarkRow replaces duplicated grouped/search markup`.

---

### Task 5: Extract `CategorySection`

**Files:** Create `frontend/src/components/CategorySection.tsx` + test; modify `BookmarkList.tsx`.

- [ ] Move the per-group IIFE (header: chevron/color/status badge/count/hide-eye + the tri-state
  multi-select checkbox using the `el.indeterminate` **ref-callback**) wrapping the collapsed body of
  `BookmarkRow`s. Props: `cat, bms, collapsed, status, selection slice, on{Toggle,Hide,row callbacks}`.
- [ ] Test the tri-state indeterminate math (none/some/all selected). `vitest` + `tsc` green. Commit:
  `refactor(p4b): extract CategorySection (tri-state header preserved)`.

---

### Task 6: Extract `BookmarkContextMenu`

**Files:** Create `frontend/src/components/BookmarkContextMenu.tsx` + test; modify `BookmarkList.tsx`.

- [ ] Move the portal menu **with all three guard mechanisms together**: the dismissal effect
  (pointerdown/contextmenu/keydown on `setTimeout(0)`), the close-reset effect, and the
  `contextMenuRef`/open-snapshot reverse-geocode stale-guard. `reverseGeocode` via `useServices().api`.
  Props: the bm + screen coords + the 9 action callbacks.
- [ ] Test: opening calls `api.reverseGeocode`; closing before resolve drops the address (move the
  Task 2 stale-guard assertion here if cleaner). `vitest` + `tsc` green. Commit:
  `refactor(p4b): extract BookmarkContextMenu (stale-guard intact, reverseGeocode via port)`.

---

### Task 7: Extract dialog components + shared utils

**Files:** Create `AddBookmarkDialog.tsx`, `CustomBookmarkDialog.tsx`, `EditBookmarkDialog.tsx`,
`EditCategoryModal.tsx` (under `components/`); move `trySplitLatLng` + color logic
(`COLOR_PALETTE`/`getCategoryColor`/`resolveColor`) into `frontend/src/utils/`; modify `BookmarkList.tsx`.

- [ ] Lift each controlled-form portal to its own file (local form state moves with it; inputs/outputs
  via props matching the current behavior). Move the shared pure helpers to `utils/` (+ a small util test).
- [ ] `vitest` + `tsc` green. Commit: `refactor(p4b): extract bookmark/category dialogs + shared utils`.

---

### Task 8: Extract `useBookmarkSelection` + `CategoryManagerPanel`

**Files:** Create `hooks/useBookmarkSelection.ts` (+ test), `components/CategoryManagerPanel.tsx`
(absorbing the already-nested `CategoryDeleteDropdown`); modify `BookmarkList.tsx`.

- [ ] `useBookmarkSelection()` owns `multiSelect`/`selectedIds`/`toggle`/`exit`/`handleBulkDelete`/
  select-all (one prop dep: `onBookmarkDelete`). Hook test for the batch-delete confirm + `Promise.all`.
- [ ] Move `CategoryManagerPanel` + `CategoryDeleteDropdown` to their own file.
- [ ] `vitest` + `tsc` green. Commit: `refactor(p4b): extract useBookmarkSelection + CategoryManagerPanel`.

---

### Task 9: Tighten the gate for the BookmarkList tree + final verify

**Files:** modify `frontend/.dependency-cruiser.cjs`.

- [ ] Confirm BookmarkList + its new children have **zero** direct `services/api`/`adapters` imports
  (`npx depcruise` shows the BookmarkList warnings gone). Add a scoped **error** rule:
```js
{
  name: "bookmarklist-no-direct-api",
  severity: "error",
  from: { path: "^src/components/(BookmarkList|BookmarkRow|CategorySection|BookmarkContextMenu|CategoryManagerPanel|AddBookmarkDialog|CustomBookmarkDialog|EditBookmarkDialog|EditCategoryModal)" },
  to: { path: "^src/(services/api|adapters)" },
},
```
- [ ] `npx depcruise` exits 0 (no BookmarkList-tree errors; App/MapView stay warnings). Re-run full
  `vitest run` + `tsc --noEmit` + `vitest run --coverage` (BookmarkList coverage ≥ baseline) + the e2e
  specs once. Commit: `chore(p4b): enforce no-direct-api for the BookmarkList tree`.

---

### Final: whole-branch review + finish

- Dispatch the adversarial whole-branch review (dimensions: behavior-equivalence vs the monolith,
  hexagon-lite/gate correctness, test quality, the load-bearing invariants). Fix confirmed findings.
- `finishing-a-development-branch`: full `vitest` + `tsc` + e2e green → present merge options to Ravi.
- Update CLAUDE.md/AGENTS.md frontend section if the gate/conventions need documenting.
