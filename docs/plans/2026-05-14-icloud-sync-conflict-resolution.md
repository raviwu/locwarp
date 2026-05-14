# iCloud Sync Conflict Resolution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **STATUS: AWAITING DIRECTION APPROVAL.** Ravi asked to "write the plan first, then decide" the architecture for symptoms 2 & 3. The survey + recommendation below is the decision input. The implementation tasks describe the *recommended* approach (Approach 1). Do not start coding until Ravi approves the direction.

**Goal:** Fix three iCloud-sync defects — the toggle resetting on rebuild, concurrent edits clobbering each other, and deleted categories reappearing — by replacing the whole-file last-writer-wins model with a tombstone + per-item-timestamp merge applied on every read and write.

**Architecture:** Symptoms 2 & 3 share one root cause (whole-file LWW, no tombstones, a save guard blind to iCloud propagation lag). The fix is a commutative, idempotent 2-way store merge (LWW-element-set CRDT) keyed by per-item `updated_at` and a tombstone list, run at *both* save and reconcile so no write ever blindly overwrites. Symptom 1 is an unrelated startup-ordering bug, fixed by re-reading the sync folder after the helper chowns root-owned files.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, watchdog file watcher, pytest. No new dependencies.

---

## Problem Statement

Three defects reported by Ravi while running LocWarp across two Macs with iCloud sync on:

1. **Toggle resets on rebuild.** Every rebuild forces re-checking the "iCloud sync" toggle.
2. **Concurrent additions clobbered.** Data added on machine A syncs; data added on machine B is overwritten.
3. **Deleted categories reappear.** A category deleted on one machine comes back.

### Root Cause 1 — Toggle resets on rebuild (isolated bug)

`_sync_folder` is the single source of truth for the toggle (`api/cloud_sync.py:41` — `enabled=app_state._sync_folder is not None`). It is read exactly once, in `AppState.__init__()` → `_load_persisted_state()` (`main.py:113`), and `app_state = AppState()` executes at **module import time** (`main.py:347`).

The startup ordering is:

1. Module import → `AppState()` → `_load_persisted_state()` reads `~/.locwarp/settings.json` **as the regular user**.
2. *Then* the FastAPI lifespan runs (`main.py:745+`) and asks the elevated helper to chown root-owned `~/.locwarp/` files back to the user (`main.py:778-786`).
3. *Then* `await app_state.load_state()` (`main.py:810`) runs — but it calls `_load_settings()` (`main.py:124`), which reads `last_position`, `coord_format`, etc. **It never re-reads `sync_folder`.**

So if `~/.locwarp/settings.json` is root-owned — which happens after an older all-root build, or a `sudo ./start.sh` dev run — step 1 fails silently (`safe_load_json` returns `None`), `_sync_folder` latches to `None`, and nothing ever re-reads it. The chown in step 2 fixes the file's ownership on disk but is too late for the in-memory value. Result: the toggle shows OFF for the whole session. Alternating `make start` (dev) and `make build-install` (packaged) reproduces it every time.

Build scripts (`build-installer-mac.sh`, `scripts/kill-all.sh`, `Makefile`) were checked and do **not** touch `~/.locwarp/` — the cause is purely the read-before-chown ordering.

### Root Cause 2 & 3 — Clobbered edits and zombie deletes (shared architectural cause)

The sync model is "whole-file last-writer-wins, with no tombstones, guarded by a same-device mtime check." iCloud Drive propagation is asynchronous (seconds to minutes), so the guard cannot see another device's not-yet-delivered write.

**Bookmarks** — `BookmarkManager._save()` (`services/bookmarks.py:95-115`):

```python
if current_mtime > self._last_loaded_mtime:
    self._reconcile_from_disk()
payload = json.loads(self.store.model_dump_json())
safe_write_json(path, payload)
```

The guard `current_mtime > self._last_loaded_mtime` only fires when *this device's local disk copy* changed since it last loaded. When machine B edits while machine A's change is still in flight through iCloud, B's local disk has not yet received A's change → guard does not fire → B writes `baseline + B's change`, **dropping A's change from the file**. iCloud then propagates B's file to A; A's watcher reconciles, but `diff_store(current=A.store, baseline=A.snapshot)` is now *empty* (A already saved, so store == snapshot) → `merge_local_wins` returns B's file verbatim → **A's change is lost on A too**. That is symptom 2.

For a deletion the same mechanism produces symptom 3: A deletes category C → file no longer has C. Before B receives that file, B saves anything → B's file still contains C (B never deleted it) → C is back in iCloud → A's reconcile pulls C back. Because there are **no tombstones**, "deleted" is indistinguishable from "this device never had it", so any concurrent writer resurrects it.

**Routes are worse.** `RouteManager._save()` (`services/route_store.py:121-124`) has **no reconcile guard at all** — it blindly overwrites. `RouteManager._watcher_tick()` (`services/route_store.py:185-203`) calls `self._load()`, a full whole-file replace of the in-memory store. Zero merge. Any concurrent route edit loses data.

The existing `diff_store` / `merge_local_wins` machinery (`services/bookmark_merge.py`) is a half-built 3-way merge whose "base" (the in-memory snapshot) goes stale the instant the device saves. It cannot be rescued by tuning mtime timing — with asynchronous file sync, lost updates are unavoidable unless the data model itself carries enough information to merge correctly regardless of write order.

---

## Approach Survey (Symptoms 2 & 3)

Three industry approaches for syncing structured local data over a dumb file-sync backend (iCloud Drive / Dropbox / OneDrive), where the transport gives no conflict callbacks — the app only sees "the file changed."

### Approach 1 — Tombstone + per-item timestamp (LWW-element-set CRDT)

Each item (`Bookmark`, `Route`, both category types) carries `updated_at`. Each store carries a `tombstones` list — `{id, kind, deleted_at}` records. Merge is a pure 2-way function: union all items by id; on id collision the newer `updated_at` wins; a tombstone suppresses an item iff `deleted_at >= item.updated_at`; tombstones older than a retention window (30 days) are garbage-collected. The merge is **commutative and idempotent** (`merge(a,b) == merge(b,a)`, `merge(a,a) == a`), so it needs no base snapshot. It runs on every save (read-merge-write) and every reconcile.

- **Pros:** No base snapshot to persist or corrupt. Commutativity means write order does not matter — the core fix for symptoms 2 & 3. Backward compatible: missing `updated_at` is treated as epoch, missing `tombstones` defaults to `[]`. Small, well-understood algorithm. Reuses the existing JSON-snapshot file format. Fixes routes and bookmarks with one shared function.
- **Cons:** Relies on wall-clock timestamps — clock skew between machines could mis-order two edits to the *same* item made within the skew window. Mitigated: single user, machines NTP-synced, true same-item concurrent edits are rare. Tombstones need GC (handled in the merge).

### Approach 2 — Three-way merge with a persisted base

Persist the last-synced snapshot ("base") to disk. On reconcile, merge `base + local + remote` git-style, precisely classifying add/modify/delete on each side.

- **Pros:** Precisely distinguishes a delete from a never-had. No timestamps needed for the add/delete cases.
- **Cons:** The base is extra durable state that can desync, corrupt, or be lost (exactly the failure mode that bit symptom 1). The "both sides modified the same item" case *still* needs a tiebreak — so you end up adding timestamps anyway. The save path still needs read-merge-write; the base only helps the pull side. Strictly more moving parts than Approach 1 for the same end behaviour once you need a tiebreak. The current half-built `diff_store`/`merge_local_wins` is this approach — and its in-memory base is the source of the bug.

### Approach 3 — Full CRDT op-log (Automerge / Yjs)

Replace the JSON snapshot with an append-only operation log; every edit is a commuting operation.

- **Pros:** Strongest correctness, supports genuine real-time concurrent editing, no lost updates ever.
- **Cons:** Heavy new dependency. Changes the on-disk format entirely (op-log, not a human-readable JSON snapshot) — breaks every existing tool, test, and the import/export feature. The op-log grows unbounded without compaction. Massive overkill for the actual use case: one user, 2-3 machines, edits that are almost never truly simultaneous.

### Tradeoff Summary

| Criterion                  | A1 — Tombstone + timestamp | A2 — 3-way + base | A3 — CRDT op-log |
|----------------------------|----------------------------|-------------------|------------------|
| Fixes symptoms 2 & 3       | Yes                        | Yes               | Yes              |
| New durable state to manage| Tombstone list (in-store)  | Base snapshot file| Op-log file      |
| New dependency             | None                       | None              | Automerge/Yjs    |
| On-disk format changes     | Additive fields only       | Additive + base   | Total rewrite    |
| Write-order independence   | Yes (commutative)          | Partial           | Yes              |
| Same-item tiebreak         | Timestamp LWW              | Still needs one   | Causal/CRDT      |
| Backward compatible        | Yes (Pydantic defaults)    | Yes               | No               |
| Effort                     | Medium                     | Medium-High       | High             |

### Recommendation — Approach 1

Approach 1 is the smallest change that actually fixes the root cause. It needs no base snapshot (the very kind of fragile durable state that caused symptom 1), no new dependency, and keeps the JSON-snapshot format that import/export and every existing test rely on. Commutativity is the property that makes symptoms 2 & 3 go away: it no longer matters which device writes when. The one real weakness — wall-clock skew on a same-item concurrent edit — is acceptable for a single-user, few-machines, rarely-simultaneous workload, and can be hardened later with a hybrid logical clock if it ever bites.

Approach 2's persisted base is more fragile for no behavioural gain. Approach 3 is the textbook-correct answer for a multi-user collaborative editor, which LocWarp is not.

**The rest of this plan implements Approach 1. It is contingent on Ravi approving this direction.**

---

## Design (Approach 1)

### Schema changes — `backend/models/schemas.py`

- `Bookmark`: add `updated_at: str = ""`.
- `BookmarkCategory`: add `updated_at: str = ""`.
- `RouteCategory`: add `updated_at: str = ""`.
- `SavedRoute`: already has `updated_at` — no change.
- New `Tombstone` model: `{ id: str, kind: str, deleted_at: str }` where `kind` is `"bookmark" | "category" | "route"`.
- `BookmarkStore`: add `tombstones: list[Tombstone] = []`.
- `RouteStore`: add `tombstones: list[Tombstone] = []`.

All additions are defaulted, so existing `bookmarks.json` / `routes.json` files load unchanged.

### Merge function — new `backend/services/store_merge.py`

A single pure module (no I/O, no logging) exporting `merge_stores`. It operates on plain Pydantic store objects and is generic over the two store shapes via a small descriptor of "what lists does this store have."

Algorithm:

1. Union categories by `id`; on collision keep the copy with the newer `updated_at` (empty string sorts as oldest).
2. Union items (`bookmarks` or `routes`) by `id` the same way.
3. Concatenate both stores' `tombstones`; dedupe by `id`, keeping the newest `deleted_at`.
4. For each tombstone, drop the matching item/category iff `tombstone.deleted_at >= survivor.updated_at` (a later edit out-votes an earlier delete — "the other device was actively using it").
5. GC: drop tombstones whose `deleted_at` is older than `TOMBSTONE_RETENTION_DAYS` (30). Safe because every device syncs well within 30 days.
6. Return a new store. The function must satisfy `merge_stores(a, b) == merge_stores(b, a)` and `merge_stores(a, a) == a`.

The existing same-name category collapse (`_build_category_remap` in `sync_merge.py`) is **kept** and runs after the union, unchanged — it is a separate, still-correct concern (bootstrap dedup of independently-created categories).

### Mutation stamping — `BookmarkManager` / `RouteManager`

Every mutation sets `updated_at = _now_iso()` on the touched item/category:

- `create_bookmark`, `update_bookmark`, `move_bookmarks` → stamp the bookmark(s).
- `create_category`, `update_category` → stamp the category.
- `delete_bookmark`, `delete_category`, `delete_route`, route delete → append a `Tombstone` to `store.tombstones` *and* remove the item from its list.
- `delete_category` non-cascade: bookmarks reparented to `default` get `updated_at` bumped (they were modified).

### Save / reconcile — `BookmarkManager` / `RouteManager`

Replace the mtime-guarded conditional reconcile with unconditional read-merge-write:

```python
def _save(self):
    path = self._path()
    disk = _load_store_or_empty(path)        # tolerant: empty store on missing/corrupt
    self.store = merge_stores(self.store, disk)
    safe_write_json(path, json.loads(self.store.model_dump_json()))
    self._update_snapshot()                  # snapshot retained only for watcher self-echo detection
```

```python
def _reconcile_from_disk(self):
    disk = _load_store_or_empty(path)
    self.store = merge_stores(self.store, disk)
```

`diff_store` and `merge_local_wins` (`services/bookmark_merge.py`) are deleted — `merge_stores` replaces them. The watcher's mtime check is kept purely as a cheap "did anything change at all" gate before doing the merge work; it is no longer load-bearing for correctness.

### Migration merge — `backend/services/sync_merge.py`

`merge_bookmark_stores` / `merge_route_stores` (used by `migrate_pair` at enable/disable) switch to `merge_stores` so tombstones are honoured during the enable/disable migration too. Same-name category collapse stays.

### Symptom 1 fix — `backend/main.py`

Add a focused `_reload_sync_folder()` that re-reads only `sync_folder` and `cloud_sync_dismissed` from `settings.json`, and call it from `load_state()` — which runs *after* the helper has chowned root-owned files. This is independent of the merge work and could ship on its own.

### Files touched

| File | Responsibility | Change |
|------|----------------|--------|
| `backend/models/schemas.py` | Data models | Add `updated_at`, `Tombstone`, `tombstones` |
| `backend/services/store_merge.py` | Pure merge | **New** — `merge_stores`, tombstone GC |
| `backend/services/bookmark_merge.py` | Old 3-way merge | **Delete** (replaced by `store_merge`) |
| `backend/services/bookmarks.py` | Bookmark CRUD + persistence | Stamp mutations, tombstones, read-merge-write |
| `backend/services/route_store.py` | Route CRUD + persistence | Stamp mutations, tombstones, read-merge-write |
| `backend/services/sync_merge.py` | Migration-time merge | Delegate to `merge_stores` |
| `backend/main.py` | App state / startup | `_reload_sync_folder()` in `load_state()` |
| `backend/tests/test_store_merge.py` | Merge unit tests | **New** |
| `backend/tests/test_bookmark_concurrency.py` | Concurrency tests | Update for new merge semantics |
| `backend/tests/test_sync_merge.py` | Migration merge tests | Update for timestamp LWW |
| `backend/tests/test_route_watcher.py` | Route watcher tests | Update for merge-on-reconcile |
| `backend/tests/test_appstate_sync_migration.py` | Startup sync tests | Add symptom-1 regression test |

---

## Implementation Tasks

### Task 1: Schema — `updated_at`, `Tombstone`, `tombstones`

**Files:**
- Modify: `backend/models/schemas.py` (`Bookmark`, `BookmarkCategory`, `RouteCategory`, `BookmarkStore`, `RouteStore`; add `Tombstone`)
- Test: `backend/tests/test_store_merge.py` (new — schema smoke only here)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_store_merge.py
from models.schemas import (
    Bookmark, BookmarkCategory, BookmarkStore,
    RouteCategory, RouteStore, SavedRoute, Tombstone,
)


def test_schema_defaults_are_backward_compatible():
    # Old JSON has no updated_at / tombstones — must still load.
    bs = BookmarkStore(**{"categories": [{"name": "X"}], "bookmarks": []})
    assert bs.tombstones == []
    assert bs.categories[0].updated_at == ""
    rs = RouteStore(**{"categories": [], "routes": []})
    assert rs.tombstones == []


def test_tombstone_model_roundtrips():
    t = Tombstone(id="abc", kind="bookmark", deleted_at="2026-05-14T00:00:00+00:00")
    assert Tombstone(**t.model_dump()) == t
```

- [ ] **Step 2: Run test, verify it fails**

Run: `backend/.venv/bin/python -m pytest tests/test_store_merge.py -v`
Expected: FAIL — `ImportError: cannot import name 'Tombstone'`.

- [ ] **Step 3: Implement the schema changes**

In `backend/models/schemas.py`:

```python
class Tombstone(BaseModel):
    id: str
    kind: str  # "bookmark" | "category" | "route"
    deleted_at: str  # ISO 8601
```

Add `updated_at: str = ""` to `Bookmark`, `BookmarkCategory`, `RouteCategory`.
Add `tombstones: list[Tombstone] = []` to `BookmarkStore` and `RouteStore`.

- [ ] **Step 4: Run test, verify it passes**

Run: `backend/.venv/bin/python -m pytest tests/test_store_merge.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/models/schemas.py backend/tests/test_store_merge.py
git commit -m "feat(sync): add updated_at + Tombstone schema for conflict-free merge"
```

---

### Task 2: Pure `merge_stores` — commutative LWW + tombstones

**Files:**
- Create: `backend/services/store_merge.py`
- Test: `backend/tests/test_store_merge.py` (extend)

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_store_merge.py
from services.store_merge import merge_stores, TOMBSTONE_RETENTION_DAYS
from datetime import datetime, timedelta, timezone


def _bm(id, name, updated_at, cat="default"):
    return Bookmark(id=id, name=name, lat=0, lng=0, category_id=cat, updated_at=updated_at)


def _store(bms=(), cats=(), tombs=()):
    return BookmarkStore(bookmarks=list(bms), categories=list(cats), tombstones=list(tombs))


def test_merge_unions_distinct_ids():
    a = _store(bms=[_bm("1", "A", "2026-05-14T01:00:00+00:00")])
    b = _store(bms=[_bm("2", "B", "2026-05-14T01:00:00+00:00")])
    merged = merge_stores(a, b)
    assert {x.id for x in merged.bookmarks} == {"1", "2"}


def test_merge_newer_updated_at_wins_on_collision():
    old = _bm("1", "old", "2026-05-14T01:00:00+00:00")
    new = _bm("1", "new", "2026-05-14T05:00:00+00:00")
    assert merge_stores(_store(bms=[old]), _store(bms=[new])).bookmarks[0].name == "new"
    # commutative — same result regardless of argument order
    assert merge_stores(_store(bms=[new]), _store(bms=[old])).bookmarks[0].name == "new"


def test_merge_is_commutative_and_idempotent():
    a = _store(bms=[_bm("1", "A", "2026-05-14T01:00:00+00:00")])
    b = _store(bms=[_bm("2", "B", "2026-05-14T02:00:00+00:00")])
    assert merge_stores(a, b).model_dump() == merge_stores(b, a).model_dump()
    assert merge_stores(a, a).model_dump() == a.model_dump()


def test_tombstone_suppresses_older_item():
    item = _bm("1", "doomed", "2026-05-14T01:00:00+00:00")
    tomb = Tombstone(id="1", kind="bookmark", deleted_at="2026-05-14T03:00:00+00:00")
    merged = merge_stores(_store(bms=[item]), _store(tombs=[tomb]))
    assert merged.bookmarks == []


def test_edit_after_delete_resurrects_item():
    # Item edited AFTER the tombstone — the live edit out-votes the delete.
    item = _bm("1", "revived", "2026-05-14T05:00:00+00:00")
    tomb = Tombstone(id="1", kind="bookmark", deleted_at="2026-05-14T03:00:00+00:00")
    merged = merge_stores(_store(bms=[item]), _store(tombs=[tomb]))
    assert [x.name for x in merged.bookmarks] == ["revived"]


def test_old_tombstones_are_garbage_collected():
    stale = (datetime.now(timezone.utc) - timedelta(days=TOMBSTONE_RETENTION_DAYS + 1)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    merged = merge_stores(
        _store(tombs=[Tombstone(id="old", kind="bookmark", deleted_at=stale)]),
        _store(tombs=[Tombstone(id="new", kind="bookmark", deleted_at=fresh)]),
    )
    assert {t.id for t in merged.tombstones} == {"new"}


def test_missing_updated_at_loses_to_stamped_copy():
    legacy = _bm("1", "legacy", "")          # pre-upgrade item, no timestamp
    stamped = _bm("1", "stamped", "2026-05-14T01:00:00+00:00")
    assert merge_stores(_store(bms=[legacy]), _store(bms=[stamped])).bookmarks[0].name == "stamped"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `backend/.venv/bin/python -m pytest tests/test_store_merge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.store_merge'`.

- [ ] **Step 3: Implement `store_merge.py`**

```python
# backend/services/store_merge.py
"""Commutative, idempotent merge for cloud-synced stores.

LWW-element-set semantics:
  - items unioned by id; newer ``updated_at`` wins a collision
  - tombstones suppress an item iff deleted_at >= item.updated_at
  - tombstones older than TOMBSTONE_RETENTION_DAYS are dropped

No I/O, no logging. merge_stores(a, b) == merge_stores(b, a); merge_stores(a, a) == a.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TypeVar

from models.schemas import BookmarkStore, RouteStore, Tombstone

TOMBSTONE_RETENTION_DAYS = 30

StoreT = TypeVar("StoreT", BookmarkStore, RouteStore)


def _items_attr(store) -> str:
    return "bookmarks" if isinstance(store, BookmarkStore) else "routes"


def _newer(a_ts: str, b_ts: str) -> bool:
    """True if a_ts is strictly newer than b_ts. Empty string sorts oldest."""
    return (a_ts or "") > (b_ts or "")


def _union_by_id(left: list, right: list) -> list:
    out: dict[str, object] = {}
    for item in list(left) + list(right):
        existing = out.get(item.id)
        if existing is None or _newer(item.updated_at, existing.updated_at):
            out[item.id] = item
    return list(out.values())


def _merge_tombstones(left: list[Tombstone], right: list[Tombstone]) -> list[Tombstone]:
    out: dict[str, Tombstone] = {}
    for t in list(left) + list(right):
        existing = out.get(t.id)
        if existing is None or _newer(t.deleted_at, existing.deleted_at):
            out[t.id] = t
    cutoff = (datetime.now(timezone.utc) - timedelta(days=TOMBSTONE_RETENTION_DAYS)).isoformat()
    return [t for t in out.values() if t.deleted_at >= cutoff]


def merge_stores(a: StoreT, b: StoreT) -> StoreT:
    items_attr = _items_attr(a)
    categories = _union_by_id(a.categories, b.categories)
    items = _union_by_id(getattr(a, items_attr), getattr(b, items_attr))
    tombstones = _merge_tombstones(a.tombstones, b.tombstones)

    tomb_by_id = {t.id: t.deleted_at for t in tombstones}

    def _alive(obj) -> bool:
        ts = tomb_by_id.get(obj.id)
        # tombstone wins iff the delete is at-or-after the item's last edit
        return ts is None or not (ts >= (obj.updated_at or ""))

    categories = [c for c in categories if _alive(c)]
    items = [i for i in items if _alive(i)]

    store_cls = type(a)
    return store_cls(**{
        "categories": categories,
        items_attr: items,
        "tombstones": tombstones,
    })
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `backend/.venv/bin/python -m pytest tests/test_store_merge.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/store_merge.py backend/tests/test_store_merge.py
git commit -m "feat(sync): add commutative merge_stores with tombstone LWW"
```

---

### Task 3: BookmarkManager — stamp mutations, emit tombstones

**Files:**
- Modify: `backend/services/bookmarks.py` (`create_bookmark`, `update_bookmark`, `move_bookmarks`, `create_category`, `update_category`, `delete_bookmark`, `delete_category`)
- Test: `backend/tests/test_bookmark_tombstones.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_bookmark_tombstones.py
import pytest
from services.bookmarks import BookmarkManager


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", object())
    return BookmarkManager()


def test_create_bookmark_stamps_updated_at(mgr):
    bm = mgr.create_bookmark("Pin", 1.0, 2.0)
    assert bm.updated_at != ""


def test_update_bookmark_advances_updated_at(mgr):
    bm = mgr.create_bookmark("Pin", 1.0, 2.0)
    first = bm.updated_at
    updated = mgr.update_bookmark(bm.id, name="Renamed")
    assert updated.updated_at >= first and updated.name == "Renamed"


def test_delete_bookmark_emits_tombstone(mgr):
    bm = mgr.create_bookmark("Pin", 1.0, 2.0)
    mgr.delete_bookmark(bm.id)
    assert any(t.id == bm.id and t.kind == "bookmark" for t in mgr.store.tombstones)
    assert all(b.id != bm.id for b in mgr.store.bookmarks)


def test_delete_category_emits_tombstone(mgr):
    cat = mgr.create_category("Trip")
    mgr.delete_category(cat.id)
    assert any(t.id == cat.id and t.kind == "category" for t in mgr.store.tombstones)


def test_create_category_stamps_updated_at(mgr):
    cat = mgr.create_category("Trip")
    assert cat.updated_at != ""
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `backend/.venv/bin/python -m pytest tests/test_bookmark_tombstones.py -v`
Expected: FAIL — `updated_at` is `""`, no tombstones appended.

- [ ] **Step 3: Implement stamping + tombstones**

In `backend/services/bookmarks.py`, add a helper and wire it in:

```python
from models.schemas import Tombstone  # add to imports

def _tombstone(obj_id: str, kind: str) -> Tombstone:
    return Tombstone(id=obj_id, kind=kind, deleted_at=_now_iso())
```

- `create_bookmark`: set `updated_at=now` in the `Bookmark(...)` constructor (alongside `created_at`).
- `update_bookmark`: after applying `kwargs`, set `bm.updated_at = _now_iso()`.
- `move_bookmarks`: for each moved bookmark, set `bm.updated_at = _now_iso()`.
- `create_category`: set `updated_at=_now_iso()` in the `BookmarkCategory(...)` constructor.
- `update_category`: after applying fields, set `cat.updated_at = _now_iso()`.
- `delete_bookmark`: before `_save()`, `self.store.tombstones.append(_tombstone(bm_id, "bookmark"))`.
- `delete_category`: before `_save()`, `self.store.tombstones.append(_tombstone(cat_id, "category"))`; in the non-cascade branch, also set `bm.updated_at = _now_iso()` on each reparented bookmark.

- [ ] **Step 4: Run tests, verify they pass**

Run: `backend/.venv/bin/python -m pytest tests/test_bookmark_tombstones.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmarks.py backend/tests/test_bookmark_tombstones.py
git commit -m "feat(sync): stamp updated_at and emit tombstones on bookmark mutations"
```

---

### Task 4: BookmarkManager — read-merge-write on save and reconcile

**Files:**
- Modify: `backend/services/bookmarks.py` (`_save`, `_reconcile_from_disk`; drop `bookmark_merge` import)
- Delete: `backend/services/bookmark_merge.py`
- Test: `backend/tests/test_bookmark_concurrency.py` (update existing)

- [ ] **Step 1: Update the failing tests**

Rewrite `test_bookmark_concurrency.py` cases that asserted the old conditional-merge behaviour. The new contract:

```python
def test_save_merges_concurrent_external_addition(tmp_path, monkeypatch):
    # Two managers on the same file; each adds a distinct bookmark.
    # After both save, the file must contain BOTH (no clobber).
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", object())
    from services.bookmarks import BookmarkManager
    a = BookmarkManager()
    b = BookmarkManager()
    a.create_bookmark("from-A", 1.0, 1.0)   # a._save() writes file
    b.create_bookmark("from-B", 2.0, 2.0)   # b._save() must read-merge-write, keeping from-A
    names = {bm.name for bm in BookmarkManager().list_bookmarks()}
    assert names == {"from-A", "from-B"}


def test_delete_propagates_and_does_not_resurrect(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", object())
    from services.bookmarks import BookmarkManager
    a = BookmarkManager()
    cat = a.create_category("Trip")
    b = BookmarkManager()                    # b loads the file, also has "Trip"
    a.delete_category(cat.id)                # a writes file w/ tombstone
    b.create_bookmark("unrelated", 1.0, 1.0) # b read-merge-writes; tombstone must survive
    cats = {c.id for c in BookmarkManager().list_categories()}
    assert cat.id not in cats
```

Keep `test_two_managers_on_same_file_converge` (should still pass). Remove `test_save_does_not_merge_when_disk_unchanged` (premise no longer holds — save always merges; merging unchanged disk is a verified no-op covered by `test_merge_is_commutative_and_idempotent`).

- [ ] **Step 2: Run tests, verify they fail**

Run: `backend/.venv/bin/python -m pytest tests/test_bookmark_concurrency.py -v`
Expected: FAIL — `test_save_merges_concurrent_external_addition` loses `from-A`.

- [ ] **Step 3: Implement read-merge-write**

In `backend/services/bookmarks.py`:
- Replace the `from services.bookmark_merge import diff_store, merge_local_wins` import with `from services.store_merge import merge_stores`.
- Add a tolerant loader:

```python
def _load_store_or_empty(path: Path) -> BookmarkStore:
    raw = safe_load_json(path)
    if not isinstance(raw, dict):
        return BookmarkStore(categories=[], bookmarks=[], tombstones=[])
    try:
        return BookmarkStore(**raw)
    except Exception:
        return BookmarkStore(categories=[], bookmarks=[], tombstones=[])
```

- Rewrite `_save`:

```python
def _save(self) -> None:
    path = self._bookmarks_path()
    disk = _load_store_or_empty(path)
    self.store = merge_stores(self.store, disk)
    safe_write_json(path, json.loads(self.store.model_dump_json()))
    self._update_snapshot()
```

- Rewrite `_reconcile_from_disk`:

```python
def _reconcile_from_disk(self) -> None:
    path = self._bookmarks_path()
    try:
        if path.stat().st_size == 0:
            return
    except FileNotFoundError:
        return
    self.store = merge_stores(self.store, _load_store_or_empty(path))
```

- `delete bookmark_merge.py`: `git rm backend/services/bookmark_merge.py`.

- [ ] **Step 4: Run the bookmark suite, verify it passes**

Run: `backend/.venv/bin/python -m pytest tests/test_bookmark_concurrency.py tests/test_bookmark_tombstones.py tests/test_bookmarks_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmarks.py backend/tests/test_bookmark_concurrency.py
git rm backend/services/bookmark_merge.py
git commit -m "fix(sync): read-merge-write on bookmark save/reconcile (fixes clobber + zombie delete)"
```

---

### Task 5: RouteManager — stamp mutations, emit tombstones

**Files:**
- Modify: `backend/services/route_store.py` (route create/update/delete, category create/update/delete, move)
- Test: `backend/tests/test_route_tombstones.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_route_tombstones.py
import pytest
from services.route_store import RouteManager
from models.schemas import Coordinate


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
    return RouteManager()


def _wp():
    return [Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)]


def test_save_route_stamps_updated_at(mgr):
    r = mgr.save_route("R", _wp(), "walking")
    assert r.updated_at != ""


def test_delete_route_emits_tombstone(mgr):
    r = mgr.save_route("R", _wp(), "walking")
    mgr.delete_route(r.id)
    assert any(t.id == r.id and t.kind == "route" for t in mgr.store.tombstones)


def test_delete_route_category_emits_tombstone(mgr):
    cat = mgr.create_category("Trip")
    mgr.delete_category(cat.id)
    assert any(t.id == cat.id and t.kind == "category" for t in mgr.store.tombstones)
```

(Adjust method names — `save_route` / `create_category` / `delete_route` / `delete_category` — to the actual `RouteManager` API; verify against `backend/services/route_store.py` before writing.)

- [ ] **Step 2: Run tests, verify they fail**

Run: `backend/.venv/bin/python -m pytest tests/test_route_tombstones.py -v`
Expected: FAIL — no `updated_at` stamping, no tombstones.

- [ ] **Step 3: Implement stamping + tombstones**

Mirror Task 3 in `route_store.py`: stamp `updated_at = _now_iso()` on every route/category create/update/move; on every route/category delete append `Tombstone(id=..., kind="route"|"category", deleted_at=_now_iso())` before `_save()`.

- [ ] **Step 4: Run tests, verify they pass**

Run: `backend/.venv/bin/python -m pytest tests/test_route_tombstones.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/route_store.py backend/tests/test_route_tombstones.py
git commit -m "feat(sync): stamp updated_at and emit tombstones on route mutations"
```

---

### Task 6: RouteManager — read-merge-write on save and reconcile

**Files:**
- Modify: `backend/services/route_store.py` (`_save`, `_watcher_tick`, add `_load_store_or_empty`)
- Test: `backend/tests/test_route_watcher.py` (update), `backend/tests/test_route_store.py` (verify still green)

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_route_watcher.py
def test_two_route_managers_converge_without_clobber(tmp_path, monkeypatch):
    monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
    from services.route_store import RouteManager
    from models.schemas import Coordinate
    wp = [Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)]
    a = RouteManager()
    b = RouteManager()
    a.save_route("from-A", wp, "walking")
    b.save_route("from-B", wp, "walking")
    names = {r.name for r in RouteManager().list_routes()}
    assert names == {"from-A", "from-B"}
```

- [ ] **Step 2: Run test, verify it fails**

Run: `backend/.venv/bin/python -m pytest tests/test_route_watcher.py::test_two_route_managers_converge_without_clobber -v`
Expected: FAIL — `from-A` clobbered (route `_save` blindly overwrites).

- [ ] **Step 3: Implement read-merge-write**

In `backend/services/route_store.py`, add a `_load_store_or_empty` mirroring Task 4 (returning `RouteStore`), then:

```python
def _save(self) -> None:
    path = self._routes_path()
    disk = _load_store_or_empty(path)
    self.store = merge_stores(self.store, disk)
    safe_write_json(path, json.loads(self.store.model_dump_json()))
    self._last_loaded_mtime = self._stat_mtime()
```

Rewrite `_watcher_tick` to merge instead of `self._load()` (whole-file replace):

```python
def _watcher_tick(self) -> None:
    try:
        path = self._routes_path()
        try:
            current_mtime = path.stat().st_mtime
        except FileNotFoundError:
            return
        if current_mtime <= self._last_loaded_mtime:
            return
        before = self.store.model_dump_json()
        self.store = merge_stores(self.store, _load_store_or_empty(path))
        self._last_loaded_mtime = current_mtime
        if self.store.model_dump_json() != before and self._on_external_change is not None:
            try:
                self._on_external_change()
            except Exception:
                logger.exception("Route on_external_change callback raised")
    except Exception:
        logger.exception("Route watcher tick failed")
```

Add `from services.store_merge import merge_stores` to imports.

- [ ] **Step 4: Run the route suite, verify it passes**

Run: `backend/.venv/bin/python -m pytest tests/test_route_watcher.py tests/test_route_store.py tests/test_route_tombstones.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/route_store.py backend/tests/test_route_watcher.py
git commit -m "fix(sync): read-merge-write on route save/reconcile (fixes clobber + zombie delete)"
```

---

### Task 7: Migration merge delegates to `merge_stores`

**Files:**
- Modify: `backend/services/sync_merge.py` (`merge_bookmark_stores`, `merge_route_stores`)
- Test: `backend/tests/test_sync_merge.py` (update)

- [ ] **Step 1: Update the failing tests**

`test_sync_merge.py`'s `test_merge_*_local_wins_on_conflict` cases assert "local wins" unconditionally. Under timestamp LWW, the *newer* copy wins. Update those two tests to stamp `updated_at` and assert the newer-timestamp copy wins. Add:

```python
def test_migration_merge_respects_tombstones(tmp_path):
    # remote has a tombstone for an id local still carries (older) → stays deleted
    from services.sync_merge import merge_bookmark_stores
    import json
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    local.write_text(json.dumps({
        "categories": [], "tombstones": [],
        "bookmarks": [{"id": "1", "name": "stale", "lat": 0, "lng": 0,
                       "category_id": "default", "updated_at": "2026-05-14T01:00:00+00:00"}],
    }))
    remote.write_text(json.dumps({
        "categories": [], "bookmarks": [],
        "tombstones": [{"id": "1", "kind": "bookmark", "deleted_at": "2026-05-14T03:00:00+00:00"}],
    }))
    merge_bookmark_stores(local, remote)
    assert json.loads(remote.read_text())["bookmarks"] == []
```

Keep `test_merge_*_union`, `test_merge_*_collapses_same_name_categories`, `test_merge_bookmark_stores_skips_on_parse_failure` — same-name collapse and parse-failure guards are unchanged.

- [ ] **Step 2: Run tests, verify they fail**

Run: `backend/.venv/bin/python -m pytest tests/test_sync_merge.py -v`
Expected: FAIL — `test_migration_merge_respects_tombstones` (tombstones ignored by old payload merge).

- [ ] **Step 3: Implement**

In `backend/services/sync_merge.py`, change `_merge_bookmark_payload` / `_merge_route_payload` to call `merge_stores` for the union step, then apply the existing `_build_category_remap` same-name collapse on the merged result. The public `merge_bookmark_stores` / `merge_route_stores` signatures and parse-failure guards stay identical.

- [ ] **Step 4: Run tests, verify they pass**

Run: `backend/.venv/bin/python -m pytest tests/test_sync_merge.py tests/test_migrate_pair.py tests/test_cloud_sync_unified_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/sync_merge.py backend/tests/test_sync_merge.py
git commit -m "fix(sync): migration merge honours tombstones via merge_stores"
```

---

### Task 8: Symptom 1 — re-read sync folder after the chown

**Files:**
- Modify: `backend/main.py` (`AppState`: add `_reload_sync_folder`; call it in `load_state`)
- Test: `backend/tests/test_appstate_sync_migration.py` (add regression test)

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_appstate_sync_migration.py
def test_load_state_rereads_sync_folder_after_init(tmp_path, monkeypatch):
    """Reproduces symptom 1: settings.json unreadable at __init__ time
    (root-owned, pre-chown) but readable by the time load_state runs."""
    import json, asyncio
    settings = tmp_path / "settings.json"
    monkeypatch.setattr("main.SETTINGS_FILE", settings)
    monkeypatch.setattr("config.SETTINGS_FILE", settings)
    from main import AppState
    app = AppState()                       # settings.json absent → _sync_folder None
    assert app._sync_folder is None
    sync_dir = tmp_path / "LocWarp"
    sync_dir.mkdir()
    settings.write_text(json.dumps({"sync_folder": str(sync_dir)}))  # "chowned" / now readable
    asyncio.get_event_loop().run_until_complete(app.load_state())
    assert app._sync_folder == str(sync_dir)
```

- [ ] **Step 2: Run test, verify it fails**

Run: `backend/.venv/bin/python -m pytest tests/test_appstate_sync_migration.py::test_load_state_rereads_sync_folder_after_init -v`
Expected: FAIL — `_sync_folder` still `None` after `load_state()`.

- [ ] **Step 3: Implement**

In `backend/main.py`, add to `AppState`:

```python
def _reload_sync_folder(self) -> None:
    """Re-read sync_folder + cloud_sync_dismissed from settings.json.

    Called from load_state(), which runs AFTER the elevated helper has
    chowned root-owned ~/.locwarp/ files back to the user. _load_persisted_state()
    runs at import time — before that chown — so a root-owned settings.json
    is unreadable then and _sync_folder latches to None. This re-read recovers it.
    """
    from services.json_safe import safe_load_json
    data = safe_load_json(SETTINGS_FILE)
    if not isinstance(data, dict):
        return
    sf = data.get("sync_folder")
    if isinstance(sf, str) and sf:
        self._sync_folder = sf
    cdsm = data.get("cloud_sync_dismissed")
    if isinstance(cdsm, bool):
        self._cloud_sync_dismissed = cdsm
```

Call it at the top of `load_state()`:

```python
async def load_state(self) -> None:
    self._reload_sync_folder()
    self._load_settings()
    self.bookmark_manager = BookmarkManager()
    self.route_manager = RouteManager()
```

- [ ] **Step 4: Run test, verify it passes**

Run: `backend/.venv/bin/python -m pytest tests/test_appstate_sync_migration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_appstate_sync_migration.py
git commit -m "fix(sync): re-read sync_folder in load_state so toggle survives root-owned settings"
```

---

### Task 9: Full suite + manual two-machine verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire backend suite**

Run: `backend/.venv/bin/python -m pytest`
Expected: PASS — all tests, no regressions. Fix any fallout from removed `bookmark_merge.py` / changed merge semantics.

- [ ] **Step 2: Manual two-machine smoke (Ravi)**

With iCloud sync enabled on machines A and B:
1. Rebuild on each — confirm the toggle stays ON (symptom 1).
2. Add a bookmark on A and a different one on B within the same minute — confirm both survive on both machines after sync settles (symptom 2).
3. Delete a category on A — confirm it stays deleted on B and does not reappear after B makes an unrelated edit (symptom 3).

- [ ] **Step 3: Commit any test fixes**

```bash
git add -A
git commit -m "test(sync): align suite with tombstone merge semantics"
```

---

## Self-Review

**Spec coverage:** Symptom 1 → Task 8. Symptom 2 (clobber) → Tasks 4, 6 (read-merge-write) backed by Task 2 (commutative merge). Symptom 3 (zombie delete) → Tasks 3, 5 (tombstone emission) + Task 2 (tombstone suppression) + Tasks 4, 6, 7 (merge applied everywhere). Routes covered alongside bookmarks in Tasks 5, 6. Migration path covered in Task 7.

**Open items to verify during execution (not placeholders — confirm against code):**
- Task 5 method names: confirm `RouteManager`'s actual create/update/delete/move method names against `backend/services/route_store.py` before writing tests.
- Task 4: confirm whether any other module imports `services.bookmark_merge` before deleting it (`grep -rn bookmark_merge backend/`).
- Task 1: confirm `Coordinate` and `SavedRoute` field names used in route tests against `backend/models/schemas.py`.

**Type consistency:** `merge_stores(a, b)` is used identically in Tasks 4, 6, 7. `_load_store_or_empty` is defined per-manager (returns the manager's own store type). `Tombstone(id, kind, deleted_at)` is constructed consistently in Tasks 3, 5 and consumed in Task 2.

**Known limitation (accepted):** Wall-clock skew between machines can mis-order two edits to the *same* item made within the skew window. Acceptable for single-user / few-machines / rarely-simultaneous use. If it ever bites, harden `updated_at` into a hybrid logical clock — additive, no format break.
