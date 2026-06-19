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
