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

  it('skips when a USB device surfaces AFTER the effect runs but before the deferred pass fires', async () => {
    // Repro of the route slow-load tunnel thrash: the USB device connects on
    // the backend before the WS connects, but its device_connected event only
    // populates connectedDevices a beat AFTER `connected` flipped true — i.e.
    // after the effect captured its snapshot, but before the ~1500ms deferred
    // pass fires. useDevice returns a NEW device object on that render (fresh
    // connectedDevices array), so the guard must read CURRENT state, not the
    // snapshot the effect closed over. Otherwise it fires a spurious WiFi
    // tunnel that tears the healthy USB tunnel down -> DVT "No route to host"
    // -> a ~27s reconnect before the route moves.
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api } = makeApi()
    const startWifiTunnel = vi.fn(async () => ({
      udid: 'u', name: 'n', ios_version: '17', connection_type: 'Network', is_connected: true,
    })) as unknown as WifiAutoConnectDevice['startWifiTunnel']
    const deviceEmpty: WifiAutoConnectDevice = { connectedDevices: [], startWifiTunnel }
    const usb = { udid: 'x', name: 'n', ios_version: '17', connection_type: 'USB', is_connected: true }
    const deviceConnected: WifiAutoConnectDevice = { connectedDevices: [usb], startWifiTunnel }

    const { rerender } = renderHook(({ d }) => useWifiAutoConnect(true, api, d), {
      initialProps: { d: deviceEmpty },
    })
    // device_connected event surfaces the USB device on a later render (new object).
    rerender({ d: deviceConnected })
    // Now the deferred pass fires.
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    expect(startWifiTunnel).not.toHaveBeenCalled()
  })

  it('calls onError when every auto-connect attempt fails', async () => {
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api } = makeApi()
    const { device, startWifiTunnel } = makeDevice()
    // Force the only attempt to reject.
    startWifiTunnel.mockRejectedValue(new Error('tunnel down'))
    const onError = vi.fn()

    renderHook(() => useWifiAutoConnect(true, api, device, onError))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    expect(startWifiTunnel).toHaveBeenCalledTimes(1)
    expect(onError).toHaveBeenCalledTimes(1)
  })

  it('does NOT call onError when at least one attempt succeeds', async () => {
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api } = makeApi()
    const { device } = makeDevice() // default startWifiTunnel resolves
    const onError = vi.fn()

    renderHook(() => useWifiAutoConnect(true, api, device, onError))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    expect(onError).not.toHaveBeenCalled()
  })

  // FIX 5: pre-flight wifiTunnelStatus throws — outer catch must NOT fire onError
  // (spurious toast during backend warmup when USB is healthy but not yet surfaced).
  it('does NOT call onError when the pre-flight wifiTunnelStatus throws (transient backend error)', async () => {
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api, stub } = makeApi()
    // Make the pre-flight status call reject.
    stub.wifiTunnelStatus.mockRejectedValue(new Error('backend not ready'))
    const onError = vi.fn()
    const { device } = makeDevice()

    renderHook(() => useWifiAutoConnect(true, api, device, onError))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    // Pre-flight threw — outer catch path; onError must remain silent (no spurious toast).
    expect(onError).not.toHaveBeenCalled()
  })

  // FIX 5 (confirmation): inner all-failed path still fires onError — the legitimate goal.
  // This is already covered by the "calls onError when every auto-connect attempt fails" test
  // above (which uses the default resolving wifiTunnelStatus + rejecting startWifiTunnel),
  // but we add an explicit companion assertion here for clarity.
  it('calls onError when wifiTunnelStatus succeeds but every startWifiTunnel attempt fails', async () => {
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.2', port: 49152, udid: 'b' }]),
    )
    const { api } = makeApi()
    const { device, startWifiTunnel } = makeDevice()
    startWifiTunnel.mockRejectedValue(new Error('unreachable'))
    const onError = vi.fn()

    renderHook(() => useWifiAutoConnect(true, api, device, onError))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    expect(onError).toHaveBeenCalledWith('wifi.autoconnect_failed')
  })

  // Win 3 — ordering tests: savedips fires immediately (doesn't wait for discover).
  it('fires the savedips candidate immediately even when discover never resolves', async () => {
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api, stub } = makeApi()
    // Discover hangs forever — the savedips fire must NOT wait on it.
    stub.wifiTunnelDiscover.mockImplementation(() => new Promise(() => {}))
    const { device, startWifiTunnel } = makeDevice()

    renderHook(() => useWifiAutoConnect(true, api, device))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    // savedips candidate fired despite discover being pending.
    expect(startWifiTunnel).toHaveBeenCalledTimes(1)
    expect(startWifiTunnel.mock.calls[0][0]).toBe('10.0.0.1')
    expect(startWifiTunnel.mock.calls[0][2]).toBe('a')
  })

  it('adds a discover-only device that is not in savedips (concurrent discover)', async () => {
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api, stub } = makeApi()
    // Discover surfaces a second, un-saved iPhone.
    stub.wifiTunnelDiscover.mockResolvedValue({ devices: [{ ip: '10.0.0.9', port: 49152 }] })
    const { device, startWifiTunnel } = makeDevice()

    renderHook(() => useWifiAutoConnect(true, api, device))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    const ipsTried = startWifiTunnel.mock.calls.map((c) => c[0])
    expect(new Set(ipsTried)).toEqual(new Set(['10.0.0.1', '10.0.0.9']))
  })

  // Regression: discover-added connect leak — before the fix, the discover-only
  // device's startWifiTunnel promise was pushed into `attempts` AFTER
  // Promise.allSettled had already snapshotted the array, so its outcome was
  // invisible to the all-failed toast accounting. With the fix (await discover
  // before allSettled), the discover connect IS in the settled batch.
  // Scenario: savedips device fails, discover-only device succeeds → NO toast.
  it('does NOT call onError when a discover-only connect succeeds even if every savedip fails (leak closed)', async () => {
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api, stub } = makeApi()
    stub.wifiTunnelDiscover.mockResolvedValue({ devices: [{ ip: '10.0.0.9', port: 49152 }] })
    const startWifiTunnel = vi.fn(async (ip: string) => {
      // savedip fails, discover-only device succeeds
      if (ip === '10.0.0.1') throw new Error('unreachable')
      return { udid: 'u2', name: 'n2', ios_version: '17', connection_type: 'Network', is_connected: true }
    }) as unknown as WifiAutoConnectDevice['startWifiTunnel']
    const device: WifiAutoConnectDevice = { connectedDevices: [], startWifiTunnel }
    const onError = vi.fn()

    renderHook(() => useWifiAutoConnect(true, api, device, onError))
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    // Both devices were attempted.
    const ipsTried = (startWifiTunnel as ReturnType<typeof vi.fn>).mock.calls.map((c: any) => c[0])
    expect(new Set(ipsTried)).toEqual(new Set(['10.0.0.1', '10.0.0.9']))
    // The discover connect succeeded — no spurious all-failed toast.
    expect(onError).not.toHaveBeenCalled()
  })

  it('no-thrash guard: an already-connected device suppresses the savedips fire even after the reorder', async () => {
    localStorage.setItem(
      'locwarp.tunnel.savedips',
      JSON.stringify([{ ip: '10.0.0.1', port: 49152, udid: 'a' }]),
    )
    const { api } = makeApi()
    const startWifiTunnel = vi.fn(async () => ({
      udid: 'u', name: 'n', ios_version: '17', connection_type: 'Network', is_connected: true,
    })) as unknown as WifiAutoConnectDevice['startWifiTunnel']
    const deviceEmpty: WifiAutoConnectDevice = { connectedDevices: [], startWifiTunnel }
    const usb = { udid: 'x', name: 'n', ios_version: '17', connection_type: 'USB', is_connected: true }
    const deviceConnected: WifiAutoConnectDevice = { connectedDevices: [usb], startWifiTunnel }

    const { rerender } = renderHook(({ d }) => useWifiAutoConnect(true, api, d), {
      initialProps: { d: deviceEmpty },
    })
    // USB device surfaces on a later render (new object) — guard reads the ref.
    rerender({ d: deviceConnected })
    await act(async () => { await vi.advanceTimersByTimeAsync(1600) })

    // Even with savedips firing "immediately", the already-connected guard
    // (read from connectedDevicesRef) runs FIRST and suppresses any fire.
    expect(startWifiTunnel).not.toHaveBeenCalled()
  })
})
