import { describe, it, expect } from 'vitest'
import { WS_EVENT_TYPES } from './wsEvents'
import type { WsEventType } from './wsEvents'

// The single source of truth for what the backend emits also lives in the
// wiring guard (adapters/ws/eventWiring.test.tsx CANONICAL_BACKEND_EVENT_TYPES).
// We re-pin the same literal list here so the typed union can never silently
// diverge from the canonical backend vocabulary. (These three lists are
// hand-maintained — keep them in lockstep; no codegen, by design.)
const CANONICAL_BACKEND_EVENT_TYPES = [
  'device_connected', 'device_disconnected', 'tunnel_recovered',
  'tunnel_degraded', 'tunnel_lost', 'device_error',
  'bookmarks_changed', 'routes_changed',
  'ddi_mounted', 'ddi_not_mounted', 'ddi_mounting', 'ddi_mount_failed',
  'position_update', 'route_path', 'state_change', 'navigation_complete',
  'waypoint_progress', 'pause_countdown', 'pause_countdown_end',
  'lap_complete', 'loop_complete', 'multi_stop_complete', 'stop_reached',
  'user_waypoint_advance', 'connection_lost', 'random_walk_arrived',
  'random_walk_complete', 'teleport', 'restored', 'goldditto_cycle',
  'connect_progress',
] as const

describe('WsEventType union', () => {
  it('WS_EVENT_TYPES is exactly the canonical backend-emitted vocabulary', () => {
    expect([...WS_EVENT_TYPES].sort()).toEqual(
      [...CANONICAL_BACKEND_EVENT_TYPES].sort(),
    )
  })

  it('every WS_EVENT_TYPES entry is assignable to WsEventType', () => {
    // Compile-time guard expressed at runtime: each entry typed as WsEventType.
    const typed: WsEventType[] = [...WS_EVENT_TYPES]
    expect(typed.length).toBe(WS_EVENT_TYPES.length)
  })
})
