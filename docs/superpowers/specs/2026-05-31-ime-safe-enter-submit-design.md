# IME-Safe Enter Submit — Design

**Date:** 2026-05-31
**Status:** Draft (pending user review)
**Author:** Ravi Wu
**Type:** Bugfix / behavior design

---

## 1. Background

When a user adds a bookmark, adds a custom landmark, renames an item, or saves
a route/category, they type into a text `<input>`. With a Chinese (or Japanese /
Korean) IME, the user presses **Enter to confirm candidate-character selection**.
That confirmation Enter currently triggers the dialog's submit/save action — so
the program fires before the user has finished typing the name.

### Root cause

Every Enter handler in the frontend is a bare `e.key === 'Enter'` check with **no
IME-composition guard**. A repository-wide search finds zero occurrences of
`isComposing`, `compositionstart`, `compositionend`, `onCompositionStart`, or
`keyCode === 229` anywhere in `frontend/src`. Example (`App.tsx`):

```tsx
onKeyDown={(e) => {
  if (e.key === 'Enter') submitAddBookmark()
  if (e.key === 'Escape') setAddBmDialog(null)
}}
```

The browser fires the candidate-confirm Enter as a `keydown` whose `key` is
`'Enter'` but whose `nativeEvent.isComposing` is `true`. (Browsers also report
`keyCode === 229` — the sentinel for any keydown still being processed by an
IME; in modern engines a composing keydown carries both `isComposing === true`
and `keyCode === 229`, so the two are not mutually exclusive.) Because the
handlers never inspect either flag, they treat the IME confirm as a submit.
This is the well-known CJK/IME false-submit bug.

### Scope

A repository-wide search found **no `<form>` elements** in `frontend/src`, so
there is no browser implicit-submit-on-Enter. Every Enter-triggered submit
comes from one of the inline `onKeyDown` handlers in §4.3 — those are the only
paths to fix. A scan across inline handlers, global `addEventListener`
listeners, native form paths, and existing IME guards produced the site list in
§4.3 and the exclusions in §4.5.

## 2. Goals

- Stop the IME candidate-confirm Enter from triggering any program action.
- **Preserve** Enter-to-submit for the deliberate case: a real Enter pressed when
  not mid-composition (English typing, or a second Enter after composition ends)
  still submits — power users keep the keyboard shortcut.
- Apply the fix **consistently** across all affected input sites (holistic, not
  just the two the user reported), via a single shared predicate so no site is
  missed and the pattern is uniform.
- Add no new npm dependencies (runtime or dev).

## 3. Non-goals

- Do **not** remove Enter-to-submit entirely / make the UI button-only. (User
  chose to keep Enter with an IME guard over button-only — 2026-05-31.)
- Do **not** convert dialogs to native `<form>` + `type="submit"`. That is a
  larger refactor across many ad-hoc `<div>` dialogs and is unnecessary once the
  predicate is in place.
- Do **not** add a frontend test runner. There is no vitest / jest /
  testing-library today (`@vitejs/plugin-react` in `package.json` is a build
  plugin, not a test framework); introducing one is a new dependency requiring
  separate discussion. Verification uses `tsc` + Playwright MCP (see §6).
- Do **not** touch global keyboard listeners or Escape-only handlers — none of
  them react to Enter (see §4.5).
- Do **not** add `e.preventDefault()` where it is not already present. Only
  `AddressSearch.tsx:361` calls it; it stays, but note it now sits inside the
  guarded Enter branch, so it no longer fires during IME composition. That is
  intended — the IME should own its confirm Enter — and harmless, since with no
  `<form>` there is no implicit submit to suppress anyway.

## 4. Design

### 4.1 Approach — shared predicate (chosen)

Three options were considered:

| Option | Description | Verdict |
|---|---|---|
| Inline guard per site | Add `if (e.nativeEvent.isComposing \|\| e.keyCode === 229) return` at each of 12 sites | Repetitive; easy to miss one; inconsistent |
| **Shared predicate `isSubmitEnter(e)`** | One util; each site swaps `e.key === 'Enter'` → `isSubmitEnter(e)`; existing Escape branches and `.trim()` / `!busy` conditions stay untouched | **Chosen** — DRY, minimal per-site diff, one uniform pattern |
| HOF factory `onSubmitEnter(fn)` | Elegant for Enter-only handlers but does not fit handlers that also handle Escape or carry extra conditions → would force two patterns | Rejected for inconsistency |

### 4.2 New utility — `frontend/src/utils/keyboard.ts`

```ts
import type { KeyboardEvent } from 'react';

/**
 * True while an IME (Chinese / Japanese / Korean, etc.) is composing a
 * character. The Enter that confirms candidate selection must NOT be treated
 * as a submit. `keyCode === 229` is the sentinel browsers emit for any keydown
 * still being processed by the IME; it is a defensive fallback for engines that
 * do not set `isComposing` reliably. The two co-occur in modern browsers and
 * are not mutually exclusive.
 */
export function isImeComposing(e: KeyboardEvent): boolean {
  return e.nativeEvent.isComposing || e.keyCode === 229;
}

/**
 * True only for a deliberate Enter that should submit — Enter pressed when NOT
 * mid-IME-composition.
 */
export function isSubmitEnter(e: KeyboardEvent): boolean {
  return e.key === 'Enter' && !isImeComposing(e);
}
```

Both functions are pure. The type-only `KeyboardEvent` import is erased at
build; `e.nativeEvent.isComposing` and `e.keyCode` are both present on React's
`KeyboardEvent` type (`keyCode` is deprecated but still typed and available).

### 4.3 Sites to change (12)

The cited line is the **`onKeyDown` prop line**. For single-line handlers that
is also where the `e.key === 'Enter'` test lives; for multi-line blocks the
`if (e.key === 'Enter')` test sits one or more lines below the prop. Line
numbers are pre-change anchors — match on content, since lines shift as edits
land. The "shape" column tells the implementer how the Enter test is written:

- *single-line* — `onKeyDown={(e) => e.key === 'Enter' && fn()}`
- *Enter + Escape* — multi-line block with a separate `if (e.key === 'Escape')`
- *`&& cond`* — the condition is ANDed onto the Enter test
  (`if (e.key === 'Enter' && cond)`), so after the swap it reads
  `if (isSubmitEnter(e) && cond)`
- *cond inside block* — the Enter test is bare and the condition lives inside
  the block (`if (e.key === 'Enter') { …if (cond) … }`); only the bare token
  swaps, the inner condition is untouched

| # | File | Line (`onKeyDown` prop) | Action on Enter | Shape |
|---|---|---|---|---|
| 1 | `App.tsx` | 2178 | `submitAddBookmark()` (map right-click add-bookmark name field) | Enter + Escape |
| 2 | `components/BookmarkList.tsx` | 816 | `handleAddBookmark()` (add-bookmark name field) | single-line |
| 3 | `components/BookmarkList.tsx` | 934 | `onCategoryAdd(newCategoryName.trim())` (new bookmark category) | `&& cond` (`.trim()`) |
| 4 | `components/BookmarkList.tsx` | 1359 | `onBookmarkEdit(bm.id, { name })` (inline bookmark rename) | Enter + Escape |
| 5 | `components/BookmarkList.tsx` | 1948 | `handleAddCustom()` (custom landmark name field) | Enter + Escape |
| 6 | `components/MapView.tsx` | 1969 | `submitCoordGo('teleport')` (coordinate / teleport field) | single-line |
| 7 | `components/StatusBar.tsx` | 949 | `handleInitialDialogSave()` (initial-location dialog) | `&& cond` (`!initialDialogBusy`) |
| 8 | `components/AddressSearch.tsx` | 361 | `saveGoogleKey()` (Google API key field) | Enter (+ `preventDefault`) |
| 9 | `components/RouteList.tsx` | 270 | `triggerSave()` (route name save field) | single-line |
| 10 | `components/RouteList.tsx` | 586 | `onCategoryRename(cat.id, …)` (inline category rename) | Enter + Escape, **cond inside block** |
| 11 | `components/RouteList.tsx` | 640 | `onCategoryAdd(newCategoryName.trim())` (new route category) | `&& cond` (`.trim()`) |
| 12 | `components/RouteList.tsx` | 1077 | `commitRename()` (inline route rename) | Enter + Escape |

Per-site change: replace the Enter test `e.key === 'Enter'` with `isSubmitEnter(e)`;
**leave every Escape branch and every extra condition (`.trim()`, `!initialDialogBusy`)
exactly as-is**; add `import { isSubmitEnter } from '<relative>/utils/keyboard';`
to each file.

Examples:

```tsx
// single-line (BookmarkList.tsx:816, MapView.tsx:1969, RouteList.tsx:270)
// before
onKeyDown={(e) => e.key === 'Enter' && handleAddBookmark()}
// after
onKeyDown={(e) => isSubmitEnter(e) && handleAddBookmark()}

// multi-line with Escape (App.tsx:2178)
// before
if (e.key === 'Enter') submitAddBookmark()
// after
if (isSubmitEnter(e)) submitAddBookmark()

// multi-line with extra condition (StatusBar.tsx:949)
// before
if (e.key === 'Enter' && !initialDialogBusy) handleInitialDialogSave();
// after
if (isSubmitEnter(e) && !initialDialogBusy) handleInitialDialogSave();
```

### 4.4 Behavior after fix

| Scenario | Result |
|---|---|
| Typing Chinese, press Enter to confirm candidate | `isComposing = true` → `isSubmitEnter` false → **no submit** ✓ (the reported bug) |
| A non-composing Enter (composition already ended) | `isComposing = false` → submits ✓ (keyboard shortcut preserved) |
| English typing, press Enter | submits (unchanged) |
| Escape | unchanged (handled separately, never gated by the predicate) |

**Note on keystroke count.** The exact number of Enters needed to submit after
typing CJK text varies by browser/IME: some flip `isComposing` to `false` on the
keydown that confirms the candidate (so the next Enter submits), others keep it
`true` on that keydown (so a second deliberate Enter submits). The guard's
priority is **never to false-submit during composition**; the contract is "a
non-composing Enter submits," not a fixed keystroke count.

### 4.5 Correctly excluded (and why)

These were found by the scan and deliberately left untouched:

- **`components/BookmarkList.tsx:1851`** — edit-bookmark dialog name field. Handler
  is Escape-only (`if (e.key === 'Escape') setEditDialog(null)`); the dialog saves
  via its Save button `onClick` (line ~1890), never via Enter. No IME submit risk.
- **`components/AddressSearch.tsx:140`** — the main address search box. It has no
  `onKeyDown` at all; it is a debounced live-search-as-you-type input with a
  results dropdown. No Enter-triggered action.
- **Global movement listeners** — `JoystickPad.tsx` (window keydown/keyup) and
  `hooks/useJoystick.ts` (window keydown/keyup) map only WASD / arrow keys, skip
  INPUT/TEXTAREA/contentEditable targets, and never react to Enter.
- **Escape-only document listeners** — `App.tsx:530` (cancel insert-after),
  `BookmarkList.tsx:319` (close context menu), `BookmarkPickerPopover.tsx:95`,
  `ExportPopover.tsx:30`, `RouteList.tsx:215` (close route menu),
  `RouteList.tsx:235` (close color picker). All Escape-only; none react to Enter.

## 5. Implementation outline

§4.3 is the complete per-site edit recipe; the `writing-plans` skill will turn
this into a checkpointed task list (one verification gate after the util, one
after the swaps). The shape:

1. Add `frontend/src/utils/keyboard.ts` with `isImeComposing` + `isSubmitEnter`.
2. In each of the 12 files (§4.3), import `isSubmitEnter` and swap the Enter test
   per the row's shape, preserving Escape branches and extra conditions verbatim.
3. `cd frontend && npx tsc --noEmit` — must be clean.
4. Behavior-verify the highest-value path (add-bookmark name field) and one route
   path with the Playwright MCP method in §6.

## 6. Testing

No frontend test runner exists (no vitest/jest/testing-library/playwright npm
package, no `test` script, no test files) — and we are not adding one (§3).

- **Static gate:** `cd frontend && npx tsc --noEmit` clean.
- **Backend suite (unaffected, sanity):** `cd backend && .venv/bin/python -m pytest`
  stays green.
- **Automated behavior check (Playwright MCP against the Vite dev server):** real
  IME composition cannot be produced by synthetic key events, but the two
  properties the guard reads *can* be set on a synthetic `KeyboardEvent`.
  Precondition: dispatch on the focused input node (inside React's root
  container) with `bubbles: true`, so React's delegated listener fires. Assert on
  observable state (dialog still open / no POST to the bookmarks API), not just
  visibility. For the add-bookmark name input:
  1. `new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true })`
     → exercises the `isComposing` arm → assert **no submit** (dialog open, no
     bookmark created).
  2. `new KeyboardEvent('keydown', { key: 'Enter', keyCode: 229, bubbles: true })`
     → exercises the `keyCode === 229` arm → assert **no submit**.
  3. `new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })` (neither flag)
     → assert **submit fires** (deliberate Enter still works).
  React surfaces both via `e.nativeEvent.isComposing` / `e.keyCode`, so the
  synthetic events drive the same predicate the IME would.
- **Manual smoke (fallback, real IME):** switch macOS to a Chinese IME, open the
  add-bookmark dialog, type a name, press Enter to pick characters → dialog stays
  open; press Enter again after composition ends → saves. Optional, since the
  automated check covers the logic.

## 7. Rollout

Direct commit to `main` (personal repo, per
`~/personal/dotfiles/personal-claude/AGENTS.md`). No feature flag, no migration,
no i18n change — a new shared util plus a mechanical one-expression swap (and one
import) in 12 files.
