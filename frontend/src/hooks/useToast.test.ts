import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useToast } from './useToast'

describe('useToast', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('starts with no toast', () => {
    const { result } = renderHook(() => useToast())
    expect(result.current.toastMsg).toBeNull()
  })

  it('shows a message and auto-clears it after the default 3000ms', () => {
    const { result } = renderHook(() => useToast())

    act(() => { result.current.showToast('hello') })
    expect(result.current.toastMsg).toBe('hello')

    // Not yet cleared just before the deadline.
    act(() => { vi.advanceTimersByTime(2999) })
    expect(result.current.toastMsg).toBe('hello')

    act(() => { vi.advanceTimersByTime(1) })
    expect(result.current.toastMsg).toBeNull()
  })

  it('honours a custom duration', () => {
    const { result } = renderHook(() => useToast())

    act(() => { result.current.showToast('slow', 6000) })
    act(() => { vi.advanceTimersByTime(3000) })
    expect(result.current.toastMsg).toBe('slow')

    act(() => { vi.advanceTimersByTime(3000) })
    expect(result.current.toastMsg).toBeNull()
  })

  // The load-bearing single-shared-timer semantic: a newer toast cancels the
  // prior auto-clear timer, so the later toast gets its FULL duration and the
  // earlier toast's timer never blanks it out mid-display.
  it('cancels the prior auto-clear timer so the newest toast gets its full duration', () => {
    const { result } = renderHook(() => useToast())

    // First toast: short 2s window.
    act(() => { result.current.showToast('first', 2000) })
    // Advance partway — the first timer is now 1.5s into its 2s life.
    act(() => { vi.advanceTimersByTime(1500) })
    expect(result.current.toastMsg).toBe('first')

    // Second toast: longer 6s window. This must clear the first timer.
    act(() => { result.current.showToast('second', 6000) })
    expect(result.current.toastMsg).toBe('second')

    // Cross the moment the FIRST timer would have fired (2000ms total).
    // If the prior timer had NOT been cancelled, the toast would blank here.
    act(() => { vi.advanceTimersByTime(600) }) // 1500 + 600 = 2100ms elapsed
    expect(result.current.toastMsg).toBe('second')

    // The second toast survives until its own full 6s elapses.
    act(() => { vi.advanceTimersByTime(5399) }) // second timer at 5999ms
    expect(result.current.toastMsg).toBe('second')
    act(() => { vi.advanceTimersByTime(1) }) // second timer hits 6000ms
    expect(result.current.toastMsg).toBeNull()
  })

  it('keeps showToast referentially stable across renders', () => {
    const { result, rerender } = renderHook(() => useToast())
    const first = result.current.showToast
    rerender()
    expect(result.current.showToast).toBe(first)
  })
})
