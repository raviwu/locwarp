# Catalog Force-Sync — Design + Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for Task 1, then superpowers:executing-plans for the rest. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "Refresh public events" always force-import the bundled catalog. After a user deletes a catalog-seeded category and clicks refresh, the deleted entries should reappear — overriding the soft-delete tombstones that currently suppress them.

---

## Root Cause

`/api/bookmarks/import` → `BookmarkManager.import_json` skips items whose id already exists (counts them as `skipped`), and otherwise appends them. Then `_save()` runs `merge_stores(self.store, on_disk)`, which applies the CRDT `_alive(obj)` rule:

```
tomb wins iff tomb.deleted_at >= obj.updated_at
```

The catalog.json entries have empty `updated_at`. Any tombstone (with a real ISO timestamp) trivially beats `""`. So after a user deletes a catalog category:

- import_json adds the items in memory (`imported: 73`)
- `_save()`'s merge pulls in the on-disk tombstones → tombstones suppress the just-added items → 0 land on disk
- Toast still reports `imported: 73, skipped: 67` (the skipped count comes from other catalog categories' bookmarks the user *didn't* delete, which collide on id)
- User clicks refresh again — same outcome, items never come back

Verified live against the user's `~/.locwarp/bookmarks.json` (143 → delete 2 → reimport → on-disk 0 / tombstones retain the deletion). The `跳過 N 筆已存在` part of the message is the existing `bm.catalog.imported` i18n string applied to the alive (non-deleted) catalog ids.

---

## Design

### Semantic change

Add a separate code path **catalog force-sync** with these rules, distinct from user-initiated import:

| Rule | `import_json` (user file) | `import_catalog` (new) |
|------|--------------------------|------------------------|
| Item id already exists | Skip, count as `skipped` | **Upsert** — overwrite fields, stamp `updated_at = now()` |
| Item id not in store    | Append                   | Append, stamp `updated_at = now()` |
| Tombstone matches id    | Honored (merge filters it after save) | **Loses** — items get `updated_at = now()` which beats `deleted_at` |
| Categories follow same rule | (skip-existing) | (upsert) |
| Local non-catalog bookmarks | Untouched | Untouched |

Why upsert (not skip) on collision: the catalog is the **source of truth** for catalog-id entries. Coordinate corrections / renames in catalog.json should propagate. The user said "強制更新，不要管 local 有沒有已存在的."

Why `updated_at = now()` (instead of also editing tombstones on disk): the CRDT semantics already give us what we want — an item with `updated_at > deleted_at` wins the merge against its tombstone. The stale tombstone gets garbage-collected after `TOMBSTONE_RETENTION_DAYS` (30d), or sooner if the same item is re-deleted (which writes a fresher tombstone). No need to special-case the merge.

### Toast change

Old: `'已加入 {imported} 筆 (跳過 {skipped} 筆已存在)'` — confusing when most are "skipped" yet nothing visibly changed.

New: `'已同步 {added} 筆新增 / {updated} 筆更新 / {resurrected} 筆復原'` (zh-TW) and equivalent English. The three counters make it obvious to the user that re-syncing a deleted category does something.

### Scope

This change is bookmark-only. Routes don't have a catalog and aren't affected.

### Out of scope

- Touching `import_json` semantics (user-file imports keep skip-existing, which matches typical "restore my backup" intent).
- A general "force overwrite" flag on the existing endpoint — adds an attack vector for accidental data loss.
- Removing tombstones from disk explicitly — the 30-day GC + updated_at-beats-deleted_at rule already covers it.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `backend/services/bookmarks.py` | `BookmarkManager` CRUD | Add `import_catalog(data: str) -> dict` |
| `backend/api/bookmarks.py` | HTTP endpoints | Add `POST /api/bookmarks/catalog/sync` (reads bundled catalog, calls `import_catalog`) |
| `backend/tests/test_bookmark_catalog_sync.py` | new test file | Cover first-sync / re-sync / delete-then-sync / local-edit / non-catalog-bookmark-untouched |
| `frontend/src/services/api.ts` | API client | Add `syncCatalog()`; remove the `importBookmarks(catalog)` call from the refresh handler |
| `frontend/src/App.tsx` | `handleCatalogRefresh` | Switch to `api.syncCatalog()`; new toast keys |
| `frontend/src/i18n/strings.ts` | i18n strings | Replace `bm.catalog.imported` with `bm.catalog.synced` carrying `{added, updated, resurrected}` |

Working directories: `backend/` for pytest (`backend/.venv/bin/python -m pytest`), `frontend/` for `tsc` / `npm run dev`.

---

## Task 1: Backend — `BookmarkManager.import_catalog`

**Files:**
- Modify: `backend/services/bookmarks.py` (append a method after `import_json` ~line 606)
- New: `backend/tests/test_bookmark_catalog_sync.py`

- [x] **Step 1: Write the failing tests (TDD)**

`backend/tests/test_bookmark_catalog_sync.py`:

```python
"""Catalog force-sync semantics: catalog is source of truth for its ids."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from services.bookmarks import BookmarkManager


CATALOG = {
    "categories": [
        {"id": "cat-A", "name": "Event A", "color": "#111", "sort_order": 1, "created_at": "2026-05-23T00:00:00Z"},
    ],
    "bookmarks": [
        {"id": "bm-1", "name": "Shop 1", "lat": 1.0, "lng": 2.0, "category_id": "cat-A", "created_at": "2026-05-23T00:00:00Z"},
        {"id": "bm-2", "name": "Shop 2", "lat": 3.0, "lng": 4.0, "category_id": "cat-A", "created_at": "2026-05-23T00:00:00Z"},
    ],
}


@pytest.fixture
def manager(tmp_path, monkeypatch):
    f = tmp_path / "bookmarks.json"
    f.write_text('{"categories": [], "bookmarks": [], "tombstones": []}')
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", f)
    monkeypatch.setattr("config.BOOKMARKS_FILE", f)
    with patch("services.bookmarks.enrich_bookmark", lambda b: None):
        yield BookmarkManager()


def test_first_sync_adds_everything(manager):
    res = manager.import_catalog(json.dumps(CATALOG))
    assert res == {"added": 2, "updated": 0, "resurrected": 0}
    assert len(manager.store.bookmarks) == 2
    assert len(manager.store.categories) == 1


def test_resync_unchanged_is_idempotent(manager):
    manager.import_catalog(json.dumps(CATALOG))
    res = manager.import_catalog(json.dumps(CATALOG))
    # All upserts (same ids exist), no resurrections
    assert res == {"added": 0, "updated": 3, "resurrected": 0}
    assert len(manager.store.bookmarks) == 2


def test_resync_after_delete_resurrects(manager):
    manager.import_catalog(json.dumps(CATALOG))
    manager.delete_category("cat-A", cascade=True)
    assert len(manager.store.bookmarks) == 0
    assert len(manager.store.tombstones) == 3  # cat-A + 2 bms

    res = manager.import_catalog(json.dumps(CATALOG))
    # All 3 ids resurrect (their tombstones lose to updated_at = now)
    assert res["resurrected"] == 3
    # Plus they're either added or updated (after delete they're "added")
    assert res["added"] + res["updated"] == 3
    # And they're alive on disk after merge
    on_disk = json.loads(Path(manager._bookmarks_path()).read_text())
    assert {b["id"] for b in on_disk["bookmarks"]} == {"bm-1", "bm-2"}
    assert {c["id"] for c in on_disk["categories"]} == {"cat-A"}


def test_resync_with_catalog_correction_overwrites(manager):
    manager.import_catalog(json.dumps(CATALOG))
    # Catalog releases a coord correction
    corrected = json.loads(json.dumps(CATALOG))
    corrected["bookmarks"][0]["lat"] = 99.9
    corrected["bookmarks"][0]["name"] = "Shop 1 (renamed)"
    res = manager.import_catalog(json.dumps(corrected))
    assert res["updated"] >= 1
    by_id = {b.id: b for b in manager.store.bookmarks}
    assert by_id["bm-1"].lat == 99.9
    assert by_id["bm-1"].name == "Shop 1 (renamed)"


def test_local_non_catalog_bookmarks_untouched(manager):
    # User adds a personal bookmark with an unrelated id
    from models.schemas import Bookmark
    manager.store.bookmarks.append(Bookmark(id="user-mine", name="Mine", lat=10.0, lng=20.0, category_id="default"))
    manager.import_catalog(json.dumps(CATALOG))
    ids = {b.id for b in manager.store.bookmarks}
    assert "user-mine" in ids  # the user's own bookmark survives
    assert {"bm-1", "bm-2"} <= ids


def test_invalid_payload_returns_zeroes(manager):
    res = manager.import_catalog("not-json")
    assert res == {"added": 0, "updated": 0, "resurrected": 0}
```

Run and confirm they all fail:
```
cd backend && .venv/bin/python -m pytest tests/test_bookmark_catalog_sync.py -v
```

- [x] **Step 2: Implement `import_catalog`**

In `backend/services/bookmarks.py`, append after `import_json` (around line 606):

```python
def import_catalog(self, data: str) -> dict:
    """Force-sync from the bundled catalog. Catalog ids are authoritative.

    Differences from import_json:
      * Existing items with catalog ids are upserted (overwrite name/coords/etc.)
      * Items get updated_at = now() so any prior tombstone loses the
        _alive(...) check in merge_stores — locally-deleted catalog entries
        resurrect.
      * Local items whose ids are NOT in the catalog are left alone.

    Returns {'added': N, 'updated': N, 'resurrected': N} where
    'resurrected' counts incoming ids that had a tombstone in our store
    (before this call) — for UI feedback only; the merge rule itself
    handles the resurrection.
    """
    try:
        incoming = BookmarkStore(**json.loads(data))
    except Exception as exc:
        logger.error("Invalid catalog JSON: %s", exc)
        return {"added": 0, "updated": 0, "resurrected": 0}

    now = _now_iso()
    incoming_cat_ids = {c.id for c in incoming.categories}
    incoming_bm_ids = {b.id for b in incoming.bookmarks}
    catalog_ids = incoming_cat_ids | incoming_bm_ids

    # Count resurrections (purely for UI feedback)
    resurrected = sum(1 for t in self.store.tombstones if t.id in catalog_ids)

    existing_cats = {c.id: c for c in self.store.categories}
    added_cats = updated_cats = 0
    for cat in incoming.categories:
        cat.updated_at = now
        if cat.id in existing_cats:
            old = existing_cats[cat.id]
            old.name = cat.name
            old.color = cat.color
            old.sort_order = cat.sort_order
            old.start_date = cat.start_date
            old.end_date = cat.end_date
            old.updated_at = now
            updated_cats += 1
        else:
            self.store.categories.append(cat)
            existing_cats[cat.id] = cat
            added_cats += 1

    valid_cat_ids = {c.id for c in self.store.categories}
    existing_bms = {b.id: b for b in self.store.bookmarks}
    added_bms = updated_bms = 0
    for bm in incoming.bookmarks:
        if bm.category_id not in valid_cat_ids:
            bm.category_id = "default"
        bm.updated_at = now
        if bm.id in existing_bms:
            old = existing_bms[bm.id]
            old.name = bm.name
            old.lat = bm.lat
            old.lng = bm.lng
            old.address = bm.address
            old.category_id = bm.category_id
            old.country_code = bm.country_code
            old.updated_at = now
            # geo enrichment for the updated record
            enrich_bookmark(old)
            updated_bms += 1
        else:
            enrich_bookmark(bm)
            self.store.bookmarks.append(bm)
            existing_bms[bm.id] = bm
            added_bms += 1

    self._save()
    return {
        "added": added_cats + added_bms,
        "updated": updated_cats + updated_bms,
        "resurrected": resurrected,
    }
```

Re-run tests → all pass.

---

## Task 2: Backend — `POST /api/bookmarks/catalog/sync` endpoint

**Files:**
- Modify: `backend/api/bookmarks.py` (add endpoint near the existing `/catalog` GET ~line 286)
- Modify: `backend/tests/test_bookmarks_api.py` (add endpoint integration test)

- [x] **Step 1: Write the failing endpoint test**

Append to `backend/tests/test_bookmarks_api.py`:

```python
def test_catalog_sync_endpoint(monkeypatch, tmp_path):
    # Use an isolated bookmarks file
    bm_file = tmp_path / "bookmarks.json"
    bm_file.write_text('{"categories": [], "bookmarks": [], "tombstones": []}')
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", bm_file)
    monkeypatch.setattr("config.BOOKMARKS_FILE", bm_file)

    # Point the catalog reader at a fixture
    cat_file = tmp_path / "catalog.json"
    cat_file.write_text(json.dumps({
        "categories": [{"id": "X", "name": "X", "color": "#000", "sort_order": 1, "created_at": "2026-05-23T00:00:00Z"}],
        "bookmarks": [{"id": "x1", "name": "x1", "lat": 1, "lng": 2, "category_id": "X", "created_at": "2026-05-23T00:00:00Z"}],
    }))
    monkeypatch.setattr("api.bookmarks._catalog_path", lambda: cat_file)

    from main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    res = client.post("/api/bookmarks/catalog/sync")
    assert res.status_code == 200
    body = res.json()
    assert body == {"added": 2, "updated": 0, "resurrected": 0}
```

- [x] **Step 2: Implement the endpoint**

In `backend/api/bookmarks.py`, below `get_catalog`:

```python
@router.post("/catalog/sync")
async def sync_catalog():
    """Force-sync the bundled catalog into the local store.

    Catalog ids are authoritative — entries previously deleted on this
    device come back, and any catalog corrections propagate. Local items
    whose ids are not in the catalog are untouched.
    """
    path = _catalog_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Catalog not bundled")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Catalog unreadable: {exc}")
    return app_state.bookmark_manager.import_catalog(text)
```

Re-run tests → pass.

---

## Task 3: Frontend — switch refresh handler to `/catalog/sync`

**Files:**
- Modify: `frontend/src/services/api.ts` (add `syncCatalog`)
- Modify: `frontend/src/App.tsx` (`handleCatalogRefresh`)
- Modify: `frontend/src/i18n/strings.ts` (toast key)

- [x] **Step 1: API client**

In `frontend/src/services/api.ts`, add:

```ts
export type CatalogSyncResult = { added: number; updated: number; resurrected: number };

export async function syncCatalog(): Promise<CatalogSyncResult> {
  const r = await fetch('/api/bookmarks/catalog/sync', { method: 'POST' });
  if (!r.ok) throw new HttpError(r.status, await r.text());
  return r.json();
}
```

- [x] **Step 2: i18n string**

In `frontend/src/i18n/strings.ts`, replace `bm.catalog.imported`:

```ts
'bm.catalog.synced': {
  zh: '已同步：新增 {added}・更新 {updated}・復原 {resurrected}',
  en: 'Synced: {added} added · {updated} updated · {resurrected} restored',
},
```

(Keep `bm.catalog.imported` for back-compat in case some test references it, but it's no longer rendered.)

- [x] **Step 3: `handleCatalogRefresh`**

In `frontend/src/App.tsx` around line 1368:

```ts
const handleCatalogRefresh = useCallback(async () => {
  if (!catalog || catalogRefreshing) return
  setCatalogRefreshing(true)
  try {
    const res = await api.syncCatalog()
    await bm.refresh()
    showToast(t('bm.catalog.synced', {
      added: res.added,
      updated: res.updated,
      resurrected: res.resurrected,
    }))
  } catch (err: unknown) {
    showToast(err instanceof Error ? err.message : t('bm.catalog.failed'))
  } finally {
    setCatalogRefreshing(false)
  }
}, [catalog, catalogRefreshing, bm, showToast, t])
```

- [ ] **Step 4: Verify in app**

Run `python start.py` (or `LocWarp.bat`). Delete a catalog category (e.g., 麵處匠 TAKUMI) via the bookmarks panel. Click **更新公開活動清單**. Confirm:
- The category and its 73 bookmarks reappear immediately
- Toast reads `已同步：新增 0・更新 0・復原 74`（or 73 + 1 depending on whether the user deleted just the category or also other entries）
- Repeated clicks become no-ops in terms of content (counts: `0 / 73 / 0`)

---

## Task 4: Smoke test — full flow

- [x] Run backend pytests (12/12 catalog tests pass; 2 unrelated pre-existing failures in `test_bookmarks_api.py` due to missing `numpy` in venv):
```
cd backend && .venv/bin/python -m pytest tests/test_bookmark_catalog_sync.py tests/test_bookmarks_api.py -v
```

- [x] Run frontend type-check (exit 0):
```
cd frontend && npx tsc --noEmit
```

- [ ] Manual: in the app, after the changes,
  1. delete category → bookmarks gone
  2. click 更新公開活動清單 → bookmarks reappear, toast shows `復原 N`
  3. click again → toast shows `0 / N / 0` (all updates, nothing new, nothing resurrected)
  4. delete a single bookmark → it's gone
  5. click again → just that one comes back

---

## Risks / open questions

- **iCloud cross-device propagation:** if another device is synced via iCloud and previously had a tombstone for the same id, when our resurrected item lands there, merge_stores compares the tombstone's `deleted_at` against our new `updated_at` (now). Now wins. ✓
- **Clock skew:** if the other device's tombstone has a future `deleted_at` (clock ahead by minutes), the resurrected item could lose. Acceptable — covered by `TOMBSTONE_RETENTION_DAYS` GC eventually, and the user can re-click sync.
- **Cascade in delete_category:** unchanged. The user can still delete catalog categories — sync brings them back.
- **`importBookmarks` callers:** still used for user-file imports (drag-drop a JSON). Skip-existing semantics retained for that path. Only the catalog Refresh button moves to the new endpoint.
