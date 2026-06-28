# Bookmark Country Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single-select country dropdown to the bookmark panel that narrows the dataset to one country, leaving the existing category-grouped display otherwise unchanged.

**Architecture:** A pure util (`utils/bookmarkCountries.ts`) derives the country option list and filters bookmarks by country. `BookmarkList` inserts one front-of-pipeline derivation (`countryFiltered`) that BOTH the search path and the category grouping consume, plus a dropdown control next to the sort control. No persistence, no backend, no API change — frontend view + util only.

**Tech Stack:** React + TypeScript, Vitest + @testing-library/react, Vite. i18n via the project's `i18n/strings.ts` flat string table. Country names from `utils/geoFormat.countryName` (browser `Intl.DisplayNames`).

## Global Constraints

- **Behavior / API freeze:** frontend-only. No HTTP / WebSocket / IPC / backend change. (Spec: "No backend / API / WebSocket / IPC change.")
- **No persistence:** the selected country is plain `useState`, reset to `All` (`''`) on every mount. No localStorage, no backend ui-state.
- **`All` (`''`) is byte-for-byte the current behavior** — this is the regression-safety anchor; do not change any code path that runs when no country is selected, beyond swapping its input source to `countryFiltered`.
- **Text-only dropdown options** (no flag emoji): Windows native `<select>` renders regional-indicator emoji as bare letters.
- **No shared `Bookmark` type exists** — each component redeclares its own. The util types against a minimal `{ country_code?: string }` structural interface, not any component's `Bookmark`.
- **Frontend gates stay green:** `npx tsc --noEmit` clean, `npm test` (vitest) 0 failures, `npm run depcruise` 0 errors. The new import is `view → utils` (allowed); the view must not import `adapters/api` or `services/api`.
- **Working dir for all commands:** `frontend/` (`cd /Users/raviwu/personal/locwarp/frontend`).
- **Commit identity** is auto-set by `~/.gitconfig` includeIf — never pass `-c user.email=...`. End every commit message with the two trailers shown in the commit steps.

---

### Task 1: Pure util `bookmarkCountries.ts` + unit tests

**Files:**
- Create: `frontend/src/utils/bookmarkCountries.ts`
- Test: `frontend/src/utils/bookmarkCountries.test.ts`

**Interfaces:**
- Consumes: `Lang` from `../i18n`; `countryName(code, lang)` from `./geoFormat`.
- Produces (Task 2 relies on these exact names/types):
  - `export const UNKNOWN_COUNTRY = '__unknown__'`
  - `export interface CountryOption { code: string; name: string; count: number }`
  - `export function availableCountries(bookmarks: { country_code?: string }[], lang: Lang, unknownLabel: string): CountryOption[]`
  - `export function filterByCountry<T extends { country_code?: string }>(items: T[], code: string): T[]`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/utils/bookmarkCountries.test.ts`:

```ts
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/utils/bookmarkCountries.test.ts`
Expected: FAIL — `Failed to resolve import "./bookmarkCountries"` (file does not exist yet).

- [ ] **Step 3: Write the util**

Create `frontend/src/utils/bookmarkCountries.ts`:

```ts
import type { Lang } from '../i18n';
import { countryName } from './geoFormat';

// Sentinel for "bookmarks with no country_code". Not a valid ISO code, so it
// never collides with a real country.
export const UNKNOWN_COUNTRY = '__unknown__';

// Minimal structural shape — the util only reads country_code. There is no
// shared Bookmark type in the codebase (each component redeclares its own), so
// typing against this narrow interface keeps the util decoupled and lets the
// component pass its local Bookmark[] without conversion.
interface HasCountry {
  country_code?: string;
}

export interface CountryOption {
  code: string;   // ISO alpha-2 (lowercase) or UNKNOWN_COUNTRY
  name: string;   // localized display label
  count: number;  // number of bookmarks in this bucket
}

/**
 * Distinct countries present in the bookmark set, each with its count, sorted
 * by localized name. Appends an Unknown bucket (UNKNOWN_COUNTRY, labeled with
 * `unknownLabel`) ONLY when at least one bookmark has an empty/absent
 * country_code; that bucket always sorts last.
 */
export function availableCountries(
  bookmarks: HasCountry[],
  lang: Lang,
  unknownLabel: string,
): CountryOption[] {
  const counts = new Map<string, number>();
  let unknown = 0;
  for (const bm of bookmarks) {
    const code = (bm.country_code ?? '').trim().toLowerCase();
    if (!code) {
      unknown += 1;
      continue;
    }
    counts.set(code, (counts.get(code) ?? 0) + 1);
  }
  const locale = lang === 'zh' ? 'zh-Hant' : 'en';
  const named: CountryOption[] = [...counts.entries()]
    .map(([code, count]) => ({ code, name: countryName(code, lang), count }))
    .sort((a, b) => a.name.localeCompare(b.name, locale));
  if (unknown > 0) {
    named.push({ code: UNKNOWN_COUNTRY, name: unknownLabel, count: unknown });
  }
  return named;
}

/**
 * Filter bookmarks by selected code.
 * - ''               => all (returns the input array unchanged, by reference)
 * - UNKNOWN_COUNTRY  => bookmarks with empty/absent country_code
 * - otherwise        => case-insensitive country_code match
 * Generic so it returns the caller's concrete element type unchanged.
 */
export function filterByCountry<T extends HasCountry>(items: T[], code: string): T[] {
  if (!code) return items;
  if (code === UNKNOWN_COUNTRY) {
    return items.filter((b) => !(b.country_code ?? '').trim());
  }
  const target = code.toLowerCase();
  return items.filter((b) => (b.country_code ?? '').trim().toLowerCase() === target);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run src/utils/bookmarkCountries.test.ts`
Expected: PASS — all 7 tests green.

- [ ] **Step 5: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/utils/bookmarkCountries.ts frontend/src/utils/bookmarkCountries.test.ts
git commit -m "feat(bookmark): pure country-filter util (availableCountries + filterByCountry)

Derives distinct countries with counts (localized name, sorted; conditional
Unknown bucket) and filters bookmarks by ISO code. Structural { country_code }
type, no coupling to any component's Bookmark. Frontend util only.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

### Task 2: Wire the country filter into `BookmarkList` + component tests

**Files:**
- Modify: `frontend/src/i18n/strings.ts` (add 3 keys after line 654)
- Modify: `frontend/src/components/BookmarkList.tsx` (import; state after line 244; derived before line 295; source swap at 296 + 301 + 634; dropdown after line 582; hide-empty filter at 675)
- Test: `frontend/src/components/BookmarkList.test.tsx` (append a new `describe` block)

**Interfaces:**
- Consumes (from Task 1): `availableCountries`, `filterByCountry`, `UNKNOWN_COUNTRY`, `CountryOption` from `../utils/bookmarkCountries`.
- Consumes (existing in `BookmarkList`): `const t = useT()` (line 140), `const { lang } = useI18n()` (line 141), the `bookmarks` prop, `bookmarksByCategory` (line 295), the search filter (line 634), the grouped-render filter (line 675).
- Produces: no new exports. New i18n keys `bm.country_label`, `bm.country_all`, `bm.country_unknown`.

- [ ] **Step 1: Add the three i18n strings**

In `frontend/src/i18n/strings.ts`, insert after the `'bm.sort_no_position'` line (currently line 654, immediately before `'bm.show_on_map'`):

```ts
  'bm.country_label': { zh: '國家', en: 'Country' },
  'bm.country_all': { zh: '全部國家', en: 'All countries' },
  'bm.country_unknown': { zh: '未知', en: 'Unknown' },
```

- [ ] **Step 2: Write the failing component tests**

Append this `describe` block to the END of `frontend/src/components/BookmarkList.test.tsx` (the file's mocks set i18n to an identity translator with `lang: 'en'`, so `t('bm.country_label')` returns the literal `'bm.country_label'` and `countryName('jp','en')` returns real `Intl` names):

```tsx
describe('BookmarkList country filter', () => {
  // Self-contained wrapper so we can rerender with new props (the shared
  // renderWithServices does not expose the wrapper for rerender).
  function wrapped(props: any) {
    const api = {
      getBookmarkUiState: (...a: any[]) => getBookmarkUiState(...a),
      setBookmarkUiState: (...a: any[]) => setBookmarkUiState(...a),
      reverseGeocode: (...a: any[]) => reverseGeocode(...a),
    } as any;
    return (
      <ServicesProvider value={{ api, ws: createWsRouter(), sendMessage: vi.fn(), connected: true }}>
        <BookmarkList {...props} />
      </ServicesProvider>
    );
  }

  // jp x3 (Tokyo, Osaka in Trips; Kyoto in Work), tw x1 (Taipei in Trips).
  const GEO = [
    { id: 'b1', name: 'Tokyo',  lat: 35, lng: 139, category: 'Trips', country_code: 'jp' },
    { id: 'b2', name: 'Osaka',  lat: 34, lng: 135, category: 'Trips', country_code: 'jp' },
    { id: 'b3', name: 'Kyoto',  lat: 35, lng: 135, category: 'Work',  country_code: 'jp' },
    { id: 'b4', name: 'Taipei', lat: 25, lng: 121, category: 'Trips', country_code: 'tw' },
  ];
  const CATS = ['Trips', 'Work'];

  // Visible category header labels (mirrors the existing isCategoryExpanded
  // helper: each .bookmark-group's first <span> is the category name).
  function visibleCategories(): string[] {
    return Array.from(document.querySelectorAll('.bookmark-group'))
      .map((g) => g.querySelector('span')?.textContent ?? '');
  }

  it('renders an All + per-country dropdown when >= 2 countries exist', async () => {
    render(wrapped(makeProps({ bookmarks: GEO, categories: CATS })));
    await screen.findByText('Tokyo');
    const select = screen.getByLabelText('bm.country_label') as HTMLSelectElement;
    const opts = Array.from(select.options);
    // Value order is deterministic (Japan/Taiwan or JP/TW both sort j < t);
    // assert values + counts rather than ICU display names to stay robust.
    expect(opts.map((o) => o.value)).toEqual(['', 'jp', 'tw']);
    expect(opts[0].textContent).toBe('bm.country_all');
    expect(opts.find((o) => o.value === 'jp')!.textContent).toMatch(/\(3\)$/);
    expect(opts.find((o) => o.value === 'tw')!.textContent).toMatch(/\(1\)$/);
  });

  it('does NOT render the dropdown when fewer than 2 countries exist', async () => {
    const oneCountry = GEO.filter((b) => b.country_code === 'jp');
    render(wrapped(makeProps({ bookmarks: oneCountry, categories: CATS })));
    await screen.findByText('Tokyo');
    expect(screen.queryByLabelText('bm.country_label')).toBeNull();
  });

  it('narrows the grouped view to the selected country and hides empty groups', async () => {
    render(wrapped(makeProps({ bookmarks: GEO, categories: CATS })));
    await screen.findByText('Tokyo');
    expect(visibleCategories().sort()).toEqual(['Trips', 'Work']);

    const select = screen.getByLabelText('bm.country_label');
    fireEvent.change(select, { target: { value: 'tw' } });

    // tw has only Taipei (Trips). Work has no tw bookmark => hidden.
    expect(screen.getByText('Taipei')).toBeInTheDocument();
    expect(screen.queryByText('Tokyo')).toBeNull();
    expect(visibleCategories()).toEqual(['Trips']);
  });

  it('narrows search results to the selected country', async () => {
    render(wrapped(makeProps({ bookmarks: GEO, categories: CATS })));
    await screen.findByText('Tokyo');

    fireEvent.change(screen.getByLabelText('bm.country_label'), { target: { value: 'tw' } });
    fireEvent.change(screen.getByPlaceholderText('bm.search_placeholder'), { target: { value: 'a' } });

    // 'a' matches Osaka (jp) and Taipei (tw); the country filter narrows the
    // search base to tw, so only Taipei survives.
    expect(screen.getByText('Taipei')).toBeInTheDocument();
    expect(screen.queryByText('Osaka')).toBeNull();
  });

  it('falls back to All when the selected country no longer exists', async () => {
    const { rerender } = render(wrapped(makeProps({ bookmarks: GEO, categories: CATS })));
    await screen.findByText('Tokyo');
    fireEvent.change(screen.getByLabelText('bm.country_label'), { target: { value: 'tw' } });
    expect(screen.queryByText('Tokyo')).toBeNull();

    // tw bookmark removed -> only jp left. Stale 'tw' filter must fall back to
    // All (effectiveCountry === ''), so every jp bookmark is visible again.
    const jpOnly = GEO.filter((b) => b.country_code === 'jp');
    rerender(wrapped(makeProps({ bookmarks: jpOnly, categories: CATS })));
    await screen.findByText('Tokyo');
    expect(screen.getByText('Osaka')).toBeInTheDocument();
    expect(screen.getByText('Kyoto')).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `npx vitest run src/components/BookmarkList.test.tsx -t "country filter"`
Expected: FAIL — `getByLabelText('bm.country_label')` finds no element (the dropdown does not exist yet).

- [ ] **Step 4a: Import the util in `BookmarkList.tsx`**

Add near the other `../utils/...` imports at the top of `frontend/src/components/BookmarkList.tsx`:

```ts
import { availableCountries, filterByCountry } from '../utils/bookmarkCountries';
```

- [ ] **Step 4b: Add the country-filter state**

In `frontend/src/components/BookmarkList.tsx`, immediately AFTER the `setSortMode` block (line 244, the closing `};` of `const setSortMode`), add:

```ts
  // Country filter. '' = all countries. Deliberately NOT persisted — resets to
  // all on every mount (sort + fly-GPS toggles persist; this does not). The
  // dropdown only renders when >= 2 countries are available.
  const [countryFilter, setCountryFilter] = useState('');
```

- [ ] **Step 4c: Add the derived country data**

Immediately BEFORE `const bookmarksByCategory = ...` (line 295), add:

```ts
  // Country-filter derivations (pure logic in utils/bookmarkCountries).
  // countryOptions drives the dropdown; effectiveCountry guards a selection
  // whose bookmarks were all removed (falls back to all, no extra render);
  // countryFiltered is the single narrowed set BOTH the search path and the
  // category grouping consume.
  const countryOptions = availableCountries(bookmarks, lang, t('bm.country_unknown'));
  const effectiveCountry =
    countryFilter && countryOptions.some((o) => o.code === countryFilter)
      ? countryFilter
      : '';
  const countryFiltered = filterByCountry(bookmarks, effectiveCountry);
```

- [ ] **Step 4d: Swap the grouping + search sources to `countryFiltered`**

Change the `bookmarksByCategory` builder (lines 295–303). Replace:

```ts
  const bookmarksByCategory = categories.reduce<Record<string, Bookmark[]>>((acc, cat) => {
    acc[cat] = bookmarks.filter((bm) => bm.category === cat);
    return acc;
  }, {});

  // Include uncategorized
  const uncategorized = bookmarks.filter((bm) => !categories.includes(bm.category));
```

with:

```ts
  const bookmarksByCategory = categories.reduce<Record<string, Bookmark[]>>((acc, cat) => {
    acc[cat] = countryFiltered.filter((bm) => bm.category === cat);
    return acc;
  }, {});

  // Include uncategorized
  const uncategorized = countryFiltered.filter((bm) => !categories.includes(bm.category));
```

Then in the search block (line 634), replace:

```ts
        const matches = sortBookmarks(bookmarks.filter((bm) => {
```

with:

```ts
        const matches = sortBookmarks(countryFiltered.filter((bm) => {
```

- [ ] **Step 4e: Add the dropdown control**

Immediately AFTER the closing `</div>` of the sort-control block (line 582, the `</div>` that closes the `{/* Sort control ... */}` flex row), add:

```tsx
      {/* Country filter — narrows the whole dataset (search + grouping) to one
          country. Text-only options (no flag emoji: Windows native <select>
          renders regional-indicator emoji as bare letters, which is why the app
          uses flagcdn images elsewhere). Hidden when fewer than 2 countries are
          available, since the filter would be a no-op. */}
      {countryOptions.length >= 2 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 11, color: '#bbb' }}>
          <span style={{ opacity: 0.7 }}>{t('bm.country_label')}</span>
          <select
            aria-label={t('bm.country_label')}
            value={effectiveCountry}
            onChange={(e) => setCountryFilter(e.target.value)}
            style={{
              flex: 1, background: '#1e1e22', color: '#e0e0e0',
              border: '1px solid rgba(255,255,255,0.12)', borderRadius: 4,
              padding: '3px 6px', fontSize: 11,
            }}
          >
            <option value="" style={{ background: '#1e1e22', color: '#e0e0e0' }}>{t('bm.country_all')}</option>
            {countryOptions.map((c) => (
              <option key={c.code} value={c.code} style={{ background: '#1e1e22', color: '#e0e0e0' }}>
                {`${c.name} (${c.count})`}
              </option>
            ))}
          </select>
        </div>
      )}
```

- [ ] **Step 4f: Hide empty category groups while a country is selected**

In the grouped-render block (line 674–677), replace:

```tsx
      {search.trim() === '' && sortCategoryEntries(
        Object.entries(bookmarksByCategory).filter(([cat]) => !hidden.has(cat)),
        sortMode,
      )
```

with:

```tsx
      {search.trim() === '' && sortCategoryEntries(
        Object.entries(bookmarksByCategory).filter(
          ([cat, bms]) => !hidden.has(cat) && (effectiveCountry === '' || bms.length > 0),
        ),
        sortMode,
      )
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `npx vitest run src/components/BookmarkList.test.tsx -t "country filter"`
Expected: PASS — all 5 country-filter tests green.

- [ ] **Step 6: Run the full gates**

Run, all from `frontend/`:

```bash
npx tsc --noEmit          # expect: no output (clean)
npm test                  # expect: all files pass, 0 failures (now incl. the 12 new tests)
npm run depcruise         # expect: no dependency violations (0 errors)
```

If any gate fails, fix inline and re-run before committing.

- [ ] **Step 7: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/i18n/strings.ts frontend/src/components/BookmarkList.tsx frontend/src/components/BookmarkList.test.tsx
git commit -m "feat(bookmark): country filter dropdown in the bookmark panel

Single-select dropdown that narrows the dataset to one country; the existing
category grouping and search both consume the narrowed set (countryFiltered).
Not persisted (resets to All each session), empty groups hidden while a country
is selected, conditional Unknown bucket, dropdown hidden below 2 countries,
stale selection falls back to All. Frontend-only, no API change.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

## Self-Review Notes (for the implementer)

- **Regression anchor:** with no country selected, `effectiveCountry === ''` → `countryFiltered === bookmarks` (same reference) and the hide-empty clause short-circuits to `true`. Every existing BookmarkList test must stay green unchanged.
- **Type check:** `filterByCountry<Bookmark>(bookmarks, …)` infers `T = Bookmark`, so `countryFiltered` is `Bookmark[]` and `bookmarksByCategory` stays `Record<string, Bookmark[]>` — no cast needed.
- **`lang` / `t` are already in scope** in `BookmarkList` (lines 140–141); do not re-declare them.
