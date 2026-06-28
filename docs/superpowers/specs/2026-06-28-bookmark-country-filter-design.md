# Bookmark Country Filter — Design

**Date:** 2026-06-28
**Status:** Approved (pending spec review)
**Area:** Frontend — bookmark panel (`frontend/src/components/BookmarkList.tsx`)

## Goal

Add a country filter (single-select dropdown) to the bookmark panel. When a
country is selected, the panel shows only that country's bookmarks, keeping the
existing category-grouped display unchanged. The filter narrows the dataset; it
does not introduce a new display mode.

## Background

Every bookmark already carries a `country_code` field (ISO 3166-1 alpha-2,
lowercase), populated at add time via reverse geocoding
(`backend/models/schemas.py:252`, frontend `Bookmark` type in
`BookmarkList.tsx:22`). The panel currently has two display paths, both fed from
the `bookmarks` prop:

- **Search mode** (`search.trim() !== ''`, `BookmarkList.tsx:632`): a flat list
  filtered by name/coordinates, no category grouping.
- **Grouped mode** (`search.trim() === ''`, `BookmarkList.tsx:673`): bookmarks
  grouped by category via `bookmarksByCategory` (`BookmarkList.tsx:295`) and
  rendered as `CategorySection`s ordered by `sortCategoryEntries`.

There is no country filter today. The only existing controls are the search box,
the sort dropdown (`BookmarkList.tsx:563`), and two checkboxes.

The country-name lookup already exists: `geoFormat.countryName(code, lang)`
(`frontend/src/utils/geoFormat.ts:39`) returns a short, localized country name
from the browser's `Intl.DisplayNames`, with overrides for long names. `lang` is
already available in `BookmarkList` (`const { lang } = useI18n()`,
`BookmarkList.tsx:141`).

## Decisions (approved)

| Decision | Choice |
|---|---|
| Selection | Single-select dropdown: `All countries` + one country |
| Persistence | None — resets to `All` on every app start |
| Interaction with search | Global narrowing — the filter narrows the base set; **both** search and grouping operate on the narrowed set |
| Empty category groups | When a country is selected, categories with zero matching bookmarks are **hidden** |
| Unknown bucket | Include an `Unknown` option **only when** bookmarks with empty `country_code` exist |
| Dropdown content | Localized country name + count, **text only** (no flag emoji) |

## Architecture

The country filter is pure view state plus derived data. No backend call, no
port, no adapter — it stays inside the frontend view/util layer, consistent with
the hexagon-lite frontend.

### Data flow

A single new derivation step is inserted at the front of the existing pipeline.
Everything downstream is unchanged except for its input source:

```
bookmarks ──► countryFiltered ──┬─► (search ≠ '')  flat search list
  (by countryFilter)            └─► (search = '')  bookmarksByCategory grouping
```

- `countryFilter === ''` → `countryFiltered = bookmarks` (behavior identical to
  today — zero regression when no country is selected).
- A real country code → `countryFiltered = bookmarks.filter(country_code match)`.
- The `UNKNOWN` sentinel → `countryFiltered = bookmarks.filter(no country_code)`.

The search filter (`BookmarkList.tsx:634`) and `bookmarksByCategory`
(`BookmarkList.tsx:295`) change their source from `bookmarks` to
`countryFiltered`. No other change to those code paths.

### New pure util: `frontend/src/utils/bookmarkCountries.ts`

Mirrors the existing `utils/bookmarkSort.ts` pattern so the logic is unit-testable
without rendering the component.

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
interface HasCountry { country_code?: string }

export interface CountryOption {
  code: string;   // ISO alpha-2 (lowercase) or UNKNOWN_COUNTRY
  name: string;   // localized display label
  count: number;  // number of bookmarks in this bucket
}

// Distinct countries present in the bookmark set, each with its count, sorted by
// localized name. Appends an Unknown bucket (UNKNOWN_COUNTRY) only when at least
// one bookmark has an empty country_code.
export function availableCountries(
  bookmarks: HasCountry[], lang: Lang, unknownLabel: string,
): CountryOption[];

// Filter by selected code. '' => all; UNKNOWN_COUNTRY => bookmarks with empty
// country_code; otherwise case-insensitive country_code match. Generic so it
// returns the caller's concrete element type unchanged.
export function filterByCountry<T extends HasCountry>(items: T[], code: string): T[];
```

- `availableCountries` lowercases and dedupes `country_code`, counts each, maps to
  a localized `name` via `countryName`, and sorts by `name` with a locale-aware
  comparator (`localeCompare`). The Unknown bucket sorts last.
- Counts are computed from the **full** `bookmarks` set (total per country), not
  from the search- or category-filtered subset.

### View changes in `BookmarkList.tsx`

1. **State:** `const [countryFilter, setCountryFilter] = useState('')`. Plain
   state, not persisted (no localStorage, no backend) — resets to `''` on mount.
2. **Derived:**
   - `countryOptions = availableCountries(bookmarks, lang, t('bm.country_unknown'))`
   - `countryFiltered = filterByCountry(bookmarks, effectiveCountry)` (see the
     stale-selection guard below for `effectiveCountry`)
   - Replace the `bookmarks` source in `bookmarksByCategory` (line 295) and in the
     search filter (line 634) with `countryFiltered`.
3. **Stale-selection guard:** compute an effective value inline, with no
   `useEffect` and no extra render — if the selected code is no longer in
   `countryOptions`, fall back to `''`:
   ```ts
   const effectiveCountry =
     countryFilter && countryOptions.some((o) => o.code === countryFilter)
       ? countryFilter : '';
   ```
   Use `effectiveCountry` everywhere downstream — the `<select value>`,
   `filterByCountry`, and the hide-empty-groups condition — so a stale selection
   immediately reads as `All`. `setCountryFilter` only ever runs from the
   dropdown's `onChange`.
4. **Dropdown UI:** a new control directly below the sort control
   (`BookmarkList.tsx:563`), same styling. Render **only when**
   `countryOptions.length >= 2` (a 0/1-country set makes the filter pointless).
   - First option: `t('bm.country_all')` with value `''`.
   - One option per `CountryOption`: label `` `${name} (${count})` ``, value `code`.
   - Text only; no flag emoji (Windows native `<select>` renders regional-indicator
     emoji as bare letters — the reason the app uses flagcdn images elsewhere).
5. **Hide empty groups:** the grouped-render filter (`BookmarkList.tsx:675`)
   becomes:
   ```ts
   .filter(([cat, bms]) => !hidden.has(cat) && (effectiveCountry === '' || bms.length > 0))
   ```
   Empty groups are hidden only while a country is selected; the `All` view keeps
   today's behavior exactly.

### i18n (`frontend/src/i18n/strings.ts`)

Add three keys alongside the existing `bm.*` entries:

- `bm.country_label` — zh: `國家`, en: `Country`
- `bm.country_all` — zh: `全部國家`, en: `All countries`
- `bm.country_unknown` — zh: `未知`, en: `Unknown`

## Edge cases

- **No country selected (`''`):** dataset and rendering are byte-for-byte the
  current behavior. This is the regression-safety anchor.
- **Selected country's bookmarks all removed:** the option disappears from
  `countryOptions`; the stale-selection guard resets the filter to `All`.
- **Bookmarks with empty `country_code`:** reachable only via the Unknown bucket,
  which appears only when such bookmarks exist.
- **Multi-select + filter change:** selection (`selectedIds`) is **not** cleared
  when the country filter changes. This matches the existing search behavior
  (typing in the search box does not clear selection). Documented, not changed.
- **Uncategorized bucket:** built from `countryFiltered`, so it too is narrowed
  and hidden when empty under a selected country.

## Testing

### `frontend/src/utils/bookmarkCountries.test.ts` (new)

- `availableCountries`: distinct codes, correct counts, sort by localized name.
- Unknown bucket present when empty-`country_code` bookmarks exist; absent
  otherwise; always sorts last.
- Empty bookmark list → empty array.
- `filterByCountry`: `''` returns all; a code returns case-insensitive matches;
  `UNKNOWN_COUNTRY` returns only empty-`country_code` bookmarks.

### `frontend/src/components/BookmarkList.test.tsx` (extend)

- Default filter is `All`; all bookmarks/categories shown (no behavior change).
- Selecting a country narrows the grouped view to that country's bookmarks.
- Categories with zero matching bookmarks are hidden while a country is selected.
- The filter narrows search results too (select country, then type a query →
  only that country's matches appear).
- Dropdown is not rendered when fewer than 2 countries are available.
- Selecting a country whose bookmarks are then removed falls back to `All`.

## Non-goals

- No persistence of the selected country (explicitly out of scope).
- No multi-country selection.
- No backend / API / WebSocket / IPC change. This is frontend-only.
- No change to the route panel (`RouteList.tsx`), even though it shares the sort
  control styling.

## Files touched

| File | Change |
|---|---|
| `frontend/src/utils/bookmarkCountries.ts` | New pure util (derive + filter) |
| `frontend/src/utils/bookmarkCountries.test.ts` | New unit tests |
| `frontend/src/components/BookmarkList.tsx` | State, derived data, dropdown UI, source swap, hide-empty filter |
| `frontend/src/components/BookmarkList.test.tsx` | New filter test cases |
| `frontend/src/i18n/strings.ts` | Three new `bm.country_*` keys |
