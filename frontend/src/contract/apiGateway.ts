import * as api from '../services/api'

// The api surface the rest of the app depends on. Using the module's own type
// keeps every existing `api.*` call site valid with zero signature drift.
export type ApiGateway = typeof api
