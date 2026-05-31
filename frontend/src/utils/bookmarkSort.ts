export type SortMode = 'default' | 'name' | 'date_added' | 'last_used';

/** Minimal shape the sort comparators read. */
interface SortableBookmark {
  name: string;
  created_at?: string;
  last_used_at?: string;
}

// Must match the bucket key the caller groups uncategorized bookmarks under
// (BookmarkList builds bookmarksByCategory['Uncategorized']).
const UNCATEGORIZED = 'Uncategorized';

/** Sort bookmarks within one category by the active mode. Non-'default' modes
 *  return a sorted copy; 'default' returns the input array unchanged (by
 *  reference) for efficiency. The input is never mutated — treat the result as
 *  read-only, since in 'default' mode it is the input. */
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
