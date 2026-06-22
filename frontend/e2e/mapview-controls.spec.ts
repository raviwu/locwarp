/**
 * MapView Leaflet-control net — Task p4b2a
 *
 * Pins the STATIC Leaflet artifacts that MapView.tsx builds imperatively at
 * map-init time, so the upcoming structural refactor (extracting a
 * `LeafletBarButton` primitive + a `useBaseLayers` hook + a `useMapInstance`
 * hook, and deleting the dead dual-mode code) can move the *implementation*
 * without changing the *DOM contract*. These assertions are the behavioral
 * net for moves that the WS-driven specs (ws.spec.ts / sim.spec.ts) don't
 * touch — they assert what exists after the map mounts, with NO WS frames.
 *
 * What this file pins (each maps to one structural move):
 *   1. The 4 custom leaflet-bar buttons (recenter / follow / library / S2-grid)
 *      built via L.DomUtil.create in MapView's map-init effect → move when the
 *      `LeafletBarButton` primitive is extracted.
 *   2. The base-layer switcher control (L.control.layers) → moves when
 *      `useBaseLayers` is extracted.
 *   3. The Leaflet zoom control + container scaffold → moves with
 *      `useMapInstance`.
 *
 * Selector strategy (frozen contract — do NOT rename without updating the
 * structural-refactor plan):
 *   - Language-stable: prefer the custom classNames that MapView puts on its
 *     buttons (`.locwarp-library-btn`, `.locwarp-s2-btn`) and Leaflet's own
 *     stable classes (`.leaflet-bar`, `.leaflet-control-layers`,
 *     `.leaflet-control-layers-toggle`, `.leaflet-control-zoom`).
 *   - The recenter + follow buttons have NO custom className today; they are
 *     anonymous `<button>`s inside their own `.leaflet-bar` wrappers, so they
 *     are pinned by their `title` attribute. The app's default language is
 *     env-dependent (navigator.language → zh|en), so the title matchers accept
 *     EITHER locale's string, mirroring the bilingual regex pattern already
 *     used in ws.spec.ts.
 *
 * No backend / device / WS is needed — these controls render from the
 * synchronous map-init effect alone.
 */

import { test, expect } from '@playwright/test'

// i18n title strings (src/i18n/strings.ts). The default lang is decided by
// navigator.language inside the headless Chromium, so we match either locale.
const RECENTER_TITLE = /定位到目前位置|Recenter on current position/
const FOLLOW_TITLE = /跟隨模式|Follow mode/

test.beforeEach(async ({ page }) => {
  // Stub the WS so the app never blocks on a real backend connection; we
  // don't broadcast anything — these controls are static, not WS-driven.
  await page.routeWebSocket('**/ws/status', () => {
    /* swallow — pure stub, no frames */
  })

  await page.goto('/')

  // Leaflet adds .leaflet-container once L.map() has run — proves the
  // map-init effect (which builds all the controls below) has executed.
  await page.waitForSelector('.leaflet-container', { timeout: 15_000 })
  // Let Strict Mode's mount/cleanup/remount settle so we assert against the
  // final, stable control tree (not a half-built first-pass mount).
  await page.waitForTimeout(500)
})

test('the 4 custom leaflet-bar buttons render after the map mounts', async ({ page }) => {
  // The whole left-side control stack lives in Leaflet's top-left corner.
  const topLeft = page.locator('.leaflet-top.leaflet-left')
  await expect(topLeft).toBeVisible()

  // ── Recenter button (1st custom leaflet-bar) ──────────────────────────
  // Anonymous <button> with only a title; pinned by the bilingual title.
  await expect(page.getByTitle(RECENTER_TITLE)).toBeVisible()
  await expect(page.getByTitle(RECENTER_TITLE)).toHaveCount(1)

  // ── Follow button (2nd custom leaflet-bar) ────────────────────────────
  // Pinned by its bilingual "Follow mode" title; default state is follow_off
  // and carries aria-pressed="false" — a load-bearing toggle attribute the
  // refactor must preserve on the extracted LeafletBarButton.
  const followBtn = page.getByTitle(FOLLOW_TITLE)
  await expect(followBtn).toBeVisible()
  await expect(followBtn).toHaveCount(1)
  await expect(followBtn).toHaveAttribute('aria-pressed', 'false')

  // ── Library button (3rd custom leaflet-bar) ───────────────────────────
  // Has the stable custom className `.locwarp-library-btn` (gold star).
  await expect(page.locator('.locwarp-library-btn')).toBeVisible()
  await expect(page.locator('.locwarp-library-btn')).toHaveCount(1)

  // ── S2-grid button (4th custom leaflet-bar) ───────────────────────────
  // Has the stable custom className `.locwarp-s2-btn`; default
  // aria-pressed="false" (grid off).
  await expect(page.locator('.locwarp-s2-btn')).toBeVisible()
  await expect(page.locator('.locwarp-s2-btn')).toHaveCount(1)
  await expect(page.locator('.locwarp-s2-btn')).toHaveAttribute('aria-pressed', 'false')
})

test('the top-left control stack has the zoom bar plus 4 custom leaflet-bars', async ({ page }) => {
  // Leaflet's zoom control is itself a `.leaflet-bar`; each of the 4 custom
  // buttons is wrapped in its own `.leaflet-bar leaflet-control`. So the
  // top-left corner holds 5 `.leaflet-bar` elements total. Pinning the count
  // catches a refactor that accidentally drops a bar or double-mounts one.
  const bars = page.locator('.leaflet-top.leaflet-left .leaflet-bar')
  await expect(bars).toHaveCount(5)

  // The native zoom control is one of them.
  await expect(page.locator('.leaflet-control-zoom')).toBeVisible()
  await expect(page.locator('.leaflet-control-zoom').locator('a')).toHaveCount(2)

  // Recenter + Follow live inside their own bars and are reachable by title.
  await expect(page.getByTitle(RECENTER_TITLE)).toBeVisible()
  await expect(page.getByTitle(FOLLOW_TITLE)).toBeVisible()
})

test('the base-layer switcher control renders (collapsed, top-right)', async ({ page }) => {
  // L.control.layers({...}, { position: 'topright', collapsed: true }) renders
  // a `.leaflet-control-layers` container with a `.leaflet-control-layers-toggle`
  // link while collapsed. This whole control moves when `useBaseLayers` is
  // extracted, so both the container and the toggle are pinned.
  const layersControl = page.locator('.leaflet-control-layers')
  await expect(layersControl).toBeVisible()
  await expect(layersControl).toHaveCount(1)

  // The collapsed toggle is the visible affordance; the expanded list is
  // present in the DOM but hidden until hover/click.
  await expect(page.locator('.leaflet-control-layers-toggle')).toBeVisible()

  // It lives in the top-right corner (where MapView mounts it).
  await expect(
    page.locator('.leaflet-top.leaflet-right .leaflet-control-layers')
  ).toBeVisible()

  // The radio list of base layers is built into the DOM even while collapsed
  // (Leaflet just hides it visually). MapView wires SIX base layers — OSM,
  // CartoDB Voyager, ESRI Satellite, OpenFreeMap Liberty, NLSC, GSI — so the
  // collapsed control must already hold 6 layer-selector radios. This proves
  // the control is wired to real layers, not an empty shell, without relying
  // on Leaflet's flaky hover-to-expand in headless Chromium.
  await expect(
    page.locator('.leaflet-control-layers-list input.leaflet-control-layers-selector')
  ).toHaveCount(6)
})
