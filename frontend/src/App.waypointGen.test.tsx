import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen, fireEvent, waitFor } from '@testing-library/react'

// Stub ControlPanel: surface mode-switch button AND pass modeExtraSection through.
vi.mock('./components/ControlPanel', () => ({
  default: (p: any) => (
    <>
      <button data-testid="cp-mode-loop" onClick={() => p.onModeChange?.('loop')} />
      {p.modeExtraSection}
    </>
  ),
}))

// MapView stub (no Leaflet/MapLibre in jsdom).
vi.mock('./components/MapView', () => ({
  default: React.forwardRef(function MapViewStub(_props: any, _ref: any) {
    return <div data-testid="mapview" />
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
    if (typeof actual[key] !== 'function') { out[key] = actual[key]; continue }
    if (key === 'cloudSyncStatus') {
      out[key] = vi.fn(async () => ({
        enabled: false, prompt_dismissed: true, detected_icloud_path: null,
      }))
    } else if (key === 'getCooldownStatus' || key === 'getStatus') {
      out[key] = async () => ({})
    } else if (arrayReturning.has(key)) {
      out[key] = vi.fn(async () => [])
    } else if (nullReturning.has(key)) {
      out[key] = async () => null
    } else if (urlReturning.has(key)) {
      out[key] = () => ''
    } else {
      out[key] = vi.fn(async () => undefined)
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
  try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
})

afterEach(() => {
  vi.clearAllMocks()
  try { localStorage.clear() } catch { /* ignore */ }
})

describe('App waypoint generation no-alert (U26)', () => {
  it('uses a toast (not a native alert) when generating waypoints with no position (U26)', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const router = createWsRouter();
    await act(async () => { renderApp(router); });

    // Switch to loop mode so WaypointEditor's modeExtraSection renders.
    fireEvent.click(screen.getByTestId('cp-mode-loop'));

    // Click the generate-random-waypoints button (EN: 'Random').
    fireEvent.click(screen.getByText('Random'));

    expect(alertSpy).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(
        screen.getByText('No current position, cannot generate random waypoints'),
      ).toBeInTheDocument(),
    );
    alertSpy.mockRestore();
  });
})
