# Gold Ditto — Unify B Selection With A — Design

**Date:** 2026-05-31
**Status:** Draft (pending user review)
**Author:** Ravi Wu
**Type:** Feature / behavior design

---

## 1. Background

The Gold Ditto panel (`frontend/src/components/GoldDittoPanel.tsx`) takes two
points, A and B, and cycles between them. Their selection UX and data model
diverge:

- **A** — a coordinate. A text input (`aText`, persisted `goldditto.A` as a
  `"lat, lng"` string) plus a 📚 button that opens `BookmarkPickerPopover`
  (a categorized bookmark browser). Picking a bookmark copies its coords into
  the text (`handlePick`, line 211-216). A can also be typed or set by the map
  right-click "設為拉金盆 A 點" (`externalAValue`).
- **B** — a bookmark identity. An inline `BookmarkDropdown` (line 272-280) bound
  to a bookmark **id** (`bBookmarkId`, persisted `goldditto.B.bookmarkId`). B's
  coords are derived live from the bookmark (line 166-170), so B follows the
  bookmark if its coords change and goes invalid if it is deleted. A one-shot
  migration (line 130-158) converted the pre-2026-05-10 `"lat, lng"` value
  (`goldditto.B`) to a matched bookmark id. Comment at line 211-212 records the
  intent: "Picker is now A-side only; B uses the inline BookmarkDropdown."

The user finds the two selection menus inconsistent and wants **B to work exactly
like A** — a coordinate field plus the same 📚 categorized picker.

## 2. Goals

- Make B's selector identical to A's: a `"lat, lng"` text input plus the 📚
  `BookmarkPickerPopover`. Picking a bookmark copies its coords into B's text.
- Make B a **coordinate snapshot** (decision 2026-05-31), symmetric with A — no
  longer bound to a bookmark id. (Consequence: B no longer auto-follows later
  edits to the source bookmark and survives the bookmark's deletion.)
- Preserve the user's existing B via a one-time reverse migration (resolve the
  stored bookmark id to its current coords) so nobody loses their B setting.
- No new dependencies.

## 3. Non-goals

- Do **not** add a map right-click "設為拉金盆 B 點" entry. A has its A-setter;
  adding a B equivalent is a separate enhancement. B is still set via the panel.
- Do **not** extract a shared `CoordPickerField` component. B's block mirrors A's
  existing markup inline — minimal change, A being the reference the user pointed
  to. (Revisit if a third coord-picker field appears.)
- Do **not** delete `BookmarkDropdown.tsx` — `StartPositionPicker.tsx` still uses
  it. Only its import/usage in `GoldDittoPanel.tsx` is removed.
- Do **not** touch the unused `mapCenter` prop (already dead per its own comment;
  ripping out the `ControlPanel`/`App.tsx` wiring is out of scope).

## 4. Design

### 4.1 B data model → coordinate snapshot (symmetric with A)

| Aspect | Before (B = bookmark id) | After (B = coordinate, like A) |
|---|---|---|
| State | `bBookmarkId: string \| null` | `bText: string` (mirrors `aText`) |
| Storage | `goldditto.B.bookmarkId` (id) | `goldditto.B` (`"lat, lng"` string) |
| Derive `b` | `bookmarks.find(id) → {lat,lng}` | `parseLatLng(bText)` |
| Selection UI | inline `BookmarkDropdown` | text input + 📚 `BookmarkPickerPopover` |
| Follows bookmark edits | yes | no (snapshot) |

`LS_B` is redefined to `'goldditto.B'` storing the coord string (its original
pre-refactor meaning). `bText` persists exactly like `aText` (a `useEffect`).
`b = useMemo(() => parseLatLng(bText), [bText])`.

New refs/state mirroring A: `bBtnRef` (the 📚 button) and `pickerCatB`
(B's last-opened category, persisted `goldditto.picker.B.lastCategory`).

### 4.2 UI — B label block mirrors A

Replace the `<BookmarkDropdown>` block with the same markup A uses: a text input
bound to `bText` (placeholder `"lat, lng"`, red border when non-empty & invalid)
and a 📚 `action-btn` whose `onClick` calls `openPicker('B', bBtnRef.current)` and
whose `title` is `t('goldditto.pick_from_bookmarks_tooltip_b')`.

### 4.3 Picker wiring (both sides through one popover)

`openPicker` already accepts `'A' | 'B'`; `BookmarkPickerPopover` already receives
`side={pickerSide ?? 'A'}`. The remaining branch points:

- `handlePick(bm)` → `if (pickerSide === 'A') setAText(coords); else if (pickerSide === 'B') setBText(coords);` (coords = `` `${bm.lat.toFixed(6)}, ${bm.lng.toFixed(6)}` ``).
- `handleCategoryChange(catId)` → A persists `goldditto.picker.A.lastCategory`;
  B persists `goldditto.picker.B.lastCategory`.
- `BookmarkPickerPopover` `initialCategoryId={pickerSide === 'B' ? pickerCatB : pickerCatA}`.

### 4.4 One-time reverse migration (don't lose existing B)

A `useEffect` mirroring the current deferred-until-bookmarks-load migration:

- Guard with a `migratedRef` so it runs once.
- If `bText` is already non-empty (or `goldditto.B` coord exists) → nothing to do;
  clear any stale `goldditto.B.bookmarkId`; done.
- Else read `goldditto.B.bookmarkId`. If absent → done. If present but
  `bookmarks.length === 0` → return (wait for async load). Once loaded, find the
  bookmark by id; if found, `setBText(`${bm.lat.toFixed(6)}, ${bm.lng.toFixed(6)}`)`.
  Then remove `goldditto.B.bookmarkId`.

After this, B never reads the id key again.

### 4.5 Removals (`GoldDittoPanel.tsx`)

- `import BookmarkDropdown from './BookmarkDropdown'` (component kept for
  `StartPositionPicker`).
- `bBookmarkId` state, its persist `useEffect`, the forward (coord→id) migration
  `useEffect` (line 130-158), and the bookmark-derived `b` (line 166-170).
- The `LS_B_LEGACY` constant (its key folds into the redefined `LS_B`).

### 4.6 i18n (`frontend/src/i18n/strings.ts`, zh + en)

- **Add** `goldditto.pick_from_bookmarks_tooltip_b` — zh `從書籤選 B 點`,
  en `Pick B from bookmarks` (mirrors the `_a` key).
- **Remove** the now-unused `goldditto.b_picker_placeholder` and
  `goldditto.b_picker_empty` (they fed `BookmarkDropdown`).
- **Update** `goldditto.b_label` to drop the now-inaccurate "(書籤)/(bookmark)":
  zh `B 真實位置`, en `B real location`.

### 4.7 Unchanged

`cycleArgs`, `sameAB`, `disableConfirm/disableFirstTry`, `handleConfirm`,
`handleFirstTry`, the wait field, and the end-event flow (`onEndEvent` /
`onCategoryDeleteCascade`) all continue to work — they consume `b` as
`{lat,lng}|null`, which `parseLatLng(bText)` still produces.

## 5. Implementation outline

(Detailed steps from `writing-plans`. Shape:)

1. `strings.ts`: add `pick_from_bookmarks_tooltip_b`; remove `b_picker_placeholder`
   / `b_picker_empty`; update `b_label`.
2. `GoldDittoPanel.tsx`: swap B state to `bText`; redefine `LS_B`; mirror A's
   input + 📚 markup for B; branch `handlePick` / `handleCategoryChange`; set the
   popover `initialCategoryId` per side; add the reverse migration; remove the
   `BookmarkDropdown` import + the old B state/effects/derivation.
3. `cd frontend && npx tsc --noEmit` — clean.
4. Verify (§6).

## 6. Testing

No frontend test runner; not adding one.

- **Static gate:** `cd frontend && npx tsc --noEmit` clean.
- **Behavior (Playwright MCP, dev server + backend for bookmark data):**
  - Open the Gold Ditto panel; confirm B now shows a `"lat, lng"` text input + 📚
    button (no dropdown), structurally identical to A.
  - Click B's 📚 → the same `BookmarkPickerPopover` opens (titled for B via its
    `side` prop). Pick a bookmark → B's text fills with that bookmark's coords.
  - Type a coord directly into B → accepted; invalid text → red border, B invalid.
  - Reverse migration: with `localStorage['goldditto.B.bookmarkId']` preset to an
    existing bookmark id and `goldditto.B` empty, reload → B seeds that bookmark's
    coords and `goldditto.B.bookmarkId` is removed.
- **Manual:** run a cycle with A and B both set from bookmarks; confirm parity.

This touches the user's real bookmark store only by reading (picking copies
coords; no bookmark is created/edited/deleted by this feature). The end-event
delete action in the popover is pre-existing and unchanged.

## 7. Rollout

Direct commit to `main` (personal repo). No new deps. One-time localStorage
reverse migration is self-healing and idempotent (guarded by `migratedRef` +
the presence checks). Stale `goldditto.B.bookmarkId` keys are removed on first
load post-update.
