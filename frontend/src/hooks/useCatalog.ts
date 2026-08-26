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
// header can show how many seed entries are not yet imported. `catalogDivergedCount`
// diffs the same pair the other direction: existing bookmarks whose id IS already
// in the catalog but whose name/lat/lng/category_id/address has drifted from the
// bundled value — the five fields the backend's three-way merge arbitrates
// (domain/catalog_merge.py::BOOKMARK_MERGE_FIELDS). It means "differs from the
// catalog", NOT "will be kept": the merge is relative to a local baseline this
// side cannot see, so a diverged record may equally take the catalog's value.
// `refresh` runs the authoritative force-sync (api.syncCatalog) behind
// a re-entrancy guard.
//
// Toasts + i18n + the post-sync bookmark refresh stay in App: `refresh` returns
// the sync result and throws on failure so App keeps full control over the
// user-facing messaging + the bm.refresh() that previously wrapped this call —
// matching the useRoutes convention.
type CatalogStatus = 'loading' | 'ok' | 'missing' | 'failed'

// Mirrors backend domain/coords.py::round_coord (COORD_PRECISION = 7) so a
// bookmark that only differs from the catalog past the store's own rounding
// precision isn't reported as locally-edited.
const COORD_PRECISION = 7
const roundCoord = (v: number) => Math.round(v * 10 ** COORD_PRECISION) / 10 ** COORD_PRECISION

interface CatalogDiffBookmark {
  id: string;
  name?: string;
  lat?: number;
  lng?: number;
  category_id?: string;
  address?: string;
}

export function useCatalog(api: ApiGateway, bookmarks: Array<CatalogDiffBookmark>) {
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

  // Existing bookmarks that differ from the bundled catalog: id already present
  // in the catalog AND one of the five merged fields (name/lat/lng/category_id/
  // address) has diverged. Coordinates are compared at the store's own rounding
  // precision (roundCoord) so float noise below that precision never counts as
  // a local edit; `address` is optional on CatalogBookmark and defaults to ""
  // on the backend Bookmark model, so both sides default a missing value to ""
  // — a catalog entry that omits address must not read as diverged from an
  // existing blank one.
  //
  // The flag code is deliberately NOT compared. E1 leaves it (and its siblings
  // timezone/city/region) to the offline geo resolver, which re-derives them
  // from whichever coordinates survive the merge, so a flag-only divergence is
  // not something the user's version survives — counting it would promise
  // durability the backend does not provide.
  const catalogDivergedCount = useMemo(() => {
    if (!catalog) return 0
    const byId = new Map(bookmarks.map((b) => [b.id, b]))
    let count = 0
    for (const cb of catalog.bookmarks) {
      const existing = byId.get(cb.id)
      if (!existing) continue
      const diverged =
        existing.name !== cb.name ||
        (existing.lat === undefined ? true : roundCoord(existing.lat) !== roundCoord(cb.lat)) ||
        (existing.lng === undefined ? true : roundCoord(existing.lng) !== roundCoord(cb.lng)) ||
        (existing.category_id ?? '') !== cb.category_id ||
        (existing.address ?? '') !== (cb.address ?? '')
      if (diverged) count++
    }
    return count
  }, [catalog, bookmarks])

  // Force-sync — catalog ids are authoritative. Resurrects entries the user
  // previously deleted from a catalog-seeded category and propagates any
  // lat/lng/name correction the user has not overridden locally. Returns the result so App
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
    catalogDivergedCount,
    catalogRefreshing,
    refresh,
  }
}
