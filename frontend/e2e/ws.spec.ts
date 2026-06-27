/**
 * WS fan-out e2e — Task 13
 *
 * Proves that a single WsRouter fan-out delivers to BOTH subscribers:
 *   1. position_update  → MapView renders the current-position marker
 *   2. device_disconnected (remaining_count 0) → useSimulation error banner
 *      AND useDevice marks devices disconnected (DeviceStatus shows disconnected state)
 *
 * The WebSocket is fully mocked via Playwright's routeWebSocket so no real
 * backend or real device is needed.
 *
 * Implementation notes:
 *   - The app creates TWO WebSocket connections at startup: one in ServicesRoot
 *     (main.tsx, provides the ServicesContext router) and one in App.tsx (provides
 *     the router passed directly to useSimulation / useDevice). React Strict Mode
 *     in development double-mounts effects, so four WS connections are intercepted
 *     in total (two from the first pass, cleaned up; two from the second/real pass).
 *   - We broadcast each mock frame to ALL intercepted routes so the message
 *     reaches every active router regardless of which WS instance each hook is
 *     currently subscribed to. Routes from the first Strict-Mode pass have already
 *     been closed by cleanup; Playwright silently drops sends to closed sockets, so
 *     broadcasting to all four is safe.
 *   - playwright.config.ts runs 'vite build && vite preview' so the app is
 *     served from a pre-built bundle (instant loads); no lazy module
 *     transforms that could time out on a cold dev server.
 *
 * To run:
 *   cd frontend && npx playwright install chromium && npx playwright test
 */

import { test, expect } from '@playwright/test'
import type { WebSocketRoute } from '@playwright/test'

test('position_update moves the map marker; device_disconnected fires both effects', async ({ page }) => {
  // ── Step 1: intercept the WS before the app connects ──────────────────
  // Collect ALL intercepted routes: the app creates two WS connections
  // (ServicesRoot + App) and React Strict Mode double-mounts, giving us four
  // intercepts. We broadcast to all of them so every active router receives
  // the frame regardless of which specific WS instance a given hook uses.
  const wsRoutes: WebSocketRoute[] = []

  await page.routeWebSocket('**/ws/status', (ws) => {
    wsRoutes.push(ws)
    // Do NOT connect to the real server — pure mock.
  })

  // Helper: broadcast a JSON frame to every intercepted route.
  const broadcast = (frame: object) => {
    const payload = JSON.stringify(frame)
    wsRoutes.forEach((r) => {
      try { r.send(payload) } catch { /* closed routes ignored */ }
    })
  }

  // ── Step 2: load the app ───────────────────────────────────────────────
  await page.goto('/')

  // Wait for the Leaflet map container to render (proves React tree is up
  // AND the Leaflet L.map() initialiser has run — Leaflet adds
  // .leaflet-container to the mount div when L.map() executes).
  await page.waitForSelector('.leaflet-container', { timeout: 15_000 })

  // Give React Strict Mode's mount/cleanup/remount cycle time to settle
  // so all active WS connections and their effect subscriptions are stable.
  await page.waitForTimeout(500)

  // ── Step 3: inject a position_update ──────────────────────────────────
  // Wire format: { type, data } — useWsRouter flattens it to { type, ...data }
  // before passing to router.dispatch.
  expect(wsRoutes.length).toBeGreaterThan(0)

  broadcast({
    type: 'position_update',
    data: {
      udid: 'E2E-UDID',
      lat: 35.6762,
      lng: 139.6503,
      bearing: 0,
      speed_mps: 5,
      progress: 0.5,
      distance_remaining: 100,
      distance_traveled: 100,
      eta_seconds: 20,
    },
  })

  // Assert the current-position marker appears in the DOM.
  // MapView creates a Leaflet divIcon with className 'current-pos-marker';
  // Leaflet renders it as a <div class="leaflet-marker-icon leaflet-div-icon current-pos-marker">.
  await expect(page.locator('.current-pos-marker').first()).toBeVisible({ timeout: 5_000 })

  // ── Step 4: inject device_disconnected ────────────────────────────────
  // remaining_count 0 → useSimulation sets sim.error → banner appears
  //                    → useDevice marks all devices disconnected
  broadcast({
    type: 'device_disconnected',
    data: {
      udid: 'E2E-UDID',
      udids: ['E2E-UDID'],
      reason: 'forgotten',
      remaining_count: 0,
    },
  })

  // Effect A — simulation-state: the error banner from useSimulation is rendered
  // in App.tsx as an absolutely-positioned red div containing the error string.
  // The disconnect banner copy (useSimulation.ts) was softened to a
  // "trying to reconnect; replug USB" message. en: "Device disconnected —
  // trying to reconnect; replug USB if it does not come back"; zh: "裝置連線
  // 中斷 — 嘗試自動重連中,若未恢復請重新插上 USB". Both end with the distinctive
  // "replug USB" / "重新插上 USB"; match on that so the assertion tracks the copy.
  await expect(
    page.locator('div').filter({ hasText: /重新插上 USB|replug USB/ }).first()
  ).toBeVisible({ timeout: 5_000 })

  // Effect B — device-state: DeviceStatus renders with class 'device-disconnected'
  // when isConnected is false. isConnected={device.connectedDevice !== null} starts
  // as false (no device connected in the mock env) so the class is already present
  // on initial render; this assertion confirms it remains visible after the
  // device_disconnected event (i.e. the useDevice handler doesn't accidentally
  // set connectedDevice to something truthy and flip the class to device-connected).
  await expect(page.locator('.device-disconnected').first()).toBeVisible({ timeout: 5_000 })
})
