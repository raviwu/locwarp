import { describe, it, expect } from 'vitest'
import { availableCountries, filterByCountry, UNKNOWN_COUNTRY } from './bookmarkCountries'

type B = { country_code?: string }

describe('availableCountries', () => {
  it('returns distinct countries with counts, sorted by localized name', () => {
    const bms: B[] = [
      { country_code: 'jp' },
      { country_code: 'tw' },
      { country_code: 'jp' },
      { country_code: 'us' },
    ]
    const out = availableCountries(bms, 'en', 'Unknown')
    // Names: Japan / Taiwan / USA(override). Both real-Intl and the
    // code-fallback (JP/TW/USA) sort to the same code order here.
    expect(out.map((c) => c.code)).toEqual(['jp', 'tw', 'us'])
    expect(out.map((c) => c.count)).toEqual([2, 1, 1])
    expect(out.find((c) => c.code === 'us')!.name).toBe('USA') // SHORT_OVERRIDES
  })

  it('lowercases and dedupes mixed-case country codes', () => {
    const out = availableCountries([{ country_code: 'JP' }, { country_code: 'jp' }], 'en', 'Unknown')
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ code: 'jp', count: 2 })
  })

  it('appends an Unknown bucket (last) only when empty-country bookmarks exist', () => {
    const withUnknown = availableCountries(
      [{ country_code: 'jp' }, { country_code: '' }, {}],
      'en', 'Unknown',
    )
    expect(withUnknown.map((c) => c.code)).toEqual(['jp', UNKNOWN_COUNTRY])
    expect(withUnknown[withUnknown.length - 1]).toMatchObject({ code: UNKNOWN_COUNTRY, count: 2 })

    const noUnknown = availableCountries([{ country_code: 'jp' }], 'en', 'Unknown')
    expect(noUnknown.some((c) => c.code === UNKNOWN_COUNTRY)).toBe(false)
  })

  it('returns an empty array for an empty bookmark list', () => {
    expect(availableCountries([], 'en', 'Unknown')).toEqual([])
  })
})

describe('filterByCountry', () => {
  const bms: B[] = [
    { country_code: 'jp' },
    { country_code: 'JP' },
    { country_code: 'tw' },
    { country_code: '' },
    {},
  ]

  it("'' returns the same array reference (all)", () => {
    expect(filterByCountry(bms, '')).toBe(bms)
  })

  it('matches a code case-insensitively', () => {
    expect(filterByCountry(bms, 'jp')).toHaveLength(2)
  })

  it('UNKNOWN_COUNTRY returns only empty/absent country_code bookmarks', () => {
    expect(filterByCountry(bms, UNKNOWN_COUNTRY)).toHaveLength(2)
  })
})
