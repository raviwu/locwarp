import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen, fireEvent } from '@testing-library/react'

// ─────────────────────────────────────────────────────────────────────────────
// GLOBAL SHORTCUTS WIRING CHARACTERIZATION (Cluster 1, Task 4).
//
// Pins the end-to-end wiring of useGlobalShortcuts into App.tsx.
// Three assertions:
//   1. Space on document calls api.stopSim (single device path, no udid).
//   2. Space fired while an INPUT is focused does NOT call api.stopSim.
//   3. Cmd+K focuses the .search-input element.
//
// Harness mirrors App.dangerzone.test.tsx exactly (ServicesProvider, fake-api
// injection, MapView/ControlPanel stubs, renderApp, connectDevices helpers).
// fireEvent only — @testing-library/user-event is NOT installed.
// ─────────────────────────────────────────────────────────────────────────────

// ── MapView test-double ───────────────────────────────────────────────────────
vi.mock('./components/MapView', () => ({
  default: React.forwardRef(function MapViewStub(props: any, _ref: any) {
    return (
      <div
        data-testid="mapview"
        data-device-count={(props.devices ?? []).length}
      >
        <button data-testid="map-click" onClick={() => props.onMapClick(25.05, 121.55)} />
        <button data-testid="map-start" onClick={() => props.onStart?.()} />
        <button data-testid="map-stop" onClick={() => props.onStop?.()} />
      </div>
    )
  }),
}))

// ── ControlPanel test-double ──────────────────────────────────────────────────
// Includes a .search-input element so onFocusSearch can locate and focus it.
vi.mock('./components/ControlPanel', () => ({
  default: function ControlPanelStub(props: any) {
    return (
      <div data-testid="controlpanel">
        <button data-testid="cp-start" onClick={() => props.onStart()} />
        <button data-testid="cp-stop" onClick={() => props.onStop()} />
        <input className="search-input" data-testid="search-input" type="text" readOnly />
      </div>
    )
  },
}))

// ── api: spy stopSim; inert stubs elsewhere ───────────────────────────────────
vi.mock('./services/api', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const arrayReturning = new Set([
    'getSavedRoutes', 'getRecent', 'listRouteCategories', 'listBookmarks',
    'listCategories', 'getBookmarks', 'getCategories',
  ])
  const nullReturning = new Set(['getCatalog'])
  const urlReturning = new Set(['bookmarksExportUrl', 'exportGpxUrl', 'routesExportUrl'])
  const spied = new Set([
    'stopSim', 'pauseSim', 'resumeSim', 'teleport', 'navigate',
    'startLoop', 'multiStop', 'randomWalk', 'joystickStart', 'joystickStop',
    'insertWaypoint',
  ])
  const out: Record<string, unknown> = {}
  for (const key of Object.keys(actual)) {
    if (typeof actual[key] !== 'function') { out[key] = actual[key]; continue }
    if (spied.has(key)) {
      out[key] = vi.fn(async () => ({ ok: true }))
    } else if (key === 'cloudSyncStatus') {
      out[key] = async () => ({ enabled: false, prompt_dismissed: true, detected_icloud_path: null })
    } else if (key === 'getCooldownStatus') {
      out[key] = async () => ({})
    } else if (key === 'getStatus') {
      out[key] = vi.fn(async () => ({}))
    } else if (key === 'listDevices') {
      out[key] = vi.fn(async () => [])
    } else if (arrayReturning.has(key)) {
      out[key] = async () => []
    } else if (nullReturning.has(key)) {
      out[key] = async () => null
    } else if (urlReturning.has(key)) {
      out[key] = () => ''
    } else {
      out[key] = async () => undefined
    }
  }
  return out
})

import App from './App'
import { I18nProvider } from './i18n'
import { ServicesProvider } from './contexts/ServicesContext'
import { createWsRouter, type WsRouterImpl } from './adapters/ws/router'
import * as api from './services/api'

const DEV = (udid: string) => ({
  udid, name: udid, ios_version: '17.0', connection_type: 'USB', is_connected: true,
})

function renderApp(router: WsRouterImpl) {
  return render(
    <I18nProvider>
      <ServicesProvider value={{ api, ws: router, sendMessage: vi.fn(), connected: true }}>
        <App />
      </ServicesProvider>
    </I18nProvider>,
  )
}

async function connectDevices(router: WsRouterImpl, udids: string[]) {
  vi.mocked(api.listDevices).mockResolvedValue(udids.map(DEV) as any)
  await act(async () => {
    for (const u of udids) router.dispatch({ type: 'device_connected', udid: u })
  })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
}

beforeEach(() => {
  try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
})

afterEach(() => {
  vi.clearAllMocks()
  try { localStorage.clear() } catch { /* ignore */ }
})

// ════════════════════════════════════════════════════════════════════════════
// Global keyboard shortcuts wiring
// ════════════════════════════════════════════════════════════════════════════
describe('App — global keyboard shortcuts wiring', () => {
  it('Space dispatched on document calls api.stopSim (single device, no udid)', async () => {
    // Render App with a single connected device, then fire Space on document.
    // The single-device path calls api.stopSim() WITHOUT a udid arg.
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])

    await act(async () => {
      fireEvent.keyDown(document, { code: 'Space', key: ' ' })
    })

    expect(api.stopSim).toHaveBeenCalledTimes(1)
    // Single-device path: stopSim called without a udid argument.
    const call = vi.mocked(api.stopSim).mock.calls[0]
    expect(call[0]).toBeUndefined()
  })

  it('Space dispatched while an INPUT is focused does NOT call api.stopSim', async () => {
    // Render App, locate the .search-input, focus it, then fire Space on the
    // input element. The keyDown bubbles to document with e.target = the input,
    // so isTypingTarget returns true and the shortcut is suppressed.
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])

    // The AddressSearch input carries className="search-input".
    const inputEl = document.querySelector<HTMLInputElement>('.search-input')
    expect(inputEl).not.toBeNull()

    await act(async () => {
      inputEl!.focus()
      // Dispatch keyDown on the focused input — it bubbles to document with
      // e.target = the input, so isTypingTarget(e.target) === true.
      fireEvent.keyDown(inputEl!, { code: 'Space', key: ' ' })
    })

    expect(api.stopSim).not.toHaveBeenCalled()
  })

  it('Cmd+K focuses the address-search input', async () => {
    // Render App, dispatch Cmd+K on document, assert .search-input is focused.
    const router = createWsRouter()
    await act(async () => { renderApp(router) })

    // Ensure the input is present.
    const inputEl = document.querySelector<HTMLInputElement>('.search-input')
    expect(inputEl).not.toBeNull()

    await act(async () => {
      fireEvent.keyDown(document, { key: 'k', metaKey: true })
    })

    expect(document.activeElement).toBe(inputEl)
  })
})
