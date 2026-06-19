import { describe, it, expect } from 'vitest'
import { countryName, formatGmtOffset } from './geoFormat'

describe('countryName', () => {
  it('returns empty string for missing code', () => {
    expect(countryName(undefined, 'en')).toBe('')
    expect(countryName('', 'zh')).toBe('')
  })

  it('uses the SHORT_OVERRIDES table for en', () => {
    expect(countryName('US', 'en')).toBe('USA')
    expect(countryName('GB', 'en')).toBe('UK')
    expect(countryName('AE', 'en')).toBe('UAE')
    expect(countryName('KR', 'en')).toBe('S. Korea')
    expect(countryName('CD', 'en')).toBe('DR Congo')
  })

  it('uses the SHORT_OVERRIDES table for zh', () => {
    expect(countryName('US', 'zh')).toBe('美國')
    expect(countryName('HK', 'zh')).toBe('香港')
    expect(countryName('RU', 'zh')).toBe('俄羅斯')
  })

  it('is case-insensitive on the override path', () => {
    expect(countryName('us', 'en')).toBe('USA')
  })

  it('returns Intl display name or uppercased code for unknown region', () => {
    // Node full-ICU: Intl.DisplayNames.of('ZZ') -> 'Unknown Region' (truthy, so
    // `|| cc` never fires). On small-ICU / older Node it's falsy -> output 'ZZ'.
    // Accept both so this characterization doesn't silently flip on a Node/ICU change.
    const result = countryName('zz', 'en')
    expect(['Unknown Region', 'ZZ']).toContain(result)
  })
})

describe('formatGmtOffset', () => {
  it('returns empty string for blank timezone', () => {
    expect(formatGmtOffset(undefined)).toBe('')
    expect(formatGmtOffset('')).toBe('')
  })

  it('formats a positive offset zone as GMT+N', () => {
    expect(formatGmtOffset('Asia/Taipei')).toBe('GMT+8')
  })

  it('formats UTC as GMT+0 (source normalizes bare GMT to GMT+0)', () => {
    // The source explicitly normalizes a bare 'GMT' return from ICU to 'GMT+0'
    // (see geoFormat.ts: `return tzName === 'GMT' ? 'GMT+0' : tzName`), so no
    // code path can return bare 'GMT' — hard-assert the normalized form.
    expect(formatGmtOffset('UTC')).toBe('GMT+0')
  })

  it('returns empty string for an unrecognized timezone', () => {
    expect(formatGmtOffset('Not/AZone')).toBe('')
  })
})
