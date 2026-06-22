# P4b — Frontend God-Component Decomposition (Design)

**Date:** 2026-06-22
**Status:** Design — awaiting review
**Author:** Ravi + Claude

## Problem

Three frontend god-components carry ~7600 LOC of mixed concerns:

| Component | LOC | Test coverage | Notes |
|-----------|-----|---------------|-------|
| `App.tsx` | 2639 | 1 socket-count test only | orchestrator; violates the view-rule (`import * as api`, 59 sites) |
| `components/MapView.tsx` | 2867 | 2 Playwright e2e only | imperative Leaflet; ~200 LOC dead dual-mode code |
| `components/BookmarkList.tsx` | 2109 | **zero tests** | props-driven; duplicated row markup; 3 direct `services/api` imports |

The hexagon-lite architecture and the extraction patterns **already exist** (`useBookmarks`-style state hooks, `useExternalChangeSubscriptions`-style subscriber hooks, `ApiGateway` port = `typeof api`, single-origin constant, `WsRouter` fan-out). P4b applies them — it does not invent new architecture. Two structural gaps make this risky: there is **no frontend layering gate** (the view-rule is convention-only and already violated in ~7 places), and the riskiest component (`BookmarkList`) has **no tests at all**.

## Decisions (locked with Ravi, 2026-06-22)

| Decision | Choice |
|----------|--------|
| **Scope per round** | Incremental — a layering gate + coverage baseline, then **one** god-component per round. |
| **First component** | **BookmarkList** — self-contained leaf (rendered via `ControlPanel`, props-driven), so internal decomposition has **zero ripple to App**; and it is the only 0%-coverage god-component (highest test ROI, lowest blast radius). |
| **Layering gate** | **dependency-cruiser, report-only** — the frontend analogue of the backend import-linter "353rd test"; tightened to error incrementally per cleaned component. |

## Overall P4b framing (sub-projects)

P4b is too large for one plan, so it is split into independently-shippable sub-projects:

- **P4b-0** — FE layering gate (dependency-cruiser, report-only) + coverage baseline. *(this round)*
- **P4b-3** — BookmarkList decomposition. *(this round)*
- **P4b-1** — App.tsx decomposition (leaf hooks: useToast / useRoutes / useRecent / useLocationMeta / useCatalog / useWifiAutoConnect / useSimActions). *(deferred — own round)*
- **P4b-2** — MapView.tsx decomposition (delete dead dual-mode; useMapInstance + per-layer hooks + presentational popovers). *(deferred — own round)*

Numbering follows the scan's risk ordering, not execution order. This document specifies **P4b-0 + P4b-3 only**. P4b-1 / P4b-2 are noted for context and need their own brainstorm before starting.

---

## P4b-0 — Layering gate + coverage baseline

### dependency-cruiser (report-only)

Add `dependency-cruiser` as a devDependency + a `depcruise` npm script + a `.dependency-cruiser.cjs` config encoding the hexagon-lite rules (all `severity: "warn"` this round — report-only, does not fail CI yet):

- **no-view-imports-api** — files under `src/components/**` and `src/App.tsx` may not import `services/api` or `adapters/**`. (Captures the existing ~7 violations as warnings — the baseline debt.)
- **only-root-opens-socket** — only `src/main.tsx` may import `adapters/ws/useWsRouter` or `hooks/useWebSocket`.
- **single-origin** — only `src/adapters/config.ts` may define the origin; nothing else imports a host/port literal (best-effort: forbid other files importing nothing — enforced mainly by the origin already living in one file; documented, not heavily machine-checked).

Wire a CI step (report-only — `|| true` or `--no-config-checks` non-failing) so the warning count is visible on every PR. **Tightening to error happens per-component**: when BookmarkList's subtree is clean (end of P4b-3), add a scoped **error** rule for `src/components/Bookmark*/**` → `services/api`/`adapters/**`, leaving App/MapView as warnings until their rounds.

> New devDependency — approved by Ravi (dependency-cruiser). No runtime dependency added.

### Coverage baseline

There is no coverage threshold gate today. Capture `npx vitest run --coverage` per-file numbers for `BookmarkList.tsx` (and note App/MapView) **before** any change, recorded in the plan, so a decomposition that silently drops covered lines is caught. At P4b-3 exit, optionally add a per-file `vitest.config.ts` threshold for the BookmarkList tree.

---

## P4b-3 — BookmarkList decomposition

### Principles

1. **Characterization-test-first** (danger-zone rule — the file has zero tests). Tests are written and green against the *current* monolith before any extraction, then must stay green through every step.
2. **`BookmarkListProps` stays stable.** `ControlPanel.tsx:946` and `App.tsx` are untouched — this is internal decomposition. Children keep speaking the legacy **name-shape** (`Bookmark.category: string`); the name↔id translation stays in `App.tsx`.
3. **Close the view-rule violation as we go.** The 3 direct `services/api` imports (`getBookmarkUiState` / `setBookmarkUiState` / `reverseGeocode`) move behind `useServices().api` — no new `ApiGateway` methods (it is `typeof api`, so they already exist). Convention: BookmarkList reads `useServices()`; extracted hooks take `api` as an argument (testable with a stub + `ServicesProvider` wrapper).
4. **Bottom-up, one seam per commit**, `vitest run` + `tsc --noEmit` green after each.

### Characterization tests (written first)

RTL `render(<BookmarkList {...makeProps()} />)` following the `ControlPanel.test.tsx` pattern (mock `../i18n` `useT` to identity; stub heavy children; wrap in `ServicesProvider` with a stub api; stub `localStorage`/`window.confirm`/clipboard). Pin:

- **AUTO_COLLAPSE_THRESHOLD = 30** cross-threshold reset: crossing up auto-collapses per the rule; crossing back down restores the *live* user choice via `savedExpandedRef` (not the session-start snapshot).
- **Hidden persistence gating:** `hiddenLoadedRef` / `uiStateLoaded` prevent echoing the initial fetch back as a write; hidden saves are immediate + strip since-deleted categories; expanded saves are debounced 400 ms.
- **Two-separate-POST partial update:** `{expanded_categories}` and `{hidden_categories}` are sent independently and must never clobber each other (backend merges).
- **Context-menu reverse-geocode stale-guard:** the `contextMenuRef` + open-snapshot + close-reset mechanisms drop a late address from a since-closed menu.
- **Multi-select batch delete:** select-all tri-state, `handleBulkDelete` confirm + `Promise.all`.
- **Search-vs-grouped row parity:** the two row-markup copies render the same bookmark identically (this test guards the de-duplication step below).

### Decomposition seams (bottom-up order)

1. **`useBookmarkUiState(api)` hook** — `collapsed` / `hidden` / `uiStateLoaded` + the threshold rule + the 3 backend calls. Takes `api` from `useServices()`. Quarantines the hardest logic *and* closes the view-rule violation for UI-state. **First** (highest value).
2. **`BookmarkRow`** leaf — collapses the duplicated grouped/search row markup into one component (the grouped copy additionally carries the inline-rename branch + a bookmark SVG — reconcile line-by-line). Modeled on the existing `BookmarkGeoLine.tsx` + test.
3. **`CategorySection`** — per-group header (chevron / color / status badge / count / hide-eye + tri-state multi-select checkbox via the `indeterminate` ref-callback) wrapping `BookmarkRow`.
4. **`BookmarkContextMenu`** — the ~295-line portal, moving **all three** stale-guard/dismissal mechanisms together; `reverseGeocode` via `useServices().api`.
5. **Dialog components** — `AddBookmarkDialog`, `CustomBookmarkDialog`, `EditBookmarkDialog`, `EditCategoryModal`; move `trySplitLatLng` + color logic (`COLOR_PALETTE` / `getCategoryColor` / `resolveColor`) to `utils/`.
6. **`useBookmarkSelection()` hook** — `multiSelect` / `selectedIds` / `handleBulkDelete` / select-all.
7. **`CategoryManagerPanel`** + the already-nested `CategoryDeleteDropdown` to their own file(s).

After the last seam, `BookmarkList.tsx` is a thin composition shell. Add the scoped dependency-cruiser **error** rule for the BookmarkList tree.

### Load-bearing invariants (must not change)

- **`BookmarkListProps` interface** (the `ControlPanel`/`App` contract) and the **name-shape** patch shape (`{name}` / `{name,lat,lng,category}`) App relies on.
- **localStorage keys + defaults:** `locwarp.bookmark_fly_gps` (default `true` = legacy teleport-on-click), `locwarp.bookmark_sort`.
- **Two-call partial UI-state POST** semantics; the debounce/immediate split + load gates.
- **Tri-state checkbox** uses a ref-callback to set `el.indeterminate` (React has no prop for it).
- **WsRouter fan-out** + **single-WebSocket** invariant: BookmarkList does not subscribe to WS today and must not start; no new `useWebSocket`/`useWsRouter`.

## Testing & verification

- `cd frontend && npx vitest run` + `npx tsc --noEmit` green after every commit; `App.singleConnection.test.tsx` and `adapters/ws/router.test.ts` (load-bearing) stay green.
- Coverage on `BookmarkList.tsx` must not drop below the captured baseline on any step.
- e2e (`sim.spec.ts` / `ws.spec.ts`) untouched (BookmarkList isn't exercised there) — run once at the end to confirm no incidental breakage.
- Final adversarial whole-branch review (multi-dimension, refute-verified) before merge.

## Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| 0-coverage file → blind refactor | Characterization tests written + green **before** any extraction |
| Grouped/search row markup differ subtly | Parity test first; reconcile line-by-line in the `BookmarkRow` step |
| Threshold-reset / hidden-gating regressions | Pinned by characterization tests before the `useBookmarkUiState` extraction |
| Context-menu stale-address leak | Move all three guard mechanisms together; dedicated test |
| Prop-interface drift rippling to App/ControlPanel | `BookmarkListProps` frozen; internal-only decomposition |
| New view-rule violations creep in | dependency-cruiser report-only catches them on every PR; scoped error rule at exit |
| Coverage silently drops (no gate) | Baseline captured; per-step check; optional per-file threshold at exit |
