import { describe, it, expect } from 'vitest'
import { parseCoord } from './coords'

describe('parseCoord', () => {
  it('extracts a decimal pair from labelled CJK text', () => {
    expect(parseCoord('(-33.41902, -70.70187) 一般火'))
      .toEqual({ lat: -33.41902, lng: -70.70187 })
  })

  it('skips a leading integer label and grabs the decimal pair', () => {
    expect(parseCoord('#3\n35.018, 135.584'))
      .toEqual({ lat: 35.018, lng: 135.584 })
  })

  it('accepts arbitrary non-numeric separators between the two numbers', () => {
    expect(parseCoord('25.0375 B 121.5637'))
      .toEqual({ lat: 25.0375, lng: 121.5637 })
  })

  it('uses the integer-only fallback only when the whole input is two numbers', () => {
    expect(parseCoord('25, 121')).toEqual({ lat: 25, lng: 121 })
  })

  it('does NOT integer-fallback when the input has surrounding label text', () => {
    // "#3" then "25, 121": decimal RE finds nothing, integer RE requires the
    // WHOLE trimmed input to be two numbers, so this is null.
    expect(parseCoord('label 25, 121 note')).toBeNull()
  })

  it('rejects out-of-range latitude', () => {
    expect(parseCoord('95.0, 10.0')).toBeNull()
  })

  it('rejects out-of-range longitude', () => {
    expect(parseCoord('10.0, 200.0')).toBeNull()
  })

  it('returns null for text with no coordinate pair', () => {
    expect(parseCoord('hello world')).toBeNull()
  })

  it('keeps the negative sign attached to the second number', () => {
    expect(parseCoord('40.0,-120.5')).toEqual({ lat: 40.0, lng: -120.5 })
  })
})

import { trySplitLatLng } from './coords'

describe('trySplitLatLng (consolidated into coords.ts)', () => {
  // Pin the EXACT current acceptance — these mirror latlng.test.ts so a
  // regression in either dialog's accepted input is caught immediately.
  it('splits a comma-separated pair into raw string halves', () => {
    expect(trySplitLatLng('24.14, 120.65')).toEqual(['24.14', '120.65'])
  })
  it('splits a pair with no space after the comma', () => {
    expect(trySplitLatLng('24.14,120.65')).toEqual(['24.14', '120.65'])
  })
  it('splits a whitespace-separated pair', () => {
    expect(trySplitLatLng('24.14 120.65')).toEqual(['24.14', '120.65'])
  })
  it('splits a tab-separated pair', () => {
    expect(trySplitLatLng('24.14\t120.65')).toEqual(['24.14', '120.65'])
  })
  it('handles negative coordinates', () => {
    expect(trySplitLatLng('-33.86, -151.20')).toEqual(['-33.86', '-151.20'])
  })
  it('splits integer (no-decimal) pairs', () => {
    expect(trySplitLatLng('25, 121')).toEqual(['25', '121'])
  })
  it('does NOT range-check (returns raw out-of-range halves)', () => {
    // Distinguishes trySplitLatLng from parseCoord, which WOULD reject this.
    expect(trySplitLatLng('95, 200')).toEqual(['95', '200'])
  })
  it('returns null while still typing the first number', () => {
    expect(trySplitLatLng('24.1')).toBeNull()
  })
  it('returns null for a single trailing comma', () => {
    expect(trySplitLatLng('24.14,')).toBeNull()
  })
  it('returns null for non-numeric input', () => {
    expect(trySplitLatLng('Taipei 101')).toBeNull()
  })
})

describe('parseCoord — map-URL precedence', () => {
  // A Google Maps place URL carries several coordinate pairs. Left-to-right
  // first-match takes the /@ CAMERA CENTRE, which sits tens to hundreds of
  // metres from the pin. CLAUDE.md fixes the precedence as
  // !3d/!4d > ?ll= > /@ for exactly this reason.
  const PLACE_URL =
    'https://www.google.com/maps/place/Taipei+101/@25.0330000,121.5640000,17z/' +
    'data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d25.0339639!4d121.5644722!16s%2Fg%2F1234'

  it('prefers the !3d/!4d pin over the /@ camera centre', () => {
    expect(parseCoord(PLACE_URL)).toEqual({ lat: 25.0339639, lng: 121.5644722 })
  })

  it('prefers ?ll= over the /@ camera centre', () => {
    const url =
      'https://maps.google.com/maps/@25.0330000,121.5640000,17z?ll=25.0339639,121.5644722'
    expect(parseCoord(url)).toEqual({ lat: 25.0339639, lng: 121.5644722 })
  })

  it('falls back to the /@ camera centre when nothing better is present', () => {
    const url = 'https://www.google.com/maps/@25.0339639,121.5644722,17z'
    expect(parseCoord(url)).toEqual({ lat: 25.0339639, lng: 121.5644722 })
  })

  it('reads an Apple Maps q= pair', () => {
    const url = 'https://maps.apple.com/?q=25.0339639,121.5644722&z=17'
    expect(parseCoord(url)).toEqual({ lat: 25.0339639, lng: 121.5644722 })
  })

  it('leaves plain pasted text on the generic scrape path', () => {
    expect(parseCoord('#3 25.033064, 121.565418 一般火')).toEqual({
      lat: 25.033064, lng: 121.565418,
    })
  })

  it('ignores a map-URL token whose pair is out of range', () => {
    // !3d/!4d present but nonsense — fall through rather than return garbage.
    const url = 'https://www.google.com/maps/@25.0339639,121.5644722,17z/data=!3d999!4d999'
    expect(parseCoord(url)).toEqual({ lat: 25.0339639, lng: 121.5644722 })
  })
})
