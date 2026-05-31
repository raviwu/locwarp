# IME-Safe Enter Submit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a Chinese/Japanese/Korean IME's candidate-confirm Enter from triggering submit/save in any LocWarp input, while keeping Enter-to-submit for a deliberate (non-composing) Enter.

**Architecture:** Add one pure predicate `isSubmitEnter(e)` in `frontend/src/utils/keyboard.ts` that returns true only for a non-composing Enter. Swap the bare `e.key === 'Enter'` test for `isSubmitEnter(e)` at all 12 inline `onKeyDown` handlers. No `<form>` elements exist, so these handlers are the only Enter-submit paths.

**Tech Stack:** React 18 + TypeScript + Vite + Electron. Spec: `docs/superpowers/specs/2026-05-31-ime-safe-enter-submit-design.md`.

---

## Testing approach (read first)

This repo has **no frontend test runner** (no vitest/jest/testing-library/playwright npm package, no `test` script, no test files) and the spec (§3) forbids adding one. Classic unit-test TDD does not apply here. Instead:

- **Per-task static gate:** `cd frontend && npx tsc --noEmit` must be clean after every code task. A wrong/missing import or typo fails this immediately.
- **Behavior gate (Task 4):** drive the running app with the Playwright MCP browser tools and dispatch synthetic `keydown` events to prove the IME-Enter is ignored and a plain Enter still submits.
- **Sanity:** backend `pytest` stays green (it is unaffected, but the global rule is to run the suite).

This is the mitigation required by `AGENTS.md` ("If tests cannot be run, explicitly state why and propose mitigation").

## File structure

| File | Responsibility | Change |
|---|---|---|
| `frontend/src/utils/keyboard.ts` | Pure IME-composition predicates (`isImeComposing`, `isSubmitEnter`) | **Create** |
| `frontend/src/App.tsx` | Map right-click add-bookmark dialog | Modify (1 site + import) |
| `frontend/src/components/BookmarkList.tsx` | Add-bookmark / add-category / inline-rename / custom-landmark inputs | Modify (4 sites + import) |
| `frontend/src/components/MapView.tsx` | Coordinate / teleport input | Modify (1 site + import) |
| `frontend/src/components/StatusBar.tsx` | Initial-location dialog input | Modify (1 site + import) |
| `frontend/src/components/AddressSearch.tsx` | Google API key input | Modify (1 site + import) |
| `frontend/src/components/RouteList.tsx` | Route save / category rename / category add / route rename inputs | Modify (4 sites + import) |

Commit grouping: Task 1 = util; Task 2 = the user-reported bug sites (add-bookmark + add-landmark); Task 3 = the remaining sites (holistic sweep); Task 4 = behavior verification (no commit).

---

### Task 1: Create the `isSubmitEnter` utility

**Files:**
- Create: `frontend/src/utils/keyboard.ts`

- [ ] **Step 1: Create the util file**

Create `frontend/src/utils/keyboard.ts` with exactly:

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

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors (the new file compiles; `keyCode` is deprecated but typed, `nativeEvent.isComposing` exists on React's `KeyboardEvent`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/utils/keyboard.ts
git commit -m "$(cat <<'EOF'
feat(keyboard): add isSubmitEnter IME-composition guard

Pure predicate that treats Enter as submit only when NOT mid-IME
composition (isComposing / keyCode 229). Used to stop CJK
candidate-confirm Enter from false-submitting input dialogs.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Guard the reported-bug sites (add bookmark + add landmark)

Fixes the exact paths Ravi reported: map right-click "add bookmark", the bookmark-list add/rename/custom-landmark inputs.

**Files:**
- Modify: `frontend/src/App.tsx` (import; site at line ~2178)
- Modify: `frontend/src/components/BookmarkList.tsx` (import; sites at lines ~816, ~934, ~1359, ~1948)

- [ ] **Step 1: Add the import to `App.tsx`**

`App.tsx` uses no-semicolon imports. Add the new import immediately after the existing utils import. Find:

```
import { parseCoord } from './utils/coords'
```

Add the line directly after it:

```
import { isSubmitEnter } from './utils/keyboard'
```

- [ ] **Step 2: Swap the Enter test in `App.tsx` (map add-bookmark dialog)**

Find this `onKeyDown` block (around line 2178):

```tsx
                onKeyDown={(e) => {
                  if (e.key === 'Enter') submitAddBookmark()
                  if (e.key === 'Escape') setAddBmDialog(null)
                }}
```

Replace with (only the Enter line changes; Escape untouched):

```tsx
                onKeyDown={(e) => {
                  if (isSubmitEnter(e)) submitAddBookmark()
                  if (e.key === 'Escape') setAddBmDialog(null)
                }}
```

- [ ] **Step 3: Add the import to `BookmarkList.tsx`**

`BookmarkList.tsx` uses semicolon imports. Find the first import (line 1):

```ts
import React, { useState, useEffect, useRef } from 'react';
```

Add directly after it:

```ts
import { isSubmitEnter } from '../utils/keyboard';
```

- [ ] **Step 4: Swap site A — add-bookmark name field (single-line, ~line 816)**

Find:

```tsx
            onKeyDown={(e) => e.key === 'Enter' && handleAddBookmark()}
```

Replace with:

```tsx
            onKeyDown={(e) => isSubmitEnter(e) && handleAddBookmark()}
```

- [ ] **Step 5: Swap site B — new bookmark category field (`&& cond`, ~line 934)**

Find:

```tsx
              onKeyDown={(e) => {
                if (e.key === 'Enter' && newCategoryName.trim()) {
                  onCategoryAdd(newCategoryName.trim());
                  setNewCategoryName('');
                }
              }}
```

Replace with (only the Enter test changes; the `.trim()` condition stays ANDed):

```tsx
              onKeyDown={(e) => {
                if (isSubmitEnter(e) && newCategoryName.trim()) {
                  onCategoryAdd(newCategoryName.trim());
                  setNewCategoryName('');
                }
              }}
```

- [ ] **Step 6: Swap site C — inline bookmark rename (`&& cond` + Escape, ~line 1359)**

Find:

```tsx
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && bm.id) {
                            onBookmarkEdit(bm.id, { name: editName });
                            setEditingId(null);
                          }
                          if (e.key === 'Escape') setEditingId(null);
                        }}
```

Replace with:

```tsx
                        onKeyDown={(e) => {
                          if (isSubmitEnter(e) && bm.id) {
                            onBookmarkEdit(bm.id, { name: editName });
                            setEditingId(null);
                          }
                          if (e.key === 'Escape') setEditingId(null);
                        }}
```

- [ ] **Step 7: Swap site D — custom landmark dialog name field (Enter + Escape, ~line 1948)**

Find:

```tsx
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAddCustom();
                if (e.key === 'Escape') setShowCustomDialog(false);
              }}
```

Replace with:

```tsx
              onKeyDown={(e) => {
                if (isSubmitEnter(e)) handleAddCustom();
                if (e.key === 'Escape') setShowCustomDialog(false);
              }}
```

- [ ] **Step 8: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors. (If it complains about an unused import, a site swap was missed — recheck steps 4–7.)

- [ ] **Step 9: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/BookmarkList.tsx
git commit -m "$(cat <<'EOF'
fix(bookmark): ignore IME confirm Enter when adding/renaming bookmarks

Add-bookmark (map + list), add-category, inline rename, and custom
landmark inputs now use isSubmitEnter(), so pressing Enter to confirm
Chinese candidate characters no longer false-submits the dialog.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Guard the remaining sites (holistic sweep)

Covers the rest so behavior is uniform: coordinate teleport, initial-location dialog, Google API key, and all four route inputs.

**Files:**
- Modify: `frontend/src/components/MapView.tsx` (import; site ~1969)
- Modify: `frontend/src/components/StatusBar.tsx` (import; site ~949)
- Modify: `frontend/src/components/AddressSearch.tsx` (import; site ~361)
- Modify: `frontend/src/components/RouteList.tsx` (import; sites ~270, ~586, ~640, ~1077)

- [ ] **Step 1: Add the import to `MapView.tsx`**

Find the existing utils import (line ~10):

```ts
import { parseCoord } from '../utils/coords';
```

Add directly after it:

```ts
import { isSubmitEnter } from '../utils/keyboard';
```

- [ ] **Step 2: Swap MapView coordinate/teleport input (single-line, ~line 1969)**

Find:

```tsx
            onKeyDown={(e) => { if (e.key === 'Enter') submitCoordGo('teleport'); }}
```

Replace with:

```tsx
            onKeyDown={(e) => { if (isSubmitEnter(e)) submitCoordGo('teleport'); }}
```

- [ ] **Step 3: Add the import to `StatusBar.tsx`**

Find the first import (line 1):

```ts
import React, { useEffect, useState } from 'react';
```

Add directly after it:

```ts
import { isSubmitEnter } from '../utils/keyboard';
```

- [ ] **Step 4: Swap StatusBar initial-location dialog (`&& cond` + Escape, ~line 949)**

Find:

```tsx
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !initialDialogBusy) handleInitialDialogSave();
                if (e.key === 'Escape' && !initialDialogBusy) setInitialDialogOpen(false);
              }}
```

Replace with (only the Enter test changes; the `!initialDialogBusy` guards stay):

```tsx
              onKeyDown={(e) => {
                if (isSubmitEnter(e) && !initialDialogBusy) handleInitialDialogSave();
                if (e.key === 'Escape' && !initialDialogBusy) setInitialDialogOpen(false);
              }}
```

- [ ] **Step 5: Add the import to `AddressSearch.tsx`**

Find the first import (line 1):

```ts
import React, { useState, useRef, useEffect, useCallback } from 'react';
```

Add directly after it:

```ts
import { isSubmitEnter } from '../utils/keyboard';
```

- [ ] **Step 6: Swap AddressSearch Google API key field (Enter + preventDefault, ~line 361)**

Find:

```tsx
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') { e.preventDefault(); saveGoogleKey(); }
                    }}
```

Replace with (preventDefault stays inside the now-guarded branch — it no longer fires during composition, which is intended):

```tsx
                    onKeyDown={(e) => {
                      if (isSubmitEnter(e)) { e.preventDefault(); saveGoogleKey(); }
                    }}
```

- [ ] **Step 7: Add the import to `RouteList.tsx`**

Find the first import (line 1):

```ts
import React, { useState, useEffect, useRef, useMemo } from 'react';
```

Add directly after it:

```ts
import { isSubmitEnter } from '../utils/keyboard';
```

- [ ] **Step 8: Swap RouteList site A — route name save field (single-line, ~line 270)**

Find:

```tsx
          onKeyDown={(e) => { if (e.key === 'Enter') triggerSave(); }}
```

Replace with:

```tsx
          onKeyDown={(e) => { if (isSubmitEnter(e)) triggerSave(); }}
```

- [ ] **Step 9: Swap RouteList site B — inline category rename (cond INSIDE block, ~line 586)**

Find:

```tsx
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      const next = editCategoryName.trim();
                      if (next && next !== cat.name && onCategoryRename) onCategoryRename(cat.id, next);
                      setEditingCategory(null);
                    }
                    if (e.key === 'Escape') setEditingCategory(null);
                  }}
```

Replace with (swap ONLY the outer bare Enter test; the inner `if (next && …)` condition is untouched):

```tsx
                  onKeyDown={(e) => {
                    if (isSubmitEnter(e)) {
                      const next = editCategoryName.trim();
                      if (next && next !== cat.name && onCategoryRename) onCategoryRename(cat.id, next);
                      setEditingCategory(null);
                    }
                    if (e.key === 'Escape') setEditingCategory(null);
                  }}
```

- [ ] **Step 10: Swap RouteList site C — new route category field (`&& cond`, ~line 640)**

Find:

```tsx
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && newCategoryName.trim()) {
                    onCategoryAdd(newCategoryName.trim());
                    setNewCategoryName('');
                  }
                }}
```

Replace with:

```tsx
                onKeyDown={(e) => {
                  if (isSubmitEnter(e) && newCategoryName.trim()) {
                    onCategoryAdd(newCategoryName.trim());
                    setNewCategoryName('');
                  }
                }}
```

- [ ] **Step 11: Swap RouteList site D — inline route rename (Enter + Escape, ~line 1077)**

Find:

```tsx
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitRename();
              if (e.key === 'Escape') setEditingRouteId(null);
            }}
```

Replace with:

```tsx
            onKeyDown={(e) => {
              if (isSubmitEnter(e)) commitRename();
              if (e.key === 'Escape') setEditingRouteId(null);
            }}
```

- [ ] **Step 12: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 13: Confirm zero stray Enter tests remain**

Run:

```bash
cd frontend/src && grep -rnE "e\.key === ['\"]Enter['\"]" --include="*.tsx" .
```

Expected: **zero matches.** All 12 Enter tests were the only `e.key === 'Enter'` occurrences in `frontend/src` (the excluded handlers — `BookmarkList.tsx:1851` and the global listeners — test Escape or movement keys, never `=== 'Enter'`). Any match here is a site that was missed; fix it before committing.

- [ ] **Step 14: Commit**

```bash
git add frontend/src/components/MapView.tsx frontend/src/components/StatusBar.tsx frontend/src/components/AddressSearch.tsx frontend/src/components/RouteList.tsx
git commit -m "$(cat <<'EOF'
fix(input): ignore IME confirm Enter in coord/route/key inputs

Apply isSubmitEnter() to the coordinate teleport, initial-location,
Google API key, and route save/rename/category inputs so the CJK
candidate-confirm Enter never false-submits. Completes the holistic
sweep started for bookmarks.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Behavior verification (Playwright MCP) + final sanity

No code change, no commit — this proves the fix and captures evidence.

**Files:** none (verification only)

- [ ] **Step 1: Start the dev server**

Run (background): `cd frontend && npx vite --host --port 5173`
Wait until it prints the local URL.

- [ ] **Step 2: Open the app and reach an add-bookmark input**

Using Playwright MCP:
1. `browser_navigate` to `http://localhost:5173`.
2. `browser_snapshot` to read the DOM.
3. Open the bookmark **category manager** and focus its "add category" input. This is the most deterministic surface: adding a category needs only non-empty text (no device, no current position, no lat/lng), so both the negative and positive assertions below are clean. The input has class `search-input`; since several `input.search-input` may exist on the page, scope the `querySelector` to the open category-manager container (or grab `document.activeElement` after focusing it) rather than the first match. Any of the 12 guarded inputs would prove the negative case; the category input is chosen so the positive case is also observable (the category list grows).

- [ ] **Step 3: Assert IME-Enter does NOT submit (the bug)**

The add-category handler calls `setNewCategoryName('')` only on a successful add, so a **cleared field == submit happened**. Set the value the React way (native setter + `input` event) so the controlled state actually holds text, making the test discriminating. Run `browser_evaluate` with:

```js
() => {
  const el = document.activeElement;
  if (!el || el.tagName !== 'INPUT') return { error: 'focus the add-category input first' };
  const setReactValue = (v) => {
    const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    desc.set.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };
  setReactValue('測試分類');
  const valueBefore = el.value;
  el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true }));
  el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 229, bubbles: true }));
  return { valueBefore, valueAfter: el.value, submitted: el.value === '' };
}
```

Expected: `valueBefore === '測試分類'`, `valueAfter === '測試分類'`, `submitted === false` — neither the `isComposing` event nor the `keyCode 229` event cleared the field, i.e. no submit. (If the guard were broken, the field would have cleared.) Take a `browser_take_screenshot` as evidence.

- [ ] **Step 4: Assert a plain Enter DOES submit (shortcut preserved)**

With the field still holding `測試分類` from Step 3, run `browser_evaluate` with:

```js
() => {
  const el = document.activeElement;
  el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  return { valueAfter: el.value, submitted: el.value === '' };
}
```

Expected: `submitted === true` — the field cleared, i.e. a single non-composing Enter ran the add-category action. Confirm the new "測試分類" category appears via `browser_snapshot`, then delete the test category to leave state clean.

- [ ] **Step 5: Stop the dev server.**

- [ ] **Step 6: Final static + backend sanity**

Run: `cd frontend && npx tsc --noEmit` → clean.
Run: `cd backend && .venv/bin/python -m pytest` → green (unaffected by this change; run per the global "full suite" rule).

- [ ] **Step 7: Manual smoke (optional, real IME)**

Switch macOS to a Chinese IME, open the add-bookmark dialog, type a name, press Enter to pick characters → dialog stays open; press Enter again after composition ends → saves. The automated check in Steps 3–4 already covers the logic; this is a real-hardware confirmation only.

---

## Done criteria

- `frontend/src/utils/keyboard.ts` exists with `isImeComposing` + `isSubmitEnter`.
- All 12 sites use `isSubmitEnter(e)`; no swapped handler still contains `e.key === 'Enter'`.
- `npx tsc --noEmit` clean; backend `pytest` green.
- Playwright MCP: IME-Enter (isComposing AND keyCode 229) does not submit; plain Enter does.
- Three commits on `main` (util / bookmark fix / remaining sweep).
