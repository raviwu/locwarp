import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import { createWsRouter } from './router'
import type { WsRouterImpl } from './router'
import type { WsRouter } from '../../ports/WsRouter'
import { useDevice } from '../../hooks/useDevice'
import { useSimulation } from '../../hooks/useSimulation'
import { useExternalChangeSubscriptions } from '../../hooks/useExternalChangeSubscriptions'
import { useGoldDittoSubscription } from '../../hooks/useGoldDittoSubscription'

// ---------------------------------------------------------------------------
// GAP 2 — WS event-type subscribe-key wiring guard.
//
// contract/wsEvents.ts types WsEvent as `{ type: string } & Record<string,
// unknown>` (intentionally OPEN). So TypeScript does NOT catch a hook that
// renames `subscribe('state_change')` to `subscribe('state_changed')`: the
// string still compiles, but the event then silently never fires.
//
// This test pins the CANONICAL set of event types the BACKEND actually emits
// (the source of truth) and asserts the real subscriber hooks — mounted
// through the real WsRouter — register a handler for every one of them
// (minus an explicit, commented UI-ignored allowlist). A renamed / typo'd
// subscribe key leaves a canonical type uncovered → this test FAILS and names
// the missing type.
//
// Direction matters: the baseline is the BACKEND-EMITTED set, NOT "whatever
// the hooks happen to subscribe" (that would be a tautology). Hooks may also
// subscribe to extra types the backend never sends (e.g. device_reconnected,
// simulation_state, simulation_complete, simulation_error,
// random_walk_pause[_end]) — harmless, and deliberately not asserted here.
// ---------------------------------------------------------------------------

// Every WS `type` the backend emits today, with the emit site for each.
// Grepped from broadcast("…") call-sites and SimulationEngine._emit("…")
// literals across backend/api, backend/core, backend/domain.
const CANONICAL_BACKEND_EVENT_TYPES = [
  // --- api/device.py broadcast() ---
  'device_connected', // api/device.py:58,837,1494 ; main.py:762
  'device_disconnected', // api/device.py:672,1527,1594 ; api/location.py:226 ; main.py:698
  'tunnel_recovered', // api/device.py:832
  'tunnel_degraded', // api/device.py:900
  'tunnel_lost', // api/device.py:996
  'device_error', // api/device.py:1289
  // --- api/cloud_sync.py broadcast() ---
  'bookmarks_changed', // api/cloud_sync.py:115,150
  'routes_changed', // api/cloud_sync.py:116,151
  // --- domain/events.py via DeviceManager._events.publish() ---
  'ddi_mounted', // device_manager.py:724,803 (DdiMountedEvent)
  'ddi_not_mounted', // device_manager.py:736 (DdiNotMountedEvent)
  'ddi_mounting', // device_manager.py:788 (DdiMountingEvent)
  'ddi_mount_failed', // device_manager.py:805 (DdiMountFailedEvent)
  // --- core/simulation_engine.py SimulationEngine._emit() ---
  'position_update', // simulation_engine.py
  'route_path', // simulation_engine.py
  'state_change', // simulation_engine.py
  'navigation_complete', // simulation_engine.py / navigator.py
  'waypoint_progress', // simulation_engine.py
  'pause_countdown', // simulation_engine.py
  'pause_countdown_end', // simulation_engine.py
  // --- movers via engine._emit() ---
  'lap_complete', // core/route_loop.py
  'loop_complete', // core/route_loop.py
  'multi_stop_complete', // core/multi_stop.py
  'stop_reached', // core/multi_stop.py
  'user_waypoint_advance', // core/multi_stop.py / core/route_loop.py
  'connection_lost', // core/random_walk.py:186
  'random_walk_arrived', // core/random_walk.py:222
  'random_walk_complete', // core/random_walk.py:262
  'teleport', // core/teleport.py:37
  'restored', // core/restore.py:47
  // --- core/goldditto.py ---
  'goldditto_cycle', // core/goldditto.py:79,102,109
] as const

// Backend-emitted types that NO hook subscribes to BY DESIGN (purely
// server-side / telemetry / not surfaced in the renderer). Each was confirmed
// to have zero `ws.subscribe('<type>')` call-site in frontend/src. Excluded
// EXPLICITLY (not silently dropped) so that if one ever gains a UI consumer,
// removing it from this list re-arms the subset assertion.
const UI_IGNORED_BY_DESIGN = new Set<string>([
  // tunnel_degraded / tunnel_recovered are now consumed by useSimulation (the
  // three-state WiFi-tunnel indicator: degraded → "reconnecting…", recovered →
  // clear + toast, lost → terminal banner) — so they are REQUIRED, not ignored.
  'device_error', // logged server-side; no renderer banner for it
  'connection_lost', // random-walk internal recovery signal
  'random_walk_arrived', // intermediate mover progress, not surfaced
  'random_walk_complete', // folded into the generic *_complete UI? no — no subscriber
  'stop_reached', // multi-stop intermediate progress, not surfaced
  'user_waypoint_advance', // multi-stop / loop internal advance, not surfaced
  'teleport', // one-shot REST result; UI updates from position_update
  'restored', // restore.py result; UI updates from position_update / state_change
])

// The canonical types we REQUIRE a subscriber for.
const REQUIRED_TYPES = CANONICAL_BACKEND_EVENT_TYPES.filter(
  (t) => !UI_IGNORED_BY_DESIGN.has(t),
)

/**
 * Build a real WsRouter, mount ALL real subscriber hooks through it, and
 * return the set of `type` strings each hook registered via subscribe().
 */
function collectSubscribedTypes(): Set<string> {
  const router = createWsRouter() as WsRouterImpl
  const subscribed = new Set<string>()
  // Wrap the real subscribe so we record every (type) while keeping the real
  // fan-out behavior intact (the hooks' returned unsubscribers still work).
  const recordingRouter: WsRouter = {
    subscribe(type, handler) {
      subscribed.add(type)
      return router.subscribe(type, handler)
    },
  }

  const noop = () => {}
  // Mount each real hook with the real recording router. The subscribe calls
  // happen inside each hook's mount effect.
  renderHook(() => useDevice(recordingRouter))
  renderHook(() => useSimulation(recordingRouter, null))
  renderHook(() =>
    useExternalChangeSubscriptions(recordingRouter, {
      onBookmarks: noop,
      onRoutes: noop,
    }),
  )
  renderHook(() =>
    useGoldDittoSubscription(recordingRouter, {
      t: (k) => String(k),
      showToast: noop,
    }),
  )

  return subscribed
}

describe('WS event-type subscribe wiring', () => {
  it('every backend-emitted event type (minus the UI-ignored allowlist) has a real subscriber', () => {
    const subscribed = collectSubscribedTypes()

    const missing = REQUIRED_TYPES.filter((t) => !subscribed.has(t))

    // If this fails, a hook renamed/typo'd a subscribe key (or stopped
    // subscribing) — the named type is emitted by the backend but nothing
    // in the renderer listens for it anymore.
    expect(
      missing,
      `Backend emits these types but no hook subscribes to them: ${missing.join(', ')}`,
    ).toEqual([])
  })

  it('the canonical set and the allowlist do not overlap (allowlist hygiene)', () => {
    // A type in BOTH the required set and the ignore set would be a
    // contradiction; this keeps the allowlist honest.
    const overlap = [...UI_IGNORED_BY_DESIGN].filter((t) =>
      REQUIRED_TYPES.includes(t as (typeof CANONICAL_BACKEND_EVENT_TYPES)[number]),
    )
    expect(overlap).toEqual([])

    // Every allowlisted type must really be in the canonical backend set —
    // otherwise it's a stale entry hiding a future-removed event.
    const staleAllowlist = [...UI_IGNORED_BY_DESIGN].filter(
      (t) =>
        !CANONICAL_BACKEND_EVENT_TYPES.includes(
          t as (typeof CANONICAL_BACKEND_EVENT_TYPES)[number],
        ),
    )
    expect(
      staleAllowlist,
      `Allowlist entries not present in the canonical backend set: ${staleAllowlist.join(', ')}`,
    ).toEqual([])
  })

  it('POSITIVE CONTROL: the subset check would FAIL if a required key were dropped', () => {
    // Prove the assertion has teeth: simulate a hook that "renamed" its
    // state_change subscription by feeding the same check a subscribed set
    // with that one canonical key removed. The check MUST flag it.
    const real = collectSubscribedTypes()
    expect(real.has('state_change')).toBe(true) // sanity: it's really there

    const broken = new Set(real)
    broken.delete('state_change') // simulate the silent typo/rename
    const missing = REQUIRED_TYPES.filter((t) => !broken.has(t))
    expect(missing).toContain('state_change')
  })
})
