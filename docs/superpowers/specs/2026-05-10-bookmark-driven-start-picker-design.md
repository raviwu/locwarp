# Bookmark-Driven Start Picker — Design

**Date:** 2026-05-10
**Status:** Draft (pending user review)
**Author:** Ravi Wu
**Type:** Feature design + targeted refactor

---

## 1. Background

LocWarp's simulation modes (RandomWalk, Joystick, Navigate, Loop, MultiStop) all
require a "current position" before they can start. That state is set only by
the Teleport action — connecting a device, opening the app, or pressing
"一鍵還原" leaves `currentPosition` as `null`.

Today, when a user selects RandomWalk, clicks Start, and has not yet teleported,
they get the toast `toast.no_position_random` ("尚未取得目前位置,無法產生
隨機路徑點") and no further guidance. The backend likewise hard-rejects the
request:

```
core/random_walk.py:58
if engine.current_position is None:
    raise RuntimeError("Cannot start random walk: no current position. Teleport first.")
```

The bookmark system already stores well-known coordinates with categories and
colors, but the user must navigate to the Library tab and click a bookmark there
before returning to the mode panel — friction that is amplified for users who
work from a small set of recurring locations.

In parallel, the GoldDitto panel has its own bookmark consumer for A and B
points: a free-text `lat,lng` input plus a 📚 button that opens
`BookmarkPickerPopover`. The B side also has Random-Taiwan and Use-Map-Center
helpers that pre-date the bookmark system. The B point is conceptually "the
user's real physical location" — a value that overlaps semantically with the
new "start position" we want to surface in other modes.

## 2. Goals

- In modes that require a current position (RandomWalk, Joystick, Navigate,
  Loop, MultiStop), let the user pick a bookmark inline as the starting point,
  without leaving the mode panel.
- Refactor the GoldDitto B-side to use the same inline bookmark dropdown,
  treating B as a bookmark-only field (no manual coord, no random, no
  map-center).
- Extract a single low-level `BookmarkDropdown` component shared by both call
  sites, so the picking experience stays consistent.

## 3. Non-Goals

- No backend changes. `random_walk` continues to require `current_position`;
  the picker fixes the UX gap, not the constraint.
- No new persistence concept beyond the existing bookmark store. The "memory"
  of nearby locations is the bookmark list itself.
- No change to the GoldDitto A side. A keeps its free-text input, popover, map
  right-click external setter, last-used category memory, and end-event
  cascade. A's flows depend on those features and are out of scope for this
  refactor.
- No auto-start. Picking a bookmark teleports; the user still presses Start
  themselves.
- No "remember last picked bookmark per mode" memory. Once a teleport happens
  the picker hides, so the affordance is naturally one-shot.
- No replacement of `BookmarkPickerPopover`. It remains in use by GoldDitto A.

## 4. Component Architecture

```
BookmarkDropdown                       // new, low-level, controlled
  ├── StartPositionPicker              // new, mode-panel use
  └── GoldDittoPanel B-side            // refactored to consume BookmarkDropdown
```

### 4.1 `BookmarkDropdown` (new)

**File:** `frontend/src/components/BookmarkDropdown.tsx`

Pure controlled component, no persistence or side-effects.

```ts
interface Bookmark {
  id?: string
  name: string
  lat: number
  lng: number
  category?: string
  category_id?: string
}

interface Category {
  id: string
  name: string
}

interface Props {
  bookmarks: Bookmark[]
  categories: Category[]            // display order, used as optgroup order
  value: string | null              // selected bookmark id; null = unselected
  onChange: (bm: Bookmark | null) => void
  placeholderText: string           // disabled placeholder option
  emptyText: string                 // shown when bookmarks.length === 0
  ariaLabel?: string
}
```

Rendering:

- When `bookmarks.length > 0`: `<select>` with one disabled placeholder option,
  followed by `<optgroup label={category.name}>` blocks in the order provided.
  Grouping key is `bookmark.category_id` (falling back to `bookmark.category`
  string when id is absent). Bookmarks whose category is unknown to the
  supplied `categories` list fall into a synthetic "其他 / Other" group at
  the end, labeled via a new i18n key `panel.bookmark_dropdown_other`.
- When `bookmarks.length === 0`: a single static line of muted text containing
  `emptyText`. No `<select>` rendered.
- Bookmarks without `id` get a synthetic key (`name + lat + lng`) for React;
  they are excluded from selection (`value` cannot match).

The component does not call `localStorage`, does not teleport, and does not
emit toast — those are caller concerns.

### 4.2 `StartPositionPicker` (new)

**File:** `frontend/src/components/StartPositionPicker.tsx`

Wraps `BookmarkDropdown` with mode-panel chrome.

```ts
interface Props {
  bookmarks: Bookmark[]
  categories: Category[]
  onPick: (lat: number, lng: number, name: string) => void
}
```

Rendering:

- Section title row: 📍 icon + i18n `panel.start_picker_label`.
- Inline `BookmarkDropdown` with:
  - `placeholderText` = i18n `panel.start_picker_placeholder`
  - `emptyText` = i18n `panel.start_picker_empty`
- Internal state: `selectedId: string | null`, reset to `null` after each
  `onChange`. The selection is fire-and-forget — once the parent teleports,
  `currentPosition` becomes non-null and the picker is unmounted.

The component does NOT decide when to show itself — that is the parent's
responsibility (see §4.4 below).

### 4.3 GoldDitto B-side refactor

**File:** `frontend/src/components/GoldDittoPanel.tsx`

Removed:

- The `<input type="text" placeholder="lat, lng">` for B.
- The `📚` button + ref + `openPicker('B', ...)` call.
- The "Random Taiwan" button (`handleRandomB`) and `randomTaiwanCoord()` helper.
- The "Use map center" button (`handleUseMapCenter`).
- The B branch inside `handlePick` and `handleCategoryChange`.
- `DEFAULT_B = '25.034897, 121.545827'`.
- `pickerCatB` state and its localStorage key `goldditto.picker.B.lastCategory`.

Added:

- A `BookmarkDropdown` for B with i18n `goldditto.b_picker_placeholder`
  / `goldditto.b_picker_empty`.
- New state `bBookmarkId: string | null`.
- Derived `b: { lat: number; lng: number } | null` from
  `bookmarks.find(bm => bm.id === bBookmarkId)`. If the bookmark has been
  deleted the lookup returns `undefined`, which collapses `b` to `null` and
  disables "② First try" automatically.

Storage migration:

- Old key: `goldditto.B` (string `"lat, lng"`, default `"25.034897, 121.545827"`).
- New key: `goldditto.B.bookmarkId` (bookmark id).
- On mount:
  1. Read `goldditto.B.bookmarkId`. If present and the id resolves to a
     bookmark, select it.
  2. Else, read legacy `goldditto.B`. Parse it as a coord and search the
     bookmark list for a match within tolerance `1e-5` on both lat and lng.
     If exactly one match, select that bookmark and write the new key.
     If zero or multiple matches, leave B unselected.
  3. After either path, delete the legacy `goldditto.B` key.

Cycle wiring:

- `cycleArgs` becomes `null` when `b` is `null`. The existing
  `disableFirstTry` already handles this via `!b`, so the user-facing change
  is "② First try" stays disabled until a B bookmark is picked.

A side: untouched. `aText`, `LS_A`, popover, `pickerCatA`, external setter,
end-event cascade, all remain.

### 4.4 ControlPanel integration

**File:** `frontend/src/components/ControlPanel.tsx` and `App.tsx`

ControlPanel today receives `bookmarkCategories: string[]` (names only,
App.tsx line 1482). BookmarkDropdown needs full `Category` objects to map
ids to display names. We add a new prop:

```ts
// ControlPanelProps
bookmarkCategoriesFull: { id: string; name: string }[]
```

App.tsx wires it from `bm.categories`:

```tsx
bookmarkCategoriesFull={bm.categories.map(c => ({ id: c.id, name: c.name }))}
```

The legacy `bookmarkCategories: string[]` prop stays — `BookmarkList` and
other consumers still use the name-only shape and changing those is out of
scope.

A single block inserted directly above `modeExtraSection`:

```tsx
const NEEDS_START_POS = new Set<SimMode>([
  SimMode.RandomWalk,
  SimMode.Joystick,
  SimMode.Navigate,
  SimMode.Loop,
  SimMode.MultiStop,
])

{NEEDS_START_POS.has(simMode) && !currentPosition && (
  <StartPositionPicker
    bookmarks={bookmarks}
    categories={bookmarkCategoriesFull}
    onPick={(lat, lng, name) => onTeleport(lat, lng, name)}
  />
)}
```

`onTeleport` is already a prop on ControlPanel (App.tsx line 1457 wires it to
`handleTeleport`, which handles single-device and group-mode pre-sync). The
picker passes the bookmark name through so existing recent-list logic
captures it.

GoldDitto mode (`SimMode.GoldDitto`) is intentionally absent from the set.
GoldDitto manages its own A/B coordinate flow.

## 5. i18n changes

**File:** `frontend/src/i18n/strings.ts`

Add:

| Key | zh | en |
|-----|----|----|
| `panel.start_picker_label` | 起點 | Start point |
| `panel.start_picker_placeholder` | 從書籤挑一個當起點 | Pick a bookmark to start from |
| `panel.start_picker_empty` | 尚無書籤,請先在地圖右鍵加書籤 | No bookmarks yet — right-click the map to add one |
| `goldditto.b_picker_placeholder` | 從書籤選 B 點 | Pick B from bookmarks |
| `goldditto.b_picker_empty` | 尚無書籤,B 點需先建立書籤 | No bookmarks yet — add one before setting B |
| `panel.bookmark_dropdown_other` | 其他 | Other |

Modify:

| Key | Before | After |
|-----|--------|-------|
| `goldditto.b_label` | B 座標 / B coord | B 真實位置(書籤) / B real location (bookmark) |

Delete (no remaining usage after refactor):

- `goldditto.random_b`
- `goldditto.use_map_center`
- `goldditto.pick_from_bookmarks_tooltip_b`

If any of these keys is referenced elsewhere, the implementation plan will
catch and resolve those before deletion.

## 6. Behavior matrix

| Scenario | Before | After |
|----------|--------|-------|
| RandomWalk + no currentPosition + click Start | Toast `no_position_random`, nothing else | Picker visible above mode controls. User can pick a bookmark inline; toast still fires if Start is pressed without picking. |
| RandomWalk + has currentPosition | Picker not present | Picker not present (unchanged) |
| Joystick / Navigate / Loop / MultiStop + no currentPosition | Mode-specific behavior (toast or silent no-op) | Picker visible; consistent inline affordance |
| GoldDitto B = manual coord typed in | Allowed | Not allowed; user must save the coord as a bookmark first |
| GoldDitto B = "Random Taiwan" button | Available | Removed |
| GoldDitto B = "Use map center" button | Available | Removed |
| GoldDitto B selected, source bookmark deleted | B keeps stale coord | B becomes `null`; "② First try" disabled until re-picked |
| GoldDitto upgrade with legacy `goldditto.B` matching a bookmark by coord | — | Auto-migrated to new key |
| GoldDitto upgrade with legacy `goldditto.B` not matching any bookmark | — | B unselected; user re-picks |

## 7. Testing

Component tests (Vitest + React Testing Library, matching existing patterns
under `frontend/src/components/__tests__/`):

- `BookmarkDropdown.test.tsx`
  - Renders one `<optgroup>` per category in supplied order.
  - Bookmarks without matching category appear in the synthetic "其他" group.
  - `onChange` fires with the selected bookmark object.
  - Empty state shows `emptyText` and no `<select>`.
- `StartPositionPicker.test.tsx`
  - Selecting a bookmark calls `onPick(lat, lng, name)` with that bookmark's
    fields.
  - Title row renders the i18n label.
  - Resets internal selection after `onPick`.
- `ControlPanel.test.tsx` additions
  - `StartPositionPicker` mounts iff `simMode ∈ NEEDS_START_POS &&
    !currentPosition`.
  - Does not mount in Teleport or GoldDitto modes.
  - Picking through it calls the `onTeleport` prop with the right args.
- `GoldDittoPanel.test.tsx` (new or extending existing)
  - Selecting a B bookmark sets `cycleArgs.lat_b` / `lng_b` to that bookmark's
    coords.
  - "② First try" disabled when no B selected; enabled after pick.
  - Migration: legacy `goldditto.B` matching a bookmark within `1e-5` is
    auto-selected; non-matching legacy value leaves B null and removes the
    legacy key.
  - Migration: legacy key is removed after being read regardless of outcome.

Manual smoke (post-implementation):

1. Fresh app, no teleport: switch to each of the five modes, verify picker
   appears, pick a bookmark, verify map + status reflect teleport, verify
   picker disappears.
2. GoldDitto: pick B, run "② First try", verify cycle goes to that B.
3. GoldDitto with a previously-stored legacy B that maps to an existing
   bookmark: open panel, verify B is preselected.
4. Group mode (≥2 devices connected): pick a bookmark via StartPositionPicker;
   verify both devices teleport.

## 8. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Existing GoldDitto users rely on Random-Taiwan or Map-Center for B | These features have no analog in the new flow. Documented as a behavior change in the PR description; users add a bookmark for their physical location once. |
| Legacy `goldditto.B` migration ambiguity (multiple bookmarks at same coord) | Migration only auto-selects on exactly one match. Zero or multiple matches leave B unselected — user re-picks once. |
| Inconsistent picker style within GoldDitto (A popover, B dropdown) | Accepted in this scope. A's popover features (end-event, includeEnded, lastCategory) have value that the dropdown does not currently model. A migration is a future option. |
| Picker hidden as soon as currentPosition is set, even by Teleport-mode use | This is the desired behavior — picker is only an entry-point affordance. Once any teleport happens, the user is in the normal flow. |
| Backend `current_position` requirement still hard-fails if user clicks Start without picking | The toast remains as a safety net. The picker is an affordance, not a guard rail. |

## 9. Out-of-scope follow-ups

- Migrating GoldDitto A to `BookmarkDropdown` (would need to model
  end-event / includeEnded / lastCategory in the dropdown or accept feature
  loss).
- Retiring `BookmarkPickerPopover`.
- "Remember last picked bookmark per mode" memory.
- Per-mode default categories filter (e.g. "RandomWalk only shows the 散步
  category").
