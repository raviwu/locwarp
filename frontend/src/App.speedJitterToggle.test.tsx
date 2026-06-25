import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen, fireEvent } from '@testing-library/react'

// MapView pulls Leaflet/MapLibre — render nothing for the toggle-only tests;
// expose a navigate trigger button for the request-body threading tests.
vi.mock('./components/MapView', () => ({
  default: React.forwardRef(function MapViewStub(props: any, _ref: any) {
    return (
      <div data-testid="mapview">
        <button data-testid="map-navigate" onClick={() => props.onNavigate?.(25.05, 121.55)} />
      </div>
    )
  }),
}))

vi.mock('./services/api', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const arrayReturning = new Set([
    'getSavedRoutes', 'getRecent', 'listRouteCategories', 'listBookmarks',
    'listCategories', 'getBookmarks', 'getCategories',
  ])
  const nullReturning = new Set(['getCatalog'])
  const urlReturning = new Set(['bookmarksExportUrl', 'exportGpxUrl', 'routesExportUrl'])
  // Endpoints we spy on so call args are inspectable in the threading tests.
  const spied = new Set(['navigate', 'listDevices'])
  const out: Record<string, unknown> = {}
  for (const key of Object.keys(actual)) {
    if (typeof actual[key] !== 'function') { out[key] = actual[key]; continue }
    if (spied.has(key)) {
      out[key] = vi.fn(async () => (key === 'listDevices' ? [] : { ok: true }))
    } else if (key === 'cloudSyncStatus') {
      out[key] = async () => ({ enabled: false, prompt_dismissed: true, detected_icloud_path: null })
    } else if (key === 'getCooldownStatus' || key === 'getStatus') {
      out[key] = async () => ({})
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

function renderApp(router: WsRouterImpl, connected = true) {
  return render(
    <I18nProvider>
      <ServicesProvider value={{ api, ws: router, sendMessage: vi.fn(), connected }}>
        <App />
      </ServicesProvider>
    </I18nProvider>,
  )
}

// Simulate a device connection so connectedDevices is populated (required for
// navigate to reach the api layer — a disconnected device blocks the call).
async function connectDevice(router: WsRouterImpl, udid = 'A') {
  vi.mocked(api.listDevices).mockResolvedValue([DEV(udid)] as any)
  await act(async () => { router.dispatch({ type: 'device_connected', udid }) })
  // Flush the listDevices().then(...) microtask chain.
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
}

describe('speed jitter settings toggle', () => {
  beforeEach(() => {
    try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
  })
  afterEach(() => {
    vi.clearAllMocks()
    try { localStorage.clear() } catch { /* ignore */ }
  })

  it('defaults the speed_jitter setting to ON when the key is absent', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    const toggle = screen.getByRole('checkbox', { name: /speed.*jitter/i })
    expect((toggle as HTMLInputElement).checked).toBe(true)
    expect(localStorage.getItem('locwarp.speed_jitter')).not.toBe('0')
  })

  it('persists OFF to localStorage when toggled off', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    const toggle = screen.getByRole('checkbox', { name: /speed.*jitter/i })
    await act(async () => { fireEvent.click(toggle) })
    expect(localStorage.getItem('locwarp.speed_jitter')).toBe('0')
  })

  it('reads OFF back from localStorage on a fresh mount', async () => {
    localStorage.setItem('locwarp.speed_jitter', '0')
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    const toggle = screen.getByRole('checkbox', { name: /speed.*jitter/i })
    expect((toggle as HTMLInputElement).checked).toBe(false)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Half-2 reachability: assert the persisted toggle value is actually threaded
// into the api.navigate request body (the feature's end-to-end purpose).
//
// useSimulation calls api.navigate(..., speedJitter) where speedJitter flows
// from App state → useSimulation 4th arg → navigate useCallback closure.
// sj(false) emits { speed_jitter_enabled: false }; sj(true|undefined) emits {}
// so the field is absent on the wire when the toggle is ON.
// ─────────────────────────────────────────────────────────────────────────────
describe('speed jitter request-body threading', () => {
  beforeEach(() => {
    try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
  })
  afterEach(() => {
    vi.clearAllMocks()
    try { localStorage.clear() } catch { /* ignore */ }
  })

  it('toggle OFF: api.navigate receives speed_jitter_enabled: false in the request body', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevice(router)

    // Toggle speed jitter OFF.
    const toggle = screen.getByRole('checkbox', { name: /speed.*jitter/i })
    await act(async () => { fireEvent.click(toggle) })
    expect(localStorage.getItem('locwarp.speed_jitter')).toBe('0')

    // Trigger a navigate action via the MapView stub button.
    await act(async () => { fireEvent.click(screen.getByTestId('map-navigate')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(vi.mocked(api.navigate)).toHaveBeenCalledTimes(1)
    // The last positional arg is speedJitter (boolean false) which sj() spreads
    // into { speed_jitter_enabled: false } — verified here at the api boundary.
    const call = vi.mocked(api.navigate).mock.calls[0]
    // api.navigate(lat, lng, mode, speedOpts, udid, straightLine, routeEngine, speedJitter)
    // speedJitter is the 8th arg (index 7).
    expect(call[7]).toBe(false)
  })

  it('toggle ON (default): api.navigate payload does NOT include speed_jitter_enabled: false', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevice(router)

    // Default: toggle is ON (no localStorage key).
    const toggle = screen.getByRole('checkbox', { name: /speed.*jitter/i })
    expect((toggle as HTMLInputElement).checked).toBe(true)

    // Trigger a navigate action via the MapView stub button.
    await act(async () => { fireEvent.click(screen.getByTestId('map-navigate')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(vi.mocked(api.navigate)).toHaveBeenCalledTimes(1)
    // speedJitter arg (index 7) must NOT be false — sj(true) emits {} so the
    // field is absent from the payload, preserving the backend default.
    const call = vi.mocked(api.navigate).mock.calls[0]
    expect(call[7]).not.toBe(false)
  })
})
