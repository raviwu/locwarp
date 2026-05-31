# Gold Ditto — Unify B Selection With A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Gold Ditto B point work exactly like A — a `"lat, lng"` text field plus the shared 📚 `BookmarkPickerPopover` — instead of the inline bookmark-id dropdown.

**Architecture:** Convert B from a bookmark-id binding to a coordinate snapshot symmetric with A (state `bText`, storage `goldditto.B`, `b = parseLatLng(bText)`). Mirror A's input + 📚 markup for B, branch the picker handlers on `pickerSide`, and add a one-time reverse migration that resolves any stored bookmark id to coords. Update i18n.

**Tech Stack:** React 18 + TypeScript + Vite. Spec: `docs/superpowers/specs/2026-05-31-gold-ditto-b-picker-parity-design.md`.

---

## Testing approach (read first)

No frontend test runner (none added). Verification:
- **Static gate:** `cd frontend && npx tsc --noEmit` clean. (TS will flag any stray `bBookmarkId` reference or any dangling i18n key reference, which is the safety net for this refactor.)
- **Behavior gate (Task 2):** Playwright MCP against the dev server — structural parity (B = input + 📚, no dropdown) is backend-independent; pick-fills-coord and reverse-migration need the backend for bookmark data.

## File structure

| File | Responsibility | Change |
|---|---|---|
| `frontend/src/i18n/strings.ts` | UI strings (zh/en) | add `pick_from_bookmarks_tooltip_b`; remove `b_picker_placeholder` / `b_picker_empty`; retitle `b_label` |
| `frontend/src/components/GoldDittoPanel.tsx` | Gold Ditto A/B panel | B → coordinate model + A-style input/📚; picker handlers branch on side; reverse migration; remove dropdown + old B state/effects |

All edits are interdependent (the file does not compile in partial states), so this is **one task, one commit**.

---

### Task 1: Convert B to A-style coordinate picker

**Files:**
- Modify: `frontend/src/i18n/strings.ts`
- Modify: `frontend/src/components/GoldDittoPanel.tsx`

- [ ] **Step 1: i18n — add the B tooltip key**

In `frontend/src/i18n/strings.ts`, find:
```ts
  'goldditto.pick_from_bookmarks_tooltip_a': { zh: '從書籤選 A 點', en: 'Pick A from bookmarks' },
```
Add directly after it:
```ts
  'goldditto.pick_from_bookmarks_tooltip_b': { zh: '從書籤選 B 點', en: 'Pick B from bookmarks' },
```

- [ ] **Step 2: i18n — retitle the B label (drop the now-inaccurate "(書籤)")**

Find:
```ts
  'goldditto.b_label': { zh: 'B 真實位置 (書籤)', en: 'B real location (bookmark)' },
```
Replace with:
```ts
  'goldditto.b_label': { zh: 'B 真實位置', en: 'B real location' },
```

- [ ] **Step 3: GoldDittoPanel — remove the `BookmarkDropdown` import**

Find and delete this line (line 5):
```ts
import BookmarkDropdown from './BookmarkDropdown'
```
(The component file stays — `StartPositionPicker.tsx` still imports it.)

- [ ] **Step 4: GoldDittoPanel — redefine the B storage constants**

Find:
```ts
const LS_A = 'goldditto.A'
const LS_B_LEGACY = 'goldditto.B'              // pre-2026-05-10: stored "lat, lng"
const LS_B_BOOKMARK_ID = 'goldditto.B.bookmarkId' // new: bookmark id only
```
Replace with:
```ts
const LS_A = 'goldditto.A'
const LS_B = 'goldditto.B'                     // "lat, lng" string (symmetric with A)
const LS_B_BOOKMARK_ID = 'goldditto.B.bookmarkId' // legacy; read once for reverse migration
```

- [ ] **Step 5: GoldDittoPanel — swap B state to `bText`**

Find:
```ts
  const [bBookmarkId, setBBookmarkId] = useState<string | null>(
    () => localStorage.getItem(LS_B_BOOKMARK_ID),
  )
```
Replace with:
```ts
  const [bText, setBText] = useState(() => localStorage.getItem(LS_B) ?? '')
```

- [ ] **Step 6: GoldDittoPanel — add `bBtnRef` and `pickerCatB`**

Find:
```ts
  const aBtnRef = useRef<HTMLButtonElement | null>(null)

  const [pickerCatA, setPickerCatA] = useState<string | null>(
    () => localStorage.getItem('goldditto.picker.A.lastCategory'),
  )
```
Replace with:
```ts
  const aBtnRef = useRef<HTMLButtonElement | null>(null)
  const bBtnRef = useRef<HTMLButtonElement | null>(null)

  const [pickerCatA, setPickerCatA] = useState<string | null>(
    () => localStorage.getItem('goldditto.picker.A.lastCategory'),
  )
  const [pickerCatB, setPickerCatB] = useState<string | null>(
    () => localStorage.getItem('goldditto.picker.B.lastCategory'),
  )
```

- [ ] **Step 7: GoldDittoPanel — replace the B persist effect**

Find:
```ts
  useEffect(() => { localStorage.setItem(LS_A, aText) }, [aText])
  useEffect(() => {
    if (bBookmarkId) localStorage.setItem(LS_B_BOOKMARK_ID, bBookmarkId)
    else localStorage.removeItem(LS_B_BOOKMARK_ID)
  }, [bBookmarkId])
  useEffect(() => { localStorage.setItem(LS_WAIT, waitText) }, [waitText])
```
Replace with:
```ts
  useEffect(() => { localStorage.setItem(LS_A, aText) }, [aText])
  useEffect(() => { localStorage.setItem(LS_B, bText) }, [bText])
  useEffect(() => { localStorage.setItem(LS_WAIT, waitText) }, [waitText])
```

- [ ] **Step 8: GoldDittoPanel — replace the forward migration with a reverse migration**

Find the entire current migration block (the comment starting "One-shot migration:" through the closing `}, [bBookmarkId, bookmarks])`):
```ts
  // One-shot migration: if no new key but legacy "lat, lng" coord exists,
  // try to match a bookmark within COORD_MATCH_TOLERANCE; otherwise drop it.
  // `bookmarks` loads async (empty array until useBookmarks resolves); the
  // guard `bookmarks.length === 0 ? return` defers the decision until at
  // least one bookmark is visible. If the user genuinely has zero bookmarks,
  // the migration sits idle (cheap no-op) until they add one or pick B.
  const migratedRef = useRef(false)
  useEffect(() => {
    if (migratedRef.current) return
    if (bBookmarkId) {
      migratedRef.current = true
      localStorage.removeItem(LS_B_LEGACY)
      return
    }
    const legacy = localStorage.getItem(LS_B_LEGACY)
    if (!legacy) {
      migratedRef.current = true
      return
    }
    if (bookmarks.length === 0) return  // wait for async bookmarks load
    const parsed = parseLatLng(legacy)
    if (parsed) {
      const matches = bookmarks.filter(
        (bm) =>
          Math.abs(bm.lat - parsed.lat) < COORD_MATCH_TOLERANCE &&
          Math.abs(bm.lng - parsed.lng) < COORD_MATCH_TOLERANCE &&
          bm.id,
      )
      if (matches.length === 1 && matches[0].id) {
        setBBookmarkId(matches[0].id)
      }
    }
    localStorage.removeItem(LS_B_LEGACY)
    migratedRef.current = true
  }, [bBookmarkId, bookmarks])
```
Replace with:
```ts
  // One-shot reverse migration (2026-05-31): B is now a coordinate like A.
  // If B has no coord yet but a legacy bookmark-id is stored, resolve it to the
  // bookmark's current coords and seed bText. Deferred until bookmarks load.
  const migratedRef = useRef(false)
  useEffect(() => {
    if (migratedRef.current) return
    if (bText.trim() !== '') {            // already have a coord — nothing to migrate
      localStorage.removeItem(LS_B_BOOKMARK_ID)
      migratedRef.current = true
      return
    }
    const legacyId = localStorage.getItem(LS_B_BOOKMARK_ID)
    if (!legacyId) { migratedRef.current = true; return }
    if (bookmarks.length === 0) return    // wait for async bookmarks load
    const bm = bookmarks.find((x) => x.id === legacyId)
    if (bm) setBText(`${bm.lat.toFixed(6)}, ${bm.lng.toFixed(6)}`)
    localStorage.removeItem(LS_B_BOOKMARK_ID)
    migratedRef.current = true
  }, [bText, bookmarks])
```

Then delete the now-unused tolerance constant — `COORD_MATCH_TOLERANCE` was used ONLY by the forward migration just removed (`parseLatLng` stays; it's still used by `a`/`b`). Find and delete this line (~line 53):
```ts
const COORD_MATCH_TOLERANCE = 1e-5
```

- [ ] **Step 9: GoldDittoPanel — derive `b` from `bText`**

Find:
```ts
  const a = useMemo(() => parseLatLng(aText), [aText])
  const b = useMemo(() => {
    if (!bBookmarkId) return null
    const bm = bookmarks.find((x) => x.id === bBookmarkId)
    return bm ? { lat: bm.lat, lng: bm.lng } : null
  }, [bBookmarkId, bookmarks])
```
Replace with:
```ts
  const a = useMemo(() => parseLatLng(aText), [aText])
  const b = useMemo(() => parseLatLng(bText), [bText])
```

- [ ] **Step 10: GoldDittoPanel — branch `handlePick` for B**

Find:
```ts
  const handlePick = (bm: { lat: number; lng: number }) => {
    // Picker is now A-side only; B uses the inline BookmarkDropdown.
    if (pickerSide === 'A') {
      setAText(`${bm.lat.toFixed(6)}, ${bm.lng.toFixed(6)}`)
    }
  }
```
Replace with:
```ts
  const handlePick = (bm: { lat: number; lng: number }) => {
    const coord = `${bm.lat.toFixed(6)}, ${bm.lng.toFixed(6)}`
    if (pickerSide === 'A') setAText(coord)
    else if (pickerSide === 'B') setBText(coord)
  }
```

- [ ] **Step 11: GoldDittoPanel — branch `handleCategoryChange` for B**

Find:
```ts
  const handleCategoryChange = (catId: string) => {
    if (pickerSide === 'A') {
      setPickerCatA(catId)
      try { localStorage.setItem('goldditto.picker.A.lastCategory', catId) } catch { /* ignore */ }
    }
  }
```
Replace with:
```ts
  const handleCategoryChange = (catId: string) => {
    if (pickerSide === 'A') {
      setPickerCatA(catId)
      try { localStorage.setItem('goldditto.picker.A.lastCategory', catId) } catch { /* ignore */ }
    } else if (pickerSide === 'B') {
      setPickerCatB(catId)
      try { localStorage.setItem('goldditto.picker.B.lastCategory', catId) } catch { /* ignore */ }
    }
  }
```

- [ ] **Step 12: GoldDittoPanel — replace the B label block (dropdown → A-style input + 📚)**

Find:
```tsx
      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{t('goldditto.b_label')}</span>
        <BookmarkDropdown
          bookmarks={bookmarks}
          categories={categories.map((c) => ({ id: c.id, name: c.name }))}
          value={bBookmarkId}
          onChange={(bm) => setBBookmarkId(bm?.id ?? null)}
          placeholderText={t('goldditto.b_picker_placeholder')}
          emptyText={t('goldditto.b_picker_empty')}
          ariaLabel={t('goldditto.b_label')}
        />
      </label>
```
Replace with (mirrors A's block at lines 242-268, swapping a→b):
```tsx
      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{t('goldditto.b_label')}</span>
        <div style={{ display: 'flex', gap: 4 }}>
          <input
            type="text"
            value={bText}
            onChange={(e) => setBText(e.target.value)}
            placeholder="lat, lng"
            style={{
              flex: 1,
              padding: '6px 8px',
              border: bValid || bText === '' ? '1px solid #4b5563' : '1px solid #f87171',
              borderRadius: 4,
              background: '#1f2937',
              color: '#fff',
            }}
          />
          <button
            ref={bBtnRef}
            type="button"
            className="action-btn"
            title={t('goldditto.pick_from_bookmarks_tooltip_b')}
            onClick={() => openPicker('B', bBtnRef.current)}
            style={{ padding: '6px 8px', fontSize: 12 }}
          >📚</button>
        </div>
      </label>
```
(`bValid` already exists: `const bValid = b !== null` near line 179.)

- [ ] **Step 13: GoldDittoPanel — make the picker open on B's last category**

Find:
```tsx
        initialCategoryId={pickerCatA}
```
Replace with:
```tsx
        initialCategoryId={pickerSide === 'B' ? pickerCatB : pickerCatA}
```

- [ ] **Step 14: i18n — remove the now-unused dropdown keys**

First confirm nothing else references them:
```bash
cd /Users/raviwu/personal/locwarp && grep -rn "b_picker_placeholder\|b_picker_empty" frontend/src
```
Expected: **zero matches** (Step 12 removed the only references). If any remain outside `strings.ts`, stop and fix.

Then in `frontend/src/i18n/strings.ts`, find and DELETE these two lines:
```ts
  'goldditto.b_picker_placeholder': { zh: '從書籤選 B 點', en: 'Pick B from bookmarks' },
  'goldditto.b_picker_empty': { zh: '尚無書籤,B 點需先建立書籤', en: 'No bookmarks yet — add one before setting B' },
```

- [ ] **Step 15: Type-check**

Run: `cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit`
Expected: no errors. If it reports:
- an unused `COORD_MATCH_TOLERANCE` → delete its `const COORD_MATCH_TOLERANCE = 1e-5` line.
- a stray `bBookmarkId` / `setBBookmarkId` → a reference was missed (re-check Steps 5/7/8/9/12).
- a missing i18n key → a tooltip/label key mismatch (re-check Steps 1/2/14).

- [ ] **Step 16: Confirm the old B model is fully gone**

Run:
```bash
cd /Users/raviwu/personal/locwarp && grep -nE "bBookmarkId|BookmarkDropdown|LS_B_LEGACY|b_picker_" frontend/src/components/GoldDittoPanel.tsx
```
Expected: **zero matches**.

- [ ] **Step 17: Commit**

```bash
cd /Users/raviwu/personal/locwarp && git add frontend/src/components/GoldDittoPanel.tsx frontend/src/i18n/strings.ts && git commit -m "$(cat <<'EOF'
feat(goldditto): B uses the same coord + 📚 picker as A

B was a bookmark-id dropdown; it now mirrors A — a "lat, lng" field plus
the shared BookmarkPickerPopover (picking copies coords). A one-time
reverse migration resolves any stored goldditto.B.bookmarkId to coords so
no B setting is lost. i18n: add B tooltip, drop the dropdown keys, retitle
the B label. Drops the BookmarkDropdown usage (still used elsewhere).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Verify behavior (Playwright MCP) — no commit

**Files:** none (verification only)

- [ ] **Step 1: Start the dev server**

Run (background): `cd /Users/raviwu/personal/locwarp/frontend && npx vite --port 5199 --strictPort`. Wait for the URL. (For pick-fills-coord and reverse-migration, the backend at `127.0.0.1:8777` must also be running so bookmarks load; structural parity does not need it.)

- [ ] **Step 2: Structural parity (backend-independent)**

Playwright MCP → `browser_navigate` to `http://localhost:5199/`, open the Gold Ditto panel (Mode → Gold Ditto), `browser_snapshot`. Confirm the B row now renders a `"lat, lng"` text input **and** a 📚 button (same shape as A) — and **no** `<select>`/dropdown. `browser_evaluate` sanity:
```js
() => {
  const btns = [...document.querySelectorAll('button')].filter(b => b.textContent.trim() === '📚');
  return { bookButtons: btns.length }; // expect 2 (A and B)
}
```
Expected: `bookButtons === 2`.

- [ ] **Step 3: Pick-fills-coord + reverse migration (needs backend with bookmarks)**

If bookmarks load: click B's 📚 → confirm the `BookmarkPickerPopover` opens; pick a bookmark → B's text fills with `lat, lng`. Reverse migration: in console, `localStorage.setItem('goldditto.B.bookmarkId', '<an existing bookmark id>'); localStorage.removeItem('goldditto.B');` then reload → confirm `localStorage.getItem('goldditto.B')` is now that bookmark's coords and `goldditto.B.bookmarkId` is `null`. If the backend is not running, skip and verify by code reading + a manual check later; note it explicitly.

- [ ] **Step 4: Stop the dev server and clean up**

Stop the vite process on 5199; remove any `.playwright-mcp/` scratch dir; `git status --short` should be empty.

- [ ] **Step 5: Final static gate**

`cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit` → clean.

---

## Done criteria

- B renders as a `"lat, lng"` input + 📚 button identical to A; the inline `BookmarkDropdown` is gone from `GoldDittoPanel`.
- `b = parseLatLng(bText)`; B persists to `goldditto.B`; picking a bookmark copies its coords into B; A and B each remember their own last picker category.
- One-time reverse migration seeds `bText` from a stored `goldditto.B.bookmarkId` then removes that key.
- i18n: `pick_from_bookmarks_tooltip_b` added, `b_picker_placeholder`/`b_picker_empty` removed, `b_label` retitled.
- `grep` for `bBookmarkId|BookmarkDropdown|LS_B_LEGACY|b_picker_` in `GoldDittoPanel.tsx` → zero; `npx tsc --noEmit` clean.
- One commit on `main`.
