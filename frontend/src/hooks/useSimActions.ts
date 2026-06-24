import { useCallback, useRef } from 'react'
import type { ApiGateway } from '../contract/apiGateway'
import { SimMode } from './useSimulation'
import { toastForFanout } from '../utils/toast'
import type { RecentKind } from '../services/api'

// ─────────────────────────────────────────────────────────────────────────────
// useSimActions — the simulation-action fan-out handlers, lifted verbatim out of
// App.tsx (Phase 4b, task p4b1). These are the start / stop / pause / resume /
// teleport / navigate / applySpeed / restore / startWaypointRoute handlers that
// share the single-vs-dual-device branch:
//
//     const udids = device.connectedDevices.map(d => d.udid)
//     if (udids.length >= 2) { const outcome = await sim.<x>All(udids, …);
//                              showToast(toastForFanout(t, <action>, outcome, …)) }
//     else                   { sim.<x>(…) }   // single — udid omitted
//
// Consolidating the dual-device branch in ONE tested place is the whole point of
// the extraction. The handlers only call `sim.*` + `showToast`/`t`/`pushRecent`;
// none reach `api.*` directly, so this hook stays inside the hexagon-lite gate
// (it imports no services/api — `api` is taken as an injected arg for parity with
// the sibling hooks and possible future use, and `ApiGateway` is a TYPE-ONLY
// import that is erased at build).
//
// PRESERVED NUANCES (each pinned by App.dangerzone.test.tsx — do NOT alter):
//   1. `udids.length >= 2` → `*All` + showToast(toastForFanout(...)); single
//      device → single variant with the udid OMITTED.
//   2. handleStop's dual path uses the LITERAL action string 'stop' (yielding
//      "stop started on all devices"), NOT a t() key; handlePause/handleResume
//      likewise pass the literal 'pause' / 'resume'.
//   3. handleStop's Joystick-dual case fans out joystickStopAll and returns
//      early before the generic stopAll branch.
//   4. handleStart only acts in Joystick / RandomWalk / Loop / MultiStop; the
//      default Teleport mode is a no-op (no api call) — the mode gate.
//   5. clampLat / normalizeLng are applied exactly where App applied them; they
//      are passed in (not re-derived) so they stay the single source of truth
//      shared with the handlers that remain in App.
//
// NOTE: the route-into-sim go-around-teleport handlers (submitRoutePaste /
// confirmRouteLoad / confirmWpFly / handleSetWpAsStart) deliberately STAY in
// App — they are coupled to App-local dialog state (routePasteText, wpFlyConfirm,
// routeLoadConfirm, …) and use the distinct `udids.length > 0 → sim.teleportAll`
// bypass, not the `>= 2` dual branch this hook owns. Moving them would mean
// threading 7+ dialog setters through here for no consolidation gain.
// ─────────────────────────────────────────────────────────────────────────────

// Structural types kept loose to mirror the runtime shapes App passes — these
// match the surfaces of useSimulation()/useDevice()/useRecentPlaces()/i18n
// without re-declaring their full interfaces (which would couple this hook to
// implementation detail it doesn't use).
type Sim = any
type Device = {
  connectedDevices: { udid: string }[]
}
type ShowToast = (msg: string, durationMs?: number) => void
type T = (k: any, v?: Record<string, string | number>) => string
type PushRecent = (lat: number, lng: number, kind: RecentKind, name?: string) => Promise<void> | void

export interface UseSimActionsArgs {
  sim: Sim
  device: Device
  showToast: ShowToast
  t: T
  pushRecent: PushRecent
  // Injected for hexagon-lite parity with the sibling hooks; the fan-out
  // handlers route through `sim.*` so they don't currently touch it.
  api: ApiGateway
  randomWalkRadius: number
  // The canonical coordinate normalisers, owned by App (shared with the
  // handlers that stay there) so there is exactly one source of truth.
  clampLat: (lat: number) => number
  normalizeLng: (lng: number) => number
  // App-level side effects the handlers fire (preview-pin clear on teleport /
  // navigate). Passed in so the hook doesn't own that App-local state.
  setPreviewPin: (v: { lat: number; lng: number } | null) => void
}

export function useSimActions(args: UseSimActionsArgs) {
  // ── Ref-mirror stabilisation (N1) ──────────────────────────────────────────
  // `sim`/`device` are the RAW return objects of useSimulation()/useDevice() —
  // FRESH object literals on every App render (a position_update tick allocates
  // a new sim object each frame). If the handler useCallbacks key on [sim,
  // device, …], their refs change every render, so the React.memo'd ControlPanel
  // / MapView (which receive ~8 of these handlers) fail their shallow prop-
  // compare and commit every frame — the N1 memoization becomes a no-op.
  //
  // Fix: mirror every input into a ref updated on each render (plain assignment,
  // same technique as `connectedDevicesRef` in useWifiAutoConnect — the ref
  // ALWAYS holds the latest value, so there is no stale-closure risk). Each
  // handler reads `*Ref.current` and is keyed on `[]`, giving it ONE stable
  // identity for the app's lifetime. Every handler fires on a USER ACTION
  // (button press / map click), at which point the refs already hold the latest
  // sim/device/showToast/t/etc., so behavior is IDENTICAL to keying on [sim,
  // device, …]. No useEffect anywhere depends on these handler identities (they
  // are passed as event-handler props, not effect deps), so freezing them is
  // safe.
  const simRef = useRef(args.sim)
  simRef.current = args.sim
  const deviceRef = useRef(args.device)
  deviceRef.current = args.device
  const showToastRef = useRef(args.showToast)
  showToastRef.current = args.showToast
  const tRef = useRef(args.t)
  tRef.current = args.t
  const pushRecentRef = useRef(args.pushRecent)
  pushRecentRef.current = args.pushRecent
  const randomWalkRadiusRef = useRef(args.randomWalkRadius)
  randomWalkRadiusRef.current = args.randomWalkRadius
  const clampLatRef = useRef(args.clampLat)
  clampLatRef.current = args.clampLat
  const normalizeLngRef = useRef(args.normalizeLng)
  normalizeLngRef.current = args.normalizeLng
  const setPreviewPinRef = useRef(args.setPreviewPin)
  setPreviewPinRef.current = args.setPreviewPin

  const handleRestore = useCallback(async () => {
    const sim = simRef.current
    const device = deviceRef.current
    const showToast = showToastRef.current
    const t = tRef.current
    // The backend stop + DVT clear can take a few seconds, especially if
    // movement was active or the channel is flaky. Give the user a visible
    // "working on it" toast up front so the UI doesn't feel frozen.
    showToast(t('status.restore_in_progress'), 10000)
    const startedAt = Date.now()
    try {
      // Group mode: fan out restore to every connected device; fall back to
      // the legacy single-engine restore when no devices are tracked yet.
      const udids = device.connectedDevices.map((d) => d.udid)
      if (udids.length >= 2) {
        const outcome = await sim.restoreAll(udids)
        if (outcome.failed.length > 0 && outcome.ok.length === 0) {
          throw new Error(outcome.failed[0]?.reason ?? 'restore failed')
        }
      } else {
        await sim.restore()
      }
      // Keep the in-progress toast visible for at least 1.2 s — otherwise a
      // fast restore (sub-second) would overwrite it before the user even
      // noticed it appeared.
      const elapsed = Date.now() - startedAt
      if (elapsed < 1200) {
        await new Promise((r) => setTimeout(r, 1200 - elapsed))
      }
      showToast(t('status.restore_success_wait'))
    } catch {
      showToast(t('status.restore_failed'))
    }
  }, [])

  const handleTeleport = useCallback(async (latIn: number, lngIn: number, source: 'menu' | 'coord' = 'menu') => {
    const sim = simRef.current
    const device = deviceRef.current
    const showToast = showToastRef.current
    const t = tRef.current
    const pushRecent = pushRecentRef.current
    const lat = clampLatRef.current(latIn)
    const lng = normalizeLngRef.current(lngIn)
    setPreviewPinRef.current(null)
    const udids = device.connectedDevices.map((d) => d.udid)
    if (udids.length >= 2) {
      const prevPos = sim.currentPosition
      sim.setCurrentPosition({ lat, lng })
      const outcome = await sim.teleportAll(udids, lat, lng)
      // Total failure: the marker jumped but no device actually moved —
      // revert so the map doesn't lie. Partial / full success keeps the
      // optimistic position (dual pre-sync wants both phones co-located).
      if (outcome.ok.length === 0 && outcome.failed.length > 0) {
        sim.setCurrentPosition(prevPos ?? null)
      }
      showToast(toastForFanout(t, t('mode.teleport'), outcome, device.connectedDevices))
    } else {
      try {
        await sim.teleport(lat, lng)
      } catch {
        showToast(t('toast.teleport_failed'))
        return
      }
    }
    void pushRecent(lat, lng, source === 'coord' ? 'coord_teleport' : 'teleport')
    // [] deps: every value is read from a ref that holds the latest render's
    // value, so this handler has ONE stable identity yet always acts on the
    // current sim/device — behaviorally identical to keying on [sim, device, …].
  }, [])

  const handleNavigate = useCallback(async (latIn: number, lngIn: number, source: 'menu' | 'coord' = 'menu') => {
    const sim = simRef.current
    const device = deviceRef.current
    const showToast = showToastRef.current
    const t = tRef.current
    const pushRecent = pushRecentRef.current
    const lat = clampLatRef.current(latIn)
    const lng = normalizeLngRef.current(lngIn)
    setPreviewPinRef.current(null)
    const udids = device.connectedDevices.map((d) => d.udid)
    if (udids.length >= 2) {
      const outcome = await sim.navigateAll(udids, lat, lng)
      showToast(toastForFanout(t, t('mode.navigate'), outcome, device.connectedDevices))
    } else {
      try {
        await sim.navigate(lat, lng)
      } catch {
        showToast(t('toast.navigate_failed'))
        return
      }
    }
    void pushRecent(lat, lng, source === 'coord' ? 'coord_navigate' : 'navigate')
    // [] deps via refs (see handleTeleport).
  }, [])

  const handleStartWaypointRoute = useCallback(async () => {
    const sim = simRef.current
    const device = deviceRef.current
    const showToast = showToastRef.current
    const t = tRef.current
    // UI waypoint list already includes the current position as index 0
    // (see handleAddWaypoint / generateWaypoints), so just hand it straight
    // to the backend. No more prepend-on-start, no more accidental re-inject
    // on repeated clicks.
    const route = sim.waypoints
    if (route.length < 2) {
      showToast(t('toast.no_waypoints'))
      return
    }
    const udids = device.connectedDevices.map((d) => d.udid)
    if (sim.mode === SimMode.Loop) {
      if (udids.length >= 2) {
        const outcome = await sim.startLoopAll(udids, route)
        showToast(toastForFanout(t, t('mode.loop'), outcome, device.connectedDevices))
      } else {
        sim.startLoop(route)
      }
    } else if (sim.mode === SimMode.MultiStop) {
      if (udids.length >= 2) {
        const outcome = await sim.multiStopAll(udids, route, 0, false)
        showToast(toastForFanout(t, t('mode.multi_stop'), outcome, device.connectedDevices))
      } else {
        sim.multiStop(route, 0, false)
      }
    }
  }, [])
  // Mirror so handleStart can call the latest handleStartWaypointRoute without
  // listing it as a dep (it's already []-stable, but routing through the ref
  // keeps the pattern uniform and future-proof).
  const handleStartWaypointRouteRef = useRef(handleStartWaypointRoute)
  handleStartWaypointRouteRef.current = handleStartWaypointRoute

  const handleStart = useCallback(async () => {
    const sim = simRef.current
    const device = deviceRef.current
    const showToast = showToastRef.current
    const t = tRef.current
    const randomWalkRadius = randomWalkRadiusRef.current
    const udids = device.connectedDevices.map((d) => d.udid)
    if (sim.mode === SimMode.Joystick) {
      if (!sim.currentPosition) {
        showToast(t('toast.no_position_random'))
        return
      }
      if (udids.length >= 2) {
        const outcome = await sim.joystickStartAll(udids)
        showToast(toastForFanout(t, t('mode.joystick'), outcome, device.connectedDevices))
      } else {
        sim.joystickStart()
      }
    } else if (sim.mode === SimMode.RandomWalk) {
      if (!sim.currentPosition) {
        showToast(t('toast.no_position_random'))
        return
      }
      if (udids.length >= 2) {
        const outcome = await sim.randomWalkAll(udids, sim.currentPosition, randomWalkRadius)
        showToast(toastForFanout(t, t('mode.random_walk'), outcome, device.connectedDevices))
      } else {
        sim.randomWalk(sim.currentPosition, randomWalkRadius)
      }
    } else if (sim.mode === SimMode.Loop || sim.mode === SimMode.MultiStop) {
      handleStartWaypointRouteRef.current()
    }
  }, [])

  const handleStop = useCallback(async () => {
    const sim = simRef.current
    const device = deviceRef.current
    const showToast = showToastRef.current
    const t = tRef.current
    // Stop the active movement only — keep the simulated location in place
    // so the device stays where the user paused it. Use the 一鍵還原 button
    // separately to clear the simulated location and restore real GPS.
    const udids = device.connectedDevices.map((d) => d.udid)
    if (sim.mode === SimMode.Joystick && udids.length >= 2) {
      const outcome = await sim.joystickStopAll(udids)
      showToast(toastForFanout(t, t('mode.joystick'), outcome, device.connectedDevices))
      return
    }
    if (udids.length >= 2) {
      const outcome = await sim.stopAll(udids)
      showToast(toastForFanout(t, 'stop', outcome, device.connectedDevices))
    } else {
      sim.stop()
    }
  }, [])

  const handleApplySpeed = useCallback(async () => {
    const sim = simRef.current
    const device = deviceRef.current
    const showToast = showToastRef.current
    const t = tRef.current
    const udids = device.connectedDevices.map((d) => d.udid)
    try {
      if (udids.length >= 2) {
        const outcome = await sim.applySpeedAll(udids)
        showToast(toastForFanout(t, t('panel.apply_speed_success'), outcome, device.connectedDevices))
      } else {
        await sim.applySpeed()
        showToast(t('panel.apply_speed_success'))
      }
    } catch (err: any) {
      showToast(t('panel.apply_speed_failed') + (err?.message ? `: ${err.message}` : ''))
    }
  }, [])

  const handlePause = useCallback(async () => {
    const sim = simRef.current
    const device = deviceRef.current
    const showToast = showToastRef.current
    const t = tRef.current
    const udids = device.connectedDevices.map((d) => d.udid)
    if (udids.length >= 2) {
      const outcome = await sim.pauseAll(udids)
      showToast(toastForFanout(t, 'pause', outcome, device.connectedDevices))
    } else {
      sim.pause()
    }
  }, [])

  const handleResume = useCallback(async () => {
    const sim = simRef.current
    const device = deviceRef.current
    const showToast = showToastRef.current
    const t = tRef.current
    const udids = device.connectedDevices.map((d) => d.udid)
    if (udids.length >= 2) {
      const outcome = await sim.resumeAll(udids)
      showToast(toastForFanout(t, 'resume', outcome, device.connectedDevices))
    } else {
      sim.resume()
    }
  }, [])

  return {
    handleRestore,
    handleTeleport,
    handleNavigate,
    handleStartWaypointRoute,
    handleStart,
    handleStop,
    handleApplySpeed,
    handlePause,
    handleResume,
  }
}
