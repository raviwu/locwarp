# Bookmark-Driven Start Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface an inline bookmark dropdown for selecting a starting position in modes that require `currentPosition` (RandomWalk / Joystick / Navigate / Loop / MultiStop), and refactor the GoldDitto B-side to use the same picker — eliminating the manual coord input, random-Taiwan, and map-center helpers for B.

**Architecture:** Three layers, top-down: (1) low-level `BookmarkDropdown` (controlled `<select>` with optgroups by category) → (2) `StartPositionPicker` (mode-panel chrome + teleport on pick) → (3) GoldDitto B-side rebuilt around `BookmarkDropdown`, with localStorage migrated from coord string to bookmark id.

**Tech Stack:** React 18.3 + TypeScript strict mode (no frontend test harness exists; verification = `tsc --noEmit` + `vite build` + manual smoke).

**Spec:** `docs/superpowers/specs/2026-05-10-bookmark-driven-start-picker-design.md`

**Note on testing:** This codebase has backend pytest tests (`backend/tests/`) but no frontend test harness (no Vitest, no React Testing Library). Adding test infrastructure is out of scope for this UI feature. Each task uses TypeScript strict + Vite build as the automated gate, and Task 6 covers manual smoke.

---

## File Structure

| File | Purpose | Status |
|------|---------|--------|
| `frontend/src/components/BookmarkDropdown.tsx` | Reusable controlled dropdown — bookmarks grouped by category_id | NEW |
| `frontend/src/components/StartPositionPicker.tsx` | Mode-panel section using BookmarkDropdown; teleports on pick | NEW |
| `frontend/src/components/ControlPanel.tsx` | Add `bookmarksRaw`, `bookmarkCategoriesFull` props; mount StartPositionPicker | MODIFY |
| `frontend/src/components/GoldDittoPanel.tsx` | Refactor B-side to BookmarkDropdown; drop manual coord/random/map-center; migrate localStorage | MODIFY |
| `frontend/src/App.tsx` | Wire new props to ControlPanel | MODIFY |
| `frontend/src/i18n/strings.ts` | Add 6 new keys; modify 1; remove 3 | MODIFY |

---

## Task 1: Add i18n strings

**Files:**
- Modify: `frontend/src/i18n/strings.ts` (lines 153–172 for the GoldDitto block)

Adds the six new keys and tweaks `goldditto.b_label`. Does NOT remove obsolete keys yet — Task 5 deletes them once their last usage is gone, so the build never sees a missing-key reference.

- [ ] **Step 1: Add new keys after the existing GoldDitto block**

In `frontend/src/i18n/strings.ts`, locate the line:

```ts
'goldditto.pick_from_bookmarks_tooltip_b': { zh: '從書籤選 B 點', en: 'Pick B from bookmarks' },
```

Immediately AFTER that line, insert:

```ts
  // ── Bookmark dropdown shared chrome (StartPositionPicker + GoldDitto B) ───
  'panel.start_picker_label': { zh: '起點', en: 'Start point' },
  'panel.start_picker_placeholder': { zh: '從書籤挑一個當起點', en: 'Pick a bookmark to start from' },
  'panel.start_picker_empty': { zh: '尚無書籤,請先在地圖右鍵加書籤', en: 'No bookmarks yet — right-click the map to add one' },
  'panel.bookmark_dropdown_other': { zh: '其他', en: 'Other' },
  'goldditto.b_picker_placeholder': { zh: '從書籤選 B 點', en: 'Pick B from bookmarks' },
  'goldditto.b_picker_empty': { zh: '尚無書籤,B 點需先建立書籤', en: 'No bookmarks yet — add one before setting B' },
```

- [ ] **Step 2: Update `goldditto.b_label` text**

Replace:

```ts
  'goldditto.b_label': { zh: 'B 點 (你的真實 GPS)', en: 'B (Your real GPS)' },
```

with:

```ts
  'goldditto.b_label': { zh: 'B 真實位置 (書籤)', en: 'B real location (bookmark)' },
```

- [ ] **Step 3: Verify build**

Run from `frontend/`:

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: exit 0. The new keys are added, the modified key is still present.

- [ ] **Step 4: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/i18n/strings.ts
git commit -m "i18n: add start-picker + GoldDitto B-picker keys"
```

---

## Task 2: Create `BookmarkDropdown`

**Files:**
- Create: `frontend/src/components/BookmarkDropdown.tsx`

Pure controlled component. No persistence, no side-effects. Groups bookmarks by `category_id`. Bookmarks whose `category_id` is missing or unknown to the supplied `categories` list fall into a synthetic "其他 / Other" optgroup at the end.

- [ ] **Step 1: Write the file**

Create `frontend/src/components/BookmarkDropdown.tsx`:

```tsx
import React, { useMemo } from 'react'
import { useT } from '../i18n'

export interface BookmarkDropdownItem {
  id?: string
  name: string
  lat: number
  lng: number
  category_id?: string
}

export interface BookmarkDropdownCategory {
  id: string
  name: string
}

interface Props {
  bookmarks: BookmarkDropdownItem[]
  categories: BookmarkDropdownCategory[]
  /** Selected bookmark id; null = nothing selected (placeholder shown). */
  value: string | null
  onChange: (bm: BookmarkDropdownItem | null) => void
  placeholderText: string
  emptyText: string
  ariaLabel?: string
}

const BookmarkDropdown: React.FC<Props> = ({
  bookmarks,
  categories,
  value,
  onChange,
  placeholderText,
  emptyText,
  ariaLabel,
}) => {
  const t = useT()

  // Group bookmarks by category_id. Bookmarks with a missing or unknown
  // category_id fall into a synthetic "Other" group rendered at the end.
  const grouped = useMemo(() => {
    const knownIds = new Set(categories.map((c) => c.id))
    const byCat: Record<string, BookmarkDropdownItem[]> = {}
    const orphans: BookmarkDropdownItem[] = []
    for (const bm of bookmarks) {
      const cid = bm.category_id
      if (cid && knownIds.has(cid)) {
        if (!byCat[cid]) byCat[cid] = []
        byCat[cid].push(bm)
      } else {
        orphans.push(bm)
      }
    }
    return { byCat, orphans }
  }, [bookmarks, categories])

  if (bookmarks.length === 0) {
    return (
      <div
        style={{ fontSize: 12, color: '#9ca3af', padding: '6px 8px' }}
        role="status"
      >
        {emptyText}
      </div>
    )
  }

  // React requires unique keys; bookmarks without `id` get a synthetic key.
  // Such bookmarks cannot be selected (their <option> value won't match `value`),
  // but they still render in their group so the user sees the full list.
  const synthKey = (bm: BookmarkDropdownItem, idx: number) =>
    bm.id ?? `__noid_${idx}_${bm.name}`

  return (
    <select
      aria-label={ariaLabel}
      value={value ?? ''}
      onChange={(e) => {
        const id = e.target.value
        if (!id) {
          onChange(null)
          return
        }
        const found = bookmarks.find((bm) => bm.id === id) ?? null
        onChange(found)
      }}
      style={{
        width: '100%',
        padding: '6px 8px',
        border: '1px solid #4b5563',
        borderRadius: 4,
        background: '#1f2937',
        color: '#fff',
        fontSize: 12,
      }}
    >
      <option value="" disabled>
        {placeholderText}
      </option>
      {categories.map((cat) => {
        const items = grouped.byCat[cat.id]
        if (!items || items.length === 0) return null
        return (
          <optgroup key={cat.id} label={cat.name}>
            {items.map((bm, i) => (
              <option key={synthKey(bm, i)} value={bm.id ?? ''}>
                {bm.name}
              </option>
            ))}
          </optgroup>
        )
      })}
      {grouped.orphans.length > 0 && (
        <optgroup label={t('panel.bookmark_dropdown_other')}>
          {grouped.orphans.map((bm, i) => (
            <option key={synthKey(bm, i)} value={bm.id ?? ''}>
              {bm.name}
            </option>
          ))}
        </optgroup>
      )}
    </select>
  )
}

export default BookmarkDropdown
```

- [ ] **Step 2: Verify build**

Run:

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: exit 0. The component is unused so far — only its types must check.

- [ ] **Step 3: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/components/BookmarkDropdown.tsx
git commit -m "feat(ui): add reusable BookmarkDropdown"
```

---

## Task 3: Create `StartPositionPicker`

**Files:**
- Create: `frontend/src/components/StartPositionPicker.tsx`

Mode-panel section: title row + `BookmarkDropdown`. On pick, calls `onPick(lat, lng, name)`. Resets its internal `selectedId` to `null` after each pick so a subsequent pick of the SAME bookmark would still fire (the parent will normally unmount it because `currentPosition` becomes non-null).

- [ ] **Step 1: Write the file**

Create `frontend/src/components/StartPositionPicker.tsx`:

```tsx
import React, { useState, useCallback } from 'react'
import { useT } from '../i18n'
import BookmarkDropdown, {
  BookmarkDropdownItem,
  BookmarkDropdownCategory,
} from './BookmarkDropdown'

interface Props {
  bookmarks: BookmarkDropdownItem[]
  categories: BookmarkDropdownCategory[]
  onPick: (lat: number, lng: number, name: string) => void
}

const StartPositionPicker: React.FC<Props> = ({ bookmarks, categories, onPick }) => {
  const t = useT()
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const handleChange = useCallback(
    (bm: BookmarkDropdownItem | null) => {
      if (!bm) {
        setSelectedId(null)
        return
      }
      // Briefly mark as selected so the <select> shows the picked label
      // while the teleport request is in-flight; in practice the parent
      // unmounts us almost immediately because currentPosition becomes
      // non-null. Reset to null so a same-pick replay still fires.
      setSelectedId(bm.id ?? null)
      onPick(bm.lat, bm.lng, bm.name)
      // Reset on the next tick so a reuse of the same bookmark works if
      // the parent doesn't unmount us (e.g. teleport failed).
      setTimeout(() => setSelectedId(null), 0)
    },
    [onPick],
  )

  return (
    <div className="section" style={{ margin: '0 0 8px 0' }}>
      <div
        className="section-title"
        style={{ display: 'flex', alignItems: 'center', gap: 6 }}
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M12 22s-8-7.5-8-13a8 8 0 0116 0c0 5.5-8 13-8 13z" />
          <circle cx="12" cy="9" r="3" />
        </svg>
        {t('panel.start_picker_label')}
      </div>
      <div className="section-content">
        <BookmarkDropdown
          bookmarks={bookmarks}
          categories={categories}
          value={selectedId}
          onChange={handleChange}
          placeholderText={t('panel.start_picker_placeholder')}
          emptyText={t('panel.start_picker_empty')}
          ariaLabel={t('panel.start_picker_label')}
        />
      </div>
    </div>
  )
}

export default StartPositionPicker
```

- [ ] **Step 2: Verify build**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/components/StartPositionPicker.tsx
git commit -m "feat(ui): add StartPositionPicker mode-panel section"
```

---

## Task 4: Wire `StartPositionPicker` into ControlPanel and App.tsx

**Files:**
- Modify: `frontend/src/components/ControlPanel.tsx` — add 2 props, render the picker above `modeExtraSection`
- Modify: `frontend/src/App.tsx` — pass new props to `<ControlPanel>` (both render sites)

Adds two new ControlPanel props (`bookmarksRaw`, `bookmarkCategoriesFull`) instead of munging the existing `bookmarks` / `bookmarkCategories` shapes. The existing shapes feed `BookmarkList` and other consumers and stay name-based. Out of scope to converge them.

- [ ] **Step 1: Add new props to `ControlPanelProps`**

In `frontend/src/components/ControlPanel.tsx`, locate the props block ending at line 173 (`onCategoryDeleteCascade?: ...`). Just BEFORE the closing `}` of `interface ControlPanelProps`, insert:

```ts
  // -- Start-position picker (RandomWalk / Joystick / Navigate / Loop / MultiStop) --
  // Raw bookmark + category data forwarded to StartPositionPicker. Kept
  // separate from the legacy `bookmarks` / `bookmarkCategories` props which
  // serve BookmarkList (name-based shape, predates category_id propagation).
  bookmarksRaw?: Array<{
    id?: string
    name: string
    lat: number
    lng: number
    category_id?: string
  }>;
  bookmarkCategoriesFull?: Array<{ id: string; name: string }>;
```

- [ ] **Step 2: Destructure the new props in the component**

Locate the destructuring around line 251 (`const ControlPanel: React.FC<ControlPanelProps> = ({`) and add `bookmarksRaw`, `bookmarkCategoriesFull` to the parameter list. The exact location: after `goldDittoBookmarks` / `goldDittoCategories` (search for those names in the destructuring block) or anywhere convenient before the closing `}) => {`. Pick a spot near other related props and add:

```ts
  bookmarksRaw,
  bookmarkCategoriesFull,
```

- [ ] **Step 3: Add the import for `StartPositionPicker`**

Near the top of `ControlPanel.tsx`, alongside the other component imports (currently includes `RouteEngineSelector`, `PauseControl`, `AddressSearch`, `BookmarkList`, `GoldDittoPanel`, `ExportPopover`, `RouteList`), add:

```ts
import StartPositionPicker from './StartPositionPicker';
```

- [ ] **Step 4: Add `NEEDS_START_POS` set near the top of the file**

After the imports and before `interface ControlPanelProps`, near other top-level constants (e.g. after the `ApplySpeedButton` definition that ends around line 31), add:

```ts
const NEEDS_START_POS: ReadonlySet<SimMode> = new Set([
  SimMode.RandomWalk,
  SimMode.Joystick,
  SimMode.Navigate,
  SimMode.Loop,
  SimMode.MultiStop,
]);
```

- [ ] **Step 5: Render the picker above `modeExtraSection`**

In `ControlPanel.tsx`, find the line `{modeExtraSection}` (currently line 585). Replace that single line with:

```tsx
      {NEEDS_START_POS.has(simMode) && !currentPosition && bookmarksRaw && bookmarkCategoriesFull && (
        <StartPositionPicker
          bookmarks={bookmarksRaw}
          categories={bookmarkCategoriesFull}
          onPick={(lat, lng) => onTeleport(lat, lng)}
        />
      )}

      {modeExtraSection}
```

Note: `onTeleport` (existing prop, line 76) takes only `(lat, lng)`. We drop the `name` for now — adding it would require widening `onTeleport`'s signature and is out of scope. Recent-list tagging continues to use the existing right-click / address-search code paths.

- [ ] **Step 6: Wire the new props in `App.tsx` (first ControlPanel render site)**

In `frontend/src/App.tsx`, locate the first `<ControlPanel ...>` render (around line 1436). Find the existing `bookmarkCategories={bm.categories.map(c => c.name)}` line (currently line 1482). Immediately AFTER it, add:

```tsx
          bookmarksRaw={bm.bookmarks.map((b: any) => ({
            id: b.id,
            name: b.name,
            lat: b.lat,
            lng: b.lng,
            category_id: b.category_id,
          }))}
          bookmarkCategoriesFull={bm.categories.map(c => ({ id: c.id, name: c.name }))}
```

- [ ] **Step 7: Wire the new props in the second ControlPanel render site (if any)**

Search for other `<ControlPanel` occurrences in `App.tsx`:

```bash
cd /Users/raviwu/personal/locwarp && grep -n "<ControlPanel" frontend/src/App.tsx
```

If a second render site exists, apply the same `bookmarksRaw` + `bookmarkCategoriesFull` additions. If only one exists, skip. Expected: a single render site.

- [ ] **Step 8: Verify build**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vite build
```

Expected: type-check passes; Vite build succeeds. Smoke-runnable artifact in `frontend/dist/`.

- [ ] **Step 9: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/components/ControlPanel.tsx frontend/src/App.tsx
git commit -m "feat(ui): mount StartPositionPicker for modes needing currentPosition"
```

---

## Task 5: Refactor GoldDittoPanel B-side

**Files:**
- Modify: `frontend/src/components/GoldDittoPanel.tsx` (extensive changes — see steps)
- Modify: `frontend/src/i18n/strings.ts` (delete 3 obsolete keys)

Drops manual coord input, random-Taiwan, and map-center for B. Uses `BookmarkDropdown` driven by a new `bBookmarkId` state. Migrates legacy `goldditto.B` coord-string localStorage to `goldditto.B.bookmarkId`.

- [ ] **Step 1: Add the import for `BookmarkDropdown`**

In `frontend/src/components/GoldDittoPanel.tsx`, near the top alongside the existing `BookmarkPickerPopover` import, add:

```ts
import BookmarkDropdown from './BookmarkDropdown'
```

- [ ] **Step 2: Replace the localStorage keys constants**

Locate (currently lines 44–47):

```ts
const DEFAULT_B = '25.034897, 121.545827'
const LS_A = 'goldditto.A'
const LS_B = 'goldditto.B'
const LS_WAIT = 'goldditto.wait_seconds'
```

Replace with:

```ts
const LS_A = 'goldditto.A'
const LS_B_LEGACY = 'goldditto.B'              // pre-2026-05-10: stored "lat, lng"
const LS_B_BOOKMARK_ID = 'goldditto.B.bookmarkId' // new: bookmark id only
const LS_WAIT = 'goldditto.wait_seconds'
const COORD_MATCH_TOLERANCE = 1e-5
```

- [ ] **Step 3: Delete `randomTaiwanCoord`**

Remove the function (currently lines 49–54):

```ts
// Taiwan main-island bounding box (24.0–25.5°N, 120.5–122.0°E).
function randomTaiwanCoord(): string {
  const lat = 24.0 + Math.random() * 1.5
  const lng = 120.5 + Math.random() * 1.5
  return `${lat.toFixed(6)}, ${lng.toFixed(6)}`
}
```

`parseLatLng` stays — it's still needed for the legacy migration (Step 5).

- [ ] **Step 4: Replace `bText` state with `bBookmarkId` and migration effect**

Locate (currently lines 79–83):

```ts
const [aText, setAText] = useState(() => localStorage.getItem(LS_A) ?? '')
const [bText, setBText] = useState(() => localStorage.getItem(LS_B) ?? DEFAULT_B)
const [waitText, setWaitText] = useState(
  () => localStorage.getItem(LS_WAIT) ?? '3.0',
)
```

Replace the middle line with:

```ts
const [bBookmarkId, setBBookmarkId] = useState<string | null>(
  () => localStorage.getItem(LS_B_BOOKMARK_ID),
)
```

So the block becomes:

```ts
const [aText, setAText] = useState(() => localStorage.getItem(LS_A) ?? '')
const [bBookmarkId, setBBookmarkId] = useState<string | null>(
  () => localStorage.getItem(LS_B_BOOKMARK_ID),
)
const [waitText, setWaitText] = useState(
  () => localStorage.getItem(LS_WAIT) ?? '3.0',
)
```

- [ ] **Step 5: Add legacy migration effect**

Immediately after the persistence effects block (currently lines 119–122 with the three `useEffect`s for `LS_A`, `LS_B`, `LS_WAIT`), insert a one-shot migration effect. First, replace the `useEffect(() => { localStorage.setItem(LS_B, bText) }, [bText])` line entirely — its companion state is gone — with the migration block:

```ts
useEffect(() => { localStorage.setItem(LS_A, aText) }, [aText])
useEffect(() => {
  if (bBookmarkId) localStorage.setItem(LS_B_BOOKMARK_ID, bBookmarkId)
  else localStorage.removeItem(LS_B_BOOKMARK_ID)
}, [bBookmarkId])
useEffect(() => { localStorage.setItem(LS_WAIT, waitText) }, [waitText])

// One-shot migration: if no new key but legacy "lat, lng" coord exists,
// try to match a bookmark within COORD_MATCH_TOLERANCE; otherwise drop it.
// `bookmarks` loads async (empty array until useBookmarks resolves); the
// guard `bookmarks.length === 0 ? return` defers the decision until at
// least one bookmark is visible. If the user genuinely has zero bookmarks,
// the migration sits idle (cheap no-op) until they add one or pick B.
const migratedRef = React.useRef(false)
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

The migration runs once: if a bookmark match is found, B is preselected; otherwise the legacy key is dropped silently and B starts unselected.

- [ ] **Step 6: Replace `b` derivation**

Locate (currently lines 129–130):

```ts
const a = useMemo(() => parseLatLng(aText), [aText])
const b = useMemo(() => parseLatLng(bText), [bText])
```

Replace the `b` line with:

```ts
const b = useMemo(() => {
  if (!bBookmarkId) return null
  const bm = bookmarks.find((x) => x.id === bBookmarkId)
  return bm ? { lat: bm.lat, lng: bm.lng } : null
}, [bBookmarkId, bookmarks])
```

`a` stays as-is — A side is unchanged.

- [ ] **Step 7: Drop `pickerCatB` state and its persistence**

Locate (currently lines 90–95):

```ts
const [pickerCatA, setPickerCatA] = useState<string | null>(
  () => localStorage.getItem('goldditto.picker.A.lastCategory'),
)
const [pickerCatB, setPickerCatB] = useState<string | null>(
  () => localStorage.getItem('goldditto.picker.B.lastCategory'),
)
```

Remove the `pickerCatB` declaration:

```ts
const [pickerCatA, setPickerCatA] = useState<string | null>(
  () => localStorage.getItem('goldditto.picker.A.lastCategory'),
)
```

Note: we leave `'goldditto.picker.B.lastCategory'` data in localStorage for users who upgrade — it's harmless dead bytes. No active cleanup needed.

- [ ] **Step 8: Update `handlePick` to drop B branch**

Locate (currently lines 176–180):

```ts
const handlePick = (bm: { lat: number; lng: number }) => {
  const text = `${bm.lat.toFixed(6)}, ${bm.lng.toFixed(6)}`
  if (pickerSide === 'A') setAText(text)
  else if (pickerSide === 'B') setBText(text)
}
```

Replace with:

```ts
const handlePick = (bm: { lat: number; lng: number }) => {
  // Picker is now A-side only; B uses the inline BookmarkDropdown.
  if (pickerSide === 'A') {
    setAText(`${bm.lat.toFixed(6)}, ${bm.lng.toFixed(6)}`)
  }
}
```

- [ ] **Step 9: Update `handleCategoryChange` to drop B branch**

Locate (currently lines 182–190):

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

Replace with:

```ts
const handleCategoryChange = (catId: string) => {
  if (pickerSide === 'A') {
    setPickerCatA(catId)
    try { localStorage.setItem('goldditto.picker.A.lastCategory', catId) } catch { /* ignore */ }
  }
}
```

- [ ] **Step 10: Drop `handleRandomB` and `handleUseMapCenter`**

Locate (currently lines 165–168):

```ts
const handleRandomB = () => setBText(randomTaiwanCoord())
const handleUseMapCenter = () => {
  if (mapCenter) setBText(`${mapCenter.lat.toFixed(6)}, ${mapCenter.lng.toFixed(6)}`)
}
```

Delete both. The `mapCenter` prop now has no consumers in this component, but is left in the props interface untouched — `goldditto.set_as_a` map-right-click flow (`externalAValue`) is the surviving channel from MapView, and removing `mapCenter` would force ControlPanel and App.tsx changes that are out of scope.

- [ ] **Step 11: Replace the B `<label>` block in JSX**

Locate the entire B `<label>` block (currently lines 237–272), starting with:

```tsx
<label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
  <span style={{ fontSize: 12, color: '#9ca3af' }}>{t('goldditto.b_label')}</span>
  <div style={{ display: 'flex', gap: 4 }}>
    <input
      type="text"
      value={bText}
      ...
```

…and ending with:

```tsx
      <button onClick={handleUseMapCenter} className="action-btn" style={{ fontSize: 12, flex: 1 }}
              disabled={!mapCenter}>
        {t('goldditto.use_map_center')}
      </button>
    </div>
  </label>
```

Replace the entire block with:

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

- [ ] **Step 12: Drop B from the BookmarkPickerPopover render**

Locate (currently lines 317–330):

```tsx
<BookmarkPickerPopover
  open={pickerSide !== null}
  side={pickerSide ?? 'A'}
  ...
  initialCategoryId={pickerSide === 'A' ? pickerCatA : pickerCatB}
  ...
/>
```

Change `initialCategoryId={pickerSide === 'A' ? pickerCatA : pickerCatB}` to:

```tsx
  initialCategoryId={pickerCatA}
```

The popover now only ever serves A. The `side` prop still receives `pickerSide ?? 'A'` for shape compatibility — `pickerSide` will only ever be `'A'` or `null` in practice after this refactor.

- [ ] **Step 13: Delete obsolete i18n keys**

In `frontend/src/i18n/strings.ts`, delete these three entries (currently lines 159, 160, 172):

```ts
'goldditto.random_b': { zh: '🎲 隨機台灣 B 點', en: '🎲 Random Taiwan B' },
'goldditto.use_map_center': { zh: '📍 用目前地圖中心', en: '📍 Use current map center' },
```

```ts
'goldditto.pick_from_bookmarks_tooltip_b': { zh: '從書籤選 B 點', en: 'Pick B from bookmarks' },
```

- [ ] **Step 14: Sanity-check no stale references**

Search the whole frontend for any remaining usage of the deleted i18n keys or removed handlers:

```bash
cd /Users/raviwu/personal/locwarp && grep -rn "goldditto.random_b\|goldditto.use_map_center\|goldditto.pick_from_bookmarks_tooltip_b\|handleRandomB\|handleUseMapCenter\|DEFAULT_B\|randomTaiwanCoord" frontend/src
```

Expected: zero matches. If any matches surface, resolve them inline before proceeding.

- [ ] **Step 15: Verify build**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vite build
```

Expected: type-check and Vite build both succeed.

- [ ] **Step 16: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/components/GoldDittoPanel.tsx frontend/src/i18n/strings.ts
git commit -m "refactor(goldditto): bookmark-only B selection, drop manual/random/map-center"
```

---

## Task 6: Manual smoke verification

**Files:** none (verification only)

No new component tests are added (project has no frontend test harness). This task documents the manual smoke that must pass before the branch is merged.

- [ ] **Step 1: Run dev server**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npm run dev
```

Open the app. If a device is connected, disconnect it before testing — the picker is currentPosition-gated, not device-gated, but this avoids ghost positions from prior sessions.

- [ ] **Step 2: Smoke — five modes show the picker on fresh launch**

For each of `RandomWalk`, `Joystick`, `Navigate`, `Loop`, `MultiStop`:

1. Switch to the mode tab.
2. Confirm StartPositionPicker section is visible above the mode-specific controls.
3. If at least one bookmark exists, the dropdown lists categories with bookmarks underneath.
4. If no bookmarks exist, the empty-state hint text is visible.

Expected: picker visible, no JS console errors.

- [ ] **Step 3: Smoke — Teleport and GoldDitto modes do NOT show the picker**

1. Switch to `Teleport`. Verify picker is NOT rendered.
2. Switch to `GoldDitto`. Verify picker is NOT rendered (GoldDitto has its own A/B flow).

Expected: picker hidden in both modes.

- [ ] **Step 4: Smoke — picking a bookmark teleports and hides the picker**

1. In RandomWalk mode with no currentPosition, pick a bookmark from the dropdown.
2. Verify map marker moves to the bookmark coord.
3. Verify the StartPositionPicker section unmounts (picker gone).
4. Verify Start button now starts a random walk centered at the bookmark.

Expected: smooth handoff, no toast errors, behavior matches existing teleport-from-library.

- [ ] **Step 5: Smoke — GoldDitto B selection works**

1. Switch to GoldDitto mode.
2. Verify B row shows the new BookmarkDropdown (no text input, no random/map-center buttons).
3. Pick a B bookmark. Confirm "② First try" enables.
4. Set A (via text input or A's 📚 popover, both unchanged), then run "② First try".
5. Verify cycle teleports to the picked B's coord.

Expected: cycle works against bookmark-derived B coord.

- [ ] **Step 6: Smoke — B legacy migration**

1. Before opening the app, set localStorage manually:
   - In DevTools console: `localStorage.setItem('goldditto.B', '<lat>, <lng>')` where `<lat>, <lng>` matches a known bookmark within `1e-5`.
   - Ensure `goldditto.B.bookmarkId` is NOT set (`localStorage.removeItem('goldditto.B.bookmarkId')`).
2. Reload the app and open GoldDitto.
3. Verify B dropdown is preselected to the matching bookmark.
4. Verify `goldditto.B` legacy key has been removed (`localStorage.getItem('goldditto.B')` returns `null`).
5. Verify `goldditto.B.bookmarkId` is set to the bookmark's id.

Expected: silent successful migration.

- [ ] **Step 7: Smoke — B legacy migration with no match**

1. `localStorage.setItem('goldditto.B', '0, 0')` (a coord no bookmark uses).
2. `localStorage.removeItem('goldditto.B.bookmarkId')`.
3. Reload and open GoldDitto.
4. Verify B dropdown shows placeholder (unselected).
5. Verify `goldditto.B` legacy key has been removed.

Expected: silent drop, no error.

- [ ] **Step 8: Smoke — deleting a B's source bookmark disables First try**

1. Pick a B bookmark, "② First try" enables.
2. Open Library, delete that bookmark.
3. Return to GoldDitto. Verify B dropdown shows placeholder (the now-orphan id resolves to nothing).
4. Verify "② First try" is disabled.

Expected: graceful self-heal.

- [ ] **Step 9: Smoke — empty bookmarks state in GoldDitto**

1. Delete all bookmarks (or test on a fresh profile).
2. Open GoldDitto. Verify B row shows the empty hint (`goldditto.b_picker_empty`).

Expected: no `<select>` rendered, hint text visible.

- [ ] **Step 10: Smoke — dual-device group mode (only if 2 devices available)**

1. Connect two devices.
2. In RandomWalk mode with no currentPosition, pick a bookmark via StartPositionPicker.
3. Verify both devices teleport to the bookmark coord.
4. Press Start; both devices should run synchronized random walk.

Expected: existing group-mode `handleTeleport` flow handles fan-out as before.

- [ ] **Step 11: Final commit (smoke fixes only)**

If any tweaks were needed during smoke, commit them with a focused message. If smoke was clean, no further commit needed.

```bash
cd /Users/raviwu/personal/locwarp
git status
# If clean, skip commit. Otherwise:
git add <only files touched during smoke fix>
git commit -m "fix(ui): <specific issue from smoke>"
```

---

## Self-Review Notes

**Spec coverage:**
- §4.1 BookmarkDropdown → Task 2 ✓
- §4.2 StartPositionPicker → Task 3 ✓
- §4.3 GoldDitto B refactor (state, migration, JSX, popover B drop) → Task 5 (steps 1–12) ✓
- §4.4 ControlPanel integration (new props, mount logic) → Task 4 ✓
- §5 i18n adds, modify, deletes → Task 1 (adds + modify), Task 5 step 13 (deletes) ✓
- §6 Behavior matrix — covered indirectly by smoke steps in Task 6 ✓
- §7 Testing — automated component tests intentionally NOT included (no harness); §7 manual smoke fully mapped in Task 6 ✓

**Type consistency:**
- `BookmarkDropdownItem` shape (id?, name, lat, lng, category_id?) used identically in Tasks 2, 3, 4, 5.
- `BookmarkDropdownCategory` shape (id, name) consistent across all sites.
- ControlPanel new props `bookmarksRaw` / `bookmarkCategoriesFull` shape matches what Task 4 step 6 wires from `App.tsx` (`bm.bookmarks`, `bm.categories`).

**Placeholder scan:** None.
