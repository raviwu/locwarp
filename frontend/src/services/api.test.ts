import { describe, it, expect } from 'vitest'
import * as api from './api'

describe('api surface', () => {
  it('does not export wifiConnect (removed /api/device/wifi/connect, 404 since v0.1.49)', () => {
    expect('wifiConnect' in api).toBe(false)
  })

  it('keeps the supported WiFi entrypoint wifiTunnelStartAndConnect', () => {
    expect(typeof api.wifiTunnelStartAndConnect).toBe('function')
  })
})
