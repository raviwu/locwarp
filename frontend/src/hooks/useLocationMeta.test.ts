import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import type { ApiGateway } from '../contract/apiGateway'
import { useLocationMeta } from './useLocationMeta'

// Stub the enrichment surface. reverseGeocode / lookupTimezone / lookupWeather
// each return a fixed shape so we can assert locMeta is populated, and the spy
// call counts pin the >=100m + sim-quiescent gate.
function makeStubApi() {
  const stub = {
    reverseGeocode: vi.fn(async () => ({ country_code: 'JP', short_name: 'Tokyo' })),
    lookupTimezone: vi.fn(async () => ({ zone: 'Asia/Tokyo', gmt_offset_seconds: 32400, abbreviation: 'JST', timestamp: 0 })),
    lookupWeather: vi.fn(async () => ({ tempC: 21, code: 3 })),
  }
  return { api: stub as unknown as ApiGateway, stub }
}

// ~100m north of a point at the given lat: 100m / 111320 m-per-deg-lat.
const M_PER_DEG_LAT = 111320
function latPlusMeters(lat: number, meters: number) {
  return lat + meters / M_PER_DEG_LAT
}

describe('useLocationMeta — >=100m + sim-quiescent gate', () => {
  beforeEach(() => { vi.restoreAllMocks(); vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  // Helper: flush the 600ms debounce + the awaited async lookups.
  async function flush() {
    await act(async () => { await vi.advanceTimersByTimeAsync(600) })
  }

  it('fires the lookup when quiescent and populates locMeta', async () => {
    const { api, stub } = makeStubApi()
    const { result } = renderHook(() =>
      useLocationMeta(api, { lat: 35.0, lng: 139.0 }, 'idle'),
    )
    await flush()
    expect(stub.reverseGeocode).toHaveBeenCalledTimes(1)
    // flush() already drained the debounce + awaited lookups inside act(), so
    // locMeta is settled — assert directly (waitFor polls on real timers, which
    // the fake-timer env starves).
    expect(result.current.locMeta.countryCode).toBe('jp')
    expect(result.current.locMeta.cityName).toBe('Tokyo')
    expect(result.current.locMeta.timezoneZone).toBe('Asia/Tokyo')
    expect(result.current.locMeta.weatherCode).toBe(3)
    expect(result.current.locMeta.tempC).toBe(21)
  })

  it('does NOT re-fetch when the sim is active (non-quiescent state)', async () => {
    const { api, stub } = makeStubApi()
    const { rerender } = renderHook(
      ({ pos, st }) => useLocationMeta(api, pos, st),
      { initialProps: { pos: { lat: 35.0, lng: 139.0 }, st: 'idle' } },
    )
    await flush()
    expect(stub.reverseGeocode).toHaveBeenCalledTimes(1)

    // A clearly >=100m move BUT with the sim running (navigate) must not fetch.
    rerender({ pos: { lat: latPlusMeters(35.0, 5000), lng: 139.0 }, st: 'navigate' })
    await flush()
    expect(stub.reverseGeocode).toHaveBeenCalledTimes(1)
  })

  it('does NOT re-fetch on a sub-100m move while quiescent', async () => {
    const { api, stub } = makeStubApi()
    const { rerender } = renderHook(
      ({ pos }) => useLocationMeta(api, pos, 'idle'),
      { initialProps: { pos: { lat: 35.0, lng: 139.0 } } },
    )
    await flush()
    expect(stub.reverseGeocode).toHaveBeenCalledTimes(1)

    // ~50m north — under the 100m threshold, so no new lookup.
    rerender({ pos: { lat: latPlusMeters(35.0, 50), lng: 139.0 } })
    await flush()
    expect(stub.reverseGeocode).toHaveBeenCalledTimes(1)
  })

  it('DOES re-fetch on a >=100m move while quiescent', async () => {
    const { api, stub } = makeStubApi()
    const { rerender } = renderHook(
      ({ pos }) => useLocationMeta(api, pos, 'idle'),
      { initialProps: { pos: { lat: 35.0, lng: 139.0 } } },
    )
    await flush()
    expect(stub.reverseGeocode).toHaveBeenCalledTimes(1)

    // ~150m north — over the 100m threshold, so a fresh lookup fires.
    rerender({ pos: { lat: latPlusMeters(35.0, 150), lng: 139.0 } })
    await flush()
    expect(stub.reverseGeocode).toHaveBeenCalledTimes(2)
  })

  it('does not fetch at all when position is null', async () => {
    const { api, stub } = makeStubApi()
    renderHook(() => useLocationMeta(api, null, 'idle'))
    await flush()
    expect(stub.reverseGeocode).not.toHaveBeenCalled()
  })
})
