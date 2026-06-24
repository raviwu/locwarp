import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen, fireEvent, waitFor } from '@testing-library/react'

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

const DEV = (udid: string, connected: boolean) => ({
  udid, name: udid, ios_version: '17.0', connection_type: 'USB', is_connected: connected,
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

beforeEach(() => { try { localStorage.setItem('locwarp.lang', 'en') } catch {} })
afterEach(() => { vi.restoreAllMocks(); try { localStorage.clear() } catch {} })

describe('App device-connect feedback (U1)', () => {
  it('shows a toast when a dropdown device-connect fails', async () => {
    // Two devices so the dropdown renders without auto-connecting (scan auto-
    // connects only when exactly one device is present).
    vi.spyOn(api, 'listDevices').mockResolvedValue([DEV('A', false), DEV('B', false)] as any)
    vi.spyOn(api, 'connectDevice').mockRejectedValue(new Error('connect boom'))

    const router = createWsRouter()
    await act(async () => { renderApp(router) })

    // Open the device dropdown (summary button shows the count) and pick a row.
    await waitFor(() => expect(screen.getByText('2 device(s) found')).toBeInTheDocument())
    fireEvent.click(screen.getByText('2 device(s) found'))
    fireEvent.click(screen.getByText('A'))

    // The connect rejects -> onSelect must surface a toast. Mirroring the
    // onRestoreOne sibling, the handler surfaces the rejection's message
    // ("connect boom") and only falls back to the device.connect_failed key
    // when the error has none. Assert the surfaced message.
    await waitFor(() => expect(screen.getByText('connect boom')).toBeInTheDocument())
  })
})
