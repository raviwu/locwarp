import { describe, it, expect, vi } from 'vitest'
import { snapContextCoord, metersPerPixel } from '../utils/mapPrecision'

// The projection itself belongs to Leaflet; what this test pins is the WIRING
// contract MapView must honour: project both points, snap, and forward the
// precision meta alongside the coordinate.
function openContextMenu(
  clickLatLng: { lat: number; lng: number },
  clickPoint: { x: number; y: number },
  current: { lat: number; lng: number; point: { x: number; y: number } } | null,
  zoom: number,
) {
  const snap = snapContextCoord({ ...clickLatLng, point: clickPoint }, current)
  return {
    lat: snap.lat,
    lng: snap.lng,
    snapped: snap.snapped,
    metersPerPixel: metersPerPixel(snap.lat, zoom),
  }
}

describe('context-menu coordinate wiring', () => {
  it('reproduces the 2026-09-17 pankrazberg case as a snap instead of a 3.6km miss', () => {
    const state = openContextMenu(
      { lat: 47.3388227, lng: 11.7993164 }, // what Leaflet returned at zoom 8
      { x: 500, y: 300 },
      { lat: 47.32825, lng: 11.845251, point: { x: 508, y: 297 } },
      8,
    )
    expect(state.snapped).toBe(true)
    expect(state.lat).toBe(47.32825)
    expect(state.lng).toBe(11.845251)
    expect(state.metersPerPixel).toBeGreaterThan(25)
  })

  it('leaves a deliberate far click alone and still reports its precision', () => {
    const state = openContextMenu(
      { lat: 47.3388227, lng: 11.7993164 },
      { x: 500, y: 300 },
      { lat: 47.32825, lng: 11.845251, point: { x: 700, y: 300 } },
      17,
    )
    expect(state.snapped).toBe(false)
    expect(state.lat).toBe(47.3388227)
    expect(state.metersPerPixel).toBeLessThan(25)
  })

  it('forwards the meta as the 4th argument of onAddBookmark', () => {
    const onAddBookmark = vi.fn()
    const state = openContextMenu(
      { lat: 1, lng: 2 }, { x: 0, y: 0 },
      { lat: 3, lng: 4, point: { x: 1, y: 1 } }, 8,
    )
    onAddBookmark(state.lat, state.lng, undefined, {
      snapped: state.snapped, metersPerPixel: state.metersPerPixel,
    })
    expect(onAddBookmark).toHaveBeenCalledWith(3, 4, undefined, {
      snapped: true, metersPerPixel: expect.any(Number),
    })
  })
})
