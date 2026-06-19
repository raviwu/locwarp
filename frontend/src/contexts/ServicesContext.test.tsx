import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import React from 'react'
import { ServicesProvider, useServices } from './ServicesContext'
import { createWsRouter } from '../adapters/ws/router'

// ── useServices provider tests ──────────────────────────────────────────────

describe('useServices', () => {
  it('exposes the injected api, ws, sendMessage, and connected', () => {
    const ws = createWsRouter()
    const api = { listDevices: vi.fn() }
    const sendMessage = vi.fn()
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <ServicesProvider value={{ api: api as any, ws, sendMessage, connected: true }}>{children}</ServicesProvider>
    )
    const { result } = renderHook(() => useServices(), { wrapper })
    expect(result.current.api).toBe(api)
    expect(result.current.ws).toBe(ws)
    expect(result.current.sendMessage).toBe(sendMessage)
    expect(result.current.connected).toBe(true)
  })

  it('throws if used outside the provider', () => {
    expect(() => renderHook(() => useServices())).toThrow(/ServicesProvider/)
  })
})

// ── live-socket → router bridge (useWsRouter) ────────────────────────────────
// We mock useWebSocket so we can drive the subscriber callback manually and
// verify that router.dispatch fires the right typed handlers synchronously.

// Capture the subscriber registered by useWsRouter so tests can invoke it.
let capturedSubscriber: ((msg: { type: string; data: any }) => void) | null = null

vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: () => {
    const subscribe = vi.fn((fn: (msg: { type: string; data: any }) => void) => {
      capturedSubscriber = fn
      // Return a cleanup function (unsubscribe)
      return () => { capturedSubscriber = null }
    })
    return { subscribe, sendMessage: vi.fn(), connected: true }
  },
}))

// Import AFTER the mock so the module picks up the mocked useWebSocket.
// Dynamic import inside the describe block ensures the mock is already in
// place when the module resolves.
describe('useWsRouter bridge', () => {
  beforeEach(() => {
    capturedSubscriber = null
  })

  it('flattens {type, data} and dispatches to typed router subscribers', async () => {
    // Dynamically import useWsRouter after mock is registered.
    const { useWsRouter } = await import('../adapters/ws/useWsRouter')

    const handler = vi.fn()
    let routerRef: ReturnType<typeof createWsRouter> | null = null

    const { result } = renderHook(() => useWsRouter())
    routerRef = result.current.router

    // Subscribe a typed handler to the router.
    act(() => {
      routerRef!.subscribe('device_disconnected', handler)
    })

    // Simulate a raw WS frame arriving via the useWebSocket subscriber.
    expect(capturedSubscriber).not.toBeNull()
    act(() => {
      capturedSubscriber!({
        type: 'device_disconnected',
        data: { udid: 'UDID-TEST', remaining_count: 2 },
      })
    })

    // Handler should have received the flattened event (top-level keys).
    expect(handler).toHaveBeenCalledTimes(1)
    expect(handler).toHaveBeenCalledWith({
      type: 'device_disconnected',
      udid: 'UDID-TEST',
      remaining_count: 2,
    })
  })

  it('router ref is stable across renders (useMemo with empty deps)', async () => {
    const { useWsRouter } = await import('../adapters/ws/useWsRouter')

    const { result, rerender } = renderHook(() => useWsRouter())
    const routerAfterFirstRender = result.current.router

    rerender()
    expect(result.current.router).toBe(routerAfterFirstRender)
  })
})
