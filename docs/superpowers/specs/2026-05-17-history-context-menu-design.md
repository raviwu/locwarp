# History Context Menu — Design

**Date:** 2026-05-17
**Status:** Draft (pending user review)
**Author:** Ravi Wu
**Type:** Feature design

---

## 1. Background

LocWarp's map surface has a right-click context menu (`MapView.tsx` lines
2360–2598) that lets the user act on any lat/lng — teleport, navigate, set as
Gold Ditto A, copy coordinates, add to bookmarks, and (in route modes) add as a
waypoint. The menu is the central way users turn an arbitrary point on the map
into a useful action.

The same map view also exposes a "Recent destinations" dropdown in the top-right
(`MapView.tsx` lines 2119–2358) that shows the last 20 places the user flew to
(teleport, navigate, search, coord input). Each row is a single button: clicking
it re-flies (teleport or navigate, depending on the entry's original kind). The
only other affordance is a list-wide "Clear" button in the header.

Today, when the user wants to do anything else with a recent destination — most
commonly **save it as a bookmark** — there is no path. The user has to either
re-fly there, then right-click on the resulting position; or copy the
coordinates manually and re-enter them somewhere. Both paths lose the entry's
already-resolved name (e.g. "Tokyo Tower" from a search).

## 2. Goals

- Expose the same set of actions on every history entry as the map's
  right-click menu, scoped to that entry's coordinates.
- Preserve the existing single-click "re-fly" behavior — no muscle-memory
  break.
- When the entry has a name (e.g. from a search), use it to pre-fill the Add
  Bookmark dialog so the user doesn't have to retype it.
- Keep the change minimal: one menu, one state, two trigger sources. No
  duplicated JSX, no premature component extraction.

## 3. Non-goals

- Extracting the context menu into a standalone component. `MapView.tsx` is
  already over 2,700 lines and would benefit from decomposition, but that is
  out of scope for this feature and would expand the diff well beyond what the
  feature requires.
- Adding history-specific actions like "Remove from history" or "Rename
  entry". The user explicitly picked the minimal "match the map menu exactly"
  scope. These can be follow-ups if needed.
- Changing the map's right-click menu behavior or appearance.
- Changing how recent entries are stored, persisted, or pushed.

## 4. Design

### 4.1 Trigger surface

Each recent-entry row gains two new triggers, in addition to the existing
left-click on the row body:

1. **Right-click on the row** (`onContextMenu`) — opens the context menu
   anchored at the cursor position, matching the map's behavior. Must call
   `e.preventDefault()` to suppress the browser's native menu and
   `e.stopPropagation()` so the outer dropdown does not interpret the gesture
   as an outside click.
2. **A small `⋮` (kebab) icon button on the right edge of each row** — left
   click opens the same context menu, anchored near the icon's bounding rect.
   `e.stopPropagation()` for the same reason.

Left-click on the row body retains its current behavior: re-fly via the
entry's original kind (teleport vs. navigate).

### 4.2 Menu contents

The menu rendered for a history entry is **the same JSX** as the map's
right-click menu — there are no two menus, just two triggers feeding into one
render path. Concretely, that exposes:

- Header: lat/lng of the entry, with the existing "what's here?" reverse-geocode
  on-click (same behavior as map).
- **Teleport here** (device-gated, same as map).
- **Navigate here** (device-gated, same as map).
- **Set as Gold Ditto A** (conditional on `onSetAsGoldDittoA` being provided).
- **Copy coordinates**.
- **Add to bookmarks** — see §4.4 for the name-pre-fill behavior.
- **Add waypoint** (conditional on the route-mode gate, same as map).

No history-specific actions, no header customization. The user explicitly chose
the minimal "match exactly" option.

### 4.3 Reuse strategy

The existing `contextMenu` state object in `MapView` already carries
`{ visible, x, y, lat, lng }` and drives the entire menu JSX. We extend it
with one optional field:

```ts
contextMenu: {
  visible: boolean;
  x: number;
  y: number;
  lat: number;
  lng: number;
  name?: string;   // NEW — present when source is a history entry
}
```

A small helper opens the menu from a history row:

```ts
const openContextMenuForRecent = (entry, x, y) => {
  setContextMenu({
    visible: true,
    x, y,
    lat: entry.lat,
    lng: entry.lng,
    name: entry.name || undefined,
  });
};
```

The only place inside the menu JSX that reads `name` is the "Add to bookmarks"
item — see §4.4. Every other item operates purely on `lat`/`lng` and is
oblivious to the trigger source.

This keeps the diff to a few surgical hunks: one state-shape tweak, one helper
function, two trigger handlers per row, one prop-call change in the bookmark
item.

### 4.4 Bookmark pre-fill

`handleAddBookmark` in `App.tsx` currently opens the Add Bookmark dialog with
an empty `name`, then runs `reverseGeocode(lat, lng)` async and fills the name
from the result — without overwriting any text the user has typed in the
meantime.

We extend the signature:

```ts
handleAddBookmark(lat: number, lng: number, suggestedName?: string)
```

When `suggestedName` is provided and non-empty, the dialog opens with `name`
pre-seeded. The existing reverse-geocode call still runs to fetch the
`country_code` (used for the bookmark's flag), but the existing
"don't overwrite a non-empty name" branch already protects the seeded name —
so no new conditional logic is needed.

The "Add to bookmarks" menu item, when `contextMenu.name` is present, calls
`onAddBookmark(lat, lng, name)`. When opened from a map right-click,
`contextMenu.name` is `undefined` and behavior is unchanged.

### 4.5 Positioning details

- Right-click trigger: `setContextMenu({ x: e.clientX, y: e.clientY, ... })`,
  matching the map's existing pattern.
- `⋮` icon trigger: use the button's `getBoundingClientRect()` to anchor the
  menu near the icon's right edge (or just use `e.clientX`/`e.clientY` of the
  click — both are acceptable; the menu's existing layout-effect already
  clamps into the viewport).
- The recent dropdown stays open while the context menu is open. If the user
  clicks anywhere outside the menu (including inside the dropdown), the
  existing document-level outside-click handler closes the menu; the dropdown
  remains open because that handler is scoped to the menu only.

## 5. Files touched

| File | What changes |
|------|--------------|
| `frontend/src/components/MapView.tsx` | (1) `contextMenu` state shape adds optional `name?: string`. (2) Each recent-entry row gains `onContextMenu` and a sibling `⋮` icon button, both calling `openContextMenuForRecent(entry, x, y)`. (3) The "Add to bookmarks" menu item reads `contextMenu.name` and forwards it to `onAddBookmark`. (4) Each recent row's outer wrapper changes from a single `<button>` to a flex `<div>` containing the existing re-fly `<button>` plus the new `⋮` `<button>`, so the two click targets are independent. |
| `frontend/src/App.tsx` | `handleAddBookmark` gains optional `suggestedName?: string`; seeds the dialog with it when provided. `<MapView onAddBookmark={...}>` signature updated to forward the third arg. |
| `frontend/src/i18n/strings.ts` | New string: `recent.menu_tooltip` (zh: `更多動作`, en: `More actions`) for the `⋮` button's `title`/`aria-label`. |

No backend changes, no new dependencies, no storage changes.

## 6. Testing

The frontend has no automated test suite (`frontend/package.json` defines only
`dev` / `build` / `electron` / `dist` scripts). Verification is manual:

1. `npm run build` passes (typecheck + vite build).
2. With a device connected, fly to a few places via teleport, navigate, and
   address search to populate history.
3. Open the Recent dropdown:
   - Left-click on a row → re-flies as before (no regression).
   - Right-click on a row → context menu opens at cursor with the same items
     as the map's right-click menu.
   - Click the `⋮` icon → same context menu opens.
   - "Add to bookmarks" on a search-kind entry → dialog opens with the search
     name pre-filled.
   - "Add to bookmarks" on a coord/teleport entry without a name → dialog
     opens with name field empty (existing reverse-geocode flow fills it).
   - Other menu items (Teleport, Navigate, Set Gold Ditto A, Copy, Add
     waypoint when in route mode) behave the same way they do from the map.
4. With no device connected, right-click on a recent row → menu still opens;
   Teleport/Navigate show the disabled "device disconnected" state, exactly
   like the map menu.
5. Map right-click still works unchanged.

## 7. Risks and rollback

- **Risk: nested click targets cause hover/focus weirdness.** Mitigation:
  test row hover with both the re-fly button and the `⋮` button. The wrapping
  `<div>` carries the row-level hover background; the `⋮` button has its own
  hover tint that overrides for clear "I'm hovering this action" feedback.
- **Risk: `contextMenu.name` leaks into a path that shouldn't see it.**
  Mitigation: only the "Add to bookmarks" item reads it; verified by
  inspection.
- **Rollback:** the change is contained to three files and behavior is
  additive (no existing flow changes); reverting the three diffs restores
  prior behavior.

## 8. Out of scope (revisit later)

- Extracting `<MapContextMenu>` into a standalone component once a second
  external caller (beyond map + history) emerges, or once `MapView.tsx` gets
  decomposed for other reasons.
- "Remove from history" action on individual entries.
- Showing the entry's name (not just lat/lng) in the menu header when opened
  from a history row.
