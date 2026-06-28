import { describe, it, expect } from 'vitest'
import { roadEstimateM } from './roadEstimate'

describe('roadEstimateM', () => {
  it('applies a per-profile detour factor', () => {
    expect(roadEstimateM(1000, 'driving')).toBe(1400)
    expect(roadEstimateM(1000, 'walking')).toBe(1300)
    expect(roadEstimateM(1000, 'cycling')).toBe(1350)
  })
  it('maps engine-profile aliases', () => {
    expect(roadEstimateM(1000, 'car')).toBe(1400)
    expect(roadEstimateM(1000, 'foot')).toBe(1300)
    expect(roadEstimateM(1000, 'running')).toBe(1300)
  })
  it('defaults to 1.4 for unknown/absent profile', () => {
    expect(roadEstimateM(1000, undefined)).toBe(1400)
    expect(roadEstimateM(1000, 'spaceship')).toBe(1400)
  })
})
