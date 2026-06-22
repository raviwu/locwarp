/**
 * Bookmark cluster-popup teleport bridge — Task p4b2bi (runtime-wiring net)
 *
 * Closes the one coverage gap an adversarial review found in
 * `useBookmarkMarkersLayer.ts`: the live `popupopen → .bm-cluster-row click →
 * map.closePopup() + onTeleport(lat,lng)` bridge. The vitest units pin only
 * the clustering math (`clusterByPixelDistance`) and the row HTML
 * (`buildBookmarkClusterRowHtml`); NEITHER they nor the other 6 Playwright
 * specs drive the runtime DOM-query click handler. A dropped listener, a
 * renamed `data-lat`/`data-lng` attr, or a swapped popup builder would pass
 * every existing test yet break cluster teleport.
 *
 * This spec exercises the bridge END TO END with no backend / device:
 *   1. Mock GET /api/bookmarks → 2 bookmarks at near-identical coords (a few
 *      px apart at the default zoom-13 Taipei center) so they CLUSTER into one
 *      `.bookmark-cluster-pin` (polaroid-stack) divIcon.
 *   2. Turn the overlay on by seeding the same localStorage key App reads on
 *      mount (`locwarp.show_bookmark_pins = '1'`).
 *   3. Click the cluster pin → assert the popup opens with `.bm-cluster-row`
 *      rows (one per member).
 *   4. Click a `.bm-cluster-row` → assert the bridge fired:
 *        - the popup CLOSES (proves `map.closePopup()` ran), AND
 *        - the teleport request hits POST /api/location/teleport with the
 *          ROW's exact coords (proves `onTeleport(lat,lng)` ran end to end:
 *          row dataset → handleTeleport → sim.teleport → api.teleport).
 *
 * Why the teleport is network-observable here: with ZERO devices connected
 * in the mock env, handleTeleport takes the `udids.length < 2` branch →
 * sim.teleport(lat,lng) → api.teleport(lat,lng) → POST /api/location/teleport
 * { lat, lng }. We intercept that POST to read the body.
 *
 * Fixture-injection recipe (reusable by later rounds):
 *   - bookmarks: page.route('** /api/bookmarks', json array). useBookmarks
 *     accepts a bare array OR { bookmarks: [...] }.
 *   - categories: page.route('** /api/bookmarks/categories', []) so the
 *     parallel GET in useBookmarks.refresh() resolves.
 *   - initial position: page.route('** /api/location/settings/initial-position',
 *     { position: null }) so the map stays at the default zoom-13 center and
 *     the two coords reliably cluster.
 *   - show-pins toggle: page.addInitScript sets
 *     localStorage['locwarp.show_bookmark_pins'] = '1' BEFORE the bundle runs.
 *   - WS: page.routeWebSocket stub (no frames) so the app never blocks on a
 *     real backend socket.
 */

import { test, expect } from '@playwright/test'

// Two bookmarks a few px apart at the map's default center (Taipei, zoom 13):
// ~0.0003° apart → well within the 40px cluster threshold, so they collapse
// into one polaroid-stack cluster pin instead of two separate pins.
const BM_A = { id: 'bm-a', name: 'Cluster Spot A', lat: 25.0330, lng: 121.5654, country_code: 'tw' }
const BM_B = { id: 'bm-b', name: 'Cluster Spot B', lat: 25.0333, lng: 121.5657, country_code: 'tw' }

test('cluster popup row click closes the popup and teleports to the row coords', async ({ page }) => {
  // ── Stub the WS so the app never blocks on a real backend connection. ────
  await page.routeWebSocket('**/ws/status', () => {
    /* swallow — pure stub, no frames needed for this overlay */
  })

  // ── Turn the bookmark-pins overlay ON before the bundle boots. App reads
  // this exact key synchronously in its showBookmarkPins useState initializer.
  await page.addInitScript(() => {
    try { localStorage.setItem('locwarp.show_bookmark_pins', '1') } catch { /* ignore */ }
  })

  // ── Mock the bookmark fixture (the api-mock seam). useBookmarks fires
  // GET /api/bookmarks + GET /api/bookmarks/categories in parallel on mount.
  await page.route('**/api/bookmarks', async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({ json: [BM_A, BM_B] })
  })
  await page.route('**/api/bookmarks/categories', async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({ json: [] })
  })

  // Keep the map at its default zoom-13 Taipei center so the two coords
  // reliably cluster (the initial-position fetch would otherwise setView).
  await page.route('**/api/location/settings/initial-position', async (route) => {
    await route.fulfill({ json: { position: null } })
  })

  // Intercept the teleport POST so we can both (a) observe it fired and
  // (b) read the coords, without needing a real backend.
  let teleportBody: { lat?: number; lng?: number } | null = null
  await page.route('**/api/location/teleport', async (route) => {
    teleportBody = route.request().postDataJSON()
    await route.fulfill({ json: { status: 'ok', lat: teleportBody?.lat, lng: teleportBody?.lng } })
  })

  // ── Load the app. ────────────────────────────────────────────────────────
  await page.goto('/')
  await page.waitForSelector('.leaflet-container', { timeout: 15_000 })
  // Let Strict Mode's mount/cleanup/remount settle + the bookmarks fetch land
  // so the overlay effect has rebuilt against the final, stable map instance.
  await page.waitForTimeout(800)

  // ── Step 1: the two close bookmarks collapsed into ONE cluster pin. ───────
  // `.bookmark-cluster-pin` is the className on the L.divIcon for a multi-member
  // cluster (buildBookmarkClusterHtml). There must be exactly one, and NO
  // single-pin `.bookmark-pin` (both bookmarks are inside the cluster).
  const clusterPin = page.locator('.bookmark-cluster-pin')
  await expect(clusterPin).toHaveCount(1, { timeout: 5_000 })
  await expect(page.locator('.bookmark-pin')).toHaveCount(0)

  // ── Step 2: click the cluster → popup opens with one row per member. ─────
  await clusterPin.click()
  await expect(page.locator('.bookmark-cluster-popup')).toBeVisible({ timeout: 5_000 })
  const rows = page.locator('.bm-cluster-row')
  await expect(rows).toHaveCount(2)

  // Pin that the rows carry the dataset coords the bridge reads. The handler
  // does parseFloat(el.dataset.lat / el.dataset.lng); a renamed attr would
  // silently break the teleport, so assert the attribute contract directly.
  const rowB = page.locator(`.bm-cluster-row[data-lat="${BM_B.lat}"][data-lng="${BM_B.lng}"]`)
  await expect(rowB).toHaveCount(1)

  // ── Step 3: click a row → the bridge fires. ──────────────────────────────
  // popupopen wired a click listener on each .bm-cluster-row that reads
  // data-lat/data-lng, calls map.closePopup() (popup detaches), then
  // onTeleport(lat,lng) → handleTeleport → api.teleport → POST /teleport.
  await rowB.click()

  // (a) The popup closed — proves map.closePopup() ran inside the handler.
  await expect(page.locator('.bookmark-cluster-popup')).toHaveCount(0, { timeout: 5_000 })

  // (b) The teleport request fired with the ROW's coords — proves the whole
  // onTeleport bridge executed end to end (row dataset → app handler → api).
  await expect.poll(() => teleportBody, { timeout: 5_000 }).not.toBeNull()
  expect(teleportBody!.lat).toBeCloseTo(BM_B.lat, 6)
  expect(teleportBody!.lng).toBeCloseTo(BM_B.lng, 6)
})
