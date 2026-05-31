# Bookmark Sort — Category-Level Ordering — Design

**Date:** 2026-05-31
**Status:** Draft (pending user review)
**Author:** Ravi Wu
**Type:** Feature / behavior design

---

## 1. Background

The bookmark panel has a sort dropdown (`BookmarkList.tsx` ~line 779) with four
modes, persisted in `localStorage` under `locwarp.bookmark_sort`:

```ts
type SortMode = 'default' | 'name' | 'date_added' | 'last_used';
```

Today the sort applies **only to bookmarks within a category**. `sortBookmarks`
(`BookmarkList.tsx:289-300`) sorts a single category's list; the **category
order itself is never sorted** — the grouped list render
(`BookmarkList.tsx:1182`) iterates `Object.entries(bookmarksByCategory)`, whose
key order is the `categories: string[]` prop order (built at line 527 via
`categories.reduce(...)`, with the synthetic `'Uncategorized'` bucket appended
last at line 535).

The user wants the chosen sort to apply **at the category level first, then the
bookmark level** — e.g. "By name" should order categories by name and then
bookmarks by name within each.

## 2. Goals

- Apply the active sort mode hierarchically: order categories first, then
  bookmarks within each category, using the same criterion.
- Keep the four existing modes; define each one's category-level behavior:

  | Mode | Category order | Bookmark order (within, unchanged) |
  |---|---|---|
  | `default` | unchanged (prop / manual order) | insertion order |
  | `name` | category name `localeCompare('zh-Hant')` | name |
  | `date_added` | category's **newest** bookmark `max(created_at)`, desc | `created_at` desc |
  | `last_used` | category's `max(last_used_at)`, desc | `last_used_at` desc |

- Extract the sort logic into a pure, testable util so the new category sorter
  and the existing bookmark sorter share one definition.

## 3. Non-goals

- Do **not** persist or mutate category order. This is a view-only transform;
  only `sortMode` is persisted (as today). The stored `categories` prop order is
  untouched.
- Do **not** change the category **management** surfaces — the Manage-Categories
  list (`BookmarkList.tsx:871`), the move-to-category menu (~1783), and the
  add-dialog category `<select>` (~1984) keep their current order. Only the main
  grouped bookmark list (line 1182) is reordered.
- Do **not** change search results. When `search.trim() !== ''` the panel renders
  a flat filtered list (`BookmarkList.tsx:1104`) with no category groups, so
  category ordering does not apply there.
- Do **not** sort by category status (ended / upcoming). Status only affects
  opacity, not order, and the user did not ask to reorder by it.
- No new dependencies.

## 4. Design

### 4.1 Conventions (resolved)

- **`Uncategorized` is always pinned last** in every non-default mode — it is a
  synthetic bucket, not a real category, so it never participates in name/date
  ordering.
- **Stable ordering:** `Array.prototype.sort` is stable (ES2019+, Chromium/
  Electron), so categories with an equal sort key keep their input (prop) order.
- **Missing data:** in date modes, a category whose bookmarks have no
  `created_at` / `last_used_at` (or is empty) gets representative key `''`, which
  sorts last (desc order) — after categories that have real timestamps.
- **Non-mutating:** both functions return new arrays; inputs are not modified.

### 4.2 New utility — `frontend/src/utils/bookmarkSort.ts`

`SortMode` moves here as the single source of truth. The functions are generic
over a minimal structural type so they don't couple to either `Bookmark`
interface (`BookmarkList.tsx:16` local, or `hooks/useBookmarks.ts:4` exported).

```ts
export type SortMode = 'default' | 'name' | 'date_added' | 'last_used';

/** Minimal shape the sort comparators read. */
interface SortableBookmark {
  name: string;
  created_at?: string;
  last_used_at?: string;
}

const UNCATEGORIZED = 'Uncategorized';

/** Sort bookmarks within one category by the active mode. 'default' preserves
 *  insertion order. Returns a copy — never mutates the input. */
export function sortBookmarks<T extends SortableBookmark>(list: T[], mode: SortMode): T[] {
  if (mode === 'default') return list;
  const copy = [...list];
  if (mode === 'name') {
    copy.sort((a, b) => a.name.localeCompare(b.name, 'zh-Hant'));
  } else if (mode === 'date_added') {
    copy.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
  } else if (mode === 'last_used') {
    copy.sort((a, b) => (b.last_used_at || '').localeCompare(a.last_used_at || ''));
  }
  return copy;
}

/** A category's representative timestamp for date modes: the newest
 *  created_at / last_used_at among its bookmarks (ISO strings compare
 *  lexicographically). Empty when the category has no such timestamps. */
function categoryKey<T extends SortableBookmark>(
  bms: T[],
  field: 'created_at' | 'last_used_at',
): string {
  let max = '';
  for (const b of bms) {
    const v = b[field] || '';
    if (v > max) max = v;
  }
  return max;
}

/** Order [categoryName, bookmarks][] entries by the active mode.
 *  - 'default'   → unchanged
 *  - 'name'      → category name (zh-Hant)
 *  - date modes  → category's newest bookmark timestamp, desc
 *  'Uncategorized' is pinned last; equal keys keep input order (stable sort). */
export function sortCategoryEntries<T extends SortableBookmark>(
  entries: [string, T[]][],
  mode: SortMode,
): [string, T[]][] {
  if (mode === 'default') return entries;
  const pinned = entries.filter(([cat]) => cat === UNCATEGORIZED);
  const rest = entries.filter(([cat]) => cat !== UNCATEGORIZED);

  let cmp: (a: [string, T[]], b: [string, T[]]) => number;
  if (mode === 'name') {
    cmp = (a, b) => a[0].localeCompare(b[0], 'zh-Hant');
  } else {
    const field = mode === 'date_added' ? 'created_at' : 'last_used_at';
    const keyOf = new Map(rest.map(([cat, bms]) => [cat, categoryKey(bms, field)]));
    cmp = (a, b) => (keyOf.get(b[0]) || '').localeCompare(keyOf.get(a[0]) || '');
  }

  return [...[...rest].sort(cmp), ...pinned];
}
```

### 4.3 `BookmarkList.tsx` wiring

1. Add `import { SortMode, sortBookmarks, sortCategoryEntries } from '../utils/bookmarkSort';`.
2. Delete the local `type SortMode = …` (line 276) and the local `sortBookmarks`
   function (lines 289-300). Keep the `sortMode` state + `localStorage`
   read/write (lines 277-287) — it now uses the imported `SortMode`.
3. Grouped list render (line 1182): wrap the hidden-filtered entries with the
   category sorter before mapping:

   ```tsx
   // before
   {search.trim() === '' && Object.entries(bookmarksByCategory)
     .filter(([cat]) => !hidden.has(cat))
     .map(([cat, bms]) => {
   // after
   {search.trim() === '' && sortCategoryEntries(
       Object.entries(bookmarksByCategory).filter(([cat]) => !hidden.has(cat)),
       sortMode,
     )
     .map(([cat, bms]) => {
   ```
4. Update the two existing `sortBookmarks(...)` call sites to pass `sortMode`:
   - within-category render (line 1298): `sortBookmarks(bms)` → `sortBookmarks(bms, sortMode)`
   - search results (line 1104): `sortBookmarks(bookmarks.filter(...))` → `sortBookmarks(bookmarks.filter(...), sortMode)`

### 4.4 Data flow

```
categories prop (order)
  → bookmarksByCategory (insertion order, Uncategorized last)   [unchanged]
  → Object.entries(...).filter(!hidden)                          [unchanged]
  → sortCategoryEntries(entries, sortMode)                       [NEW: category order]
  → .map(cat → sortBookmarks(bms, sortMode))                     [bookmark order, now param-driven]
```

## 5. Implementation outline

(Detailed steps come from `writing-plans`. Shape:)

1. Create `frontend/src/utils/bookmarkSort.ts` (§4.2).
2. In `BookmarkList.tsx`: add the import; remove the local `SortMode` type and
   local `sortBookmarks`; wrap line-1182 entries with `sortCategoryEntries`;
   add `sortMode` arg to the two `sortBookmarks` call sites.
3. `cd frontend && npx tsc --noEmit` — clean.
4. Runtime-verify the util (§6).

## 6. Testing

No frontend test runner exists (and none is being added).

- **Static gate:** `cd frontend && npx tsc --noEmit` clean.
- **Runtime unit check (safe, no data mutation):** with the Vite dev server up,
  `browser_evaluate` dynamically imports the real module and asserts on fixtures
  — mirroring the IME-util verification:
  ```js
  const m = await import('/src/utils/bookmarkSort.ts');
  const bm = (name, c, l) => ({ name, created_at: c, last_used_at: l });
  const entries = [
    ['B-cat', [bm('b', '2026-01-02', '2026-05-01')]],
    ['A-cat', [bm('a', '2026-03-01', '2026-02-01')]],
    ['Uncategorized', [bm('z', '2026-09-01', '2026-09-01')]], // newest dates — but must stay last
  ];
  // Expected category order by mode:
  //   default     → ['B-cat', 'A-cat', 'Uncategorized']  (input order unchanged)
  //   name        → ['A-cat', 'B-cat', 'Uncategorized']
  //   date_added  → ['A-cat', 'B-cat', 'Uncategorized']  (A newest created 03-01 > B 01-02)
  //   last_used   → ['B-cat', 'A-cat', 'Uncategorized']  (B newest used 05-01 > A 02-01)
  // Uncategorized stays last in every non-default mode despite its newest dates.
  ```
  Assert the category order for each mode, that `Uncategorized` is last in every
  non-default mode, that `default` returns input order, and that `sortBookmarks`
  orders within a category per mode.
- **Visual smoke (optional, read-only):** in the running app, switch the sort
  dropdown across the four modes and confirm category headers reorder (and revert
  to manual order on `default`). Read-only — does not mutate bookmarks.

## 7. Rollout

Direct commit to `main` (personal repo). No migration, no i18n change, no
persisted-state change — a new pure util + a small wiring change in one
component.
