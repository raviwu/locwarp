# Bookmark Context Menu — Design

**Date:** 2026-05-24
**Status:** Draft (pending user review)
**Author:** Ravi Wu
**Type:** Feature design

---

## 1. Background

LocWarp has three places where a user can right-click on a coordinate-bearing
target to act on it:

| Surface | Right-click menu source | Items |
|---|---|---|
| Map canvas (any lat/lng) | `MapView.tsx` lines 2488–2748 (shared `contextMenu` state) | Coords + What's-here · Teleport · Navigate · Set as Gold A · Copy coords · Add bookmark · Add waypoint |
| Recent-destinations dropdown | Reuses the same `MapView` `contextMenu` (`MapView.tsx` lines 2338–2364) | Same as above |
| Bookmark list rows | `BookmarkList.tsx` lines 1480–1596 (its own separate `contextMenu` state) | Edit · Copy (name + lat/lng) · Delete · Move to <category> |

The first two share a single, full-featured menu. The third — bookmarks — is the
odd one out: it can't teleport / navigate / set Gold A / add as waypoint
directly. To do any of those things, the user must left-click the bookmark to
fly there, then right-click on the resulting position to act.

To partially work around that, `BookmarkList` has a "Click also flies GPS"
checkbox (`localStorage.locwarp.bookmark_fly_gps`, `BookmarkList.tsx` lines
235–248, 719–736). When on (default), clicking a bookmark calls `handleTeleport`
in `App.tsx` (line 1581). When off, clicking instead pans the map only (via
`onBookmarkPreview` → `handleMapPanOnly`). The setting tries to give the user
control over whether click = teleport or click = preview, but it conflates two
concerns (preview vs. teleport vs. navigate vs. Gold A vs. waypoint) into one
binary toggle.

## 2. Goals

- Give bookmark right-click the same jump-mode actions (Teleport / Navigate /
  Set as Gold A / Add Waypoint) that map and history right-clicks already have.
- Preserve bookmark-specific actions (Edit / Delete / Move to category) — they
  have no equivalent on the map surface.
- Simplify the bookmark-click model: remove the binary "fly GPS" toggle. Every
  bookmark left-click is now just "pan the map to this point." All GPS jump
  modes are reached via right-click, the same way they are on the map.
- Keep the change visually consistent with the existing map/history menu (same
  item styles, same coords header with What's-here reverse-geocode).

## 3. Non-goals

- Do **not** extract a shared `<UnifiedContextMenu>` React component yet. Bookmark
  and map menus diverge significantly (bookmark-only Edit / Delete / Move-to-
  category items, map-only "Add bookmark" item), so an extracted component would
  need many boolean / optional-callback props. Revisit if a third caller appears.
- Do **not** change the recent-destinations menu (it already shares with map).
- Do **not** change the multi-select flow (`multiSelect = true` still suppresses
  the context menu entirely, as it does today — `BookmarkList.tsx` line 1098).
- Do **not** add a "Pin / Unpin from map" or any other new bookmark action that
  isn't already in map or bookmark menus today. This change is unification, not
  expansion.

## 4. Design

### 4.1 New bookmark right-click menu (top to bottom)

```
┌────────────────────────────────────────┐
│ 📍 25.034712, 121.564468   what's here │ ← clickable: triggers reverse-geocode
│   ┊ (reverse-geocode result, selectable)│
├────────────────────────────────────────┤
│ ⊕ Teleport                              │ ← device-gated (greyed when no device)
│ ➤ Navigate                              │ ← device-gated
│ ✦ Set as Gold Ditto A                   │ ← only when onSetAsGoldDittoA wired
│ ＋ Add as Waypoint                       │ ← only when showWaypointOption=true
├────────────────────────────────────────┤
│ ✎ Edit                                  │ ← existing
│ 📋 Copy (name + lat/lng)                │ ← existing
│ 🗑 Delete                                │ ← existing
├────────────────────────────────────────┤
│ Move to category                         │ ← existing
│   ● Restaurants                          │
│   ● Pokémon                              │
│   …                                     │
└────────────────────────────────────────┘
```

Notes:
- The "Add bookmark" item from the map menu is intentionally omitted — a
  bookmark is already a bookmark, so the row would be a no-op.
- When `deviceConnected = false`, Teleport and Navigate render as one disabled
  "Device disconnected" placeholder row (mirroring `MapView.tsx` lines 2642–2652).
- When `showWaypointOption = false` (not in a route mode), the Add-Waypoint row
  is hidden entirely; no placeholder.
- Coords-header behavior (reverse-geocode loading state, error text, result
  expansion, max-width clipping) matches the map menu exactly — it is the same
  visual contract.

### 4.2 Bookmark left-click simplification

Today:
```
click(bm) → if (flyGps) handleTeleport(bm.lat, bm.lng)
           else if (onBookmarkPreview) handleMapPanOnly(bm.lat, bm.lng)
```

After:
```
click(bm) → handleMapPanOnly(bm.lat, bm.lng)
```

Removed in `BookmarkList.tsx`:
- `flyGps` state + `setFlyGps` (lines 238–248)
- `localStorage.locwarp.bookmark_fly_gps` read/write
- The fly-GPS checkbox UI block (lines 722–736)
- The branch inside `handleBookmarkClick` (lines 442–446) — it becomes
  unconditional `onBookmarkClick(bm)` (whose semantic now means "pan-only").
- Prop `onBookmarkPreview?: (bm: Bookmark) => void` — no longer referenced.

Removed in `i18n/*.json`:
- Keys `bm.fly_gps` and `bm.fly_gps_tooltip`.

Changed in `App.tsx` (line 1581):
- `onBookmarkClick={(b) => handleTeleport(b.lat, b.lng)}`
  → `onBookmarkClick={(b) => handleMapPanOnly(b.lat, b.lng)}`
- The line that used to pass `onBookmarkPreview` (line 1582) is deleted.

### 4.3 `last_used_at` — no behavior change

`bookmark.last_used_at` is currently set at creation (`bookmarks.py` line 429)
and is otherwise only updated by explicit `update_bookmark` PUTs that include
`last_used_at` in the body. **Nothing in the frontend or backend auto-bumps
this field on teleport, navigate, or click** today. The "last_used" sort mode
(`BookmarkList.tsx` line 271) therefore effectively sorts by creation time on
fresh bookmarks until someone edits one.

This change does not alter that. Left-click behavior is changing (teleport →
pan-only), but neither the old nor the new path writes `last_used_at`. The
field's dormancy is unrelated to this redesign — flagged here so the spec
doesn't imply a side-effect that doesn't exist.

If we later want "last used = last time the user teleported here," that is a
separate change: add a `match-coord-to-bookmark` step in `handleTeleport` /
`handleNavigate` that calls `update_bookmark` with `last_used_at=now`. Out of
scope for this spec.

### 4.4 `BookmarkList` props delta

Added:

| Prop | Type | Purpose |
|---|---|---|
| `onTeleport` | `(lat: number, lng: number) => void` | Wire to `App.handleTeleport`. |
| `onNavigate` | `(lat: number, lng: number) => void` | Wire to `App.handleNavigate`. |
| `onSetAsGoldDittoA?` | `(lat: number, lng: number) => void` | Wire to the same setter `MapView` uses. Optional — when omitted, the menu row is hidden. |
| `onAddWaypoint?` | `(lat: number, lng: number) => void` | Wire to the route mode's add-waypoint callback. Optional. |
| `deviceConnected` | `boolean` | Used to gate Teleport / Navigate, mirroring `MapView` prop of same name. |
| `showWaypointOption` | `boolean` | Used to gate Add-Waypoint, mirroring `MapView` prop of same name. |
| `onShowToast?` | `(msg: string) => void` | Used by Copy and What's-here for transient feedback, matching `MapView`. Optional. |

Removed:

| Prop | Reason |
|---|---|
| `onBookmarkPreview` | No longer referenced after click-handler simplification. |

Unchanged but semantically reassigned:

| Prop | Old meaning | New meaning |
|---|---|---|
| `onBookmarkClick` | "User clicked a bookmark; do whatever the user has configured (teleport if flyGps, else pan)." | "User clicked a bookmark; pan the map to it." (Caller wires `handleMapPanOnly`.) |

### 4.5 Reverse-geocode state ownership

`MapView` owns its `reverseGeo` state (per-coord cache). `BookmarkList` will
have its own equivalent `reverseGeo` state scoped to its own menu — they do not
share cache. Two separate caches are acceptable: each menu has ≤1 active key at
a time, Nominatim is rate-limited per UA not per call, and sharing would require
either lifting state to `App` (overkill) or a context (also overkill for two
callers).

### 4.6 ESC / outside-click dismissal

Bookmark menu already has its own document-level dismissal listener
(`BookmarkList.tsx` lines 280–303). No change needed — the new items are inside
the same `[data-bookmark-context-menu]` portal, so they participate in the same
dismissal logic for free.

## 5. Implementation outline

(Detailed plan to be produced by the `writing-plans` skill. High-level shape:)

1. Add new props to `BookmarkList` interface; thread the new callbacks /
   booleans / toast through from `App.tsx` (the values already exist there —
   they're already passed to `MapView`).
2. Inside `BookmarkList`'s portal-rendered context menu (the existing block at
   line 1480), prepend the coords header + What's-here block (copied/adapted
   from `MapView.tsx` 2520–2585), then the jump-mode items block (copied/adapted
   from 2588–2746, minus the Add-bookmark item), then the existing
   Edit/Copy/Delete/Move-to block.
3. Add `reverseGeo` state and `reverseGeocode` call to `BookmarkList`, scoped to
   the menu lifecycle (cleared in the existing dismissal effect).
4. Remove the `flyGps` state, its localStorage I/O, its checkbox UI, and the
   branch inside `handleBookmarkClick`.
5. Remove `onBookmarkPreview` prop and all references.
6. In `App.tsx`, swap `onBookmarkClick` wiring from `handleTeleport` to
   `handleMapPanOnly`; delete the `onBookmarkPreview` line; pass the new props.
7. Delete i18n keys `bm.fly_gps`, `bm.fly_gps_tooltip` from every locale file.
8. Update any tests referencing the removed prop / state / i18n keys.

## 6. Testing

- Manual: open the app with at least one bookmark, no device connected, then
  with a device. Verify: left-click pans only (no teleport); right-click opens
  full menu; Teleport/Navigate disabled w/o device, enabled with device; Gold A
  row appears (Gold Ditto panel is always wired); Add Waypoint appears only
  when in a route mode; Edit / Copy / Delete / Move-to still work; coords
  header → "what's here" reverse-geocodes; ESC and outside-click dismiss the
  menu.
- Regression: confirm multi-select mode still suppresses the context menu
  entirely (no jump-mode items leak into a multi-select right-click).
- Regression: confirm bookmark sort order is unchanged in all four modes
  (default / name / date_added / last_used) — no list reordering should occur
  as a side-effect of this change.
- Type check: `cd frontend && npx tsc --noEmit` clean after the prop removal.
- Existing test suites: `cd backend && .venv/bin/python -m pytest` and any
  frontend tests stay green.

## 7. Rollout

Direct commit to `main` (personal repo, per `~/personal/dotfiles/personal-claude/AGENTS.md`).
No feature flag; no migration. The removed localStorage key
(`locwarp.bookmark_fly_gps`) is leftover bytes — harmless, GC'd on next browser
clear. No reader after the rebuild.
