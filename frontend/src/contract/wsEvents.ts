// Typed view of the WS wire frames. The backend sends {"type", "data"} and the
// renderer flattens to a single object keyed by `type` (see adapters/ws/router).
// WsEvent stays intentionally open (Record<string, unknown>) so unknown event
// types still flow through the router untouched.
export type WsEvent = { type: string } & Record<string, unknown>

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
