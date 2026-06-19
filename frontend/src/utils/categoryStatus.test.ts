import { describe, it, expect } from 'vitest'
import { getCategoryStatus, todayLocal, formatChipDate } from './categoryStatus'

describe('getCategoryStatus', () => {
  it('evergreen when both start and end are empty', () => {
    expect(getCategoryStatus('', '', '2026-06-19')).toBe('evergreen')
  })

  it('upcoming when today is before start', () => {
    expect(getCategoryStatus('2026-07-01', '', '2026-06-19')).toBe('upcoming')
  })

  it('ended when today is after end', () => {
    expect(getCategoryStatus('', '2026-06-01', '2026-06-19')).toBe('ended')
  })

  it('active when today is within the window', () => {
    expect(getCategoryStatus('2026-06-01', '2026-06-30', '2026-06-19')).toBe('active')
  })

  it('active on the exact start boundary (today === start is not < start)', () => {
    expect(getCategoryStatus('2026-06-19', '2026-06-30', '2026-06-19')).toBe('active')
  })

  it('active on the exact end boundary (today === end is not > end)', () => {
    expect(getCategoryStatus('2026-06-01', '2026-06-19', '2026-06-19')).toBe('active')
  })
})

describe('todayLocal', () => {
  it('returns a YYYY-MM-DD string', () => {
    expect(todayLocal()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})

describe('formatChipDate', () => {
  it('formats month/day in en-US treating the date as UTC', () => {
    expect(formatChipDate('2026-06-07', 'en-US')).toBe('Jun 7')
  })

  it('formats month/day in zh-TW', () => {
    // Intl zh-TW short month/day -> '6月7日'
    expect(formatChipDate('2026-06-07', 'zh-TW')).toBe('6月7日')
  })
})
