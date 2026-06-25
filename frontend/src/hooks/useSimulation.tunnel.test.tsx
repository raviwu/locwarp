import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { createWsRouter } from '../adapters/ws/router'
import { useSimulation } from './useSimulation'
import * as api from '../services/api'

vi.mock('../services/api')

beforeEach(() => {
  localStorage.removeItem('locwarp.lang')
  vi.mocked(api.getStatus).mockResolvedValue({ position: null, mode: null, running: false, paused: false, speed: 0 } as any)
})

afterEach(() => {
  vi.useRealTimers()
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

  it('tunnel_degraded with attempt keys populates reconnectInfo', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))
    act(() => {
      ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-a', reason: 'task_exited', attempt: 1, max_attempts: 3, next_delay_s: 6 })
    })
    expect(result.current.reconnectInfo).toEqual({ attempt: 1, maxAttempts: 3, retryInSec: 6 })
  })

  it('tunnel_degraded without attempt keys leaves reconnectInfo null', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))
    act(() => { ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-a', reason: 'task_exited' }) })
    expect(result.current.tunnelReconnecting).toBe(true)
    expect(result.current.reconnectInfo).toBeNull()
  })

  it('reconnectInfo is cleared on tunnel_recovered', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))
    act(() => {
      ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-a', attempt: 2, max_attempts: 3, next_delay_s: 12 })
    })
    expect(result.current.reconnectInfo).not.toBeNull()
    act(() => { ws.dispatch({ type: 'tunnel_recovered', udid: 'dev-a', rsd_address: 'x', rsd_port: 1 }) })
    expect(result.current.reconnectInfo).toBeNull()
  })

  it('reconnectInfo is cleared on tunnel_lost', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))
    act(() => {
      ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-a', attempt: 1, max_attempts: 3, next_delay_s: 6 })
    })
    expect(result.current.reconnectInfo).not.toBeNull()
    act(() => { ws.dispatch({ type: 'tunnel_lost', udid: 'dev-a', reason: 'task_exited' }) })
    expect(result.current.reconnectInfo).toBeNull()
  })

  // ── Finding 1: countdown arms once per round, ticks internally ──────────
  // The dep array uses [attempt, maxAttempts] rather than the full object so
  // each retryInSec tick does NOT re-arm the interval. This test verifies the
  // countdown still decrements correctly (6→5→4→…→0) and floors at 0.
  it('countdown ticks retryInSec from 6 down to 0 and does not go negative (arm-once-per-round)', () => {
    vi.useFakeTimers()
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))

    act(() => {
      ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-a', attempt: 1, max_attempts: 3, next_delay_s: 6 })
    })
    expect(result.current.reconnectInfo?.retryInSec).toBe(6)

    // tick 1s → 5
    act(() => { vi.advanceTimersByTime(1000) })
    expect(result.current.reconnectInfo?.retryInSec).toBe(5)

    // tick 1s → 4
    act(() => { vi.advanceTimersByTime(1000) })
    expect(result.current.reconnectInfo?.retryInSec).toBe(4)

    // advance the remaining 4s → should reach exactly 0, not go negative
    act(() => { vi.advanceTimersByTime(4000) })
    expect(result.current.reconnectInfo?.retryInSec).toBe(0)

    // one more tick must not go below 0
    act(() => { vi.advanceTimersByTime(1000) })
    expect(result.current.reconnectInfo?.retryInSec).toBe(0)
  })

  it('tunnel_lost captures the lost udid', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))
    act(() => { ws.dispatch({ type: 'tunnel_lost', udid: 'dev-lost', reason: 'task_exited' }) })
    expect(result.current.lostUdid).toBe('dev-lost')
  })

  it('tunnel_recovered clears lostUdid', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))
    act(() => { ws.dispatch({ type: 'tunnel_lost', udid: 'dev-lost' }) })
    expect(result.current.lostUdid).toBe('dev-lost')
    act(() => { ws.dispatch({ type: 'tunnel_recovered', udid: 'dev-lost', rsd_address: 'x', rsd_port: 1 }) })
    expect(result.current.lostUdid).toBeNull()
  })

  // ── Finding 2: device_connected is a backstop that clears reconnectInfo ──
  it('device_connected clears reconnectInfo (backstop clear path)', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))

    act(() => {
      ws.dispatch({ type: 'tunnel_degraded', udid: 'dev-a', attempt: 2, max_attempts: 3, next_delay_s: 12 })
    })
    expect(result.current.reconnectInfo).toEqual({ attempt: 2, maxAttempts: 3, retryInSec: 12 })

    act(() => { ws.dispatch({ type: 'device_connected', udid: 'dev-a', connection_type: 'Network' }) })
    expect(result.current.reconnectInfo).toBeNull()
  })
})
