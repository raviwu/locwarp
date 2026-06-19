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

describe('useSimulation device_disconnected banner on WsRouter', () => {
  it('remaining_count === 0 sets the disconnect banner + halts running', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))

    act(() => {
      ws.dispatch({ type: 'device_disconnected', remaining_count: 0 })
    })

    expect(result.current.error).toContain('USB')
    expect(result.current.status.running).toBe(false)
  })

  it('remaining_count > 0 clears the error (a survivor remains)', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))

    act(() => {
      ws.dispatch({ type: 'device_disconnected', remaining_count: 2 })
    })

    expect(result.current.error).toBeNull()
  })
})

describe('useSimulation position_update — group mode + dual-device filter', () => {
  it('non-primary udid updates runtimes map but does NOT call primary-only setters', () => {
    const primaryUdid = 'device-primary'
    const secondaryUdid = 'device-secondary'
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, primaryUdid))

    act(() => {
      ws.dispatch({
        type: 'position_update',
        udid: secondaryUdid,
        lat: 25.1,
        lng: 121.5,
        progress: 0.42,
        eta_seconds: 30,
        distance_remaining: 500,
        distance_traveled: 200,
        speed_mps: 1.5,
      })
    })

    // Group-mode runtimes entry is created for the secondary device
    expect(result.current.runtimes[secondaryUdid]).toBeDefined()
    expect(result.current.runtimes[secondaryUdid].currentPos).toEqual({ lat: 25.1, lng: 121.5 })
    expect(result.current.runtimes[secondaryUdid].progress).toBe(0.42)
    expect(result.current.runtimes[secondaryUdid].eta).toBe(30)
    expect(result.current.runtimes[secondaryUdid].distanceRemaining).toBe(500)
    expect(result.current.runtimes[secondaryUdid].distanceTraveled).toBe(200)
    expect(result.current.runtimes[secondaryUdid].currentSpeedKmh).toBeCloseTo(1.5 * 3.6)

    // Primary-only state is NOT updated (dual-device filter early-returned)
    expect(result.current.currentPosition).toBeNull()
    expect(result.current.progress).toBe(0)
    expect(result.current.eta).toBeNull()
  })

  it('primary udid updates runtimes AND primary-only setters', () => {
    const primaryUdid = 'device-primary'
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, primaryUdid))

    act(() => {
      ws.dispatch({
        type: 'position_update',
        udid: primaryUdid,
        lat: 35.7,
        lng: 139.7,
        progress: 0.75,
        eta_seconds: 10,
        distance_remaining: 100,
        distance_traveled: 900,
      })
    })

    // Group-mode runtimes updated for primary
    expect(result.current.runtimes[primaryUdid]).toBeDefined()
    expect(result.current.runtimes[primaryUdid].currentPos).toEqual({ lat: 35.7, lng: 139.7 })
    expect(result.current.runtimes[primaryUdid].progress).toBe(0.75)

    // Primary-only setters also run (filter passes through for primary udid)
    expect(result.current.currentPosition).toEqual({ lat: 35.7, lng: 139.7 })
    expect(result.current.progress).toBe(0.75)
    expect(result.current.eta).toBe(10)
    expect(result.current.status.distance_remaining).toBe(100)
    expect(result.current.status.distance_traveled).toBe(900)
  })

  it('null backend fields are coalesced to undefined in runtimes (parity fix)', () => {
    const ws = createWsRouter()
    const { result } = renderHook(() => useSimulation(ws, null))

    act(() => {
      ws.dispatch({
        type: 'position_update',
        udid: 'dev-a',
        lat: 1,
        lng: 1,
        // Explicitly send null for all four parity fields
        progress: null as any,
        eta_seconds: null as any,
        distance_remaining: null as any,
        distance_traveled: null as any,
      })
    })

    const rt = result.current.runtimes['dev-a']
    expect(rt).toBeDefined()
    // Should be undefined (coalesced via ?? undefined), not null
    expect(rt.progress).toBeUndefined()
    expect(rt.eta).toBeUndefined()
    expect(rt.distanceRemaining).toBeUndefined()
    expect(rt.distanceTraveled).toBeUndefined()
  })
})
