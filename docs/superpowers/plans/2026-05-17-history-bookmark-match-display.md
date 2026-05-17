# History Bookmark-Match Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a "Recent destinations" history row's coordinates exactly match an existing bookmark, render the row with the bookmark's name + `BookmarkGeoLine`, and disable "Add to bookmarks" in the context menu so the user can't create a duplicate.

**Architecture:** Build a memoized `Map<string, BookmarkPin>` in `MapView` keyed by `${lat.toFixed(5)}|${lng.toFixed(5)}`. Each history row and the context menu's "Add to bookmarks" item do a single `Map.get` lookup. The matched render swaps line 1 to `bookmark.name` and line 2 to `<BookmarkGeoLine /> · ${agoLabel}`; the unmatched render is unchanged. The disabled menu item mirrors the existing "device disconnected" disabled-item visual pattern. `App.tsx` extends its `bookmarkPins` builder to forward `city` / `timezone` from `bm.bookmarks`, and wraps the builder in `useMemo` so MapView's lookup memo isn't invalidated every render.

**Tech Stack:** React 18 + TypeScript + Vite (frontend lives in `frontend/`). No automated test suite — gates are `tsc --noEmit` + `npm run build` + manual smoke test.

**Spec:** `docs/superpowers/specs/2026-05-17-history-bookmark-match-display-design.md` (commit `c350bd3`).

---

## File Structure

All changes in `frontend/`. No new files.

| File | Why it changes |
|------|----------------|
| `frontend/src/i18n/strings.ts` | Add `map.already_bookmarked` (zh: `已加入書籤`, en: `Already bookmarked`). |
| `frontend/src/components/MapView.tsx` | (1) Import `useMemo` from React and `BookmarkGeoLine`. (2) `bookmarkPins` prop type adds optional `city?: string; timezone?: string`. (3) New `bookmarkByCoord` `useMemo` near the top of the function body. (4) Each recent row computes `match = bookmarkByCoord.get(key)` and conditionally renders line 1 + line 2. (5) Context menu's "Add to bookmarks" item computes `ctxMatch` from the same lookup and renders a disabled "Already bookmarked" variant when set. |
| `frontend/src/App.tsx` | The inline `bm.bookmarks.map(...)` that builds `bookmarkPins` (around line 2084) is hoisted into a `useMemo` keyed on `bm.bookmarks`; the map closure also forwards `city` and `timezone`. |

---

## Task 1: Add `map.already_bookmarked` i18n string

**Files:**
- Modify: `frontend/src/i18n/strings.ts`

Smallest, no dependencies, unblocks Task 5.

- [ ] **Step 1: Add the string**

Find the existing entry:

```ts
  'map.add_bookmark': { zh: '加入座標收藏', en: 'Add to bookmarks' },
```

Insert the new entry directly after it:

```ts
  'map.add_bookmark': { zh: '加入座標收藏', en: 'Add to bookmarks' },
  'map.already_bookmarked': { zh: '已加入書籤', en: 'Already bookmarked' },
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/strings.ts
git commit -m "i18n: add map.already_bookmarked string"
```

---

## Task 2: Extend `bookmarkPins` prop type in MapView with optional `city` / `timezone`

**Files:**
- Modify: `frontend/src/components/MapView.tsx:86`

Pure type-only change. No runtime effect until Task 4 reads the new fields.

- [ ] **Step 1: Edit the prop type**

In `frontend/src/components/MapView.tsx`, find line 86:

```ts
  bookmarkPins?: Array<{ id?: string; name: string; lat: number; lng: number; country_code?: string }>;
```

Replace with:

```ts
  bookmarkPins?: Array<{
    id?: string;
    name: string;
    lat: number;
    lng: number;
    country_code?: string;
    // Populated by the backend reverse-geocode reconciliation sweep.
    // Used to render the BookmarkGeoLine on matched history rows; may
    // be absent for freshly-saved bookmarks not yet reconciled.
    city?: string;
    timezone?: string;
  }>;
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output. Existing call sites (App.tsx line 2084) don't pass `city` / `timezone` yet — that's fine, they're optional.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/MapView.tsx
git commit -m "refactor(map): allow bookmarkPins to carry city/timezone"
```

---

## Task 3: Hoist `bookmarkPins` into `useMemo` in App.tsx + forward `city` / `timezone`

**Files:**
- Modify: `frontend/src/App.tsx:2084-2086` (the inline builder) + add a new `useMemo` block above the JSX

This is load-bearing for performance. Without the `useMemo`, MapView's `bookmarkByCoord` memo (added in Task 4) would rebuild on every render because `bookmarkPins` would be a fresh array reference each time.

- [ ] **Step 1: Find the existing inline builder**

In `frontend/src/App.tsx`, around line 2084, the current call site is:

```tsx
          bookmarkPins={bm.bookmarks.map((b: any) => ({
            id: b.id, name: b.name, lat: b.lat, lng: b.lng, country_code: b.country_code || '',
          }))}
```

- [ ] **Step 2: Hoist into a `useMemo` and forward the new fields**

Just before the `return (` of the App component (search for a good neighbor — e.g. near other top-level `useCallback` / `useMemo` blocks in App.tsx; if unsure, place it immediately above the JSX `return`), declare:

```ts
  // Memoized so MapView's bookmarkByCoord lookup memo isn't invalidated
  // on every parent render. Re-derives only when bm.bookmarks changes.
  const bookmarkPins = useMemo(
    () => bm.bookmarks.map((b: any) => ({
      id: b.id,
      name: b.name,
      lat: b.lat,
      lng: b.lng,
      country_code: b.country_code || '',
      city: b.city || undefined,
      timezone: b.timezone || undefined,
    })),
    [bm.bookmarks]
  )
```

Replace the inline expression at the `<MapView>` call site:

```tsx
          bookmarkPins={bm.bookmarks.map((b: any) => ({
            id: b.id, name: b.name, lat: b.lat, lng: b.lng, country_code: b.country_code || '',
          }))}
```

with:

```tsx
          bookmarkPins={bookmarkPins}
```

If `useMemo` is not already imported, add it to the existing React import line at the top of `App.tsx` (e.g. `import React, { useState, useEffect, useCallback, useMemo } from 'react'`).

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output.

- [ ] **Step 4: Production build (catch unused-import issues if any)**

```bash
cd frontend && npm run build
```

Expected: `✓ built in <time>s`. Pre-existing dynamic-import warning unchanged.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "refactor(app): memoize bookmarkPins and forward city/timezone"
```

---

## Task 4: MapView — `bookmarkByCoord` memo + matched-row render

**Files:**
- Modify: `frontend/src/components/MapView.tsx` — import section, function-body memo, recent-row inner render

This task wires the matched layout end-to-end. After this task, history rows whose coords match a bookmark show `bookmark.name` + `BookmarkGeoLine · agoLabel`; unmatched rows are untouched.

- [ ] **Step 1: Add `useMemo` to the React import and import `BookmarkGeoLine`**

Find line 1:

```ts
import React, { useRef, useEffect, useLayoutEffect, useState, useCallback } from 'react';
```

Replace with:

```ts
import React, { useRef, useEffect, useLayoutEffect, useState, useCallback, useMemo } from 'react';
```

Find the import block (lines 1–11 area) and add a new import for `BookmarkGeoLine`. The simplest placement is right after the existing `parseCoord` import at line 10:

```ts
import { parseCoord } from '../utils/coords';
```

becomes:

```ts
import { parseCoord } from '../utils/coords';
import { BookmarkGeoLine } from './BookmarkGeoLine';
```

- [ ] **Step 2: Add the `bookmarkByCoord` memo**

The function body starts at line 283 (`}) => {`). The first content lines are 284–289 (a comment block about dual-mode rendering). Insert the memo just after the destructure block ends and before that comment block. So at line 284, insert:

```ts
  // Lookup: bookmark coords → bookmark pin. Used by recent-history rows
  // and the context-menu's Add Bookmark item to detect matches.
  // toFixed(5) gives ~1m precision and avoids float drift in comparisons.
  const bookmarkByCoord = useMemo(() => {
    const m = new Map<string, NonNullable<typeof bookmarkPins>[number]>();
    if (bookmarkPins) {
      for (const bm of bookmarkPins) {
        m.set(`${bm.lat.toFixed(5)}|${bm.lng.toFixed(5)}`, bm);
      }
    }
    return m;
  }, [bookmarkPins]);

```

- [ ] **Step 3: Render the matched / unmatched variant per row**

The recent row's existing line-1 and line-2 render lives at `MapView.tsx:2369-2379` inside the re-fly `<button>`:

```tsx
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{
                            fontSize: 13, fontWeight: 500,
                            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                          }}>{display}</div>
                          <div style={{
                            fontSize: 10, opacity: 0.55, fontFamily: 'monospace', marginTop: 2,
                          }}>
                            {entry.lat.toFixed(5)}, {entry.lng.toFixed(5)} · {agoLabel}
                          </div>
                        </div>
```

Replace with:

```tsx
                        <div style={{ minWidth: 0, flex: 1 }}>
                          {(() => {
                            // If this entry's coords match an existing
                            // bookmark, show the bookmark's name + geo
                            // line so the row reads like a bookmark
                            // entry while keeping the kind badge + time
                            // (those are history-specific).
                            const match = bookmarkByCoord.get(
                              `${entry.lat.toFixed(5)}|${entry.lng.toFixed(5)}`
                            );
                            if (match) {
                              const hasGeo = !!(match.country_code || match.city || match.timezone);
                              return (
                                <>
                                  <div style={{
                                    fontSize: 13, fontWeight: 500,
                                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                                  }}>{match.name}</div>
                                  <div style={{
                                    fontSize: 10, marginTop: 2,
                                    display: 'flex', alignItems: 'center', gap: 4,
                                    minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden',
                                  }}>
                                    <BookmarkGeoLine
                                      countryCode={match.country_code}
                                      city={match.city}
                                      timezone={match.timezone}
                                    />
                                    {hasGeo && <span style={{ opacity: 0.55 }}>·</span>}
                                    <span style={{ opacity: 0.55, fontFamily: 'monospace' }}>{agoLabel}</span>
                                  </div>
                                </>
                              );
                            }
                            return (
                              <>
                                <div style={{
                                  fontSize: 13, fontWeight: 500,
                                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                                }}>{display}</div>
                                <div style={{
                                  fontSize: 10, opacity: 0.55, fontFamily: 'monospace', marginTop: 2,
                                }}>
                                  {entry.lat.toFixed(5)}, {entry.lng.toFixed(5)} · {agoLabel}
                                </div>
                              </>
                            );
                          })()}
                        </div>
```

Why these choices:
- IIFE keeps the conditional close to the existing layout without lifting state or computing match outside the row map (which would force restructuring the surrounding `recentPlaces.map` body).
- Outer `<div>` styling is unchanged. Only the inner two `<div>`s switch.
- The matched line-2 wrapper omits the global `opacity: 0.55` so `BookmarkGeoLine` (which carries its own `opacity: 0.55`) doesn't double up to `0.30`. The `·` separator and `agoLabel` get explicit `opacity: 0.55` to keep them dim like the unmatched layout.
- `hasGeo` gates the `· ` separator so a not-yet-reconciled bookmark renders cleanly as just `name / agoLabel`.

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output.

- [ ] **Step 5: Production build**

```bash
cd frontend && npm run build
```

Expected: `✓ built in <time>s`. Pre-existing dynamic-import warning unchanged.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/MapView.tsx
git commit -m "feat(map): show bookmark name + geo on matched history rows"
```

---

## Task 5: Disable "Add to bookmarks" when the coord matches a bookmark

**Files:**
- Modify: `frontend/src/components/MapView.tsx:2621-2636` (the Add to bookmarks menu item)

Reuses the `bookmarkByCoord` memo from Task 4. Applies to all 3 trigger sources (map right-click, history row right-click, history `⋮` click) because they all populate `contextMenu.lat` / `lng` consistently.

- [ ] **Step 1: Replace the menu item**

The current "Add to bookmarks" item lives at lines 2621–2636:

```tsx
          {/* 5. Add to bookmarks. */}
          <div
            className="context-menu-item"
            style={contextMenuItemStyle}
            onMouseEnter={highlightItem}
            onMouseLeave={unhighlightItem}
            onClick={() => {
              onAddBookmark(contextMenu.lat, contextMenu.lng, contextMenu.name);
              closeContextMenu();
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
              <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
            </svg>
            {t('map.add_bookmark')}
          </div>
```

Replace with:

```tsx
          {/* 5. Add to bookmarks — disabled when the coord matches an
              existing bookmark, to prevent duplicates. Visual mirrors
              the device-disconnected disabled item above. */}
          {(() => {
            const ctxMatch = bookmarkByCoord.get(
              `${contextMenu.lat.toFixed(5)}|${contextMenu.lng.toFixed(5)}`
            );
            if (ctxMatch) {
              return (
                <div
                  style={{ ...contextMenuItemStyle, color: '#9499ac', cursor: 'not-allowed', opacity: 0.75 }}
                  title={ctxMatch.name}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                    <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
                  </svg>
                  {t('map.already_bookmarked')}
                </div>
              );
            }
            return (
              <div
                className="context-menu-item"
                style={contextMenuItemStyle}
                onMouseEnter={highlightItem}
                onMouseLeave={unhighlightItem}
                onClick={() => {
                  onAddBookmark(contextMenu.lat, contextMenu.lng, contextMenu.name);
                  closeContextMenu();
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                  <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
                </svg>
                {t('map.add_bookmark')}
              </div>
            );
          })()}
```

Why these choices:
- Disabled visual mirrors the existing "device disconnected" item (`{ ...contextMenuItemStyle, color: ..., cursor: 'not-allowed', opacity: 0.75 }`), but uses a neutral grey `#9499ac` instead of the red `#ff6b6b` — "this is already done" is informational, not an error.
- `title={ctxMatch.name}` gives a hover tooltip showing which bookmark — small polish, helps when multiple bookmarks share visually similar names.
- No `onClick`, no `onMouseEnter`/`Leave` highlight handlers on the disabled variant — feels inert, matches the device-disconnected pattern.
- The matched branch omits the `className="context-menu-item"` to skip the CSS hover-highlight defined for that class.

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output.

- [ ] **Step 3: Production build**

```bash
cd frontend && npm run build
```

Expected: `✓ built in <time>s`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/MapView.tsx
git commit -m "feat(map): disable Add Bookmark when coord matches a bookmark"
```

---

## Task 6: Manual smoke test

**Files:** none

No automated test suite — verification is on the dev server per spec §6.

- [ ] **Step 1: Start the dev server**

```bash
cd frontend && npm run dev
```

Open the printed URL (typically `http://localhost:5173`) in a browser, or `npm start` to also launch Electron.

- [ ] **Step 2: Walk through the verification matrix**

For each check, confirm the observed behavior matches Expected:

| # | Action | Expected |
|---|--------|----------|
| 1 | Save a bookmark for a recognized address (e.g. Tokyo Tower via search). Open Recent dropdown. | Row that flew there now shows `bookmark.name` on line 1 and `flag · country · city · GMT · 5 mins ago` on line 2. Kind badge unchanged. ⋮ button unchanged. |
| 2 | Right-click that row OR click its ⋮. | Context menu opens. "Add to bookmarks" item is replaced by disabled "已加入書籤 / Already bookmarked" with `cursor: not-allowed`, slightly dimmed, can't click. Tooltip shows the bookmark name. |
| 3 | Right-click on the map at the exact coords of an existing bookmark pin. | Same disabled "已加入書籤" affordance. |
| 4 | Right-click anywhere NOT matching a bookmark (history row or map). | "Add to bookmarks" works normally; dialog opens. |
| 5 | Delete the bookmark from BookmarkList, then re-open Recent dropdown. | The row reverts to unmatched layout: `[kind] entry.name OR coords / lat,lng · agoLabel`. The menu item is "Add to bookmarks" again, enabled. |
| 6 | Rename the bookmark in BookmarkList. | Recent dropdown row's line 1 updates to the new name on next render (re-open the dropdown if it was open). |
| 7 | Save a bookmark for a coord whose `country_code`/`city`/`timezone` aren't yet reconciled (or temporarily edit one to clear those fields). | Matched row shows `bookmark.name` on line 1, just `agoLabel` on line 2 with no leading `· ` separator. |
| 8 | All other map and recent-list behaviors (left-click re-fly, ⋮ menu actions, map right-click for non-matched coords, Add waypoint in route mode, etc.). | No regressions. |

- [ ] **Step 3: Stop the dev server**

`Ctrl-C` the foreground process.

- [ ] **Step 4: (no commit — manual-test task)**

This task has no code changes. If smoke test surfaces defects, fix them in a follow-up task with its own commit.

---

## Out of scope (do not implement here)

Per spec §3 / §8 — do **not** sneak these in:

- Fuzzy / radius matching, configurable match precision.
- A category color dot on the matched row in addition to the kind badge.
- Click-through navigation from a matched row to its BookmarkList entry.
- Letting the disabled menu item open the Edit Bookmark dialog directly.
- Extracting a shared `<MatchedLocationRow>` component used by both BookmarkList and the history dropdown.
- Touching `frontend/src/hooks/useBookmarks.ts`'s `Bookmark` interface to add `country_code` / `city` / `timezone` typing (the codebase uses `(b: any)` cast elsewhere — match that pattern; cleanup is out of scope).
