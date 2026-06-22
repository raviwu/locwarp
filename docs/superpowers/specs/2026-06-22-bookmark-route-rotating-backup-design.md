# In-Process Rotating Backup (bookmarks + routes) — Design

**Date:** 2026-06-22
**Status:** Design — awaiting review
**Author:** Ravi + Claude

## Problem

A rotating local backup script already ships (`scripts/desktop_backup.py` + `make backup` +
`scripts/test_desktop_backup.py`), but **it was never running automatically**: the launchd agent
`~/Library/LaunchAgents/com.locwarp.desktop-backup.plist` is not installed, and
`~/.locwarp/backups/` does not exist. The script only ran on a manual `make backup`. This is the
root cause of the recent data-loss incident — the backup mechanism existed but nothing triggered it,
so there was no recovery point when the store got corrupted.

The fix is to make the backup run **reliably and automatically whenever LocWarp is open**, retuned to
the requested cadence and retention, without depending on a separate manual install step that can be
forgotten.

## Decisions (locked with Ravi, 2026-06-22)

| Decision | Choice |
|----------|--------|
| **Approach** | **In-process backend task** — a lifespan-owned asyncio loop. Runs whenever LocWarp runs, cross-platform (mac + win), committed & reproducible. No separate install. |
| **Trigger** | **Check every 5 min; archive only on change.** `latest` refreshed every tick; a timestamped snapshot kept only when bookmark/route data actually changed. |
| **Retention** | **Keep 3 days (72h)** of timestamped snapshots (matches the existing script's default; longer window, trivial disk cost since archiving is change-only). |
| **Scope** | **bookmarks + routes** (routes are sister data with the same loss risk; same mechanism). |

## Goals

1. While the backend runs, snapshot the live bookmark + route stores to `~/.locwarp/backups/` on a
   5-minute cadence, **archiving a timestamped copy only when the data changed**.
2. Always keep `~/.locwarp/backups/locwarp-latest-backup.json` current.
3. Prune timestamped snapshots older than 72h.
4. **Never clobber a good backup with an empty/degenerate snapshot** (transient iCloud eviction,
   startup before load).
5. Snapshots are restorable via `backend/merge_backup.py`: `make restore-backup` restores both
   stores from a combined snapshot (combined-detection added to `merge_backup.py`); per-store files
   via `make merge-bookmarks` / `make merge-routes`.
6. Behavior/API freeze honored: **no new HTTP/WS/IPC surface**, full pytest suite green after every
   commit, import-linter stays `7 kept, 0 broken`.

## Non-goals

- No in-app UI to list/trigger/restore snapshots (separate product decision; restore stays CLI/Makefile).
- No new HTTP/WS endpoint.
- Not removing `scripts/desktop_backup.py` / `make backup` — they stay as a manual on-demand tool
  (they write the **same** file format/dir, so they coexist with the in-process task with no conflict;
  no launchd agent is installed).

## File format & naming (matches the existing script — deliberate)

Backups live under `~/.locwarp/backups/` (a local dotfolder, **never** the iCloud sync_folder, so
they are local-only and not re-synced/clobbered). Two file kinds, identical to `desktop_backup.py`:

- `locwarp-latest-backup.json` — refreshed every tick, never a prune target.
- `locwarp-backup-<YYYYMMDD-HHMMSS>.json` — written only on data change; pruned past 72h.

Payload shape (combined, restore-compatible):

```json
{
  "_backup_meta": {
    "captured_at": "2026-06-22T14:30:00+08:00",
    "source": "in-process",
    "bookmark_count": 105,
    "route_count": 12,
    "note": "Insurance snapshot of LocWarp live state. 'bookmarks' and 'routes' are each re-importable."
  },
  "bookmarks": { "categories": [ ... ], "bookmarks": [ ... ] },
  "routes":    { "categories": [ ... ], "routes":    [ ... ] }
}
```

`bookmarks` is the `{categories, bookmarks}` whole-store shape (`bookmark_export.to_json`,
`services/bookmark_export.py:116`); `routes` is the `{categories, routes}` bundle that
`GET /api/route/saved/export` emits and `POST /saved/import` accepts (`api/route.py:84-105`).
Restore: `make restore-backup` (`merge_backup.restore_combined_snapshot`) auto-detects the combined
shape and folds **both** sub-stores into their live paths via `merge_stores` in one pass. (Per-store
files still restore via `make merge-bookmarks` / `make merge-routes`.)

## Architecture (Pragmatic Hexagonal-lite — clean-arch rings respected)

Dependencies point inward only. New code spans four rings exactly like the existing
bookmark/route persistence, so no new import-linter contract is required (the existing 7 cover it).

```
domain/backup.py            (pure: fingerprint, stamp, prune policy, payload builder)   ← stdlib only
domain/ports/backup_repository.py  (BackupRepository Protocol)                          ← stdlib + typing
infra/persistence/backup_store.py  (FileBackupStore: atomic file I/O via json_safe)     ← stdlib + domain + services.json_safe
services/backup_service.py  (BackupService.tick(now): orchestration use-case)           ← domain + port (NO fastapi/infra)
bootstrap/factories.py      (make_backup_service: wires infra impl into the service)     ← composition root
main.py                     (lifespan loop + snapshot provider closure + mkdir)          ← composition root
```

`infra → services.json_safe` is an existing allowed edge (`infra/persistence/json_store.py:14`).
Only `bootstrap/` + `main.py` read `config` constants — the dir/interval/retention are injected.

### `domain/backup.py` (pure, fully unit-testable)

```python
LATEST_NAME = "locwarp-latest-backup.json"
SNAPSHOT_PREFIX = "locwarp-backup-"
SNAPSHOT_SUFFIX = ".json"
_STAMP_FMT = "%Y%m%d-%H%M%S"

def data_fingerprint(bookmarks: dict, routes: dict) -> str:
    """Canonical JSON of the data only (excludes _backup_meta) — 'changed' means the
    data changed, not that a tick passed. Mirrors desktop_backup._content_of."""
    return json.dumps({"bookmarks": bookmarks, "routes": routes}, sort_keys=True, ensure_ascii=False)

def build_snapshot(bookmarks: dict, routes: dict, now: datetime, source: str) -> dict: ...
def snapshot_stamp(now: datetime) -> str:            # now.strftime("%Y%m%d-%H%M%S")
def parse_snapshot_stamp(filename: str) -> datetime | None:  # None if it doesn't match the scheme
def select_stale_snapshots(filenames: list[str], now: datetime, retention_hours: int) -> list[str]:
    """Names whose embedded stamp is older than retention. Non-matching names (incl. LATEST_NAME)
    are never selected. Prune by embedded timestamp, NOT mtime (deterministic + iCloud-safe)."""
```

### `domain/ports/backup_repository.py`

```python
class BackupRepository(Protocol):
    def read_latest(self) -> dict | None: ...          # parsed locwarp-latest-backup.json, or None
    def write_latest(self, payload: dict) -> None: ...  # atomic
    def write_snapshot(self, payload: dict, stamp: str) -> Path: ...  # atomic; locwarp-backup-<stamp>.json
    def list_snapshot_names(self) -> list[str]: ...     # filenames matching the snapshot scheme
    def delete_snapshots(self, names: list[str]) -> list[str]: ...    # best-effort; returns deleted
```

### `infra/persistence/backup_store.py`

`FileBackupStore(dir_provider: Callable[[], Path])` implements the port. Writes go through
`services.json_safe.safe_write_json` (atomic temp + `os.replace`, parent mkdir). `read_latest` uses
`safe_load_json`. `delete_snapshots` is best-effort (swallows `OSError`, logs). Resolves the dir
lazily via `dir_provider()` so test isolation (conftest monkeypatch of `config.BACKUP_DIR`) works.

### `services/backup_service.py`

```python
class BackupService:
    def __init__(self, repo, snapshot_provider, retention_hours, source="in-process"): ...
    def tick(self, now: datetime) -> BackupTickResult:
        bookmarks, routes = self._snapshot_provider()           # {categories,bookmarks}, {categories,routes}
        bm, rt = len(bookmarks.get("bookmarks", [])), len(routes.get("routes", []))
        if bm == 0 and rt == 0:
            return BackupTickResult(skipped="empty")            # never clobber a good backup
        payload = build_snapshot(bookmarks, routes, now, self._source)
        prev = self._repo.read_latest()
        changed = prev is None or data_fingerprint(bookmarks, routes) != \
            data_fingerprint(prev.get("bookmarks", {}), prev.get("routes", {}))
        self._repo.write_latest(payload)                        # always
        if changed:
            self._repo.write_snapshot(payload, snapshot_stamp(now))
        stale = select_stale_snapshots(self._repo.list_snapshot_names(), now, self._retention_hours)
        deleted = self._repo.delete_snapshots(stale)
        return BackupTickResult(bm, rt, changed, len(deleted))
```

No fastapi, no infra import; raises domain errors only. `tick(now)` takes `now` as a parameter, so it
is deterministic and unit-testable with zero sleeping.

### Manager snapshot seams (consistent reads)

Add small public methods so the composition root never reaches into private state:

- `BookmarkManager.snapshot_export(self) -> dict` — `with self._store_lock:` builds
  `{categories, bookmarks}` via `model_dump(mode="json")`. The lock (a `threading.Lock` shared with the
  watcher Timer thread, `services/bookmarks.py:132`) guarantees no torn read against `_save` /
  `_watcher_tick`. Critical section is the dict build only.
- `RouteManager.snapshot_export(self) -> dict` — `{categories, routes}` from `list_categories()` /
  `list_routes()` (RouteManager has no lock; the watcher never writes — `route_store.py`).

### `main.py` lifespan wiring

- Runtime `config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)` next to `DATA_DIR.mkdir` (`main.py:771`).
- In `AppState.load_state` (after managers are built and the macOS helper has chowned `~/.locwarp`),
  build the provider closure + service:
  ```python
  def _provider():
      return self.bookmark_manager.snapshot_export(), self.route_manager.snapshot_export()
  self.backup_service = make_backup_service(_provider)
  ```
- Module-level loop (mirrors `_usbmux_presence_watchdog`):
  ```python
  async def _bookmark_backup_loop(service, *, interval_s, sleep=asyncio.sleep, now_provider=datetime.now):
      while True:
          try:
              service.tick(now_provider())
          except asyncio.CancelledError:
              raise
          except Exception:
              logger.exception("backup tick failed")
          await sleep(interval_s)
  ```
  Ticks immediately on start (instant baseline), then every 5 min.
- Start near `main.py:852`: `backup_task = asyncio.create_task(_bookmark_backup_loop(app_state.backup_service, interval_s=config.BACKUP_INTERVAL_S))`.
- Stop near `main.py:902-906`: `backup_task.cancel(); try: await backup_task except (CancelledError, Exception): pass`.

### `config.py` (import-pure constants)

```python
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_INTERVAL_S = 300          # 5 minutes
BACKUP_RETENTION_HOURS = 72      # 3 days
```

No new imports, no mkdir at import (created at runtime in lifespan, like `DATA_DIR`).

## Test isolation — HARD requirement

`backend/tests/conftest.py`'s autouse `_isolate_real_data_paths` MUST be extended to redirect
`config.BACKUP_DIR` → `tmp_path / "backups"` **in the same change** that adds the constant. Referencing
`config.BACKUP_DIR` lazily everywhere (never `from config import BACKUP_DIR`) means the monkeypatch
takes effect. This closes the exact hole that previously let a test corrupt the real iCloud data.

## Testing (danger-zone-test-first — tests precede implementation)

- `test_backup_domain.py` — fingerprint (changed / unchanged / meta-only-differs), stamp roundtrip,
  `select_stale_snapshots` at the 72h boundary (drop old, keep recent, ignore `latest` + non-matching).
- `test_backup_store.py` (infra) — atomic write produces valid JSON; `read_latest` roundtrip + `None`
  on missing/corrupt; `list_snapshot_names` filters to the scheme; `delete_snapshots` best-effort on an
  undeletable file.
- `test_backup_service.py` — `tick`: skip-on-empty (no file written), latest-always-refreshed,
  snapshot-only-on-change, prune-stale, restore-compatible payload shape, result counts.
- `test_backup_loop.py` — loop with injected `sleep` + `now_provider`: K ticks on changing data →
  K snapshots + latest; advancing `now` past 72h prunes; `CancelledError` exits cleanly.
- `test_lifespan.py` (extend) — `app_state.backup_service` is non-None inside `yield`; `backup_task` is
  cancelled on teardown.
- conftest guard extension verified (a backup test writes only under `tmp_path`).

Pin the exact collected count via `cd backend && .venv/bin/python -m pytest --collect-only -q` before
starting; keep it green + import-linter `7 kept, 0 broken` after every commit.

## Risks & mitigations (from the context scan)

| Risk | Mitigation |
|------|-----------|
| Torn read of the bookmark store (mutated by event loop + watcher Timer thread) | Snapshot via `BookmarkManager.snapshot_export()` under `_store_lock`; build dict under lock, write outside |
| Empty snapshot clobbers good backup (iCloud eviction / startup) | `tick` skips entirely when bm==0 and rt==0 |
| Backups written into the iCloud sync_folder get re-synced/clobbered | Always `~/.locwarp/backups/` (local), resolved via `config.BACKUP_DIR`, never `get_*_path()` |
| Prune deletes the wrong files | Scoped to `~/.locwarp/backups/` + strict `locwarp-backup-*` name scheme; `latest` never matches; prune by embedded timestamp |
| Test escapes isolation → corrupts real data | conftest guard extended for `BACKUP_DIR` in the same change |
| Backup task leaks across shutdown | Cancelled + awaited in lifespan teardown alongside `watchdog_task` |
| Two backup systems on one dir | In-process uses the identical format/dir as `desktop_backup.py`; no launchd agent installed; `make backup` remains a compatible manual tool |
