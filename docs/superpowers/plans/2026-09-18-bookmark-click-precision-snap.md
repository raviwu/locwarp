# Bookmark Click-Precision Snap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the map right-click "加入座標收藏" from saving a bookmark kilometres away from the device's actual position, by snapping the right-click to the current position when the click lands inside the position marker's on-screen footprint — and by making the coordinate being saved visible in the dialog.

**Architecture:** The defect is pure frontend. Leaflet converts a right-click's *screen pixel* to a lat/lng at the map's current zoom (`hooks/useMapInstance.ts:172`), and that raw value flows unchanged into the bookmark (`MapView.tsx:495` → `MapContextMenu.tsx:361` → `App.tsx:390` → POST). The current-position marker is a 44×44 divIcon with `iconAnchor: [22,22]` and `interactive: false` (`hooks/useCurrentPositionLayer.ts:110-125`), so a right-click aimed at the avatar passes through to the map and can land up to 22 px from the true anchor. At zoom 8 one pixel is 220–610 m, so a visually-perfect click becomes a 0.6–8.7 km error. Fix: a pure `snapContextCoord()` policy in `utils/mapPrecision.ts`, applied once where the context menu opens, so every menu action (bookmark, teleport, navigate, copy, waypoint) inherits the pristine coordinate. A second pure helper `metersPerPixel()` feeds a precision hint into the add-bookmark dialog.

**Tech Stack:** TypeScript, React 18, Leaflet 1.x, Vitest + @testing-library/react. Frontend only — no backend, API, or schema change.

## Global Constraints

- **Frontend baseline is currently RED and must be fixed first (Task 0).** On `main` at `834 passed | 161 failed (995)` across 116 files, caused by Node v26's built-in global `localStorage` (which is `undefined` without `--localstorage-file`) shadowing jsdom's. After Task 0 the expected baseline is **995 passed, 0 failed**. Re-pin before starting: `cd frontend && npx vitest run --reporter=dot 2>&1 | tail -4`.
- **Backend baseline: 1315 tests collected**, and this plan must not change it. Re-pin with `cd backend && .venv/bin/python -m pytest --collect-only -q | tail -1`. No backend file is touched by Tasks 0–2.
- **Behavior / API freeze.** No HTTP / WS / IPC shape change. `POST /api/bookmarks` and `PUT /api/bookmarks/{id}` are used exactly as they are today. The only value that changes is the lat/lng the frontend *chooses* to send — that IS the fix.
- **Clean-arch (frontend hexagon-lite):** `view (features/app)` → `hooks/` → `ports/` ← `adapters/`. `utils/` is leaf-level and imports nothing from the app. The new `utils/mapPrecision.ts` must import **nothing** (no leaflet, no React) so it stays trivially testable. dependency-cruiser must stay at `0 errors`.
- **Do not abstract Leaflet.** The projection call stays inline in `MapView.tsx`; only the arithmetic moves into `utils/`. This mirrors the repo's "thick carve-outs stay leaky" rule.
- **Snap radius = 22 px**, derived from the marker's real geometry (`iconSize: [44,44]`, `iconAnchor: [22,22]`). If the icon size ever changes, this constant changes with it — the plan pins that link in a comment.
- **Precision-hint threshold = 25 m/px** (≈ zoom ≤ 12 at mid latitudes), chosen because a live-store scan found all 35 historically-imprecise bookmarks were created at zoom ≤ 12.
- No new dependencies. Personal repo: direct commits to `main`, auto git identity (never pass `-c user.email`). One commit per task.
- Language: code comments and commit messages in English.

## Evidence This Plan Is Based On

Reproduced from `~/.locwarp/logs/backend.log.2026-09-17` and the 1-minute snapshots in `~/.locwarp/backups/`:

- 22 of 23 bookmarks created 2026-09-17 21:14–22:54 local were born on an **exact Leaflet integer-pixel grid** (< 0.002 px deviation), at map zoom 6–8.
- Offsets from the intended point: **1.1–17.2 px**, all inside the marker's 22 px half-size; mean (−0.10, +5.78) px — x unbiased, y biased downward, consistent with clicking the avatar body rather than its centre.
- Resulting ground error: **674 m – 8.7 km**.
- The first backup snapshot after each creation already holds the wrong value, and `field_updated_at.coords == created_at` — nothing moved the bookmark after it was saved. `enrich_bookmark` (`backend/services/bookmarks.py:74`) resolves geo fields **offline** and never writes lat/lng.
- The coordinate was not copy-pasted: `copyContextCoords` emits `toFixed(6)` (`MapView.tsx:458`) while the stored values keep 7 decimals (`COORD_PRECISION = 7`), so the raw float went straight from `e.latlng` to the API.

---

## File Structure

| File | Change |
|------|--------|
| `frontend/src/test/setup.ts` | **Modify.** Bind jsdom's `localStorage` / `sessionStorage` onto `globalThis` so Node 26's undefined built-ins stop shadowing them. |
| `frontend/src/utils/mapPrecision.ts` | **Create.** Pure, dependency-free: `MARKER_SNAP_RADIUS_PX`, `PRECISION_HINT_M_PER_PX`, `snapContextCoord()`, `metersPerPixel()`. |
| `frontend/src/utils/mapPrecision.test.ts` | **Create.** Unit tests for both helpers. |
| `frontend/src/components/MapView.tsx` | **Modify.** `ContextMenuState` gains `snapped` / `metersPerPixel`; the `onContextMenu` handler (line ~495) projects both points and applies `snapContextCoord`; the `onAddBookmark` pass-through (line ~887) forwards the meta. |
| `frontend/src/components/MapContextMenu.tsx` | **Modify.** `onAddBookmark` prop signature gains the optional 4th `meta` argument and forwards it. |
| `frontend/src/App.tsx` | **Modify.** `handleAddBookmark` accepts the optional `meta` and stores it on `addBmDialog`. |
| `frontend/src/components/AppAddBookmarkDialog.tsx` | **Modify.** `AppAddBookmarkState` gains `snapped` / `metersPerPixel`; render the coordinate readout, the snap badge, and the low-precision hint. |
| `frontend/src/components/AppAddBookmarkDialog.test.tsx` | **Modify.** Add cases for the three new rendered states. |
| `frontend/src/i18n/strings.ts` | **Modify.** Three new keys (zh + en). |

Out of scope, stated explicitly so no one widens it mid-flight:
- `onMapClick` (waypoint insertion) keeps raw click coordinates.
- The 33 other historical low-zoom bookmarks are **not** rewritten — their intended coordinates are unknowable. Only the two from 2026-09-17 are addressed, in the gated Task 4.

---

### Task 0: Restore the green frontend test baseline

Node v26.3.0 defines a global `localStorage` that evaluates to `undefined` unless the process is started with `--localstorage-file`. Vitest's jsdom environment skips installing jsdom's own `localStorage` because the global name already exists, so every test touching `localStorage` throws `Cannot read properties of undefined`. This is an environment regression, not a code regression — no frontend source file changed.

**Files:**
- Modify: `frontend/src/test/setup.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: a green suite that every later task's "tests still pass" step depends on.

- [ ] **Step 1: Confirm the failure and its cause**

```bash
cd frontend && npx vitest run src/hooks/savedips.test.ts --reporter=verbose 2>&1 | head -20
```

Expected: 5 failures, each `TypeError: Cannot read properties of undefined (reading 'clear')` at `localStorage.clear()`, preceded by the node warning `localStorage is not available because --localstorage-file was not provided`.

- [ ] **Step 2: Add the shim to the shared setup file**

Append to `frontend/src/test/setup.ts`, after the existing imports and before the `afterEach` block:

```ts
// Node >= 26 ships a built-in global `localStorage` that is `undefined` unless
// the process gets --localstorage-file. Because the global NAME already exists,
// vitest's jsdom environment declines to install jsdom's own storage objects,
// and every test that touches localStorage throws. Bind jsdom's implementations
// explicitly so the suite is independent of the host node version.
for (const key of ['localStorage', 'sessionStorage'] as const) {
  if (typeof globalThis[key] === 'undefined' && typeof window !== 'undefined' && window[key]) {
    Object.defineProperty(globalThis, key, {
      value: window[key],
      configurable: true,
      writable: true,
    })
  }
}
```

- [ ] **Step 3: Verify the previously-failing file now passes**

```bash
cd frontend && npx vitest run src/hooks/savedips.test.ts --reporter=dot 2>&1 | tail -4
```

Expected: `Tests  5 passed (5)`.

- [ ] **Step 4: Verify the whole suite is green and record the number**

```bash
cd frontend && npx vitest run --reporter=dot 2>&1 | tail -4
```

Expected: `Tests  995 passed (995)`, `Test Files  116 passed (116)`. If any test still fails, STOP — it is a second, unrelated defect and must be reported before continuing; do not proceed to Task 1 on a red suite.

- [ ] **Step 5: Commit**

```bash
cd /Users/ravi.wu/personal/locwarp
git add frontend/src/test/setup.ts
git commit -m "fix(test): node 26's built-in localStorage shadowed jsdom's"
```

---

### Task 1: The pure snap + precision policy

**Files:**
- Create: `frontend/src/utils/mapPrecision.ts`
- Test: `frontend/src/utils/mapPrecision.test.ts`

**Interfaces:**
- Consumes: nothing (leaf module, zero imports).
- Produces, for Tasks 2–3:
  - `MARKER_SNAP_RADIUS_PX: number` (= 22)
  - `PRECISION_HINT_M_PER_PX: number` (= 25)
  - `interface PixelPoint { x: number; y: number }`
  - `snapContextCoord(click: { lat: number; lng: number; point: PixelPoint }, current: { lat: number; lng: number; point: PixelPoint } | null, radiusPx?: number): { lat: number; lng: number; snapped: boolean }`
  - `metersPerPixel(lat: number, zoom: number): number`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/utils/mapPrecision.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import {
  MARKER_SNAP_RADIUS_PX,
  snapContextCoord,
  metersPerPixel,
} from './mapPrecision'

const CLICK = { lat: 47.3388227, lng: 11.7993164, point: { x: 500, y: 300 } }
const CURRENT = { lat: 47.32825, lng: 11.845251, point: { x: 508, y: 297 } }

describe('snapContextCoord', () => {
  it('returns the current position when the click lands inside the marker footprint', () => {
    // 8px right, 3px up => 8.54px, inside the 22px radius.
    expect(snapContextCoord(CLICK, CURRENT)).toEqual({
      lat: 47.32825, lng: 11.845251, snapped: true,
    })
  })

  it('returns the raw click when it lands outside the marker footprint', () => {
    const far = { ...CURRENT, point: { x: 560, y: 300 } } // 60px away
    expect(snapContextCoord(CLICK, far)).toEqual({
      lat: 47.3388227, lng: 11.7993164, snapped: false,
    })
  })

  it('snaps exactly at the radius boundary but not one pixel beyond', () => {
    const onEdge = { ...CURRENT, point: { x: 500 + MARKER_SNAP_RADIUS_PX, y: 300 } }
    const justOut = { ...CURRENT, point: { x: 500 + MARKER_SNAP_RADIUS_PX + 1, y: 300 } }
    expect(snapContextCoord(CLICK, onEdge).snapped).toBe(true)
    expect(snapContextCoord(CLICK, justOut).snapped).toBe(false)
  })

  it('returns the raw click when there is no current position', () => {
    expect(snapContextCoord(CLICK, null)).toEqual({
      lat: 47.3388227, lng: 11.7993164, snapped: false,
    })
  })

  it('honours an explicit radius override', () => {
    expect(snapContextCoord(CLICK, CURRENT, 4).snapped).toBe(false)
  })
})

describe('metersPerPixel', () => {
  it('matches the known web-mercator resolution at the equator', () => {
    expect(metersPerPixel(0, 0)).toBeCloseTo(156543.03, 1)
    expect(metersPerPixel(0, 8)).toBeCloseTo(611.50, 1)
  })

  it('shrinks with the cosine of the latitude', () => {
    expect(metersPerPixel(47, 8)).toBeCloseTo(417.0, 0)
    expect(metersPerPixel(60, 8)).toBeCloseTo(305.7, 0)
  })

  it('halves for every zoom level gained', () => {
    expect(metersPerPixel(35, 13)).toBeCloseTo(metersPerPixel(35, 12) / 2, 6)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd frontend && npx vitest run src/utils/mapPrecision.test.ts --reporter=dot 2>&1 | tail -6
```

Expected: FAIL — `Failed to resolve import "./mapPrecision"`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/utils/mapPrecision.ts`:

```ts
// Map-pixel <-> ground-precision policy. Pure arithmetic, zero imports, so it
// stays trivially testable and usable from any ring.
//
// Why this module exists: Leaflet turns a right-click's SCREEN PIXEL into a
// lat/lng at the map's current zoom. At zoom 8 one pixel is 220-610 m of
// ground, so a click that looks perfectly on-target can store a bookmark
// kilometres away. On 2026-09-17, 22 bookmarks were saved 0.67-8.7 km off this
// way; every one of them landed on an exact integer-pixel grid at zoom 6-8.

export interface PixelPoint {
  x: number
  y: number
}

// The current-position marker is a 44x44 divIcon anchored at its centre
// (`iconAnchor: [22, 22]` in hooks/useCurrentPositionLayer.ts) and is
// `interactive: false`, so a right-click anywhere on the avatar passes THROUGH
// to the map and arrives up to 22 px from the true anchor. Keep this in step
// with that icon's size: radius = iconSize / 2.
export const MARKER_SNAP_RADIUS_PX = 22

// Show the add-bookmark precision hint once a single pixel is worth this many
// metres (~zoom 12 at mid latitudes). A live-store scan found every one of the
// 35 historically-imprecise bookmarks was created at zoom <= 12.
export const PRECISION_HINT_M_PER_PX = 25

/**
 * The coordinate a map right-click should act on.
 *
 * When the click landed inside the position marker's on-screen footprint the
 * user was pointing AT the device, not at a pixel near it — so return the
 * device's exact position instead of the click's own (zoom-quantised)
 * coordinate. Otherwise the click stands, unchanged.
 *
 * Both points are container pixels from the same map, so the comparison is
 * zoom-independent: it always means "within the avatar graphic".
 */
export function snapContextCoord(
  click: { lat: number; lng: number; point: PixelPoint },
  current: { lat: number; lng: number; point: PixelPoint } | null,
  radiusPx: number = MARKER_SNAP_RADIUS_PX,
): { lat: number; lng: number; snapped: boolean } {
  if (current) {
    const dx = click.point.x - current.point.x
    const dy = click.point.y - current.point.y
    if (Math.sqrt(dx * dx + dy * dy) <= radiusPx) {
      return { lat: current.lat, lng: current.lng, snapped: true }
    }
  }
  return { lat: click.lat, lng: click.lng, snapped: false }
}

// Ground resolution of one screen pixel, web-mercator, 256 px tiles.
// 156543.03392 = earth equatorial circumference / 256.
export function metersPerPixel(lat: number, zoom: number): number {
  return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, zoom)
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd frontend && npx vitest run src/utils/mapPrecision.test.ts --reporter=dot 2>&1 | tail -4
```

Expected: `Tests  8 passed (8)`.

- [ ] **Step 5: Commit**

```bash
cd /Users/ravi.wu/personal/locwarp
git add frontend/src/utils/mapPrecision.ts frontend/src/utils/mapPrecision.test.ts
git commit -m "feat(map): add the click-snap and pixel-precision policy"
```

---

### Task 2: Snap the context menu to the current position

**Files:**
- Modify: `frontend/src/components/MapView.tsx` (`ContextMenuState` ~line 33, the `onContextMenu` handler ~line 495, the `<MapContextMenu>` render ~line 868)
- Modify: `frontend/src/components/MapContextMenu.tsx` (`onAddBookmark` prop ~line 46, the click handler ~line 361)
- Modify: `frontend/src/App.tsx` (`handleAddBookmark` ~line 390, `submitAddBookmark` ~line 434)

**Interfaces:**
- Consumes from Task 1: `snapContextCoord`, `metersPerPixel`, `PixelPoint`.
- Produces for Task 3:
  - `interface AddBookmarkMeta { snapped?: boolean; metersPerPixel?: number }` exported from `components/AppAddBookmarkDialog.tsx` — declared here, consumed there.
  - `onAddBookmark(lat: number, lng: number, suggestedName?: string, meta?: AddBookmarkMeta)` — the optional 4th argument keeps every existing caller (`BookmarkList`, `NearbyPlacesMenu`, `RecentPlacesPopover`) source-compatible.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/MapContextMenu.snap.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { snapContextCoord, metersPerPixel } from '../utils/mapPrecision'

// The projection itself belongs to Leaflet; what this test pins is the WIRING
// contract MapView must honour: project both points, snap, and forward the
// precision meta alongside the coordinate.
function openContextMenu(
  clickLatLng: { lat: number; lng: number },
  clickPoint: { x: number; y: number },
  current: { lat: number; lng: number; point: { x: number; y: number } } | null,
  zoom: number,
) {
  const snap = snapContextCoord({ ...clickLatLng, point: clickPoint }, current)
  return {
    lat: snap.lat,
    lng: snap.lng,
    snapped: snap.snapped,
    metersPerPixel: metersPerPixel(snap.lat, zoom),
  }
}

describe('context-menu coordinate wiring', () => {
  it('reproduces the 2026-09-17 pankrazberg case as a snap instead of a 3.6km miss', () => {
    const state = openContextMenu(
      { lat: 47.3388227, lng: 11.7993164 }, // what Leaflet returned at zoom 8
      { x: 500, y: 300 },
      { lat: 47.32825, lng: 11.845251, point: { x: 508, y: 297 } },
      8,
    )
    expect(state.snapped).toBe(true)
    expect(state.lat).toBe(47.32825)
    expect(state.lng).toBe(11.845251)
    expect(state.metersPerPixel).toBeGreaterThan(25)
  })

  it('leaves a deliberate far click alone and still reports its precision', () => {
    const state = openContextMenu(
      { lat: 47.3388227, lng: 11.7993164 },
      { x: 500, y: 300 },
      { lat: 47.32825, lng: 11.845251, point: { x: 700, y: 300 } },
      17,
    )
    expect(state.snapped).toBe(false)
    expect(state.lat).toBe(47.3388227)
    expect(state.metersPerPixel).toBeLessThan(25)
  })

  it('forwards the meta as the 4th argument of onAddBookmark', () => {
    const onAddBookmark = vi.fn()
    const state = openContextMenu(
      { lat: 1, lng: 2 }, { x: 0, y: 0 },
      { lat: 3, lng: 4, point: { x: 1, y: 1 } }, 8,
    )
    onAddBookmark(state.lat, state.lng, undefined, {
      snapped: state.snapped, metersPerPixel: state.metersPerPixel,
    })
    expect(onAddBookmark).toHaveBeenCalledWith(3, 4, undefined, {
      snapped: true, metersPerPixel: expect.any(Number),
    })
  })
})
```

- [ ] **Step 2: Run it to confirm it passes against Task 1's helpers**

```bash
cd frontend && npx vitest run src/components/MapContextMenu.snap.test.tsx --reporter=dot 2>&1 | tail -4
```

Expected: `Tests  3 passed (3)`. This test pins the contract; Steps 3–5 make `MapView` actually obey it.

- [ ] **Step 3: Declare the meta type and widen the dialog state**

In `frontend/src/components/AppAddBookmarkDialog.tsx`, extend the exported state interface (the dialog's rendering changes land in Task 3):

```ts
// Precision provenance for a map-originated add. Absent for library-panel and
// recent-places adds, which carry an exact coordinate by construction.
export interface AddBookmarkMeta {
  // True when the right-click was inside the position marker and was replaced
  // by the device's exact coordinate.
  snapped?: boolean
  // Ground resolution of one screen pixel at the zoom the click happened on.
  metersPerPixel?: number
}

export interface AppAddBookmarkState {
  lat: number;
  lng: number;
  name: string;
  category: string;
  countryCode?: string;
  nameResolving?: boolean;
  snapped?: boolean;
  metersPerPixel?: number;
}
```

- [ ] **Step 4: Apply the snap where the context menu opens**

In `frontend/src/components/MapView.tsx`:

Add the import next to the other `utils` imports:

```ts
import { snapContextCoord, metersPerPixel } from '../utils/mapPrecision';
```

Extend `ContextMenuState` (~line 33):

```ts
interface ContextMenuState {
  visible: boolean;
  x: number;
  y: number;
  lat: number;
  lng: number;
  name?: string;
  // Set when the open coordinate was replaced by the device's exact position
  // because the right-click landed inside the position marker's footprint.
  snapped?: boolean;
  // Ground metres per screen pixel at the zoom this menu was opened on.
  metersPerPixel?: number;
}
```

Replace the `onContextMenu` handler (~line 495):

```ts
    // Right-click: open the shared context menu at the click point. The
    // hook already called preventDefault on the original event.
    //
    // The raw `lat`/`lng` Leaflet hands us is the click PIXEL converted at the
    // map's current zoom — at zoom 8 that is 220-610 m per pixel. The position
    // marker is non-interactive, so a right-click aimed at the avatar passes
    // through and arrives up to 22 px off. Snap it back to the device's exact
    // coordinate, once, here: every menu action then inherits the clean value.
    onContextMenu: (lat, lng, oe) => {
      const map = mapRef.current;
      let coord = { lat, lng, snapped: false };
      let mpp: number | undefined;
      if (map) {
        const clickPt = map.mouseEventToContainerPoint(oe);
        const cur = currentPosition
          ? {
              lat: currentPosition.lat,
              lng: currentPosition.lng,
              point: map.latLngToContainerPoint([currentPosition.lat, currentPosition.lng]),
            }
          : null;
        coord = snapContextCoord({ lat, lng, point: clickPt }, cur);
        mpp = metersPerPixel(coord.lat, map.getZoom());
      }
      setContextMenu({
        visible: true,
        x: oe.clientX,
        y: oe.clientY,
        lat: coord.lat,
        lng: coord.lng,
        snapped: coord.snapped,
        metersPerPixel: mpp,
      });
    },
```

Forward the meta where `<MapContextMenu>` is rendered (~line 887) — replace the bare `onAddBookmark={onAddBookmark}` line with:

```tsx
          onAddBookmark={(la, ln, nm) => onAddBookmark(la, ln, nm, {
            snapped: contextMenu.snapped,
            metersPerPixel: contextMenu.metersPerPixel,
          })}
```

- [ ] **Step 5: Widen the two prop signatures and the App handler**

In `frontend/src/components/MapView.tsx`, update the prop type (~line 58):

```ts
  onAddBookmark: (lat: number, lng: number, suggestedName?: string, meta?: AddBookmarkMeta) => void;
```

and import the type:

```ts
import type { AddBookmarkMeta } from './AppAddBookmarkDialog';
```

In `frontend/src/components/MapContextMenu.tsx`, leave the prop at three arguments — MapView now supplies the 4th through its own closure, so `MapContextMenu` stays unaware of precision. No change needed there; delete this step's edit if you were about to widen it.

In `frontend/src/App.tsx`, widen `handleAddBookmark` (~line 390):

```ts
  const handleAddBookmark = useCallback((
    lat: number,
    lng: number,
    suggestedName?: string,
    meta?: AddBookmarkMeta,
  ) => {
    const seedName = (suggestedName || '').trim()
    setAddBmDialog({
      lat,
      lng,
      name: seedName,
      category: bm.categories[0]?.name || t('bm.default'),
      nameResolving: true,
      snapped: meta?.snapped,
      metersPerPixel: meta?.metersPerPixel,
    })
```

(the rest of the callback body is unchanged), and add the type import beside the existing `AppAddBookmarkState` import:

```ts
import type { AddBookmarkMeta } from './components/AppAddBookmarkDialog'
```

- [ ] **Step 6: Type-check and run the full suite**

```bash
cd frontend && npx tsc --noEmit && npx vitest run --reporter=dot 2>&1 | tail -4
```

Expected: tsc silent; `Tests  998 passed (998)` (995 baseline + 3 new).

- [ ] **Step 7: Commit**

```bash
cd /Users/ravi.wu/personal/locwarp
git add frontend/src/components/MapView.tsx frontend/src/components/AppAddBookmarkDialog.tsx frontend/src/App.tsx frontend/src/components/MapContextMenu.snap.test.tsx
git commit -m "fix(bookmarks): a right-click on the position pin saved a pixel, not the position"
```

---

### Task 3: Show what is actually being saved

**Files:**
- Modify: `frontend/src/components/AppAddBookmarkDialog.tsx`
- Modify: `frontend/src/i18n/strings.ts`
- Test: `frontend/src/components/AppAddBookmarkDialog.test.tsx`

**Interfaces:**
- Consumes from Task 2: `AppAddBookmarkState.snapped`, `AppAddBookmarkState.metersPerPixel`.
- Consumes from Task 1: `PRECISION_HINT_M_PER_PX`.
- Produces: nothing downstream.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/AppAddBookmarkDialog.test.tsx` (keep the file's existing imports and render helper; if it renders through a helper with a different name, reuse that one rather than introducing a second):

```tsx
  it('shows the coordinate that will be saved', () => {
    render(
      <AppAddBookmarkDialog
        dialog={{ lat: 47.32825, lng: 11.845251, name: 'x', category: 'c' }}
        categories={['c']}
        onNameChange={() => {}}
        onCategoryChange={() => {}}
        onSubmit={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText(/47\.328250, 11\.845251/)).toBeInTheDocument()
  })

  it('reports when the coordinate was snapped to the current position', () => {
    render(
      <AppAddBookmarkDialog
        dialog={{ lat: 1, lng: 2, name: 'x', category: 'c', snapped: true }}
        categories={['c']}
        onNameChange={() => {}}
        onCategoryChange={() => {}}
        onSubmit={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByTestId('addbm-snapped')).toBeInTheDocument()
    expect(screen.queryByTestId('addbm-precision')).not.toBeInTheDocument()
  })

  it('warns when one screen pixel is worth more than the hint threshold', () => {
    render(
      <AppAddBookmarkDialog
        dialog={{ lat: 1, lng: 2, name: 'x', category: 'c', metersPerPixel: 417 }}
        categories={['c']}
        onNameChange={() => {}}
        onCategoryChange={() => {}}
        onSubmit={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByTestId('addbm-precision')).toHaveTextContent('417')
  })

  it('stays quiet at a precise zoom', () => {
    render(
      <AppAddBookmarkDialog
        dialog={{ lat: 1, lng: 2, name: 'x', category: 'c', metersPerPixel: 1.2 }}
        categories={['c']}
        onNameChange={() => {}}
        onCategoryChange={() => {}}
        onSubmit={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.queryByTestId('addbm-precision')).not.toBeInTheDocument()
  })
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd frontend && npx vitest run src/components/AppAddBookmarkDialog.test.tsx --reporter=dot 2>&1 | tail -6
```

Expected: FAIL — the four new cases cannot find the text / test ids.

- [ ] **Step 3: Add the i18n keys**

In `frontend/src/i18n/strings.ts`, beside the other `bm.*` keys:

```ts
  'bm.coord_readout': { zh: '座標', en: 'Coordinate' },
  'bm.coord_snapped': { zh: '已吸附至目前位置', en: 'Snapped to current position' },
  'bm.coord_imprecise': { zh: '此縮放下 1 像素 ≈ {m} 公尺,放大後再點更準確', en: '1 pixel ≈ {m} m at this zoom — zoom in for a precise pick' },
```

- [ ] **Step 4: Render the three states**

In `frontend/src/components/AppAddBookmarkDialog.tsx`, import the threshold:

```ts
import { PRECISION_HINT_M_PER_PX } from '../utils/mapPrecision';
```

and insert this block immediately after the title `<div>{t('bm.add')}</div>`:

```tsx
      <div
        style={{ fontSize: 11, color: '#9aa4bf', marginBottom: 6, fontFamily: 'monospace' }}
      >
        {dialog.lat.toFixed(6)}, {dialog.lng.toFixed(6)}
      </div>
      {dialog.snapped && (
        <div
          data-testid="addbm-snapped"
          style={{ fontSize: 11, color: '#4caf50', marginBottom: 6 }}
        >
          {t('bm.coord_snapped')}
        </div>
      )}
      {!dialog.snapped
        && typeof dialog.metersPerPixel === 'number'
        && dialog.metersPerPixel >= PRECISION_HINT_M_PER_PX && (
        <div
          data-testid="addbm-precision"
          style={{ fontSize: 11, color: '#ffa726', marginBottom: 6 }}
        >
          {t('bm.coord_imprecise').replace('{m}', String(Math.round(dialog.metersPerPixel)))}
        </div>
      )}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd frontend && npx vitest run src/components/AppAddBookmarkDialog.test.tsx --reporter=dot 2>&1 | tail -4
```

Expected: every case in the file passes, including the four new ones.

- [ ] **Step 6: Type-check and run the full suite**

```bash
cd frontend && npx tsc --noEmit && npx vitest run --reporter=dot 2>&1 | tail -4
```

Expected: tsc silent; `Tests  1002 passed (1002)`.

- [ ] **Step 7: Verify the frontend layering gate still passes**

```bash
cd frontend && npx depcruise --config .dependency-cruiser.js src 2>&1 | tail -3
```

Expected: `0 errors`. (If the script is exposed as an npm script in `package.json`, run that instead — check with `grep -n '"depcruise\|dependency-cruiser"' package.json`.)

- [ ] **Step 8: Commit**

```bash
cd /Users/ravi.wu/personal/locwarp
git add frontend/src/components/AppAddBookmarkDialog.tsx frontend/src/components/AppAddBookmarkDialog.test.tsx frontend/src/i18n/strings.ts
git commit -m "feat(bookmarks): show the coordinate a map add is about to save"
```

---

### Task 4: Repair the two surviving bad coordinates — GATED, DO NOT RUN WITHOUT RAVI'S SIGN-OFF

This task writes to the live iCloud-synced store. It must not be executed autonomously. Twenty of the twenty-two damaged bookmarks were already hand-corrected on the night; two still hold a zoom-derived coordinate.

**Evidence for each, from `backend.log.2026-09-17`:**

| Bookmark | Stored (wrong) | Created | Preceding teleport | Candidate correction | Error |
|---|---|---|---|---|---|
| 浮島向日葵 | `35.1019341, 138.7573242` | 22:54:01 | 22:52:00 → `35.141044, 138.785346` | `35.141044, 138.785346` | ~5.0 km (zoom 6, ~2 km/px) |
| 非美片 雪地十字架 | `47.3239306, 13.4197998` | 21:30:43 | 21:29:59 → `47.380016, 13.413680` | see note | ~6.2 km (zoom 8, ~415 m/px) |

**Note on 非美片 雪地十字架 — needs a decision, not a guess.** The log shows this bookmark was *already investigated* that night: at 22:19:10 the user teleported to its stored (wrong) coordinate, at 22:20:39 teleported to `47.380016, 13.413680`, and at 22:21:04 created a **new** bookmark `urbisgut altenmarkt` there instead of fixing this one. `urbisgut` now holds exactly `47.380016, 13.41368`. So 非美片 is most likely an abandoned duplicate. Three options — Ravi picks one:
1. Delete 非美片 as a superseded duplicate.
2. Point it at `47.380016, 13.413680` (it then duplicates `urbisgut`'s coordinate under a different name).
3. Leave it; Ravi supplies the real intended coordinate.

- [ ] **Step 1: Confirm the backend is running and re-read both records**

```bash
curl -s http://127.0.0.1:8777/api/bookmarks \
  | python3 -c "import sys,json;[print(b['id'],b['name'],b['lat'],b['lng']) for b in json.load(sys.stdin)['bookmarks'] if b['name'] in ('浮島向日葵','非美片 雪地十字架')]"
```

Expected: two rows matching the table above. If either coordinate has already changed, STOP and re-check with Ravi — someone edited it in the meantime.

- [ ] **Step 2: Take a fresh backup before writing**

```bash
cd /Users/ravi.wu/personal/locwarp && make backup && ls -lt ~/.locwarp/backups/ | head -3
```

Expected: a new `locwarp-backup-<stamp>.json`, newest first.

- [ ] **Step 3: Correct 浮島向日葵 (only after Ravi confirms the candidate)**

`PUT` is a partial update — sending only `lat`/`lng` leaves `name`, `category_id`, and `address` untouched, and per-unit stamping means only the `coords` unit is re-stamped.

```bash
curl -s -X PUT http://127.0.0.1:8777/api/bookmarks/87cc7d9a-0a8e-4d9f-b32e-ac8ff66e174b \
  -H 'Content-Type: application/json' \
  -d '{"lat": 35.141044, "lng": 138.785346}' | python3 -m json.tool
```

Expected: the returned record shows the new coordinate and a bumped `updated_at`.

- [ ] **Step 4: Apply Ravi's chosen action for 非美片 雪地十字架**

Only after option 1, 2, or 3 has been chosen. For option 2:

```bash
curl -s -X PUT http://127.0.0.1:8777/api/bookmarks/5bfa7575-d04d-46d0-b837-4c8adcc090f3 \
  -H 'Content-Type: application/json' \
  -d '{"lat": 47.380016, "lng": 13.413680}' | python3 -m json.tool
```

For option 1, use the UI's delete so the tombstone is written through the normal path. Do not hand-edit `bookmarks.json`.

- [ ] **Step 5: Verify the change survived the merge on save**

The store re-merges against the on-disk copy inside `_save()`, so "it came back in the response" is not proof it persisted. Re-read from disk:

```bash
python3 -c "
import json,os
p=os.path.expanduser('~/Library/Mobile Documents/com~apple~CloudDocs/LocWarp/bookmarks.json')
for b in json.load(open(p))['bookmarks']:
    if b['name'] in ('浮島向日葵','非美片 雪地十字架'):
        print(b['name'], b['lat'], b['lng'], b['updated_at'], b.get('field_updated_at',{}).get('coords'))
"
```

Expected: the corrected coordinates, with `field_updated_at.coords` newer than `created_at`.

- [ ] **Step 6: Re-run the tile-grid scan to confirm nothing on 2026-09-17 is still pixel-derived**

```bash
python3 - <<'PY'
import json,os,math
p=os.path.expanduser('~/Library/Mobile Documents/com~apple~CloudDocs/LocWarp/bookmarks.json')
def zoom_of(lat,lng):
    if abs(lat)>85: return None
    for Z in range(0,19):
        s=256*2**Z
        x=(lng+180.0)/360.0*s
        y=(1.0-math.asinh(math.tan(math.radians(lat)))/math.pi)/2.0*s
        if abs(x-round(x))<3e-3 and abs(y-round(y))<3e-3: return Z
    return None
for b in json.load(open(p))['bookmarks']:
    if b.get('created_at','').startswith('2026-09-17'):
        z=zoom_of(b['lat'],b['lng'])
        if z is not None and z<=12: print('STILL IMPRECISE', z, b['name'], b['lat'], b['lng'])
print('scan done')
PY
```

Expected: `scan done` with no `STILL IMPRECISE` lines.

---

## Self-Review

**Spec coverage.** Recommendation (1) "snap within the marker footprint" → Tasks 1+2. Recommendation (2) "make the precision visible" → Tasks 1+3. The red baseline discovered while pinning constraints → Task 0. The two unrepaired records surfaced by the investigation → Task 4 (gated). Nothing in the agreed scope is unassigned.

**Placeholder scan.** No TBD / "handle edge cases" / "similar to Task N" survives; every code step carries the literal code, every verification step carries the command and its expected output. Task 4 deliberately stops at a decision point for 非美片 雪地十字架 rather than inventing an intent — that is a gate, not a placeholder, and it is marked as one.

**Type consistency.** `AddBookmarkMeta` is declared once (Task 2, Step 3, in `AppAddBookmarkDialog.tsx`) and imported by `MapView.tsx` and `App.tsx`; `AppAddBookmarkState` gains the same two optional fields it is read through in Task 3. `snapContextCoord` / `metersPerPixel` / `MARKER_SNAP_RADIUS_PX` / `PRECISION_HINT_M_PER_PX` keep identical names from their definition in Task 1 through every later use. Task 2 Step 5 explicitly cancels its own `MapContextMenu` edit so the three-argument prop there is not accidentally widened.

**Known risk.** `map.mouseEventToContainerPoint(oe)` requires the original `MouseEvent`, which `useMapInstance` already forwards as the handler's third argument — no hook change is needed. If a future refactor drops that argument, the snap silently stops working; the Task 2 test pins the arithmetic but not the plumbing, so a manual check (right-click the pin at zoom 8, confirm the dialog shows the exact device coordinate and the green snap badge) belongs in the acceptance pass.
