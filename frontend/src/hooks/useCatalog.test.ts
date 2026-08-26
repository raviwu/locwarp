import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import type { ApiGateway } from '../contract/apiGateway'
import { HttpError } from '../services/api'
import { useCatalog } from './useCatalog'

// Stub the catalog surface. getCatalog returns `current()` so a test can decide
// what the bundled file contains; syncCatalog returns a fixed result.
function makeStubApi() {
  let catalog: any = { categories: [], bookmarks: [] }
  const stub = {
    getCatalog: vi.fn(async () => catalog),
    syncCatalog: vi.fn(async () => ({ added: 2, updated: 1, resurrected: 0, kept_local: 0, conflicts: 0 })),
  }
  return {
    api: stub as unknown as ApiGateway,
    stub,
    setCatalog: (c: any) => { catalog = c },
  }
}

describe('useCatalog', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('fetches the catalog on mount and reports ok', async () => {
    const { api, stub, setCatalog } = makeStubApi()
    setCatalog({ categories: [], bookmarks: [{ id: 'seed-1' }] })
    const { result } = renderHook(() => useCatalog(api, []))
    await waitFor(() => expect(result.current.catalogStatus).toBe('ok'))
    expect(stub.getCatalog).toHaveBeenCalledTimes(1)
    expect(result.current.catalog?.bookmarks).toHaveLength(1)
  })

  it('catalogNewCount counts catalog ids missing from the current bookmarks', async () => {
    const { api, setCatalog } = makeStubApi()
    setCatalog({
      categories: [],
      bookmarks: [{ id: 'seed-1' }, { id: 'seed-2' }, { id: 'seed-3' }],
    })
    // seed-2 already imported locally; seed-1 + seed-3 are new.
    const bookmarks = [{ id: 'seed-2' }, { id: 'local-x' }]
    const { result } = renderHook(() => useCatalog(api, bookmarks))
    await waitFor(() => expect(result.current.catalogStatus).toBe('ok'))
    expect(result.current.catalogNewCount).toBe(2)
  })

  it('catalogNewCount is 0 when every catalog id is already imported', async () => {
    const { api, setCatalog } = makeStubApi()
    setCatalog({ categories: [], bookmarks: [{ id: 'seed-1' }, { id: 'seed-2' }] })
    const { result } = renderHook(() =>
      useCatalog(api, [{ id: 'seed-1' }, { id: 'seed-2' }]),
    )
    await waitFor(() => expect(result.current.catalogStatus).toBe('ok'))
    expect(result.current.catalogNewCount).toBe(0)
  })

  it('refresh force-syncs and returns the result', async () => {
    const { api, stub, setCatalog } = makeStubApi()
    setCatalog({ categories: [], bookmarks: [{ id: 'seed-1' }] })
    const { result } = renderHook(() => useCatalog(api, []))
    await waitFor(() => expect(result.current.catalogStatus).toBe('ok'))

    let res: any
    await act(async () => { res = await result.current.refresh() })
    expect(stub.syncCatalog).toHaveBeenCalledTimes(1)
    expect(res).toEqual({ added: 2, updated: 1, resurrected: 0, kept_local: 0, conflicts: 0 })
  })

  it('refresh is a no-op (returns null, no sync) when no catalog is loaded', async () => {
    const { api, stub } = makeStubApi()
    // getCatalog 404s -> catalog stays null, status 'missing'.
    stub.getCatalog.mockRejectedValueOnce(new HttpError('not found', 404))
    const { result } = renderHook(() => useCatalog(api, []))
    await waitFor(() => expect(result.current.catalogStatus).toBe('missing'))

    let res: any
    await act(async () => { res = await result.current.refresh() })
    expect(res).toBeNull()
    expect(stub.syncCatalog).not.toHaveBeenCalled()
  })

  it('catalogDivergedCount counts existing bookmarks whose name/lat/lng/category_id/address diverged from the catalog', async () => {
    const { api, setCatalog } = makeStubApi()
    setCatalog({
      categories: [],
      bookmarks: [
        { id: 'seed-1', name: 'Original Name', lat: 25.0, lng: 121.0, category_id: 'cat-a' },
        { id: 'seed-2', name: 'Unchanged', lat: 24.0, lng: 120.0, category_id: 'cat-b' },
        { id: 'seed-3', name: 'Never imported', lat: 23.0, lng: 119.0, category_id: 'cat-a' },
      ],
    })
    const bookmarks = [
      // Renamed locally -> diverges.
      { id: 'seed-1', name: 'User Renamed', lat: 25.0, lng: 121.0, category_id: 'cat-a' },
      // Identical to the catalog value -> not counted.
      { id: 'seed-2', name: 'Unchanged', lat: 24.0, lng: 120.0, category_id: 'cat-b' },
      // seed-3 was never imported locally, so it's a "new" entry, not an overwrite.
    ]
    const { result } = renderHook(() => useCatalog(api, bookmarks))
    await waitFor(() => expect(result.current.catalogStatus).toBe('ok'))
    expect(result.current.catalogDivergedCount).toBe(1)
  })

  it('catalogDivergedCount ignores coordinate noise below the store rounding precision (7dp)', async () => {
    const { api, setCatalog } = makeStubApi()
    setCatalog({
      categories: [],
      bookmarks: [{ id: 'seed-1', name: 'Same', lat: 25.1234567, lng: 121.1234567, category_id: 'cat-a' }],
    })
    // Differs only in the 8th decimal place -> rounds to the same 7dp value.
    const bookmarks = [{ id: 'seed-1', name: 'Same', lat: 25.12345674, lng: 121.12345674, category_id: 'cat-a' }]
    const { result } = renderHook(() => useCatalog(api, bookmarks))
    await waitFor(() => expect(result.current.catalogStatus).toBe('ok'))
    expect(result.current.catalogDivergedCount).toBe(0)
  })

  it('catalogDivergedCount counts a diverged address (address is one of the five merged fields)', async () => {
    const { api, setCatalog } = makeStubApi()
    setCatalog({
      categories: [],
      bookmarks: [{ id: 'seed-1', name: 'Same', lat: 25.0, lng: 121.0, category_id: 'cat-a', address: 'Catalog Address' }],
    })
    const bookmarks = [{ id: 'seed-1', name: 'Same', lat: 25.0, lng: 121.0, category_id: 'cat-a', address: 'User-edited address' }]
    const { result } = renderHook(() => useCatalog(api, bookmarks))
    await waitFor(() => expect(result.current.catalogStatus).toBe('ok'))
    expect(result.current.catalogDivergedCount).toBe(1)
  })

  it('catalogDivergedCount does NOT count a country_code-only divergence (E1 leaves that field to the geo resolver)', async () => {
    const { api, setCatalog } = makeStubApi()
    setCatalog({
      categories: [],
      bookmarks: [{ id: 'seed-1', name: 'Same', lat: 25.0, lng: 121.0, category_id: 'cat-a', country_code: 'jp' }],
    })
    const bookmarks = [{ id: 'seed-1', name: 'Same', lat: 25.0, lng: 121.0, category_id: 'cat-a', country_code: 'tw' }]
    const { result } = renderHook(() => useCatalog(api, bookmarks))
    await waitFor(() => expect(result.current.catalogStatus).toBe('ok'))
    expect(result.current.catalogDivergedCount).toBe(0)
  })

  it('catalogDivergedCount treats a missing address the same as an empty one (matches the backend Bookmark default)', async () => {
    const { api, setCatalog } = makeStubApi()
    // Catalog entry omits address entirely (CatalogBookmark.address is optional).
    setCatalog({
      categories: [],
      bookmarks: [{ id: 'seed-1', name: 'Same', lat: 25.0, lng: 121.0, category_id: 'cat-a' }],
    })
    // Local bookmark has the backend's default blank address.
    const bookmarks = [{ id: 'seed-1', name: 'Same', lat: 25.0, lng: 121.0, category_id: 'cat-a', address: '' }]
    const { result } = renderHook(() => useCatalog(api, bookmarks))
    await waitFor(() => expect(result.current.catalogStatus).toBe('ok'))
    expect(result.current.catalogDivergedCount).toBe(0)
  })

  it('catalogDivergedCount ignores a country_code that differs only in case, for the same reason it ignores country_code entirely', async () => {
    const { api, setCatalog } = makeStubApi()
    setCatalog({
      categories: [],
      bookmarks: [{ id: 'seed-1', name: 'Same', lat: 25.0, lng: 121.0, category_id: 'cat-a', country_code: 'jp' }],
    })
    const bookmarks = [{ id: 'seed-1', name: 'Same', lat: 25.0, lng: 121.0, category_id: 'cat-a', country_code: 'JP' }]
    const { result } = renderHook(() => useCatalog(api, bookmarks))
    await waitFor(() => expect(result.current.catalogStatus).toBe('ok'))
    expect(result.current.catalogDivergedCount).toBe(0)
  })

  it('classifies a 404 as missing and a non-404 as failed', async () => {
    const { api, stub } = makeStubApi()
    stub.getCatalog.mockRejectedValueOnce(new HttpError('boom', 500))
    const { result } = renderHook(() => useCatalog(api, []))
    await waitFor(() => expect(result.current.catalogStatus).toBe('failed'))
    expect(result.current.catalogError).toBe('boom')
  })
})
