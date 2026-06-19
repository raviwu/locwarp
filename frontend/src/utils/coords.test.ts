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
