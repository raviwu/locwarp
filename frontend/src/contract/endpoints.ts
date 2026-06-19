import { HTTP_ORIGIN, WS_ORIGIN } from '../adapters/config'

// Derived from adapters/config.ts — the single origin source. Never reintroduce
// a literal host:port here.
export const BASE_URL = HTTP_ORIGIN
export const WS_URL = `${WS_ORIGIN}/ws/status`
