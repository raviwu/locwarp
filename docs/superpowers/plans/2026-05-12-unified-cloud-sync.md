# Unified Cloud Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalise LocWarp's cloud sync from bookmark-only to a single `sync_folder` setting that covers `bookmarks.json` and `routes.json`, with atomic migration, parallel file watchers, and silent upgrade from the legacy `bookmarks_path` setting.

**Architecture:** A new top-level `/api/cloud-sync/*` router brokers both files via a generic `sync_merge.merge_stores` helper and an atomic `cloud_sync.migrate_pair` function. `RouteManager` gains the same watchdog and dynamic path resolution that `BookmarkManager` already has. `AppState` swaps `_bookmarks_path` for `_sync_folder` and auto-migrates legacy settings at startup.

**Tech Stack:** Python 3.11 (FastAPI, Pydantic v2, watchdog, asyncio), pytest with `TestClient`, React + TypeScript frontend.

**Spec:** `docs/superpowers/specs/2026-05-12-unified-cloud-sync-design.md`

---

## File Structure

**New backend files:**
- `backend/services/sync_merge.py` — generic ID-based union-merge over a Pydantic store
- `backend/api/cloud_sync.py` — top-level cloud-sync router

**New tests:**
- `backend/tests/test_sync_merge.py`
- `backend/tests/test_migrate_pair.py`
- `backend/tests/test_route_watcher.py`
- `backend/tests/test_appstate_sync_migration.py`
- `backend/tests/test_cloud_sync_unified_api.py`

**Modified backend files:**
- `backend/config.py` — add `get_routes_path()`
- `backend/services/cloud_sync.py` — add `migrate_pair()`; `migrate_bookmarks` becomes a thin wrapper
- `backend/services/route_store.py` — use `get_routes_path()`; add `start_watcher` / `stop_watcher`
- `backend/models/schemas.py` — new `CloudSyncStatus`, `CloudSyncResource`, `CloudSyncEnableRequest` shape
- `backend/api/bookmarks.py` — remove cloud-sync endpoints and helpers
- `backend/main.py` — `AppState` swaps `_bookmarks_path` → `_sync_folder`, auto-migration, `restart_route_watcher`, lifespan boots route watcher, register new router
- `backend/tests/test_cloud_sync_api.py` — delete (superseded by unified tests)

**Modified frontend files:**
- `frontend/src/api.ts` — `CloudSyncStatus` type
- `frontend/src/components/CloudSyncSection.tsx` — read new nested fields
- `frontend/src/i18n/strings.ts` — `detail_counts`, `discovery_prompt`

---

## Task 1: `config.get_routes_path` (TDD)

**Files:**
- Modify: `backend/config.py`
- Create: `backend/tests/test_config_paths.py` (add cases — file already exists)

- [ ] **Step 1: Read the existing test patterns**

Open `backend/tests/test_config_paths.py` and read the existing `get_bookmarks_path` tests so the new tests mirror them.

- [ ] **Step 2: Write failing tests for `get_routes_path`**

Append to `backend/tests/test_config_paths.py`:

```python
def test_get_routes_path_default_when_no_sync_folder(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    from config import get_routes_path
    assert get_routes_path() == tmp_path / "routes.json"


def test_get_routes_path_honours_sync_folder(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    sync_dir = tmp_path / "iCloud" / "LocWarp"
    sync_dir.mkdir(parents=True)
    (tmp_path / "settings.json").write_text(
        '{"sync_folder": "%s"}' % sync_dir
    )
    from config import get_routes_path
    assert get_routes_path() == sync_dir / "routes.json"


def test_get_routes_path_falls_back_when_sync_folder_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text(
        '{"sync_folder": "/no/such/dir"}'
    )
    from config import get_routes_path
    assert get_routes_path() == tmp_path / "routes.json"


def test_get_routes_path_legacy_bookmarks_path_honoured(tmp_path, monkeypatch):
    # During the migration window, legacy bookmarks_path's parent acts as
    # the sync folder so routes co-locate with bookmarks even before the
    # AppState migration runs.
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    sync_dir = tmp_path / "legacy" / "LocWarp"
    sync_dir.mkdir(parents=True)
    (tmp_path / "settings.json").write_text(
        '{"bookmarks_path": "%s"}' % (sync_dir / "bookmarks.json")
    )
    from config import get_routes_path
    assert get_routes_path() == sync_dir / "routes.json"
```

- [ ] **Step 3: Run the tests; confirm they fail**

```bash
cd backend && python -m pytest tests/test_config_paths.py -v -k "routes_path"
```
Expected: 4 failures with `ImportError: cannot import name 'get_routes_path'`.

- [ ] **Step 4: Implement `get_routes_path` in `backend/config.py`**

Add directly after `get_bookmarks_path` (around line 32):

```python
def get_routes_path() -> Path:
    """Return the configured routes file path.

    Reads ``sync_folder`` from settings.json — falls back to legacy
    ``bookmarks_path``'s parent during the migration window so routes
    co-locate with bookmarks before AppState migrates the setting.
    Falls back to ``DATA_DIR / "routes.json"`` when no sync folder is
    configured or the configured folder is unreachable.
    """
    import config as _cfg
    from services.json_safe import safe_load_json
    data = safe_load_json(_cfg.SETTINGS_FILE)
    if isinstance(data, dict):
        sync_folder = data.get("sync_folder")
        if isinstance(sync_folder, str) and sync_folder:
            p = Path(sync_folder)
            if p.exists():
                return p / "routes.json"
        legacy = data.get("bookmarks_path")
        if isinstance(legacy, str) and legacy:
            parent = Path(legacy).parent
            if parent.exists():
                return parent / "routes.json"
    return _cfg.DATA_DIR / "routes.json"
```

Also update `get_bookmarks_path` (around line 11) to read `sync_folder` first, then fall back to the legacy `bookmarks_path`:

```python
def get_bookmarks_path() -> Path:
    """Return the configured bookmarks file path.

    Resolution order:
      1. ``sync_folder`` from settings.json (new model) →
         ``<sync_folder>/bookmarks.json``
      2. ``bookmarks_path`` from settings.json (legacy, migration window)
      3. ``DATA_DIR / "bookmarks.json"``
    """
    import config as _cfg
    from services.json_safe import safe_load_json
    data = safe_load_json(_cfg.SETTINGS_FILE)
    if isinstance(data, dict):
        sync_folder = data.get("sync_folder")
        if isinstance(sync_folder, str) and sync_folder:
            p = Path(sync_folder)
            if p.exists():
                return p / "bookmarks.json"
        override = data.get("bookmarks_path")
        if isinstance(override, str) and override:
            p = Path(override)
            if p.parent.exists():
                return p
    return _cfg.DATA_DIR / "bookmarks.json"
```

- [ ] **Step 5: Run the new tests; confirm they pass**

```bash
cd backend && python -m pytest tests/test_config_paths.py -v
```
Expected: all pass (new + existing).

- [ ] **Step 6: Commit**

```bash
git add backend/config.py backend/tests/test_config_paths.py
git commit -m "feat(config): add get_routes_path with sync_folder resolution"
```

---

## Task 2: `RouteManager` uses `get_routes_path` (TDD)

**Files:**
- Modify: `backend/services/route_store.py`
- Modify: `backend/tests/test_config_paths.py` (or wherever route loading lives — add if missing)

- [ ] **Step 1: Find existing route_store tests**

```bash
cd backend && grep -rln "RouteManager\|route_store" tests/
```
If none exist, create `backend/tests/test_route_store.py`. Otherwise reuse.

- [ ] **Step 2: Write failing test that `RouteManager` reads from `get_routes_path()`**

Add to `backend/tests/test_route_store.py` (create if missing):

```python
import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config.ROUTES_FILE", tmp_path / "routes.json")
    yield


def test_route_manager_writes_to_sync_folder_when_configured(tmp_path, monkeypatch):
    sync_dir = tmp_path / "iCloud" / "LocWarp"
    sync_dir.mkdir(parents=True)
    (tmp_path / "settings.json").write_text(
        json.dumps({"sync_folder": str(sync_dir)})
    )

    from services.route_store import RouteManager
    rm = RouteManager()
    cat = rm.create_category(name="Test")
    expected_path = sync_dir / "routes.json"
    assert expected_path.exists()
    payload = json.loads(expected_path.read_text())
    assert any(c["id"] == cat.id for c in payload["categories"])


def test_route_manager_reads_from_sync_folder(tmp_path, monkeypatch):
    sync_dir = tmp_path / "iCloud" / "LocWarp"
    sync_dir.mkdir(parents=True)
    (tmp_path / "settings.json").write_text(
        json.dumps({"sync_folder": str(sync_dir)})
    )
    (sync_dir / "routes.json").write_text(json.dumps({
        "categories": [
            {"id": "default", "name": "預設", "color": "#6c8cff",
             "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00"}
        ],
        "routes": [],
    }))

    from services.route_store import RouteManager
    rm = RouteManager()
    assert len(rm.list_categories()) == 1
```

- [ ] **Step 3: Run tests; confirm they fail**

```bash
cd backend && python -m pytest tests/test_route_store.py -v
```
Expected: failures because `RouteManager` still reads `ROUTES_FILE` constant which points to `~/.locwarp/routes.json`.

- [ ] **Step 4: Update `RouteManager` to use `get_routes_path()` per call**

Edit `backend/services/route_store.py`:

```python
# Replace this import line
from config import ROUTES_FILE
# With this:
from config import ROUTES_FILE, get_routes_path

# Capture the import-time default so tests that monkeypatch
# config.ROUTES_FILE keep working.
_CONFIG_DEFAULT_ROUTES_FILE = ROUTES_FILE
```

Then replace `_load` and `_save`:

```python
def _routes_path(self) -> Path:
    # Tests may monkeypatch the module-level ROUTES_FILE; if it differs
    # from the import-time default, honour the test override.
    if ROUTES_FILE is not _CONFIG_DEFAULT_ROUTES_FILE:
        return Path(ROUTES_FILE)
    return get_routes_path()

def _load(self) -> None:
    data = safe_load_json(self._routes_path())
    if data is None:
        logger.info("No routes file (or unreadable); using defaults")
        return
    # ... rest unchanged

def _save(self) -> None:
    payload = json.loads(self.store.model_dump_json())
    safe_write_json(self._routes_path(), payload)
```

- [ ] **Step 5: Run tests; confirm they pass**

```bash
cd backend && python -m pytest tests/test_route_store.py -v
```
Expected: pass.

- [ ] **Step 6: Run the full route test suite to confirm no regressions**

```bash
cd backend && python -m pytest tests/ -v -k "route"
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/services/route_store.py backend/tests/test_route_store.py
git commit -m "refactor(routes): resolve path via get_routes_path on every read/write"
```

---

## Task 3: Generic `sync_merge.merge_stores` (TDD)

**Files:**
- Create: `backend/services/sync_merge.py`
- Create: `backend/tests/test_sync_merge.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_sync_merge.py`:

```python
"""Unit tests for the generic store merge helper."""

import json
from pathlib import Path

import pytest

from models.schemas import (
    Bookmark, BookmarkCategory, BookmarkStore,
    SavedRoute, RouteCategory, RouteStore,
)
from services.sync_merge import merge_bookmark_stores, merge_route_stores


def _write(p: Path, payload: dict) -> None:
    p.write_text(json.dumps(payload))


def _bm_payload(bookmarks, categories=None) -> dict:
    cats = categories or [{
        "id": "default", "name": "預設", "color": "#6c8cff",
        "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
    }]
    return {"categories": cats, "bookmarks": bookmarks}


def _route_payload(routes, categories=None) -> dict:
    cats = categories or [{
        "id": "default", "name": "預設", "color": "#6c8cff",
        "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
    }]
    return {"categories": cats, "routes": routes}


def test_merge_bookmark_stores_union(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    _write(local, _bm_payload([{
        "id": "a", "name": "A", "lat": 1.0, "lng": 1.0,
        "category_id": "default", "created_at": "2026-05-12T00:00:00+00:00",
    }]))
    _write(remote, _bm_payload([{
        "id": "b", "name": "B", "lat": 2.0, "lng": 2.0,
        "category_id": "default", "created_at": "2026-05-12T00:00:00+00:00",
    }]))

    merge_bookmark_stores(local, remote)

    merged = json.loads(remote.read_text())
    ids = {b["id"] for b in merged["bookmarks"]}
    assert ids == {"a", "b"}


def test_merge_bookmark_stores_local_wins_on_conflict(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    _write(local, _bm_payload([{
        "id": "a", "name": "LOCAL", "lat": 1.0, "lng": 1.0,
        "category_id": "default", "created_at": "2026-05-12T00:00:00+00:00",
    }]))
    _write(remote, _bm_payload([{
        "id": "a", "name": "REMOTE", "lat": 9.0, "lng": 9.0,
        "category_id": "default", "created_at": "2026-05-12T00:00:00+00:00",
    }]))

    merge_bookmark_stores(local, remote)

    merged = json.loads(remote.read_text())
    [bm] = merged["bookmarks"]
    assert bm["name"] == "LOCAL"
    assert bm["lat"] == 1.0


def test_merge_route_stores_union(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    _write(local, _route_payload([{
        "id": "r1", "name": "Loop", "category_id": "default",
        "engine": "osrm", "waypoints": [[1.0, 1.0], [2.0, 2.0]],
        "geometry": [[1.0, 1.0], [2.0, 2.0]], "duration_s": 10.0,
        "distance_m": 100.0, "created_at": "2026-05-12T00:00:00+00:00",
    }]))
    _write(remote, _route_payload([{
        "id": "r2", "name": "Hill", "category_id": "default",
        "engine": "osrm", "waypoints": [[3.0, 3.0], [4.0, 4.0]],
        "geometry": [[3.0, 3.0], [4.0, 4.0]], "duration_s": 20.0,
        "distance_m": 200.0, "created_at": "2026-05-12T00:00:00+00:00",
    }]))

    merge_route_stores(local, remote)

    merged = json.loads(remote.read_text())
    ids = {r["id"] for r in merged["routes"]}
    assert ids == {"r1", "r2"}


def test_merge_route_stores_local_wins_on_conflict(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    base = {
        "id": "r1", "category_id": "default", "engine": "osrm",
        "waypoints": [[1.0, 1.0]], "geometry": [[1.0, 1.0]],
        "duration_s": 1.0, "distance_m": 1.0,
        "created_at": "2026-05-12T00:00:00+00:00",
    }
    _write(local, _route_payload([dict(base, name="LOCAL")]))
    _write(remote, _route_payload([dict(base, name="REMOTE")]))

    merge_route_stores(local, remote)

    merged = json.loads(remote.read_text())
    [route] = merged["routes"]
    assert route["name"] == "LOCAL"


def test_merge_bookmark_stores_skips_on_parse_failure(tmp_path):
    local = tmp_path / "local.json"
    remote = tmp_path / "remote.json"
    _write(local, _bm_payload([]))
    remote.write_text("{not json}")

    # Should not raise; remote file left as-is.
    merge_bookmark_stores(local, remote)
    assert remote.read_text() == "{not json}"
```

Then verify the actual route schema fields by reading `backend/models/schemas.py` lines 175–200 first; adjust the payload fields in the tests if any are required and missing. The fields in `_route_payload` above are the expected required set — confirm before running.

- [ ] **Step 2: Run tests; confirm they fail**

```bash
cd backend && python -m pytest tests/test_sync_merge.py -v
```
Expected: ImportError on `services.sync_merge`.

- [ ] **Step 3: Implement `sync_merge.py`**

Create `backend/services/sync_merge.py`:

```python
"""Generic ID-based union merge for cloud-synced JSON stores.

Used by both bookmark and route cloud sync. Strategy: union of local +
remote items; for the same ID, local wins. Remote-only items added by
other devices are preserved.

Skips merge (leaving remote untouched) when either file is unreadable
or fails schema validation — better than wiping the remote with an empty
fallback.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from models.schemas import BookmarkStore, RouteStore
from services.json_safe import safe_load_json, safe_write_json

logger = logging.getLogger(__name__)


def _merge_bookmark_payload(local: BookmarkStore, remote: BookmarkStore) -> BookmarkStore:
    cats = {c.id: c for c in remote.categories}
    cats.update({c.id: c for c in local.categories})
    bms = {b.id: b for b in remote.bookmarks}
    bms.update({b.id: b for b in local.bookmarks})
    return BookmarkStore(categories=list(cats.values()), bookmarks=list(bms.values()))


def _merge_route_payload(local: RouteStore, remote: RouteStore) -> RouteStore:
    cats = {c.id: c for c in remote.categories}
    cats.update({c.id: c for c in local.categories})
    routes = {r.id: r for r in remote.routes}
    routes.update({r.id: r for r in local.routes})
    return RouteStore(categories=list(cats.values()), routes=list(routes.values()))


def merge_bookmark_stores(local_path: Path, remote_path: Path) -> None:
    """Union-merge bookmarks at *local_path* into *remote_path* (local wins)."""
    try:
        local_data = safe_load_json(local_path)
        remote_data = safe_load_json(remote_path)
        if not isinstance(local_data, dict) or not isinstance(remote_data, dict):
            return
        local_store = BookmarkStore(**local_data)
        remote_store = BookmarkStore(**remote_data)
    except Exception as exc:
        logger.warning("sync_merge bookmarks: skipping, parse failed: %s", exc)
        return
    merged = _merge_bookmark_payload(local_store, remote_store)
    safe_write_json(remote_path, json.loads(merged.model_dump_json()))
    logger.info(
        "sync_merge bookmarks: %d local + %d remote → %d merged",
        len(local_store.bookmarks), len(remote_store.bookmarks), len(merged.bookmarks),
    )


def merge_route_stores(local_path: Path, remote_path: Path) -> None:
    """Union-merge routes at *local_path* into *remote_path* (local wins)."""
    try:
        local_data = safe_load_json(local_path)
        remote_data = safe_load_json(remote_path)
        if not isinstance(local_data, dict) or not isinstance(remote_data, dict):
            return
        local_store = RouteStore(**local_data)
        remote_store = RouteStore(**remote_data)
    except Exception as exc:
        logger.warning("sync_merge routes: skipping, parse failed: %s", exc)
        return
    merged = _merge_route_payload(local_store, remote_store)
    safe_write_json(remote_path, json.loads(merged.model_dump_json()))
    logger.info(
        "sync_merge routes: %d local + %d remote → %d merged",
        len(local_store.routes), len(remote_store.routes), len(merged.routes),
    )
```

- [ ] **Step 4: Run tests; confirm they pass**

```bash
cd backend && python -m pytest tests/test_sync_merge.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/services/sync_merge.py backend/tests/test_sync_merge.py
git commit -m "feat(sync): generic union-merge helper for bookmark and route stores"
```

---

## Task 4: `cloud_sync.migrate_pair` atomic two-file migration (TDD)

**Files:**
- Modify: `backend/services/cloud_sync.py`
- Create: `backend/tests/test_migrate_pair.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_migrate_pair.py`:

```python
"""Tests for the atomic two-file (bookmarks + routes) migration."""

import json
from pathlib import Path

import pytest

from services.cloud_sync import migrate_pair


def _write_bookmarks(p: Path, ids: list[str]) -> None:
    p.write_text(json.dumps({
        "categories": [{
            "id": "default", "name": "預設", "color": "#6c8cff",
            "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
        }],
        "bookmarks": [
            {"id": i, "name": i, "lat": 1.0, "lng": 1.0,
             "category_id": "default",
             "created_at": "2026-05-12T00:00:00+00:00"}
            for i in ids
        ],
    }))


def _write_routes(p: Path, ids: list[str]) -> None:
    p.write_text(json.dumps({
        "categories": [{
            "id": "default", "name": "預設", "color": "#6c8cff",
            "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
        }],
        "routes": [
            {"id": i, "name": i, "category_id": "default", "engine": "osrm",
             "waypoints": [[1.0, 1.0]], "geometry": [[1.0, 1.0]],
             "duration_s": 1.0, "distance_m": 1.0,
             "created_at": "2026-05-12T00:00:00+00:00"}
            for i in ids
        ],
    }))


def test_migrate_pair_src_only(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    _write_bookmarks(src / "bookmarks.json", ["a"])
    _write_routes(src / "routes.json", ["r1"])

    migrate_pair(src, dst)

    assert (dst / "bookmarks.json").exists()
    assert (dst / "routes.json").exists()
    assert not (src / "bookmarks.json").exists()
    assert not (src / "routes.json").exists()


def test_migrate_pair_dst_only_is_noop(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    _write_bookmarks(dst / "bookmarks.json", ["a"])
    _write_routes(dst / "routes.json", ["r1"])

    migrate_pair(src, dst)

    # No src files to migrate; dst untouched.
    dst_bm = json.loads((dst / "bookmarks.json").read_text())
    assert [b["id"] for b in dst_bm["bookmarks"]] == ["a"]


def test_migrate_pair_both_present_union_merges(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    _write_bookmarks(src / "bookmarks.json", ["a"])
    _write_bookmarks(dst / "bookmarks.json", ["b"])
    _write_routes(src / "routes.json", ["r1"])
    _write_routes(dst / "routes.json", ["r2"])

    migrate_pair(src, dst)

    dst_bm = json.loads((dst / "bookmarks.json").read_text())
    dst_rt = json.loads((dst / "routes.json").read_text())
    assert {b["id"] for b in dst_bm["bookmarks"]} == {"a", "b"}
    assert {r["id"] for r in dst_rt["routes"]} == {"r1", "r2"}
    assert not (src / "bookmarks.json").exists()
    assert not (src / "routes.json").exists()


def test_migrate_pair_partial_src_only_bookmarks(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    _write_bookmarks(src / "bookmarks.json", ["a"])
    # routes only on dst — should remain
    _write_routes(dst / "routes.json", ["r2"])

    migrate_pair(src, dst)

    assert (dst / "bookmarks.json").exists()
    assert (dst / "routes.json").exists()
    dst_rt = json.loads((dst / "routes.json").read_text())
    assert [r["id"] for r in dst_rt["routes"]] == ["r2"]


def test_migrate_pair_rollback_on_failure(tmp_path, monkeypatch):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "dst"; dst.mkdir()
    _write_bookmarks(src / "bookmarks.json", ["a"])
    _write_routes(src / "routes.json", ["r1"])

    # Inject a failure when migrating the routes file (after bookmarks
    # have already been written to dst). The rollback must:
    #   - restore src/bookmarks.json
    #   - remove dst/bookmarks.json (which we created this call)
    import services.cloud_sync as cs
    original = cs._move_or_merge_file

    def boom(src_file, dst_file, kind):
        if kind == "routes":
            raise OSError("simulated failure")
        return original(src_file, dst_file, kind)

    monkeypatch.setattr("services.cloud_sync._move_or_merge_file", boom)

    with pytest.raises(OSError):
        migrate_pair(src, dst)

    # Source must be restored.
    assert (src / "bookmarks.json").exists()
    assert (src / "routes.json").exists()
    # Destination must not contain partial state.
    assert not (dst / "bookmarks.json").exists()
    assert not (dst / "routes.json").exists()
```

- [ ] **Step 2: Run tests; confirm they fail**

```bash
cd backend && python -m pytest tests/test_migrate_pair.py -v
```
Expected: failures (`migrate_pair` not defined, `_move_or_merge_file` not defined).

- [ ] **Step 3: Implement `migrate_pair` in `cloud_sync.py`**

Edit `backend/services/cloud_sync.py`. Add at the top of the file:

```python
import os
import tempfile

from services.sync_merge import merge_bookmark_stores, merge_route_stores
```

Add these helpers and rewrite `migrate_bookmarks` to delegate. Append after `migrate_bookmarks`:

```python
_PAIR_FILES: tuple[tuple[str, str], ...] = (
    ("bookmarks.json", "bookmarks"),
    ("routes.json", "routes"),
)


def _move_or_merge_file(src: Path, dst: Path, kind: str) -> None:
    """Move *src* to *dst*, union-merging when both exist with different content.

    *kind* is "bookmarks" or "routes" — picks the right merger.
    No-op when *src* does not exist.
    """
    if not src.exists():
        return
    if dst.exists():
        if dst.read_bytes() == src.read_bytes():
            try:
                src.unlink()
            except OSError as exc:
                logger.warning(
                    "migrate %s: %s and %s match but src unlink failed: %s",
                    kind, src, dst, exc,
                )
            return
        if kind == "bookmarks":
            merge_bookmark_stores(src, dst)
        elif kind == "routes":
            merge_route_stores(src, dst)
        else:
            raise ValueError(f"unknown kind: {kind}")
        src.unlink(missing_ok=True)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    src.unlink()


def migrate_pair(src_dir: Path, dst_dir: Path) -> None:
    """Move bookmarks.json + routes.json from *src_dir* to *dst_dir*.

    All-or-nothing: on any failure, restore *src_dir* to its original
    state, remove any files newly created in *dst_dir* by this call, then
    re-raise.

    Union-merges when a file exists on both sides with different content.
    """
    if not dst_dir.exists():
        raise FileNotFoundError(f"Destination folder does not exist: {dst_dir}")

    # Snapshot src files so we can restore on failure.
    snapshot_dir = Path(tempfile.mkdtemp(prefix="locwarp-migrate-"))
    dst_existed_before: dict[str, bool] = {}
    try:
        for name, _kind in _PAIR_FILES:
            src_file = src_dir / name
            if src_file.exists():
                shutil.copy2(src_file, snapshot_dir / name)
            dst_existed_before[name] = (dst_dir / name).exists()

        for name, kind in _PAIR_FILES:
            _move_or_merge_file(src_dir / name, dst_dir / name, kind)
    except Exception:
        # Restore src from snapshot.
        for name, _kind in _PAIR_FILES:
            snap = snapshot_dir / name
            target = src_dir / name
            if snap.exists() and not target.exists():
                shutil.copy2(snap, target)
        # Remove dst files we created in this call.
        for name, _kind in _PAIR_FILES:
            if not dst_existed_before.get(name, False):
                p = dst_dir / name
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        logger.exception("rollback: could not unlink %s", p)
        raise
    finally:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
```

Then replace the body of `migrate_bookmarks` so old callers keep working:

```python
def migrate_bookmarks(src: Path, dst: Path) -> None:
    """Backwards-compat wrapper: move just the bookmarks file.

    Retained so existing tests and the legacy API path continue to work
    while we migrate to the unified ``migrate_pair`` flow.
    """
    _move_or_merge_file(src, dst, "bookmarks")
```

- [ ] **Step 4: Run tests; confirm they pass**

```bash
cd backend && python -m pytest tests/test_migrate_pair.py tests/test_cloud_sync.py -v
```
Expected: all pass (new tests + existing bookmark tests still green).

- [ ] **Step 5: Commit**

```bash
git add backend/services/cloud_sync.py backend/tests/test_migrate_pair.py
git commit -m "feat(sync): atomic two-file migrate_pair with rollback"
```

---

## Task 5: `RouteManager.start_watcher` / `stop_watcher` (TDD)

**Files:**
- Modify: `backend/services/route_store.py`
- Create: `backend/tests/test_route_watcher.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_route_watcher.py`:

```python
"""Tests for RouteManager file-watcher (external mtime → on_change callback)."""

import json
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config.ROUTES_FILE", tmp_path / "routes.json")
    yield


def _write_routes(p: Path, route_id: str) -> None:
    p.write_text(json.dumps({
        "categories": [{
            "id": "default", "name": "預設", "color": "#6c8cff",
            "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
        }],
        "routes": [{
            "id": route_id, "name": route_id, "category_id": "default",
            "engine": "osrm", "waypoints": [[1.0, 1.0]],
            "geometry": [[1.0, 1.0]], "duration_s": 1.0, "distance_m": 1.0,
            "created_at": "2026-05-12T00:00:00+00:00",
        }],
    }))


def _wait_for(predicate, timeout: float = 3.0, interval: float = 0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_external_modification_triggers_callback(tmp_path):
    routes_file = tmp_path / "routes.json"
    _write_routes(routes_file, "initial")

    from services.route_store import RouteManager
    rm = RouteManager()
    assert len(rm.list_routes()) == 1

    fired: list[None] = []
    rm.start_watcher(lambda: fired.append(None))
    try:
        _write_routes(routes_file, "external")
        # Force a distinctly newer mtime so the watcher tick does not
        # mistake it for a self-write.
        new_mtime = time.time() + 1.0
        import os
        os.utime(routes_file, (new_mtime, new_mtime))

        assert _wait_for(lambda: bool(fired)), "callback never fired"
        assert rm.list_routes()[0].id == "external"
    finally:
        rm.stop_watcher()


def test_self_write_does_not_trigger_callback(tmp_path):
    routes_file = tmp_path / "routes.json"
    _write_routes(routes_file, "r0")

    from services.route_store import RouteManager
    rm = RouteManager()
    fired: list[None] = []
    rm.start_watcher(lambda: fired.append(None))
    try:
        rm.create_category(name="from-self")
        time.sleep(1.0)  # past the debounce
        assert not fired, "self-write should not trigger external-change callback"
    finally:
        rm.stop_watcher()


def test_stop_watcher_idempotent(tmp_path):
    from services.route_store import RouteManager
    rm = RouteManager()
    rm.stop_watcher()  # never started
    rm.start_watcher(lambda: None)
    rm.stop_watcher()
    rm.stop_watcher()  # second call must not raise
```

- [ ] **Step 2: Run tests; confirm they fail**

```bash
cd backend && python -m pytest tests/test_route_watcher.py -v
```
Expected: AttributeError on `start_watcher` / `stop_watcher`.

- [ ] **Step 3: Mirror `BookmarkManager`'s watcher onto `RouteManager`**

Edit `backend/services/route_store.py`. Add imports near the top:

```python
import threading
from typing import Callable
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
```

Extend `RouteManager.__init__` (add after `self._load()`):

```python
        self._last_loaded_mtime: float = self._stat_mtime()
        self._watcher_observer: Observer | None = None
        self._watcher_debounce_timer: threading.Timer | None = None
        self._on_external_change: Callable[[], None] | None = None
```

Add helper methods on `RouteManager` (paste right above `# Categories`):

```python
    def _stat_mtime(self) -> float:
        try:
            return self._routes_path().stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def start_watcher(self, on_change: Callable[[], None]) -> None:
        self.stop_watcher()
        path = self._routes_path()
        parent = path.parent
        if not parent.exists():
            logger.warning("Routes folder does not exist; watcher not started: %s", parent)
            return
        self._on_external_change = on_change
        manager = self

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.is_directory:
                    return
                if Path(event.src_path) != manager._routes_path():
                    return
                manager._schedule_reconcile()

            on_created = on_modified

            def on_moved(self, event):
                if event.is_directory:
                    return
                rp = manager._routes_path()
                if Path(event.src_path) != rp and Path(getattr(event, "dest_path", "")) != rp:
                    return
                manager._schedule_reconcile()

        self._watcher_observer = Observer()
        self._watcher_observer.schedule(_Handler(), str(parent), recursive=False)
        self._watcher_observer.start()
        logger.info("Route watcher started on %s", parent)

    def stop_watcher(self) -> None:
        if self._watcher_debounce_timer is not None:
            self._watcher_debounce_timer.cancel()
            self._watcher_debounce_timer = None
        if self._watcher_observer is not None:
            try:
                self._watcher_observer.stop()
                self._watcher_observer.join(timeout=2.0)
            except Exception:
                logger.exception("Failed to stop route watcher cleanly")
            self._watcher_observer = None

    def _schedule_reconcile(self) -> None:
        if self._watcher_debounce_timer is not None:
            self._watcher_debounce_timer.cancel()
        self._watcher_debounce_timer = threading.Timer(0.5, self._watcher_tick)
        self._watcher_debounce_timer.daemon = True
        self._watcher_debounce_timer.start()

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
            self._load()
            after = self.store.model_dump_json()
            self._last_loaded_mtime = current_mtime
            if before != after and self._on_external_change is not None:
                try:
                    self._on_external_change()
                except Exception:
                    logger.exception("Route on_external_change callback raised")
        except Exception:
            logger.exception("Route watcher tick failed")
```

Update `_save` to refresh `_last_loaded_mtime` after writing, so subsequent self-write events are skipped:

```python
def _save(self) -> None:
    payload = json.loads(self.store.model_dump_json())
    safe_write_json(self._routes_path(), payload)
    self._last_loaded_mtime = self._stat_mtime()
```

- [ ] **Step 4: Run tests; confirm they pass**

```bash
cd backend && python -m pytest tests/test_route_watcher.py -v
```
Expected: all pass.

- [ ] **Step 5: Run all route-related tests**

```bash
cd backend && python -m pytest tests/test_route_store.py tests/test_route_watcher.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/route_store.py backend/tests/test_route_watcher.py
git commit -m "feat(routes): watchdog file watcher mirroring BookmarkManager"
```

---

## Task 6: `CloudSync*` schemas in `models/schemas.py` (TDD)

**Files:**
- Modify: `backend/models/schemas.py`

- [ ] **Step 1: Write a tiny test for the new schema shape**

Create `backend/tests/test_cloud_sync_schemas.py`:

```python
import pytest

from models.schemas import (
    CloudSyncResource, CloudSyncStatus, CloudSyncEnableRequest,
)


def test_cloud_sync_status_has_nested_resources():
    s = CloudSyncStatus(
        enabled=True,
        sync_folder="/tmp/LocWarp",
        detected_icloud_path="/tmp",
        prompt_dismissed=False,
        bookmarks=CloudSyncResource(path="/tmp/LocWarp/bookmarks.json",
                                     count=3, category_count=1),
        routes=CloudSyncResource(path="/tmp/LocWarp/routes.json",
                                  count=2, category_count=1),
    )
    payload = s.model_dump()
    assert payload["bookmarks"]["count"] == 3
    assert payload["routes"]["count"] == 2


def test_cloud_sync_enable_request_folder_optional():
    assert CloudSyncEnableRequest().folder is None
    assert CloudSyncEnableRequest(folder="/x").folder == "/x"
```

- [ ] **Step 2: Run tests; confirm they fail**

```bash
cd backend && python -m pytest tests/test_cloud_sync_schemas.py -v
```
Expected: ImportError on `CloudSyncResource`.

- [ ] **Step 3: Replace the existing `CloudSync*` classes**

In `backend/models/schemas.py`, replace the existing `CloudSyncStatus` and `CloudSyncEnableRequest` (around line 309–321) with:

```python
# ── Cloud sync ────────────────────────────────────────────
class CloudSyncResource(BaseModel):
    path: str
    count: int = 0
    category_count: int = 0


class CloudSyncStatus(BaseModel):
    enabled: bool
    sync_folder: str | None = None
    detected_icloud_path: str | None = None
    prompt_dismissed: bool = False
    bookmarks: CloudSyncResource
    routes: CloudSyncResource


class CloudSyncEnableRequest(BaseModel):
    folder: str | None = None  # absolute path; None = use detected iCloud
```

- [ ] **Step 4: Run tests; confirm they pass**

```bash
cd backend && python -m pytest tests/test_cloud_sync_schemas.py -v
```
Expected: pass.

- [ ] **Step 5: Note — the existing `test_cloud_sync_api.py` will now fail**

That's expected. We delete and replace it in Task 9.

- [ ] **Step 6: Commit**

```bash
git add backend/models/schemas.py backend/tests/test_cloud_sync_schemas.py
git commit -m "feat(schemas): unified CloudSyncStatus with nested resources"
```

---

## Task 7: `AppState` swaps `_bookmarks_path` for `_sync_folder` (TDD)

**Files:**
- Modify: `backend/main.py`
- Create: `backend/tests/test_appstate_sync_migration.py`

- [ ] **Step 1: Read the existing `AppState` block**

Open `backend/main.py` and read lines 80–170 to understand `_load_persisted_state`, `save_settings`, `restart_bookmark_watcher`.

- [ ] **Step 2: Write failing tests for the new field + migration**

Create `backend/tests/test_appstate_sync_migration.py`:

```python
"""AppState: sync_folder field + legacy bookmarks_path auto-migration."""

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config._DEFAULT_BOOKMARKS_FILE",
                        tmp_path / "bookmarks.json")
    monkeypatch.setattr("config.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("main.SETTINGS_FILE", tmp_path / "settings.json")
    yield


def _write_settings(tmp_path, data):
    (tmp_path / "settings.json").write_text(json.dumps(data))


def test_appstate_loads_sync_folder(tmp_path):
    sync_dir = tmp_path / "iCloud" / "LocWarp"
    sync_dir.mkdir(parents=True)
    _write_settings(tmp_path, {"sync_folder": str(sync_dir)})

    import importlib, main
    importlib.reload(main)
    assert main.app_state._sync_folder == str(sync_dir)


def test_legacy_bookmarks_path_auto_migrates(tmp_path):
    sync_dir = tmp_path / "iCloud" / "LocWarp"
    sync_dir.mkdir(parents=True)
    # Legacy: pre-migration user had bookmarks synced to iCloud, routes local.
    (sync_dir / "bookmarks.json").write_text(json.dumps({
        "categories": [{
            "id": "default", "name": "預設", "color": "#6c8cff",
            "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
        }],
        "bookmarks": [],
    }))
    (tmp_path / "routes.json").write_text(json.dumps({
        "categories": [{
            "id": "default", "name": "預設", "color": "#6c8cff",
            "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
        }],
        "routes": [{
            "id": "r1", "name": "Loop", "category_id": "default",
            "engine": "osrm", "waypoints": [[1.0, 1.0]],
            "geometry": [[1.0, 1.0]], "duration_s": 1.0, "distance_m": 1.0,
            "created_at": "2026-05-12T00:00:00+00:00",
        }],
    }))
    _write_settings(tmp_path, {
        "bookmarks_path": str(sync_dir / "bookmarks.json"),
        "cloud_sync_dismissed": False,
    })

    import importlib, main
    importlib.reload(main)
    state = main.app_state

    # Setting was upgraded.
    assert state._sync_folder == str(sync_dir)
    assert getattr(state, "_bookmarks_path", None) in (None, "")  # legacy gone
    persisted = json.loads((tmp_path / "settings.json").read_text())
    assert persisted.get("sync_folder") == str(sync_dir)
    assert "bookmarks_path" not in persisted

    # Local routes.json was migrated into the sync folder.
    assert (sync_dir / "routes.json").exists()
    moved = json.loads((sync_dir / "routes.json").read_text())
    assert [r["id"] for r in moved["routes"]] == ["r1"]
    assert not (tmp_path / "routes.json").exists()


def test_legacy_bookmarks_path_with_missing_folder_keeps_setting(tmp_path):
    _write_settings(tmp_path, {
        "bookmarks_path": "/no/such/dir/bookmarks.json",
    })

    import importlib, main
    importlib.reload(main)

    # Folder doesn't exist; migration must not crash, must not silently
    # delete legacy setting (user can re-enable later).
    persisted = json.loads((tmp_path / "settings.json").read_text())
    assert persisted.get("bookmarks_path") == "/no/such/dir/bookmarks.json"
    assert persisted.get("sync_folder") is None
```

- [ ] **Step 3: Run tests; confirm they fail**

```bash
cd backend && python -m pytest tests/test_appstate_sync_migration.py -v
```
Expected: AttributeError on `_sync_folder`.

- [ ] **Step 4: Replace the relevant `AppState` block in `backend/main.py`**

Locate the block around lines 80–145. Make these changes:

1. Replace the `self._bookmarks_path` and related state init (line 85–86):

```python
        self._sync_folder: str | None = None
        self._cloud_sync_dismissed: bool = False
```

2. Replace `_load_persisted_state` body (the block reading `data.get("bookmarks_path")` etc., around line 110–125):

```python
    def _load_persisted_state(self) -> None:
        from services.json_safe import safe_load_json
        data = safe_load_json(SETTINGS_FILE)
        if not isinstance(data, dict):
            return

        sync_folder = data.get("sync_folder")
        if isinstance(sync_folder, str) and sync_folder:
            self._sync_folder = sync_folder

        cdsm = data.get("cloud_sync_dismissed")
        if isinstance(cdsm, bool):
            self._cloud_sync_dismissed = cdsm

        # Legacy migration: upgrade bookmarks_path → sync_folder, and
        # pull the local routes.json into the same folder.
        legacy = data.get("bookmarks_path")
        if (
            self._sync_folder is None
            and isinstance(legacy, str)
            and legacy
        ):
            from pathlib import Path as _P
            candidate = _P(legacy).parent
            if candidate.exists():
                try:
                    from services.cloud_sync import migrate_pair
                    import config as _cfg
                    migrate_pair(_cfg.DATA_DIR, candidate)
                    self._sync_folder = str(candidate)
                    # Drop legacy key from on-disk settings.
                    data.pop("bookmarks_path", None)
                    data["sync_folder"] = str(candidate)
                    from services.json_safe import safe_write_json
                    safe_write_json(SETTINGS_FILE, data)
                    logger.info(
                        "AppState: migrated legacy bookmarks_path → "
                        "sync_folder=%s", candidate,
                    )
                except Exception:
                    logger.exception(
                        "AppState: legacy bookmarks_path migration failed; "
                        "keeping legacy setting"
                    )
            else:
                logger.warning(
                    "AppState: legacy bookmarks_path points at missing "
                    "folder %s; deferring migration until cloud drive is "
                    "available",
                    candidate,
                )
```

3. Replace `save_settings` body (around line 130–137):

```python
    def save_settings(self) -> None:
        from services.json_safe import safe_write_json
        payload = {
            "sync_folder": self._sync_folder,
            "cloud_sync_dismissed": self._cloud_sync_dismissed,
        }
        safe_write_json(SETTINGS_FILE, payload)
```

4. Add `restart_route_watcher` next to `restart_bookmark_watcher` (around line 147):

```python
    def restart_route_watcher(self) -> None:
        """Re-bind the route watcher to the current routes path.

        Call this after `_sync_folder` changes so the watcher binds to
        the new directory. Mirrors `restart_bookmark_watcher`.
        """
        import asyncio
        from api.websocket import broadcast as _bc

        self.route_manager.stop_watcher()
        loop = asyncio.get_running_loop()

        def _on_change():
            asyncio.run_coroutine_threadsafe(
                _bc("routes_changed", {"reason": "external_update"}), loop
            )

        self.route_manager.start_watcher(_on_change)
```

- [ ] **Step 5: Run the new tests; confirm they pass**

```bash
cd backend && python -m pytest tests/test_appstate_sync_migration.py -v
```
Expected: all pass.

- [ ] **Step 6: Run the lifespan / appstate regression tests**

```bash
cd backend && python -m pytest tests/test_lifespan.py tests/test_migrate_user_state.py -v
```
Expected: pass (may need to update one or two if they touch `_bookmarks_path` directly — fix any obvious symbol-name breakage and re-run).

- [ ] **Step 7: Commit**

```bash
git add backend/main.py backend/tests/test_appstate_sync_migration.py
git commit -m "feat(appstate): sync_folder setting with legacy bookmarks_path auto-migration"
```

---

## Task 8: New `/api/cloud-sync/*` router + tests (TDD)

**Files:**
- Create: `backend/api/cloud_sync.py`
- Create: `backend/tests/test_cloud_sync_unified_api.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_cloud_sync_unified_api.py`:

```python
"""End-to-end tests for /api/cloud-sync/*."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config._DEFAULT_BOOKMARKS_FILE",
                        tmp_path / "bookmarks.json")
    monkeypatch.setattr("config.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("main.SETTINGS_FILE", tmp_path / "settings.json")

    # Force services.bookmarks to fall through to get_bookmarks_path()
    _default_bm = tmp_path / "bookmarks.json"
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", _default_bm)
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE",
                        _default_bm)
    _default_rt = tmp_path / "routes.json"
    monkeypatch.setattr("services.route_store.ROUTES_FILE", _default_rt)
    monkeypatch.setattr("services.route_store._CONFIG_DEFAULT_ROUTES_FILE",
                        _default_rt)

    import importlib, main
    importlib.reload(main)
    return TestClient(main.app)


def test_status_default(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/cloud-sync/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["sync_folder"] is None
    assert body["bookmarks"]["count"] == 0
    assert body["routes"]["count"] == 0


def test_enable_with_custom_folder(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    custom = tmp_path / "fake-icloud"
    custom.mkdir()

    r = client.post("/api/cloud-sync/enable", json={"folder": str(custom)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["sync_folder"] == str(custom / "LocWarp")
    assert body["bookmarks"]["path"] == str(custom / "LocWarp" / "bookmarks.json")
    assert body["routes"]["path"] == str(custom / "LocWarp" / "routes.json")
    # The target folder exists on disk.
    assert (custom / "LocWarp").exists()


def test_enable_migrates_local_routes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    # Create a local route via the regular API first.
    cat_payload = {
        "id": "default", "name": "預設", "color": "#6c8cff",
        "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
    }
    (tmp_path / "routes.json").write_text(json.dumps({
        "categories": [cat_payload],
        "routes": [{
            "id": "r1", "name": "Loop", "category_id": "default",
            "engine": "osrm", "waypoints": [[1.0, 1.0]],
            "geometry": [[1.0, 1.0]], "duration_s": 1.0, "distance_m": 1.0,
            "created_at": "2026-05-12T00:00:00+00:00",
        }],
    }))

    custom = tmp_path / "fake-icloud"
    custom.mkdir()
    r = client.post("/api/cloud-sync/enable", json={"folder": str(custom)})
    assert r.status_code == 200, r.text
    assert (custom / "LocWarp" / "routes.json").exists()
    assert not (tmp_path / "routes.json").exists()


def test_disable_moves_back(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    custom = tmp_path / "fake-icloud"
    custom.mkdir()
    client.post("/api/cloud-sync/enable", json={"folder": str(custom)})
    r = client.post("/api/cloud-sync/disable")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["sync_folder"] is None


def test_enable_rollback_on_failure(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    # Seed local bookmarks so migrate_pair has work to do.
    (tmp_path / "bookmarks.json").write_text(json.dumps({
        "categories": [{
            "id": "default", "name": "預設", "color": "#6c8cff",
            "sort_order": 0, "created_at": "2026-05-12T00:00:00+00:00",
        }],
        "bookmarks": [{
            "id": "a", "name": "A", "lat": 1.0, "lng": 1.0,
            "category_id": "default",
            "created_at": "2026-05-12T00:00:00+00:00",
        }],
    }))
    # Inject failure in migrate_pair.
    import services.cloud_sync as cs
    orig = cs._move_or_merge_file
    def boom(src, dst, kind):
        if kind == "routes":
            raise OSError("boom")
        return orig(src, dst, kind)
    monkeypatch.setattr(cs, "_move_or_merge_file", boom)

    custom = tmp_path / "fake-icloud"
    custom.mkdir()
    r = client.post("/api/cloud-sync/enable", json={"folder": str(custom)})
    assert r.status_code == 500, r.text

    # Settings must not record the failed enable.
    settings = json.loads((tmp_path / "settings.json").read_text())
    assert settings.get("sync_folder") is None
    # Local file must still be intact.
    assert (tmp_path / "bookmarks.json").exists()


def test_dismiss_prompt(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.post("/api/cloud-sync/dismiss-prompt")
    assert r.status_code == 200
    assert r.json()["prompt_dismissed"] is True
```

- [ ] **Step 2: Run tests; confirm they fail**

```bash
cd backend && python -m pytest tests/test_cloud_sync_unified_api.py -v
```
Expected: 404 on every route (router not mounted yet).

- [ ] **Step 3: Implement the new router**

Create `backend/api/cloud_sync.py`:

```python
"""Top-level cloud-sync router covering bookmarks + routes.

Single toggle, single synced folder under <iCloud Drive>/LocWarp/.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

import config as _config
from models.schemas import (
    CloudSyncEnableRequest, CloudSyncResource, CloudSyncStatus,
)
from services.cloud_sync import (
    detect_icloud_path, migrate_pair, setup_sync_folder,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cloud-sync", tags=["cloud-sync"])


def _resource(path: Path, count: int, category_count: int) -> CloudSyncResource:
    return CloudSyncResource(
        path=str(path), count=count, category_count=category_count,
    )


def _build_status() -> CloudSyncStatus:
    from main import app_state
    bm = app_state.bookmark_manager
    rm = app_state.route_manager
    bm_path = bm._bookmarks_path()
    rt_path = rm._routes_path()
    icloud = detect_icloud_path()
    return CloudSyncStatus(
        enabled=app_state._sync_folder is not None,
        sync_folder=app_state._sync_folder,
        detected_icloud_path=str(icloud) if icloud else None,
        prompt_dismissed=app_state._cloud_sync_dismissed,
        bookmarks=_resource(
            bm_path,
            count=len(bm.list_bookmarks()),
            category_count=len(bm.list_categories()),
        ),
        routes=_resource(
            rt_path,
            count=len(rm.list_routes()),
            category_count=len(rm.list_categories()),
        ),
    )


@router.get("/status", response_model=CloudSyncStatus)
async def cloud_sync_status():
    return _build_status()


@router.post("/enable", response_model=CloudSyncStatus)
async def cloud_sync_enable(req: CloudSyncEnableRequest):
    from main import app_state
    if req.folder:
        parent = Path(req.folder)
    else:
        parent = detect_icloud_path()
    if parent is None:
        raise HTTPException(
            400, "No iCloud Drive detected and no custom folder provided"
        )
    try:
        target_folder = setup_sync_folder(parent)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(400, str(exc))

    try:
        migrate_pair(_config.DATA_DIR, target_folder)
    except Exception as exc:
        logger.exception("cloud-sync enable: migrate_pair failed")
        raise HTTPException(500, f"Migration failed: {exc}")

    app_state._sync_folder = str(target_folder)
    app_state.save_settings()

    # Re-init managers so they pick up the new path; rebind watchers.
    from services.bookmarks import BookmarkManager
    from services.route_store import RouteManager
    app_state.bookmark_manager = BookmarkManager()
    app_state.route_manager = RouteManager()
    app_state.restart_bookmark_watcher()
    app_state.restart_route_watcher()

    return _build_status()


@router.post("/disable", response_model=CloudSyncStatus)
async def cloud_sync_disable():
    from main import app_state
    if app_state._sync_folder is None:
        return _build_status()

    current = Path(app_state._sync_folder)
    try:
        migrate_pair(current, _config.DATA_DIR)
    except Exception as exc:
        logger.exception("cloud-sync disable: migrate_pair failed")
        raise HTTPException(500, f"Migration failed: {exc}")

    app_state._sync_folder = None
    app_state.save_settings()

    from services.bookmarks import BookmarkManager
    from services.route_store import RouteManager
    app_state.bookmark_manager = BookmarkManager()
    app_state.route_manager = RouteManager()
    app_state.restart_bookmark_watcher()
    app_state.restart_route_watcher()

    return _build_status()


@router.post("/dismiss-prompt", response_model=CloudSyncStatus)
async def cloud_sync_dismiss_prompt():
    from main import app_state
    app_state._cloud_sync_dismissed = True
    app_state.save_settings()
    return _build_status()
```

- [ ] **Step 4: Mount the router in `backend/main.py`**

Find the `app.include_router(...)` block (around line 806–814). Add:

```python
from api.cloud_sync import router as cloud_sync_router
# ... after the other include_router calls
app.include_router(cloud_sync_router)
```

- [ ] **Step 5: Run the new tests; confirm they pass**

```bash
cd backend && python -m pytest tests/test_cloud_sync_unified_api.py -v
```
Expected: all 6 pass.

- [ ] **Step 6: Commit**

```bash
git add backend/api/cloud_sync.py backend/main.py backend/tests/test_cloud_sync_unified_api.py
git commit -m "feat(api): top-level /api/cloud-sync router covering bookmarks + routes"
```

---

## Task 9: Remove legacy cloud-sync endpoints from `api/bookmarks.py`

**Files:**
- Modify: `backend/api/bookmarks.py`
- Delete: `backend/tests/test_cloud_sync_api.py`

- [ ] **Step 1: Delete the obsolete test file**

```bash
git rm backend/tests/test_cloud_sync_api.py
```

- [ ] **Step 2: Strip cloud-sync code from `backend/api/bookmarks.py`**

Open the file and remove these blocks:

1. The `_merge_local_into_remote` function (lines ~60–98).
2. The `# ── Cloud sync ───` section and the four `@router.get/post("/cloud-sync/*")` handlers (lines ~334 to end of that section).
3. Update the `models.schemas` import line to drop `CloudSyncStatus, CloudSyncEnableRequest`:

```python
from models.schemas import Bookmark, BookmarkCategory, BookmarkMoveRequest
```

4. Drop the `from services.cloud_sync import detect_icloud_path, setup_sync_folder, migrate_bookmarks` import (no longer used here).

- [ ] **Step 3: Run the full backend test suite**

```bash
cd backend && python -m pytest tests/ -v
```
Expected: all pass. `test_cloud_sync.py` (the service-level tests, not the API tests) should still pass because `migrate_bookmarks` was preserved as a wrapper.

- [ ] **Step 4: Commit**

```bash
git add backend/api/bookmarks.py
git commit -m "refactor(api): remove cloud-sync endpoints from bookmarks router"
```

---

## Task 10: Lifespan boots the route watcher

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Locate the lifespan block**

Find the spot where `bookmark_manager.start_watcher(_on_bookmark_change)` is called (around line 740) inside the FastAPI lifespan.

- [ ] **Step 2: Wire up the route watcher next to it**

Add right after the existing bookmark watcher start:

```python
    async def _on_route_change_async():
        await broadcast("routes_changed", {"reason": "external_update"})

    def _on_route_change():
        asyncio.run_coroutine_threadsafe(_on_route_change_async(), loop)

    app_state.route_manager.start_watcher(_on_route_change)
```

(Reuse the existing `loop = asyncio.get_running_loop()` if it is already in scope; otherwise grab it as the bookmark setup does.)

- [ ] **Step 3: Add `stop_watcher` in the shutdown branch**

Find the `try: app_state.bookmark_manager.stop_watcher()` block (around line 750). Add a parallel guard:

```python
        try:
            app_state.route_manager.stop_watcher()
        except Exception:
            logger.exception("route watcher stop_watcher failed during shutdown")
```

- [ ] **Step 4: Run lifespan-related tests**

```bash
cd backend && python -m pytest tests/test_lifespan.py tests/test_route_watcher.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat(main): start route watcher in lifespan; broadcast routes_changed"
```

---

## Task 11: Frontend type + component + i18n

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/CloudSyncSection.tsx`
- Modify: `frontend/src/i18n/strings.ts`

- [ ] **Step 1: Update `CloudSyncStatus` type and endpoint URLs in `api.ts`**

Find the existing `CloudSyncStatus` type and the four cloud-sync functions. Replace with:

```ts
export type CloudSyncResource = {
  path: string
  count: number
  category_count: number
}

export type CloudSyncStatus = {
  enabled: boolean
  sync_folder: string | null
  detected_icloud_path: string | null
  prompt_dismissed: boolean
  bookmarks: CloudSyncResource
  routes: CloudSyncResource
}

export async function cloudSyncStatus(): Promise<CloudSyncStatus> {
  const r = await fetch(`${API_BASE}/api/cloud-sync/status`)
  if (!r.ok) throw new Error(`cloud-sync status ${r.status}`)
  return r.json()
}

export async function cloudSyncEnable(folder?: string): Promise<CloudSyncStatus> {
  const r = await fetch(`${API_BASE}/api/cloud-sync/enable`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ folder: folder ?? null }),
  })
  if (!r.ok) throw new Error(`cloud-sync enable ${r.status}: ${await r.text()}`)
  return r.json()
}

export async function cloudSyncDisable(): Promise<CloudSyncStatus> {
  const r = await fetch(`${API_BASE}/api/cloud-sync/disable`, { method: 'POST' })
  if (!r.ok) throw new Error(`cloud-sync disable ${r.status}`)
  return r.json()
}

export async function cloudSyncDismissPrompt(): Promise<CloudSyncStatus> {
  const r = await fetch(`${API_BASE}/api/cloud-sync/dismiss-prompt`, { method: 'POST' })
  if (!r.ok) throw new Error(`cloud-sync dismiss-prompt ${r.status}`)
  return r.json()
}
```

(If the current code uses different URL helpers, match the local convention — the key change is `/api/cloud-sync/*` and the nested status shape.)

- [ ] **Step 2: Update `CloudSyncSection.tsx`**

Find lines around 106–115 that read `status.bookmark_count`, `status.category_count`. Replace with:

```tsx
{status.enabled && status.sync_folder && (
  <div className="cloud-sync-detail">
    <div>{t('cloud_sync.detail_path', { path: status.sync_folder })}</div>
    <div>
      {t('cloud_sync.detail_counts', {
        bookmarks: status.bookmarks.count,
        bookmark_categories: status.bookmarks.category_count,
        routes: status.routes.count,
        route_categories: status.routes.category_count,
      })}
    </div>
  </div>
)}
```

- [ ] **Step 3: Update i18n strings**

In `frontend/src/i18n/strings.ts`, replace the `cloud_sync.detail_counts` and `cloud_sync.discovery_prompt` entries:

```ts
'cloud_sync.detail_counts': {
  zh: '{bookmarks} 個書籤 · {bookmark_categories} 個分類 · {routes} 條路線 · {route_categories} 個路線分類',
  en: '{bookmarks} bookmarks · {bookmark_categories} categories · {routes} routes · {route_categories} route categories',
},
'cloud_sync.discovery_prompt': {
  zh: '偵測到 iCloud Drive。是否透過 iCloud Drive 在所有登入此 Apple ID 的裝置間同步 LocWarp 書籤與路線?',
  en: 'iCloud Drive detected. Use it to sync your LocWarp bookmarks and routes across all devices signed in to this Apple ID?',
},
```

- [ ] **Step 4: Run the frontend type check / unit tests**

```bash
cd frontend && npm run typecheck && npm test --silent
```
Expected: pass. Fix any leftover references to `status.bookmark_count` or `status.current_path` that the compiler flags.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/CloudSyncSection.tsx frontend/src/i18n/strings.ts
git commit -m "feat(frontend): unified cloud sync status with bookmarks + routes"
```

---

## Task 12: Full test sweep + manual macOS verification

- [ ] **Step 1: Run the entire backend test suite**

```bash
cd backend && python -m pytest tests/ -v
```
Expected: all green. If anything fails, fix it before continuing.

- [ ] **Step 2: Run frontend tests**

```bash
cd frontend && npm test --silent
```
Expected: green.

- [ ] **Step 3: Manual verification on macOS**

Boot the app (`./start.sh`) on a machine with iCloud Drive enabled. Run these checks:

1. Open the Cloud Sync section. Toggle on. Confirm the toast appears.
2. Inspect `~/Library/Mobile Documents/com~apple~CloudDocs/LocWarp/` — both `bookmarks.json` and `routes.json` should be present.
3. Add a saved route through the UI; confirm `routes.json` in the iCloud folder updates within a few seconds.
4. From a second terminal, write a tweak to `routes.json` directly (e.g., add a category via a JSON editor). Confirm the frontend receives a `routes_changed` event and refreshes the route list without a page reload.
5. Toggle Cloud Sync off. Confirm both files move back to `~/.locwarp/` and the iCloud folder is empty (the `LocWarp` directory itself may remain).

- [ ] **Step 4: Verify legacy upgrade path**

In a separate test profile:

1. Set `~/.locwarp/settings.json` to `{"bookmarks_path": "/Users/<you>/Library/Mobile Documents/com~apple~CloudDocs/LocWarp/bookmarks.json"}` (with the file pre-existing in that folder).
2. Put any saved route into `~/.locwarp/routes.json`.
3. Start the app.
4. Confirm `settings.json` now has `sync_folder` (not `bookmarks_path`) and the iCloud folder gained `routes.json`.

- [ ] **Step 5: Commit any fixes from the sweep, push the branch**

```bash
git status  # confirm clean working tree
git log --oneline main..HEAD
```

Confirm commit history is logically ordered. Optionally run `/rewrite-commits` per the project's PR workflow.

---

## Notes for the implementer

- **Pydantic v2:** This project is on Pydantic v2 (`model_dump`, `model_dump_json`). Don't use v1 idioms (`dict()`, `json()`).
- **`safe_load_json` / `safe_write_json`:** Always go through these helpers — they handle parse errors, atomic writes, and corrupt-file quarantine.
- **No `os.geteuid` / sudo concerns here.** This work runs entirely in the user-context backend after the tunnel-helper split.
- **Watcher self-write debounce:** The bookmark pattern uses `_last_loaded_mtime` updated inside `_save`. The route version in Task 5 follows the same scheme. If a route self-write still fires the callback in your manual test, double-check that `_save` updated `_last_loaded_mtime` to the post-write mtime.
- **`migrate_pair` rollback ordering:** Snapshot src files first, attempt the operation, restore on failure. The snapshot directory uses `tempfile.mkdtemp` and is cleaned up in `finally`.
