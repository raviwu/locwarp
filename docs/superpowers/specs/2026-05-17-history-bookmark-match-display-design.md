# History Row — Bookmark Match Display — Design

**Date:** 2026-05-17
**Status:** Draft (pending user review)
**Author:** Ravi Wu
**Type:** Feature design

---

## 1. Background

The "Recent destinations" history dropdown in `MapView` (the feature shipped in
`docs/superpowers/specs/2026-05-17-history-context-menu-design.md`) currently
renders each entry as `[kind badge] name-or-coords / coords · timeAgo`. The
name comes from the entry itself — typically the search query for `search`
entries, or empty for `teleport` / `coord_*` entries (in which case the
`lat, lng` is shown as a fallback).

Bookmarks, by contrast, render in the BookmarkList as `[category color dot]
bookmark.name / <BookmarkGeoLine flag · country · city · GMT>`. The geo line
is a reusable component (`BookmarkGeoLine.tsx`) populated from the bookmark's
`country_code` / `city` / `timezone` fields, which are populated during the
reverse-geocode reconciliation sweep that runs in the background.

Today, if the user flies to "Tokyo Tower" (saved as a bookmark) via address
search and later opens the history dropdown, that row shows
`【地址】 Tokyo Tower / 35.67620, 139.65030 · 5 mins ago`. Useful, but it
ignores that the location is already a recognized bookmark with a richer
display style. The user sees one piece of metadata in the bookmark list and a
different, less informative line in history for the same place.

## 2. Goals

- When a history entry's coordinates match an existing bookmark, show the
  bookmark's name and geo info (`BookmarkGeoLine`) on that row, so the user
  recognizes "this is my saved place" at a glance.
- Preserve what's unique to history: the **kind badge** (Teleport / Navigate
  / Search / Coord) and the **time-ago label** stay visible — that's the
  history dimension the bookmark list doesn't carry.
- Prevent the user from creating a duplicate bookmark by clicking
  "Add to bookmarks" on a row (or map pin) that already corresponds to one.
- Keep the change small: exact coord matching, no fuzzy / radius logic, no
  storage changes, no new components.

## 3. Non-goals

- Fuzzy / radius matching. Two history entries 5m apart are still two
  distinct rows; the user can dedupe by saving a bookmark at the canonical
  location.
- Letting the matched row's `⋮` menu open the bookmark in the BookmarkList
  (no cross-tab navigation, no edit-bookmark shortcut). The "Add to
  bookmarks" item simply turns into a disabled "Already bookmarked"
  indicator.
- Showing the bookmark's category color dot on the history row in addition
  to the kind badge. (User chose layout B in brainstorming, which keeps the
  kind badge and omits the color dot to avoid visual clutter.)
- Updating BookmarkList — no changes there.

## 4. Design

### 4.1 Match definition

A history entry matches a bookmark iff
`entry.lat.toFixed(5) === bookmark.lat.toFixed(5)` AND
`entry.lng.toFixed(5) === bookmark.lng.toFixed(5)`.

`toFixed(5)` gives ~1m precision — plenty to disambiguate locations the user
cares about. Float comparison via fixed-decimal strings avoids the usual
`1e-7` drift problems and matches the precision the rest of the UI already
displays.

If two bookmarks happen to share the same coords (extremely rare), the last
one inserted into the lookup map wins. Documented; not worth special-casing.

### 4.2 Lookup index

Inside `MapView`, derive a memoized map:

```ts
const bookmarkByCoord = useMemo(() => {
  const m = new Map<string, BookmarkPin>();
  for (const bm of bookmarkPins) {
    m.set(`${bm.lat.toFixed(5)}|${bm.lng.toFixed(5)}`, bm);
  }
  return m;
}, [bookmarkPins]);
```

This rebuilds only when `bookmarkPins` changes (which already happens on
bookmark create/edit/delete via the existing wiring). Recent-list row render
becomes a single `Map.get` per row.

### 4.3 Matched row layout

For each row, look up `match = bookmarkByCoord.get(\`${entry.lat.toFixed(5)}|${entry.lng.toFixed(5)}\`)`.

If `match` is **undefined** (no match): render the existing layout
unchanged.

If `match` is **defined**:

- Kind badge: **unchanged** (still `recent.kind_teleport` / `navigate` /
  `search` / `coord`).
- Line 1: **`match.name`** (overrides `entry.name` or the
  `${lat}, ${lng}` fallback). Wraps in the same `whiteSpace: nowrap;
  overflow: hidden; text-overflow: ellipsis` span as today.
- Line 2: **`<BookmarkGeoLine countryCode={match.country_code} city={match.city} timezone={match.timezone} /> · {agoLabel}`** — the existing component, followed inline by ` · ${agoLabel}` (per user choice in brainstorming). The
  `agoLabel` keeps the same fontSize / opacity styling as today.
- `⋮` icon button on the right: **unchanged**.

If `match.country_code` / `city` / `timezone` are all missing (the bookmark
hasn't been reconciled yet), `BookmarkGeoLine` already collapses to `null`
internally — the row gracefully falls back to just `bookmark.name` on line 1
and `· {agoLabel}` on line 2 (or we drop the leading `· ` when GeoLine
renders nothing — see §4.5 implementation note).

### 4.4 Duplicate prevention in the context menu

The same lookup is reused in the **"Add to bookmarks"** item of the context
menu, regardless of how the menu was opened (right-click on map, right-click
on history row, click on `⋮`):

```ts
const ctxMatch = bookmarkByCoord.get(
  `${contextMenu.lat.toFixed(5)}|${contextMenu.lng.toFixed(5)}`
);
```

- If `ctxMatch` is **undefined** (no existing bookmark): item is enabled,
  label is `t('map.add_bookmark')` — current behavior.
- If `ctxMatch` is **defined**: item is **disabled** (cannot click, no
  `onClick`), label switches to `t('map.already_bookmarked')`
  (zh: `已加入書籤`, en: `Already bookmarked`), visual style matches the
  existing "device disconnected" disabled item already present at
  `MapView.tsx:2516-2524` (red color + `cursor: not-allowed` +
  `opacity: 0.75` — proven pattern).

Bonus: this also catches the case where the user right-clicks **on the map**
at the exact coords of an existing bookmark pin — same disabled affordance,
no special-casing required.

### 4.5 Layout edge case — when GeoLine renders null

`BookmarkGeoLine` returns `null` when both `countryCode` is falsy AND
`textParts` (country / city / GMT) is empty. In that case the `· ` separator
preceding `agoLabel` should not appear — line 2 becomes just `agoLabel`. The
cleanest implementation:

```tsx
<div style={{ fontSize: 10, opacity: 0.55, fontFamily: 'monospace', marginTop: 2,
              display: 'flex', alignItems: 'center', gap: 4 }}>
  <BookmarkGeoLine countryCode={match.country_code} city={match.city} timezone={match.timezone} />
  {hasGeo && <span>·</span>}
  <span>{agoLabel}</span>
</div>
```

where `hasGeo = !!(match.country_code || match.city || match.timezone)` (a
small boolean computed alongside `match`). Avoids stranded separator and
matches the conditional-segment style `BookmarkGeoLine` already uses.

### 4.6 Data plumbing

`App.tsx` builds `bookmarkPins` for `<MapView />` from `bm.bookmarks` (line
~2079). Today's map call:

```ts
bookmarkPins={bm.bookmarks.map((b: any) => ({
  id: b.id, name: b.name, lat: b.lat, lng: b.lng, country_code: b.country_code || '',
}))}
```

Extended to:

```ts
bookmarkPins={bm.bookmarks.map((b: any) => ({
  id: b.id, name: b.name, lat: b.lat, lng: b.lng,
  country_code: b.country_code || '',
  city: b.city || undefined,
  timezone: b.timezone || undefined,
}))}
```

`MapView`'s `bookmarkPins` prop type gains two new optional fields:

```ts
bookmarkPins?: Array<{
  id?: string;
  name: string;
  lat: number;
  lng: number;
  country_code: string;
  city?: string;
  timezone?: string;
}>;
```

No backend / storage changes. The fields are already on `bm.bookmarks`
(populated by the reverse-geocode reconciliation sweep).

## 5. Files touched

| File | What changes |
|------|--------------|
| `frontend/src/App.tsx` | (1) `bookmarkPins` mapping (one block, ~line 2079) gains `city` and `timezone` fields. (2) Hoist the `bm.bookmarks.map(...)` expression into a `useMemo([bm.bookmarks])` and pass the memoized value to `<MapView bookmarkPins={...}/>` — required so MapView's `bookmarkByCoord` memo isn't invalidated every render. See §7 risks. |
| `frontend/src/components/MapView.tsx` | (1) `bookmarkPins` prop type gains optional `city?: string; timezone?: string`. (2) New `useMemo` for `bookmarkByCoord` after `bookmarkPins` destructure. (3) Each recent-row render computes `match`; switches between matched / unmatched layout for line-1 and line-2. (4) `import { BookmarkGeoLine } from './BookmarkGeoLine';`. (5) Context menu's "Add to bookmarks" item computes `ctxMatch` and renders the disabled "already bookmarked" variant when matched (visually mirroring the existing "device disconnected" disabled item). |
| `frontend/src/i18n/strings.ts` | New string `map.already_bookmarked` (zh: `已加入書籤`, en: `Already bookmarked`). |

No new files, no backend changes, no storage changes.

## 6. Testing

Frontend has no automated test suite (`frontend/package.json` defines only
`dev` / `build` / `electron` / `dist`). Verification is manual against the
dev server.

Automated gates: `cd frontend && npx tsc --noEmit` clean, `npm run build`
green.

Manual matrix:

1. Save a bookmark for an address (e.g. Tokyo Tower via search). Open the
   recent dropdown — the row that flew there matches: shows `Tokyo Tower`
   on line 1 and `🇯🇵 Japan · Tokyo · GMT+9 · 5 mins ago` on line 2.
2. Right-click that row or click its `⋮`. The "Add to bookmarks" item shows
   `已加入書籤` (zh) / `Already bookmarked` (en), disabled state, can't
   click.
3. Right-click on the map at the exact coords of an existing bookmark pin —
   same disabled "已加入書籤" affordance.
4. Right-click anywhere not matching a bookmark — "Add to bookmarks" works
   normally, dialog seeds correctly.
5. Delete the bookmark via BookmarkList. Open the recent dropdown — the
   row reverts to unmatched layout (`Tokyo Tower / 35.67620, 139.65030 ·
   5 mins ago`). "Add to bookmarks" in its menu becomes enabled again.
6. Rename the bookmark — the row's line 1 updates automatically to the new
   name on next render.
7. Save a bookmark for a freshly-resolved point so its `country_code` /
   `city` / `timezone` are all empty (the reconciliation sweep hasn't
   reached it yet). The matched row should show `bookmark.name / agoLabel`
   with no leading `· ` separator.
8. Existing map right-click flow, history left-click re-fly, context menu
   for unmatched rows — no regressions.

## 7. Risks and rollback

- **Risk: `useMemo` rebuilds too often.** `bookmarkPins` is derived inline
  inside the JSX in `App.tsx` — it's a new array reference on every render.
  This would cause `bookmarkByCoord` to rebuild on every render, defeating
  the memo. Mitigation: lift the `bookmarkPins` array creation in `App.tsx`
  into its own `useMemo` keyed on `bm.bookmarks`, OR memoize
  `bookmarkByCoord` on `bookmarkPins.length` + a content hash. Easiest:
  hoist `bookmarkPins` into a `useMemo([bm.bookmarks])` in App.tsx. **The
  plan must include this hoist.**
- **Risk: GeoLine layout drift.** `BookmarkGeoLine` is currently used
  inside BookmarkList rows with specific parent flex / opacity. In history
  rows the parent is a column-flex `div` with `marginTop: 2` and
  `opacity: 0.55` already applied. `BookmarkGeoLine` has its own
  `opacity: 0.55`, which would double up to `0.55² ≈ 0.30`. Mitigation:
  drop the outer line-2 `opacity: 0.55` when rendering the matched layout
  (let GeoLine carry it) so the visual matches the BookmarkList exactly.
  Plan should call this out.
- **Risk: Map right-click on a bookmark pin gets disabled before the user
  realizes why.** Mitigation: the label change to "已加入書籤" is the
  explanation. Add a `title` attribute on the disabled item that says
  something like "此座標已是書籤" / "This coordinate is already a
  bookmark" — minor polish; defer to implementation taste.
- **Rollback:** The change is additive and contained to 3 files. Reverting
  the diffs restores prior behavior. No data migration to undo.

## 8. Out of scope (revisit later)

- Fuzzy / radius matching, configurable match precision.
- Showing the bookmark's category color dot on the matched history row in
  addition to the kind badge.
- Navigating from a matched history row to the BookmarkList entry for
  that bookmark (e.g. clicking the bookmark name jumps to BookmarkList and
  scrolls to it).
- Letting the matched menu item open the Edit Bookmark dialog directly.
- Extracting a shared `<MatchedLocationRow>` component used by both
  BookmarkList and the history dropdown.
