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

describe('App re-render count per position_update tick (N1 memoization guard)', () => {
  it('does NOT re-commit ControlPanel/MapView on repeated SAME-coordinate position frames', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })

    // Reset AFTER mount so we count only the steady-state ticks, not the
    // initial mount + the mount-effect flushes (status fetch, scan, etc.).
    counts.control = 0
    counts.map = 0

    // Establish a position with the FIRST frame. This legitimately changes
    // currentPos (null -> {lat,lng}), so ControlPanel + MapView SHOULD commit
    // exactly once here. We count it, then assert the *subsequent* identical
    // frames add nothing.
    const LAT = 25.0330
    const LNG = 121.5654
    await act(async () => {
      router.dispatch({
        type: 'position_update',
        lat: LAT, lng: LNG,
        progress: 0, distance_remaining: 100, distance_traveled: 0,
      })
    })
    const controlAfterFirst = counts.control
    const mapAfterFirst = counts.map

    // Now dispatch REPEATED frames with the SAME lat/lng. useSimulation's
    // handler still calls setCurrentPosition({lat,lng}) on each one — a FRESH
    // object literal every tick (useSimulation.ts L312) — so App re-renders.
    // But:
    //   • currentPos / destPos are VALUE-keyed memos (App.tsx) → the ref stays
    //     stable because lat/lng are unchanged.
    //   • the ~8 action handlers from useSimActions are []-stable (ref-mirror).
    // So the memo'd children must short-circuit and NOT commit again.
    //
    // WITHOUT the N1 fix this fails hard: the useSimActions handlers were keyed
    // on [sim, device, …] (fresh objects every render), so their refs changed
    // every frame, the memo shallow-compare missed, and BOTH children committed
    // on every one of these frames (verified by stashing the fix: control/map
    // jump from 1 to 1+REPEAT_FRAMES). See sh3-s4-report.md.
    const REPEAT_FRAMES = 5
    for (let i = 0; i < REPEAT_FRAMES; i++) {
      await act(async () => {
        router.dispatch({
          type: 'position_update',
          lat: LAT, lng: LNG,
          progress: 0, distance_remaining: 100, distance_traveled: 0,
        })
      })
    }

    // The first frame committed once (coordinate change). The 5 identical
    // follow-up frames must add ZERO commits — that is the whole point of the
    // memoization. (Absolute count is the first-frame commit, unchanged.)
    expect(counts.control).toBe(controlAfterFirst)
    expect(counts.map).toBe(mapAfterFirst)
    // And the first frame itself should have committed exactly once each.
    expect(controlAfterFirst).toBe(1)
    expect(mapAfterFirst).toBe(1)
  })
})
