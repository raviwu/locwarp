# P4b-2b-i — MapView Per-Layer Leaflet Hooks — Design

**Date:** 2026-06-22
**Status:** Design — awaiting review
**Author:** Ravi + Claude

## Problem

P4b-2a shrank `MapView.tsx` (2867→2193 LOC) by extracting the map instance, base layers, leaflet-bar
buttons, and pure helpers, and built the e2e net. The remaining bulk is the **imperative per-layer
Leaflet effects** (each owns a Leaflet ref + add/remove/cleanup) and the presentational popovers/menus.
This round (P4b-2b-i) extracts the **per-layer hooks**; the popovers/menus are deferred to **P4b-2b-ii**.

## Decisions (locked with Ravi, 2026-06-22)

| Decision | Choice |
|----------|--------|
| **Scope (this round)** | P4b-2b-i: the 8 per-layer Leaflet hooks. Popovers/menus (RecentPlacesPopover, MapContextMenu, CoordInputStrip, S2LevelPicker, WaypointMenu) → P4b-2b-ii. |
| **Test net** | Verbatim ref-move per layer (move the ref + its cleanup together). e2e net covers `current-pos`/`dest`/`route`; the **prop-driven overlays (bookmark/preview/waypoint/radius) have no e2e net** and rely on verbatim moves + the existing pure-helper units (clustering, icon-html). No fragile jsdom Leaflet mock. |

## Goals

1. Move each Leaflet layer effect out of `MapView.tsx` into its own `useXLayer(mapRef, …)` hook, so MapView
   becomes a thin composition of layer hooks + (still-inline) popovers.
2. No behavior change. `MapView`'s prop interface FROZEN (`App.tsx` untouched). e2e CSS contract +
   localStorage keys FROZEN.

## Non-negotiable invariants

- **Leaflet layer ownership**: each hook owns exactly ONE layer ref + its add/remove/cleanup, moved
  together — no double-remove/orphan/leak. The signature-gating (dest/preview) + zoomend-rebuild
  (bookmark/s2) discipline preserved verbatim.
- **e2e CSS contract FROZEN**: `.current-pos-marker`, `.dest-marker`, `path.route-flow-dash`, `.leaflet-container`.
- **localStorage keys FROZEN**: `locwarp.s2_enabled`, `locwarp.s2_level` (the s2 layer); `locwarp.tile_layer` already in `useBaseLayers`.
- **Wire-once + `*Ref`-mirror**: per-marker click handlers wired once read fresh props via `*Ref` mirrors.
- **Pure helpers reused** (already extracted in P4b-2a): `clusterByPixelDistance`, `buildCurrentPositionHtml`/
  `buildDestinationHtml`/`buildPreviewHtml`/`buildWaypointHtml`/`buildBookmarkPinHtml`/`buildBookmarkClusterHtml`/…,
  `escapeHtml`. The layer hooks call these; do not re-inline.
- `mapRef` (from `useMapInstance`) is the shared input; layer effects guard `if (!mapRef.current) return`.
- single-WebSocket / WsRouter fan-out untouched (MapView doesn't subscribe).

## Architecture

Each layer → a hook in `frontend/src/hooks/` taking `mapRef` + the props/state its effect reads, owning its
ref + cleanup. MapView calls them after `useMapInstance`/`useBaseLayers`. No new api coupling (MapView stays
api-clean + error-gated from P4b-2a). dependency-cruiser stays 0 errors.

## Layer hooks (sequenced — e2e-covered first, then verbatim no-net)

**e2e-covered (the net catches regressions):**
1. `useRoutePolylineLayer(mapRef, routePath, …)` — base line + animated flowing-arrow dash overlay. e2e: `path.route-flow-dash`.
2. `useCurrentPositionLayer(mapRef, currentPosition, userAvatarHtml, followMode, …)` — marker move-vs-recreate, avatar rebuild, >500m auto-center, follow auto-pan. e2e: `.current-pos-marker`. (Has the most logic; uses `buildCurrentPositionHtml`.)
3. `useDestinationLayer(mapRef, destination, …)` — signature-gated marker. e2e: `.dest-marker`. Uses `buildDestinationHtml`.

**no e2e net (verbatim ref-move + unit-tested algorithms):**
4. `useRandomWalkCircleLayer(mapRef, currentPosition, randomWalkRadius, isRandomWalk, …)` — the `L.circle`. Tiny, verbatim.
5. `usePreviewPinLayer(mapRef, previewPin, onDismiss, …)` — amber pin + click-to-dismiss. Uses `buildPreviewHtml`. Verbatim.
6. `useWaypointMarkersLayer(mapRef, waypoints, …, onWaypointMenu)` — marker rebuild + per-marker click that opens the waypoint mini-menu. Uses `buildWaypointHtml`. The mini-menu JSX (`WaypointMenu`) + its `wpMenu` state STAY inline in MapView (→ P4b-2b-ii); the layer's click handler sets that lifted state. Verbatim move of the marker rebuild.
7. `useBookmarkMarkersLayer(mapRef, bookmarkPins, showBookmarkPins, onTeleport, …)` — the largest: px-distance clustering (`clusterByPixelDistance`, already unit-tested) + single/cluster icon builders (pure, unit-tested) + cluster popup + zoomend rebuild. Verbatim ref-move; the algorithm is the unit-test net.
8. `useS2Grid(mapRef, …)` — the `s2Enabled`/`s2Level`/`s2Suppressed` state + localStorage (`locwarp.s2_enabled`/`s2_level`) + the paint-on-moveend/zoomend effect (the grid overlay layer). The S2 **level-picker popover** + the S2 toggle button (already a `LeafletBarButton` from 2a) stay/were-handled elsewhere; the picker JSX → P4b-2b-ii. Verbatim.

After this round MapView is a thin shell of layer-hook calls + the still-inline popovers/menus (the P4b-2b-ii targets).

## Deferred to P4b-2b-ii (NOT this round)

`RecentPlacesPopover` (draggable), `MapContextMenu` (the reverse-geocode stale-guard + 7 actions —
same pattern as P4b-3's `BookmarkContextMenu`), `CoordInputStrip`, `S2LevelPicker`, `WaypointMenu`.

## Testing & verification

- After every commit: `npx vitest run` green, `npx tsc --noEmit` clean, AND `npx playwright test` green
  (the 6-test net) — esp. after the current-pos/dest/route layer moves.
- `npx depcruise src --config .dependency-cruiser.cjs` → 0 errors throughout (MapView stays api-clean +
  error-gated; the new hooks import no services/api).
- Final adversarial whole-branch review (Leaflet ref-ownership equivalence, the 500m/follow logic, the
  clustering/zoomend rebuild, the signature-gating), refute-verified, before merge.

## Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Leaflet ref double-remove/orphan on extraction | Move each ref + its cleanup together as one unit; one owner per layer; e2e for current-pos/dest/route |
| No e2e net for bookmark/preview/waypoint/radius | Verbatim ref-move; the clustering + icon-html algorithms are unit-tested; keep the effect bodies byte-identical |
| 500m auto-center / follow auto-pan regression (current-position) | Move the heuristic verbatim; e2e pins `.current-pos-marker` presence + marker-effect independence |
| zoomend-rebuild clustering regression | Verbatim; the `clusterByPixelDistance` unit test pins the algorithm |
| MapView prop interface drift → ripples to App | Freeze the prop interface; App.tsx untouched |
