import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import type { ApiGateway } from '../contract/apiGateway'
import { useRecentPlaces } from './useRecentPlaces'

// A minimal stub of the api surface useRecentPlaces touches. getRecent returns
// `current()` so each test can mutate what the backend "has" between calls and
// assert the hook re-fetches it (mirroring the real push-then-refresh flow).
function makeStubApi() {
  let recent: any[] = []
  const stub = {
    getRecent: vi.fn(async () => recent),
    pushRecent: vi.fn(async (e: any) => e),
    clearRecent: vi.fn(async () => ({ status: 'ok' })),
    reverseGeocode: vi.fn(async () => ({ short_name: '', display_name: '' })),
  }
  return {
    api: stub as unknown as ApiGateway,
    stub,
    setRecent: (r: any[]) => { recent = r },
  }
}

describe('useRecentPlaces', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('refresh populates the list on mount', async () => {
    const { api, stub, setRecent } = makeStubApi()
    setRecent([{ lat: 1, lng: 2, kind: 'teleport', name: 'X', ts: 1 }])
    const { result } = renderHook(() => useRecentPlaces(api, true))
    await waitFor(() => expect(result.current.recentPlaces).toHaveLength(1))
    expect(stub.getRecent).toHaveBeenCalled()
    expect(result.current.recentPlaces[0].name).toBe('X')
  })

  it('clearRecentList clears the backend then empties the list', async () => {
    const { api, stub, setRecent } = makeStubApi()
    setRecent([{ lat: 1, lng: 2, kind: 'teleport', name: 'X', ts: 1 }])
    const { result } = renderHook(() => useRecentPlaces(api, true))
    await waitFor(() => expect(result.current.recentPlaces).toHaveLength(1))

    await act(async () => { await result.current.clearRecentList() })
    expect(stub.clearRecent).toHaveBeenCalled()
    expect(result.current.recentPlaces).toEqual([])
  })

  it('pushRecent posts the entry then re-fetches', async () => {
    const { api, stub, setRecent } = makeStubApi()
    const { result } = renderHook(() => useRecentPlaces(api, true))
    await waitFor(() => expect(stub.getRecent).toHaveBeenCalled())

    setRecent([{ lat: 5, lng: 6, kind: 'search', name: 'Tokyo', ts: 2 }])
    await act(async () => { await result.current.pushRecent(5, 6, 'search', 'Tokyo') })
    expect(stub.pushRecent).toHaveBeenCalledWith({ lat: 5, lng: 6, kind: 'search', name: 'Tokyo' })
    await waitFor(() => expect(result.current.recentPlaces).toEqual([
      { lat: 5, lng: 6, kind: 'search', name: 'Tokyo', ts: 2 },
    ]))
  })

  it('pushRecent without a name reverse-geocodes and re-pushes with the resolved name', async () => {
    const { api, stub } = makeStubApi()
    stub.reverseGeocode.mockResolvedValueOnce({ short_name: 'Shibuya', display_name: 'Shibuya, Tokyo' })
    const { result } = renderHook(() => useRecentPlaces(api, true))
    await waitFor(() => expect(stub.getRecent).toHaveBeenCalled())

    await act(async () => { await result.current.pushRecent(35, 139, 'teleport') })
    // First push: no name. Background push: resolved name from reverseGeocode.
    await waitFor(() => {
      expect(stub.pushRecent).toHaveBeenCalledWith({ lat: 35, lng: 139, kind: 'teleport', name: null })
      expect(stub.reverseGeocode).toHaveBeenCalledWith(35, 139)
      expect(stub.pushRecent).toHaveBeenCalledWith({ lat: 35, lng: 139, kind: 'teleport', name: 'Shibuya' })
    })
  })

  it('refetches when connected flips false -> true', async () => {
    const { api, stub } = makeStubApi()
    const { rerender } = renderHook(({ c }) => useRecentPlaces(api, c), {
      initialProps: { c: false },
    })
    await waitFor(() => expect(stub.getRecent).toHaveBeenCalledTimes(1))
    rerender({ c: true })
    await waitFor(() => expect(stub.getRecent).toHaveBeenCalledTimes(2))
  })
})
