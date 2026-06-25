import * as api from '../services/api'

// The api surface the rest of the app depends on. Using the module's own type
// keeps every existing `api.*` call site valid with zero signature drift.
export type ApiGateway = typeof api

// Re-export domain types so view components can import from the contract
// layer instead of directly from services/api (hexagon-lite: views must not
// cross the adapter boundary).
export type { BookmarkExportFormat, TunnelInfo, CloudSyncStatus, NearbyPoi } from '../services/api'
