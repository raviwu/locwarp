import { useState, useCallback, useEffect, useMemo } from 'react'
import type { ApiGateway } from '../contract/apiGateway'
import { HttpError, type CatalogPayload, type CatalogSyncResult } from '../services/api'

// Bundled public-event catalog state, extracted out of App.tsx. Mirrors the
// useRoutes/useBookmarks `useX(api)` shape — the backend `api` is injected (App
// sources it from useServices()) so the hook never imports services/api for I/O.
// HttpError is imported as a runtime VALUE (it's an error class needed for the
// 404-vs-failure status classification); CatalogPayload / CatalogSyncResult are
// TYPE-ONLY. No other services/api edge is introduced.
//
// The catalog is fetched once on mount. `catalogNewCount` diffs the catalog
// against the current bookmarks (passed in from useBookmarks) so the Library
// header can show how many seed entries are not yet imported. `refresh` runs the
// authoritative force-sync (api.syncCatalog) behind a re-entrancy guard.
//
// Toasts + i18n + the post-sync bookmark refresh stay in App: `refresh` returns
// the sync result and throws on failure so App keeps full control over the
// user-facing messaging + the bm.refresh() that previously wrapped this call —
// matching the useRoutes convention.
type CatalogStatus = 'loading' | 'ok' | 'missing' | 'failed'

export function useCatalog(api: ApiGateway, bookmarks: Array<{ id: string }>) {
  const [catalog, setCatalog] = useState<CatalogPayload | null>(null)
  const [catalogStatus, setCatalogStatus] = useState<CatalogStatus>('loading')
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [catalogRefreshing, setCatalogRefreshing] = useState(false)

  const fetchCatalog = useCallback(async () => {
    try {
      const data = await api.getCatalog()
      setCatalog(data)
      setCatalogStatus('ok')
      setCatalogError(null)
    } catch (err: unknown) {
      setCatalog(null)
      const status = err instanceof HttpError ? err.status : 0
      if (status === 404) {
        setCatalogStatus('missing')
      } else {
        setCatalogStatus('failed')
        setCatalogError(err instanceof Error ? err.message : 'unknown')
      }
    }
  }, [api])

  // Fetch once on mount.
  useEffect(() => {
    void fetchCatalog()
  }, [fetchCatalog])

  const catalogNewCount = useMemo(() => {
    if (!catalog) return 0
    const existingIds = new Set(bookmarks.map((b) => b.id))
    return catalog.bookmarks.filter((cb) => !existingIds.has(cb.id)).length
  }, [catalog, bookmarks])

  // Force-sync — catalog ids are authoritative. Resurrects entries the user
  // previously deleted from a catalog-seeded category and propagates any
  // lat/lng/name corrections from the bundled file. Returns the result so App
  // can toast; throws on failure so App can toast the error. No-op (returns null)
  // while there is no catalog loaded OR a sync is already in flight — same guard
  // the inline App handler used.
  const refresh = useCallback(async (): Promise<CatalogSyncResult | null> => {
    if (!catalog || catalogRefreshing) return null
    setCatalogRefreshing(true)
    try {
      const res = await api.syncCatalog()
      return res
    } finally {
      setCatalogRefreshing(false)
    }
  }, [api, catalog, catalogRefreshing])

  return {
    catalog,
    catalogStatus,
    catalogError,
    catalogNewCount,
    catalogRefreshing,
    refresh,
  }
}
