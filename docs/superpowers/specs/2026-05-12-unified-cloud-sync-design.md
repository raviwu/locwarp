# Unified Cloud Sync — Bookmarks + Routes

**Status:** Draft for review
**Author:** Ravi (with Claude)
**Date:** 2026-05-12
**Extends:** `2026-05-11-cloud-sync-via-os-drive-design.md` — that spec covered bookmarks only; this one generalises the model to bookmarks and routes.

## Problem

LocWarp's cloud sync covers only `bookmarks.json` today. Saved routes
(`routes.json`) live in `~/.locwarp/` and never leave the device. Users who
enabled iCloud sync for bookmarks expect routes to follow the same model:
one toggle, one synced folder, both files inside.

The current setting model (`bookmarks_path` in `settings.json`) is also
file-specific. Adding a parallel `routes_path` would multiply the schema
with every new file. The unified design replaces both with a single
`sync_folder` setting that all synced files derive from.

## Goals

- One user-facing toggle ("Cloud Sync") enables sync for both bookmarks and routes.
- Both files live under `<sync_folder>/{bookmarks,routes}.json` (default `<iCloud Drive>/LocWarp/`).
- Existing users on the old `bookmarks_path` setting upgrade silently on next launch.
- Routes get the same UX as bookmarks: union merge on enable, file watchdog for external edits, WebSocket notification to the frontend.
- All-or-nothing migration: a partial failure rolls back so the user never ends up with bookmarks synced but routes orphaned.

## Non-goals

- Syncing `recent_places.json`, `device_names.json`, or `settings.json`.
- Interactive conflict resolution UI (local-wins merge stays).
- iCloud detection on Linux.
- A conflict log or history view.

## Architecture

### Settings model

```jsonc
// Before
{ "bookmarks_path": "/.../iCloud Drive/LocWarp/bookmarks.json",
  "cloud_sync_dismissed": false }

// After
{ "sync_folder": "/.../iCloud Drive/LocWarp",
  "cloud_sync_dismissed": false }
```

- `sync_folder == null` → sync disabled; files live in `~/.locwarp/`.
- `sync_folder == "/path/to/folder"` → bookmarks and routes live at `<sync_folder>/bookmarks.json` and `<sync_folder>/routes.json`.
- The user never edits `sync_folder` by hand; the API owns the field.

### Path resolution

`backend/config.py`:

- `get_bookmarks_path()` — already exists; updated to read `sync_folder` (falls back to `DATA_DIR / "bookmarks.json"`). The legacy `bookmarks_path` key is honoured at read time during the migration window.
- `get_routes_path()` — new; mirror of the above for `routes.json`.

Path resolution runs on every `_load` / `_save`, not at construction time, so changes to `sync_folder` (via the API) take effect immediately on the next read or write.

### Manager changes

- `BookmarkManager` — no behaviour change; already calls `get_bookmarks_path()` per operation.
- `RouteManager` — switches from `from config import ROUTES_FILE` to `from config import get_routes_path` and resolves the path inside `_load` / `_save`.
- `RouteManager.start_watcher(on_change)` / `stop_watcher()` — new; mirrors `BookmarkManager.start_watcher`. Watches the resolved routes path, debounces and de-dupes self-writes via the same `_last_loaded_mtime` pattern, and fires `on_change` on external mtime changes after reconciliation.

### Generic merge helper

New: `backend/services/sync_merge.py`. Lifts the union-merge logic out of `api/bookmarks.py:_merge_local_into_remote` so it can serve both bookmarks and routes.

```python
def merge_stores(
    local_path: Path,
    remote_path: Path,
    *,
    model_cls: type[BaseModel],
    merger: Callable[[BaseModel, BaseModel], BaseModel],
) -> None:
    """Merge local file into remote using `merger`. Writes result to remote.
    Bookmarks and routes both use ID-based union merge, local wins on conflict."""
```

`bookmark_merge.merge_local_wins` stays as-is. `sync_merge` wraps it for the bookmark case and adds a route equivalent (same algorithm against `RouteStore`).

### Atomic pair migration

New helper in `backend/services/cloud_sync.py`:

```python
def migrate_pair(src_dir: Path, dst_dir: Path) -> None:
    """Move bookmarks.json + routes.json from src_dir to dst_dir.
    Union-merges when both sides have content. All-or-nothing:
    on any failure, restore src_dir to its original state and re-raise."""
```

Implementation sketch:
1. Snapshot any pre-existing files in `src_dir` (bookmarks, routes) to a temp directory.
2. For each file present in `src_dir`: call `sync_merge.merge_stores(src, dst, ...)` if `dst` exists, otherwise `shutil.copy2(src, dst)`.
3. If any step raises, restore from snapshot, remove any new files in `dst` that we created, re-raise.
4. On success, unlink `src` copies and drop the snapshot.

`migrate_bookmarks` is retained as a thin wrapper that calls `migrate_pair` with only the bookmark file present, so existing tests keep working.

### API surface

New module: `backend/api/cloud_sync.py`. Replaces the cloud-sync endpoints currently embedded in `api/bookmarks.py`.

```python
class CloudSyncResource(BaseModel):
    path: str
    count: int
    category_count: int

class CloudSyncStatus(BaseModel):
    enabled: bool
    sync_folder: str | None
    detected_icloud_path: str | None
    prompt_dismissed: bool
    bookmarks: CloudSyncResource
    routes: CloudSyncResource

class CloudSyncEnableRequest(BaseModel):
    folder: str | None = None  # absolute path; None = use detected iCloud
```

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/cloud_sync/status` | Returns the new shape. |
| POST | `/cloud_sync/enable` | Resolves `folder` (default = detected iCloud + `LOCWARP_SUBFOLDER`). Calls `migrate_pair(DATA_DIR, folder)`. On success writes `sync_folder` to `settings.json`. Returns updated status. |
| POST | `/cloud_sync/disable` | Calls `migrate_pair(current_sync_folder, DATA_DIR)`. Clears `sync_folder`. Returns updated status. |
| POST | `/cloud_sync/dismiss_prompt` | Unchanged. Sets `cloud_sync_dismissed=true`. |

`api/bookmarks.py` retains only bookmark CRUD; cloud-sync code is removed from it.

### Watcher refresh on settings change

`AppState` currently exposes `refresh_bookmark_watcher()` that stops and re-binds the bookmark watcher to the new resolved path. A parallel `refresh_route_watcher()` is added. Both `/cloud_sync/enable` and `/cloud_sync/disable` call them after `migrate_pair` succeeds and `sync_folder` is written, so the watchers immediately bind to the new directory without an app restart.

### Startup auto-migration

In `main.py:AppState._load_persisted_state`:

1. Read `settings.json`.
2. If `bookmarks_path` is set and `sync_folder` is not:
   - Compute `candidate = Path(bookmarks_path).parent`.
   - If `candidate` exists, set `sync_folder = candidate`, drop `bookmarks_path`, and call `migrate_pair(DATA_DIR, candidate)` so the local `routes.json` joins its bookmarks counterpart.
   - If `candidate` does not exist (cloud drive offline, folder deleted, etc.), keep `bookmarks_path` as-is, log a warning, skip migration. The user can re-enable from the UI later.
3. Persist the updated settings.

The migration is idempotent: re-running it is a no-op once `sync_folder` is set.

### WebSocket events

- Existing: `bookmarks_changed` on bookmark watchdog fire.
- New: `routes_changed` on route watchdog fire.

`main.py` lifespan starts both watchdogs and wires each to its broadcast handler.

## Data flow

```
[user clicks toggle]
        |
        v
POST /cloud_sync/enable {folder?}
        |
        v
resolve_folder() -> folder
        |
        v
migrate_pair(DATA_DIR, folder)
   |          |
   |       success → write sync_folder to settings.json
   |          |
   |          v
   |   BookmarkManager / RouteManager next read picks new path
   |          |
   |          v
   |   watchdogs already watching path (re-bound after settings write)
   |
   failure → rollback, raise → API returns 500 with detail; settings untouched
```

## Error handling

| Scenario | Behaviour |
| --- | --- |
| `migrate_pair` mid-step failure | Rollback src, delete partial dst writes, raise; `settings.json` unchanged. |
| Startup auto-migration failure | Log warning; keep legacy `bookmarks_path`; do not block app start. |
| `sync_folder` points at a missing directory at runtime (cloud offline) | Path resolver returns the configured path anyway; managers' `_load` treats a missing file as empty (existing behaviour). On next watchdog rebind, log warning. Do not auto-clear `sync_folder`. |
| Union merge parse failure (corrupt file) | Log warning, skip merge, treat as one-sided (existing bookmark behaviour). |
| Route id collision with different content | Local wins (same policy as bookmarks). |
| Watchdog catches the manager's own write | De-duped via `_last_self_write_mtime` (existing pattern). |

## Frontend changes

`frontend/src/components/CloudSyncSection.tsx`:
- Read `status.bookmarks.count` / `status.bookmarks.category_count` and `status.routes.count` / `status.routes.category_count`.
- Expand the `detail_counts` i18n string to include both pairs.
- Update `discovery_prompt` to mention bookmarks and routes.

`frontend/src/api.ts`: update the `CloudSyncStatus` type to the new shape.

`App.tsx`: no logic change. The existing toast and prompt flow continues to work.

## Test plan

| Layer | Coverage |
| --- | --- |
| Unit | `config.get_routes_path` (mirror existing bookmark test); `sync_merge.merge_stores` over BookmarkStore and RouteStore fixtures; `migrate_pair` for src-only, dst-only, both-match, both-conflict, failure-rollback. |
| Unit | `RouteManager.start_watching`: external mtime fires callback; self-write does not. |
| Unit | `AppState._load_persisted_state` auto-migration: legacy `bookmarks_path` with sync folder present; legacy `bookmarks_path` with sync folder missing; new `sync_folder` already set (no-op). |
| API | `test_cloud_sync_api.py`: status, enable (default + custom folder), enable rollback on injected merge failure, disable, dismiss. |
| Regression | Existing `test_bookmarks.py` cloud_sync_* tests pass after migration (move them into `test_cloud_sync_api.py`). |
| Manual (macOS) | Detect iCloud → enable → verify `LocWarp/{bookmarks,routes}.json` exist in iCloud Drive; add a saved route → confirm `routes.json` updates; edit `routes.json` externally → confirm `routes_changed` WebSocket fires. |

## Implementation order (TDD)

1. `config.get_routes_path` + test.
2. Switch `RouteManager` to `get_routes_path()`; existing route tests stay green.
3. `services/sync_merge.py` + tests (no call-site changes).
4. `cloud_sync.migrate_pair` + tests; `migrate_bookmarks` becomes a wrapper.
5. `RouteManager.start_watching` + tests.
6. `AppState._load_persisted_state` auto-migration + tests.
7. `api/cloud_sync.py` + `test_cloud_sync_api.py` (test-first).
8. Remove cloud-sync endpoints from `api/bookmarks.py`; mount the new router.
9. `main.py` lifespan: start the route watchdog and wire `routes_changed`.
10. Frontend: `api.ts` type, `CloudSyncSection.tsx`, `i18n/strings.ts`.
11. Run the full test suite; perform the macOS manual verification.

## File manifest

**New**

- `backend/services/sync_merge.py`
- `backend/api/cloud_sync.py`
- `backend/tests/test_sync_merge.py`
- `backend/tests/test_cloud_sync_api.py`
- `backend/tests/test_migrate_pair.py`
- `backend/tests/test_route_watchdog.py`
- `backend/tests/test_appstate_migration.py`

**Modified**

- `backend/config.py` — add `get_routes_path`.
- `backend/services/cloud_sync.py` — add `migrate_pair`; `migrate_bookmarks` becomes a wrapper.
- `backend/services/route_store.py` — use `get_routes_path`; add `start_watcher` / `stop_watcher`.
- `backend/services/bookmarks.py` — no behavioural change; consumed by `sync_merge`.
- `backend/models/schemas.py` — new `CloudSyncStatus` / `CloudSyncResource` / `CloudSyncEnableRequest` shape.
- `backend/api/bookmarks.py` — remove cloud-sync endpoints and helpers.
- `backend/main.py` — `AppState` switches to `sync_folder`; auto-migration; add `refresh_route_watcher`; start route watchdog in lifespan.
- `backend/tests/test_bookmarks.py` — move cloud_sync_* tests out.
- `frontend/src/api.ts` — `CloudSyncStatus` type.
- `frontend/src/components/CloudSyncSection.tsx` — read new fields.
- `frontend/src/i18n/strings.ts` — `detail_counts`, `discovery_prompt`.

**Unchanged**

- `backend/services/bookmark_merge.py` — wrapped by `sync_merge`; logic unchanged.
- `backend/api/route.py` — pure CRUD; no sync involvement.

## Open questions

None. All design decisions confirmed during brainstorming on 2026-05-12.
