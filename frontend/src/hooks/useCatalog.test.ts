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
    syncCatalog: vi.fn(async () => ({ added: 2, updated: 1, resurrected: 0 })),
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
    expect(res).toEqual({ added: 2, updated: 1, resurrected: 0 })
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

  it('classifies a 404 as missing and a non-404 as failed', async () => {
    const { api, stub } = makeStubApi()
    stub.getCatalog.mockRejectedValueOnce(new HttpError('boom', 500))
    const { result } = renderHook(() => useCatalog(api, []))
    await waitFor(() => expect(result.current.catalogStatus).toBe('failed'))
    expect(result.current.catalogError).toBe('boom')
  })
})
