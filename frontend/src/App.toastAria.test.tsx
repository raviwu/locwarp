import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen } from '@testing-library/react'

// MapView pulls Leaflet/MapLibre — render nothing (same as App.smoke.test.tsx).
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
    if (typeof actual[key] !== 'function') { out[key] = actual[key]; continue }
    if (key === 'cloudSyncStatus') {
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

function renderApp(router: WsRouterImpl, connected = true) {
  return render(
    <I18nProvider>
      <ServicesProvider value={{ api, ws: router, sendMessage: vi.fn(), connected }}>
        <App />
      </ServicesProvider>
    </I18nProvider>,
  )
}

beforeEach(() => { try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ } })
afterEach(() => { try { localStorage.clear() } catch { /* ignore */ } })

describe('App toast a11y (U19)', () => {
  it('renders the toast inside a polite live region (role=status, aria-live=polite)', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })

    // No primaryDevice in this harness -> useSimulation's udid guard is skipped
    // and the positive 'WiFi tunnel restored' toast fires unconditionally.
    await act(async () => {
      router.dispatch({ type: 'tunnel_recovered' })
    })

    // 'wifi.tunnel_recovered' resolves to its English string via I18nProvider.
    const region = await screen.findByRole('status')
    expect(region).toHaveAttribute('aria-live', 'polite')
    // The toast message text lives inside the same live-region node.
    expect(region.textContent && region.textContent.length).toBeGreaterThan(0)
  })
})
