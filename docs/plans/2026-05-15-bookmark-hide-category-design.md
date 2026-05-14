# Bookmark — Hide Category + Move-To Scrollbar — Design

**Date:** 2026-05-15
**Status:** Approved (design) — pending spec review, then implementation plan

## Problem

Two issues in the bookmark panel (`frontend/src/components/BookmarkList.tsx`):

1. **No way to temporarily hide a category.** A user with many categories has a
   cluttered panel. Categories can be *collapsed* (header stays, items hidden) but
   not *hidden* (header + items gone from view). The user wants to declutter the
   browse view and bring categories back on demand.
2. **The "move to category" list has no scrollbar.** The bookmark context menu's
   "move to" section (`BookmarkList.tsx` ~line 1446-1477) renders every category
   as a flat list inside a `createPortal` menu whose container has `minWidth` but
   no `maxHeight` / `overflow`. With many categories the list runs off-screen and
   the lower entries are unreachable.

## Scope

Both fixed together in one PR. Frontend-led; #1 also touches the backend
ui-state persistence.

---

## #1 — Hide category temporarily

### State & persistence

A new per-device list `bookmark_hidden_categories`, mirroring the existing
`bookmark_expanded_categories` exactly:

- **Storage:** `~/.locwarp/settings.json` — *not* iCloud-synced. Hiding is a
  personal view preference; it must not propagate to other machines.
- **Backend `AppState`** (`backend/main.py`): add `_bookmark_hidden_categories`,
  loaded in `_load_settings` from `data.get("bookmark_hidden_categories")` and
  written in `save_settings` alongside `bookmark_expanded_categories`.
- **Endpoint** (`backend/api/bookmarks.py`): extend `BookmarkUiState` with
  `hidden_categories: list[str] | None = None`. `GET /api/bookmarks/ui-state`
  also returns `hidden_categories`. `POST /api/bookmarks/ui-state` updates each
  field **only when present** (`is not None`) — so the frontend can send a
  partial update (just expanded, just hidden, or both) without one clobbering
  the other.
- **Frontend api** (`frontend/src/services/api.ts`): `getBookmarkUiState`
  returns `{ expanded_categories, hidden_categories }`. `setBookmarkUiState`
  accepts a partial `{ expanded_categories?, hidden_categories? }` and POSTs
  only the keys provided.

### UI behaviour (`BookmarkList.tsx`)

- **New state:** `hidden: Set<string>`, keyed by the same category key the
  existing `collapsed` map uses (the `cat` value from `bookmarksByCategory`).
- **Hide trigger:** an eye-off icon button on the category header row (the
  `<div>` at ~line 1119, beside the collapse chevron / count). Appears on
  hover. `onClick` adds the category to `hidden` and calls `stopPropagation()`
  so it does not also toggle collapse.
- **Render:** the bookmark-groups loop (`~line 1106`,
  `Object.entries(bookmarksByCategory).map`) skips any category in `hidden`.
- **Unhide affordance:** after the groups, when `hidden.size > 0` and not
  searching, render a collapsible row `N 個已隱藏 ▸/▾`. Expanding it lists each
  hidden category name + an eye icon; clicking the icon removes that category
  from `hidden` (restores it). This fully declutters — hidden categories leave
  no trace in the main list.
- **Persistence:** every hide / unhide calls
  `setBookmarkUiState({ hidden_categories: [...] })`, best-effort (`.catch`).
  On mount, `getBookmarkUiState` seeds both `expanded` and `hidden`.
- **Search interaction:** none. The groups only render when
  `search.trim() === ''`; search results are a separate code path that shows
  every match. Hiding therefore only affects the browse view — a hidden
  category's bookmarks are still found by search. The unhide row follows the
  same `search.trim() === ''` condition as the groups.
- **Stale cleanup:** on load and on render, intersect `hidden` with the current
  category set so a since-deleted category never lingers in the persisted list
  or the unhide row.

### Edge cases

- The `default` category may be hidden like any other — hiding is harmless
  (unlike delete, which is blocked for `default`).
- `multiSelect` mode: hidden categories' bookmarks are not rendered, so
  select-all / per-category checkboxes naturally exclude them. No extra work.
- The auto-collapse threshold (`bookmarks.length > AUTO_COLLAPSE_THRESHOLD`)
  is left unchanged — it governs collapse defaults, orthogonal to hide.

---

## #2 — Scrollbar on the move-to-category list

In the bookmark context menu (`BookmarkList.tsx`, `createPortal`, ~line
1446-1477), wrap the `categories.filter(...).map(...)` "move to" entries in a
scroll container: `maxHeight: 240` + `overflowY: 'auto'`. The fixed menu items
(Edit / Copy / Delete / the "move to" label) stay outside the scroll region so
only the category list scrolls. No backend change.

---

## Files touched

| File | Change |
|------|--------|
| `backend/main.py` | `AppState._bookmark_hidden_categories` — load in `_load_settings`, write in `save_settings` |
| `backend/api/bookmarks.py` | `BookmarkUiState.hidden_categories`; GET returns it; POST does per-field (`is not None`) updates |
| `frontend/src/services/api.ts` | `getBookmarkUiState` / `setBookmarkUiState` carry `hidden_categories` (partial updates) |
| `frontend/src/components/BookmarkList.tsx` | `hidden` state; header eye-off button; skip hidden groups; "N 個已隱藏" unhide row; seed/persist hidden; stale cleanup; scrollable move-to list (#2) |

## Testing

- **Backend:** unit tests for the extended ui-state endpoint — POST with only
  `hidden_categories` does not clear `expanded_categories` and vice versa; GET
  returns both; `AppState` round-trips `bookmark_hidden_categories` through
  `save_settings` / `_load_settings`.
- **Frontend:** no test harness change; verify in the browser — hide a
  category (it leaves the list), the "N 個已隱藏" row appears, unhiding restores
  it, the state survives a reload, and the move-to list scrolls with many
  categories.
