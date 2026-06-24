# Clean-Arch Phase 4a — Repository around the CRDT store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Invert the **file-I/O** half of `BookmarkManager`/`RouteManager` behind `BookmarkRepository`/`RouteRepository` Protocols (domain ports) implemented by a generic `infra/persistence/json_store.py` constructed at the composition root; move the pure `merge_stores` CRDT rule into `domain/`; and add a shared `force_seed` primitive that encodes the empty-`updated_at` tombstone pitfall — with zero external behavior change.

**Architecture:** Pragmatic Hexagonal-lite (spec §4.1, §4.4). **Phase 4a (backend only)** — frontend god-component decomposition (P4b) is a separate later design+plan cycle (owner decision 2026-06-22). The repo owns ONLY pure I/O (`load`/`load_or_empty`/`save`/`path`). The managers keep CRUD/business **and the watcher state machine + `_store_lock` + mtime** — they call the injected repo for disk ops. The repo is a **required, injected** Protocol arg built at the 3 composition sites (true inversion: services depends on the domain Protocol, never imports infra).

**Tech Stack:** Python 3.13, pytest + pytest-asyncio, import-linter (`lint-imports`), pydantic, watchdog, threading.

> **This plan was adversarially reviewed (4-agent workflow, 2026-06-22) BEFORE execution.** The review caught three Criticals that reshaped it: the RouteManager lock was YAGNI (the route watcher never writes to disk → no race; **dropped**); moving the watcher into the repo broke test reach-ins + flattened divergent watcher bodies (**watcher stays on the managers**); and a manager-default-constructs-repo path was a `services→infra` ring violation (**repo is required-injected, built at the composition root, with an adapter-layer factory for test constructions**). Owner approved the full clean inversion + dropping the lock.

## Global Constraints

Every task's requirements implicitly include this section.

- **Behavior / API freeze.** No external HTTP / WS / IPC change. WS/HTTP payloads stay deep-equal JSON (`exclude_unset`/`exclude_none`). The full backend pytest suite stays green after **EVERY** commit. Pin the baseline first: `cd backend && .venv/bin/python -m pytest --collect-only -q | tail -1` (currently **871**; grows only by added tests — never let an existing test drop or change assertion). Any store's `model_dump`/`model_dump_json` output stays byte-equal.
- **No sanctioned behavior change.** Unlike P0–P3, P4a has NONE — it is a pure structural inversion. (The RouteManager lock that would have been the one change is dropped as YAGNI.)
- **Verbatim relocation, bit-exact.** `merge_stores` + helpers + `TOMBSTONE_RETENTION_DAYS` move byte-identical to `domain/store_merge.py`. The file-I/O primitives move byte-identical into `JsonStore` (only `self._bookmarks_path()` → `self._path_provider()` rebinds). No CRDT-math edit. The empty-`updated_at` pitfall is load-bearing in BOTH `_newer` and `_alive`'s `(obj.updated_at or "")` — preserve both exactly.
- **Watcher + lock + mtime STAY on the managers.** Do NOT move `_watcher_tick`/`_reconcile_from_disk`/`_schedule_reconcile`/`_last_loaded_mtime`/`_on_external_change`/`_record_disk_mtime`/`_stat_mtime`/`_store_lock`/`start_watcher`/`stop_watcher` into the repo. Existing tests reach into these on the MANAGER (`mgr._watcher_tick = ...`, `mgr._last_loaded_mtime`, `mgr._reconcile_from_disk()`), and the two managers' `_watcher_tick` bodies differ materially (bookmark writes back to disk + has a zero-byte guard; route does neither). Each manager keeps its OWN `_watcher_tick`, now calling `self._repo.save()` / `self._repo.load_or_empty()` / `self._repo.path()` instead of inlined file ops. The `_store_lock` (BookmarkManager only) keeps owning the full read-merge-write; `on_external_change` fires OUTSIDE the lock.
- **Repo is REQUIRED + injected (no services→infra import).** `BookmarkManager`/`RouteManager` take `repo: BookmarkRepository`/`RouteRepository` (domain Protocol) as a required ctor arg. They import ONLY `domain.ports`, never `infra.persistence`. The concrete `JsonStore` is built at the 3 composition sites + an adapter-layer factory (`make_bookmark_manager`/`make_route_manager`) used by tests. The `path_provider` callable is supplied by the factory/manager module so the `services.bookmarks.BOOKMARKS_FILE` / `services.route_store.ROUTES_FILE` monkeypatch seam (≈16 test fixtures patch those module attrs) stays intact.
- **Thin facade (owner decision).** Managers keep `self.store`, a `save()` passthrough, and `_bookmarks_path()`/`_routes_path()` (→ `repo.path()`) — the 3 reach-ins stay unchanged: `services/bookmark_import.py` (mutates `manager.store` + `manager._save()`), `services/cloud_sync_service.py:48` (`bm._bookmarks_path()`), `api/bookmarks.py:192` (`bm.store` export).
- **`merge_stores` home (owner-approved deviation from spec §4.4-literal):** the pure rule goes in **`domain/store_merge.py`** (consistent with P3's `domain/movement.py`; `models` is allowed under `no-domain-imports-outer`), NOT `infra/persistence`. The I/O repo CALLS the domain rule.
- **DEFERRED — out of scope:** P4b frontend; the RouteManager lock (no demonstrated race — documented); moving `services/json_safe.py`/`services/file_watcher.py` into infra (infra→services is a legal inward edge — leave them, note as tidy-up); route catalog/force-seed parity (no route catalog — the `force_seed_items` primitive is shared/available but unused for routes; YAGNI); `sync_merge`'s same-name-category collapse (stays a migration use-case in services).
- **Git:** branch `chore/clean-arch-p4a` off `main`. Personal repo, direct-to-branch commits, identity auto-set (never `-c user.email`). Merge after a real-data smoke (Task 8).

---

## File Structure

| File | Responsibility | Tasks |
|------|----------------|-------|
| `backend/domain/store_merge.py` | **NEW** pure CRDT rule: `merge_stores` + helpers + `TOMBSTONE_RETENTION_DAYS` (verbatim) + the pure `force_seed_items` stamping primitive. stdlib + models only. | 2, 6 |
| `backend/services/store_merge.py` | Re-export shim (`merge_stores`, `TOMBSTONE_RETENTION_DAYS`) — preserves the **5** importers (2 managers, sync_merge, merge_backup, test_store_merge). | 2 |
| `backend/domain/ports/bookmark_repository.py`, `route_repository.py` | **NEW** thin repo Protocols: `load()`/`load_or_empty()`/`save(store)`/`path()`. | 3 |
| `backend/infra/persistence/__init__.py`, `json_store.py` | **NEW** generic `JsonStore` (params: `store_cls`, `path_provider`, `post_load`) implementing both Protocols. Pure file I/O + the read-merge-write in `save`. NO watcher, NO lock. | 4 |
| `backend/services/bookmarks.py`, `route_store.py` | Managers take an injected `repo`; `_load`/`_save`/`_bookmarks_path` become facade passthroughs; `_watcher_tick` keeps its own body but calls repo methods; lock/mtime/watcher stay. | 4 |
| `backend/bootstrap/factories.py` (or `infra/persistence/__init__.py`) | **NEW** `make_bookmark_manager(path_provider=None)` / `make_route_manager(...)` building `JsonStore` + manager — used by main.py, cloud_sync, and tests. | 5 |
| `backend/main.py`, `backend/services/cloud_sync_service.py` | Build the repo (via factory) at the 3 manager-construction sites. | 5 |
| ~12 test files constructing `BookmarkManager()`/`RouteManager()` | Switch to the factory (or a conftest fixture). | 5 |
| `backend/.importlinter` + `backend/tests/test_import_contracts_enforced.py` | Add `no-infra-imports-fastapi` (7th contract). | 7 |
| `backend/tests/test_gc_through_save.py`, `test_force_seed.py`, route default-injection test | **NEW** nets. | 1, 6 |

---

## Decisions baked in (owner-approved 2026-06-22, post-review)

1. **Scope:** backend repository only. P4b frontend = separate later cycle.
2. **RouteManager lock: DROPPED** — adversarial review empirically disproved the race (route `_watcher_tick` never writes to disk; only `_save` does, single-threaded on the event loop). Document the asymmetry; no lock, no vacuous test.
3. **Repo: full clean inversion** — required-injected Protocol, composition-root construction, adapter factory, ~12 test call-sites migrated. Watcher/lock/mtime stay on managers.
4. **force_seed:** NEW shared `force_seed_items(items, now_iso)` primitive (PARTIAL extraction — see Task 6) + a `force_seed` manager method; `import_catalog` uses it. Test-first, asserting on-disk, driving the NEW method.
5. **Thin facade:** managers keep `.store`/`.save()`/`.path()`; 3 reach-ins untouched.
6. **merge_stores → `domain/`** (approved deviation from spec §4.4).

---

### Task 1: Pin the relocation-fragile seams test-first

Three nets that guard the Task 4 I/O move (the test audit found these gaps).

**Files:**
- Create: `backend/tests/test_gc_through_save.py`
- Modify: `backend/tests/test_bookmark_concurrency.py` (pin the real watcher handler)
- Modify/Create: a route legacy-default-injection test (extend `test_route_store.py` or new file)

- [ ] **Step 1: GC-through-`_save` integration net**

Create `backend/tests/test_gc_through_save.py`: append a stale `Tombstone(deleted_at = (now - (TOMBSTONE_RETENTION_DAYS+1) days).isoformat())` to a manager's store, trigger `_save()` (e.g. via `create_bookmark`), then assert the stale id is ABSENT from `json.loads(path.read_text())["tombstones"]`. Read `test_store_merge.py::test_old_tombstones_are_garbage_collected` (stale construction) + `test_bookmark_catalog_sync.py::test_resync_after_delete_resurrects` (on-disk assertion + monkeypatch-path pattern). (Review-confirmed efficacious.)

- [ ] **Step 2: Pin the real watcher handler via `_watcher_schedule` capture**

In `test_bookmark_concurrency.py::test_watcher_handler_triggers_on_moved_to_target`, replace the inline `_Handler` re-implementation: monkeypatch `services.bookmarks._watcher_schedule` to CAPTURE the handler the manager passes, call `start_watcher(...)`, then fire `captured_handler.on_moved(fake_event)` and assert reconcile fired. (Review-verified: captures the real nested `_Handler`, fails if it relocates, no real Observer / no flakiness.)

- [ ] **Step 3: Route legacy default-category injection net**

Add a test (extend `test_route_store.py`): load a legacy `{"routes":[{... category_id: "ghost"}]}` file with NO categories, assert `list_categories()` contains `"default"` and the orphan route was reparented to `"default"`. Also assert the merge snapshot path (`load_or_empty`) does NOT inject a default category (locks the asymmetry the `post_load` hook must preserve in Task 4).

- [ ] **Step 4: Run + full suite + commit**

Run: `cd backend && .venv/bin/python -m pytest tests/test_gc_through_save.py tests/test_bookmark_concurrency.py tests/test_route_store.py -q` → PASS. Full suite green.

```bash
git add backend/tests/test_gc_through_save.py backend/tests/test_bookmark_concurrency.py backend/tests/test_route_store.py
git commit -m "test(persistence): pin GC-through-save, real watcher handler, route default-injection before relocation"
```

---

### Task 2: Move `merge_stores` to `domain/store_merge.py` (verbatim) + shim

**Files:**
- Create: `backend/domain/store_merge.py`
- Modify: `backend/services/store_merge.py` (→ shim)

- [ ] **Step 1: Move the file body verbatim**

Copy the ENTIRE body of `backend/services/store_merge.py` byte-for-byte into `backend/domain/store_merge.py` (docstring, imports, `TOMBSTONE_RETENTION_DAYS`, `_newer`, `_union_by_id`, `_merge_tombstones`, `_alive`, `merge_stores`, `_items_attr`). No edit to math, the `(a or "")` coalescing, or the GC `datetime.now(timezone.utc)`. Imports are stdlib + `models.schemas` — legal under `no-domain-imports-outer`.

- [ ] **Step 2: Replace `services/store_merge.py` with a re-export shim**

```python
"""Re-export shim — the CRDT merge rule moved to domain/store_merge.py (Phase 4a).
Preserves the 5 importers (services/bookmarks.py, services/route_store.py,
services/sync_merge.py, merge_backup.py, tests/test_store_merge.py). Only
test_store_merge.py imports TOMBSTONE_RETENTION_DAYS; the rest import merge_stores."""
from domain.store_merge import merge_stores, TOMBSTONE_RETENTION_DAYS  # noqa: F401

__all__ = ["merge_stores", "TOMBSTONE_RETENTION_DAYS"]
```

Verify shim coverage across the WHOLE backend (not just tests): `grep -rn 'from services.store_merge import' backend` → confirm every importer needs only `merge_stores`/`TOMBSTONE_RETENTION_DAYS` (incl. `merge_backup.py` at repo root, which import-linter does NOT scan).

- [ ] **Step 3: SAFE tests + gate + full suite + commit**

Run: `cd backend && .venv/bin/python -m pytest tests/test_store_merge.py tests/test_bookmark_tombstones.py tests/test_route_tombstones.py tests/test_list_ordering.py tests/test_merge_backup.py -q` → PASS. `.venv/bin/lint-imports` → 6 kept/0 broken. Full suite green.

```bash
git add backend/domain/store_merge.py backend/services/store_merge.py
git commit -m "refactor(domain): move merge_stores CRDT rule to domain/store_merge.py (re-export shim in services)"
```

---

### Task 3: Define the thin repository Protocols in `domain/ports`

**Files:**
- Create: `backend/domain/ports/bookmark_repository.py`, `route_repository.py`; Modify `domain/ports/__init__.py`.

- [ ] **Step 1: Write the Protocols (thin — I/O only)**

`bookmark_repository.py`:

```python
"""Persistence port for the bookmark store (clean-arch Phase 4a).

THIN — pure file I/O. The manager keeps the watcher state machine + the
threading.Lock + mtime, and calls these methods for disk ops:
  load()          -> full read (materialize + parse + post_load)
  load_or_empty() -> the merge-snapshot read (parse only, NO post_load) used by
                     _save / _watcher_tick / _reconcile_from_disk
  save(store)     -> read-merge-write: merge_stores(store, on-disk), write,
                     return merged (the iCloud-clobber guard). No lock here —
                     the manager holds _store_lock across the call.
  path()          -> the resolved file Path (cloud_sync_service reach-in).
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from models.schemas import BookmarkStore


class BookmarkRepository(Protocol):
    def load(self) -> BookmarkStore: ...
    def load_or_empty(self) -> BookmarkStore: ...
    def save(self, store: BookmarkStore) -> BookmarkStore: ...
    def path(self) -> Path: ...
```

`route_repository.py` mirrors it with `RouteStore`.

- [ ] **Step 2: Export + gate + commit**

Add to `domain/ports/__init__.py`. `.venv/bin/lint-imports` → 6 kept/0 broken. Full suite green.

```bash
git add backend/domain/ports/
git commit -m "feat(domain/ports): add thin BookmarkRepository + RouteRepository I/O Protocols"
```

---

### Task 4: Implement `JsonStore` + managers delegate I/O to the injected repo

**Files:**
- Create: `backend/infra/persistence/__init__.py`, `json_store.py`
- Modify: `backend/services/bookmarks.py`, `route_store.py`

- [ ] **Step 1: Write `JsonStore` (move ONLY the I/O primitives, parameterized)**

`infra/persistence/json_store.py`:

```python
class JsonStore:
    """Generic JSON-file repository over a CRDT store (pure I/O).
      store_cls:     BookmarkStore | RouteStore
      path_provider: () -> Path  (stays in the manager module so the
                     BOOKMARKS_FILE/ROUTES_FILE monkeypatch seam is intact)
      post_load:     optional (store) -> store, applied in load() ONLY (NOT
                     load_or_empty) — RouteStore injects the default category +
                     reparents orphans on a full load, never on a merge snapshot.
    """
    def __init__(self, store_cls, path_provider, post_load=None):
        self._store_cls = store_cls
        self._path_provider = path_provider
        self._post_load = post_load

    def path(self): return self._path_provider()

    def load(self):
        from services.cloud_sync import materialize_if_placeholder
        materialize_if_placeholder(self.path())
        data = safe_load_json(self.path())
        store = self._store_cls(**data) if data else self._store_cls()
        return self._post_load(store) if self._post_load else store

    def load_or_empty(self):
        data = safe_load_json(self.path())
        return self._store_cls(**data) if data else self._store_cls()

    def save(self, store):
        path = self.path()
        merged = merge_stores(store, self.load_or_empty())
        safe_write_json(path, json.loads(merged.model_dump_json()))
        return merged
```

(`safe_load_json`/`safe_write_json` from `services.json_safe`, `merge_stores` from `domain.store_merge` — both legal inward edges. Move the EXACT body of the managers' `_load`/`_load_store_or_empty`/`_save` read-merge-write here; preserve the schema-validation try/except + the empty-data fallback.) NOTE: `load()` must reproduce the manager's `_load` exactly (incl. the parse-fail-keeps-defaults behavior); confirm against `bookmarks.py:149-171` / `route_store.py:108-141`.

- [ ] **Step 2: Managers take an injected repo; delegate I/O; keep watcher/lock/mtime**

`BookmarkManager.__init__(self, repo: BookmarkRepository)`: **reorder** so `self._store_lock = threading.Lock()` is created FIRST, then `self._repo = repo`, then `self._load()` (now `self.store = self._repo.load()`). Keep all watcher state (`_last_loaded_mtime`, `_on_external_change`, `_watch`, `_watcher_debounce_timer`). Replace the persistence-method bodies:

```python
    def _load(self): self.store = self._repo.load()
    def _save(self):
        with self._store_lock:
            self.store = self._repo.save(self.store)
            self._record_disk_mtime()
    def _bookmarks_path(self): return self._repo.path()   # keep — cloud_sync reach-in
    def _reconcile_from_disk(self):
        path = self._repo.path()
        try:
            if path.stat().st_size == 0: return
        except FileNotFoundError:
            return
        self.store = merge_stores(self.store, self._repo.load_or_empty())
```

Keep `_watcher_tick` BODY as-is but route its file ops through the repo (`self._bookmarks_path()` → `self._repo.path()`, `_load_store_or_empty(path)` → `self._repo.load_or_empty()`, the write-back → keep its `safe_write_json`/`_record_disk_mtime` OR call `self._repo.save(...)` — preserve the exact write-back + zero-byte-guard + callback-outside-lock behavior; do not flatten). `start_watcher`/`stop_watcher`/`_schedule_reconcile` unchanged. RouteManager symmetric — but its `_watcher_tick` does NOT write back (keep that), passes `post_load=_inject_default_category`, and has NO lock (unchanged — decision 2).

- [ ] **Step 3: Concurrency + watcher + GC + catalog tests + gate + full suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmarks_thread_race.py tests/test_bookmark_concurrency.py tests/test_route_watcher.py tests/test_gc_through_save.py tests/test_bookmark_catalog_sync.py tests/test_route_store.py -q` → PASS. `.venv/bin/lint-imports` → 6 kept/0 broken (and `grep -rn 'from infra' backend/services` → ZERO — no services→infra edge). Full suite green.

- [ ] **Step 4: Commit**

```bash
git add backend/infra/persistence/ backend/services/bookmarks.py backend/services/route_store.py
git commit -m "feat(infra/persistence): JsonStore I/O repo; managers delegate disk ops to the injected port"
```

---

### Task 5: Build the repo at the composition root + factory + migrate test constructions

The real inversion: managers no longer self-construct persistence. Build `JsonStore` at the 3 sites + an adapter factory; repoint test `BookmarkManager()`/`RouteManager()` calls.

**Files:**
- Create: `backend/bootstrap/factories.py`
- Modify: `backend/main.py` (load_state), `backend/services/cloud_sync_service.py` (enable/disable)
- Modify: ~12 test files constructing managers directly

- [ ] **Step 1: Adapter-layer factories**

`backend/bootstrap/factories.py`:

```python
"""Composition-root factories: build the infra JsonStore + the service manager.
Lives in bootstrap (the only ring allowed to import every ring) so services
never import infra. Used by main.load_state, cloud_sync enable/disable, and tests."""
from infra.persistence.json_store import JsonStore
from models.schemas import BookmarkStore, RouteStore
from services.bookmarks import BookmarkManager, _bookmarks_path_default  # path resolver stays in services
from services.route_store import RouteManager, _routes_path_default, _inject_default_category


def make_bookmark_manager(path_provider=None) -> BookmarkManager:
    repo = JsonStore(BookmarkStore, path_provider or _bookmarks_path_default)
    return BookmarkManager(repo=repo)

def make_route_manager(path_provider=None) -> RouteManager:
    repo = JsonStore(RouteStore, path_provider or _routes_path_default, post_load=_inject_default_category)
    return RouteManager(repo=repo)
```

The `path_provider` defaults are the managers' existing `_bookmarks_path`/`_routes_path` resolvers (which read the module-level `BOOKMARKS_FILE`/`ROUTES_FILE` — keep them in `services/bookmarks.py`/`route_store.py` as module functions so the monkeypatch seam still bites). Expose them as module-level functions if they are currently methods.

- [ ] **Step 2: Wire the 3 production sites**

`main.py` `AppState.load_state` (≈163/168) and `cloud_sync_service.py` `enable`/`disable` (≈99-102/137-140): replace `BookmarkManager()`/`RouteManager()` with `make_bookmark_manager()`/`make_route_manager()`. `bootstrap/container.py` needs NO change (its `@property` live-delegates to `engine_registry`, forwarding whatever manager AppState built — verified container.py:69-81).

- [ ] **Step 3: Migrate the ~12 test constructions**

`grep -rln 'BookmarkManager()\|RouteManager()' backend/tests` (also catch `BookmarkManager(` with args). Switch each to `make_bookmark_manager()`/`make_route_manager()` (import from `bootstrap.factories`), preserving each test's existing `BOOKMARKS_FILE`/`ROUTES_FILE` monkeypatch (the factory's default path_provider reads it). Race tests that do `mgr._watcher_tick = ...` keep working (watcher is on the manager). Consider a `conftest.py` fixture to reduce duplication.

- [ ] **Step 4: Full suite + gate + commit**

Run: `cd backend && .venv/bin/python -m pytest -q` → all green; `grep -rn 'from infra' backend/services` → ZERO. `.venv/bin/lint-imports` → 6 kept/0 broken.

```bash
git add backend/bootstrap/factories.py backend/main.py backend/services/cloud_sync_service.py backend/tests/
git commit -m "refactor(bootstrap): construct JsonStore at the composition root; factory + migrate test constructions"
```

---

### Task 6: Shared `force_seed` primitive + refactor `import_catalog` onto it

**Files:**
- Modify: `backend/domain/store_merge.py` (add `force_seed_items`), `backend/services/bookmarks.py` (`force_seed` + `import_catalog`)
- Create: `backend/tests/test_force_seed.py`

- [ ] **Step 1: force_seed test-first — assert ON-DISK, drive the NEW method**

Create `backend/tests/test_force_seed.py`. Treatment: create+delete a bookmark (real-timestamp tombstone), then call the NEW `manager.force_seed([...])` with the same id + empty `updated_at`; assert the item is ALIVE on disk (`json.loads(path.read_text())`). Control: a naive append (no stamp) stays DEAD on disk. **Drive `force_seed` (the new code), not `import_catalog`** (so the net guards the new primitive). (Review-verified efficacious.)

Run → RED (force_seed missing).

- [ ] **Step 2: Pure stamp primitive in domain**

In `domain/store_merge.py`:

```python
def force_seed_items(items: list, now_iso: str) -> list:
    """Stamp updated_at=now on each item so a force-seed/import beats any
    pre-existing real-timestamp tombstone in merge_stores (the empty-updated_at
    pitfall). Pure: mutates + returns the given items. Caller supplies the time."""
    for it in items:
        it.updated_at = now_iso
    return items
```

- [ ] **Step 3: `BookmarkManager.force_seed` + PARTIAL `import_catalog` refactor**

Add `force_seed(self, items) -> dict`: stamp via `force_seed_items(items, _now_iso())`, upsert into `self.store`, `self._save()`. Refactor `import_catalog` (bookmarks.py:636-722) so the INCOMING-item stamping goes through `force_seed_items`. **PARTIAL extraction (review):** `import_catalog` stamps `updated_at=now` in FOUR positions — incoming `cat`/`bm` (674/695) AND the matched `old` record on the upsert branch (682/704). `force_seed_items` covers ONLY the incoming items; the upsert-branch `old.updated_at = now` lines MUST stay inline (different objects). Keep the single shared `now = _now_iso()`, the up-front `resurrected` count (669), the enrich order (`enrich_bookmark(old, force=True)` 705 / `enrich_bookmark(bm)` 708), and the exact `{added,updated,resurrected}` return — `test_bookmark_catalog_sync.py` (e.g. `test_resync_unchanged_is_idempotent` expects `{added:0,updated:3,resurrected:0}`) is the deep-equal freeze gate.

- [ ] **Step 4: force_seed GREEN + catalog tests + full suite + commit**

Run: `cd backend && .venv/bin/python -m pytest tests/test_force_seed.py tests/test_bookmark_catalog_sync.py tests/test_bookmark_catalog.py -q` → PASS. Full suite green.

```bash
git add backend/domain/store_merge.py backend/services/bookmarks.py backend/tests/test_force_seed.py
git commit -m "feat(persistence): shared force_seed_items primitive encoding the empty-updated_at pitfall; import_catalog uses it"
```

---

### Task 7: Enforce `no-infra-imports-fastapi`

**Files:** `backend/.importlinter`, `backend/tests/test_import_contracts_enforced.py`

- [ ] **Step 1: Require the 7th contract (RED)** — add `"no-infra-imports-fastapi"` to `REQUIRED_CONTRACTS`; run config-declares test → RED.
- [ ] **Step 2: Add the contract** (passes today — infra imports no fastapi):

```ini
[importlinter:contract:no-infra-imports-fastapi]
name = Infra must not import FastAPI
type = forbidden
source_modules =
    infra
forbidden_modules =
    fastapi
```

- [ ] **Step 3: GREEN (7 kept/0 broken) + full suite + commit**

```bash
git add backend/.importlinter backend/tests/test_import_contracts_enforced.py
git commit -m "test(arch): enforce no-infra-imports-fastapi (7th contract)"
```

---

### Task 8: Close-out — verify, document, smoke, merge

**Files:** spec, `CLAUDE.md`, `AGENTS.md`, `backend/CLAUDE.md`.

- [ ] **Step 1: Final verification** — `cd backend && .venv/bin/python -m pytest -q && .venv/bin/python -m pytest --collect-only -q | tail -1 && .venv/bin/lint-imports | grep Contracts:` → all green; 7 kept/0 broken; record count.
- [ ] **Step 2: Confirm the freeze + inversion** — `grep -rn 'from infra' backend/services` → ZERO (no services→infra); the 3 reach-ins untouched + green; managers take an injected repo.
- [ ] **Step 3: Docs flip** — spec §5 Phase 4 → P4a (backend repository) DONE on `chore/clean-arch-p4a` (merge in domain — §4.4-deviation noted; RouteManager lock dropped as YAGNI with rationale; force_seed primitive); P4b frontend deferred. Update `CLAUDE.md`/`AGENTS.md` status; update `backend/CLAUDE.md` CRDT section (repo behind the port + force_seed; note the route-watcher-doesn't-write-disk asymmetry so no lock).
- [ ] **Step 4: Commit docs.**
- [ ] **Step 5: Real-data smoke + merge** — with a real `~/.locwarp` store: bookmark CRUD + catalog/sync refresh (resurrect-after-delete) + route save/load + a cloud-sync folder toggle; confirm persistence. If green, ff-merge `chore/clean-arch-p4a` → `main`; else `git revert` the offending commit (shim + facade keep the old path alive).

---

## Rollback & Verification Gates

- Every commit keeps 871+ green individually; `git revert <sha>` is safe (shim + facade + factory).
- Task 2 verbatim move guarded by the 43 SAFE CRDT tests; Task 4 I/O move guarded by the thread-race + concurrency + watcher + GC + catalog nets (incl. Task 1's pins).
- No sanctioned behavior change — pure inversion. `no-infra-imports-fastapi` enforced at Task 7 (passes from the start); the services→infra non-edge is verified by grep at Tasks 4/5/8.
- Branch `chore/clean-arch-p4a`; merge after the Task-8 smoke.

## Execution Handoff

1. **Subagent-Driven (recommended)** — fresh implementer per task, test-first, review between tasks, broad final review. Use superpowers:subagent-driven-development.
2. **Inline Execution** — batch with checkpoints. Use superpowers:executing-plans.
