import { describe, it, expect } from 'vitest'
import {
  MARKER_SNAP_RADIUS_PX,
  snapContextCoord,
  metersPerPixel,
  precisionHintText,
} from './mapPrecision'

const CLICK = { lat: 47.3388227, lng: 11.7993164, point: { x: 500, y: 300 } }
const CURRENT = { lat: 47.32825, lng: 11.845251, point: { x: 508, y: 297 } }

describe('snapContextCoord', () => {
  it('returns the current position when the click lands inside the marker footprint', () => {
    // 8px right, 3px up => 8.54px, inside the 22px radius.
    expect(snapContextCoord(CLICK, CURRENT)).toEqual({
      lat: 47.32825, lng: 11.845251, snapped: true,
    })
  })

  it('returns the raw click when it lands outside the marker footprint', () => {
    const far = { ...CURRENT, point: { x: 560, y: 300 } } // 60px away
    expect(snapContextCoord(CLICK, far)).toEqual({
      lat: 47.3388227, lng: 11.7993164, snapped: false,
    })
  })

  it('snaps exactly at the radius boundary but not one pixel beyond', () => {
    const onEdge = { ...CURRENT, point: { x: 500 + MARKER_SNAP_RADIUS_PX, y: 300 } }
    const justOut = { ...CURRENT, point: { x: 500 + MARKER_SNAP_RADIUS_PX + 1, y: 300 } }
    expect(snapContextCoord(CLICK, onEdge).snapped).toBe(true)
    expect(snapContextCoord(CLICK, justOut).snapped).toBe(false)
  })

  it('returns the raw click when there is no current position', () => {
    expect(snapContextCoord(CLICK, null)).toEqual({
      lat: 47.3388227, lng: 11.7993164, snapped: false,
    })
  })

  it('honours an explicit radius override', () => {
    expect(snapContextCoord(CLICK, CURRENT, 4).snapped).toBe(false)
  })
})

describe('metersPerPixel', () => {
  it('matches the known web-mercator resolution at the equator', () => {
    expect(metersPerPixel(0, 0)).toBeCloseTo(156543.03, 1)
    expect(metersPerPixel(0, 8)).toBeCloseTo(611.50, 1)
  })

  it('shrinks with the cosine of the latitude', () => {
    expect(metersPerPixel(47, 8)).toBeCloseTo(417.0, 0)
    expect(metersPerPixel(60, 8)).toBeCloseTo(305.7, 0)
  })

  it('halves for every zoom level gained', () => {
    expect(metersPerPixel(35, 13)).toBeCloseTo(metersPerPixel(35, 12) / 2, 6)
  })
})

describe('precisionHintText', () => {
  it('substitutes the rounded metre value into the {m} token', () => {
    expect(precisionHintText('1px ~ {m} m', 417.04)).toBe('1px ~ 417 m')
  })

  it('rounds to a whole metre', () => {
    expect(precisionHintText('{m}', 2000.6)).toBe('2001')
  })

  it('leaves a template without the token untouched', () => {
    expect(precisionHintText('no token here', 417)).toBe('no token here')
  })
})
