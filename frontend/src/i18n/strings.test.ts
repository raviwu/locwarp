import { describe, it, expect } from 'vitest'
import { STRINGS } from './strings'

// Regression guard for DEFECT B2 (bookmark-revert-hazards review): the catalog
// force-sync confirm dialog's own tests mock '../i18n' entirely (see
// CatalogRefreshConfirmDialog.test.tsx), so a wrong-but-existing key would
// still pass there. This file imports the REAL strings table — no mock — and
// checks the keys the dialog actually renders.
describe('i18n strings table — catalog refresh confirm dialog', () => {
  // Keys read directly off src/components/CatalogRefreshConfirmDialog.tsx's
  // t(...) calls. Keep this list in sync if that dialog adds/removes a key.
  const DIALOG_KEYS = [
    'bm.catalog.confirm_title',
    'bm.catalog.confirm_added',
    'bm.catalog.confirm_diverged',
    'bm.catalog.confirm_no_diverged',
    'bm.catalog.confirm_button',
  ] as const

  // The table currently carries exactly these two languages (StringKey entries
  // are `{ zh, en }`); if a third language is ever added, extend this list so
  // the completeness check stays meaningful.
  const LANGS = ['zh', 'en'] as const

  const entryOf = (key: string) => (STRINGS as Record<string, Record<string, string>>)[key]

  it('every dialog key exists in the real table with a non-empty entry for every language', () => {
    for (const key of DIALOG_KEYS) {
      const entry = entryOf(key)
      expect(entry, `missing key: ${key}`).toBeDefined()
      for (const lang of LANGS) {
        expect(entry[lang], `${key}.${lang} is empty`).toBeTruthy()
      }
    }
  })

  // Deliberately NOT exhaustive — a representative set of characters that
  // exist ONLY in Simplified Chinese orthography, chosen to be unambiguous
  // (excludes characters like 台/只/于/万 that are also valid in Traditional
  // usage, to avoid false positives).
  const SIMPLIFIED_ONLY = new Set(
    '国会对说现从这为学习长门问间开关电车东华业儿处广应义书买卖产众优传伤价体变单双号'.split(''),
  )
  // Hiragana (U+3040-U+309F) + Katakana (U+30A0-U+30FF).
  const KANA_RE = /[\u3040-\u30ff]/

  it('the Chinese text for every dialog key is 繁體 (no Simplified-only chars, no kana)', () => {
    for (const key of DIALOG_KEYS) {
      const zh = entryOf(key).zh
      for (const ch of zh) {
        expect(SIMPLIFIED_ONLY.has(ch), `${key}.zh contains a Simplified-only char: "${ch}"`).toBe(false)
      }
      expect(KANA_RE.test(zh), `${key}.zh contains kana`).toBe(false)
    }
  })
})
