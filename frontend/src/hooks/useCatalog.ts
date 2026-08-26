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
// header can show how many seed entries are not yet imported. `catalogOverwriteCount`
// diffs the same pair the other direction: existing bookmarks whose id IS already
// in the catalog but whose name/lat/lng/category_id/address/country_code has
// drifted from the bundled value — i.e. every field backend/services/bookmarks.py
// _upsert_items overwrites on an update, so what a force-sync would silently
// clobber. `refresh` runs the authoritative force-sync (api.syncCatalog) behind
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
  country_code?: string;
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

  // Existing bookmarks a force-sync would overwrite: id already present in the
  // catalog AND any field backend _upsert_items overwrites on update
  // (name/lat/lng/category_id/address/country_code) has diverged from the
  // bundled value. Coordinates are compared at the store's own rounding
  // precision (roundCoord) so float noise below that precision never counts
  // as a local edit.
  //
  // Normalisation for the two fields that are optional on CatalogBookmark:
  // - address defaults to "" on the backend Bookmark model (models/schemas.py)
  //   and is never otherwise normalised, so both sides default a missing
  //   value to "" before comparing — a catalog entry that omits address must
  //   not be flagged as diverged from an existing blank address.
  // - country_code is canonicalised to lowercase once, at create time only
  //   (services/bookmarks.py::create_bookmark does country_code.lower(); the
  //   force-sync upsert itself does a bare assignment with no re-lowering).
  //   The bundled catalog's own values are already lowercase. Comparing
  //   case-insensitively (plus the same "" default) matches what the backend
  //   treats as the same code, so a bookmark whose code differs only in case
  //   isn't reported as a local edit that force-sync would clobber.
  const catalogOverwriteCount = useMemo(() => {
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
        (existing.address ?? '') !== (cb.address ?? '') ||
        (existing.country_code ?? '').toLowerCase() !== (cb.country_code ?? '').toLowerCase()
      if (diverged) count++
    }
    return count
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
    catalogOverwriteCount,
    catalogRefreshing,
    refresh,
  }
}
