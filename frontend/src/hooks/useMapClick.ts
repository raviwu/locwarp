import { useCallback, useEffect, useRef, useState } from 'react'
import type { ApiGateway } from '../contract/apiGateway'
import { SimMode } from './useSimulation'

// ─────────────────────────────────────────────────────────────────────────────
// useMapClick — the map left-click handler + the insert-after-waypoint mode it
// shares, lifted VERBATIM out of App.tsx (Phase 4b, task p4b1). Pinned by
// App.dangerzone.test.tsx tests 13-15 ("handleMapClick modes") plus the
// supplementary useMapClick.test.tsx — behavior is FROZEN, no changes.
//
// THREE BRANCHES, exactly as App had them:
//   1. insert-after mode (insertAfterIndex !== null) → splice a waypoint after
//      the chosen index + a one-shot live-insert api.insertWaypoint fan-out when
//      a Loop/MultiStop is running, then clear the mode. THIS BRANCH IS DEAD FROM
//      THE UI today: App defines handleInsertAfterWp (returned here for parity)
//      but NEVER wires onInsertAfterWp onto <MapView>, so insert mode can't be
//      armed and the splice/fan-out is unreachable. test 13 pins that reality.
//      The branch is moved verbatim and stays UNwired — reviving it (passing
//      onInsertAfterWp through) would be a behavior change.
//   2. click-to-add toggle ON + Loop/MultiStop → append a waypoint (seeding the
//      current position as index 0 on the first add). normalizeLng/clampLat are
//      applied at the handler entry exactly where App applied them. test 14.
//   3. default (no insert armed, toggle OFF) → pure NO-OP; teleport/preview live
//      on the right-click menu (onTeleport/onCoordPreview), NOT onMapClick.
//      test 15.
//
// The ESC-cancels-insert-mode keydown listener travels with this code (the same
// effect App registered) — armed only while insertAfterIndex !== null.
//
// `clampLat` / `normalizeLng` are taken as args (owned by App, shared with the
// handlers that stay there) so there is exactly one source of truth — mirroring
// useSimActions. `api` is taken as an injected arg (type-only import of
// ApiGateway, erased at build) so the dead branch's api.insertWaypoint fan-out
// keeps working without this hook importing services/api directly.
// ─────────────────────────────────────────────────────────────────────────────

// Loose structural types mirroring the runtime shapes App passes — match the
// surfaces of useSimulation()/useDevice() without re-declaring their full
// interfaces (parity with useSimActions).
type Sim = any
type Device = {
  connectedDevices: { udid: string }[]
}

export interface UseMapClickArgs {
  sim: Sim
  device: Device
  // Injected so the dead insert-after branch's live-insert fan-out
  // (api.insertWaypoint) keeps working; type-only import keeps the hook inside
  // the hexagon-lite gate.
  api: ApiGateway
  clickToAddWaypoint: boolean
  // The canonical coordinate normalisers, owned by App (shared with the
  // handlers that stay there) so there is exactly one source of truth.
  clampLat: (lat: number) => number
  normalizeLng: (lng: number) => number
}

export function useMapClick(args: UseMapClickArgs) {
  const { api, clickToAddWaypoint, clampLat, normalizeLng } = args
  // Mirror the FRESH-every-render sim/device objects into refs so handleMapClick
  // can drop them from its dep array (keeping only the behavior-gating
  // clickToAddWaypoint + insertAfterIndex), giving it a stable identity across
  // position ticks. It only reads sim/device when it FIRES (a user map click),
  // at which point the refs hold the latest value — behaviorally identical to
  // closing over sim/device. Same ref-mirror technique as useSimActions (N1).
  const simRef = useRef(args.sim)
  simRef.current = args.sim
  const deviceRef = useRef(args.device)
  deviceRef.current = args.device

  // Insert-after-waypoint mode: when set, the next map click drops a new
  // waypoint immediately AFTER the chosen index instead of appending to
  // the end. Activated from the waypoint left-click menu (map) or the
  // fly-confirm dialog (left side). Cleared by ESC, by clicking the
  // banner's cancel, or after one successful insert.
  const [insertAfterIndex, setInsertAfterIndex] = useState<number | null>(null)
  const handleInsertAfterWp = useCallback((index: number) => {
    setInsertAfterIndex(index)
  }, [])
  const cancelInsertMode = useCallback(() => setInsertAfterIndex(null), [])

  // ESC cancels insert mode anywhere in the app — same affordance as
  // every dialog.
  useEffect(() => {
    if (insertAfterIndex === null) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setInsertAfterIndex(null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [insertAfterIndex])

  // -- Map handlers --
  const handleMapClick = useCallback((lat: number, lng: number) => {
    const sim = simRef.current
    const device = deviceRef.current
    const nlat = clampLat(lat)
    const nlng = normalizeLng(lng)
    // Priority 1: insert-after mode. One-shot — clears itself after the
    // splice so the next plain click goes back to the default behaviour
    // (no-op or click-to-add-waypoint, depending on the toggle).
    if (insertAfterIndex !== null) {
      const idx = insertAfterIndex
      // Always update the local list immediately so the UI shows the
      // new waypoint without waiting for the backend round-trip.
      sim.setWaypoints((prev: any[]) => {
        const safeIdx = Math.min(Math.max(idx, 0), prev.length - 1)
        const target = safeIdx + 1
        const next = [...prev]
        next.splice(target, 0, { lat: nlat, lng: nlng })
        return next
      })
      // If a multi-stop / loop is currently running, also push the
      // splice into every connected device's engine so each iPhone
      // walks the new waypoint as part of the active route (no need
      // to Stop+Start). When inserted in a future leg the device
      // continues to that leg and visits the new wp in line; when
      // inserted in a past / current leg the new wp is recorded for
      // the route list but the iPhone keeps walking forward without
      // backtracking. See SimulationEngine.live_insert_waypoint.
      const isRouteMode = sim.mode === SimMode.Loop || sim.mode === SimMode.MultiStop
      if (isRouteMode && sim.status?.running) {
        const udids = device.connectedDevices.map((d) => d.udid)
        if (udids.length > 0) {
          void Promise.allSettled(
            udids.map((u) => api.insertWaypoint(idx, nlat, nlng, u)),
          )
        } else {
          void api.insertWaypoint(idx, nlat, nlng).catch(() => {})
        }
      }
      setInsertAfterIndex(null)
      return
    }
    // When the "left-click to add waypoint" toggle is on AND we're in a
    // waypoint-based mode, append to the waypoint list. Otherwise a map
    // click is a no-op (teleport / navigate live on right-click menu).
    if (!clickToAddWaypoint) return
    if (sim.mode !== SimMode.Loop && sim.mode !== SimMode.MultiStop) return
    sim.setWaypoints((prev: any[]) => {
      if (prev.length === 0 && sim.currentPosition) {
        return [
          { lat: sim.currentPosition.lat, lng: sim.currentPosition.lng },
          { lat: nlat, lng: nlng },
        ]
      }
      return [...prev, { lat: nlat, lng: nlng }]
    })
    // Deps are the two BEHAVIOR-GATING values only (clickToAddWaypoint +
    // insertAfterIndex); sim/device are read via refs so this handler keeps a
    // stable identity across position ticks (those gates only change on user
    // action). clampLat / normalizeLng / api remain unlisted (pure / stable),
    // matching the original referential stability.
  }, [clickToAddWaypoint, insertAfterIndex])

  return {
    insertAfterIndex,
    setInsertAfterIndex,
    handleInsertAfterWp,
    cancelInsertMode,
    handleMapClick,
  }
}
