import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act } from '@testing-library/react'

// ─────────────────────────────────────────────────────────────────────────────
// REGRESSION GUARD for commit 093428a — the single-WebSocket-connection
// invariant.
//
// THE BUG: App.tsx used to call useWebSocket() itself, opening a SECOND real
// WebSocket on top of the one ServicesProvider already opens (via useWsRouter →
// useWebSocket inside main.tsx's ServicesRoot). THE FIX: useWebSocket() is
// invoked EXACTLY ONCE — inside the provider. App and every consumer read
// {subscribe, sendMessage, connected} off useServices() instead.
//
// This test renders the REAL ServicesProvider composition (the same wiring
// main.tsx uses: ServicesRoot → useWsRouter → useWebSocket → ServicesProvider)
// wrapping the REAL <App/>, under a counting global-WebSocket stub. It does NOT
// mock ServicesContext, useWsRouter, or useWebSocket — exercising that real
// provider→single-socket path IS the test. If anyone re-adds a second
// useWebSocket() call anywhere in the rendered tree, the construction count
// climbs above 1 and the main assertion fails.
//
// The mandatory positive control (second test) wires a deliberately-wrong tree
// that ALSO calls useWebSocket() alongside the provider and asserts the count
// is 2 — proving the counter genuinely distinguishes 1 from 2, so the main
// assertion is not vacuous.
// ─────────────────────────────────────────────────────────────────────────────

// ── Counting WebSocket stub ──────────────────────────────────────────────────
// Counts constructions. Exposes the static OPEN const useWebSocket reads at
// connect() (line 41) and a no-op send/close so the hook never throws. We
// deliberately set readyState !== OPEN and never fire onopen, so:
//   - connect()'s `readyState === WebSocket.OPEN` early-return does NOT fire
//     (every mount really constructs a socket), and
//   - `connected` stays false, so App's connected-gated effects (device.scan,
//     polls, wifi auto-connect) never run and can't add network noise.
let wsConstructionCount = 0

class CountingWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  url: string
  readyState = CountingWebSocket.CONNECTING
  onopen: ((ev: any) => void) | null = null
  onclose: ((ev: any) => void) | null = null
  onmessage: ((ev: any) => void) | null = null
  onerror: ((ev: any) => void) | null = null

  constructor(url: string) {
    wsConstructionCount++
    this.url = url
  }

  send() { /* no-op */ }
  close() { this.readyState = CountingWebSocket.CLOSED }
}

let originalWebSocket: typeof globalThis.WebSocket

beforeEach(() => {
  wsConstructionCount = 0
  originalWebSocket = globalThis.WebSocket
  // @ts-expect-error — swapping in a minimal counting fake for the test.
  globalThis.WebSocket = CountingWebSocket
})

afterEach(() => {
  globalThis.WebSocket = originalWebSocket
})

// ── Mock the heavy / network-touching children that would explode in jsdom ───
// MapView pulls in Leaflet/MapLibre (no canvas/WebGL in jsdom). Replace it with
// a render-nothing stub. We deliberately do NOT mock ServicesContext,
// useWsRouter, or useWebSocket — those are the wiring under test.
vi.mock('./components/MapView', () => ({
  default: React.forwardRef(function MapViewStub(_props: any, _ref: any) {
    return null
  }),
}))

// services/api is imported by App and by the hooks (useDevice / useSimulation /
// useBookmarks). We stub every call so App's mount-time fetches don't hit the
// network or reject noisily — but we must enumerate EVERY export, because
// vitest validates each accessed name against the keys the factory returns and
// throws "No export defined" otherwise (a bare Proxy is rejected). We therefore
// build the mock from the REAL module's own export names via importOriginal and
// replace each with an inert stub, guaranteeing full coverage without listing
// dozens of names by hand. A few exports are read synchronously during render
// (e.g. bookmarksExportUrl / exportGpxUrl return URL strings; cloudSyncStatus's
// shape gates the discovery effect) so those get tailored return values.
vi.mock('./services/api', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const arrayReturning = new Set([
    'getSavedRoutes', 'getRecent', 'listRouteCategories', 'listBookmarks',
    'listCategories', 'listDevices',
    // useBookmarks reads these on mount; it does `bms.bookmarks ?? []` when the
    // result isn't an array, so returning [] keeps that path quiet.
    'getBookmarks', 'getCategories',
  ])
  // App's catalog memo does `if (!catalog) return 0` then `catalog.bookmarks
  // .filter(...)` — returning null (not []) takes the guarded early-return so
  // the `.bookmarks.filter` access never runs on a shapeless stub.
  const nullReturning = new Set(['getCatalog'])
  const urlReturning = new Set(['bookmarksExportUrl', 'exportGpxUrl', 'routesExportUrl'])
  const out: Record<string, unknown> = {}
  for (const key of Object.keys(actual)) {
    if (typeof actual[key] !== 'function') {
      // Pass through non-function exports (types are erased; constants kept).
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

// i18n strings + bundle are heavy but pure; the real I18nProvider is needed so
// useT() inside App resolves. Import everything AFTER the mocks above register.
import App from './App'
import { I18nProvider } from './i18n'
import { ServicesProvider } from './contexts/ServicesContext'
import { useWsRouter } from './adapters/ws/useWsRouter'
import * as api from './services/api'

// EXACT replica of main.tsx's ServicesRoot — the only place useWebSocket() is
// allowed to be called (transitively via useWsRouter). Keep this in lock-step
// with main.tsx.
function ServicesRoot({ children }: { children: React.ReactNode }) {
  const { router, sendMessage, connected } = useWsRouter()
  return (
    <ServicesProvider value={{ api, ws: router, sendMessage, connected }}>
      {children}
    </ServicesProvider>
  )
}

describe('single WebSocket connection invariant (093428a)', () => {
  it('opens EXACTLY ONE WebSocket for the real provider→App composition', async () => {
    // RTL render is not StrictMode, so one mount = one connect() = one
    // `new WebSocket(WS_URL)`. If App (or any consumer) re-adds its own
    // useWebSocket() call, this count climbs to 2+ and the test fails.
    //
    // Wrap in async act() so App's mount effects (and the inert mocked-api
    // promises they await) flush inside act — keeps the output free of
    // "not wrapped in act(...)" warnings. The socket is constructed
    // synchronously at mount, so the count is unaffected by the flush.
    await act(async () => {
      render(
        <I18nProvider>
          <ServicesRoot>
            <App />
          </ServicesRoot>
        </I18nProvider>,
      )
    })

    expect(wsConstructionCount).toBe(1)
  })

  // ── MANDATORY positive control ─────────────────────────────────────────────
  // Proves the counter is not vacuous: a tree that (WRONGLY) calls
  // useWebSocket() a SECOND time alongside the provider constructs TWO sockets.
  // This is exactly the regression 093428a removed. If the counting stub were
  // broken (e.g. counted once regardless), this assertion would fail too — so a
  // green positive control certifies that `toBe(1)` above genuinely guards 1
  // vs 2.
  it('positive control: a second useWebSocket() call yields TWO sockets', async () => {
    // Import the real hook (NOT mocked) — the same one the provider uses.
    const { useWebSocket } = await import('./hooks/useWebSocket')

    // A bug-shaped component that opens its own socket on top of the provider's.
    function SecondConnectionBug() {
      useWebSocket()
      return null
    }

    await act(async () => {
      render(
        <I18nProvider>
          <ServicesRoot>
            <SecondConnectionBug />
          </ServicesRoot>
        </I18nProvider>,
      )
    })

    expect(wsConstructionCount).toBe(2)
  })
})
