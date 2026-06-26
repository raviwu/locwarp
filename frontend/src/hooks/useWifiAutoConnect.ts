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
// via the backend's own watchdog. On a full failure (every candidate
// rejected) the injected onError callback fires a toast — the WiFi panel
// does NOT surface auto-pass failures on its own (its tunnelError is only
// set by the manual connect / discover paths).
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
  onError?: (msg: string) => void,
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
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError
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
          const fired = new Set<string>()
          const attempts: Array<Promise<unknown>> = []
          const fire = (ip: string, port: number, udid?: string) => {
            const key = `${ip}:${port}`
            if (seen.has(key)) return
            if (alreadyTunneled.has(key)) return
            // Cap at the MAX_DEVICES the backend enforces — anything beyond
            // would 409 anyway. Count only what we've actually fired.
            if (fired.size >= 3) return
            seen.add(key)
            fired.add(key)
            attempts.push(device.startWifiTunnel(ip, port, udid))
          }
          // (Win 3) Fire the savedips candidates IMMEDIATELY — they already
          // hold exact {ip, port, udid} for known phones, so there's no reason
          // to wait the full ~3s mDNS browse before connecting them. A
          // single-phone user's auto-connect now starts ~3s earlier per launch.
          // The already-connected guard above (connectedDevicesRef) has already
          // run, so this never fires a spurious tunnel over a healthy USB/WiFi
          // connection — the thrash fix (memory: wifi_autoconnect_tunnel_thrash)
          // is preserved.
          for (const entry of savedList) fire(entry.ip, entry.port, entry.udid)
          // Discover runs CONCURRENTLY (best-effort) and only ADDS devices not
          // already in savedips — e.g. a second iPhone connected via the
          // auto-connect path itself that never went through the manual save.
          // Its failure must not block (or surface a toast for) the savedips
          // path, so we allSettle it alongside the saved attempts.
          attempts.push(
            (async () => {
              try {
                const dres = await api.wifiTunnelDiscover()
                for (const d of (dres?.devices || [])) {
                  fire(String(d.ip), Number(d.port) || 49152)
                }
              } catch { /* discover failed — savedips entries still tried */ }
            })(),
          )
          if (attempts.length === 0) return
          // Parallel: every iPhone gets its tunnel attempt at the same time
          // (savedips fired up-front, discover-found ones added as discover
          // resolves) so the user doesn't wait sequentially for unreachable
          // ones to time out (~10s each). The udid hint was passed into
          // startWifiTunnel so the backend tries the right pair record FIRST.
          // `attempts` is [...savedStartWifiTunnel promises, discoverDriver];
          // the discover driver resolves to undefined and can't be "rejected"
          // here (it swallows its own error), so it never miscounts as a
          // connect failure.
          const results = await Promise.allSettled(attempts)
          // The WiFi panel does NOT surface auto-pass failures (its tunnelError
          // is manual-path only). Only count the actual connect attempts (the
          // ones that fired a device); if EVERY fired candidate rejected, toast.
          // If nothing fired at all (no saved + no discovered), stay silent.
          const connectResults = results.slice(0, fired.size)
          const anyOk = connectResults.some((r) => r.status === 'fulfilled')
          if (connectResults.length > 0 && !anyOk) {
            onErrorRef.current?.('wifi.autoconnect_failed')
          }
        } catch {
          // Pre-flight (wifiTunnelStatus/discover) threw — silent: a transient
          // 500/timeout during backend warmup must NOT pop a spurious toast for
          // a user whose USB device is healthy but not yet surfaced in
          // connectedDevices. Only the inner Promise.allSettled all-failed path
          // (above) fires the onError toast, because that path proves every
          // explicit connect attempt was genuinely rejected.
        }
      })()
    }, 1500)
    return () => clearTimeout(tid)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected])
}
