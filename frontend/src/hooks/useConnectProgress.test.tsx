import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { createWsRouter } from '../adapters/ws/router'
import { useConnectProgress } from './useConnectProgress'

describe('useConnectProgress', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts with no phase', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useConnectProgress(ws))
    expect(result.current.connectPhase).toBeNull()
  })

  it('tracks the latest connect_progress phase', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useConnectProgress(ws))
    act(() => { ws.dispatch({ type: 'connect_progress', phase: 'opening_tunnel' }) })
    expect(result.current.connectPhase).toBe('opening_tunnel')
    act(() => { ws.dispatch({ type: 'connect_progress', phase: 'rsd_attempt', attempt: 1, max: 10 }) })
    expect(result.current.connectPhase).toBe('rsd_attempt')
    act(() => { ws.dispatch({ type: 'connect_progress', phase: 'checking_ddi', udid: 'u1' }) })
    expect(result.current.connectPhase).toBe('checking_ddi')
  })

  it('clears the phase after the connected terminal phase', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useConnectProgress(ws))
    act(() => { ws.dispatch({ type: 'connect_progress', phase: 'opening_dvt', udid: 'u1' }) })
    expect(result.current.connectPhase).toBe('opening_dvt')
    act(() => { ws.dispatch({ type: 'connect_progress', phase: 'connected', udid: 'u1' }) })
    expect(result.current.connectPhase).toBeNull()
  })

  it('is a no-op when ws is undefined', () => {
    const { result } = renderHook(() => useConnectProgress(undefined))
    expect(result.current.connectPhase).toBeNull()
  })

  // ---- timeout backstop tests ----

  it('clears phase after STALE_MS (20 s) if no connected event arrives', () => {
    vi.useFakeTimers()
    const ws = createWsRouter()
    const { result } = renderHook(() => useConnectProgress(ws))

    act(() => { ws.dispatch({ type: 'connect_progress', phase: 'rsd_attempt', attempt: 5, max: 10 }) })
    expect(result.current.connectPhase).toBe('rsd_attempt')

    // Advance just under the threshold — phase must still be set
    act(() => { vi.advanceTimersByTime(19_999) })
    expect(result.current.connectPhase).toBe('rsd_attempt')

    // Advance past the threshold — phase must clear
    act(() => { vi.advanceTimersByTime(1) })
    expect(result.current.connectPhase).toBeNull()
  })

  it('re-arms the timer on each new progress event (no early clear)', () => {
    vi.useFakeTimers()
    const ws = createWsRouter()
    const { result } = renderHook(() => useConnectProgress(ws))

    act(() => { ws.dispatch({ type: 'connect_progress', phase: 'opening_tunnel' }) })
    // Advance 15 s (< 20 s) — phase still set
    act(() => { vi.advanceTimersByTime(15_000) })
    expect(result.current.connectPhase).toBe('opening_tunnel')

    // New progress event re-arms the timer from zero
    act(() => { ws.dispatch({ type: 'connect_progress', phase: 'rsd_attempt', attempt: 1, max: 10 }) })
    // 15 s more — total 30 s from first event, but only 15 s from re-arm; must NOT clear yet
    act(() => { vi.advanceTimersByTime(15_000) })
    expect(result.current.connectPhase).toBe('rsd_attempt')

    // Final 5 s — now past 20 s from the re-arm; must clear
    act(() => { vi.advanceTimersByTime(5_001) })
    expect(result.current.connectPhase).toBeNull()
  })

  it('connected event clears phase immediately without waiting for timeout', () => {
    vi.useFakeTimers()
    const ws = createWsRouter()
    const { result } = renderHook(() => useConnectProgress(ws))

    act(() => { ws.dispatch({ type: 'connect_progress', phase: 'opening_dvt', udid: 'u1' }) })
    expect(result.current.connectPhase).toBe('opening_dvt')

    // connected fires well before the 20 s timeout
    act(() => { vi.advanceTimersByTime(5_000) })
    act(() => { ws.dispatch({ type: 'connect_progress', phase: 'connected', udid: 'u1' }) })
    expect(result.current.connectPhase).toBeNull()

    // Remaining time elapses — phase stays null (timer was cancelled)
    act(() => { vi.advanceTimersByTime(15_001) })
    expect(result.current.connectPhase).toBeNull()
  })

  it('cancels the timer on unmount (no setState-after-unmount warning)', () => {
    vi.useFakeTimers()
    const ws = createWsRouter()
    const { result, unmount } = renderHook(() => useConnectProgress(ws))

    act(() => { ws.dispatch({ type: 'connect_progress', phase: 'rsd_attempt', attempt: 3, max: 10 }) })
    expect(result.current.connectPhase).toBe('rsd_attempt')

    // Unmount before the timeout fires
    unmount()

    // Advancing past timeout must NOT trigger a setState (no act warning)
    act(() => { vi.advanceTimersByTime(25_000) })
    // If timer was NOT cancelled, React would warn about setState after unmount.
    // Passing without warnings is the assertion.
  })
})
