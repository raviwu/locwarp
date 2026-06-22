import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen } from '@testing-library/react'

// ─────────────────────────────────────────────────────────────────────────────
// CHARACTERIZATION FOUNDATION (Phase 4b, task p4b1) — App.tsx render smoke.
//
// Pins the CURRENT composed render of the 2639-LOC App god-component BEFORE the
// upcoming decomposition. If a later extraction accidentally drops a sidebar
// panel, breaks the error-banner wiring, or stops App from mounting, these
// tests go red.
//
// HARNESS (reused by App.dangerzone.test.tsx):
//   - MapView is stubbed to a render-nothing forwardRef (Leaflet/WebGL can't
//     run in jsdom — same approach as App.singleConnection.test.tsx).
//   - services/api is mocked from the REAL module's export names via
//     importOriginal so every accessed name resolves; inert async stubs return
//     shapes that keep App's mount-time effects quiet.
//   - The ws router is a REAL createWsRouter() injected straight into a
//     ServicesProvider with connected:true. We do NOT go through ServicesRoot /
//     useWsRouter / useWebSocket here — injecting the router directly gives us a
//     `dispatch` we can pump WS frames into without opening a socket, while
//     still exercising the real useDevice / useSimulation subscription paths.
// ─────────────────────────────────────────────────────────────────────────────

// MapView pulls Leaflet/MapLibre — render nothing.
vi.mock('./components/MapView', () => ({
  default: React.forwardRef(function MapViewStub(_props: any, _ref: any) {
    return null
  }),
}))

vi.mock('./services/api', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const arrayReturning = new Set([
    'getSavedRoutes', 'getRecent', 'listRouteCategories', 'listBookmarks',
    'listCategories', 'listDevices', 'getBookmarks', 'getCategories',
  ])
  const nullReturning = new Set(['getCatalog'])
  const urlReturning = new Set(['bookmarksExportUrl', 'exportGpxUrl', 'routesExportUrl'])
  const out: Record<string, unknown> = {}
  for (const key of Object.keys(actual)) {
    if (typeof actual[key] !== 'function') {
      out[key] = actual[key]
      continue
    }
    if (key === 'cloudSyncStatus') {
      out[key] = async () => ({
        enabled: false, prompt_dismissed: true, detected_icloud_path: null,
      })
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

// Inject a real router (with dispatch) + connected:true so App's connected-gated
// effects run and the device/sim WS subscriptions are live. `sendMessage` is a
// no-op spy.
function renderApp(router: WsRouterImpl, connected = true) {
  return render(
    <I18nProvider>
      <ServicesProvider value={{ api, ws: router, sendMessage: vi.fn(), connected }}>
        <App />
      </ServicesProvider>
    </I18nProvider>,
  )
}

beforeEach(() => {
  // Deterministic English strings so banner / toast assertions are stable
  // (jsdom navigator.language is en-US, but pin it explicitly).
  try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
})

afterEach(() => {
  try { localStorage.clear() } catch { /* ignore */ }
})

describe('App render smoke (characterization)', () => {
  it('mounts and renders the sidebar shell with its panels', async () => {
    const router = createWsRouter()
    let container: HTMLElement
    await act(async () => {
      const r = renderApp(router)
      container = r.container
    })

    // App's top-level layout shell.
    expect(container!.querySelector('.app-layout')).not.toBeNull()
    const sidebar = container!.querySelector('.sidebar')
    expect(sidebar).not.toBeNull()
    expect(container!.querySelector('.sidebar-content')).not.toBeNull()

    // ControlPanel renders real — its mode section title (panel.mode) and a
    // mode button per SimMode value are the cheapest stable structural anchor.
    expect(screen.getByText('Mode')).toBeInTheDocument()
    expect(document.querySelectorAll('button.mode-btn').length).toBeGreaterThan(0)
  })

  it('surfaces a red error banner when a simulation_error WS frame arrives', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })

    // No banner before the error event.
    expect(screen.queryByText('boom from device')).not.toBeInTheDocument()

    // useSimulation subscribes to 'simulation_error' and setError(message);
    // App renders sim.error in the red banner div.
    await act(async () => {
      router.dispatch({ type: 'simulation_error', message: 'boom from device' })
    })

    expect(screen.getByText('boom from device')).toBeInTheDocument()
  })

  it('surfaces the disconnect banner when the last device drops (remaining_count 0)', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })

    // device_disconnected with remaining_count:0 → useSimulation sets the
    // localized "device disconnected" error string (English here).
    await act(async () => {
      router.dispatch({ type: 'device_disconnected', remaining_count: 0 })
    })

    expect(
      screen.getByText('Device disconnected (USB unplugged or tunnel died), please reconnect USB'),
    ).toBeInTheDocument()
  })
})
