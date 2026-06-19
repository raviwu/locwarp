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
 * To run:
 *   cd frontend && npx playwright install chromium && npx playwright test
 */

import { test, expect } from '@playwright/test'
import type { WebSocketRoute } from '@playwright/test'

test('position_update moves the map marker; device_disconnected fires both effects', async ({ page }) => {
  // ── Step 1: intercept the WS before the app connects ──────────────────
  // Capture the server-side route handle so we can push frames later.
  let wsRoute: WebSocketRoute | null = null

  await page.routeWebSocket('**/ws/status', (ws) => {
    wsRoute = ws
    // Do NOT connect to the real server — this is a pure mock.
    // The app thinks it has an open WebSocket; we drive it entirely from here.
  })

  // ── Step 2: load the app ───────────────────────────────────────────────
  await page.goto('/')

  // Wait for the Leaflet map container to render (proves React tree is up).
  await page.waitForSelector('.leaflet-container', { timeout: 15_000 })

  // Wait until the app has established a WS connection attempt and our
  // intercept handler has fired (wsRoute should be set).
  await page.waitForFunction(() => true) // flush micro-tasks
  // Give the hook's connect() a tick to run and fire routeWebSocket.
  await page.waitForTimeout(500)

  // ── Step 3: inject a position_update ──────────────────────────────────
  // The wire format is { type, data } — useWsRouter flattens it to
  // { type, ...data } before passing to WsRouter.dispatch.
  expect(wsRoute).not.toBeNull()
  const route = wsRoute as WebSocketRoute

  route.send(JSON.stringify({
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
  }))

  // Assert the current-position marker appears in the DOM.
  // MapView creates a Leaflet divIcon with className 'current-pos-marker';
  // Leaflet renders it as a <div class="leaflet-marker-icon leaflet-div-icon current-pos-marker">.
  await expect(page.locator('.current-pos-marker').first()).toBeVisible({ timeout: 5_000 })

  // ── Step 4: inject device_disconnected ────────────────────────────────
  // remaining_count 0 → useSimulation sets error → banner appears
  //                    → useDevice marks all devices disconnected
  route.send(JSON.stringify({
    type: 'device_disconnected',
    data: {
      udid: 'E2E-UDID',
      udids: ['E2E-UDID'],
      reason: 'forgotten',
      remaining_count: 0,
    },
  }))

  // Effect A — simulation-state: the error banner from useSimulation is rendered
  // in App.tsx as an absolutely-positioned red div containing the error string.
  // With lang=en it says "Device disconnected (USB unplugged…)";
  // default (zh) says "裝置連線中斷(USB 拔除…)". Both contain "USB".
  await expect(page.getByText(/USB/)).toBeVisible({ timeout: 5_000 })

  // Effect B — device-state: useDevice.device_disconnected handler marks
  // devices as is_connected: false. DeviceStatus renders the component with
  // the 'device-disconnected' CSS class when isConnected is false.
  // In the single-device (no chip row) path, StatusBar's DeviceStatus gets
  // isConnected={device.connectedDevice !== null} which becomes false after
  // the disconnect. DeviceStatus renders:
  //   <div className={`device-status ${isConnected ? 'device-connected' : 'device-disconnected'}`}>
  // We assert that class appears somewhere in the rendered tree.
  await expect(page.locator('.device-disconnected').first()).toBeVisible({ timeout: 5_000 })
})
