# Map Tearing Fix (raster basemap) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the user-reported map tearing (破圖) during a running simulation on the default OpenStreetMap raster basemap.

**Architecture:** Two independent frontend changes. ② switches the *default* basemap from the public OSM raster endpoint (which rate-limits and tears under constant panning) to the already-defined CartoDB Voyager (CARTO CDN, no rate limit). ① stops the follow-mode camera from restarting a `panTo` animation on every sim tick — it now recenters only when the position marker drifts out of a central deadzone, so the map sits still between recenters and tiles finish loading.

**Tech Stack:** React 18 + TypeScript, Leaflet 1.9.4, Vitest + @testing-library/react (`renderHook`), Vite.

## Global Constraints

- **Frontend-only.** No backend file is touched. No HTTP/WS/IPC surface changes.
- **No new dependency.** CartoDB Voyager (`cartoLayer`) is already defined in `useBaseLayers.ts`.
- Green after EVERY commit: from `frontend/`, `npx vitest run` (**862 baseline** + new tests must all pass), `npx tsc --noEmit` (0 errors), and dependency-cruiser stays at 0 errors. Tests use `renderHook`/`fireEvent` only.
- Tests mock Leaflet + maplibre (jsdom cannot run their WebGL / `URL.createObjectURL` init) — mirror the `vi.mock` header in `frontend/src/components/MapView.test.tsx` and the fake-`mapRef` pattern in `frontend/src/hooks/useMapClick.test.tsx`.
- ② changes a behavior documented as FROZEN. This is deliberate and approved; the FROZEN comment MUST be updated in the same change so the doc stays truthful.
- Working directory for all frontend commands: `cd /Users/raviwu/personal/locwarp/frontend`.

---

### Task 1: Default basemap OSM → CartoDB Voyager (②)

**Files:**
- Modify: `frontend/src/hooks/useBaseLayers.ts:34` (the FROZEN comment) and `:138-141` (the `savedLayer` fallback)
- Test: `frontend/src/hooks/useBaseLayers.test.tsx` (create)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing other tasks rely on. `useBaseLayers(mapRef: React.RefObject<L.Map | null>)` signature is unchanged.

**Context for the implementer:** `useBaseLayers` is an effect-only hook that runs once on mount. It builds 6 base layers (`osmLayer`, `cartoLayer`, `esriSatLayer`, `libertyLayer`, `nlscLayer`, `gsiLayer`), reads `localStorage['locwarp.tile_layer']` to decide which one to add to the map, adds an `L.control.layers` switcher, and wires `map.on('baselayerchange', ...)` to persist the user's choice. Today the fallback when no choice is stored is `'osm'`; we change it to `'carto'`. Existing stored choices (including an explicit `'osm'`) are unaffected because the `initialKey` ternary at lines 150-156 already maps every stored key. The current code at lines 138-141:

```ts
    // Restore the user's previous choice so switching persists between launches.
    const savedLayer = (() => {
      try { return localStorage.getItem('locwarp.tile_layer') || 'osm' }
      catch { return 'osm' }
    })()
```

- [ ] **Step 1: Write the failing test**

Create `frontend/src/hooks/useBaseLayers.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

// Leaflet + maplibre have WebGL / URL.createObjectURL side-effects at module
// init that jsdom can't run — stub the whole chain (mirrors MapView.test.tsx).
// The leaflet stub makes L.tileLayer / L.maplibreGL return identifiable layer
// stubs (each carrying its url + its own addTo spy) so the test can assert
// WHICH layer the hook added to the map.
vi.mock('maplibre-gl', () => ({ default: {} }))
vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}))
vi.mock('@maplibre/maplibre-gl-leaflet', () => ({}))
vi.mock('leaflet', () => {
  const tileLayer = vi.fn((url: string, opts: any) => ({ url, opts, kind: 'tile', addTo: vi.fn() }))
  const maplibreGL = vi.fn((opts: any) => ({ url: 'liberty', opts, kind: 'maplibre', addTo: vi.fn() }))
  const control = { layers: vi.fn(() => ({ addTo: vi.fn() })) }
  return { default: { tileLayer, maplibreGL, control } }
})

import L from 'leaflet'
import { useBaseLayers } from './useBaseLayers'

const tileLayerMock = (L as any).tileLayer as ReturnType<typeof vi.fn>
const maplibreMock = (L as any).maplibreGL as ReturnType<typeof vi.fn>

// Find the layer stub whose tile URL contains a substring (e.g. 'cartocdn').
function tileStubByUrl(substr: string): any {
  const r = tileLayerMock.mock.results.find((res) => String(res.value?.url).includes(substr))
  return r?.value
}

function renderWith(stored: string | null) {
  const map = { on: vi.fn() }
  const mapRef = { current: map } as any
  if (stored === null) localStorage.removeItem('locwarp.tile_layer')
  else localStorage.setItem('locwarp.tile_layer', stored)
  renderHook(() => useBaseLayers(mapRef))
  return { map }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

describe('useBaseLayers — default-layer choice', () => {
  it('adds CartoDB Voyager (not OSM) when no layer was ever chosen', () => {
    renderWith(null)
    const carto = tileStubByUrl('cartocdn')
    const osm = tileStubByUrl('openstreetmap')
    expect(carto.addTo).toHaveBeenCalledTimes(1)
    expect(osm.addTo).not.toHaveBeenCalled()
  })

  it('respects an explicit stored OSM choice', () => {
    renderWith('osm')
    const carto = tileStubByUrl('cartocdn')
    const osm = tileStubByUrl('openstreetmap')
    expect(osm.addTo).toHaveBeenCalledTimes(1)
    expect(carto.addTo).not.toHaveBeenCalled()
  })

  it('respects an explicit stored Liberty (vector) choice', () => {
    renderWith('liberty')
    expect(maplibreMock).toHaveBeenCalledTimes(1)
    const liberty = maplibreMock.mock.results[0].value
    expect(liberty.addTo).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/hooks/useBaseLayers.test.tsx`
Expected: the first test FAILS — `carto.addTo` is not called (and `osm.addTo` IS called) because the default is still `'osm'`. The other two tests pass.

- [ ] **Step 3: Change the default fallback**

In `frontend/src/hooks/useBaseLayers.ts`, change the `savedLayer` fallback (lines 138-141) from `'osm'` to `'carto'`:

```ts
    // Restore the user's previous choice so switching persists between launches.
    // Default (no stored choice) is CartoDB Voyager, NOT OSM — see the header
    // note: the public OSM raster endpoint rate-limits under follow-mode
    // panning and tears.
    const savedLayer = (() => {
      try { return localStorage.getItem('locwarp.tile_layer') || 'carto' }
      catch { return 'carto' }
    })()
```

- [ ] **Step 4: Update the FROZEN comment**

In `frontend/src/hooks/useBaseLayers.ts`, replace the FROZEN note at line 34 (currently two lines):

```ts
// Behavior is FROZEN: the localStorage key, the default-layer choice, the layer
// set + order, and the switcher position are all preserved exactly.
```

with:

```ts
// Behavior is mostly FROZEN: the localStorage key, the layer set + order, and
// the switcher position are preserved exactly. The DEFAULT-layer choice was
// deliberately changed 2026-06-26 from OSM to CartoDB Voyager — the public OSM
// raster endpoint rate-limits under follow-mode panning and produced the
// reported map tearing (破圖). CartoDB Voyager is OSM data on the CARTO CDN
// with no such limit. Only users who never picked a basemap are affected;
// any stored choice (including an explicit 'osm') is untouched.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest run src/hooks/useBaseLayers.test.tsx`
Expected: PASS (3/3).

- [ ] **Step 6: Type-check**

Run: `npx tsc --noEmit`
Expected: 0 errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/useBaseLayers.ts frontend/src/hooks/useBaseLayers.test.tsx
git commit -m "fix(map): default basemap OSM -> CartoDB Voyager (raster tearing)

The public OSM raster endpoint rate-limits under follow-mode panning,
producing the reported map 破圖. CartoDB Voyager is already defined (OSM
data on the CARTO CDN, no rate limit) — only the default fallback changes,
so users who never picked a basemap get it; any stored choice is untouched.
Updates the FROZEN-behavior note to record the deliberate default change.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

### Task 2: Follow-pan deadzone (①)

**Files:**
- Modify: `frontend/src/hooks/useCurrentPositionLayer.ts:146-159` (the comment + the second `useEffect`)
- Test: `frontend/src/hooks/useCurrentPositionLayer.test.tsx` (create)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: nothing. `useCurrentPositionLayer(mapRef, { currentPosition, userAvatarHtml, followMode, prevPositionRef })` signature is unchanged.

**Context for the implementer:** `useCurrentPositionLayer` has two effects. The FIRST (lines 77-144) creates/moves the marker (`setLatLng`) and does a `setView` jump on the first position or a >500m teleport — **leave it untouched**. The SECOND (lines 151-159) is the follow-mode auto-pan; today it calls `map.panTo(latlng, { animate: true, duration: 0.4 })` on every `currentPosition` change. Because sim ticks arrive every 0.2-1.0s — shorter than the 0.4s pan animation — each tick restarts the animation before it settles, so the tile layer never stops pruning + re-requesting tiles (the tearing). The fix: only `panTo` when the marker has drifted out of the central 50% of the viewport. The current code at lines 146-159:

```ts
  // Auto-pan the map to the current position whenever follow mode is on.
  // Uses panTo with a short animation so rapid backend ticks (random walk
  // can be ~10 Hz) blend into a smooth camera trail rather than jumpy
  // snaps. Programmatic panTo does NOT fire dragstart, so the auto-disable
  // wired at map init is safe.
  useEffect(() => {
    if (!followMode || !currentPosition) return;
    const map = mapRef.current;
    if (!map) return;
    map.panTo([currentPosition.lat, currentPosition.lng], {
      animate: true,
      duration: 0.4,
    });
  }, [currentPosition, followMode]);
```

- [ ] **Step 1: Write the failing test**

Create `frontend/src/hooks/useCurrentPositionLayer.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

// Stub Leaflet (jsdom can't run its DOM/WebGL init). L.marker returns a stub
// with the methods the first effect calls; the deadzone math lives on the MAP
// object (latLngToContainerPoint / getSize), which the fake map fully controls.
vi.mock('leaflet', () => ({
  default: {
    divIcon: vi.fn(() => ({})),
    marker: vi.fn(() => ({ addTo: vi.fn(function (this: any) { return this }), setLatLng: vi.fn(), remove: vi.fn() })),
  },
}))

import { useCurrentPositionLayer } from './useCurrentPositionLayer'

// Fake L.Map: only the methods the hook calls. latLngToContainerPoint is set
// per-test to place the marker inside or outside the deadzone. Viewport is
// 800x600 so the central 50% box is x in [200,600], y in [150,450].
function makeMap(pt: { x: number; y: number }) {
  return {
    panTo: vi.fn(),
    setView: vi.fn(),
    getZoom: vi.fn(() => 15),
    getSize: vi.fn(() => ({ x: 800, y: 600 })),
    latLngToContainerPoint: vi.fn(() => pt),
  }
}

function render(opts: { pt: { x: number; y: number }; followMode?: boolean }) {
  const map = makeMap(opts.pt)
  const mapRef = { current: map } as any
  const prevPositionRef = { current: null as any }
  renderHook(() =>
    useCurrentPositionLayer(mapRef, {
      currentPosition: { lat: 25, lng: 121 },
      userAvatarHtml: undefined,
      followMode: opts.followMode ?? true,
      prevPositionRef,
    }),
  )
  return { map }
}

beforeEach(() => { vi.clearAllMocks() })

describe('useCurrentPositionLayer — follow-pan deadzone', () => {
  it('does NOT pan when the marker is inside the central deadzone', () => {
    // Dead center of an 800x600 viewport.
    const { map } = render({ pt: { x: 400, y: 300 } })
    expect(map.panTo).not.toHaveBeenCalled()
  })

  it('pans when the marker drifts out of the deadzone (x axis)', () => {
    // x=700 is 300px off center > 25% of 800 (=200) → outside the box.
    const { map } = render({ pt: { x: 700, y: 300 } })
    expect(map.panTo).toHaveBeenCalledTimes(1)
    expect(map.panTo).toHaveBeenCalledWith([25, 121], { animate: true, duration: 0.4 })
  })

  it('never pans when follow mode is off, even far off-center', () => {
    const { map } = render({ pt: { x: 790, y: 590 }, followMode: false })
    expect(map.panTo).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/hooks/useCurrentPositionLayer.test.tsx`
Expected: the first test FAILS — with the current unconditional `panTo`, `map.panTo` IS called even at dead center. (The third test passes; the second passes incidentally.)

- [ ] **Step 3: Replace the follow-pan effect with the deadzone version**

In `frontend/src/hooks/useCurrentPositionLayer.ts`, replace lines 146-159 (the comment + the second `useEffect`) with:

```ts
  // Auto-pan the map to the current position in follow mode, but ONLY when the
  // marker has drifted out of a central deadzone (the central 50% of the
  // viewport). Recentering on every tick restarted the 0.4s pan animation
  // before it could settle — sim ticks arrive every 0.2-1.0s — so the tile
  // layer never stopped pruning + re-requesting tiles, producing a torn /
  // half-loaded band along the direction of travel (worsened by the OSM
  // endpoint's rate limit). With the deadzone, most ticks leave the map still
  // (tiles settle); the marker only reaches the box edge every few seconds, so
  // each pan runs to completion uninterrupted and animate:true stays smooth.
  // Programmatic panTo does NOT fire dragstart, so the auto-disable wired at
  // map init is safe.
  useEffect(() => {
    if (!followMode || !currentPosition) return;
    const map = mapRef.current;
    if (!map) return;
    const pt = map.latLngToContainerPoint([currentPosition.lat, currentPosition.lng]);
    const size = map.getSize();
    const offX = Math.abs(pt.x - size.x / 2);
    const offY = Math.abs(pt.y - size.y / 2);
    // Inside the central 50% box (within 25% of half-size from center on BOTH
    // axes) → leave the map still so tiles can finish loading.
    if (offX <= size.x * 0.25 && offY <= size.y * 0.25) return;
    map.panTo([currentPosition.lat, currentPosition.lng], {
      animate: true,
      duration: 0.4,
    });
  }, [currentPosition, followMode]);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/hooks/useCurrentPositionLayer.test.tsx`
Expected: PASS (3/3).

- [ ] **Step 5: Type-check**

Run: `npx tsc --noEmit`
Expected: 0 errors.

- [ ] **Step 6: Run the full frontend suite + dependency-cruiser**

Run: `npx vitest run` then `npm run depcruise` (defined as `depcruise src --config .dependency-cruiser.cjs`).
Expected: all vitest pass (862 baseline + 6 new = 868), depcruise 0 errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/useCurrentPositionLayer.ts frontend/src/hooks/useCurrentPositionLayer.test.tsx
git commit -m "fix(map): deadzone the follow-mode pan to stop raster tile tearing

Follow mode restarted a 0.4s animated panTo on every sim tick (0.2-1.0s),
so the pan center never settled and the tile layer pruned + re-requested
tiles continuously — the reported 破圖. Now recenter only when the marker
leaves the central 50% box; most ticks leave the map still so tiles finish
loading, and each recenter pan runs to completion (animate:true kept).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

## Self-Review

**1. Spec coverage:**
- Spec ① (deadzone follow-pan, `useCurrentPositionLayer.ts:151-159`, central 50% box, keep `animate:true`, comment fix) → Task 2. ✓
- Spec ② (default `'osm'`→`'carto'` at `useBaseLayers.ts:138-141`, update FROZEN note, existing choices untouched) → Task 1. ✓
- Spec test plan (deadzone: inside→no pan, outside→pan, follow-off→no pan; basemap: empty→carto, 'osm'→osm, 'liberty'→liberty; `useMapClick` fake-`mapRef` + `vi.mock('leaflet')`) → both tasks' tests. ✓
- Spec "rAF-coalesce explicitly NOT in scope" → no task touches `useSimulation.ts` / `setCurrentPosition`. ✓
- Spec constraints (frontend-only, no new dep, green every commit, FROZEN note updated) → Global Constraints + Task 1 Step 4. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; every test step shows complete test code and the exact command + expected result. ✓

**3. Type consistency:** `useBaseLayers(mapRef)` and `useCurrentPositionLayer(mapRef, opts)` signatures match the existing source. The deadzone uses `latLngToContainerPoint` / `getSize` (both real `L.Map` methods returning `L.Point` with `.x`/`.y`). `panTo(LatLngExpression, { animate, duration })` matches the existing call. ✓
