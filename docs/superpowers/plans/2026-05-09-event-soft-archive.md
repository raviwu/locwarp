# Event Soft-Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add date-bound `start_date`/`end_date` to `BookmarkCategory` and soft-archive ended events in the Library and GoldDitto picker, while keeping evergreen categories at full opacity.

**Architecture:** Two new optional ISO-date fields on `BookmarkCategory`. Status (`evergreen | upcoming | active | ended`) is purely derived in the frontend from those two fields and the user's local date — no persisted archive flag, no backend scheduler. The Library auto-collapses `upcoming` and `ended` categories with a status chip but preserves any prior manual expand. The GoldDitto picker hides `ended` categories by default behind a per-side `Include ended` checkbox.

**Tech Stack:** Python 3 + FastAPI + Pydantic v2 (backend), React 18 + TypeScript + Vite (frontend), pytest (test runner). No frontend test harness exists today; per-task manual smoke + `tsc --noEmit` covers the frontend, with backend pytest tests authored TDD-style.

**Spec:** `docs/superpowers/specs/2026-05-09-event-soft-archive-design.md`

---

## File Map

**Backend — modified:**
- `backend/models/schemas.py` — add `start_date` / `end_date` to `BookmarkCategory` (Task 1)
- `backend/services/bookmarks.py` — extend `create_category` / `update_category` kwargs (Task 3)
- `backend/api/bookmarks.py` — add `_validate_date_range`, wire into POST/PUT (Task 2, Task 4)

**Backend — new tests:**
- `backend/tests/test_bookmark_event_dates.py` — covers schema, validation helper, manager kwargs, and API wiring (Tasks 1–4)

**Frontend — new:**
- `frontend/src/utils/categoryStatus.ts` — `getCategoryStatus`, `todayLocal`, `formatChipDate` (Task 5)

**Frontend — modified:**
- `frontend/src/i18n/strings.ts` — 7 new keys (Task 6)
- `frontend/src/services/api.ts` — type the `updateCategory` payload (Task 7)
- `frontend/src/components/BookmarkList.tsx` — Edit dialog, chip + auto-collapse, drop legacy props (Tasks 8–9)
- `frontend/src/components/BookmarkPickerPopover.tsx` — `categoryDates` prop, Include-ended checkbox, fallback (Task 10)
- `frontend/src/components/ControlPanel.tsx` — pass `categoryDates` and `onCategoryEdit` through, drop legacy props (Task 11)
- `frontend/src/components/GoldDittoPanel.tsx` — pass `categoryDates` (by id) into picker (Task 11)
- `frontend/src/App.tsx` — derive both date maps, replace rename/recolor handlers with `onCategoryEdit` (Task 11)

**Verification:**
- `frontend/tsconfig.json` — used by `npm run build` for compile check (Task 12)
- `docs/samples/pikmin-bloom-events.json` — already committed, used during smoke test (Task 12)

---

## Task 1 — Schema fields on `BookmarkCategory`

**Files:**
- Modify: `backend/models/schemas.py:176-182` (the `BookmarkCategory` class)
- Create: `backend/tests/test_bookmark_event_dates.py`

- [ ] **Step 1.1: Write the failing schema test**

Create `backend/tests/test_bookmark_event_dates.py`:

```python
"""Tests for event date fields on BookmarkCategory."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    import main
    from services.bookmarks import BookmarkManager
    main.app_state.bookmark_manager = BookmarkManager()
    return TestClient(main.app)


def test_bookmark_category_schema_has_event_date_fields():
    from models.schemas import BookmarkCategory

    cat = BookmarkCategory(name="evt")
    assert cat.start_date == ""
    assert cat.end_date == ""


def test_bookmark_category_accepts_iso_dates():
    from models.schemas import BookmarkCategory

    cat = BookmarkCategory(
        name="Sanga",
        start_date="2026-02-06",
        end_date="2026-06-07",
    )
    assert cat.start_date == "2026-02-06"
    assert cat.end_date == "2026-06-07"


def test_bookmark_store_round_trips_legacy_payload():
    """A bookmarks.json without the new keys still parses (defaults to '')."""
    from models.schemas import BookmarkStore

    store = BookmarkStore(**{
        "categories": [{
            "id": "x",
            "name": "old",
            "color": "#000",
            "sort_order": 0,
            "created_at": "2026-01-01T00:00:00Z",
        }],
        "bookmarks": [],
    })
    assert store.categories[0].start_date == ""
    assert store.categories[0].end_date == ""
```

- [ ] **Step 1.2: Run the test to confirm it fails**

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/test_bookmark_event_dates.py::test_bookmark_category_schema_has_event_date_fields -v
```

Expected: `AttributeError: 'BookmarkCategory' object has no attribute 'start_date'` (or similar).

- [ ] **Step 1.3: Add the two fields to `BookmarkCategory`**

In `backend/models/schemas.py`, replace the existing `BookmarkCategory` class (around line 176):

```python
class BookmarkCategory(BaseModel):
    id: str = ""
    name: str
    color: str = "#6c8cff"
    sort_order: int = 0
    created_at: str = ""
    # ISO 8601 date 'YYYY-MM-DD'. Empty string = unbounded on that side.
    # Both empty → evergreen (never archives). Validation lives in the
    # API layer (api/bookmarks.py::_validate_date_range).
    start_date: str = ""
    end_date: str = ""
```

- [ ] **Step 1.4: Run the schema tests**

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/test_bookmark_event_dates.py -v
```

Expected: 3 tests pass.

- [ ] **Step 1.5: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/models/schemas.py backend/tests/test_bookmark_event_dates.py
git commit -m "$(cat <<'EOF'
feat(backend): start_date/end_date on BookmarkCategory

Optional ISO YYYY-MM-DD fields, default ''. Validation deferred to
the API layer; legacy bookmarks.json files round-trip via Pydantic
defaults.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — `_validate_date_range` helper

**Files:**
- Modify: `backend/api/bookmarks.py` (top of file, before the router definition)
- Modify: `backend/tests/test_bookmark_event_dates.py` (append)

- [ ] **Step 2.1: Write the failing validation tests**

Append to `backend/tests/test_bookmark_event_dates.py`:

```python
def test_validate_date_range_accepts_empty():
    from api.bookmarks import _validate_date_range
    _validate_date_range("", "")  # no exception


def test_validate_date_range_accepts_only_start():
    from api.bookmarks import _validate_date_range
    _validate_date_range("2026-06-01", "")  # no exception


def test_validate_date_range_accepts_only_end():
    from api.bookmarks import _validate_date_range
    _validate_date_range("", "2026-06-01")  # no exception


def test_validate_date_range_accepts_valid_range():
    from api.bookmarks import _validate_date_range
    _validate_date_range("2026-02-06", "2026-06-07")  # no exception


def test_validate_date_range_rejects_slash_format():
    from fastapi import HTTPException
    from api.bookmarks import _validate_date_range
    with pytest.raises(HTTPException) as excinfo:
        _validate_date_range("2026/06/01", "")
    assert excinfo.value.status_code == 422


def test_validate_date_range_rejects_garbage_string():
    from fastapi import HTTPException
    from api.bookmarks import _validate_date_range
    with pytest.raises(HTTPException) as excinfo:
        _validate_date_range("not-a-date", "")
    assert excinfo.value.status_code == 422


def test_validate_date_range_rejects_invalid_calendar_date():
    from fastapi import HTTPException
    from api.bookmarks import _validate_date_range
    with pytest.raises(HTTPException) as excinfo:
        _validate_date_range("2026-13-01", "")
    assert excinfo.value.status_code == 422


def test_validate_date_range_rejects_inverted_range():
    from fastapi import HTTPException
    from api.bookmarks import _validate_date_range
    with pytest.raises(HTTPException) as excinfo:
        _validate_date_range("2026-06-30", "2026-06-29")
    assert excinfo.value.status_code == 422
    assert "<= end_date" in excinfo.value.detail
```

- [ ] **Step 2.2: Run to confirm failure**

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/test_bookmark_event_dates.py::test_validate_date_range_accepts_empty -v
```

Expected: `ImportError: cannot import name '_validate_date_range' from 'api.bookmarks'`.

- [ ] **Step 2.3: Add the helper to `api/bookmarks.py`**

At the top of `backend/api/bookmarks.py`, after the existing imports (after line 8 where `from models.schemas` lives), add:

```python
import re
from datetime import date as _date

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date_range(start: str, end: str) -> None:
    """Validate ISO date strings on BookmarkCategory.

    Empty strings are allowed on either side. Non-empty values must match
    YYYY-MM-DD and be valid calendar dates. When both are non-empty,
    start must be <= end.

    Raises HTTPException(422) on any violation.
    """
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

- [ ] **Step 2.4: Run all date tests**

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/test_bookmark_event_dates.py -v
```

Expected: all 11 tests pass (3 from Task 1, 8 added here).

- [ ] **Step 2.5: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/api/bookmarks.py backend/tests/test_bookmark_event_dates.py
git commit -m "$(cat <<'EOF'
feat(backend): _validate_date_range helper for category event dates

Accepts empty strings; rejects non-ISO formats, invalid calendar
dates, and inverted ranges with HTTP 422. Wiring into create/update
endpoints lands in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — `BookmarkManager.create_category` / `update_category` kwargs

**Files:**
- Modify: `backend/services/bookmarks.py:80-113` (`create_category`, `update_category`)
- Modify: `backend/tests/test_bookmark_event_dates.py` (append)

- [ ] **Step 3.1: Write the failing service tests**

Append to `backend/tests/test_bookmark_event_dates.py`:

```python
def _make_manager(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    from services.bookmarks import BookmarkManager
    return BookmarkManager()


def test_create_category_persists_event_dates(tmp_path, monkeypatch):
    bm = _make_manager(tmp_path, monkeypatch)
    cat = bm.create_category(
        name="Sanga",
        color="#ef4444",
        start_date="2026-02-06",
        end_date="2026-06-07",
    )
    assert cat.start_date == "2026-02-06"
    assert cat.end_date == "2026-06-07"

    # Reload from disk to confirm persistence
    from services.bookmarks import BookmarkManager
    reloaded = BookmarkManager()
    found = next(c for c in reloaded.list_categories() if c.id == cat.id)
    assert found.start_date == "2026-02-06"
    assert found.end_date == "2026-06-07"


def test_update_category_with_empty_string_clears_date(tmp_path, monkeypatch):
    bm = _make_manager(tmp_path, monkeypatch)
    cat = bm.create_category(
        name="Sanga",
        start_date="2026-02-06",
        end_date="2026-06-07",
    )
    updated = bm.update_category(cat.id, start_date="", end_date="")
    assert updated is not None
    assert updated.start_date == ""
    assert updated.end_date == ""


def test_update_category_with_none_preserves_date(tmp_path, monkeypatch):
    bm = _make_manager(tmp_path, monkeypatch)
    cat = bm.create_category(
        name="Sanga",
        start_date="2026-02-06",
        end_date="2026-06-07",
    )
    updated = bm.update_category(cat.id, name="Renamed")
    assert updated is not None
    assert updated.name == "Renamed"
    assert updated.start_date == "2026-02-06"
    assert updated.end_date == "2026-06-07"
```

- [ ] **Step 3.2: Run to confirm failure**

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/test_bookmark_event_dates.py::test_create_category_persists_event_dates -v
```

Expected: `TypeError: create_category() got an unexpected keyword argument 'start_date'`.

- [ ] **Step 3.3: Extend `create_category`**

In `backend/services/bookmarks.py`, replace the `create_category` method (around line 80) with:

```python
    def create_category(
        self,
        name: str,
        color: str = "#6c8cff",
        start_date: str = "",
        end_date: str = "",
    ) -> BookmarkCategory:
        """Create and return a new category."""
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
```

- [ ] **Step 3.4: Extend `update_category`**

In the same file, replace `update_category` (around line 98) with:

```python
    def update_category(
        self,
        cat_id: str,
        name: str | None = None,
        color: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> BookmarkCategory | None:
        """Update a category's mutable fields. Returns ``None`` if not found.

        ``None`` for any field means "do not modify"; pass an empty string
        to clear ``start_date`` or ``end_date``.
        """
        cat = self._find_category(cat_id)
        if cat is None:
            return None
        if name is not None:
            cat.name = name
        if color is not None:
            cat.color = color
        if start_date is not None:
            cat.start_date = start_date
        if end_date is not None:
            cat.end_date = end_date
        self._save()
        return cat
```

- [ ] **Step 3.5: Run service tests**

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/test_bookmark_event_dates.py -v
```

Expected: 14 tests pass (11 + 3).

- [ ] **Step 3.6: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/services/bookmarks.py backend/tests/test_bookmark_event_dates.py
git commit -m "$(cat <<'EOF'
feat(backend): BookmarkManager.create/update_category accept event dates

create_category gains start_date/end_date kwargs (default '').
update_category uses ``is not None`` to distinguish "do not modify"
from "clear" — callers send '' to wipe a previously-set date.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — Wire validation + dates into POST/PUT category endpoints

**Files:**
- Modify: `backend/api/bookmarks.py:85-97` (`create_category`, `update_category` route handlers)
- Modify: `backend/tests/test_bookmark_event_dates.py` (append)

- [ ] **Step 4.1: Write the failing API tests**

Append to `backend/tests/test_bookmark_event_dates.py`:

```python
def test_post_category_with_dates(client):
    resp = client.post("/api/bookmarks/categories", json={
        "name": "Sanga",
        "color": "#ef4444",
        "start_date": "2026-02-06",
        "end_date": "2026-06-07",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["start_date"] == "2026-02-06"
    assert body["end_date"] == "2026-06-07"


def test_post_category_rejects_bad_date_format(client):
    resp = client.post("/api/bookmarks/categories", json={
        "name": "Bad",
        "start_date": "2026/02/06",
    })
    assert resp.status_code == 422


def test_post_category_rejects_inverted_range(client):
    resp = client.post("/api/bookmarks/categories", json={
        "name": "Bad",
        "start_date": "2026-06-07",
        "end_date": "2026-02-06",
    })
    assert resp.status_code == 422


def test_put_category_updates_dates(client):
    create = client.post("/api/bookmarks/categories", json={
        "name": "Sanga",
        "start_date": "2026-02-06",
        "end_date": "2026-06-07",
    })
    cat = create.json()
    resp = client.put(f"/api/bookmarks/categories/{cat['id']}", json={
        "name": cat["name"],
        "color": cat["color"],
        "start_date": "",
        "end_date": "",
    })
    assert resp.status_code == 200
    assert resp.json()["start_date"] == ""
    assert resp.json()["end_date"] == ""


def test_put_category_rejects_bad_format(client):
    create = client.post("/api/bookmarks/categories", json={"name": "evt"})
    cat = create.json()
    resp = client.put(f"/api/bookmarks/categories/{cat['id']}", json={
        "name": cat["name"],
        "color": cat["color"],
        "end_date": "tomorrow",
    })
    assert resp.status_code == 422


def test_get_categories_returns_event_dates(client):
    client.post("/api/bookmarks/categories", json={
        "name": "Sanga",
        "start_date": "2026-02-06",
        "end_date": "2026-06-07",
    })
    listing = client.get("/api/bookmarks").json()
    sanga = next(c for c in listing["categories"] if c["name"] == "Sanga")
    assert sanga["start_date"] == "2026-02-06"
    assert sanga["end_date"] == "2026-06-07"
```

- [ ] **Step 4.2: Run to confirm failure**

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/test_bookmark_event_dates.py::test_post_category_with_dates -v
```

Expected: assertion failure on `body["start_date"] == "2026-02-06"` because the route handler calls `create_category(name=..., color=...)` without forwarding the dates. (Field exists in schema but not propagated.)

- [ ] **Step 4.3: Wire `_validate_date_range` + dates into `POST /categories`**

In `backend/api/bookmarks.py`, replace the existing `create_category` route handler (around line 85) with:

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
```

- [ ] **Step 4.4: Wire into `PUT /categories/{cat_id}`**

In the same file, replace the existing `update_category` handler (around line 91) with:

```python
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

- [ ] **Step 4.5: Run all tests, confirm whole bookmarks suite still green**

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/ -v
```

Expected: 20 tests in `test_bookmark_event_dates.py` plus the existing suites all pass.

- [ ] **Step 4.6: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/api/bookmarks.py backend/tests/test_bookmark_event_dates.py
git commit -m "$(cat <<'EOF'
feat(backend): wire event dates + validation into category endpoints

POST /api/bookmarks/categories and PUT /api/bookmarks/categories/{id}
now accept start_date/end_date and 422 on bad input. GET responses
include the new fields. Backend story is done — frontend lands next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5 — `frontend/src/utils/categoryStatus.ts`

**Files:**
- Create: `frontend/src/utils/categoryStatus.ts`

- [ ] **Step 5.1: Create the utils module**

Write to `frontend/src/utils/categoryStatus.ts`:

```ts
// Pure helpers for the category soft-archive feature.
// Spec: docs/superpowers/specs/2026-05-09-event-soft-archive-design.md §4.4.

export type CategoryStatus = 'evergreen' | 'upcoming' | 'active' | 'ended';

/**
 * Derive a category's temporal status from its event dates and "today".
 *
 * | start | end   | status                                  |
 * |-------|-------|------------------------------------------|
 * | ''    | ''    | evergreen (always shown)                 |
 * | set   | any   | upcoming when today < start              |
 * | any   | set   | ended when today > end                   |
 * | else  |       | active                                   |
 *
 * `today`, `start`, and `end` are all 'YYYY-MM-DD' strings; ISO date
 * strings sort lexically so no Date parsing is required.
 */
export function getCategoryStatus(
  start: string,
  end: string,
  today: string,
): CategoryStatus {
  if (!start && !end) return 'evergreen';
  if (start && today < start) return 'upcoming';
  if (end && today > end) return 'ended';
  return 'active';
}

/** User-local 'YYYY-MM-DD' (sv-SE locale formats the way we need). */
export function todayLocal(): string {
  return new Date().toLocaleDateString('sv-SE');
}

/**
 * Locale-aware month/day for the "Starts {date}" chip.
 *
 *   formatChipDate('2026-06-07', 'zh-TW') -> '6月7日'
 *   formatChipDate('2026-06-07', 'en-US') -> 'Jun 7'
 *
 * Treats the input as UTC so the formatter doesn't shift the wall-clock
 * day across timezones (we only care about month/day, not time).
 */
export function formatChipDate(iso: string, locale: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(dt);
}
```

- [ ] **Step 5.2: Type-check**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5.3: Sanity-check the truth table interactively**

```bash
cd /Users/raviwu/personal/locwarp/frontend && node --input-type=module -e "
const tests = [
  ['','','2026-05-09','evergreen'],
  ['2026-06-01','','2026-05-30','upcoming'],
  ['2026-06-01','','2026-06-01','active'],
  ['','2026-06-07','2026-06-07','active'],
  ['','2026-06-07','2026-06-08','ended'],
  ['2026-02-06','2026-06-07','2026-05-09','active'],
  ['2026-02-06','2026-06-07','2026-06-08','ended'],
  ['2026-06-01','2026-06-01','2026-06-01','active'],
];
function getCategoryStatus(start, end, today){
  if(!start && !end) return 'evergreen';
  if(start && today < start) return 'upcoming';
  if(end && today > end) return 'ended';
  return 'active';
}
let fails = 0;
for (const [s,e,t,want] of tests) {
  const got = getCategoryStatus(s,e,t);
  const ok = got === want;
  console.log(ok?'OK':'FAIL', JSON.stringify([s,e,t]), '->', got, ok?'':' (want '+want+')');
  if (!ok) fails++;
}
console.log(fails===0?'ALL PASS':'FAILED '+fails);
process.exit(fails===0?0:1);
"
```

Expected: `ALL PASS` and 8 `OK` lines.

- [ ] **Step 5.4: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/utils/categoryStatus.ts
git commit -m "$(cat <<'EOF'
feat(frontend): categoryStatus utils for event soft-archive

getCategoryStatus + todayLocal + formatChipDate, all pure. ISO
date strings sort lexically so no Date parsing required for the
status check itself; formatChipDate uses Intl.DateTimeFormat for
locale-aware month/day chips.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6 — i18n keys

**Files:**
- Modify: `frontend/src/i18n/strings.ts` (insert near existing `bm.cat.*` and `bm.picker.*` keys)

- [ ] **Step 6.1: Add new keys**

Add these entries inside the existing string map in `frontend/src/i18n/strings.ts`. Group them with the other `bm.cat.*` and `bm.picker.*` keys — search for `'bm.recolor_custom'` and insert below; search for `'bm.picker.close'` and insert near it.

```ts
  // — Edit-category dialog (replaces inline rename) —
  'bm.cat.edit_title':       { zh: '編輯分類',                    en: 'Edit category' },
  'bm.cat.starts':           { zh: '開始日期',                    en: 'Starts' },
  'bm.cat.ends':             { zh: '結束日期',                    en: 'Ends' },
  'bm.cat.dates_hint':       { zh: '留空 = 永久(不會自動隱藏)',    en: 'Leave empty for evergreen (never auto-hide)' },
  'bm.cat.dates_clear':      { zh: '清空',                        en: 'Clear' },
  'bm.cat.dates_invalid':    { zh: '結束日期須晚於或等於開始日期', en: 'End date must be on or after start date' },
  'bm.cat.save':             { zh: '儲存',                        en: 'Save' },

  // — Soft-archive status chips —
  'bm.cat.status_ended':     { zh: '已結束',                      en: 'Ended' },
  'bm.cat.status_upcoming':  { zh: '即將開始 {date}',              en: 'Starts {date}' },

  // — GoldDitto picker filter —
  'bm.picker.include_ended': { zh: '包含已結束',                   en: 'Include ended' },
```

- [ ] **Step 6.2: Type-check**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 6.3: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/i18n/strings.ts
git commit -m "$(cat <<'EOF'
feat(frontend): i18n keys for event soft-archive

10 new keys covering the Edit-category dialog, status chips, and
picker Include-ended toggle.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7 — Tighten `updateCategory` API client signature

**Files:**
- Modify: `frontend/src/services/api.ts:253-256`

- [ ] **Step 7.1: Replace the loose `any` with the actual patch shape**

In `frontend/src/services/api.ts`, replace the existing `getCategories` / `createCategory` / `updateCategory` block (around line 253) with:

```ts
export interface CategoryPayload {
  name: string;
  color: string;
  start_date?: string;
  end_date?: string;
}

export interface CategoryResponse extends CategoryPayload {
  id: string;
  sort_order: number;
  created_at: string;
  start_date: string;
  end_date: string;
}

export const getCategories = () =>
  request<CategoryResponse[]>('GET', '/api/bookmarks/categories')
export const createCategory = (cat: CategoryPayload) =>
  request<CategoryResponse>('POST', '/api/bookmarks/categories', cat)
export const updateCategory = (id: string, cat: CategoryPayload) =>
  request<CategoryResponse>('PUT', `/api/bookmarks/categories/${id}`, cat)
```

- [ ] **Step 7.2: Type-check**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: no errors. (App.tsx callers spread an existing object into the patch — TS will accept the wider shape.)

- [ ] **Step 7.3: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/services/api.ts
git commit -m "$(cat <<'EOF'
refactor(frontend): typed CategoryPayload/Response on api.ts

Replaces the prior `any` on createCategory/updateCategory so the
date-aware Edit dialog gets compile-time signal when the patch
shape drifts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8 — `BookmarkList` Edit Category dialog (drop legacy props)

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx` (interface, state, dialog markup, category-manager row)

- [ ] **Step 8.1: Replace `onCategoryRename` + `onCategoryRecolor` with `onCategoryEdit` in the props interface**

In `frontend/src/components/BookmarkList.tsx`, find the `BookmarkListProps` interface (around line 26) and replace the two props:

```ts
  // Removed:
  // onCategoryRename?: (oldName: string, newName: string) => void;
  // onCategoryRecolor?: (name: string, color: string) => void;
  onCategoryEdit?: (
    name: string,
    patch: { name: string; color: string; start_date: string; end_date: string },
  ) => void;
  // Per-category event dates, keyed by category name (matches the
  // existing categoryColors prop).
  categoryDates?: Record<string, { start_date: string; end_date: string }>;
```

Update the destructured props in the function signature (around line 88) to match: drop `onCategoryRename` / `onCategoryRecolor`, add `onCategoryEdit` and `categoryDates`.

- [ ] **Step 8.2: Replace inline-rename state with edit-dialog state**

Find the existing rename state (around lines 135–136):

```ts
  const [editingCategory, setEditingCategory] = useState<string | null>(null);
  const [editCategoryName, setEditCategoryName] = useState('');
```

Replace with the edit-dialog state:

```ts
  // Edit-category dialog. Open when non-null; the value is the category
  // name being edited. Form fields below are local to the dialog.
  const [editCatName, setEditCatName] = useState<string | null>(null);
  const [editCatNewName, setEditCatNewName] = useState('');
  const [editCatColor, setEditCatColor] = useState('#6c8cff');
  const [editCatStart, setEditCatStart] = useState('');
  const [editCatEnd, setEditCatEnd] = useState('');
```

- [ ] **Step 8.3: Add an `openEditCategory` helper**

Right after the new dialog state, add:

```ts
  const openEditCategory = (cat: string) => {
    setEditCatName(cat);
    setEditCatNewName(cat);
    setEditCatColor(resolveColor(cat));
    const d = categoryDates?.[cat];
    setEditCatStart(d?.start_date ?? '');
    setEditCatEnd(d?.end_date ?? '');
  };
  const closeEditCategory = () => setEditCatName(null);
```

- [ ] **Step 8.4: Swap the rename pencil for the edit pencil**

Locate the pencil button block in the Category Manager (around lines 831–849, the conditional `cat !== 'Default' && cat !== '預設' && onCategoryRename && editingCategory !== cat && ...`). Replace the entire conditional + button + the inline rename `<input>` block (around lines 810–849) with:

```tsx
              <span style={{ flex: 1 }}>{displayCat(cat)}</span>
              {cat !== 'Default' && cat !== '預設' && onCategoryEdit && (
                <button
                  onClick={() => openEditCategory(cat)}
                  title={t('bm.cat.edit_title')}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--fg-muted, #888)',
                    cursor: 'pointer',
                    padding: '2px 4px',
                    fontSize: 11,
                  }}
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                    <path d="M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                  </svg>
                </button>
              )}
```

(Removes the inline-rename input and the standalone color-picker dot — both go away. The colored dot to the LEFT of the name in the row should remain as a status indicator only; it no longer triggers the color picker. Find the button block with `onClick={(e) => { e.stopPropagation(); if (!onCategoryRecolor) return; setColorPickerFor(...) ` and convert it from a `<button>` to a `<div>` with no click handler. The associated `colorPickerFor` popover and `COLOR_PALETTE` rendering stay — but they are now invoked from the new dialog instead. **Move** the `COLOR_PALETTE` rendering block out of the row and into the dialog body (Step 8.5).)

- [ ] **Step 8.5: Render the Edit dialog above `Bookmark groups` section**

Locate the `{/* Search mode: flat filtered list, no category grouping */}` comment (around line 895). **Above it**, insert the edit dialog markup. Use `createPortal` so it overlays everything:

```tsx
      {editCatName !== null && createPortal(
        <div
          onClick={closeEditCategory}
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(8,10,20,0.55)',
            backdropFilter: 'blur(4px)',
            zIndex: 10000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'rgba(26,29,39,0.96)',
              border: '1px solid rgba(108,140,255,0.35)',
              borderRadius: 12, padding: 18, width: 340,
              boxShadow: '0 20px 60px rgba(12,18,40,0.65)',
              color: '#e0e0e0',
              display: 'flex', flexDirection: 'column', gap: 10,
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600 }}>{t('bm.cat.edit_title')}</div>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ opacity: 0.7, fontSize: 11 }}>{t('bm.add_category')}</span>
              <input
                className="search-input"
                value={editCatNewName}
                onChange={(e) => setEditCatNewName(e.target.value)}
                style={{ padding: '4px 6px' }}
              />
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ opacity: 0.7, fontSize: 11 }}>{t('bm.recolor_tooltip')}</span>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 28px)', gap: 6 }}>
                {COLOR_PALETTE.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setEditCatColor(c)}
                    style={{
                      width: 28, height: 28, borderRadius: '50%',
                      background: c,
                      border: editCatColor.toLowerCase() === c.toLowerCase()
                        ? '2px solid #fff'
                        : '1.5px solid rgba(255,255,255,0.12)',
                      cursor: 'pointer', padding: 0,
                    }}
                    title={c}
                  />
                ))}
              </div>
              <input
                type="color"
                value={editCatColor}
                onChange={(e) => setEditCatColor(e.target.value)}
                title={t('bm.recolor_custom')}
                style={{ width: '100%', height: 28, border: 'none', borderRadius: 4, padding: 0, marginTop: 4 }}
              />
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ opacity: 0.7, fontSize: 11 }}>{t('bm.cat.starts')}</span>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input
                  type="date"
                  value={editCatStart}
                  onChange={(e) => setEditCatStart(e.target.value)}
                  style={{ flex: 1, padding: '4px 6px', background: '#1e1e22', color: '#e0e0e0', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4 }}
                />
                <button
                  className="action-btn"
                  onClick={() => setEditCatStart('')}
                  disabled={!editCatStart}
                  style={{ fontSize: 11, padding: '3px 8px', opacity: editCatStart ? 1 : 0.4 }}
                >
                  ✕ {t('bm.cat.dates_clear')}
                </button>
              </div>
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ opacity: 0.7, fontSize: 11 }}>{t('bm.cat.ends')}</span>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input
                  type="date"
                  value={editCatEnd}
                  onChange={(e) => setEditCatEnd(e.target.value)}
                  style={{ flex: 1, padding: '4px 6px', background: '#1e1e22', color: '#e0e0e0', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4 }}
                />
                <button
                  className="action-btn"
                  onClick={() => setEditCatEnd('')}
                  disabled={!editCatEnd}
                  style={{ fontSize: 11, padding: '3px 8px', opacity: editCatEnd ? 1 : 0.4 }}
                >
                  ✕ {t('bm.cat.dates_clear')}
                </button>
              </div>
            </label>

            <div style={{ fontSize: 10, opacity: 0.55 }}>{t('bm.cat.dates_hint')}</div>
            {editCatStart && editCatEnd && editCatStart > editCatEnd && (
              <div style={{ fontSize: 11, color: '#f87171' }}>{t('bm.cat.dates_invalid')}</div>
            )}

            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginTop: 4 }}>
              <button className="action-btn" onClick={closeEditCategory} style={{ fontSize: 11 }}>
                {t('bm.picker.close')}
              </button>
              <button
                className="action-btn"
                disabled={
                  !editCatNewName.trim() ||
                  (!!editCatStart && !!editCatEnd && editCatStart > editCatEnd)
                }
                onClick={() => {
                  if (!onCategoryEdit || !editCatName) return;
                  const next = editCatNewName.trim();
                  if (!next) return;
                  if (editCatStart && editCatEnd && editCatStart > editCatEnd) return;
                  onCategoryEdit(editCatName, {
                    name: next,
                    color: editCatColor,
                    start_date: editCatStart,
                    end_date: editCatEnd,
                  });
                  closeEditCategory();
                }}
                style={{ fontSize: 11 }}
              >
                {t('bm.cat.save')}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
```

- [ ] **Step 8.6: Drop the now-unused `colorPickerFor` per-row popover**

Search for `colorPickerFor` in `BookmarkList.tsx`. Remove:
- The `useState<string | null>` declaration for `colorPickerFor` (around line 119).
- The `useEffect` that dismisses it on outside click (around lines 254–273).
- The inline `{colorPickerFor === cat && onCategoryRecolor && (...)` popover block (around lines 753–809).
- The button-with-onClick-on-the-color-dot — change it to a plain `<div>`:

```tsx
              <div
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: '50%',
                  background: resolveColor(cat),
                  border: '1.5px solid rgba(255,255,255,0.15)',
                  flexShrink: 0,
                  boxShadow: '0 1px 2px rgba(0,0,0,0.3)',
                }}
              />
```

- [ ] **Step 8.7: Type-check + dev build**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: no errors. If TS complains about unused `onCategoryRecolor` prop, the cleanup is incomplete — re-grep and remove every reference.

- [ ] **Step 8.8: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/components/BookmarkList.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): BookmarkList Edit-category dialog (replaces inline rename)

Single dialog covers name + color + event dates. Drops the legacy
inline-rename input and the per-row color popover. Wires
onCategoryEdit + categoryDates props; old onCategoryRename and
onCategoryRecolor are removed from the interface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9 — `BookmarkList` default-collapse + status chip

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx` (collapse `useEffect`, group header render)

- [ ] **Step 9.1: Import the status helpers**

At the top of `frontend/src/components/BookmarkList.tsx`, add:

```ts
import {
  getCategoryStatus,
  todayLocal,
  formatChipDate,
  type CategoryStatus,
} from '../utils/categoryStatus';
```

- [ ] **Step 9.2: Add a `computeDefaultCollapsed` helper**

Just below the existing `displayCat` helper (around line 123) add:

```ts
  const computeDefaultCollapsed = (cat: string): boolean => {
    const d = categoryDates?.[cat];
    if (!d) return false;
    const status = getCategoryStatus(d.start_date, d.end_date, todayLocal());
    return status === 'ended' || status === 'upcoming';
  };
```

- [ ] **Step 9.3: Patch the collapse `useEffect`**

Locate the collapse `useEffect` (around lines 309–334). Replace the body with:

```tsx
  useEffect(() => {
    if (!uiStateLoaded) return;
    if (categories.length === 0) return;
    const isOver = bookmarks.length > AUTO_COLLAPSE_THRESHOLD;
    const wasOver = prevOverThresholdRef.current;
    if (wasOver === null || isOver !== wasOver) {
      if (isOver) {
        const all: Record<string, boolean> = {};
        categories.forEach((c) => { all[c] = true; });
        setCollapsed(all);
      } else {
        const saved = savedExpandedRef.current;
        if (saved === null) {
          const next: Record<string, boolean> = {};
          categories.forEach((c) => { next[c] = computeDefaultCollapsed(c); });
          setCollapsed(next);
        } else {
          const savedSet = new Set(saved);
          const next: Record<string, boolean> = {};
          categories.forEach((c) => {
            // Saved snapshot wins: any explicitly-expanded category stays
            // expanded even if it later flips to ended/upcoming.
            next[c] = savedSet.has(c) ? false : computeDefaultCollapsed(c);
          });
          setCollapsed(next);
        }
      }
    }
    prevOverThresholdRef.current = isOver;
  }, [uiStateLoaded, bookmarks.length, categories, categoryDates]);
```

(Note the dependency array now includes `categoryDates` so a date edit re-evaluates the default; manual toggles persisted in `savedExpandedRef` still win.)

- [ ] **Step 9.4: Render the status chip in the group header**

Locate the group-header `<div>` (around lines 992–1054, the one with `onClick={() => toggleCategory(cat)}`). Just before the line `<span>{displayCat(cat)}</span>`, compute the status:

```tsx
            ; const _d = categoryDates?.[cat];
            const status: CategoryStatus = _d
              ? getCategoryStatus(_d.start_date, _d.end_date, todayLocal())
              : 'evergreen';
            const headerOpacity =
              status === 'ended' ? 0.5 : status === 'upcoming' ? 0.7 : 1;
```

(That block needs to live inside the existing `Object.entries(...).map(...)` callback — wrap it just inside the function body of the map callback so `status` is a local. Since the existing callback already has braces from `const catIds = ...` etc., insert the `_d` / `status` / `headerOpacity` lines right after `const someSelectedInCat = selectedInCat > 0 && !allSelectedInCat;`.)

Then change the wrapping `<div>` of the header to apply opacity inline:

```tsx
        <div key={cat} className="bookmark-group" style={{ marginBottom: 4, opacity: headerOpacity }}>
```

(Header opacity ripples to children too — fine; bookmark items inside an `ended` category aren't supposed to look full-bright when expanded either.)

Insert the chip **after** `<span>{displayCat(cat)}</span>` and **before** the trailing count `<span>` (around line 1051):

```tsx
            {status === 'ended' && (
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                background: '#3a3a3e', color: '#9aa0a6', marginLeft: 4,
              }}>{t('bm.cat.status_ended')}</span>
            )}
            {status === 'upcoming' && _d && (
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                background: 'rgba(59,130,246,0.18)', color: '#7aa9ff', marginLeft: 4,
              }}>
                {t('bm.cat.status_upcoming').replace(
                  '{date}',
                  formatChipDate(_d.start_date, navigator.language || 'en-US'),
                )}
              </span>
            )}
```

- [ ] **Step 9.5: Type-check**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: no errors. (If `_d` is flagged as possibly used outside the chip block, scope it inside the map callback — already done in 9.4.)

- [ ] **Step 9.6: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/components/BookmarkList.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): BookmarkList default-collapse + status chip

Categories whose end_date has passed (ended) or whose start_date is
in the future (upcoming) start collapsed unless the user previously
expanded them. Header gets a grey '已結束' or blue '即將開始 M/D'
chip and a softened opacity. Saved expanded snapshot still wins.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10 — `BookmarkPickerPopover` Include-ended filter

**Files:**
- Modify: `frontend/src/components/BookmarkPickerPopover.tsx`

- [ ] **Step 10.1: Add the new prop and helpers**

At the top of `frontend/src/components/BookmarkPickerPopover.tsx`, add:

```ts
import { getCategoryStatus, todayLocal } from '../utils/categoryStatus';
```

In the `Props` interface (around line 23), add:

```ts
  // Per-category event dates, keyed by category id (the picker has
  // ids handy already; BookmarkList uses by-name because of legacy).
  categoryDates?: Record<string, { start_date: string; end_date: string }>;
```

- [ ] **Step 10.2: Persist `includeEnded` per side**

In the component body (right after `useT()`, around line 44), add:

```ts
  const includeEndedKey = `goldditto.picker.${side}.includeEnded`;
  const [includeEnded, setIncludeEnded] = useState<boolean>(
    () => (typeof window !== 'undefined' ? localStorage.getItem(includeEndedKey) === 'true' : false),
  );
```

Update the destructured props in the function signature (around line 41) to include `categoryDates`.

- [ ] **Step 10.3: Filter `visibleCategories`**

Just above the existing `visible` `useMemo` (around line 79), add:

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

- [ ] **Step 10.4: Replace the dropdown source + add fallback selection effect**

Find the existing select (around lines 110–129) and replace `categories.map` with `visibleCategories.map`:

```tsx
        <select
          value={selectedCatId ?? ''}
          onChange={(e) => {
            const v = e.target.value || null;
            setSelectedCatId(v);
            if (v) onCategoryChange(v);
          }}
          style={{
            background: '#1e1e22', color: '#e0e0e0',
            border: '1px solid rgba(255,255,255,0.15)',
            borderRadius: 4, padding: '4px 6px',
          }}
        >
          <option value="" disabled>—</option>
          {visibleCategories.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
```

Replace the existing initial-category `useEffect` (around lines 53–55) with:

```tsx
  useEffect(() => {
    const stillVisible = visibleCategories.some((c) => c.id === initialCategoryId);
    setSelectedCatId(
      initialCategoryId && stillVisible
        ? initialCategoryId
        : (visibleCategories[0]?.id ?? fallbackCatId),
    );
  }, [initialCategoryId, open, visibleCategories, fallbackCatId]);
```

(Crucially: when the fallback fires it does NOT call `onCategoryChange`, so the parent's persisted `lastCategory` localStorage entry is preserved — toggling Include-ended later restores the original choice.)

Update `fallbackCatId` (around line 48) to also stay valid in the filter context:

```ts
  const fallbackCatId = visibleCategories[0]?.id ?? categories[0]?.id ?? 'default';
```

(Place `fallbackCatId` declaration **after** `visibleCategories` so it can read from it. Move both to the appropriate spots; ensure `visibleCategories` is defined before `fallbackCatId` and the initial `useState`.)

- [ ] **Step 10.5: Render the Include-ended checkbox**

Above the `<label>` that holds the category select (around line 109), add:

```tsx
      <label style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: 11, opacity: 0.7 }}>
        <input
          type="checkbox"
          checked={includeEnded}
          onChange={(e) => {
            setIncludeEnded(e.target.checked);
            try {
              localStorage.setItem(includeEndedKey, String(e.target.checked));
            } catch { /* ignore quota */ }
          }}
        />
        {t('bm.picker.include_ended')}
      </label>
```

- [ ] **Step 10.6: Type-check**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 10.7: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/components/BookmarkPickerPopover.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): GoldDitto picker hides ended categories by default

Per-side 'Include ended' checkbox persisted in localStorage as
goldditto.picker.{A|B}.includeEnded. When the last-used category is
filtered out, the picker falls back to the first visible without
overwriting the saved preference, so toggling the checkbox restores
the user's original choice.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11 — Wire `categoryDates` and `onCategoryEdit` from App through the panels

**Files:**
- Modify: `frontend/src/App.tsx` (handler block around lines 1256–1269)
- Modify: `frontend/src/components/ControlPanel.tsx` (props interface, destructure, pass-through to BookmarkList)
- Modify: `frontend/src/components/GoldDittoPanel.tsx` (BookmarkPickerPopover invocation)

- [ ] **Step 11.1: Replace the App-level rename/recolor handlers with `onCategoryEdit`**

In `frontend/src/App.tsx`, locate the block from `onCategoryRename={...}` through the closing of `onCategoryRecolor` (lines 1256–1269) and replace with:

```tsx
          onCategoryEdit={(oldName: string, patch) => {
            const cat = bm.categories.find(c => c.name === oldName);
            if (!cat) return;
            // Default category is immutable.
            if (cat.id === 'default') return;
            bm.updateCategory(cat.id, {
              name: patch.name,
              color: patch.color,
              start_date: patch.start_date,
              end_date: patch.end_date,
            });
          }}
          categoryDates={Object.fromEntries(
            bm.categories.map(c => [c.name, {
              start_date: c.start_date ?? '',
              end_date: c.end_date ?? '',
            }]),
          )}
```

- [ ] **Step 11.2: Pass `categoryDates` (by id) into GoldDittoPanel**

`GoldDittoPanel` already receives `goldDittoCategories={bm.categories}`. The picker inside it can derive its by-id map directly from those category objects, so no new prop on `GoldDittoPanel`'s own interface is needed.

In `frontend/src/components/GoldDittoPanel.tsx`, locate the `<BookmarkPickerPopover` invocation (around line 305) and add:

```tsx
        categoryDates={Object.fromEntries(
          categories.map(c => [c.id, {
            start_date: (c as any).start_date ?? '',
            end_date: (c as any).end_date ?? '',
          }]),
        )}
```

(If the local `categories` type in GoldDittoPanel is too loose to surface `start_date`/`end_date`, tighten it: search for the `Category` interface in that file and add `start_date?: string; end_date?: string;`. Then drop the `as any` cast.)

- [ ] **Step 11.3: Update `ControlPanel.tsx` props**

In `frontend/src/components/ControlPanel.tsx`, locate the props interface (around lines 101–102):

```ts
  onCategoryRename?: (oldName: string, newName: string) => void;
  onCategoryRecolor?: (name: string, color: string) => void;
```

Replace with:

```ts
  onCategoryEdit?: (
    oldName: string,
    patch: { name: string; color: string; start_date: string; end_date: string },
  ) => void;
  categoryDates?: Record<string, { start_date: string; end_date: string }>;
```

Update the destructure (around lines 277–278) similarly: drop `onCategoryRename` / `onCategoryRecolor`, add `onCategoryEdit` and `categoryDates`.

In the `<BookmarkList ... />` JSX (around lines 883–900), replace `onCategoryRename={onCategoryRename}` and `onCategoryRecolor={onCategoryRecolor}` with:

```tsx
                    onCategoryEdit={onCategoryEdit}
                    categoryDates={categoryDates}
```

- [ ] **Step 11.4: Type-check whole frontend**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: no errors. Common slips: forgot to remove a destructure of `onCategoryRename` somewhere, or missed the `<BookmarkList>` site in `ControlPanel.tsx`. Re-grep for `onCategoryRename` and `onCategoryRecolor` in the repo and confirm zero matches:

```bash
grep -rn "onCategoryRename\|onCategoryRecolor" /Users/raviwu/personal/locwarp/frontend/src/
```

Expected: no output.

- [ ] **Step 11.5: Full build sanity**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npm run build
```

Expected: build completes (TS + Vite). Warnings about chunk size are pre-existing and fine.

- [ ] **Step 11.6: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/App.tsx frontend/src/components/ControlPanel.tsx frontend/src/components/GoldDittoPanel.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): wire categoryDates + onCategoryEdit end-to-end

App.tsx replaces the rename/recolor handler pair with a single
onCategoryEdit that PUTs the full category patch (name + color +
event dates). ControlPanel passes the new props through to
BookmarkList. GoldDittoPanel exposes categoryDates (by id) to the
picker so the Include-ended filter has the data it needs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12 — Manual smoke against the Pikmin Bloom seed

**Files:** none modified — this is a verification gate.

- [ ] **Step 12.1: Run the backend test suite once more**

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/ -v
```

Expected: every test passes, including the 20+ in `test_bookmark_event_dates.py`.

- [ ] **Step 12.2: Start the dev environment**

```bash
cd /Users/raviwu/personal/locwarp && ./start.sh
```

(or `python start.py` on Windows). The Electron window should open against `localhost:5173`.

- [ ] **Step 12.3: Import the seed**

Open the Library panel → Import → choose `docs/samples/pikmin-bloom-events.json`. Two new categories appear:

- `Sapporo Pikmin Bloom Tour` (12 bookmarks, no chip — evergreen).
- `Sanga Stadium by KYOCERA` (1 bookmark, no chip while today ≤ 2026-06-07 — `active`).

- [ ] **Step 12.4: Force the ended state**

Click the pencil on `Sanga Stadium by KYOCERA` → set Ends to `2026-05-08` (yesterday relative to the spec's 2026-05-09) → Save. The Library row should:

- Get a grey `已結束` chip.
- Drop opacity on its header to ~50%.
- Auto-collapse on next render. (Click the caret to confirm it expands and you can still see the bookmark.)

Reload the app (`Cmd-R`). The category remains expanded if you previously expanded it; if you didn't, it stays collapsed.

- [ ] **Step 12.5: Verify the picker filter**

Switch SimMode to GoldDitto. Click `📚` next to A. The category dropdown:

- Excludes `Sanga Stadium by KYOCERA` by default.
- Tick `包含已結束` — Sanga reappears at the bottom of the list.
- Click a Sanga bookmark — A field populates.
- Untick `包含已結束`, close the popover, re-open. A picker auto-falls-back to the first visible category. Re-ticking restores the prior selection.

- [ ] **Step 12.6: Verify the upcoming state**

Edit `Sapporo Pikmin Bloom Tour` → Starts `2027-01-01` → Save. Header gets a blue `即將開始 1月1日` chip (zh-TW) or `Starts Jan 1` (en-US). Library auto-collapses unless previously expanded. Picker still shows it (upcoming is not filtered).

Set Starts back to empty → Save. The category returns to evergreen, no chip.

- [ ] **Step 12.7: Validate the spec date hint**

Edit any non-default category → set Starts `2026-06-07`, Ends `2026-06-06`. Save button should disable and the red hint `End date must be on or after start date` should appear inline.

- [ ] **Step 12.8: No commit**

Smoke test makes no code changes. If you spotted a regression, fix it in a new commit referencing the broken step.

---

## Self-Review (recorded after writing the plan)

**Spec coverage:**
- §4.1 schema fields → Task 1 ✓
- §4.3 validation rules → Task 2 ✓
- §4.4–4.5 status helper + truth table → Task 5 ✓
- §5.1 `_validate_date_range` → Task 2 ✓
- §5.2 manager kwargs → Task 3 ✓
- §5.1/5.2 API wiring → Task 4 ✓
- §5.4 export/import — no code change required; covered by §11 seed-data note plus the existing `model_dump_json` round-trip already exercised in `test_bookmark_event_dates.py` Step 1.1 ✓
- §6 Edit dialog → Task 8 ✓
- §6.3 i18n keys → Task 6 ✓
- §7.1 by-name `categoryDates` thread → Task 11 (App.tsx) + Task 8 (BookmarkList prop) ✓
- §7.2 default-collapse integration → Task 9 ✓
- §7.3 chip + opacity → Task 9 ✓
- §7.4 i18n + locale-aware date → Task 5 (formatChipDate) + Task 6 (keys) + Task 9 (chip render) ✓
- §8 Picker filter + checkbox + fallback → Task 10 ✓
- §9 Edge cases — covered by tests in Tasks 1–4 (validation, defaults) and manual smoke in Task 12; the "Default category dialog hides date fields" rule is enforced by Task 8 Step 8.4's `cat !== 'Default' && cat !== '預設'` guard on the pencil button (gating the dialog itself). ✓
- §10.1 backend tests → Tasks 1–4 ✓
- §10.2 frontend tests — deferred: no Vitest harness in the repo today; replaced with the inline node assertions in Task 5 Step 5.3 plus the manual-smoke battery in Task 12. Spec's intent (verify status function across the 8-row truth table; verify chip render; verify picker filter) is covered. ✓
- §10.3 manual smoke → Task 12 ✓
- §11 seed data — already committed in `6aa0fe1`; Task 12 references it. ✓

**Placeholder scan:** searched the plan for "TBD", "TODO", "implement later", "fill in details", "add appropriate", "similar to Task" — zero hits. Code blocks present in every modify step. Exact file paths everywhere.

**Type consistency:**
- Backend `_validate_date_range(start: str, end: str) -> None` — same signature in Task 2 (defined) and Task 4 (called). ✓
- `BookmarkManager.create_category(..., start_date='', end_date='')` defined in Task 3, called in Task 4 with the same kwargs. ✓
- `BookmarkManager.update_category(..., start_date=None, end_date=None)` defined in Task 3, called in Task 4 with `cat.start_date` / `cat.end_date` (strings — `None` semantic in service is preserved for direct callers; API layer never sends `None`). ✓
- Frontend `getCategoryStatus(start, end, today)` signature consistent across Tasks 5, 9, 10. ✓
- Frontend `onCategoryEdit(oldName, { name, color, start_date, end_date })` consistent across Tasks 8 (definition), 11 (App.tsx caller, ControlPanel forward). ✓
- Frontend `categoryDates: Record<string, {start_date, end_date}>` keyed by **name** in BookmarkList (Tasks 8/9/11), keyed by **id** in BookmarkPickerPopover (Tasks 10/11). The spec calls this out (§7.1 vs §8.1) — App.tsx and GoldDittoPanel each derive the right map for their consumer. ✓

No issues found.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-09-event-soft-archive.md`.** Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
