// Typed view of the WS wire frames. The backend sends {"type", "data"} and the
// renderer flattens to a single object keyed by `type` (see adapters/ws/router).
// WsEvent stays intentionally open (Record<string, unknown>) so unknown event
// types still flow through the router untouched.
export type WsEvent = { type: string } & Record<string, unknown>

// The REAL backend event vocabulary the renderer may subscribe to. Source of
// truth: every broadcast("…") / DeviceManager._events.publish(("…", …)) /
// SimulationEngine._emit("…") literal across backend/api, backend/core,
// backend/domain. Kept in lockstep with the canonical list in
// adapters/ws/eventWiring.test.tsx and contract/wsEvents.test.ts.
// NOTE: this is a typing/lint seam, not codegen — update by hand when the
// backend gains or drops an emitted type.
export const WS_EVENT_TYPES = [
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

// String-literal union of the backend vocabulary. subscribe() is typed with
// this so a typo'd key (e.g. 'state_changed') is now a COMPILE error.
export type WsEventType = (typeof WS_EVENT_TYPES)[number]

// device_disconnected is the ONE message two hooks read with divergent shapes.
// `udid` / `udids` feed useDevice; `remaining_count` feeds the useSimulation
// banner (absent → treated as 0 → banner shows). All payload keys optional
// because the backend omits absent keys (exclude_unset/exclude_none).
export interface DeviceDisconnectedEvent {
  type: 'device_disconnected'
  udid?: string
  udids?: string[]
  reason?: string
  remaining_count?: number
}

// connect_progress — coarse phases of the iOS connect path (WiFi-tunnel RSD
// loop, then DDI check + DVT open). Streamed so a slow connect is
// distinguishable from a hang. udid is absent during the RSD loop (device
// identity is only known after rsd.connect() succeeds). attempt/max are
// present only on the 'rsd_attempt' phase. All optional keys are omitted by
// the backend (exclude_unset/exclude_none).
export interface ConnectProgressEvent {
  type: 'connect_progress'
  udid?: string
  phase: 'opening_tunnel' | 'rsd_attempt' | 'checking_ddi' | 'opening_dvt' | 'connected'
  attempt?: number
  max?: number
}
