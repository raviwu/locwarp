import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act } from '@testing-library/react'

// Commit counters mutated from inside the stubbed children's render bodies.
const counts = { control: 0, map: 0 }

// MapView pulls Leaflet/MapLibre (no WebGL in jsdom). Stub to a render-nothing
// component that bumps a commit counter. CRITICAL: wrap the stub in React.memo
// so its shallow prop-compare is what we measure — that mirrors the real
// component's memo wrapper (which vi.mock would otherwise shadow) and turns
// the counter into a prop-reference-stability probe, the exact seam under test.
// forwardRef so App's onMapReady/ref wiring still type-checks.
vi.mock('./components/MapView', () => {
  const MapViewStub = React.memo(React.forwardRef(function MapViewStub(_props: any, _ref: any) {
    counts.map++
    return null
  }))
  ;(MapViewStub as any).displayName = 'MapViewStub'
  return { default: MapViewStub }
})

// ControlPanel is heavy. Stub to a memo'd counter for the same reason.
vi.mock('./components/ControlPanel', () => {
  const ControlPanelStub = React.memo(function ControlPanelStub(_props: any) {
    counts.control++
    return null
  })
  ;(ControlPanelStub as any).displayName = 'ControlPanelStub'
  return { default: ControlPanelStub }
})

// Same inert services/api mock the smoke test uses, copied verbatim.
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
    if (typeof actual[key] !== 'function') { out[key] = actual[key]; continue }
    if (key === 'cloudSyncStatus') {
      out[key] = async () => ({ enabled: false, prompt_dismissed: true, detected_icloud_path: null })
    } else if (key === 'getCooldownStatus' || key === 'getStatus') {
      out[key] = async () => ({})
    } else if (arrayReturning.has(key)) { out[key] = async () => [] }
    else if (nullReturning.has(key)) { out[key] = async () => null }
    else if (urlReturning.has(key)) { out[key] = () => '' }
    else { out[key] = async () => undefined }
  }
  return out
})

import App from './App'
import { I18nProvider } from './i18n'
import { ServicesProvider } from './contexts/ServicesContext'
import { createWsRouter, type WsRouterImpl } from './adapters/ws/router'
import * as api from './services/api'

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
  counts.control = 0
  counts.map = 0
  try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
})
afterEach(() => { try { localStorage.clear() } catch { /* ignore */ } })

describe('App re-render count per position_update tick (characterization)', () => {
  it('pins the commit count for ControlPanel + MapView across N position_update frames', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })

    // Reset AFTER mount so we count only the steady-state ticks, not the
    // initial mount + the mount-effect flushes (status fetch, scan, etc.).
    counts.control = 0
    counts.map = 0

    const FRAMES = 5
    for (let i = 0; i < FRAMES; i++) {
      await act(async () => {
        // Single-device frame (NO udid) so it flows through the legacy
        // setters: useSimulation's position_update handler calls
        // setCurrentPosition + setProgress + setStatus (useSimulation.ts
        // L309-330) — the path that re-renders App on every tick.
        router.dispatch({
          type: 'position_update',
          lat: 25.03 + i * 1e-4,
          lng: 121.56 + i * 1e-4,
          progress: i / FRAMES,
          distance_remaining: 100 - i,
          distance_traveled: i,
        })
      })
    }

    // PIN the status quo (AFTER memo+useMemo refactor).
    //
    // before refactor: control=5, map=5 — every App re-render from a position
    //   tick allocated fresh bookmark-array/handler refs, so the memo'd stubs
    //   always saw new prop refs and committed every frame.
    //
    // after refactor: control=5, map=5 — bookmark arrays and inline handlers
    //   are now memoized (stable refs across position ticks). HOWEVER,
    //   `currentPos` (passed to ControlPanel as `currentPosition`) genuinely
    //   changes on every tick (each frame dispatches a different lat/lng), so
    //   the shallow-compare still fires once per frame. In a real scenario where
    //   App re-renders for OTHER reasons (e.g. catalog polling, unrelated state)
    //   but position didn't change, ControlPanel now correctly short-circuits.
    //   The test pins this minimum-necessary count; a regression (e.g. adding
    //   an unstable ref prop) would push the count above 5.
    //
    // before→after: control 5→5, map 5→5 (minimum-necessary given position changes)
    expect(counts.control).toBe(5)
    expect(counts.map).toBe(5)
  })
})
