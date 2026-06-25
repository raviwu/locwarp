import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'

vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
  useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: (k: string) => k }),
}))

import NearbyPlacesMenu from './NearbyPlacesMenu'

const POIS = [
  { id: '1', name: 'Cafe A', category: 'amenity', subcategory: 'cafe', lat: 25.001, lng: 121.001, distance_m: 42 },
  { id: '2', name: 'Park B', category: 'leisure', subcategory: 'park', lat: 25.002, lng: 121.002, distance_m: 88 },
]

function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    lat: 25.0,
    lng: 121.0,
    nearbyPois: vi.fn().mockResolvedValue(POIS),
    onTeleport: vi.fn(),
    onAddBookmark: vi.fn(),
    deviceConnected: true,
    onClose: vi.fn(),
    ...over,
  } as any
}

describe('NearbyPlacesMenu', () => {
  it('fetches on mount and renders one row per POI', async () => {
    const nearbyPois = vi.fn().mockResolvedValue(POIS)
    render(<NearbyPlacesMenu {...makeProps({ nearbyPois })} />)
    expect(nearbyPois).toHaveBeenCalledWith(25.0, 121.0)
    expect(await screen.findByText('Cafe A')).toBeTruthy()
    expect(screen.getByText('Park B')).toBeTruthy()
  })

  it('clicking a POI row adds a bookmark at the POI coord with its name and closes', async () => {
    const onAddBookmark = vi.fn()
    const onClose = vi.fn()
    render(<NearbyPlacesMenu {...makeProps({ onAddBookmark, onClose })} />)
    const row = await screen.findByText('Cafe A')
    fireEvent.click(row)
    expect(onAddBookmark).toHaveBeenCalledWith(25.001, 121.001, 'Cafe A')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('shows the empty state when the fetch returns []', async () => {
    const nearbyPois = vi.fn().mockResolvedValue([])
    render(<NearbyPlacesMenu {...makeProps({ nearbyPois })} />)
    expect(await screen.findByText('map.nearby_empty')).toBeTruthy()
  })

  it('shows the error state when the fetch rejects', async () => {
    const nearbyPois = vi.fn().mockRejectedValue(new Error('boom'))
    render(<NearbyPlacesMenu {...makeProps({ nearbyPois })} />)
    expect(await screen.findByText('map.nearby_error')).toBeTruthy()
  })

  it('drops a late resolve after unmount (no rows leak)', async () => {
    let resolve!: (v: any) => void
    const nearbyPois = vi.fn(() => new Promise((r) => { resolve = r }))
    const { rerender } = render(<NearbyPlacesMenu {...makeProps({ nearbyPois })} />)
    expect(nearbyPois).toHaveBeenCalledTimes(1)
    rerender(<div />)
    await waitFor(() => expect(screen.queryByText('map.nearby_loading')).toBeNull())
    await act(async () => {
      resolve(POIS)
      await Promise.resolve()
    })
    expect(screen.queryByText('Cafe A')).toBeNull()
  })
})
