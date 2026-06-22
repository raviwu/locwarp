import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen, fireEvent, waitFor } from '@testing-library/react'

// ─────────────────────────────────────────────────────────────────────────────
// COVERAGE-GAP CLOSURE (Phase 4b, task p4b1) — two App-level characterizations
// surfaced by an adversarial review of the App.tsx decomposition.
//
//   GAP 1 — AppAddBookmark functional-updater micro-fix.
//     The add-bookmark dialog's onNameChange now goes through App's
//     setAddBmDialog((prev) => prev ? { ...prev, name } : prev) functional
//     updater. The monolith used an object-spread over a STALE addBmDialog
//     snapshot, so a keystroke that landed AFTER reverseGeocode resolved would
//     momentarily wipe the just-resolved countryCode (the flag flickered away).
//     The component test (AppAddBookmarkDialog.test.tsx) can't pin this — the
//     dialog is controlled and owns no state; countryCode survival lives in
//     App's setState closure. This test drives the REAL flow at App level:
//     open → resolve geocode (countryCode set) → type a char → assert the flag
//     is STILL present and the name updated.
//
//   GAP 2 — the single combined cloud-sync after-closure fan-out.
//     App registers ONE useCloudSyncAfter(Promise.all([bm.refresh(),
//     routes.refresh()])). _setAfter is last-writer-wins, so a future second
//     registration (or dropping one leg of the Promise.all) would silently stop
//     refreshing one store. This test fires the discovery → cloudSyncEnable()
//     path and asserts BOTH stores re-fetch after the toggle resolves.
//
// HARNESS: same shape as App.smoke / App.dangerzone — MapView stubbed, services/
// api built from the REAL export names via importOriginal so every accessed name
// resolves, a real createWsRouter() + connected:true injected through
// ServicesProvider. The MapView stub additionally surfaces onAddBookmark as a
// button so we can open the App-level add-bookmark dialog from the test.
// ─────────────────────────────────────────────────────────────────────────────

// MapView pulls Leaflet/MapLibre (no canvas/WebGL in jsdom). Stub it, and surface
// onAddBookmark(lat,lng) — the right-click-menu callback App wires at line ~1335
// (onAddBookmark={handleAddBookmark}) — as a clickable button so the test can
// open the App-level add-bookmark dialog.
vi.mock('./components/MapView', () => ({
  default: React.forwardRef(function MapViewStub(props: any, _ref: any) {
    return (
      <div data-testid="mapview">
        <button
          data-testid="map-add-bookmark"
          onClick={() => props.onAddBookmark?.(25.0478, 121.5319)}
        />
      </div>
    )
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
  // Endpoints we inspect — fresh spies so call counts / args are observable.
  // The four refresh legs (getBookmarks + getCategories = bm.refresh;
  // getSavedRoutes + listRouteCategories = routes.refresh) plus reverseGeocode
  // and the cloud-sync toggle.
  const spied: Record<string, () => any> = {
    getBookmarks: () => [],
    getCategories: () => [],
    getSavedRoutes: () => [],
    listRouteCategories: () => [],
    reverseGeocode: () => null,
    cloudSyncEnable: () => ({ ok: true }),
  }
  const out: Record<string, unknown> = {}
  for (const key of Object.keys(actual)) {
    if (typeof actual[key] !== 'function') { out[key] = actual[key]; continue }
    if (key in spied) {
      out[key] = vi.fn(async () => spied[key]())
    } else if (key === 'cloudSyncStatus') {
      // Default: nothing to prompt. The cloud-sync test overrides this per-test
      // to drive the discovery → enable path.
      out[key] = vi.fn(async () => ({
        enabled: false, prompt_dismissed: true, detected_icloud_path: null,
      }))
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

function renderApp(router: WsRouterImpl) {
  return render(
    <I18nProvider>
      <ServicesProvider value={{ api, ws: router, sendMessage: vi.fn(), connected: true }}>
        <App />
      </ServicesProvider>
    </I18nProvider>,
  )
}

beforeEach(() => {
  // Deterministic English strings (placeholders / flag alt) for stable queries.
  try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
})

afterEach(() => {
  vi.clearAllMocks()
  try { localStorage.clear() } catch { /* ignore */ }
})

// ════════════════════════════════════════════════════════════════════════════
// GAP 1 — functional-updater preserves countryCode across a post-resolve keystroke
// ════════════════════════════════════════════════════════════════════════════
describe('AppAddBookmark functional updater (countryCode survives a keystroke)', () => {
  it('keeps the resolved country flag when a character is typed after reverseGeocode resolves', async () => {
    // reverseGeocode resolves with a country_code but NO short/display name, so
    // App's resolve branch sets countryCode + nameResolving:false and leaves the
    // (empty) name field for the user. The dialog then shows the flag.
    vi.mocked(api.reverseGeocode).mockResolvedValue({ country_code: 'TW' } as any)

    const router = createWsRouter()
    await act(async () => { renderApp(router) })

    // Open the App-level add-bookmark dialog (right-click → Add bookmark).
    await act(async () => { fireEvent.click(screen.getByTestId('map-add-bookmark')) })

    // After the geocode microtask flushes the dialog is no longer resolving and
    // the country flag is shown (English alt is the uppercased code).
    const flag = await screen.findByAltText('TW') as HTMLImageElement
    expect(flag.src).toContain('flagcdn.com/w20/tw.png')

    // Now type a character into the name field. App's onNameChange runs the
    // functional updater setAddBmDialog((prev) => prev ? { ...prev, name } : prev)
    // — the monolith's object-spread over a stale snapshot would have dropped
    // countryCode here, flickering the flag away.
    const input = screen.getByPlaceholderText('Bookmark name') as HTMLInputElement
    await act(async () => { fireEvent.change(input, { target: { value: 'T' } }) })

    // Name updated …
    expect(input.value).toBe('T')
    // … AND the flag is STILL rendered (countryCode preserved across the keystroke).
    const flagAfter = screen.getByAltText('TW') as HTMLImageElement
    expect(flagAfter.src).toContain('flagcdn.com/w20/tw.png')
  })
})

// ════════════════════════════════════════════════════════════════════════════
// GAP 2 — the single combined useCloudSyncAfter closure fans out to BOTH stores
// ════════════════════════════════════════════════════════════════════════════
describe('cloud-sync combined after-closure fan-out', () => {
  it('refreshes BOTH the bookmark store and the route store after cloudSyncEnable resolves', async () => {
    // Drive useCloudSyncDiscovery down the enable branch: status reports an
    // un-dismissed prompt with a detected iCloud path and sync disabled, so App
    // calls window.confirm; stub it true so run(() => api.cloudSyncEnable()) fires.
    vi.mocked(api.cloudSyncStatus).mockResolvedValue({
      enabled: false, prompt_dismissed: false, detected_icloud_path: '/some/path',
    } as any)
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    const router = createWsRouter()
    await act(async () => { renderApp(router) })

    // Confirm was shown (we're really on the enable path, not the dismissed one).
    expect(confirmSpy).toHaveBeenCalledTimes(1)

    // The toggle ran, then the ONE combined useCloudSyncAfter closure fired
    // Promise.all([bm.refresh(), routes.refresh()]). bm.refresh() = getBookmarks
    // + getCategories; routes.refresh() = getSavedRoutes + listRouteCategories.
    await waitFor(() => expect(api.cloudSyncEnable).toHaveBeenCalledTimes(1))

    // Both stores' refresh legs fire AFTER the toggle. Each is also called once
    // on mount, so we assert the post-enable call count strictly exceeds the
    // mount baseline (1) — i.e. the after-closure actually re-fetched both.
    // If a future second useCloudSyncAfter clobbered this closure, or the
    // Promise.all dropped a leg, one of these would stay at the mount baseline.
    await waitFor(() => {
      expect(vi.mocked(api.getBookmarks).mock.calls.length).toBeGreaterThanOrEqual(2)
      expect(vi.mocked(api.getSavedRoutes).mock.calls.length).toBeGreaterThanOrEqual(2)
    })

    confirmSpy.mockRestore()
  })
})
