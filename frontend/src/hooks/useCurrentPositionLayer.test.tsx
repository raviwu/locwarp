import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

// Stub Leaflet (jsdom can't run its DOM/WebGL init). L.marker returns a stub
// with the methods the first effect calls; the deadzone math lives on the MAP
// object (latLngToContainerPoint / getSize), which the fake map fully controls.
vi.mock('leaflet', () => ({
  default: {
    divIcon: vi.fn(() => ({})),
    marker: vi.fn(() => ({ addTo: vi.fn(function (this: any) { return this }), setLatLng: vi.fn(), remove: vi.fn() })),
  },
}))

import { useCurrentPositionLayer } from './useCurrentPositionLayer'

// Fake L.Map: only the methods the hook calls. latLngToContainerPoint is set
// per-test to place the marker inside or outside the deadzone. Viewport is
// 800x600 so the central 50% box is x in [200,600], y in [150,450].
function makeMap(pt: { x: number; y: number }) {
  return {
    panTo: vi.fn(),
    setView: vi.fn(),
    getZoom: vi.fn(() => 15),
    getSize: vi.fn(() => ({ x: 800, y: 600 })),
    latLngToContainerPoint: vi.fn(() => pt),
  }
}

function render(opts: { pt: { x: number; y: number }; followMode?: boolean }) {
  const map = makeMap(opts.pt)
  const mapRef = { current: map } as any
  const prevPositionRef = { current: null as any }
  renderHook(() =>
    useCurrentPositionLayer(mapRef, {
      currentPosition: { lat: 25, lng: 121 },
      userAvatarHtml: undefined,
      followMode: opts.followMode ?? true,
      prevPositionRef,
    }),
  )
  return { map }
}

beforeEach(() => { vi.clearAllMocks() })

describe('useCurrentPositionLayer — follow-pan deadzone', () => {
  it('does NOT pan when the marker is inside the central deadzone', () => {
    // Dead center of an 800x600 viewport.
    const { map } = render({ pt: { x: 400, y: 300 } })
    expect(map.panTo).not.toHaveBeenCalled()
  })

  it('pans when the marker drifts out of the deadzone (x axis)', () => {
    // x=700 is 300px off center > 25% of 800 (=200) → outside the box.
    const { map } = render({ pt: { x: 700, y: 300 } })
    expect(map.panTo).toHaveBeenCalledTimes(1)
    expect(map.panTo).toHaveBeenCalledWith([25, 121], { animate: true, duration: 0.4 })
  })

  it('never pans when follow mode is off, even far off-center', () => {
    const { map } = render({ pt: { x: 790, y: 590 }, followMode: false })
    expect(map.panTo).not.toHaveBeenCalled()
  })
})
