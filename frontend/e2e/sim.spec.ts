/**
 * Simulation route lifecycle e2e — companion to ws.spec.ts
 *
 * Proves the route-overlay lifecycle driven purely by mocked WS frames:
 *   1. position_update → MapView renders the current-position marker
 *   2. route_path (>=2 coords) → useSimulation.setRoutePath → MapView draws
 *      the flowing-arrow polyline (an SVG <path class="route-flow-dash">)
 *   3. state_change(idle) → useSimulation clears routePath/destination/eta →
 *      MapView removes the polyline (the .route-flow-dash path disappears)
 *
 * This exercises a DIFFERENT slice of the WsRouter fan-out than ws.spec.ts:
 * the route-path + state-change handlers and the MapView polyline effect,
 * end to end, with no real backend or device.
 *
 * Mock-WS + selector patterns mirror ws.spec.ts:
 *   - The app opens multiple WS connections (ServicesRoot + App, each
 *     double-mounted by React Strict Mode), so we collect every intercepted
 *     route and broadcast each frame to all of them. Sends to already-closed
 *     routes are silently dropped.
 *   - Wire format is { type, data }; useWsRouter flattens data into the event.
 *
 * To run:
 *   cd frontend && npx playwright install chromium && npx playwright test
 */

import { test, expect } from '@playwright/test'
import type { WebSocketRoute } from '@playwright/test'

test('route_path draws the map polyline; state_change(idle) clears it', async ({ page }) => {
  // ── Step 1: intercept the WS before the app connects ──────────────────
  const wsRoutes: WebSocketRoute[] = []

  await page.routeWebSocket('**/ws/status', (ws) => {
    wsRoutes.push(ws)
    // Pure mock — never connect to the real server.
  })

  const broadcast = (frame: object) => {
    const payload = JSON.stringify(frame)
    wsRoutes.forEach((r) => {
      try { r.send(payload) } catch { /* closed routes ignored */ }
    })
  }

  // ── Step 2: load the app ───────────────────────────────────────────────
  await page.goto('/')

  // Leaflet adds .leaflet-container once L.map() has run.
  await page.waitForSelector('.leaflet-container', { timeout: 15_000 })

  // Let Strict Mode's mount/cleanup/remount cycle settle so all active
  // WS subscriptions are stable before we broadcast.
  await page.waitForTimeout(500)
  expect(wsRoutes.length).toBeGreaterThan(0)

  // ── Step 3: position_update → current-position marker appears ──────────
  broadcast({
    type: 'position_update',
    data: {
      udid: 'E2E-UDID',
      lat: 35.6762,
      lng: 139.6503,
      bearing: 0,
      speed_mps: 5,
      progress: 0.1,
      distance_remaining: 900,
      distance_traveled: 100,
      eta_seconds: 180,
    },
  })

  await expect(page.locator('.current-pos-marker').first()).toBeVisible({ timeout: 5_000 })

  // ── Step 4: route_path → flowing-arrow polyline appears ────────────────
  // MapView draws the route only when routePath.length > 1, as an SVG
  // <path class="route-flow-dash"> in the Leaflet overlay pane.
  broadcast({
    type: 'route_path',
    data: {
      udid: 'E2E-UDID',
      coords: [
        { lat: 35.6762, lng: 139.6503 },
        { lat: 35.6800, lng: 139.6600 },
        { lat: 35.6850, lng: 139.6700 },
      ],
    },
  })

  await expect(page.locator('path.route-flow-dash').first()).toBeVisible({ timeout: 5_000 })

  // ── Step 5: state_change(idle) → route overlay cleared ─────────────────
  // No device is connected in the mock env so primaryUdidRef is null and the
  // dual-device filter passes; st === 'idle' calls setRoutePath([]), which
  // makes the MapView effect remove the polyline.
  broadcast({
    type: 'state_change',
    data: {
      udid: 'E2E-UDID',
      state: 'idle',
    },
  })

  // The flowing-arrow path is detached from the DOM once routePath is empty.
  await expect(page.locator('path.route-flow-dash')).toHaveCount(0, { timeout: 5_000 })
})
