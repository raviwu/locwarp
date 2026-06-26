import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

// Leaflet + maplibre have WebGL / URL.createObjectURL side-effects at module
// init that jsdom can't run — stub the whole chain (mirrors MapView.test.tsx).
// The leaflet stub makes L.tileLayer / L.maplibreGL return identifiable layer
// stubs (each carrying its url + its own addTo spy) so the test can assert
// WHICH layer the hook added to the map.
vi.mock('maplibre-gl', () => ({ default: {} }))
vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}))
vi.mock('@maplibre/maplibre-gl-leaflet', () => ({}))
vi.mock('leaflet', () => {
  const tileLayer = vi.fn((url: string, opts: any) => ({ url, opts, kind: 'tile', addTo: vi.fn() }))
  const maplibreGL = vi.fn((opts: any) => ({ url: 'liberty', opts, kind: 'maplibre', addTo: vi.fn() }))
  const control = { layers: vi.fn(() => ({ addTo: vi.fn() })) }
  return { default: { tileLayer, maplibreGL, control } }
})

import L from 'leaflet'
import { useBaseLayers } from './useBaseLayers'

const tileLayerMock = (L as any).tileLayer as ReturnType<typeof vi.fn>
const maplibreMock = (L as any).maplibreGL as ReturnType<typeof vi.fn>

// Find the layer stub whose tile URL contains a substring (e.g. 'cartocdn').
function tileStubByUrl(substr: string): any {
  const r = tileLayerMock.mock.results.find((res) => String(res.value?.url).includes(substr))
  return r?.value
}

function renderWith(stored: string | null) {
  const map = { on: vi.fn() }
  const mapRef = { current: map } as any
  if (stored === null) localStorage.removeItem('locwarp.tile_layer')
  else localStorage.setItem('locwarp.tile_layer', stored)
  renderHook(() => useBaseLayers(mapRef))
  return { map }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

describe('useBaseLayers — default-layer choice', () => {
  it('adds CartoDB Voyager (not OSM) when no layer was ever chosen', () => {
    renderWith(null)
    const carto = tileStubByUrl('cartocdn')
    const osm = tileStubByUrl('openstreetmap')
    expect(carto.addTo).toHaveBeenCalledTimes(1)
    expect(osm.addTo).not.toHaveBeenCalled()
  })

  it('respects an explicit stored OSM choice', () => {
    renderWith('osm')
    const carto = tileStubByUrl('cartocdn')
    const osm = tileStubByUrl('openstreetmap')
    expect(osm.addTo).toHaveBeenCalledTimes(1)
    expect(carto.addTo).not.toHaveBeenCalled()
  })

  it('respects an explicit stored Liberty (vector) choice', () => {
    renderWith('liberty')
    expect(maplibreMock).toHaveBeenCalledTimes(1)
    const liberty = maplibreMock.mock.results[0].value
    expect(liberty.addTo).toHaveBeenCalledTimes(1)
  })
})
