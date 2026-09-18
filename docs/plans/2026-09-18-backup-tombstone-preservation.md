# Backup tombstone preservation

**Status:** awaiting approval · **Date:** 2026-09-18 · **Trigger:** the 2026-09-18 store-loss incident

## Problem

Backups drop deletion history, so restoring one resurrects deleted bookmarks.

Measured during the incident:

| Writer | `_backup_meta.source` | bookmark tombstones | route tombstones |
|---|---|---|---|
| in-process `BackupService` (5 min) | `in-process` | **0** | **0** |
| `desktop_backup.py` (launchd, 60 s) | `http://127.0.0.1:8777` | **0** | 4 |
| live store (recovered from iCloud) | — | **13** | 5 |

Per the documented CRDT rule (alive iff no tombstone has `deleted_at >= item.updated_at`),
restoring a tombstone-less snapshot resurrects every deleted item on the next merge with any
peer still holding it. Silent data corruption, not a cosmetic gap.

### Root cause

Both snapshot feeds hand-build a dict listing two of the store's three fields:

- `services/bookmarks.py:622-629` `snapshot_export()` → `{categories, bookmarks}`
- `services/route_store.py:185-198` `snapshot_export()` → `{categories, routes}`

`BookmarkStore.tombstones` / `RouteStore.tombstones` already exist
(`models/schemas.py:320`, `:253`), so this is purely an export-side omission — no schema change.

The HTTP leg differs per store, which is why routes partially survived:
`GET /api/route/saved/export` → `RouteManager.export_json()` → `model_dump_json()` serializes
all three fields **by accident**; `GET /api/bookmarks` hand-builds `{categories, bookmarks}`.

### Two facts the incident corrected

1. **A launchd agent IS installed** (`~/Library/LaunchAgents/com.locwarp.desktop-backup.plist`,
   present in `launchctl list`). `CLAUDE.md` states "no launchd agent is installed" — stale, fix it.
2. **Two writers share `locwarp-latest-backup.json`** and overwrite each other (observed 18:17:31
   in-process, then 18:18:13 HTTP). That file's fidelity depends on who ran last.
3. Measured pytest baseline is **1315 collected / 1315 passed**, not the ~914 in `CLAUDE.md`.

## API decision

**Add one endpoint, `GET /api/bookmarks/store`** — surveyed first, per the repo rule.

All 15 bookmark routes and 14 route routes were enumerated. Neither existing candidate works:

- `GET /api/bookmarks` (`api/bookmarks.py:102`) is the UI list endpoint. Adding tombstones changes
  a contract the frontend consumes on every load — violates the behavior freeze for no benefit.
- `GET /api/bookmarks/export` (`:212`) is a user-facing download with `?format=json|markdown|geojson|csv`
  and per-category scoping. Its documented intent (`6e810ed`, `bd4b1ff`) is a shareable artifact,
  not a fidelity dump; tombstones would leak into markdown/CSV consumers.

`BookmarkManager.export_json()` (`services/bookmarks.py:618`) already produces the right shape but
has **zero call sites** — the new endpoint gives it its first caller. Treat it as new code, not
proven plumbing.

Routes need no endpoint: `GET /api/route/saved/export` already carries tombstones. Pin that with a
test so a future hand-built dict cannot silently undo it.

## Changes

Test-first. Each commit keeps the full suite green.

| # | File | Change |
|---|---|---|
| 1 | `tests/test_backup_tombstone_fidelity.py` | **NEW — the red test.** Delete an item, snapshot, restore into a peer that still holds it alive with a stale `updated_at`; assert it stays deleted. RED before the fix. |
| 2 | `services/bookmarks.py:622` | Add `"tombstones": [...]` inside the existing `with self._store_lock:` block. |
| 3 | `services/route_store.py:185` | Add `"tombstones": [...]` from the pre-bound `store` local, **not** `self.store`. |
| 4 | `tests/test_backup_snapshot_seam.py:10,:22` | Update the two exact key-set assertions (the only certain breakage) in the same commit. |
| 5 | `api/bookmarks.py` | New `@router.get("/store")` after `/export`. Call `export_json` via `asyncio.to_thread` — it takes a blocking `threading.Lock` the watcher holds during merges. |
| 6 | `scripts/desktop_backup.py:129` | Try `/api/bookmarks/store`, fall back to `/api/bookmarks` on 404. **`HTTPError` subclasses `URLError`** — the existing `except URLError` at `:131` would otherwise swallow the 404 and return 0. |
| 7 | `merge_backup.py` | Restore-side safety — see below. This is the part the critique proved is not optional. |
| 8 | `domain/backup.py:74-77` + `desktop_backup.py:156-158` | Fix the `_backup_meta.note` (identical strings) — it currently tells the reader to recover via the import endpoints, which **drop tombstones**. |
| 9 | design doc + `CLAUDE.md` | Record the behavior; correct the launchd and ~914 claims. |

## Restore-side safety (the critique's CRITICAL finding)

Once a backup carries tombstones, **`make restore-backup` can delete live items and says nothing.**
`_merge_store_into_live` only inspects `live.tombstones ∩ backup_ids` (`merge_backup.py:119-120`);
the backup's own tombstones flow straight into `merge_stores` and suppress live records.

This is exactly today's shape: the hand-restored-from-iCloud store is the *live* side.

Two required corrections, both verified by execution in the critique:

1. **Report what gets killed.** After computing `merged`, diff live-alive against merged-alive and
   print/return the ids. A restore that deletes live data must never be silent.
2. **Fix the `--force-restore` scope.** The originally proposed drop was keyed on `backup_ids`
   (ids the backup holds *alive*) — but the tombstones that destroy live data are precisely those
   for ids the backup does *not* hold alive, so it fixed nothing. Widen the keep-set to
   `backup_ids | live alive ids`.

Also make `DRY_RUN=1` the documented first step, and note that the `.bak-<timestamp>` sidecar
(`merge_backup.py:157-161`) is the recovery artifact when a restore does delete something.

## Known adjacent bug (recorded, not fixed here)

`merge_stores` builds `tomb_at` as one flat id→`deleted_at` map applied to both categories and
items; `Tombstone.kind` (`models/schemas.py:189`) is never consulted. `backend/static/catalog.json`
contains a real collision — `seed-sanga-stadium` is **both** a category id and a bookmark id — so
deleting one can suppress the other. Reachable with shipped data. Out of scope here (it is a merge
bug, not a backup bug) but it should get its own ticket.

## Backward compatibility

- **Old snapshots** (no `tombstones` key): safe. Both models default the field to `[]`, and
  `detect_store_cls` keys only off `bookmarks`/`routes`. Pinned by a new test.
- **Old builds / peer Mac**: pydantic `extra='ignore'` drops the unknown key. But the plan's original
  claim that nothing reaching the peer changes is **wrong** — a restore now writes the GC'd union of
  live+backup tombstones into `bookmarks.json`, which *is* the iCloud artifact the peer reads.
  Needs a test asserting the written file's tombstone set.
- **Frontend**: no file changes. `GET /api/bookmarks` shape is frozen and pinned by a guard test.
  Electron couples only to port 8777 — verified, no `/api/` route coupling.
- **GC**: the exported list is whatever was live at snapshot time (GC runs only inside `merge_stores`,
  i.e. on write — an idle store can export a >30-day tombstone). Restore applies the authoritative
  cutoff. Do **not** write "a snapshot can never carry a tombstone older than 30 days" into the docs.

## Verification

```bash
cd backend && .venv/bin/python -m pytest tests/test_backup_tombstone_fidelity.py -q   # STEP 1: MUST FAIL
cd backend && .venv/bin/python -m pytest -q                                           # after every commit: 1315+N passed
cd backend && .venv/bin/lint-imports                                                  # 7 kept, 0 broken
cd frontend && npx tsc --noEmit && npx vitest run && npx depcruise src --config .dependency-cruiser.cjs
```

> **Removed from the generated plan:** a bare `python -c` smoke test using `make_bookmark_manager()`
> with no `path_provider`. That falls back to `config.get_bookmarks_path()` → **the live iCloud
> store**, and its `create`/`delete` calls each `_save()`. It would have written to the
> just-recovered data. Any manual snippet must pass explicit `path_provider` /
> `baseline_path_provider` pointing at a tmp dir.

## Out of scope

- The `tomb_at` kind-collision bug (own ticket).
- Reconciling the two writers of `locwarp-latest-backup.json` (in-process vs launchd) — worth doing,
  but it is a retention/ownership question, not a fidelity one.
- Route category ordering differs between the two writers (`snapshot_export` sorts by `sort_order`,
  `export_json` does not), causing fingerprint churn. Pre-existing; document, do not fold in.

## Residual risk

Every existing file in `~/.locwarp/backups/` still has zero bookmark tombstones. The fix applies only
to snapshots taken after it ships. Until the first post-fix tick,
`~/.locwarp-rescue/20260918-1132/icloud-manual-restore/` remains the only tombstone-faithful copy.
