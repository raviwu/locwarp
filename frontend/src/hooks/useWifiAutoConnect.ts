import { useEffect, useRef } from 'react'
import type { ApiGateway } from '../contract/apiGateway'
import type { DeviceInfo } from './useDevice'

// Once-per-session WiFi auto-connect side-effect, extracted out of App.tsx.
// Mirrors the useRoutes/useRecentPlaces `useX(...)` shape — the backend `api`
// and the `device` surface it calls are INJECTED (App sources them from
// useServices()/useDevice()) so the hook never imports services/api or reaches
// into modules, staying inside the hexagon-lite layering gate.
//
// Behavior is moved verbatim; see the inline comments below (and the App.tsx
// history) for why each guard exists. The `wifiAutoConnectAttemptedRef`
// once-per-session latch and the `connected`-only dependency are part of the
// frozen behavior — do NOT widen the dep array.

// Narrow slice of the useDevice() return that this effect touches. Kept local
// (rather than importing the whole hook return type) so the injection seam
// stays explicit.
export interface WifiAutoConnectDevice {
  connectedDevices: DeviceInfo[]
  startWifiTunnel: (
    ip: string,
    port?: number,
    udidHint?: string,
    bonjourId?: string,
  ) => Promise<DeviceInfo>
}

// Auto-attempt WiFi tunnel on first WS connect if the user previously
// saved at least one IP/port AND has the auto-connect toggle on. Runs
// once per app session — not on every WS reconnect — to avoid re-
// triggering after a backend restart that already restored the tunnel
// via the backend's own watchdog. Failures are silent (the WiFi panel
// will surface them when the user opens it).
//
// Multi-device: tries every IP/port pair in `locwarp.tunnel.savedips`
// in parallel (up to MAX_TUNNEL_DEVICES = 3) so a user with two or
// three iPhones gets all of them connecting at once, not just the
// most recent one. Falls back to the legacy single-IP keys for users
// upgrading from a build that didn't track multiple IPs yet.
//
// Group-mode safety: each per-IP attempt is independent. The whole
// pass is skipped if a device is already connected at trigger time
// (USB plug, or backend already brought a tunnel back up via its own
// restart logic) so we don't fight with an existing USB connection.
export function useWifiAutoConnect(
  connected: boolean,
  api: ApiGateway,
  device: WifiAutoConnectDevice,
) {
  const wifiAutoConnectAttemptedRef = useRef(false)
  // Mirror the latest connectedDevices so the deferred guard below reads the
  // CURRENT connection state, not the snapshot the effect closed over when
  // `connected` flipped true. The effect dep stays [connected] (frozen,
  // once-per-session); without this ref the setTimeout closure reads a stale
  // (usually empty) connectedDevices from before the USB device's
  // device_connected event surfaced — so it fires a spurious WiFi tunnel and
  // the backend tears the healthy USB tunnel down (DVT "No route to host" ->
  // ~27s reconnect before a route moves).
  const connectedDevicesRef = useRef(device.connectedDevices)
  connectedDevicesRef.current = device.connectedDevices
  useEffect(() => {
    if (!connected) return
    if (wifiAutoConnectAttemptedRef.current) return
    let enabled: boolean
    let savedList: Array<{ ip: string; port: number; udid?: string }> = []
    try {
      enabled = localStorage.getItem('locwarp.tunnel.autoconnect') !== '0'
      const raw = localStorage.getItem('locwarp.tunnel.savedips') || '[]'
      try {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed)) {
          savedList = parsed
            .filter((e) => e && typeof e.ip === 'string' && e.ip.trim())
            .map((e) => ({
              ip: String(e.ip).trim(),
              port: Number(e.port) || 49152,
              udid: typeof e.udid === 'string' && e.udid ? e.udid : undefined,
            }))
        }
      } catch { /* ignore — fall back to legacy below */ }
      // Legacy single-IP fallback for upgraders.
      if (savedList.length === 0) {
        const legacyIp = (localStorage.getItem('locwarp.tunnel.ip') || '').trim()
        if (legacyIp) {
          const portStr = localStorage.getItem('locwarp.tunnel.port') || '49152'
          savedList = [{ ip: legacyIp, port: parseInt(portStr, 10) || 49152 }]
        }
      }
    } catch {
      return
    }
    if (!enabled) return
    wifiAutoConnectAttemptedRef.current = true
    // Defer so device.scan() and any backend-side restored tunnels have
    // time to surface in `device.connectedDevices` before we decide
    // whether auto-connect is needed.
    const tid = setTimeout(() => {
      ;(async () => {
        try {
          // Skip if a device is already connected (USB plug, or backend
          // already brought a tunnel back up via its own restart logic). Read
          // the ref, not the closed-over device, so a USB device that surfaced
          // after the effect ran still suppresses the spurious WiFi attempt.
          if (connectedDevicesRef.current.length > 0) return
          const status = await api.wifiTunnelStatus()
          const alreadyTunneled = new Set(
            (status?.tunnels || [])
              .map((tn) => `${tn.rsd_address || ''}:${tn.rsd_port || 0}`),
          )
          // Two sources for auto-connect candidates:
          //   1. savedips: previously-connected iPhones (UDID known)
          //   2. mDNS / subnet discover: iPhones currently broadcasting
          //      their RemotePairing service (UDID unknown until handshake)
          // Discover catches the case where a user connected a second
          // iPhone via the auto-connect path itself (so it never went
          // through the manual save) — without it, only one iPhone keeps
          // auto-connecting on every launch even though both are paired.
          const seen = new Set<string>()
          const uniq: Array<{ ip: string; port: number; udid?: string }> = []
          const addCand = (ip: string, port: number, udid?: string) => {
            const key = `${ip}:${port}`
            if (seen.has(key)) return
            if (alreadyTunneled.has(key)) return
            seen.add(key)
            uniq.push({ ip, port, udid })
          }
          for (const entry of savedList) addCand(entry.ip, entry.port, entry.udid)
          // Discover is best-effort and runs in parallel; failures don't
          // block the savedips path.
          try {
            const dres = await api.wifiTunnelDiscover()
            for (const d of (dres?.devices || [])) {
              addCand(String(d.ip), Number(d.port) || 49152)
            }
          } catch { /* discover failed — savedips entries still try */ }
          // Cap at MAX_DEVICES the backend enforces — anything beyond
          // would 409 anyway.
          const limited = uniq.slice(0, 3)
          if (limited.length === 0) return
          // Parallel: every iPhone gets a tunnel attempt at the same
          // time so the user doesn't wait sequentially for unreachable
          // ones to time out (~10s each). Pass entry.udid so the backend
          // tries the right pair record FIRST — without the hint, the
          // second device's request can stall on the wrong candidate's
          // 8s handshake timeout and bail.
          await Promise.allSettled(
            limited.map((entry) =>
              device.startWifiTunnel(entry.ip, entry.port, entry.udid).catch(() => {}),
            ),
          )
        } catch {
          // Silent — tunnel section will show its own error when opened.
        }
      })()
    }, 1500)
    return () => clearTimeout(tid)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected])
}
