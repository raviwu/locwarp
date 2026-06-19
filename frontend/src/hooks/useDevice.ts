import { useState, useCallback, useEffect } from 'react'
import {
  listDevices, connectDevice, disconnectDevice,
  wifiConnect, wifiScan,
  wifiTunnelStartAndConnect, wifiTunnelStatus, wifiTunnelStop,
  type TunnelInfo,
} from '../services/api'
import type { WsRouter } from '../ports/WsRouter'
import type { WsEvent } from '../contract/wsEvents'

export interface DeviceInfo {
  udid: string
  name: string
  ios_version: string
  connection_type: string
  is_connected: boolean
  // iOS 16+ Developer Mode toggle state. null = unknown (iOS <16, query
  // failed, or device not yet connected). Used to decide whether to show
  // the "Reveal Developer Mode option" button.
  developer_mode_enabled?: boolean | null
  // Pair-handshake state from the backend. "ok" = device is healthy;
  // "trust_required" = iPhone forgot this host, needs re-trust;
  // "error" = some other lockdown failure (text in pair_error).
  // Older backends omit this field; treat undefined as "ok".
  pair_status?: 'ok' | 'trust_required' | 'error'
  pair_error?: string | null
}

export interface WifiScanResult {
  ip: string
  name: string
  udid: string
  ios_version: string
}

export function useDevice(ws?: WsRouter) {
  const [devices, setDevices] = useState<DeviceInfo[]>([])
  const [connectedDevice, setConnectedDevice] = useState<DeviceInfo | null>(null)

  // React to real-time device state broadcasts via the typed WsRouter.
  // See useWebSocket.ts for the rationale vs the old useState pattern.
  useEffect(() => {
    if (!ws) return
    const offDisc = ws.subscribe('device_disconnected', (e: WsEvent) => {
      // Group mode: only mark the specific udid disconnected when provided;
      // fall back to clearing all for legacy single-device disconnect events.
      const udid = e.udid as string | undefined
      const udids: string[] = Array.isArray(e.udids) ? (e.udids as string[]) : (udid ? [udid] : [])
      if (udids.length === 0) {
        setConnectedDevice(null)
        setDevices((prev) => prev.map((d) => ({ ...d, is_connected: false })))
      } else {
        setDevices((prev) => prev.map((d) => udids.includes(d.udid) ? { ...d, is_connected: false } : d))
        // DON'T null out connectedDevice here. The authoritative refresh
        // below (listDevices) will pick a surviving device to promote
        // so downstream UI (MapView / StatusBar) doesn't flash
        // 'No device' in dual-device mode when only one was unplugged.
      }
      // Re-fetch so the sidebar list and metadata stay in sync with the
      // backend, AND promote a surviving connected device as the new
      // active one when the old primary was the one unplugged. This
      // fixes the bug where unplugging A (primary) in dual-device mode
      // made the UI think no device was connected even though B was
      // still alive.
      listDevices().then((list) => {
        setDevices(list)
        setConnectedDevice((prev) => {
          // Keep the current one if it's still connected.
          if (prev && list.some((d) => d.udid === prev.udid && d.is_connected)) return prev
          // Otherwise promote the first surviving connected device.
          return list.find((d) => d.is_connected) ?? null
        })
      }).catch(() => {})
    })
    const offConn = ws.subscribe('device_connected', (e: WsEvent) => {
      // Re-fetch list so the newly-connected device appears with correct metadata.
      listDevices().then((list) => {
        setDevices(list)
        // If nothing is currently set as the active device, promote the
        // newly-connected one so the bottom panel switches off NODEVICE
        // without the user having to press the USB button.
        const udid = e.udid as string | undefined
        const match = udid ? list.find((d) => d.udid === udid && d.is_connected) : null
        setConnectedDevice((prev) => prev ?? match ?? list.find((d) => d.is_connected) ?? null)
      }).catch(() => {})
    })
    const offReconn = ws.subscribe('device_reconnected', (e: WsEvent) => {
      listDevices().then((list) => {
        setDevices(list)
        const udid = e.udid as string | undefined
        const match = udid ? list.find((d) => d.udid === udid) : null
        setConnectedDevice(match ?? list.find((d) => d.is_connected) ?? null)
      }).catch(() => {})
    })
    return () => { offDisc(); offConn(); offReconn() }
  }, [ws])
  const [scanning, setScanning] = useState(false)
  const [wifiScanning, setWifiScanning] = useState(false)
  const [wifiDevices, setWifiDevices] = useState<WifiScanResult[]>([])

  const scan = useCallback(async () => {
    setScanning(true)
    try {
      const result = await listDevices()
      const list: DeviceInfo[] = Array.isArray(result) ? result : []
      setDevices(list)
      const active = list.find((d) => d.is_connected) ?? null
      if (active) {
        setConnectedDevice(active)
      } else if (list.length === 1) {
        // Auto-connect when exactly one device is found
        try {
          await connectDevice(list[0].udid)
          const refreshed = await listDevices()
          const rList: DeviceInfo[] = Array.isArray(refreshed) ? refreshed : []
          setDevices(rList)
          setConnectedDevice(rList.find((d) => d.udid === list[0].udid) ?? list[0])
        } catch {
          setConnectedDevice(null)
        }
      } else {
        setConnectedDevice(null)
      }
      return list
    } catch (err) {
      console.error('Failed to scan devices:', err)
      return []
    } finally {
      setScanning(false)
    }
  }, [])

  const connect = useCallback(
    async (udid: string) => {
      try {
        await connectDevice(udid)
        const refreshed = await listDevices()
        const list: DeviceInfo[] = Array.isArray(refreshed) ? refreshed : []
        setDevices(list)
        const active = list.find((d) => d.udid === udid) ?? null
        setConnectedDevice(active)
        return active
      } catch (err) {
        console.error('Failed to connect device:', err)
        throw err
      }
    },
    [],
  )

  const disconnect = useCallback(
    async (udid: string) => {
      try {
        await disconnectDevice(udid)
        const refreshed = await listDevices()
        const list: DeviceInfo[] = Array.isArray(refreshed) ? refreshed : []
        setDevices(list)
        setConnectedDevice(null)
      } catch (err) {
        console.error('Failed to disconnect device:', err)
        throw err
      }
    },
    [],
  )

  const connectWifi = useCallback(
    async (ip: string) => {
      try {
        const res = await wifiConnect(ip)
        const info: DeviceInfo = {
          udid: res.udid,
          name: res.name,
          ios_version: res.ios_version,
          connection_type: 'Network',
          is_connected: true,
        }
        setConnectedDevice(info)
        setDevices((prev) => {
          const filtered = prev.filter((d) => d.udid !== info.udid)
          return [...filtered, info]
        })
        return info
      } catch (err) {
        console.error('WiFi connect failed:', err)
        throw err
      }
    },
    [],
  )

  const scanWifi = useCallback(async () => {
    setWifiScanning(true)
    try {
      const results = await wifiScan()
      const list: WifiScanResult[] = Array.isArray(results) ? results : []
      setWifiDevices(list)
      return list
    } catch (err) {
      console.error('WiFi scan failed:', err)
      return []
    } finally {
      setWifiScanning(false)
    }
  }, [])

  // v0.2.83: WiFi tunnel state went from a singleton to a per-device list.
  // Each connected iOS 17+ WiFi device gets its own runner on the backend;
  // `tunnels` mirrors that list. `tunnelStatus` is kept as a derived
  // singleton (mirrors first tunnel) for any leftover single-tunnel callers
  // until they migrate.
  const [tunnels, setTunnels] = useState<TunnelInfo[]>([])
  const tunnelStatus = tunnels.length > 0
    ? { running: true, rsd_address: tunnels[0].rsd_address, rsd_port: tunnels[0].rsd_port }
    : { running: false }

  const startWifiTunnel = useCallback(
    async (ip: string, port = 49152, udidHint?: string, bonjourId?: string) => {
      try {
        const res = await wifiTunnelStartAndConnect(ip, port, udidHint, bonjourId)
        const info: DeviceInfo = {
          udid: res.udid,
          name: res.name,
          ios_version: res.ios_version,
          connection_type: 'Network',
          is_connected: true,
        }
        setConnectedDevice(info)
        setDevices((prev) => {
          const filtered = prev.filter((d) => d.udid !== info.udid)
          return [...filtered, info]
        })
        setTunnels((prev) => {
          const filtered = prev.filter((tn) => tn.udid !== res.udid)
          return [...filtered, {
            udid: res.udid,
            rsd_address: res.rsd_address,
            rsd_port: res.rsd_port,
          }]
        })
        // Persist every successful tunnel into savedips, regardless of
        // who initiated it (manual button, launch auto-connect, mDNS
        // discover-and-connect). Without this, an iPhone that was
        // connected via auto-discovery never gets remembered, and the
        // next launch only auto-connects whichever iPhone the user once
        // manually clicked through. v0.2.110 bug surfaced when a user
        // with two iPhones only had one of them in savedips.
        try {
          const raw = localStorage.getItem('locwarp.tunnel.savedips') || '[]'
          const list = (() => {
            try { return JSON.parse(raw) as Array<{ ip: string; port: number; udid?: string; lastUsed: number }> }
            catch { return [] }
          })()
          const baseList = Array.isArray(list) ? list : []
          // Dedup by both (ip, port) AND by udid — covers the case where
          // an iPhone reconnects on a NEW DHCP-assigned IP. Without the
          // udid dedup we'd accumulate stale IPs for the same device.
          const filtered = baseList.filter((e) =>
            e && !(e.ip === ip && e.port === port) && !(res.udid && e.udid === res.udid)
          )
          const next = [{ ip, port, udid: res.udid, lastUsed: Date.now() }, ...filtered].slice(0, 5)
          localStorage.setItem('locwarp.tunnel.savedips', JSON.stringify(next))
        } catch { /* storage disabled */ }
        return info
      } catch (err) {
        console.error('WiFi tunnel failed:', err)
        throw err
      }
    },
    [],
  )

  const checkTunnelStatus = useCallback(async () => {
    try {
      const res = await wifiTunnelStatus()
      setTunnels(Array.isArray(res?.tunnels) ? res.tunnels : [])
      return res
    } catch {
      setTunnels([])
      return { tunnels: [], running: false }
    }
  }, [])

  // udid: stop one specific tunnel; omit to stop all.
  const stopTunnel = useCallback(async (udid?: string) => {
    try {
      await wifiTunnelStop(udid)
      if (udid) {
        setTunnels((prev) => prev.filter((tn) => tn.udid !== udid))
      } else {
        setTunnels([])
      }
    } catch (err) {
      console.error('Failed to stop tunnel:', err)
    }
  }, [])

  // Group-mode derived state: every device in `devices` marked is_connected.
  // `primaryDevice` sticks to whichever device we picked first; we only
  // promote a new one when the current sticky primary is no longer in the
  // connected slice. Without stickiness, listDevices()'s order on a
  // mid-session reconnect can swap primary back to the just-rejoined
  // device, which then receives the auto-sync replay (a fresh sim from
  // its current position) and the frontend lets that REPLAY's events
  // through the udid filter, overwriting the surviving device's polyline
  // and "瞬移回起點 / 慢慢走回起點" on screen. Sticky primary keeps the
  // surviving device in charge so the rejoining one's replay stays
  // filtered out and invisible until the user explicitly chooses to
  // switch.
  const connectedDevices: DeviceInfo[] = devices.filter((d) => d.is_connected)
  const [stickyPrimaryUdid, setStickyPrimaryUdid] = useState<string | null>(null)
  useEffect(() => {
    if (connectedDevices.length === 0) {
      if (stickyPrimaryUdid !== null) setStickyPrimaryUdid(null)
      return
    }
    if (stickyPrimaryUdid && connectedDevices.some((d) => d.udid === stickyPrimaryUdid)) {
      return
    }
    setStickyPrimaryUdid(connectedDevices[0].udid)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [devices])
  const primaryDevice: DeviceInfo | null =
    devices.find((d) => d.udid === stickyPrimaryUdid && d.is_connected) ?? null

  return {
    devices, connectedDevice, scanning, scan, connect, disconnect,
    connectWifi, scanWifi, wifiScanning, wifiDevices,
    startWifiTunnel, checkTunnelStatus, stopTunnel, tunnelStatus, tunnels,
    connectedDevices, primaryDevice,
  }
}
