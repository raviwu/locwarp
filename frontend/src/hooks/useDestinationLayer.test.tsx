import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

// Stub Leaflet (jsdom can't run its DOM/WebGL init). L.marker returns a stub
// with the methods the effect calls (addTo → chainable, bindTooltip, remove).
// L.divIcon returns its opts so the test can assert the dest-marker className.
vi.mock('leaflet', () => ({
  default: {
    divIcon: vi.fn((opts: any) => ({ opts })),
    marker: vi.fn(() => ({
      addTo: vi.fn(function (this: any) { return this }),
      bindTooltip: vi.fn(function (this: any) { return this }),
      remove: vi.fn(),
    })),
  },
}))

import L from 'leaflet'
import { useDestinationLayer } from './useDestinationLayer'

const divIconMock = (L as any).divIcon as ReturnType<typeof vi.fn>
const markerMock = (L as any).marker as ReturnType<typeof vi.fn>

type Pos = { lat: number; lng: number } | null
const t = ((k: string) => k) as any

function render(destination: Pos) {
  const map = {} // dest layer only touches the map via marker.addTo(map)
  const mapRef = { current: map } as any
  const view = renderHook(
    (props: { destination: Pos; t: any }) => useDestinationLayer(mapRef, props),
    { initialProps: { destination, t } },
  )
  return { ...view, map }
}

beforeEach(() => { vi.clearAllMocks() })

describe('useDestinationLayer — dest-marker lifecycle', () => {
  it('adds a .dest-marker marker when a destination is set', () => {
    const { map } = render({ lat: 35.685, lng: 139.67 })
    expect(markerMock).toHaveBeenCalledTimes(1)
    expect(divIconMock).toHaveBeenCalledWith(expect.objectContaining({ className: 'dest-marker' }))
    const marker = markerMock.mock.results[0].value
    expect(marker.addTo).toHaveBeenCalledTimes(1)
    expect(marker.addTo).toHaveBeenCalledWith(map)
  })

  it('adds no marker when destination is null', () => {
    render(null)
    expect(markerMock).not.toHaveBeenCalled()
  })

  it('removes the marker when destination clears to null', () => {
    const { rerender } = render({ lat: 35.685, lng: 139.67 })
    const marker = markerMock.mock.results[0].value
    rerender({ destination: null, t })
    expect(marker.remove).toHaveBeenCalledTimes(1)
    expect(markerMock).toHaveBeenCalledTimes(1) // only the initial render created a marker; clearing must not create another
  })
})
