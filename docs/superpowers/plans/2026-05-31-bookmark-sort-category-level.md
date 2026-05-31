# Bookmark Sort — Category-Level Ordering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bookmark sort dropdown order categories first (by the active mode), then bookmarks within each — currently only bookmarks are sorted.

**Architecture:** Extract the sort logic into a pure, generic util `frontend/src/utils/bookmarkSort.ts` (`sortBookmarks`, `sortCategoryEntries`, `SortMode`). `BookmarkList.tsx` imports them: it wraps the grouped category entries with `sortCategoryEntries` and passes `sortMode` to the two `sortBookmarks` call sites. View-only transform — no persisted/category-order mutation.

**Tech Stack:** React 18 + TypeScript + Vite. Spec: `docs/superpowers/specs/2026-05-31-bookmark-sort-category-level-design.md`.

---

## Testing approach (read first)

No frontend test runner exists (no vitest/jest), and none is being added. Verification:
- **Per-task static gate:** `cd frontend && npx tsc --noEmit` must be clean.
- **Behavior gate (Task 3):** dynamically import the real `bookmarkSort.ts` module in the running Vite dev server via Playwright MCP and assert category/bookmark ordering against fixtures. Pure functions, no data mutation — safe against the live store.

## File structure

| File | Responsibility | Change |
|---|---|---|
| `frontend/src/utils/bookmarkSort.ts` | Pure sort: `SortMode`, `sortBookmarks(list, mode)`, `sortCategoryEntries(entries, mode)` | **Create** |
| `frontend/src/components/BookmarkList.tsx` | Bookmark panel: import util, drop local copies, wrap category entries, pass `sortMode` | Modify |

Commit grouping: Task 1 = util; Task 2 = BookmarkList wiring; Task 3 = verification (no commit).

---

### Task 1: Create the `bookmarkSort` utility

**Files:**
- Create: `frontend/src/utils/bookmarkSort.ts`

- [ ] **Step 1: Create the util file**

Create `frontend/src/utils/bookmarkSort.ts` with exactly:

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

- [ ] **Step 2: Type-check**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit`
Expected: no errors. (The module is not imported yet; an unused module does not fail tsc.)

- [ ] **Step 3: Commit**

```bash
cd /Users/raviwu/personal/locwarp && git add frontend/src/utils/bookmarkSort.ts && git commit -m "$(cat <<'EOF'
feat(bookmark): pure sort util for categories + bookmarks

sortBookmarks(list, mode) and sortCategoryEntries(entries, mode), generic
over a minimal {name, created_at?, last_used_at?} shape. Category modes:
name (zh-Hant), date_added/last_used by the category's newest bookmark,
desc; Uncategorized pinned last; default unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Wire `BookmarkList.tsx` to the util

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx` (import; remove local `SortMode` + local `sortBookmarks`; wrap category entries; pass `sortMode` to 2 call sites)

- [ ] **Step 1: Add the import**

Find (line 6):
```ts
import { getBookmarkUiState, setBookmarkUiState, reverseGeocode } from '../services/api';
```
Add directly after it:
```ts
import { sortBookmarks, sortCategoryEntries, type SortMode } from '../utils/bookmarkSort';
```

- [ ] **Step 2: Remove the local `SortMode` type**

Find (the comment stays; remove only the `type` line):
```ts
  // Sort mode persisted in localStorage so it survives restart.
  type SortMode = 'default' | 'name' | 'date_added' | 'last_used';
  const [sortMode, setSortModeRaw] = useState<SortMode>(() => {
```
Replace with:
```ts
  // Sort mode persisted in localStorage so it survives restart.
  const [sortMode, setSortModeRaw] = useState<SortMode>(() => {
```

- [ ] **Step 3: Remove the local `sortBookmarks` function**

Find and DELETE this whole block (the imported `sortBookmarks` replaces it). After deleting, leave exactly ONE blank line between the `setSortMode` closing `};` (line 287) and the next code below — don't leave a double blank gap:
```ts
  const sortBookmarks = (list: Bookmark[]): Bookmark[] => {
    if (sortMode === 'default') return list;
    const copy = [...list];
    if (sortMode === 'name') {
      copy.sort((a, b) => a.name.localeCompare(b.name, 'zh-Hant'));
    } else if (sortMode === 'date_added') {
      copy.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
    } else if (sortMode === 'last_used') {
      copy.sort((a, b) => (b.last_used_at || '').localeCompare(a.last_used_at || ''));
    }
    return copy;
  };
```
(Delete those 12 lines entirely.)

- [ ] **Step 4: Pass `sortMode` at the search-results call site**

Find (the closing of the flat search list's filter, ~line 1108):
```tsx
          return name.includes(q) || coord.includes(q);
        }));
```
Replace with (add `, sortMode` as the second arg to `sortBookmarks`):
```tsx
          return name.includes(q) || coord.includes(q);
        }), sortMode);
```

- [ ] **Step 5: Sort the category entries in the grouped render**

Find (~line 1182):
```tsx
      {search.trim() === '' && Object.entries(bookmarksByCategory)
        .filter(([cat]) => !hidden.has(cat))
        .map(([cat, bms]) => {
```
Replace with:
```tsx
      {search.trim() === '' && sortCategoryEntries(
        Object.entries(bookmarksByCategory).filter(([cat]) => !hidden.has(cat)),
        sortMode,
      )
        .map(([cat, bms]) => {
```

- [ ] **Step 6: Pass `sortMode` at the within-category call site**

Find (~line 1298):
```tsx
              {sortBookmarks(bms).map((bm) => {
```
Replace with:
```tsx
              {sortBookmarks(bms, sortMode).map((bm) => {
```

- [ ] **Step 7: Type-check**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit`
Expected: no errors. (If it reports `sortBookmarks` expects 2 args, a call site was missed — check Steps 4 and 6. If it reports an unused `Bookmark`-only construct, that is unrelated.)

- [ ] **Step 8: Confirm the local copies are gone**

Run:
```bash
cd /Users/raviwu/personal/locwarp && grep -nE "type SortMode =|const sortBookmarks =" frontend/src/components/BookmarkList.tsx
```
Expected: **zero matches** (both local definitions removed; the symbols now come from the util import).

- [ ] **Step 9: Commit**

```bash
cd /Users/raviwu/personal/locwarp && git add frontend/src/components/BookmarkList.tsx && git commit -m "$(cat <<'EOF'
feat(bookmark): apply sort to category order, then bookmarks

The sort dropdown now orders categories first (by name / newest
created_at / newest last_used) and bookmarks within, via the shared
bookmarkSort util. Uncategorized stays last; default and search are
unchanged. Drops the now-duplicated local SortMode + sortBookmarks.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Verify behavior (Playwright MCP) — no commit

**Files:** none (verification only)

- [ ] **Step 1: Start the dev server**

Run (background): `cd /Users/raviwu/personal/locwarp/frontend && npx vite --port 5199 --strictPort`
Wait for the local URL.

- [ ] **Step 2: Runtime unit check of the real module (safe, no data mutation)**

Playwright MCP → `browser_navigate` to `http://localhost:5199/`, then `browser_evaluate`:

```js
async () => {
  const m = await import('/src/utils/bookmarkSort.ts');
  const bm = (name, c, l) => ({ name, created_at: c, last_used_at: l });
  const entries = () => ([
    ['B-cat', [bm('b', '2026-01-02', '2026-05-01')]],
    ['A-cat', [bm('a', '2026-03-01', '2026-02-01')]],
    ['Uncategorized', [bm('z', '2026-09-01', '2026-09-01')]], // newest dates, must stay last
  ]);
  const order = (mode) => m.sortCategoryEntries(entries(), mode).map(([c]) => c);
  return {
    default: order('default'),       // ['B-cat','A-cat','Uncategorized']
    name: order('name'),             // ['A-cat','B-cat','Uncategorized']
    date_added: order('date_added'), // ['A-cat','B-cat','Uncategorized']
    last_used: order('last_used'),   // ['B-cat','A-cat','Uncategorized']
    // bookmark-level within a category
    bmNames: m.sortBookmarks([bm('banana'), bm('apple'), bm('cherry')], 'name').map((x) => x.name),
    // [‘apple’,‘banana’,‘cherry’]
    bmDefault: m.sortBookmarks([bm('banana'), bm('apple')], 'default').map((x) => x.name), // ['banana','apple']
  };
}
```

Expected exactly:
- `default` → `['B-cat','A-cat','Uncategorized']`
- `name` → `['A-cat','B-cat','Uncategorized']`
- `date_added` → `['A-cat','B-cat','Uncategorized']`
- `last_used` → `['B-cat','A-cat','Uncategorized']`
- `bmNames` → `['apple','banana','cherry']`
- `bmDefault` → `['banana','apple']`

(Confirms: each mode orders categories correctly, `Uncategorized` pinned last despite newest dates, `default` preserves input order, and bookmark-level sort still works.)

- [ ] **Step 3: Visual smoke (read-only, optional)**

In the running app, open Bookmarks, switch the Sort dropdown across the four modes, and confirm the **category headers** reorder (name → alphabetical; date modes → by newest; default → manual order). This only reads — it does not mutate bookmarks.

- [ ] **Step 4: Stop the dev server and clean up**

Stop the vite process on 5199. Remove any `.playwright-mcp/` scratch dir so the tree stays clean (`git status --short` should be empty).

- [ ] **Step 5: Final static gate**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit` → clean.

---

## Done criteria

- `frontend/src/utils/bookmarkSort.ts` exists with `SortMode`, `sortBookmarks`, `sortCategoryEntries`.
- `BookmarkList.tsx` imports them; local `SortMode` + `sortBookmarks` removed (grep zero); category entries wrapped with `sortCategoryEntries`; both `sortBookmarks` call sites pass `sortMode`.
- `npx tsc --noEmit` clean.
- Playwright runtime check: all four category orders + bookmark order match expected; `Uncategorized` last; `default` unchanged.
- Two commits on `main` (util / wiring).
