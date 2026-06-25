import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen, fireEvent } from '@testing-library/react'

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

describe('speed jitter settings toggle', () => {
  beforeEach(() => {
    try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
  })
  afterEach(() => {
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
