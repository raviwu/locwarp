import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import type { ApiGateway } from '../contract/apiGateway'
import { useWifiAutoConnect, type WifiAutoConnectDevice } from './useWifiAutoConnect'

// The effect defers ~1500ms before firing, awaits wifiTunnelStatus +
// wifiTunnelDiscover, then fans out startWifiTunnel calls. We drive it with
// fake timers and advanceTimersByTimeAsync so the deferred async body resolves
// deterministically.

function makeApi() {
  const stub = {
    wifiTunnelStatus: vi.fn(async () => ({ tunnels: [], running: false })),
    wifiTunnelDiscover: vi.fn(async () => ({ devices: [] as any[] })),
  }
  return { api: stub as unknown as ApiGateway, stub }
}

function makeDevice(): { device: WifiAutoConnectDevice; startWifiTunnel: ReturnType<typeof vi.fn> } {
  const startWifiTunnel = vi.fn(async (_ip: string, _port?: number, _udid?: string) => ({
    udid: 'u', name: 'n', ios_version: '17', connection_type: 'Network', is_connected: true,
  }))
  const device: WifiAutoConnectDevice = {
    connectedDevices: [],
    startWifiTunnel: startWifiTunnel as unknown as WifiAutoConnectDevice['startWifiTunnel'],
  }
  return { device, startWifiTunnel }
}

describe('useWifiAutoConnect', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    // Default to enabled so the run-once / dedupe assertions exercise the
    // real candidate path unless a test overrides it.
    localStorage.setItem('locwarp.tunnel.autoconnect', '1')
  })
  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
    localStorage.clear()
  })

  it('fires once when connected becomes true and does NOT re-run on a second toggle', async () => {
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api, stub } = makeApi()
    const { device, startWifiTunnel } = makeDevice()

    const { rerender } = renderHook(({ c }) => useWifiAutoConnect(c, api, device), {
      initialProps: { c: false },
    })
    // Not connected yet: nothing scheduled / fired.
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })
    expect(stub.wifiTunnelStatus).not.toHaveBeenCalled()
    expect(startWifiTunnel).not.toHaveBeenCalled()

    // connected -> true: the deferred pass runs exactly once.
    rerender({ c: true })
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })
    expect(stub.wifiTunnelStatus).toHaveBeenCalledTimes(1)
    expect(startWifiTunnel).toHaveBeenCalledTimes(1)

    // A second connected toggle (false -> true again) MUST NOT re-run: the
    // once-per-session ref latch is set. Counts stay the same.
    rerender({ c: false })
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })
    rerender({ c: true })
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })
    expect(stub.wifiTunnelStatus).toHaveBeenCalledTimes(1)
    expect(startWifiTunnel).toHaveBeenCalledTimes(1)
  })

  it('parses savedips, dedupes, and caps at 3 parallel connect attempts', async () => {
    // 5 entries, one a duplicate of another (same ip:port) -> 4 unique, then
    // capped at 3. Proves parse + dedupe + cap-at-3.
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([
        { ip: '10.0.0.1', port: 49152, udid: 'a' },
        { ip: '10.0.0.2', port: 49152, udid: 'b' },
        { ip: '10.0.0.1', port: 49152, udid: 'a' }, // duplicate of #1
        { ip: '10.0.0.3', port: 49152, udid: 'c' },
        { ip: '10.0.0.4', port: 49152, udid: 'd' },
      ]),
    )
    const { api } = makeApi()
    const { device, startWifiTunnel } = makeDevice()

    renderHook(() => useWifiAutoConnect(true, api, device))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    // 4 unique candidates, capped to 3 -> exactly 3 attempts.
    expect(startWifiTunnel).toHaveBeenCalledTimes(3)
    const ipsTried = startWifiTunnel.mock.calls.map((c) => c[0])
    // Dedupe: 10.0.0.1 appears once, not twice.
    expect(ipsTried.filter((ip) => ip === '10.0.0.1')).toHaveLength(1)
    // First 3 unique (in candidate order) are tried; the 4th (10.0.0.4) is
    // dropped by the cap.
    expect(new Set(ipsTried)).toEqual(new Set(['10.0.0.1', '10.0.0.2', '10.0.0.3']))
    // udid hint is threaded through as the 3rd arg.
    const call1 = startWifiTunnel.mock.calls.find((c) => c[0] === '10.0.0.1')!
    expect(call1[2]).toBe('a')
  })

  it('skips the whole pass when autoconnect is disabled', async () => {
    localStorage.setItem('locwarp.tunnel.autoconnect', '0')
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api, stub } = makeApi()
    const { device, startWifiTunnel } = makeDevice()

    renderHook(() => useWifiAutoConnect(true, api, device))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })
    expect(stub.wifiTunnelStatus).not.toHaveBeenCalled()
    expect(startWifiTunnel).not.toHaveBeenCalled()
  })

  it('skips when a device is already connected at trigger time', async () => {
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api } = makeApi()
    const { device, startWifiTunnel } = makeDevice()
    device.connectedDevices = [{
      udid: 'x', name: 'n', ios_version: '17', connection_type: 'USB', is_connected: true,
    }]

    renderHook(() => useWifiAutoConnect(true, api, device))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })
    // status is queried but no tunnel attempt is made (USB already up).
    expect(startWifiTunnel).not.toHaveBeenCalled()
  })
})
