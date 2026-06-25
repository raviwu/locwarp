import { useState, useCallback, useEffect, useRef } from 'react'
import * as api from '../services/api'
import type { WsRouter } from '../ports/WsRouter'
import type { WsEvent } from '../contract/wsEvents'
import { playCompletionAlert } from '../services/alertSound'

export enum SimMode {
  Teleport = 'teleport',
  Navigate = 'navigate',
  Loop = 'loop',
  Joystick = 'joystick',
  MultiStop = 'multistop',
  RandomWalk = 'randomwalk',
  GoldDitto = 'goldditto',
}

export enum MoveMode {
  Walking = 'walking',
  Running = 'running',
  Driving = 'driving',
}

export interface LatLng {
  lat: number
  lng: number
}

export interface SimulationStatus {
  running: boolean
  paused: boolean
  speed: number
  state?: string
  distance_remaining?: number
  distance_traveled?: number
}

// Mode → preset km/h. Kept in sync with ControlPanel's preset buttons
// so the status bar shows the correct "mode default" when the user
// applies a preset without a custom km/h.
const MODE_DEFAULT_KMH: Record<MoveMode, number> = {
  [MoveMode.Walking]: 10.8,
  [MoveMode.Running]: 19.8,
  [MoveMode.Driving]: 60,
}

// ── Per-device runtime state (group mode) ──────────────────────────────
export interface DeviceRuntime {
  udid: string
  state: string
  currentPos: LatLng | null
  destination: LatLng | null
  routePath: LatLng[]
  progress: number
  eta: number
  distanceRemaining: number
  distanceTraveled: number
  waypointIndex: number | null
  currentSpeedKmh: number
  error: string | null
  lapCount: number
  cooldown: number
}

export type RuntimesMap = Record<string, DeviceRuntime>

function emptyRuntime(udid: string): DeviceRuntime {
  return {
    udid,
    state: 'idle',
    currentPos: null,
    destination: null,
    routePath: [],
    progress: 0,
    eta: 0,
    distanceRemaining: 0,
    distanceTraveled: 0,
    waypointIndex: null,
    currentSpeedKmh: 0,
    error: null,
    lapCount: 0,
    cooldown: 0,
  }
}

// ── Fan-out helper ─────────────────────────────────────────────────────
export interface FanoutOutcome<T> {
  ok: Array<{ udid: string; value: T }>
  failed: Array<{ udid: string; reason: string }>
}

export function summarizeResults<T>(
  results: PromiseSettledResult<T>[],
  udids: string[],
  _action: string,
): FanoutOutcome<T> {
  const ok: FanoutOutcome<T>['ok'] = []
  const failed: FanoutOutcome<T>['failed'] = []
  results.forEach((r, i) => {
    const udid = udids[i]
    if (r.status === 'fulfilled') ok.push({ udid, value: r.value })
    else failed.push({ udid, reason: r.reason?.message ?? String(r.reason) })
  })
  return { ok, failed }
}

export function useSimulation(
  ws?: WsRouter,
  primaryUdid?: string | null,
  onTunnelRecovered?: () => void,
  speedJitter?: boolean,
) {
  // In dual-device mode every position_update carries a udid. Without a
  // filter, the legacy single-device setters below run for BOTH devices
  // and the global currentPosition ping-pongs between each device's
  // independently jittered coordinate, making the marker look stuttery.
  // Keep a ref so WS handler reads the latest primary synchronously.
  const primaryUdidRef = useRef<string | null>(primaryUdid ?? null)
  useEffect(() => { primaryUdidRef.current = primaryUdid ?? null }, [primaryUdid])

  // Stable ref for the recovery toast callback so the WS effect (keyed on
  // [ws, updateRuntime]) never re-subscribes when App passes a fresh closure.
  const onTunnelRecoveredRef = useRef(onTunnelRecovered)
  useEffect(() => { onTunnelRecoveredRef.current = onTunnelRecovered }, [onTunnelRecovered])
  const [mode, _setMode] = useState<SimMode>(SimMode.Teleport)
  const [moveMode, setMoveMode] = useState<MoveMode>(MoveMode.Walking)
  const [status, setStatus] = useState<SimulationStatus>({
    running: false,
    paused: false,
    speed: 0,
  })
  // Mirror status into a ref so callbacks captured with empty deps
  // (e.g. setMode) can read the live value without re-binding.
  const statusRef = useRef(status)
  useEffect(() => { statusRef.current = status }, [status])
  const [currentPosition, setCurrentPosition] = useState<LatLng | null>(null)
  const [destination, setDestination] = useState<LatLng | null>(null)
  const [progress, setProgress] = useState(0)
  const [eta, setEta] = useState<number | null>(null)
  const [waypoints, setWaypoints] = useState<LatLng[]>([])
  // Per-waypoint GPX seconds-from-start offsets, parallel to `waypoints`.
  // Set when loading a timed saved route; consumed (and cleared) by startLoop
  // so they are sent once to the backend and don't linger across subsequent
  // hand-drawn loops. Stored in a ref so updates don't trigger re-renders.
  const waypointTimestampsRef = useRef<number[] | null>(null)
  const setWaypointTimestamps = useCallback((ts: number[] | null) => {
    waypointTimestampsRef.current = ts
  }, [])
  const [routePath, setRoutePath] = useState<LatLng[]>([])
  const [customSpeedKmh, setCustomSpeedKmh] = useState<number | null>(null)
  const [speedMinKmh, setSpeedMinKmh] = useState<number | null>(null)
  const [speedMaxKmh, setSpeedMaxKmh] = useState<number | null>(null)
  // Global "straight-line path" toggle. When on, all nav modes bypass OSRM
  // and move along densified straight segments between waypoints.
  const [straightLine, setStraightLineRaw] = useState<boolean>(() => {
    try { return localStorage.getItem('locwarp.straight_line') === '1' } catch { return false }
  })
  // useCallback([]) so the setter keeps a stable ref across renders — it only
  // calls the stable raw setter + a pure localStorage write, so freezing it is
  // behaviorally identical and lets memo'd consumers (ControlPanel) short-circuit (N1).
  const setStraightLine = useCallback((v: boolean) => {
    setStraightLineRaw(v)
    try { localStorage.setItem('locwarp.straight_line', v ? '1' : '0') } catch { /* ignore */ }
  }, [])

  // Routing engine selection. Persisted in localStorage; backend default is
  // 'osrm' so omitting the field is equivalent to picking it explicitly.
  const ROUTE_ENGINES = ['osrm', 'osrm_fossgis', 'valhalla', 'brouter'] as const
  type RouteEngine = typeof ROUTE_ENGINES[number]
  const [routeEngine, setRouteEngineRaw] = useState<RouteEngine>(() => {
    try {
      const saved = localStorage.getItem('locwarp.route_engine')
      if (saved && (ROUTE_ENGINES as readonly string[]).includes(saved)) return saved as RouteEngine
    } catch { /* ignore */ }
    return 'osrm'
  })
  const setRouteEngine = useCallback((v: RouteEngine) => {
    setRouteEngineRaw(v)
    try { localStorage.setItem('locwarp.route_engine', v) } catch { /* ignore */ }
  }, [])

  // Per-mode pause settings, persisted in localStorage.
  interface PauseSetting { enabled: boolean; min: number; max: number }
  const defaultPause: PauseSetting = { enabled: true, min: 5, max: 20 }
  const loadPause = (key: string): PauseSetting => {
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return defaultPause
      const p = JSON.parse(raw)
      return {
        enabled: typeof p.enabled === 'boolean' ? p.enabled : true,
        min: typeof p.min === 'number' ? p.min : 5,
        max: typeof p.max === 'number' ? p.max : 20,
      }
    } catch {
      return defaultPause
    }
  }
  const savePause = (key: string, v: PauseSetting) => {
    try { localStorage.setItem(key, JSON.stringify(v)) } catch { /* ignore */ }
  }
  const [pauseMultiStop, setPauseMultiStopRaw] = useState<PauseSetting>(() => loadPause('locwarp.pause.multi_stop'))
  const [pauseLoop, setPauseLoopRaw] = useState<PauseSetting>(() => loadPause('locwarp.pause.loop'))
  const [pauseRandomWalk, setPauseRandomWalkRaw] = useState<PauseSetting>(() => loadPause('locwarp.pause.random_walk'))
  // []-stable (see setStraightLine). `savePause` is a render-stable pure helper
  // (only a localStorage write); not listing it is safe and intentional.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const setPauseMultiStop = useCallback((v: PauseSetting) => { setPauseMultiStopRaw(v); savePause('locwarp.pause.multi_stop', v) }, [])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const setPauseLoop = useCallback((v: PauseSetting) => { setPauseLoopRaw(v); savePause('locwarp.pause.loop', v) }, [])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const setPauseRandomWalk = useCallback((v: PauseSetting) => { setPauseRandomWalkRaw(v); savePause('locwarp.pause.random_walk', v) }, [])
  const [error, setError] = useState<string | null>(null)
  // Transient "WiFi tunnel dropped, reconnecting…" state for the up-to-~21s
  // backend retry window (tunnel_degraded → retry×3 → tunnel_recovered | tunnel_lost).
  // Distinct from `error` (the terminal red banner) so a recovery doesn't get
  // conflated with a real failure. Primary-device focused, like `error`.
  const [tunnelReconnecting, setTunnelReconnecting] = useState(false)
  // Attempt counter + retry countdown derived from the enriched tunnel_degraded
  // payload ({attempt, max_attempts, next_delay_s}). Null when the backend
  // sent no attempt keys (empty backoff) — the banner then falls back to the
  // plain "reconnecting…" copy. retryInSec ticks down to 0 at 1 Hz.
  const [reconnectInfo, setReconnectInfo] = useState<
    { attempt: number; maxAttempts: number; retryInSec: number } | null
  >(null)
  // The udid whose tunnel was just LOST (terminal). Drives the one-click
  // Reconnect button on the error banner. Cleared when the tunnel recovers or
  // the device reconnects.
  const [lostUdid, setLostUdid] = useState<string | null>(null)
  // Random-walk pause countdown (unix epoch seconds of when pause ends)
  const [pauseEndAt, setPauseEndAt] = useState<number | null>(null)
  const [pauseRemaining, setPauseRemaining] = useState<number | null>(null)
  const [ddiMounting, setDdiMounting] = useState(false)
  // Stage within the DDI mount pipeline. null when not mounting, else
  // one of the backend's stage names (starting / downloading / verifying
  // / signing / uploading / mounting). `elapsed` is seconds since the
  // mount started, used for a rough ETA estimate in the overlay.
  const [ddiStage, setDdiStage] = useState<{ stage: string; elapsed: number } | null>(null)
  const [waypointProgress, setWaypointProgress] = useState<{ current: number; next: number; total: number } | null>(null)
  // Loop lap tracker. `current` = laps completed so far; `total` = the
  // configured lap limit if the user asked for auto-stop, or null for an
  // unbounded loop. Updated on `lap_complete` WS events from the backend.
  const [lapProgress, setLapProgress] = useState<{ current: number; total: number | null } | null>(null)
  // User's preferred lap count for the Loop mode start button. Null / 0 = no limit.
  const [loopLapCount, setLoopLapCountRaw] = useState<number | null>(() => {
    try {
      const raw = localStorage.getItem('locwarp.loop.lap_count')
      if (!raw) return null
      const n = parseInt(raw, 10)
      return Number.isFinite(n) && n > 0 ? n : null
    } catch { return null }
  })
  const setLoopLapCount = useCallback((v: number | null) => {
    setLoopLapCountRaw(v)
    try {
      if (v != null && v > 0) localStorage.setItem('locwarp.loop.lap_count', String(v))
      else localStorage.removeItem('locwarp.loop.lap_count')
    } catch { /* ignore quota errors */ }
  }, [])

  // Jump mode (point-to-point teleport with fixed dwell). Persisted per-mode
  // so the user's preference for Loop and MultiStop is restored on reload.
  const [jumpMode, setJumpModeRaw] = useState<boolean>(() => {
    try { return localStorage.getItem('locwarp.jump.mode') === '1' } catch { return false }
  })
  const setJumpMode = useCallback((v: boolean) => {
    setJumpModeRaw(v)
    try { localStorage.setItem('locwarp.jump.mode', v ? '1' : '0') } catch { /* ignore */ }
  }, [])
  const [jumpInterval, setJumpIntervalRaw] = useState<number>(() => {
    try {
      const n = parseFloat(localStorage.getItem('locwarp.jump.interval') || '12')
      return Number.isFinite(n) && n >= 0 ? n : 12
    } catch { return 12 }
  })
  const setJumpInterval = useCallback((v: number) => {
    const clamped = Number.isFinite(v) && v >= 0 ? v : 12
    setJumpIntervalRaw(clamped)
    try { localStorage.setItem('locwarp.jump.interval', String(clamped)) } catch { /* ignore */ }
  }, [])
  // What's *actually* running on the device — set when a route handler
  // starts or when applySpeed succeeds. Used by the status bar so the
  // user doesn't see a typed-or-preset-selected speed before it has
  // been applied. Initialized to the walking default so the status bar
  // has something sensible to show before the first apply / start.
  const [effectiveSpeed, setEffectiveSpeed] = useState<
    { kmh: number | null; min: number | null; max: number | null } | null
  >({ kmh: MODE_DEFAULT_KMH.walking, min: null, max: null })

  // Per-device runtime map (group mode). Populated from WS events tagged with udid.
  const [runtimes, setRuntimes] = useState<RuntimesMap>({})
  const updateRuntime = useCallback((udid: string, patch: Partial<DeviceRuntime>) => {
    setRuntimes((prev) => {
      const cur = prev[udid] ?? emptyRuntime(udid)
      return { ...prev, [udid]: { ...cur, ...patch } }
    })
  }, [])

  // Tick the pause countdown at 1 Hz
  useEffect(() => {
    if (pauseEndAt == null) {
      setPauseRemaining(null)
      return
    }
    const tick = () => {
      const rem = Math.max(0, Math.round((pauseEndAt - Date.now()) / 1000))
      setPauseRemaining(rem)
      if (rem <= 0) setPauseEndAt(null)
    }
    tick()
    const id = setInterval(tick, 250)
    return () => clearInterval(id)
  }, [pauseEndAt])

  // Tick the reconnect retry countdown down to 0 at 1 Hz.
  // Dep array uses the round-identity scalars (attempt, maxAttempts) rather
  // than the full reconnectInfo object, so the interval is armed ONCE per
  // reconnect round and ticks internally — not re-armed on every retryInSec
  // tick (which would clear+create a new interval every second). The effect
  // still re-arms when a new tunnel_degraded round arrives (attempt changes)
  // and tears down cleanly when reconnectInfo is cleared (attempt→undefined).
  // The functional updater reads `prev`, not the outer closure, so stale
  // closure is not a concern.
  useEffect(() => {
    if (reconnectInfo == null) return
    if (reconnectInfo.retryInSec <= 0) return
    const id = setInterval(() => {
      setReconnectInfo((prev) => {
        if (prev == null || prev.retryInSec <= 0) return prev
        return { ...prev, retryInSec: Math.max(0, prev.retryInSec - 1) }
      })
    }, 1000)
    return () => clearInterval(id)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reconnectInfo?.attempt, reconnectInfo?.maxAttempts])

  // Process incoming WS messages via typed WsRouter subscriptions. The old
  // useState-based approach dropped messages when two arrived in the
  // same React tick; see useWebSocket.ts for details.
  useEffect(() => {
    if (!ws) return

    const offPos = ws.subscribe('position_update', (e: WsEvent) => {
      // ── Group mode: mirror per-device state into `runtimes` map ────────
      const udid = e.udid as string | undefined
      if (udid) {
        updateRuntime(udid, {
          currentPos: (typeof e.lat === 'number' && typeof e.lng === 'number') ? { lat: e.lat as number, lng: e.lng as number } : undefined as any,
          progress: (e.progress ?? undefined) as any,
          eta: ((e.eta_seconds ?? e.eta) ?? undefined) as any,
          distanceRemaining: (e.distance_remaining ?? undefined) as any,
          distanceTraveled: (e.distance_traveled ?? undefined) as any,
          currentSpeedKmh: e.speed_mps != null ? (e.speed_mps as number) * 3.6 : undefined as any,
        })
      }
      // Dual-device filter
      const msgUdid = udid
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      const lat = e.lat as number | undefined
      const lng = e.lng as number | undefined
      if (typeof lat === 'number' && typeof lng === 'number') {
        setCurrentPosition({ lat, lng })
      }
      if (e.progress != null) {
        setProgress(e.progress as number)
      }
      {
        const etaVal = e.eta_seconds ?? e.eta
        if (etaVal != null) setEta(etaVal as number)
      }
      {
        const dr = e.distance_remaining
        const dt = e.distance_traveled
        if (dr != null || dt != null) {
          setStatus((prev) => ({
            ...prev,
            ...(dr != null ? { distance_remaining: dr as number } : {}),
            ...(dt != null ? { distance_traveled: dt as number } : {}),
          }))
        }
      }
    })

    const handleComplete = (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      setStatus((prev) => ({ ...prev, running: false, paused: false }))
      setProgress(1)
      setEta(null)
      setPauseEndAt(null)
      setWaypointProgress(null)
      setLapProgress(null)
      setDestination(null)
      setRoutePath([])
      // Route reached its end naturally (vs user pressing stop). Fire
      // the user-toggleable cascading-bell alert; alertSound's setting
      // gate suppresses playback when disabled.
      playCompletionAlert()
    }
    const completeWithRuntime = (e: WsEvent) => {
      // ── Group mode ──────────────────────────────────────────────────────
      const udid = e.udid as string | undefined
      if (udid) updateRuntime(udid, { progress: 1, state: 'idle' })
      handleComplete(e)
    }
    const offNavComplete = ws.subscribe('navigation_complete', completeWithRuntime)
    const offMultiComplete = ws.subscribe('multi_stop_complete', completeWithRuntime)
    const offLoopComplete = ws.subscribe('loop_complete', completeWithRuntime)

    const offWpProgress = ws.subscribe('waypoint_progress', (e: WsEvent) => {
      // ── Group mode ──────────────────────────────────────────────────────
      const udid = e.udid as string | undefined
      if (udid && typeof e.current_index === 'number') {
        updateRuntime(udid, { waypointIndex: e.current_index as number })
      }
      // Dual-device filter
      const msgUdid = udid
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      if (typeof e.current_index === 'number') {
        setWaypointProgress({
          current: e.current_index as number,
          next: (e.next_index as number) ?? (e.current_index as number) + 1,
          total: (e.total as number) ?? 0,
        })
      }
    })

    const offLapComplete = ws.subscribe('lap_complete', (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      if (typeof e.lap === 'number') {
        setLapProgress({
          current: e.lap as number,
          total: typeof e.total === 'number' && (e.total as number) > 0 ? e.total as number : null,
        })
      }
    })

    const offDdiMounting = ws.subscribe('ddi_mounting', (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      setDdiMounting(true)
      if (typeof e.stage === 'string') {
        setDdiStage({ stage: e.stage as string, elapsed: typeof e.elapsed === 'number' ? e.elapsed as number : 0 })
      }
    })

    const handleDdiDone = (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      setDdiMounting(false)
      setDdiStage(null)
    }
    const offDdiMounted = ws.subscribe('ddi_mounted', handleDdiDone)
    const offDdiMountFailed = ws.subscribe('ddi_mount_failed', handleDdiDone)

    const offDdiNotMounted = ws.subscribe('ddi_not_mounted', (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      // Backend reports the DDI isn't mounted. Silently dismiss the
      // mount-progress overlay; we no longer surface the hint as a
      // banner because most users on iOS 17+ have DDI auto-mounted by
      // a prior tool and the warning fires spuriously after every
      // reconnect. Users who genuinely lack DDI will see the failure
      // when an action (teleport / navigate) actually returns an
      // error from the device.
      setDdiMounting(false)
      setDdiStage(null)
    })

    // ── WiFi-tunnel three-state lifecycle (per-udid, primary-filtered) ──
    // The backend watchdog runs degraded → retry×3 (~3/6/12s) → recovered,
    // or → lost (terminal) if every retry fails. We mirror that as a transient
    // "reconnecting…" indicator + a terminal banner, kept separate so a
    // recovery is never conflated with a real failure.
    const offTunnelDegraded = ws.subscribe('tunnel_degraded', (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      // Entering the backend retry/backoff window — show "reconnecting…".
      setTunnelReconnecting(true)
      // Enriched payload (attempt/max_attempts/next_delay_s) drives the
      // attempt counter + countdown. Absent (empty backoff) → leave null so
      // the banner shows the plain reconnecting copy.
      const attempt = typeof e.attempt === 'number' ? e.attempt : undefined
      const maxAttempts = typeof e.max_attempts === 'number' ? e.max_attempts : undefined
      const nextDelay = typeof e.next_delay_s === 'number' ? e.next_delay_s : undefined
      if (attempt != null && maxAttempts != null && nextDelay != null) {
        setReconnectInfo({ attempt, maxAttempts, retryInSec: Math.round(nextDelay) })
      }
    })

    const offTunnelRecovered = ws.subscribe('tunnel_recovered', (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      // Back online. Drop the reconnecting indicator and any stale banner,
      // then fire the positive "restored" toast. (setError(null) unconditional
      // to match the sibling device_connected/device_reconnected handlers,
      // which the backend emits one frame after this anyway.)
      setTunnelReconnecting(false)
      setReconnectInfo(null)
      setLostUdid(null)
      setError(null)
      onTunnelRecoveredRef.current?.()
    })

    const offTunnelLost = ws.subscribe('tunnel_lost', (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      // Retries exhausted → terminal: drop the transient reconnecting state
      // and raise the persistent banner.
      setTunnelReconnecting(false)
      setReconnectInfo(null)
      // Uses localStorage to get current language (hooks don't have i18n context easily here)
      setError((typeof localStorage !== 'undefined' && localStorage.getItem('locwarp.lang') === 'en')
        ? 'Wi-Fi tunnel dropped, please reconnect'
        : 'WiFi Tunnel 連線中斷,請重新建立')
      setLostUdid((msgUdid as string | undefined) ?? null)
    })

    const offDisc = ws.subscribe('device_disconnected', (e: WsEvent) => {
      // ── Group mode ──────────────────────────────────────────────────────
      const udid = e.udid as string | undefined
      if (udid) updateRuntime(udid, { state: 'disconnected' })
      // Dual-device filter
      const msgUdid = udid
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      // In dual-device mode we only show the full-screen banner when the
      // LAST connected device goes away. If another device is still alive
      // (remaining_count > 0), the sidebar chip already reflects the
      // per-device state; no need to nag the user. Backward compat: when
      // the broadcast omits remaining_count we default to 0 (old behaviour).
      const remaining = typeof e.remaining_count === 'number' ? e.remaining_count as number : 0
      if (remaining === 0) {
        const isEn = typeof localStorage !== 'undefined' && localStorage.getItem('locwarp.lang') === 'en'
        // Softened from a dead-end terminal message: the watchdog may
        // auto-reconnect within ~27s (it broadcasts device_connected, which
        // clears this banner). Copy now reads as "reconnecting" with replug as
        // the fallback, mirroring the WiFi degraded->reconnecting tone.
        setError(isEn
          ? 'Device disconnected — trying to reconnect; replug USB if it does not come back'
          : '裝置連線中斷 — 嘗試自動重連中,若未恢復請重新插上 USB')
        setStatus((prev) => ({ ...prev, running: false, paused: false }))
      } else {
        // Clear any stale banner in case a previous lost-all event left it
        // visible; the fact that at least one device is still connected
        // means we're back to a healthy state.
        setError(null)
      }
    })

    const offConnected = ws.subscribe('device_connected', (e: WsEvent) => {
      // ── Group mode ──────────────────────────────────────────────────────
      const udid = e.udid as string | undefined
      if (udid) {
        setRuntimes((prev) => prev[udid] ? prev : { ...prev, [udid]: emptyRuntime(udid) })
      }
      // A device reconnecting implicitly resolves any prior connection-
      // loss banner (watchdog auto-connect broadcasts `device_connected`).
      const msgUdid = udid
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      setError(null)
      setTunnelReconnecting(false)
      setReconnectInfo(null)
      setLostUdid(null)
    })

    const offDeviceError = ws.subscribe('device_error', (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      // Backend hit an internal failure outside the request/response path
      // (e.g. USB-fallback engine rebuild after a tunnel stop). Surface it on
      // the terminal banner so the user isn't left thinking the device is
      // still healthy. Payload carries {stage, error}.
      const stage = typeof e.stage === 'string' ? e.stage as string : ''
      const detail = typeof e.error === 'string' ? e.error as string : ''
      const isEn = typeof localStorage !== 'undefined' && localStorage.getItem('locwarp.lang') === 'en'
      const base = isEn ? 'Device error' : '裝置發生錯誤'
      setError(detail ? `${base}: ${detail}` : (stage ? `${base} (${stage})` : base))
    })

    const handlePauseStart = (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      const dur = e.duration_seconds
      if (typeof dur === 'number' && (dur as number) > 0) {
        setPauseEndAt(Date.now() + (dur as number) * 1000)
      }
    }
    const offPauseCountdown = ws.subscribe('pause_countdown', handlePauseStart)

    const handlePauseEnd = (e: WsEvent) => {
      const msgUdid = e.udid as string | undefined
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      setPauseEndAt(null)
    }
    const offPauseCountdownEnd = ws.subscribe('pause_countdown_end', handlePauseEnd)

    const offRoutePath = ws.subscribe('route_path', (e: WsEvent) => {
      // ── Group mode ──────────────────────────────────────────────────────
      const udid = e.udid as string | undefined
      if (udid && Array.isArray(e.coords)) {
        updateRuntime(udid, {
          routePath: (e.coords as any[]).map((p: any) => ({ lat: p.lat ?? p[0], lng: p.lng ?? p[1] })),
        })
      }
      // Dual-device filter
      const msgUdid = udid
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      const pts = e.coords
      if (Array.isArray(pts)) {
        setRoutePath((pts as any[]).map((p: any) => ({ lat: p.lat ?? p[0], lng: p.lng ?? p[1] })))
      }
    })

    const offStateChange = ws.subscribe('state_change', (e: WsEvent) => {
      // ── Group mode ──────────────────────────────────────────────────────
      const udid = e.udid as string | undefined
      if (udid && e.state) {
        updateRuntime(udid, { state: e.state as string, ...((e.state === 'idle' || e.state === 'disconnected') ? { routePath: [] } : {}) })
      }
      // Dual-device filter
      const msgUdid = udid
      const primary = primaryUdidRef.current
      if (primary && msgUdid && msgUdid !== primary) return
      const st = e.state as string | undefined
      if (st === 'idle') {
        // User-initiated stop or natural sim completion: clear the
        // overlays so the map goes back to a clean state.
        setStatus((prev) => ({ ...prev, running: false, paused: false, state: st }))
        setRoutePath([])
        setDestination(null)
        setEta(null)
      } else if (st === 'disconnected') {
        // USB unplug or tunnel death of THIS engine. In dual-device
        // mode the surviving device is still running the same sim, so
        // keep routePath / destination AND keep running/paused alone:
        // flipping running to false here would revert the toolbar's
        // 停止 button back to 開始 even though the other device is
        // still actively running the simulation. Just record the new
        // state for completeness; the global running flag is reset by
        // the device_disconnected handler when remaining_count hits 0.
        setStatus((prev) => ({ ...prev, state: st }))
      } else if (st === 'paused') {
        setStatus((prev) => ({ ...prev, paused: true, state: st }))
      } else if (st) {
        setStatus((prev) => ({ ...prev, running: true, paused: false, state: st }))
      }
    })

    return () => {
      offPos(); offNavComplete(); offMultiComplete(); offLoopComplete()
      offWpProgress(); offLapComplete(); offDdiMounting(); offDdiMounted(); offDdiMountFailed()
      offDdiNotMounted(); offTunnelDegraded(); offTunnelRecovered(); offTunnelLost()
      offDisc(); offConnected(); offDeviceError()
      offPauseCountdown(); offPauseCountdownEnd()
      offRoutePath(); offStateChange()
    }
  }, [ws, updateRuntime])

  const clearError = useCallback(() => setError(null), [])

  // Public mode setter: clears the destination marker + route path when the
  // user switches mode tabs. Internal handlers (teleport/navigate/loop/...)
  // still use _setMode directly so they can set destination in the same tick.
  // While a simulation is in progress, switching tabs is just a UI peek —
  // we keep the live route, destination, and waypoints on screen so the
  // user can come back to the running mode without losing context.
  const setMode = useCallback((next: SimMode) => {
    _setMode((prev) => {
      if (prev !== next && !statusRef.current.running && !statusRef.current.paused) {
        setDestination(null)
        setRoutePath([])
        setWaypoints([])
        setProgress(0)
        setEta(null)
      }
      return next
    })
  }, [])

  const teleport = useCallback(async (lat: number, lng: number) => {
    setError(null)
    try {
      // Intentionally NOT calling _setMode here. Teleport is an ACTION
      // (right-click / bookmark / recent / address / locate-PC / coord
      // overlay all flow through here), not a mode switch. Mode change
      // only happens when the user explicitly clicks the Teleport tab in
      // ControlPanel, which goes through the separate setMode() path
      // that also wipes waypoints / destination / routePath. Previously,
      // this line flipped sim.mode to Teleport on every teleport action,
      // which was visible as "setting up Loop waypoints, right-clicking
      // to teleport, then finding waypoints gone" — the tab switch made
      // the Loop UI unmount its waypoint list. Removing this one line is
      // the entire fix.
      const res = await api.teleport(lat, lng)
      setCurrentPosition({ lat, lng })
      setDestination(null)
      setProgress(0)
      setEta(null)
      return res
    } catch (err: any) {
      setError(err.message)
      throw err
    }
  }, [])

  const navigate = useCallback(
    async (lat: number, lng: number) => {
      setError(null)
      try {
        _setMode(SimMode.Navigate)
        setDestination({ lat, lng })
        setProgress(0)
        const res = await api.navigate(lat, lng, moveMode, { speed_kmh: customSpeedKmh, speed_min_kmh: speedMinKmh, speed_max_kmh: speedMaxKmh }, undefined, straightLine, routeEngine, speedJitter)
        setStatus((prev) => ({ ...prev, running: true, paused: false }))
        setEffectiveSpeed({ kmh: customSpeedKmh ?? MODE_DEFAULT_KMH[moveMode], min: speedMinKmh, max: speedMaxKmh })
        return res
      } catch (err: any) {
        setError(err.message)
        throw err
      }
    },
    [moveMode, customSpeedKmh, speedMinKmh, speedMaxKmh, pauseMultiStop, pauseLoop, pauseRandomWalk, straightLine, routeEngine, speedJitter],
  )

  const startLoop = useCallback(
    async (wps: LatLng[]) => {
      setError(null)
      try {
        _setMode(SimMode.Loop)
        // Don't setWaypoints(wps) — wps is the route as sent to the backend
        // (already includes the start position from caller). Overwriting UI
        // waypoints here would prepend the start point on every restart,
        // and break the backend↔UI seg_idx mapping for highlighting.
        setProgress(0)
        setLapProgress(null)
        // Consume GPX timestamps once (cleared immediately so they don't
        // accidentally persist across subsequent hand-drawn loop starts).
        const timestamps = waypointTimestampsRef.current ?? undefined
        waypointTimestampsRef.current = null
        const res = await api.startLoop(wps, moveMode, { speed_kmh: customSpeedKmh, speed_min_kmh: speedMinKmh, speed_max_kmh: speedMaxKmh }, { pause_enabled: pauseLoop.enabled, pause_min: pauseLoop.min, pause_max: pauseLoop.max }, undefined, straightLine, loopLapCount, routeEngine, { jump_mode: jumpMode, jump_interval: jumpInterval }, timestamps, speedJitter)
        setStatus((prev) => ({ ...prev, running: true, paused: false }))
        setEffectiveSpeed({ kmh: customSpeedKmh ?? MODE_DEFAULT_KMH[moveMode], min: speedMinKmh, max: speedMaxKmh })
        return res
      } catch (err: any) {
        setError(err.message)
        throw err
      }
    },
    [moveMode, customSpeedKmh, speedMinKmh, speedMaxKmh, pauseMultiStop, pauseLoop, pauseRandomWalk, straightLine, loopLapCount, routeEngine, jumpMode, jumpInterval, speedJitter],
  )

  const multiStop = useCallback(
    async (wps: LatLng[], stopDuration: number, loop: boolean) => {
      setError(null)
      try {
        _setMode(SimMode.MultiStop)
        // See startLoop — do not overwrite UI waypoints with the backend route.
        setProgress(0)
        const res = await api.multiStop(wps, moveMode, stopDuration, loop, { speed_kmh: customSpeedKmh, speed_min_kmh: speedMinKmh, speed_max_kmh: speedMaxKmh }, { pause_enabled: pauseMultiStop.enabled, pause_min: pauseMultiStop.min, pause_max: pauseMultiStop.max }, undefined, straightLine, routeEngine, { jump_mode: jumpMode, jump_interval: jumpInterval }, speedJitter)
        setStatus((prev) => ({ ...prev, running: true, paused: false }))
        setEffectiveSpeed({ kmh: customSpeedKmh ?? MODE_DEFAULT_KMH[moveMode], min: speedMinKmh, max: speedMaxKmh })
        return res
      } catch (err: any) {
        setError(err.message)
        throw err
      }
    },
    [moveMode, customSpeedKmh, speedMinKmh, speedMaxKmh, pauseMultiStop, pauseLoop, pauseRandomWalk, straightLine, routeEngine, jumpMode, jumpInterval, speedJitter],
  )

  const randomWalk = useCallback(
    async (center: LatLng, radiusM: number) => {
      setError(null)
      try {
        _setMode(SimMode.RandomWalk)
        setProgress(0)
        const res = await api.randomWalk(center, radiusM, moveMode, { speed_kmh: customSpeedKmh, speed_min_kmh: speedMinKmh, speed_max_kmh: speedMaxKmh }, { pause_enabled: pauseRandomWalk.enabled, pause_min: pauseRandomWalk.min, pause_max: pauseRandomWalk.max }, undefined, undefined, straightLine, routeEngine, speedJitter)
        setStatus((prev) => ({ ...prev, running: true, paused: false }))
        setEffectiveSpeed({ kmh: customSpeedKmh ?? MODE_DEFAULT_KMH[moveMode], min: speedMinKmh, max: speedMaxKmh })
        return res
      } catch (err: any) {
        setError(err.message)
        throw err
      }
    },
    [moveMode, customSpeedKmh, speedMinKmh, speedMaxKmh, pauseMultiStop, pauseLoop, pauseRandomWalk, straightLine, routeEngine, speedJitter],
  )

  const joystickStart = useCallback(async () => {
    setError(null)
    try {
      _setMode(SimMode.Joystick)
      const res = await api.joystickStart(moveMode)
      setStatus((prev) => ({ ...prev, running: true, paused: false }))
      return res
    } catch (err: any) {
      setError(err.message)
      throw err
    }
  }, [moveMode])

  const joystickStop = useCallback(async () => {
    setError(null)
    try {
      const res = await api.joystickStop()
      // leave mode as-is; status drives running state
      setStatus((prev) => ({ ...prev, running: false, paused: false }))
      return res
    } catch (err: any) {
      setError(err.message)
      throw err
    }
  }, [])

  const pause = useCallback(async () => {
    setError(null)
    try {
      const res = await api.pauseSim()
      setStatus((prev) => ({ ...prev, paused: true }))
      return res
    } catch (err: any) {
      setError(err.message)
      throw err
    }
  }, [])

  const resume = useCallback(async () => {
    setError(null)
    try {
      const res = await api.resumeSim()
      setStatus((prev) => ({ ...prev, paused: false }))
      return res
    } catch (err: any) {
      setError(err.message)
      throw err
    }
  }, [])

  const stop = useCallback(async () => {
    setError(null)
    try {
      const res = await api.stopSim()
      setStatus((prev) => ({ ...prev, running: false, paused: false }))
      setProgress(0)
      setEta(null)
      setRoutePath([])
      setWaypointProgress(null)
      setLapProgress(null)
      // Keep effectiveSpeed so status bar shows last-applied speed after stop/restore.
      // Clear the destination so the red "target" marker goes away —
      // lingering destination pin after Stop was a reported UX bug.
      setDestination(null)
      return res
    } catch (err: any) {
      setError(err.message)
      throw err
    }
  }, [])

  const restore = useCallback(async () => {
    setError(null)
    try {
      const res = await api.restoreSim()
      // leave mode as-is; status drives running state
      setStatus({ running: false, paused: false, speed: 0 })
      setCurrentPosition(null)
      setDestination(null)
      setProgress(0)
      setEta(null)
      setWaypoints([])
      setRoutePath([])
      setWaypointProgress(null)
      setLapProgress(null)
      // Keep effectiveSpeed so status bar shows last-applied speed after stop/restore.
      return res
    } catch (err: any) {
      setError(err.message)
      throw err
    }
  }, [])

  const applySpeed = useCallback(async () => {
    setError(null)
    try {
      const res = await api.applySpeed(moveMode, {
        speed_kmh: customSpeedKmh,
        speed_min_kmh: speedMinKmh,
        speed_max_kmh: speedMaxKmh,
      })
      // Status bar should now reflect the just-applied values, not the
      // ones the route originally started with.
      setEffectiveSpeed({ kmh: customSpeedKmh ?? MODE_DEFAULT_KMH[moveMode], min: speedMinKmh, max: speedMaxKmh })
      return res
    } catch (err: any) {
      setError(err.message)
      throw err
    }
  }, [moveMode, customSpeedKmh, speedMinKmh, speedMaxKmh])

  // Fetch initial status on mount
  const initialFetched = useRef(false)
  useEffect(() => {
    if (initialFetched.current) return
    initialFetched.current = true
    api.getStatus().then((res) => {
      if (res.position) {
        setCurrentPosition({ lat: res.position.lat, lng: res.position.lng })
      }
      if (res.mode) _setMode(res.mode)
      if (res.running != null || res.paused != null) {
        setStatus({
          running: !!res.running,
          paused: !!res.paused,
          speed: res.speed ?? 0,
        })
      }
    }).catch(() => {
      // backend may not be running yet
    })
  }, [])

  // ── Group-mode fan-out helpers ──────────────────────────────────────
  // Each takes an explicit list of udids so the caller (App.tsx) decides
  // which devices to target. Returns a FanoutOutcome for toast summarisation.
  const fanout = useCallback(async <T,>(
    udids: string[],
    action: string,
    fn: (udid: string) => Promise<T>,
  ): Promise<FanoutOutcome<T>> => {
    if (udids.length === 0) {
      setError('No device connected')
      return { ok: [], failed: [] }
    }
    const results = await Promise.allSettled(udids.map((u) => fn(u)))
    return summarizeResults(results, udids, action)
  }, [])

  // Group-mode sync helper: before any action that depends on a common start
  // (navigate / loop / multistop / randomwalk / joystick), teleport every
  // target device to the primary's current position so both phones begin from
  // the same coordinate and follow identical paths.
  const preSyncStart = useCallback(async (udids: string[]) => {
    if (udids.length < 2) return
    const pos = currentPosition
    if (!pos) return
    try {
      await Promise.allSettled(udids.map((u) => api.teleport(pos.lat, pos.lng, u)))
      // Tiny settle delay so devices finalise the teleport before the next
      // command arrives.
      await new Promise((r) => setTimeout(r, 150))
    } catch {
      // Non-fatal: fall through to the primary action.
    }
  }, [currentPosition])

  const teleportAll = useCallback((udids: string[], lat: number, lng: number) =>
    fanout(udids, 'teleport', (u) => api.teleport(lat, lng, u)), [fanout])

  const [goldDittoCycling, setGoldDittoCycling] = useState(false)

  const goldDittoCycleAll = useCallback(async (
    udids: string[],
    args: {
      target: 'A' | 'B' | 'auto';
      lat_a: number; lng_a: number;
      lat_b: number; lng_b: number;
      wait_seconds: number;
    },
  ) => {
    setGoldDittoCycling(true)
    try {
      return await fanout(udids, 'goldditto_cycle', (u) => api.goldDittoCycle(args, u))
    } finally {
      setGoldDittoCycling(false)
    }
  }, [fanout])

  const navigateAll = useCallback(async (udids: string[], lat: number, lng: number) => {
    await preSyncStart(udids)
    return fanout(udids, 'navigate', (u) => api.navigate(lat, lng, moveMode, { speed_kmh: customSpeedKmh, speed_min_kmh: speedMinKmh, speed_max_kmh: speedMaxKmh }, u, straightLine, routeEngine, speedJitter))
  }, [fanout, preSyncStart, moveMode, customSpeedKmh, speedMinKmh, speedMaxKmh, straightLine, routeEngine, speedJitter])
  const startLoopAll = useCallback(async (udids: string[], wps: LatLng[]) => {
    await preSyncStart(udids)
    setLapProgress(null)
    // Consume GPX timestamps once — same as startLoop so fan-out paths also
    // activate the timed-replay branch when a timed saved route is played.
    const timestamps = waypointTimestampsRef.current ?? undefined
    waypointTimestampsRef.current = null
    return fanout(udids, 'loop', (u) => api.startLoop(wps, moveMode, { speed_kmh: customSpeedKmh, speed_min_kmh: speedMinKmh, speed_max_kmh: speedMaxKmh }, { pause_enabled: pauseLoop.enabled, pause_min: pauseLoop.min, pause_max: pauseLoop.max }, u, straightLine, loopLapCount, routeEngine, { jump_mode: jumpMode, jump_interval: jumpInterval }, timestamps, speedJitter))
  }, [fanout, preSyncStart, moveMode, customSpeedKmh, speedMinKmh, speedMaxKmh, pauseLoop, straightLine, loopLapCount, routeEngine, jumpMode, jumpInterval, speedJitter])
  const multiStopAll = useCallback(async (udids: string[], wps: LatLng[], dur: number, loop: boolean) => {
    await preSyncStart(udids)
    return fanout(udids, 'multistop', (u) => api.multiStop(wps, moveMode, dur, loop, { speed_kmh: customSpeedKmh, speed_min_kmh: speedMinKmh, speed_max_kmh: speedMaxKmh }, { pause_enabled: pauseMultiStop.enabled, pause_min: pauseMultiStop.min, pause_max: pauseMultiStop.max }, u, straightLine, routeEngine, { jump_mode: jumpMode, jump_interval: jumpInterval }, speedJitter))
  }, [fanout, preSyncStart, moveMode, customSpeedKmh, speedMinKmh, speedMaxKmh, pauseMultiStop, straightLine, routeEngine, jumpMode, jumpInterval, speedJitter])
  const randomWalkAll = useCallback(async (udids: string[], center: LatLng, r: number) => {
    await preSyncStart(udids)
    // Shared seed → both engines produce identical destination sequences.
    const seed = udids.length >= 2 ? Date.now() : null
    return fanout(udids, 'randomwalk', (u) => api.randomWalk(center, r, moveMode, { speed_kmh: customSpeedKmh, speed_min_kmh: speedMinKmh, speed_max_kmh: speedMaxKmh }, { pause_enabled: pauseRandomWalk.enabled, pause_min: pauseRandomWalk.min, pause_max: pauseRandomWalk.max }, u, seed, straightLine, routeEngine, speedJitter))
  }, [fanout, preSyncStart, moveMode, customSpeedKmh, speedMinKmh, speedMaxKmh, pauseRandomWalk, straightLine, routeEngine, speedJitter])
  const applySpeedAll = useCallback(async (udids: string[]) => {
    const outcome = await fanout(udids, 'apply-speed', (u) => api.applySpeed(moveMode, { speed_kmh: customSpeedKmh, speed_min_kmh: speedMinKmh, speed_max_kmh: speedMaxKmh }, u))
    if (outcome.ok.length > 0) {
      setEffectiveSpeed({ kmh: customSpeedKmh ?? MODE_DEFAULT_KMH[moveMode], min: speedMinKmh, max: speedMaxKmh })
    }
    return outcome
  }, [fanout, moveMode, customSpeedKmh, speedMinKmh, speedMaxKmh])
  const pauseAll = useCallback((udids: string[]) => fanout(udids, 'pause', (u) => api.pauseSim(u)), [fanout])
  const resumeAll = useCallback((udids: string[]) => fanout(udids, 'resume', (u) => api.resumeSim(u)), [fanout])
  const stopAll = useCallback((udids: string[]) => fanout(udids, 'stop', (u) => api.stopSim(u)), [fanout])
  const restoreAll = useCallback(async (udids: string[]) => {
    const outcome = await fanout(udids, 'restore', (u) => api.restoreSim(u))
    // Clear per-device runtime state (markers, routes) and legacy state so
    // the map immediately reflects the wipe without waiting for events.
    setRuntimes((prev) => {
      const next: RuntimesMap = { ...prev }
      for (const u of udids) {
        if (next[u]) {
          next[u] = { ...next[u], currentPos: null, destination: null, routePath: [], progress: 0, eta: 0, distanceRemaining: 0, distanceTraveled: 0, waypointIndex: null, state: 'idle' }
        }
      }
      return next
    })
    setCurrentPosition(null)
    setDestination(null)
    setProgress(0)
    setEta(null)
    setWaypoints([])
    setRoutePath([])
    setWaypointProgress(null)
    setLapProgress(null)
    // Keep effectiveSpeed so status bar shows last-applied speed after restore-all.
    return outcome
  }, [fanout])
  const joystickStartAll = useCallback(async (udids: string[]) => {
    await preSyncStart(udids)
    return fanout(udids, 'joystick-start', (u) => api.joystickStart(moveMode, u))
  }, [fanout, preSyncStart, moveMode])
  const joystickStopAll = useCallback((udids: string[]) =>
    fanout(udids, 'joystick-stop', (u) => api.joystickStop(u)), [fanout])

  // Derived: primary runtime for legacy single-device components.
  const primaryRuntime: DeviceRuntime | null = (() => {
    const keys = Object.keys(runtimes)
    return keys.length ? runtimes[keys[0]] : null
  })()
  const anyRunning = Object.values(runtimes).some((r) =>
    r.state && r.state !== 'idle' && r.state !== 'disconnected',
  )

  return {
    runtimes,
    primaryRuntime,
    anyRunning,
    teleportAll,
    goldDittoCycleAll,
    goldDittoCycling,
    navigateAll,
    startLoopAll,
    multiStopAll,
    randomWalkAll,
    applySpeedAll,
    pauseAll,
    resumeAll,
    stopAll,
    restoreAll,
    joystickStartAll,
    joystickStopAll,
    mode,
    setMode,
    moveMode,
    setMoveMode,
    status,
    currentPosition,
    setCurrentPosition,
    destination,
    progress,
    eta,
    waypoints,
    setWaypoints,
    setWaypointTimestamps,
    routePath,
    customSpeedKmh,
    setCustomSpeedKmh,
    speedMinKmh,
    setSpeedMinKmh,
    speedMaxKmh,
    setSpeedMaxKmh,
    straightLine,
    setStraightLine,
    routeEngine,
    setRouteEngine,
    pauseMultiStop,
    setPauseMultiStop,
    pauseLoop,
    setPauseLoop,
    pauseRandomWalk,
    setPauseRandomWalk,
    pauseRemaining,
    ddiMounting,
    ddiStage,
    waypointProgress,
    lapProgress,
    loopLapCount,
    setLoopLapCount,
    jumpMode,
    setJumpMode,
    jumpInterval,
    setJumpInterval,
    effectiveSpeed,
    applySpeed,
    error,
    clearError,
    tunnelReconnecting,
    reconnectInfo,
    lostUdid,
    teleport,
    stop,
    navigate,
    startLoop,
    multiStop,
    randomWalk,
    joystickStart,
    joystickStop,
    pause,
    resume,
    restore,
  }
}
