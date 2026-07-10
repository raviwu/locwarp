import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen, fireEvent } from '@testing-library/react'

// ─────────────────────────────────────────────────────────────────────────────
// Task 8: `onRecentReFly` (App.tsx:1147) is the one piece of this fix that
// can't be exercised through `useSimActions.test.ts` alone — `isRunning`
// (App.tsx:955) and the isRouteStop→record:false wiring are App-local. This
// file follows the mock-list idiom of `App.dangerzone.test.tsx` /
// `App.smoke.test.tsx`: MapView is stubbed (Leaflet can't run in jsdom) with
// buttons that surface the callbacks under test, services/api is mocked from
// the real module's export names via importOriginal, and a real
// `createWsRouter()` is injected so useDevice's WS subscription works.
//
// Covers:
//   - route_stop re-fly does not push a duplicate Recent entry (isRouteStop→
//     record:false), manual re-fly still does (isRouteStop is False for other
//     kinds) — mirrors useSimActions.test.ts's opts.record assertions but
//     through the real onRecentReFly wiring instead of calling the opt
//     directly.
//   - re-fly while a simulation is running raises toast.sim_stopped_by_refly;
//     re-fly while nothing is running does not.
//   - a re-fly that itself fails must NOT be masked by the interruption toast
//     (onRecentReFly only toasts when `ok && isRunning`).
// ─────────────────────────────────────────────────────────────────────────────

// MapView pulls Leaflet/MapLibre — stub with buttons that surface exactly the
// callbacks this file drives. `onNavigate` doubles as the "start a running
// simulation" trigger: sim.navigate() (the real useSimulation method) sets
// status.running=true on success, same as the real navigate button would.
vi.mock('./components/MapView', () => ({
  default: React.forwardRef(function MapViewStub(props: any, _ref: any) {
    return (
      <div data-testid="mapview">
        <button data-testid="map-navigate" onClick={() => props.onNavigate?.(30, 40)} />
        <button
          data-testid="map-refly-route-stop"
          onClick={() => props.onRecentReFly?.({ lat: 10, lng: 20, kind: 'route_stop', name: 'stop', ts: 1 })}
        />
        <button
          data-testid="map-refly-manual-teleport"
          onClick={() => props.onRecentReFly?.({ lat: 10, lng: 20, kind: 'teleport', name: 'manual', ts: 1 })}
        />
        <button
          data-testid="map-refly-navigate"
          onClick={() => props.onRecentReFly?.({ lat: 10, lng: 20, kind: 'navigate', name: 'nav', ts: 1 })}
        />
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
  // Endpoints we assert on — fresh spies so call args are inspectable.
  const spied = new Set(['teleport', 'navigate', 'pushRecent'])
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

// Bring connectedDevices up to `udids` (see App.dangerzone.test.tsx's helper
// of the same name/shape).
async function connectDevices(router: WsRouterImpl, udids: string[]) {
  vi.mocked(api.listDevices).mockResolvedValue(udids.map(DEV) as any)
  await act(async () => {
    for (const u of udids) router.dispatch({ type: 'device_connected', udid: u })
  })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
}

async function startRunningSim() {
  await act(async () => { fireEvent.click(screen.getByTestId('map-navigate')) })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
}

beforeEach(() => {
  try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
})

afterEach(() => {
  vi.clearAllMocks()
  try { localStorage.clear() } catch { /* ignore */ }
})

describe('onRecentReFly (Task 8)', () => {
  it('re-flying a route_stop entry does not push a duplicate Recent entry', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])

    await act(async () => { fireEvent.click(screen.getByTestId('map-refly-route-stop')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(api.pushRecent).not.toHaveBeenCalled()
  })

  it('re-flying a manual entry still pushes a Recent entry', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])

    await act(async () => { fireEvent.click(screen.getByTestId('map-refly-manual-teleport')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(api.pushRecent).toHaveBeenCalledWith({ lat: 10, lng: 20, kind: 'teleport', name: null })
  })

  it('raises toast.sim_stopped_by_refly when a re-fly interrupts a running simulation', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])
    await startRunningSim()

    await act(async () => { fireEvent.click(screen.getByTestId('map-refly-manual-teleport')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(screen.getByText('Interrupted the running simulation')).toBeInTheDocument()
  })

  it('raises no interruption toast when nothing is running', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])

    await act(async () => { fireEvent.click(screen.getByTestId('map-refly-manual-teleport')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(screen.queryByText('Interrupted the running simulation')).not.toBeInTheDocument()
  })

  it('does not overwrite a failure toast with the interruption toast', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])
    await startRunningSim()
    vi.mocked(api.teleport).mockRejectedValueOnce(new Error('boom'))

    await act(async () => { fireEvent.click(screen.getByTestId('map-refly-manual-teleport')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(screen.getByText('Teleport failed')).toBeInTheDocument()
    expect(screen.queryByText('Interrupted the running simulation')).not.toBeInTheDocument()
  })

  it('raises toast.sim_stopped_by_refly when re-flying a navigate row interrupts a running simulation', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])
    await startRunningSim()

    await act(async () => { fireEvent.click(screen.getByTestId('map-refly-navigate')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(screen.getByText('Interrupted the running simulation')).toBeInTheDocument()
  })

  it('does not overwrite a failure toast with the interruption toast when a navigate re-fly fails', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })
    await connectDevices(router, ['A'])
    await startRunningSim()
    vi.mocked(api.navigate).mockRejectedValueOnce(new Error('boom'))

    await act(async () => { fireEvent.click(screen.getByTestId('map-refly-navigate')) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(screen.getByText('Navigate failed')).toBeInTheDocument()
    expect(screen.queryByText('Interrupted the running simulation')).not.toBeInTheDocument()
  })
})
