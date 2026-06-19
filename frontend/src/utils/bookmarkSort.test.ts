import { describe, it, expect } from 'vitest'
import { sortBookmarks, sortCategoryEntries } from './bookmarkSort'

type B = { name: string; created_at?: string; last_used_at?: string }

const list: B[] = [
  { name: 'Banana', created_at: '2026-01-02', last_used_at: '2026-03-01' },
  { name: 'apple',  created_at: '2026-01-03', last_used_at: '2026-02-01' },
  { name: 'cherry', created_at: '2026-01-01', last_used_at: '2026-04-01' },
]

describe('sortBookmarks', () => {
  it("'default' returns the SAME array reference (no copy)", () => {
    expect(sortBookmarks(list, 'default')).toBe(list)
  })

  it("'name' sorts a copy ascending (zh-Hant locale) without mutating input", () => {
    const before = list.map((b) => b.name)
    const out = sortBookmarks(list, 'name')
    expect(out).not.toBe(list)
    expect(out.map((b) => b.name)).toEqual(['apple', 'Banana', 'cherry'])
    expect(list.map((b) => b.name)).toEqual(before) // input untouched
  })

  it("'date_added' sorts by created_at descending", () => {
    expect(sortBookmarks(list, 'date_added').map((b) => b.name))
      .toEqual(['apple', 'Banana', 'cherry'])
  })

  it("'last_used' sorts by last_used_at descending", () => {
    expect(sortBookmarks(list, 'last_used').map((b) => b.name))
      .toEqual(['cherry', 'Banana', 'apple'])
  })

  it('treats missing timestamps as empty string (sorts last in desc)', () => {
    const withMissing: B[] = [
      { name: 'has', created_at: '2026-01-01' },
      { name: 'none' },
    ]
    expect(sortBookmarks(withMissing, 'date_added').map((b) => b.name))
      .toEqual(['has', 'none'])
  })
})

describe('sortCategoryEntries', () => {
  const entries: [string, B[]][] = [
    ['Zebra', [{ name: 'z', created_at: '2026-01-01' }]],
    ['Uncategorized', [{ name: 'u', created_at: '2026-09-09' }]],
    ['Alpha', [{ name: 'a', created_at: '2026-05-05' }]],
  ]

  it("'default' returns entries unchanged (by reference)", () => {
    expect(sortCategoryEntries(entries, 'default')).toBe(entries)
  })

  it("'name' sorts categories and pins Uncategorized last", () => {
    expect(sortCategoryEntries(entries, 'name').map(([c]) => c))
      .toEqual(['Alpha', 'Zebra', 'Uncategorized'])
  })

  it("'date_added' orders by newest bookmark desc, Uncategorized still last", () => {
    // Alpha=2026-05-05, Zebra=2026-01-01 -> Alpha first; Uncategorized pinned.
    expect(sortCategoryEntries(entries, 'date_added').map(([c]) => c))
      .toEqual(['Alpha', 'Zebra', 'Uncategorized'])
  })

  it("'last_used' orders by newest last_used_at desc, Uncategorized still last", () => {
    // categoryKey picks the max last_used_at per category, then sorts descending.
    // Zebra=2026-06-01, Alpha=2026-03-15 -> Zebra first; Uncategorized pinned last.
    const luEntries: [string, B[]][] = [
      ['Zebra',         [{ name: 'z', last_used_at: '2026-06-01' }]],
      ['Uncategorized', [{ name: 'u', last_used_at: '2026-09-09' }]],
      ['Alpha',         [{ name: 'a', last_used_at: '2026-03-15' }]],
    ]
    expect(sortCategoryEntries(luEntries, 'last_used').map(([c]) => c))
      .toEqual(['Zebra', 'Alpha', 'Uncategorized'])
  })
})
