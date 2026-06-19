import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { createWsRouter } from '../adapters/ws/router'
import { useDevice } from './useDevice'
import * as api from '../services/api'

vi.mock('../services/api')

const DEV = (udid: string, connected: boolean) => ({
  udid, name: udid, ios_version: '17.0', connection_type: 'USB',
  is_connected: connected,
})

beforeEach(() => {
  vi.resetAllMocks()
})

describe('useDevice on WsRouter', () => {
  it('device_disconnected with udids=[A] marks A only and promotes a survivor', async () => {
    vi.mocked(api.listDevices).mockResolvedValue([DEV('A', false), DEV('B', true)])
    const ws = createWsRouter()
    const { result } = renderHook(() => useDevice(ws))

    act(() => {
      ws.dispatch({ type: 'device_disconnected', udid: 'A', udids: ['A'], remaining_count: 1 })
    })

    await waitFor(() => {
      expect(result.current.connectedDevice?.udid).toBe('B')
    })
    expect(api.listDevices).toHaveBeenCalled()
  })

  it('device_disconnected with no udid/udids clears all devices', async () => {
    vi.mocked(api.listDevices).mockResolvedValue([])
    const ws = createWsRouter()
    const { result } = renderHook(() => useDevice(ws))

    act(() => {
      ws.dispatch({ type: 'device_disconnected' })
    })

    await waitFor(() => {
      expect(result.current.connectedDevice).toBeNull()
    })
  })
})
