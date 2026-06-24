import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen, fireEvent, waitFor } from '@testing-library/react'

// Stub ControlPanel to surface category add handler as a testable button.
vi.mock('./components/ControlPanel', () => ({
  default: (p: any) => (
    <button data-testid="cp-cat-add" onClick={() => p.onCategoryAdd?.('NewCat')} />
  ),
}))

// MapView pulls Leaflet/MapLibre (no canvas/WebGL in jsdom). Stub it.
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
  // Deterministic English strings for stable queries.
  try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
})

afterEach(() => {
  vi.clearAllMocks()
  try { localStorage.clear() } catch { /* ignore */ }
})

describe('App category mutation failure toasts (U14)', () => {
  it('shows a failure toast when a category add rejects (U14)', async () => {
    // Force api.createCategory to reject.
    vi.mocked(api.createCategory).mockRejectedValueOnce(new Error('boom'));
    const router = createWsRouter();
    await act(async () => { renderApp(router); });
    fireEvent.click(screen.getByTestId('cp-cat-add'));
    await waitFor(() =>
      expect(screen.getByText(/Add category failed/i)).toBeInTheDocument(),
    );
  });
})
