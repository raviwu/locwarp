import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { createWsRouter } from '../adapters/ws/router'
import { useGoldDittoSubscription } from './useGoldDittoSubscription'

describe('useGoldDittoSubscription', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.removeItem('goldditto.wait_seconds')
  })

  afterEach(() => {
    vi.useRealTimers()
    localStorage.removeItem('goldditto.wait_seconds')
  })

  it('teleported phase shows toast and starts 200ms countdown', () => {
    const ws = createWsRouter()
    const showToast = vi.fn()
    const t = vi.fn((key: string, vars?: Record<string, string | number>) => {
      if (vars) return `${key}:${JSON.stringify(vars)}`
      return key
    })
    localStorage.setItem('goldditto.wait_seconds', '1.0')

    renderHook(() => useGoldDittoSubscription(ws, { t: t as any, showToast }))

    act(() => {
      ws.dispatch({ type: 'goldditto_cycle', phase: 'teleported', target: 'A' })
    })

    // Immediately after dispatch: showToast called once with teleported message
    expect(showToast).toHaveBeenCalledTimes(1)
    expect(t).toHaveBeenCalledWith('goldditto.toast.teleported', { target: 'A' })

    // Advance 200ms → first countdown tick fires
    act(() => { vi.advanceTimersByTime(200) })
    expect(showToast).toHaveBeenCalledTimes(2)
    expect(t).toHaveBeenCalledWith('goldditto.toast.waiting', expect.objectContaining({ remaining: expect.any(String) }))

    // Advance past the 1s wait → countdown clears (no more ticks)
    act(() => { vi.advanceTimersByTime(1000) })
    const callCountAfterExpiry = showToast.mock.calls.length
    act(() => { vi.advanceTimersByTime(600) })
    // No additional calls after countdown expires
    expect(showToast.mock.calls.length).toBe(callCountAfterExpiry)
  })

  it('restored phase clears countdown and shows restored toast', () => {
    const ws = createWsRouter()
    const showToast = vi.fn()
    const t = vi.fn((key: string) => key)
    localStorage.setItem('goldditto.wait_seconds', '5.0')

    renderHook(() => useGoldDittoSubscription(ws, { t: t as any, showToast }))

    act(() => {
      ws.dispatch({ type: 'goldditto_cycle', phase: 'teleported', target: 'B' })
    })
    // Advance part-way through countdown
    act(() => { vi.advanceTimersByTime(400) })
    const callsBefore = showToast.mock.calls.length

    act(() => {
      ws.dispatch({ type: 'goldditto_cycle', phase: 'restored' })
    })
    expect(t).toHaveBeenCalledWith('goldditto.toast.restored')

    // After restored, countdown should be cleared — no more ticks
    act(() => { vi.advanceTimersByTime(2000) })
    expect(showToast.mock.calls.length).toBe(callsBefore + 1) // only the restored toast
  })

  it('restore_failed phase clears countdown and shows 8s failure toast', () => {
    const ws = createWsRouter()
    const showToast = vi.fn()
    const t = vi.fn((key: string) => key)

    renderHook(() => useGoldDittoSubscription(ws, { t: t as any, showToast }))

    act(() => {
      ws.dispatch({ type: 'goldditto_cycle', phase: 'restore_failed' })
    })

    expect(showToast).toHaveBeenCalledWith('goldditto.toast.restore_failed', 8000)
  })
})
