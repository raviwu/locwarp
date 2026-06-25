import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { nearbyPois } from './api'

describe('nearbyPois api', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => [
        { id: '1', name: 'Cafe A', category: 'amenity', subcategory: 'cafe',
          lat: 25.001, lng: 121.001, distance_m: 42.0 },
      ],
    })) as any)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('GETs /api/geocode/nearby with lat/lng/radius_m/limit and returns the POI list', async () => {
    const out = await nearbyPois(25.0, 121.0, 350, 7)
    expect(out).toHaveLength(1)
    expect(out[0].name).toBe('Cafe A')
    const calledUrl = (globalThis.fetch as any).mock.calls[0][0] as string
    expect(calledUrl).toContain('/api/geocode/nearby')
    expect(calledUrl).toContain('lat=25')
    expect(calledUrl).toContain('lng=121')
    expect(calledUrl).toContain('radius_m=350')
    expect(calledUrl).toContain('limit=7')
  })

  it('uses default radius_m=200 and limit=40 when omitted', async () => {
    await nearbyPois(25.0, 121.0)
    const calledUrl = (globalThis.fetch as any).mock.calls[0][0] as string
    expect(calledUrl).toContain('radius_m=200')
    expect(calledUrl).toContain('limit=40')
  })
})
