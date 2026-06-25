import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { createWsRouter } from '../adapters/ws/router'
import { useConnectProgress } from './useConnectProgress'

describe('useConnectProgress', () => {
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
})
