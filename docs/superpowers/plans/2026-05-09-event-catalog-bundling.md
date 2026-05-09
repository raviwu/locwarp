# Event Catalog Bundling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a curated `catalog.json` inside the LocWarp build and add a Library button that merges it into the user's bookmark store on demand.

**Architecture:** The catalog file lives at `backend/static/catalog.json`, bundled by PyInstaller. A read-only `GET /api/bookmarks/catalog` endpoint returns its contents. The frontend fetches it on Library mount, computes how many bookmark ids are not yet in the local store (`N`), and renders a button next to Import labelled `更新公開活動清單 (N new)` / `Refresh public events (N new)`. Clicking the button POSTs the catalog body to the existing `/api/bookmarks/import` endpoint, which already does id-collision-skip merging, then refetches the catalog so `N` falls to 0.

**Tech Stack:** Python 3 + FastAPI + Pydantic v2 + PyInstaller (backend), React 18 + TypeScript + Vite (frontend), pytest. No frontend test harness — manual smoke + tsc.

**Spec:** `docs/superpowers/specs/2026-05-09-event-catalog-bundling-design.md`.

---

## File Map

**Backend — moved/new:**
- `git mv docs/samples/pikmin-bloom-events.json → backend/static/catalog.json` (Task 1).
- `backend/api/bookmarks.py` — `_catalog_path()` helper + `GET /api/bookmarks/catalog` endpoint (Task 1).
- `backend/locwarp-backend.spec` — add `('static/catalog.json', 'static')` to `datas` (Task 1).
- `backend/tests/test_bookmark_catalog.py` — new test file with 3 tests (Task 1).

**Frontend — modified:**
- `frontend/src/i18n/strings.ts` — 6 new keys (Task 2).
- `frontend/src/services/api.ts` — `CatalogPayload` interface + `getCatalog()` function (Task 3).
- `frontend/src/App.tsx` — catalog fetch, count derivation, refresh handler, props pass (Task 4).
- `frontend/src/components/ControlPanel.tsx` — pass-through props (Task 4).
- `frontend/src/components/BookmarkList.tsx` — render the button next to Import (Task 4).

**Verification:**
- Manual smoke against the live app (Task 5).

---

## Task 1 — Backend: catalog file, endpoint, tests, PyInstaller bundling

**Files:**
- Move: `docs/samples/pikmin-bloom-events.json` → `backend/static/catalog.json` (via `git mv`).
- Modify: `backend/api/bookmarks.py` (add helper + endpoint near the existing `_FORMAT_TO_FILENAME_EXT` block).
- Modify: `backend/locwarp-backend.spec` (one-line addition to `datas`).
- Create: `backend/tests/test_bookmark_catalog.py` (new file).

- [ ] **Step 1.1: Move the catalog file**

```bash
cd /Users/raviwu/personal/locwarp
git mv docs/samples/pikmin-bloom-events.json backend/static/catalog.json
```

(The directory `docs/samples/` may now be empty; do not delete it — leave it for future samples.)

- [ ] **Step 1.2: Update the PyInstaller spec**

In `backend/locwarp-backend.spec`, find the `datas=` list (around line 68–69) which currently contains `('static/phone.html', 'static')`. Append `('static/catalog.json', 'static')`:

```python
    datas=[*pmd_datas, *pytun_datas, *ddi_datas, *pyimg4_datas, *pyimg4_meta,
           ('static/phone.html', 'static'),
           ('static/catalog.json', 'static')],
```

- [ ] **Step 1.3: Write the failing endpoint tests**

Create `backend/tests/test_bookmark_catalog.py`:

```python
"""Tests for GET /api/bookmarks/catalog."""
from __future__ import annotations

import json
from pathlib import Path

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


def test_get_catalog_returns_bundled_payload(client):
    resp = client.get("/api/bookmarks/catalog")
    assert resp.status_code == 200
    body = resp.json()
    assert "categories" in body
    assert "bookmarks" in body
    # Sanity: the seed file has Sapporo Tour and Sanga Stadium.
    cat_names = [c["name"] for c in body["categories"]]
    assert "Sapporo Pikmin Bloom Tour" in cat_names
    assert "Sanga Stadium by KYOCERA" in cat_names
    # Dates round-trip.
    sanga = next(c for c in body["categories"] if c["name"] == "Sanga Stadium by KYOCERA")
    assert sanga["start_date"] == "2026-02-06"
    assert sanga["end_date"] == "2026-06-07"


def test_get_catalog_404_when_file_missing(client, tmp_path, monkeypatch):
    missing = tmp_path / "nope.json"
    monkeypatch.setattr("api.bookmarks._catalog_path", lambda: missing)
    resp = client.get("/api/bookmarks/catalog")
    assert resp.status_code == 404


def test_get_catalog_500_when_malformed(client, tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    monkeypatch.setattr("api.bookmarks._catalog_path", lambda: bad)
    resp = client.get("/api/bookmarks/catalog")
    assert resp.status_code == 500
```

- [ ] **Step 1.4: Run to confirm the tests fail**

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/test_bookmark_catalog.py -v
```

Expected: All 3 fail. The first two with `404` (no endpoint), the third also `404`. (Alternatively if the route is intercepted by another handler, you'll get a different error — either way, no `200`.)

- [ ] **Step 1.5: Add the helper + endpoint to `api/bookmarks.py`**

In `backend/api/bookmarks.py`, near the top after the existing imports (right after the `_validate_date_range` block from the soft-archive feature), add:

```python
import sys


def _catalog_path() -> Path:
    """Resolve catalog.json in both dev and PyInstaller-packaged layouts.

    Mirrors the convention used by ``api.phone_control._phone_page_path``.
    """
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "static" / "catalog.json")
    candidates.append(Path(__file__).resolve().parent.parent / "static" / "catalog.json")
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]
```

Also add `from pathlib import Path` to the imports if not already present (the file may have it; grep first).

Then, **at the bottom of the route handlers** (after the existing `set_bookmark_ui_state` POST), add:

```python
@router.get("/catalog")
async def get_catalog():
    """Return the curated event catalog bundled with the build.

    404 when the file is missing (build did not include it; UI hides
    the Refresh button). 500 when the file is unreadable or malformed.
    """
    path = _catalog_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Catalog not bundled")
    try:
        text = path.read_text(encoding="utf-8")
        json.loads(text)  # validate
    except (OSError, ValueError):
        raise HTTPException(status_code=500, detail="Catalog unreadable or malformed")
    return Response(content=text, media_type="application/json")
```

`json` and `Response` are already imported at module scope. Do **not** call `_bm()` — the catalog endpoint is independent of the user store.

- [ ] **Step 1.6: Run the tests, expect green**

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/test_bookmark_catalog.py -v
```

Expected: 3 passed. Then run the whole backend suite to confirm no regressions:

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/ -q
```

Expected: 82 passed (79 prior + 3 new).

- [ ] **Step 1.7: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add backend/static/catalog.json backend/api/bookmarks.py backend/locwarp-backend.spec backend/tests/test_bookmark_catalog.py docs/samples/pikmin-bloom-events.json
git commit -m "$(cat <<'EOF'
feat(backend): GET /api/bookmarks/catalog + bundled catalog.json

Curated event seed moves from docs/samples/ to backend/static/ so
PyInstaller picks it up. Read-only endpoint reads, validates, and
returns the file body; 404 if missing, 500 if malformed. Mirrors the
_phone_page_path() resolution pattern for dev vs frozen layouts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(`git mv` from Step 1.1 is staged automatically; `git add` here picks up everything else. Confirm `git status` is clean afterwards.)

---

## Task 2 — Frontend i18n keys

**Files:**
- Modify: `frontend/src/i18n/strings.ts` (insert new block near other `bm.cat.*` keys).

- [ ] **Step 2.1: Add the catalog keys**

In `frontend/src/i18n/strings.ts`, after the existing `bm.picker.include_ended` line, add:

```ts
  // — Public event catalog (bundled JSON refresh button) —
  'bm.catalog.refresh':            { zh: '更新公開活動清單',           en: 'Refresh public events' },
  'bm.catalog.refresh_count':      { zh: '更新公開活動清單 ({n} new)', en: 'Refresh public events ({n} new)' },
  'bm.catalog.up_to_date':         { zh: '已是最新',                   en: 'Up to date' },
  'bm.catalog.up_to_date_tooltip': { zh: '無新活動可加入',             en: 'No new events available' },
  'bm.catalog.failed':             { zh: '更新失敗',                   en: 'Update failed' },
  'bm.catalog.imported':           { zh: '已加入 {imported} 筆 (跳過 {skipped} 筆已存在)',
                                     en: 'Added {imported} entries ({skipped} already present, skipped)' },
```

- [ ] **Step 2.2: Type-check**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 2.3: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/i18n/strings.ts
git commit -m "$(cat <<'EOF'
feat(frontend): i18n keys for event catalog refresh

Six new keys covering the Library button labels (refresh / up-to-date),
its disabled tooltip, the failure label, and the post-import toast.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — Frontend api.ts: `getCatalog` + types

**Files:**
- Modify: `frontend/src/services/api.ts` (add interface + function near existing bookmark exports around line 305).

- [ ] **Step 3.1: Add the catalog interface and fetch function**

In `frontend/src/services/api.ts`, near the existing `importBookmarks` export (around line 305), add:

```ts
export interface CatalogBookmark {
  id: string;
  name: string;
  lat: number;
  lng: number;
  category_id: string;
  address?: string;
  country_code?: string;
  created_at?: string;
  last_used_at?: string;
}

export interface CatalogPayload {
  // _meta is informational; the import endpoint ignores it.
  _meta?: Record<string, unknown>;
  categories: CategoryResponse[];
  bookmarks: CatalogBookmark[];
}

export const getCatalog = () =>
  request<CatalogPayload>('GET', '/api/bookmarks/catalog')
```

(Place the interfaces immediately above the `getCatalog` export. `CategoryResponse` is already exported earlier in the file.)

- [ ] **Step 3.2: Type-check**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3.3: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/services/api.ts
git commit -m "$(cat <<'EOF'
feat(frontend): typed getCatalog() in api.ts

Reads the bundled event catalog from GET /api/bookmarks/catalog.
404 / 500 propagate as thrown errors via the existing request()
helper; the caller decides whether to hide or fail-flag the UI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — Frontend wiring: App + ControlPanel + BookmarkList button

**Files:**
- Modify: `frontend/src/App.tsx` (catalog state, fetch, refresh handler, prop pass).
- Modify: `frontend/src/components/ControlPanel.tsx` (props pass-through).
- Modify: `frontend/src/components/BookmarkList.tsx` (button render).

- [ ] **Step 4.1: Add catalog state + handlers in `App.tsx`**

In `frontend/src/App.tsx`, near the other bookmark-related state (around the existing `bm = useBookmarks()` and `handleBookmarkImport` definitions), add:

```ts
type CatalogStatus = 'loading' | 'ok' | 'missing' | 'failed';

const [catalog, setCatalog] = useState<api.CatalogPayload | null>(null);
const [catalogStatus, setCatalogStatus] = useState<CatalogStatus>('loading');
const [catalogError, setCatalogError] = useState<string | null>(null);

const fetchCatalog = useCallback(async () => {
  try {
    const data = await api.getCatalog();
    setCatalog(data);
    setCatalogStatus('ok');
    setCatalogError(null);
  } catch (err: any) {
    setCatalog(null);
    const msg = err?.message ?? 'unknown';
    if (/404/.test(msg) || /not bundled/i.test(msg)) {
      setCatalogStatus('missing');
    } else {
      setCatalogStatus('failed');
      setCatalogError(msg);
    }
  }
}, []);

useEffect(() => {
  void fetchCatalog();
}, [fetchCatalog]);

const catalogNewCount = useMemo(() => {
  if (!catalog) return 0;
  const existingIds = new Set(bm.bookmarks.map((b) => b.id));
  return catalog.bookmarks.filter((cb) => !existingIds.has(cb.id)).length;
}, [catalog, bm.bookmarks]);

const handleCatalogRefresh = useCallback(async () => {
  if (!catalog) return;
  try {
    const res = await api.importBookmarks(catalog as unknown as Record<string, unknown>);
    await bm.refresh();
    await fetchCatalog();
    const imported = (res as any).imported ?? 0;
    const skipped = (res as any).skipped ?? 0;
    showToast(t('bm.catalog.imported', { imported, skipped }));
  } catch (err: any) {
    showToast(err?.message ?? t('bm.catalog.failed'));
  }
}, [catalog, bm, fetchCatalog, showToast, t]);
```

(Verify `useState`, `useCallback`, `useEffect`, `useMemo` are all imported at the top of App.tsx — they should be from prior tasks.)

In the `<ControlPanel ...>` JSX block where other bookmark props are passed, add:

```tsx
catalogStatus={catalogStatus}
catalogNewCount={catalogNewCount}
catalogError={catalogError}
onCatalogRefresh={handleCatalogRefresh}
```

- [ ] **Step 4.2: Pass props through `ControlPanel.tsx`**

In `frontend/src/components/ControlPanel.tsx`, locate the props interface (where `categoryDates` lives, around line 102 after Task 11 of soft-archive) and add:

```ts
catalogStatus?: 'loading' | 'ok' | 'missing' | 'failed';
catalogNewCount?: number;
catalogError?: string | null;
onCatalogRefresh?: () => Promise<void> | void;
```

Update the destructure (around line 277) similarly: add `catalogStatus`, `catalogNewCount`, `catalogError`, `onCatalogRefresh`.

In the `<BookmarkList ... />` JSX (around line 883), add:

```tsx
catalogStatus={catalogStatus}
catalogNewCount={catalogNewCount}
catalogError={catalogError}
onCatalogRefresh={onCatalogRefresh}
```

- [ ] **Step 4.3: Add the button to `BookmarkList.tsx`**

In `frontend/src/components/BookmarkList.tsx`, locate the `BookmarkListProps` interface (where `categoryDates` was added in Task 8 of soft-archive) and add:

```ts
catalogStatus?: 'loading' | 'ok' | 'missing' | 'failed';
catalogNewCount?: number;
catalogError?: string | null;
onCatalogRefresh?: () => Promise<void> | void;
```

Update the destructure in the function signature similarly.

Locate the existing `Import` button in the header. The header is in the JSX around the `<div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, marginBottom: 8 }}>` block (around line 426). The Import button likely uses `t('bm.import')` or has a `<input type="file">` — find the block that wires up `onImport`.

Insert the new button **immediately after** the Import button. Code:

```tsx
{onCatalogRefresh && catalogStatus !== 'missing' && (() => {
  const loading = catalogStatus === 'loading';
  const failed = catalogStatus === 'failed';
  const count = catalogNewCount ?? 0;
  const upToDate = catalogStatus === 'ok' && count === 0;
  const disabled = loading || failed || upToDate;
  const label = failed
    ? t('bm.catalog.failed')
    : upToDate
      ? t('bm.catalog.up_to_date')
      : loading
        ? t('bm.catalog.refresh')
        : t('bm.catalog.refresh_count', { n: count });
  const title = failed
    ? (catalogError ?? '')
    : upToDate
      ? t('bm.catalog.up_to_date_tooltip')
      : '';
  return (
    <button
      className="action-btn"
      onClick={() => { void onCatalogRefresh(); }}
      disabled={disabled}
      title={title || undefined}
      style={{ padding: '3px 8px', fontSize: 12, opacity: disabled ? 0.5 : 1 }}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polyline points="23 4 23 10 17 10" />
        <polyline points="1 20 1 14 7 14" />
        <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
      </svg>
      {label}
    </button>
  );
})()}
```

(Inline `(() => { ... })()` keeps the local `loading` / `failed` / `count` / `upToDate` derivations next to the JSX. The SVG is the standard "refresh" / cycle arrow.)

- [ ] **Step 4.4: Type-check**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 4.5: Build sanity**

```bash
cd /Users/raviwu/personal/locwarp/frontend && npm run build
```

Expected: build completes. Pre-existing chunk-size warning unchanged.

- [ ] **Step 4.6: Commit**

```bash
cd /Users/raviwu/personal/locwarp
git add frontend/src/App.tsx frontend/src/components/ControlPanel.tsx frontend/src/components/BookmarkList.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): "Refresh public events" Library button

App.tsx fetches the bundled catalog on mount and exposes a
refresh handler that POSTs through the existing import flow.
BookmarkList renders a button next to Import with three labels:
"Refresh public events ({n} new)" when there are deltas,
"Up to date" when N=0, and "Update failed" with a tooltip on error.
The button is hidden when the catalog endpoint 404s (build did
not bundle it).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5 — Manual smoke

**Files:** none modified — this is a verification gate.

- [ ] **Step 5.1: Verify backend tests one more time**

```bash
cd /Users/raviwu/personal/locwarp/backend && python -m pytest tests/ -q
```

Expected: all green (82+).

- [ ] **Step 5.2: Run the dev environment**

```bash
cd /Users/raviwu/personal/locwarp && ./start.sh
```

- [ ] **Step 5.3: Initial state — already merged earlier**

Open Library. The `更新公開活動清單` button should read `已是最新` (zh) or `Up to date` (en) and be disabled with tooltip `無新活動可加入` / `No new events available`. (Earlier in this session you already merged the catalog into your local store, so `N=0`.)

- [ ] **Step 5.4: Force a delta**

In Library, delete the `Sapporo Pikmin Bloom Tour` category with cascade (drops 12 bookmarks). The catalog button label should refresh to `更新公開活動清單 (12 new)` / `Refresh public events (12 new)` and become enabled.

Click it. Toast appears: `已加入 12 筆 (跳過 1 筆已存在)` (the 1 skipped is Sanga Stadium, already in your store). The category and 12 bookmarks reappear. Button label drops back to `已是最新`.

- [ ] **Step 5.5: Force a failure**

In a separate terminal, temporarily rename `backend/static/catalog.json` to `catalog.json.tmp`, restart the backend, reopen Library. The button should hide entirely (`catalogStatus === 'missing'`).

Restore the file:

```bash
mv backend/static/catalog.json.tmp backend/static/catalog.json
```

- [ ] **Step 5.6: Force a malformed catalog**

Edit `backend/static/catalog.json` and corrupt the JSON (insert a stray `{`). Restart the backend, reopen Library. The button should read `更新失敗` / `Update failed`, be disabled, and show the error in tooltip on hover.

Revert the file:

```bash
git -C /Users/raviwu/personal/locwarp checkout -- backend/static/catalog.json
```

- [ ] **Step 5.7: No commit**

Smoke makes no code changes. If you spotted a regression, fix it as a new commit referencing the broken step.

---

## Self-Review (recorded after writing the plan)

**Spec coverage:**
- §2 Goal 1 (bundled file) → Task 1.1 + 1.2 ✓
- §2 Goal 2 (Library button) → Task 4.3 ✓
- §2 Goal 3 (show count before click) → Task 4.1 (`catalogNewCount`) + 4.3 (`refresh_count` label) ✓
- §2 Goal 4 (reuse import) → Task 4.1 (`api.importBookmarks(catalog)`) ✓
- §2 Goal 5 (release-cadence ship) → Task 1.2 (PyInstaller datas) ✓
- §3 Non-goals — no auto-import (Task 4 only registers the button), no remote URL (endpoint reads local file), no deletion (relies on existing import semantics), no force-overwrite (relies on existing import semantics), no diff dialog (button label only), no version tracking (idempotent endpoint) ✓
- §5.1 file format — preserved verbatim (git mv, no content change) ✓
- §5.2 endpoint behaviour — Task 1.5 ✓
- §6.1 button location — Task 4.3 inserts after Import ✓
- §6.2 button states — all four covered in Task 4.3 (loading, up_to_date, count, failed; missing hides) ✓
- §6.3 click flow — Task 4.1 `handleCatalogRefresh` does fetch → import → refresh → refetch → toast ✓
- §6.4 lifecycle — Task 4.1 `useEffect(() => void fetchCatalog(), [])` on mount; refetch after merge in same handler ✓
- §6.5 i18n keys — Task 2 ✓
- §7.1 backend tests — Task 1.3 ✓
- §7.2 frontend manual smoke — Task 5 ✓
- §8 edge cases — file missing (404 → button hidden, Task 4.3 guard `catalogStatus !== 'missing'`), empty catalog (count is 0 → up_to_date), id collision (existing import path), past dates (existing soft-archive renders ended), network error (catch block in Task 4.1), rapid double-click (idempotent endpoint), race window (refetch-after-import covers it). ✓

**Placeholder scan:** searched plan for "TBD", "TODO", "implement later", "fill in details", "add appropriate", "similar to Task" — zero hits.

**Type consistency:**
- `CatalogPayload` defined in Task 3, consumed in Task 4 (`api.CatalogPayload`). Same shape. ✓
- `getCatalog()` returns `CatalogPayload`; consumed by `setCatalog`. ✓
- `importBookmarks(data)` already accepts `any` shape; passing the catalog as the body is intentional even with the `as unknown as Record<string, unknown>` widening (the existing function signature is `importBookmarks(data: any)` per `api.ts:305`). Acceptable. ✓
- `catalogStatus` type alias defined in App.tsx as a string union; ControlPanel and BookmarkList copy it as inline string-union types. Consistent values. ✓
- i18n key names match across Tasks 2 and 4 (`bm.catalog.refresh`, `bm.catalog.refresh_count`, `bm.catalog.up_to_date`, `bm.catalog.up_to_date_tooltip`, `bm.catalog.failed`, `bm.catalog.imported`). ✓
- Endpoint URL `/api/bookmarks/catalog` matches between Task 1 (definition) and Task 3 (call). ✓

No issues found.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-09-event-catalog-bundling.md`.** Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review.
2. **Inline Execution** — execute tasks in this session.

Which approach?
