# Map Tearing Fix (raster basemap) — Design

**Date:** 2026-06-26
**Status:** Approved (scope ①+②)
**Author:** Ravi + Claude

## Problem

A user reported the map looking "torn" / 破圖 (gray tiles, half-loaded
tiles, a tearing band along the direction of travel) while a simulation is
running. The user was on the **default basemap**, which is the OpenStreetMap
raster `L.tileLayer` — not the WebGL "OpenFreeMap Liberty" layer. So the cause
must be explained on the raster path.

## Root cause (raster path)

Two compounding factors:

1. **`panTo` interrupt-storm.** In follow mode, `useCurrentPositionLayer.ts`
   runs a second effect (lines 151-159) that calls
   `map.panTo(latlng, { animate: true, duration: 0.4 })` on **every**
   `currentPosition` change. Backend sim ticks arrive every 0.5s (running) /
   1.0s (walking) / 0.2s (joystick) — all shorter than or comparable to the
   0.4s pan animation. Each new tick restarts the animation before it
   settles, so the pan center never comes to rest. Leaflet's `TileLayer._update`
   recomputes the leading-edge tile set against a perpetually-moving center,
   `_pruneTiles` evicts tiles and re-requests them, and the user sees a
   gray/half-loaded band where tiles are mid-flight.

2. **Public OSM endpoint rate-limit.** `tile.openstreetmap.org` rate-limits
   aggressively. Under the constant re-request churn from (1), some tile
   requests are throttled, widening and prolonging the gray band.

The earlier idea of an rAF-coalesce on `setCurrentPosition` is a **red herring
here**: ticks are 0.2-1.0s apart, never sub-frame, and the React Profiler
bench (`App.profiler.bench.test.tsx`, on `main`) measured exactly one commit
per tick. Coalescing buys nothing for this symptom; it is explicitly NOT in
scope.

## Fix (two changes)

### ① Follow-pan deadzone — `useCurrentPositionLayer.ts:151-159`

Replace the unconditional per-tick `panTo` with a **deadzone recenter**: only
pan when the marker has drifted out of a central box of the viewport.

- On each `currentPosition` change while `followMode` is on, project the
  marker to viewport pixels with `map.latLngToContainerPoint([lat, lng])` and
  read `map.getSize()`.
- If the marker is within the **central 50% box** (i.e. within ±25% of the
  viewport's half-width/half-height of center on BOTH axes), do **nothing** —
  the map stays still, tiles settle, no tear.
- Only when the marker exits that box (>25% off-center on either axis) call
  `map.panTo(latlng, { animate: true, duration: 0.4 })`. Because the next pan
  cannot fire until the marker crosses the box edge again (seconds away), this
  animation runs to completion uninterrupted — so `animate: true` stays (still
  smooth, no jump).

Exact predicate (kept inside the effect; no new exported function):

```ts
const map = mapRef.current;
if (!map) return;
const pt = map.latLngToContainerPoint([currentPosition.lat, currentPosition.lng]);
const size = map.getSize();
const offX = Math.abs(pt.x - size.x / 2);
const offY = Math.abs(pt.y - size.y / 2);
// central 50% box = within 25% of half-size from center on each axis
if (offX <= size.x * 0.25 && offY <= size.y * 0.25) return; // inside deadzone — don't pan
map.panTo([currentPosition.lat, currentPosition.lng], { animate: true, duration: 0.4 });
```

**Unchanged (out of scope for ①):**
- The first effect (lines 77-144): marker create/move via `setLatLng`
  (immediate — the marker never lags behind the deadzone), and the >500m
  teleport `setView` jump. Both stay byte-for-byte.
- `followMode` / `currentPosition` early-return guards (152-154) stay.

**Comment fix:** the comment at lines 146-149 wrongly claims "random walk can
be ~10 Hz". Rewrite it to describe the deadzone behavior and the real tick
cadence (0.2-1.0s).

### ② Default basemap OSM → CartoDB Voyager — `useBaseLayers.ts:138-141` + the FROZEN note

Change the saved-layer fallback from `'osm'` to `'carto'`:

```ts
const savedLayer = (() => {
  try { return localStorage.getItem('locwarp.tile_layer') || 'carto' }
  catch { return 'carto' }
})()
```

CartoDB Voyager is already a defined layer (lines 77-85): OSM data on the
CARTO CDN, 4 subdomains, built-in @2x retina, **no OSM rate-limit risk** — the
existing code comment already recommends it "when OSM feels laggy". This is
zero new dependencies.

- **Only affects users who never picked a basemap** (no
  `localStorage['locwarp.tile_layer']`). Any existing explicit choice
  (including an explicit `'osm'`) is untouched — the `initialKey` ternary
  (lines 150-156) already maps every stored key correctly, and the
  `baselayerchange` persistence (159-169) is unchanged.
- The `// Behavior is FROZEN: ... the default-layer choice ...` note at line 34
  must be updated to record that the default-layer choice was deliberately
  changed from OSM to CartoDB Voyager (with the reason: OSM raster rate-limit
  tearing under follow-mode panning). This is an intentional, approved
  un-freeze, not an accidental drift.

## Testing

No existing tests cover either hook. Both are effect-only hooks taking a
`mapRef`; mirror the established `useMapClick.test.tsx` pattern — `renderHook`
with a fake `mapRef.current` whose Leaflet methods are `vi.fn()` spies, and
`vi.mock('leaflet')` (plus the maplibre mocks from `MapView.test.tsx`) so no
real WebGL/`createObjectURL` runs in jsdom. The deadzone math lives on the map
object (`latLngToContainerPoint` / `getSize`), which the fake fully controls.

**① `useCurrentPositionLayer` follow-pan deadzone** (new test file):
- marker inside the deadzone (projected point near center) → `panTo` NOT called.
- marker outside the deadzone (projected point >25% off-center on x) → `panTo`
  called once with `{ animate: true, duration: 0.4 }`.
- `followMode === false` → `panTo` NOT called (early-return guard).

**② `useBaseLayers` default layer** (new test file):
- `localStorage` empty → the CartoDB layer (URL contains `cartocdn`) is the one
  added to the map; the OSM layer is NOT added.
- `localStorage['locwarp.tile_layer'] = 'osm'` → the OSM layer is added
  (existing explicit choice respected).
- `localStorage['locwarp.tile_layer'] = 'liberty'` → the Liberty layer is added
  (regression guard that the other key mappings still resolve).

## Constraints

- **No backend changes.** This is frontend-only.
- **No external dependency added** (CartoDB Voyager already defined).
- Green after every commit: `npx vitest run` (**862 baseline** + new tests),
  `npx tsc --noEmit` (0 errors), dependency-cruiser (0 errors). Vitest uses
  `fireEvent`/`renderHook` only.
- ② changes a behavior documented as FROZEN — deliberate and approved; the
  FROZEN comment must be updated in the same change so the doc stays truthful.

## Execution

One cluster branch off `main` (`7bf2f2f`), two tasks:
- **Task 1 (②):** small, self-contained default-basemap change + its test.
- **Task 2 (①):** deadzone follow-pan + comment fix + its tests.

Whole-branch review → ff-merge to `main`. Subagent-Driven Development.
