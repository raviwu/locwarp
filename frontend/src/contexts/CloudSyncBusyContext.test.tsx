import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import {
  CloudSyncBusyProvider,
  useCloudSyncBusy,
  CLOUD_SYNC_TIMEOUT_MS,
  CLOUD_SYNC_SLOW_HINT_MS,
} from './CloudSyncBusyContext'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <CloudSyncBusyProvider>{children}</CloudSyncBusyProvider>
)

describe('CloudSyncBusyContext run() timeout', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('exposes a 35s timeout constant', () => {
    expect(CLOUD_SYNC_TIMEOUT_MS).toBe(35000)
  })

  it('sets busy true while the toggle is in flight', () => {
    const { result } = renderHook(() => useCloudSyncBusy(), { wrapper })
    expect(result.current.busy).toBe(false)
    act(() => { void result.current.run(() => new Promise(() => {})) })
    expect(result.current.busy).toBe(true)
  })

  it('aborts the in-flight fn and clears busy + rejects when the toggle stalls past the timeout', async () => {
    const { result } = renderHook(() => useCloudSyncBusy(), { wrapper })

    let observedSignal: AbortSignal | undefined
    let rejected: unknown
    // fn never resolves on its own; it only settles when its signal aborts.
    const fn = (signal: AbortSignal) =>
      new Promise<never>((_, reject) => {
        observedSignal = signal
        signal.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError')),
        )
      })

    act(() => {
      result.current.run(fn).catch((e) => { rejected = e })
    })
    expect(result.current.busy).toBe(true)
    expect(observedSignal?.aborted).toBe(false)

    // Cross the timeout deadline; advanceTimersByTimeAsync drains the abort
    // event + the rejection + run()'s finally (setBusy(false)) as microtasks.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CLOUD_SYNC_TIMEOUT_MS)
    })

    expect(observedSignal?.aborted).toBe(true)
    expect(result.current.busy).toBe(false)
    expect((rejected as Error)?.name).toBe('AbortError')
  })

  it('does NOT abort and clears busy normally when the toggle resolves before the timeout', async () => {
    const { result } = renderHook(() => useCloudSyncBusy(), { wrapper })

    let observedSignal: AbortSignal | undefined
    const fn = (signal: AbortSignal) => {
      observedSignal = signal
      return Promise.resolve('ok')
    }

    let resolved: unknown
    await act(async () => {
      resolved = await result.current.run(fn)
    })

    expect(resolved).toBe('ok')
    expect(observedSignal?.aborted).toBe(false)
    expect(result.current.busy).toBe(false)
  })

  it('flips tookTooLong after the slow-hint threshold and cancel() aborts + clears busy', async () => {
    const { result } = renderHook(() => useCloudSyncBusy(), { wrapper })

    let observedSignal: AbortSignal | undefined
    let rejected: unknown
    const fn = (signal: AbortSignal) =>
      new Promise<never>((_, reject) => {
        observedSignal = signal
        signal.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError')),
        )
      })

    act(() => { result.current.run(fn).catch((e) => { rejected = e }) })
    expect(result.current.tookTooLong).toBe(false)

    // Cross the 10s slow-hint threshold (but not the 35s hard timeout).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CLOUD_SYNC_SLOW_HINT_MS)
    })
    expect(result.current.tookTooLong).toBe(true)
    expect(observedSignal?.aborted).toBe(false)

    // User hits Cancel; advanceTimersByTimeAsync(0) drains the abort event +
    // the rejection + run()'s finally as microtasks.
    await act(async () => {
      result.current.cancel()
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(observedSignal?.aborted).toBe(true)
    expect(result.current.busy).toBe(false)
    expect(result.current.tookTooLong).toBe(false)
    expect((rejected as Error)?.name).toBe('AbortError')
  })
})
