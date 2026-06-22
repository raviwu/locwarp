import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import type { ApiGateway } from '../contract/apiGateway'
import { useRoutes } from './useRoutes'

// A minimal stub of the api surface useRoutes touches. getSavedRoutes returns
// `current()` so each test can mutate what the backend "has" between calls and
// assert the hook re-fetches it (mirroring the real CRUD-then-refresh flow).
function makeStubApi() {
  let routes: any[] = []
  const stub = {
    getSavedRoutes: vi.fn(async () => routes),
    saveRoute: vi.fn(async () => ({})),
    replaceRoute: vi.fn(async () => ({})),
    renameRoute: vi.fn(async () => ({})),
    deleteRoute: vi.fn(async () => ({})),
    moveRoutes: vi.fn(async () => ({ moved: 0 })),
    listRouteCategories: vi.fn(async () => [] as any[]),
    createRouteCategory: vi.fn(async () => ({})),
    updateRouteCategory: vi.fn(async () => ({})),
    deleteRouteCategory: vi.fn(async () => ({})),
    importGpx: vi.fn(async () => ({ status: 'ok', id: 'g1', points: 7 })),
    exportGpxUrl: vi.fn((id: string) => `http://x/${id}`),
    importAllRoutes: vi.fn(async () => ({ imported: 3 })),
  }
  return {
    api: stub as unknown as ApiGateway,
    stub,
    setRoutes: (r: any[]) => { routes = r },
  }
}

describe('useRoutes', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('loads saved routes + categories on mount', async () => {
    const { api, stub, setRoutes } = makeStubApi()
    setRoutes([{ id: 'r1', name: 'A' }])
    stub.listRouteCategories.mockResolvedValueOnce([{ id: 'c1', name: 'Cat' }])
    const { result } = renderHook(() => useRoutes(api))
    await waitFor(() => expect(result.current.savedRoutes).toHaveLength(1))
    expect(result.current.savedRoutes[0].id).toBe('r1')
    expect(result.current.routeCategories).toEqual([{ id: 'c1', name: 'Cat' }])
  })

  it('save (new) posts the route then re-fetches', async () => {
    const { api, stub, setRoutes } = makeStubApi()
    const { result } = renderHook(() => useRoutes(api))
    await waitFor(() => expect(stub.getSavedRoutes).toHaveBeenCalled())
    setRoutes([{ id: 'new', name: 'My Route' }])

    let res: any
    await act(async () => {
      res = await result.current.save({
        name: 'My Route', waypoints: [{ lat: 1, lng: 2 }], profile: 'walking',
      })
    })
    expect(res).toEqual({ overwritten: false })
    expect(stub.saveRoute).toHaveBeenCalledWith({
      name: 'My Route', waypoints: [{ lat: 1, lng: 2 }], profile: 'walking',
      category_id: 'default',
    })
    expect(stub.replaceRoute).not.toHaveBeenCalled()
    await waitFor(() => expect(result.current.savedRoutes).toEqual([{ id: 'new', name: 'My Route' }]))
  })

  it('save (overwrite) keeps the existing category_id when none is passed', async () => {
    const { api, stub, setRoutes } = makeStubApi()
    setRoutes([{ id: 'r1', name: 'Old', category_id: 'cat-keep' }])
    const { result } = renderHook(() => useRoutes(api))
    await waitFor(() => expect(result.current.savedRoutes).toHaveLength(1))

    let res: any
    await act(async () => {
      res = await result.current.save({
        name: 'New', waypoints: [{ lat: 3, lng: 4 }], profile: 'driving',
        overwriteId: 'r1',
      })
    })
    expect(res).toEqual({ overwritten: true })
    expect(stub.replaceRoute).toHaveBeenCalledWith('r1', {
      id: 'r1', name: 'New', waypoints: [{ lat: 3, lng: 4 }], profile: 'driving',
      category_id: 'cat-keep',
    })
  })

  it('remove deletes then re-fetches', async () => {
    const { api, stub, setRoutes } = makeStubApi()
    setRoutes([{ id: 'r1' }, { id: 'r2' }])
    const { result } = renderHook(() => useRoutes(api))
    await waitFor(() => expect(result.current.savedRoutes).toHaveLength(2))

    setRoutes([{ id: 'r2' }])
    await act(async () => { await result.current.remove('r1') })
    expect(stub.deleteRoute).toHaveBeenCalledWith('r1')
    await waitFor(() => expect(result.current.savedRoutes).toEqual([{ id: 'r2' }]))
  })

  it('move sends ids + target category then re-fetches', async () => {
    const { api, stub } = makeStubApi()
    const { result } = renderHook(() => useRoutes(api))
    await waitFor(() => expect(stub.getSavedRoutes).toHaveBeenCalled())

    await act(async () => { await result.current.move(['r1', 'r2'], 'cat-x') })
    expect(stub.moveRoutes).toHaveBeenCalledWith(['r1', 'r2'], 'cat-x')
    // re-fetch after the move
    expect(stub.getSavedRoutes).toHaveBeenCalledTimes(2)
  })

  it('categoryAdd creates the category then refreshes categories', async () => {
    const { api, stub } = makeStubApi()
    const { result } = renderHook(() => useRoutes(api))
    await waitFor(() => expect(stub.listRouteCategories).toHaveBeenCalledTimes(1))

    stub.listRouteCategories.mockResolvedValueOnce([{ id: 'c9', name: 'Fresh' }])
    await act(async () => { await result.current.categoryAdd('Fresh', '#abc') })
    expect(stub.createRouteCategory).toHaveBeenCalledWith('Fresh', '#abc')
    await waitFor(() => expect(result.current.routeCategories).toEqual([{ id: 'c9', name: 'Fresh' }]))
  })

  it('importAll parses the file, imports, then refreshes routes + categories', async () => {
    const { api, stub, setRoutes } = makeStubApi()
    const { result } = renderHook(() => useRoutes(api))
    await waitFor(() => expect(stub.getSavedRoutes).toHaveBeenCalled())

    const payload = { routes: [{ id: 'i1' }], categories: [{ id: 'ic1' }] }
    const file = { text: async () => JSON.stringify(payload) } as unknown as File
    setRoutes([{ id: 'i1' }])
    stub.listRouteCategories.mockResolvedValueOnce([{ id: 'ic1' }])

    let res: any
    await act(async () => { res = await result.current.importAll(file) })
    expect(res).toEqual({ imported: 3 })
    expect(stub.importAllRoutes).toHaveBeenCalledWith({
      routes: [{ id: 'i1' }], categories: [{ id: 'ic1' }],
    })
    await waitFor(() => expect(result.current.savedRoutes).toEqual([{ id: 'i1' }]))
    await waitFor(() => expect(result.current.routeCategories).toEqual([{ id: 'ic1' }]))
  })

  it('importAll rejects a file with no routes array', async () => {
    const { api, stub } = makeStubApi()
    const { result } = renderHook(() => useRoutes(api))
    await waitFor(() => expect(stub.getSavedRoutes).toHaveBeenCalled())
    const file = { text: async () => JSON.stringify({ nope: true }) } as unknown as File
    await expect(result.current.importAll(file)).rejects.toThrow(/missing routes array/)
  })
})
