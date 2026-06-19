import { describe, it, expect } from 'vitest'
import { approxCellSizeMeters } from './s2grid'

describe('approxCellSizeMeters', () => {
  it('equals (40075016/4 / 2^level) * cos(lat) at the equator (cos=1)', () => {
    // level 0 at the equator: 40075016/4 = 10018754
    expect(approxCellSizeMeters(0, 0)).toBeCloseTo(10018754, 0)
  })

  it('halves the size for each extra level', () => {
    expect(approxCellSizeMeters(1, 0)).toBeCloseTo(10018754 / 2, 0)
    expect(approxCellSizeMeters(10, 0)).toBeCloseTo(10018754 / 1024, 3)
  })

  it('scales by cos(latitude)', () => {
    // at lat 60, cos(60deg) = 0.5
    expect(approxCellSizeMeters(0, 60)).toBeCloseTo(10018754 * 0.5, 0)
  })

  it('matches the exact formula for an arbitrary level/lat', () => {
    const level = 14
    const lat = 25.0375
    const expected = (40075016 / 4 / Math.pow(2, level)) *
      Math.cos((lat * Math.PI) / 180)
    expect(approxCellSizeMeters(level, lat)).toBeCloseTo(expected, 9)
  })
})
