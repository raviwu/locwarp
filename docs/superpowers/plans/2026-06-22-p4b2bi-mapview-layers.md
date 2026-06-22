# P4b-2b-i — MapView Per-Layer Leaflet Hooks — Implementation Plan

> **For agentic workers:** Execute task-by-task via subagent-driven-development. Each layer = a VERBATIM
> ref-move into a `useXLayer(mapRef, …)` hook. No behavior change. MapView prop interface + e2e contract +
> localStorage keys FROZEN. Leaflet is jsdom-untestable — net is Playwright e2e (6) + the pure-helper units.

**Goal:** Extract the 8 imperative per-layer Leaflet effects from `MapView.tsx` into per-layer hooks.

**Spec:** `docs/superpowers/specs/2026-06-22-p4b2bi-mapview-layers-design.md`

## Global Constraints

- Frontend-only, **no behavior change**. `MapView` prop interface FROZEN (`App.tsx` untouched).
- After every commit: `npx vitest run` green + `npx tsc --noEmit` clean + `npx playwright test` green (6).
- `npx depcruise src --config .dependency-cruiser.cjs` → 0 errors (MapView stays api-clean + error-gated;
  new hooks import no `services/api`).
- **Per layer: move the ONE Leaflet ref + its add/remove/cleanup together** (no double-remove/orphan).
  Preserve signature-gating (dest/preview), zoomend-rebuild (bookmark/s2), and the wire-once + `*Ref`-mirror
  pattern verbatim. Reuse the P4b-2a pure helpers (`clusterByPixelDistance`, `build*Html`, `escapeHtml`).
- Frozen: e2e selectors (`.current-pos-marker`/`.dest-marker`/`path.route-flow-dash`), localStorage keys
  (`locwarp.s2_enabled`/`s2_level`).
- Each layer hook takes `mapRef` + the props/state its effect reads; guards `if (!mapRef.current) return`.

---

### Task 1: `useRoutePolylineLayer` (e2e-covered)

**Files:** Create `frontend/src/hooks/useRoutePolylineLayer.ts`; modify `MapView.tsx`.

- [ ] Move the route polyline effect (base line + animated flowing-arrow dash overlay) into the hook,
  owning its polyline ref(s) + cleanup. Inputs: `mapRef` + the route path/visibility props it reads.
- [ ] `npx playwright test` (pins `path.route-flow-dash` draw + idle-clear) + `vitest` + `tsc` green.
  Commit: `refactor(p4b2bi): extract useRoutePolylineLayer`.

---

### Task 2: `useCurrentPositionLayer` (e2e-covered; most logic)

**Files:** Create `frontend/src/hooks/useCurrentPositionLayer.ts`; modify `MapView.tsx`.

- [ ] Move the current-position marker effect: marker move-vs-recreate, avatar rebuild (`buildCurrentPositionHtml`),
  the **>500m auto-center heuristic**, and the **follow auto-pan**. Own the marker ref + `lastAvatarHtmlRef` +
  cleanup. Inputs: `mapRef`, `currentPosition`, `userAvatarHtml`, `followMode`, …
- [ ] Preserve the heuristic + follow logic VERBATIM. `npx playwright test` (pins `.current-pos-marker`
  presence + marker-effect independence) + `vitest` + `tsc` green.
  Commit: `refactor(p4b2bi): extract useCurrentPositionLayer (500m auto-center + follow preserved)`.

---

### Task 3: `useDestinationLayer` (e2e-covered)

**Files:** Create `frontend/src/hooks/useDestinationLayer.ts`; modify `MapView.tsx`.

- [ ] Move the signature-gated destination marker effect (`buildDestinationHtml`), owning its ref + cleanup.
- [ ] `npx playwright test` (pins `.dest-marker`) + `vitest` + `tsc` green.
  Commit: `refactor(p4b2bi): extract useDestinationLayer`.

---

### Task 4: `useRandomWalkCircleLayer` (no e2e net — verbatim)

**Files:** Create `frontend/src/hooks/useRandomWalkCircleLayer.ts`; modify `MapView.tsx`.

- [ ] Move the `L.circle` random-walk-radius effect, owning its circle ref + cleanup. Byte-identical body
  (no e2e net — verify by reading). `npx playwright test` + `vitest` + `tsc` green.
  Commit: `refactor(p4b2bi): extract useRandomWalkCircleLayer`.

---

### Task 5: `usePreviewPinLayer` (no e2e net — verbatim)

**Files:** Create `frontend/src/hooks/usePreviewPinLayer.ts`; modify `MapView.tsx`.

- [ ] Move the amber preview-pin effect (`buildPreviewHtml`) + click-to-dismiss, owning its ref + cleanup.
  Verbatim. `npx playwright test` + `vitest` + `tsc` green.
  Commit: `refactor(p4b2bi): extract usePreviewPinLayer`.

---

### Task 6: `useWaypointMarkersLayer` (no e2e net — verbatim; menu state stays lifted)

**Files:** Create `frontend/src/hooks/useWaypointMarkersLayer.ts`; modify `MapView.tsx`.

- [ ] Move the waypoint-markers rebuild effect (`buildWaypointHtml`) + the per-marker click that opens the
  waypoint mini-menu. The click handler sets the `wpMenu` state which STAYS lifted in MapView (the
  `WaypointMenu` JSX → P4b-2b-ii); pass an `onWaypointMenu(index, latlng)`-style callback in. Own the
  marker refs + the `*Ref` mirrors (for fresh click handlers) + cleanup. Verbatim.
- [ ] `npx playwright test` + `vitest` + `tsc` green. Commit: `refactor(p4b2bi): extract useWaypointMarkersLayer (menu state stays in MapView)`.

---

### Task 7: `useBookmarkMarkersLayer` (no e2e net — verbatim; biggest)

**Files:** Create `frontend/src/hooks/useBookmarkMarkersLayer.ts`; modify `MapView.tsx`.

- [ ] Move the bookmark-pins effect: px-distance clustering via `clusterByPixelDistance` (pure, already
  unit-tested) + single/cluster icon builders (`buildBookmarkPinHtml`/`buildBookmarkClusterHtml`/…, pure,
  unit-tested) + the cluster popup (`buildBookmarkClusterPopupHtml` + the `popupopen` DOM-query click
  handlers) + the **zoomend rebuild** listener. Own the marker/layer refs + cleanup. Inputs: `mapRef`,
  `bookmarkPins`, `showBookmarkPins`, `onTeleport`, … The algorithm is the unit-test net; keep the effect
  body byte-identical otherwise.
- [ ] `npx playwright test` + `vitest` + `tsc` green. Commit: `refactor(p4b2bi): extract useBookmarkMarkersLayer (clustering + zoomend rebuild)`.

---

### Task 8: `useS2Grid` (no e2e net — verbatim)

**Files:** Create `frontend/src/hooks/useS2Grid.ts`; modify `MapView.tsx`.

- [ ] Move the `s2Enabled`/`s2Level`/`s2Suppressed` state + localStorage persistence
  (`locwarp.s2_enabled`/`s2_level`, FROZEN keys) + the paint-on-moveend/zoomend grid-overlay effect. Return
  the state + setters MapView/the S2 button + the (still-inline) level-picker read. Own the grid layer ref +
  cleanup. The S2 level-picker JSX stays inline (→ P4b-2b-ii). Verbatim.
- [ ] `npx playwright test` + `vitest` + `tsc` green. Commit: `refactor(p4b2bi): extract useS2Grid hook`.

---

### Final: whole-branch review + finish

- Dispatch the adversarial whole-branch review (Leaflet ref-ownership equivalence per layer, the 500m/follow
  heuristic, clustering/zoomend rebuild, signature-gating, the frozen invariants), refute-verified. Fix
  confirmed findings (one wave).
- `finishing-a-development-branch`: full `vitest` + `tsc` + `playwright test` green → present merge options.
- Note P4b-2b-ii (popovers/menus) remains for the final MapView round.
