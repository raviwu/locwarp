# Event Soft-Archive (Date-bound Bookmark Categories) — Design

**Date:** 2026-05-09
**Status:** Draft (pending user review)
**Author:** Ravi Wu
**Type:** Feature design (extends 2026-05-09 GoldDitto Bookmark Management)

---

## 1. Background

The bookmark system treats each `BookmarkCategory` as an "event" by convention
(see `2026-05-09-goldditto-bookmark-management-design.md`). Real Pikmin Bloom
events fall into three temporal shapes:

- **Permanent** — e.g. 札幌 Pikmin Bloom Tour（常設活動）, 京都散步（沒有截止期限）.
- **Time-bound** — e.g. Sanga Stadium 特殊地點 (2026/2/6 ~ 2026/6/7).
- **Recurring annual** — e.g. 札幌 Tour 每年可參加一次. Out of scope here;
  treated as permanent because Pikmin Bloom marks them 常設.

With a dozen events accumulating over a year, the Library category list and the
GoldDitto A/B picker both grow noisy. Time-bound events that have ended remain
visible at full opacity even though the user is unlikely to need them again
this year.

## 2. Goals

1. Add optional `start_date` and `end_date` to `BookmarkCategory`.
2. Derive `'evergreen' | 'upcoming' | 'active' | 'ended'` on the frontend from
   those two fields plus the user's local date.
3. In the Library: default-collapse `upcoming` and `ended` categories and tag
   their headers with grey/blue status chips. Preserve any prior manual expand.
4. In the GoldDitto picker: hide `ended` categories by default. Add a per-side
   "Include ended" checkbox persisted in `localStorage`.
5. Replace the existing inline-rename pencil with a full "Edit category" dialog
   that edits name, color, start date, and end date together.

## 3. Non-Goals

- No automatic yearly reset / recurring event logic. `常設活動，每年可參加一次`
  is modelled as evergreen (both dates empty).
- No date fields on individual `Bookmark`s — event granularity stays at the
  category.
- No backend scheduler, no expiry notifications, no auto-hard-delete. Existing
  cascade delete already covers "I want to wipe this event now."
- No manual `is_archived` override. Soft-archive is purely date-derived.
- No change to the existing `AUTO_COLLAPSE_THRESHOLD = 30` rule. The new logic
  augments the default-collapsed calculation only.
- Picker does NOT hide `upcoming`. Future events stay visible because the user
  may want to pre-pick.
- No timezone handling. Comparison uses `new Date().toLocaleDateString('sv-SE')`
  in the user's local timezone. Cross-midnight 1-hour drift across regions is
  acceptable.

## 4. Data Model

### 4.1 Schema (`backend/models/schemas.py`)

```python
class BookmarkCategory(BaseModel):
    id: str = ""
    name: str
    color: str = "#6c8cff"
    sort_order: int = 0
    created_at: str = ""
    # ISO 8601 date 'YYYY-MM-DD'. Empty string = unbounded on that side.
    # Both empty → evergreen (never archives). Validated in API layer.
    start_date: str = ""
    end_date: str = ""
```

### 4.2 Storage Migration

Existing `bookmarks.json` files lack the two new keys. Pydantic supplies the
default `""`, so `BookmarkStore(**data)` parses unchanged. The next `_save()`
writes the new keys. Zero migration script.

### 4.3 Validation (API Layer)

Both fields accept `""`. Non-empty values must:

- Match `^\d{4}-\d{2}-\d{2}$`.
- Parse via `datetime.date.fromisoformat()`.
- Satisfy `start_date <= end_date` when both are non-empty.

Violations → HTTP 422.

### 4.4 Status Derivation (Pure Frontend)

`frontend/src/utils/categoryStatus.ts` (new file):

```ts
export type CategoryStatus = 'evergreen' | 'upcoming' | 'active' | 'ended';

export function getCategoryStatus(
  start: string,    // '' or 'YYYY-MM-DD'
  end: string,      // '' or 'YYYY-MM-DD'
  today: string,    // 'YYYY-MM-DD' in user-local time
): CategoryStatus {
  if (!start && !end) return 'evergreen';
  if (start && today < start) return 'upcoming';
  if (end && today > end) return 'ended';
  return 'active';
}

export function todayLocal(): string {
  return new Date().toLocaleDateString('sv-SE'); // 'YYYY-MM-DD'
}
```

ISO date strings sort lexically; no `Date` parsing required.

### 4.5 Status Truth Table

| `start_date` | `end_date` | Today | Status |
|---|---|---|---|
| `""` | `""` | any | `evergreen` |
| `2026-06-01` | `""` | `2026-05-30` | `upcoming` |
| `2026-06-01` | `""` | `2026-06-01` | `active` (inclusive) |
| `""` | `2026-06-07` | `2026-06-07` | `active` (last day) |
| `""` | `2026-06-07` | `2026-06-08` | `ended` |
| `2026-02-06` | `2026-06-07` | `2026-05-09` | `active` |
| `2026-02-06` | `2026-06-07` | `2026-06-08` | `ended` |
| `2026-06-01` | `2026-06-01` | `2026-06-01` | `active` (single-day) |

UI recomputes on every render; no timer, no scheduled re-render.

## 5. Backend Changes

### 5.1 `backend/api/bookmarks.py`

Add a top-level helper:

```python
import re
from datetime import date as _date

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def _validate_date_range(start: str, end: str) -> None:
    """Raise HTTPException(422) on invalid date strings or inverted range."""
    for label, val in (("start_date", start), ("end_date", end)):
        if val == "":
            continue
        if not _ISO_DATE_RE.match(val):
            raise HTTPException(422, f"{label} must be YYYY-MM-DD or empty")
        try:
            _date.fromisoformat(val)
        except ValueError:
            raise HTTPException(422, f"{label} is not a valid calendar date")
    if start and end and start > end:
        raise HTTPException(422, "start_date must be <= end_date")
```

Wire it into `create_category` and `update_category`. `delete_category`,
`list_categories`, and the bookmark endpoints are unchanged.

```python
@router.post("/categories", response_model=BookmarkCategory)
async def create_category(cat: BookmarkCategory):
    _validate_date_range(cat.start_date, cat.end_date)
    bm = _bm()
    return bm.create_category(
        name=cat.name,
        color=cat.color,
        start_date=cat.start_date,
        end_date=cat.end_date,
    )

@router.put("/categories/{cat_id}", response_model=BookmarkCategory)
async def update_category(cat_id: str, cat: BookmarkCategory):
    _validate_date_range(cat.start_date, cat.end_date)
    bm = _bm()
    updated = bm.update_category(
        cat_id,
        name=cat.name,
        color=cat.color,
        start_date=cat.start_date,
        end_date=cat.end_date,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Category not found")
    return updated
```

### 5.2 `backend/services/bookmarks.py`

```python
def create_category(
    self,
    name: str,
    color: str = "#6c8cff",
    start_date: str = "",
    end_date: str = "",
) -> BookmarkCategory:
    max_order = max((c.sort_order for c in self.store.categories), default=-1)
    cat = BookmarkCategory(
        id=str(uuid.uuid4()),
        name=name,
        color=color,
        sort_order=max_order + 1,
        created_at=_now_iso(),
        start_date=start_date,
        end_date=end_date,
    )
    self.store.categories.append(cat)
    self._save()
    return cat

def update_category(
    self,
    cat_id: str,
    name: str | None = None,
    color: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> BookmarkCategory | None:
    cat = self._find_category(cat_id)
    if cat is None:
        return None
    if name is not None: cat.name = name
    if color is not None: cat.color = color
    if start_date is not None: cat.start_date = start_date
    if end_date is not None: cat.end_date = end_date
    self._save()
    return cat
```

`is not None` distinguishes "do not modify" (omit the key) from "clear"
(send `""`). The frontend Save action always sends the full dict, so empty
strings clear the field cleanly.

### 5.3 Read Endpoints

`GET /api/bookmarks` and `GET /api/bookmarks/categories` need no code change —
Pydantic serialises `start_date` / `end_date` automatically.

### 5.4 Export / Import

| Format | Treatment |
|---|---|
| `json` (whole-store + single-category) | Round-trips dates via Pydantic. |
| `markdown` | Unchanged — human-readable share format, no dates emitted. |
| `geojson` | Unchanged. |
| `csv` | Unchanged. |

Date metadata is exposed only through JSON. Markdown / GeoJSON / CSV imports
create evergreen categories.

## 6. Frontend — Edit Category Dialog

Replace the current inline-rename interaction in the Category Manager (the
pencil icon currently swaps the name into an `<input>`) with a modal dialog
matching the style of `showAddDialog` / `showCustomDialog`.

### 6.1 Layout

```
┌─ Edit category ─────────────────┐
│ Name      [Sanga Stadium      ] │
│ Color     ● ○ ○ ○ ○ ○ ○ ○ ○ ○   │
│ Starts    [2026-02-06]  [✕清空] │
│ Ends      [2026-06-07]  [✕清空] │
│ ⓘ 留空 = 永久(不會自動隱藏)      │
│ [Cancel]               [Save]   │
└─────────────────────────────────┘
```

- `<input type="date">` for both fields. Each has an adjacent `✕ Clear`
  button that sets the value to `""`.
- Color uses the existing `COLOR_PALETTE` row plus a custom-color input.
- Save is disabled when `start && end && start > end`, with hint text
  `End date must be on or after start date`.
- Save dispatches `onCategoryEdit(catId, { name, color, start_date, end_date })`,
  which calls `PUT /api/bookmarks/categories/{id}`.
- The dialog is NOT shown for the Default category. The pencil icon hides for
  Default, matching the existing "default category cannot be renamed" rule.

### 6.2 Props

`BookmarkList` adds `onCategoryEdit: (id: string, patch: { name: string; color: string; start_date: string; end_date: string }) => void`.

Legacy `onCategoryRename` and `onCategoryRecolor` are removed in this PR
along with their inline call sites — `App.tsx` switches to a single
`onCategoryEdit` handler that wraps `PUT /api/bookmarks/categories/{id}`
with the full patch. Net diff is smaller than maintaining two parallel
call paths.

### 6.3 i18n Keys (new)

```ts
'bm.cat.edit_title':       { zh: '編輯分類', en: 'Edit category' },
'bm.cat.starts':           { zh: '開始日期', en: 'Starts' },
'bm.cat.ends':             { zh: '結束日期', en: 'Ends' },
'bm.cat.dates_hint':       { zh: '留空 = 永久(不會自動隱藏)', en: 'Leave empty for evergreen (never auto-hide)' },
'bm.cat.dates_clear':      { zh: '清空',     en: 'Clear' },
'bm.cat.dates_invalid':    { zh: '結束日期須晚於或等於開始日期', en: 'End date must be on or after start date' },
'bm.cat.save':             { zh: '儲存',     en: 'Save' },
```

## 7. Frontend — Library Category List

### 7.1 Data Threading

`App.tsx` derives a name-keyed map alongside the existing `categoryColors`:

```ts
const categoryDates: Record<string, { start_date: string; end_date: string }> =
  Object.fromEntries(
    categories.map(c => [c.name, { start_date: c.start_date, end_date: c.end_date }])
  );
```

Pass to `BookmarkList` as `categoryDates`. Picker uses the same source data
keyed by `id` (see §8).

### 7.2 Default-Collapse Integration

Modify the existing collapse `useEffect` (currently lines 309–334 in
`BookmarkList.tsx`):

```ts
const computeDefaultCollapsed = (cat: string): boolean => {
  const d = categoryDates?.[cat];
  if (!d) return false;
  const status = getCategoryStatus(d.start_date, d.end_date, todayLocal());
  return status === 'ended' || status === 'upcoming';
};
```

Branch changes:

- **Over threshold** — unchanged: collapse all.
- **Under threshold + saved snapshot is `null`** — replace `setCollapsed({})`
  with `Object.fromEntries(categories.map(c => [c, computeDefaultCollapsed(c)]))`.
- **Under threshold + saved snapshot exists** — replace
  `next[c] = !savedSet.has(c)` with
  `next[c] = savedSet.has(c) ? false : computeDefaultCollapsed(c)`.

Result:
- Categories the user explicitly expanded survive (saved snapshot wins).
- New categories never expanded: `ended` / `upcoming` start collapsed,
  `active` / `evergreen` start expanded.
- A category that becomes `ended` overnight collapses on the next mount unless
  the user had previously expanded it.

### 7.3 Header Chip + Opacity

Each rendered group header (currently lines 992–1054) computes:

```tsx
const status = categoryDates?.[cat]
  ? getCategoryStatus(categoryDates[cat].start_date, categoryDates[cat].end_date, today)
  : 'evergreen';
```

| Status | Opacity | Chip |
|---|---|---|
| `evergreen` / `active` | 1 (existing 0.8 on header text) | none |
| `ended` | 0.5 | `已結束` — bg `#3a3a3e`, fg `#9aa0a6`, 10px, 4px padding |
| `upcoming` | 0.7 | `即將開始 M/D` — bg `rgba(59,130,246,0.18)`, fg `#7aa9ff` |

The disclosure caret, color dot, and bookmark count remain. Bookmark items
inside a collapsed-by-default category render normally when the user expands —
no additional fading.

### 7.4 i18n (new)

```ts
'bm.cat.status_ended':    { zh: '已結束',          en: 'Ended' },
'bm.cat.status_upcoming': { zh: '即將開始 {date}',  en: 'Starts {date}' },
```

`{date}` is locale-formatted from `start_date` via
`Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' })`, where
`locale` is the active i18n locale (`zh-TW` or `en-US`). Examples:

| `start_date` | zh-TW | en-US |
|---|---|---|
| `2026-06-07` | `6月7日` | `Jun 7` |
| `2026-12-25` | `12月25日` | `Dec 25` |

A small helper lives next to `getCategoryStatus`:

```ts
export function formatChipDate(iso: string, locale: string): string {
  // iso must be 'YYYY-MM-DD'; treat as UTC to avoid TZ-shift on the
  // formatter (we only care about month/day, not wall-clock time).
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return new Intl.DateTimeFormat(locale, {
    month: 'short', day: 'numeric', timeZone: 'UTC',
  }).format(dt);
}
```

## 8. Frontend — GoldDitto Picker

### 8.1 Data + Default Filter

`BookmarkPickerPopover` props add:

```ts
categoryDates?: Record<string, { start_date: string; end_date: string }>; // by id
```

(Keyed by `id` here, in contrast with the by-name map fed to BookmarkList. The
picker already operates on `BookmarkCategory` objects with stable ids, so
there's no need to round-trip through name.)

```ts
const visibleCategories = useMemo(() => {
  const today = todayLocal();
  return categories.filter((c) => {
    const d = categoryDates?.[c.id];
    if (!d) return true;
    if (includeEnded) return true;
    return getCategoryStatus(d.start_date, d.end_date, today) !== 'ended';
  });
}, [categories, categoryDates, includeEnded]);
```

### 8.2 Include-Ended Checkbox

Inserted above the category select:

```tsx
<label style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: 11, opacity: 0.7 }}>
  <input
    type="checkbox"
    checked={includeEnded}
    onChange={(e) => {
      setIncludeEnded(e.target.checked);
      localStorage.setItem(`goldditto.picker.${side}.includeEnded`, String(e.target.checked));
    }}
  />
  {t('bm.picker.include_ended')}
</label>
```

State initialiser:

```ts
const [includeEnded, setIncludeEnded] = useState<boolean>(
  () => localStorage.getItem(`goldditto.picker.${side}.includeEnded`) === 'true',
);
```

Default `false`. Per-side independent (A and B remember separately, matching
the existing `goldditto.picker.{side}.lastCategory` pattern).

### 8.3 Last-Used Fallback

When `initialCategoryId` points at a category that is now filtered out
(`ended` and `includeEnded=false`), the existing `useEffect` that syncs
`selectedCatId` to `initialCategoryId` falls back to `visibleCategories[0]?.id ?? 'default'`:

```ts
useEffect(() => {
  const stillVisible = visibleCategories.some(c => c.id === initialCategoryId);
  setSelectedCatId(
    initialCategoryId && stillVisible
      ? initialCategoryId
      : (visibleCategories[0]?.id ?? 'default')
  );
}, [initialCategoryId, open, visibleCategories]);
```

The fallback does NOT write back to `localStorage`. If the user toggles
"Include ended" the original choice reappears.

### 8.4 i18n (new)

```ts
'bm.picker.include_ended': { zh: '包含已結束', en: 'Include ended' },
```

## 9. Edge Cases

| Scenario | Behaviour |
|---|---|
| Existing `bookmarks.json` lacks new fields | Pydantic defaults → `""`, evergreen. |
| User sets `start_date` to a future date | UI re-renders → blue `即將開始` chip, default collapse if not previously expanded. |
| User sets `end_date` to a past date | Immediately ends → grey chip, default collapse if not previously expanded. |
| User wants to teleport to an old spot in an ended category | Library expand still works; clicking a bookmark teleports as before. |
| Picker opened with last-used now ended (`includeEnded=false`) | Auto-fallback to first visible; `localStorage` untouched. |
| `start_date > end_date` | Backend 422; frontend Save disabled. |
| `start_date == end_date == today` | `active` (single-day event). |
| Default category | Edit dialog hides date fields and the pencil icon, matching the existing "Default cannot be renamed" rule. Backend has no special guard — date setting is UI-prevented only, mirroring the existing rename flow. |
| Cascade delete on ended category | Existing flow, unchanged. |
| Bulk paste into an ended category | Allowed (rare retroactive cleanup). |
| Cross-midnight on the boundary day | UI updates on next render; no timer. |
| Single-category JSON export → import | Dates round-trip via Pydantic. |
| GeoJSON / Markdown / CSV import | Resulting category is evergreen. |
| Two devices write the same category concurrently | Existing `safe_write_json` atomicity unchanged; date edits are a regular field write. |

## 10. Testing

### 10.1 Backend (pytest)

- `_validate_date_range` accepts `("", "")`, `("2026-06-01", "")`,
  `("", "2026-06-01")`, `("2026-02-01", "2026-06-01")`.
- `_validate_date_range` raises 422 on `("2026/06/01", "")`,
  `("not-a-date", "")`, `("2026-13-01", "")`, `("2026-06-30", "2026-06-29")`.
- `BookmarkManager.create_category(start_date="2026-06-01", end_date="2026-06-07")`
  persists and returns those values.
- `update_category(cat_id, start_date="")` clears an existing date.
- `update_category(cat_id, start_date=None)` leaves the existing date intact.
- `GET /api/bookmarks` returns the new fields.
- Loading a fixture without `start_date`/`end_date` yields evergreen categories.
- Single-category JSON export → import preserves dates.

### 10.2 Frontend (Vitest)

- `getCategoryStatus` covers all 8 truth-table rows.
- `todayLocal()` returns `YYYY-MM-DD`.
- `BookmarkList`: `ended` category with no saved snapshot starts collapsed;
  `active` starts expanded.
- `BookmarkList`: a category in `expanded_categories` stays expanded even when
  its status is `ended`.
- `BookmarkList`: header renders `已結束` chip for `ended`,
  `即將開始 M/D` chip for `upcoming`.
- `BookmarkPickerPopover`: `includeEnded=false` filters out `ended` categories.
- `BookmarkPickerPopover`: toggling the checkbox writes the per-side key to
  `localStorage`.
- `BookmarkPickerPopover`: `initialCategoryId` pointing at an ended category
  with `includeEnded=false` falls back to the first visible.

### 10.3 Manual Smoke

1. Create category `Sanga Stadium`, set start `2026-02-06`, end `2026-06-07`.
   Today (2026-05-09) → `active`, no chip, expanded.
2. Edit end to `2026-05-08`. Header turns grey, `已結束` chip appears, group
   collapses on next render.
3. Click the caret to expand. Reload the app. Group remains expanded
   (`expanded_categories` snapshot wins).
4. Open GoldDitto picker A. `Sanga Stadium` is hidden. Tick `包含已結束` →
   it appears → click a spot → A coordinate populates.
5. Untick the checkbox, close the popover, reopen. Picker auto-falls-back to
   the first visible category.

## 11. Seed Data

A sample `bookmarks.json` payload covering the data the user has already
collected from Pikmin Bloom announcements lives at
`docs/samples/pikmin-bloom-events.json`. It is a full-store import shape
(`{ "categories": [...], "bookmarks": [...] }`) and round-trips through
`POST /api/bookmarks/import`.

Categories included:

| Category | Dates | Bookmarks |
|---|---|---|
| Sapporo Pikmin Bloom Tour | evergreen (`""`, `""`) | 12 spots (A–L) |
| Sanga Stadium by KYOCERA | `2026-02-06` ~ `2026-06-07` | 1 spot |

The Sanga category exercises the `active → ended` transition (it is
`active` while today ≤ `2026-06-07` and `ended` from `2026-06-08`
onwards). Sapporo Tour is permanent. The seed lets reviewers verify the
soft-archive behaviour against real coordinates without manual entry.

## 12. Open Questions

None at design approval time. Implementation may surface:

- Whether `App.tsx` should expose the by-name and by-id date maps from a single
  selector, or compute both inline. Mechanical, resolved during implementation.
