import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { createWsRouter } from '../adapters/ws/router'
import { useSimulation } from './useSimulation'
import * as api from '../services/api'

vi.mock('../services/api')

beforeEach(() => {
  localStorage.removeItem('locwarp.lang')
  vi.mocked(api.getStatus).mockResolvedValue({ position: null, mode: null, running: false, paused: false, speed: 0 } as any)
})

// The WiFi-tunnel three-state lifecycle (per-udid, primary-filtered):
//   tunnel_degraded  → reconnecting indicator ON  (backend retry window)
//   tunnel_recovered → reconnecting OFF + clear banner + recovery toast
//   tunnel_lost      → reconnecting OFF + terminal error banner
describe('useSimulation — WiFi tunnel three-state', () => {
  it('tunnel_degraded turns on the reconnecting indicator', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))

    expect(result.current.tunnelReconnecting).toBe(false)
    act(() => { ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-a', reason: 'task_exited' }) })
    expect(result.current.tunnelReconnecting).toBe(true)
    expect(result.current.error).toBeNull()
  })

  it('degraded → recovered clears the indicator and fires the recovery toast', () => {
    const onRecovered = vi.fn()
    const primary = 'dev-a'
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, primary, onRecovered))

    act(() => { ws.dispatch({ type: 'tunnel_degraded', udid: primary }) })
    expect(result.current.tunnelReconnecting).toBe(true)

    act(() => { ws.dispatch({ type: 'tunnel_recovered', udid: primary, rsd_address: 'fd00::1', rsd_port: 49152 }) })
    expect(result.current.tunnelReconnecting).toBe(false)
    expect(result.current.error).toBeNull()
    expect(onRecovered).toHaveBeenCalledTimes(1)
  })

  it('degraded → lost drops the indicator and raises the terminal banner (no toast)', () => {
    const onRecovered = vi.fn()
    const primary = 'dev-a'
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, primary, onRecovered))

    act(() => { ws.dispatch({ type: 'tunnel_degraded', udid: primary }) })
    expect(result.current.tunnelReconnecting).toBe(true)

    act(() => { ws.dispatch({ type: 'tunnel_lost', udid: primary, reason: 'task_exited' }) })
    expect(result.current.tunnelReconnecting).toBe(false)
    expect(result.current.error).toBeTruthy() // terminal banner up
    expect(onRecovered).not.toHaveBeenCalled()
  })

  it('en banner copy on terminal loss when lang=en', () => {
    localStorage.setItem('locwarp.lang', 'en')
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))
    act(() => { ws.dispatch({ type: 'tunnel_lost', udid: 'dev-a' }) })
    expect(result.current.error).toBe('Wi-Fi tunnel dropped, please reconnect')
  })

  // ── dual-device: a NON-primary device's tunnel events must not drive the
  //    primary-focused indicator/toast ──
  it('non-primary tunnel_degraded does NOT turn on the indicator', () => {
    const primary = 'dev-primary'
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, primary))

    act(() => { ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-other' }) })
    expect(result.current.tunnelReconnecting).toBe(false)
  })

  it('non-primary tunnel_recovered does NOT fire the toast or clear the indicator', () => {
    const onRecovered = vi.fn()
    const primary = 'dev-primary'
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, primary, onRecovered))

    // primary is genuinely reconnecting
    act(() => { ws.dispatch({ type: 'tunnel_degraded', udid: primary }) })
    expect(result.current.tunnelReconnecting).toBe(true)

    // a different device recovering must not touch the primary's state
    act(() => { ws.dispatch({ type: 'tunnel_recovered', udid: 'dev-other', rsd_address: 'x', rsd_port: 1 }) })
    expect(result.current.tunnelReconnecting).toBe(true)
    expect(onRecovered).not.toHaveBeenCalled()
  })

  it('device_connected after recovery is a backstop that also clears the indicator', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))
    act(() => { ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-a' }) })
    expect(result.current.tunnelReconnecting).toBe(true)
    act(() => { ws.dispatch({ type: 'device_connected', udid: 'dev-a', connection_type: 'Network' }) })
    expect(result.current.tunnelReconnecting).toBe(false)
  })
})
