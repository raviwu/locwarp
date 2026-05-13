# iCloud Eager Download on Startup

## Problem

When cloud sync is enabled and the user reopens LocWarp after iCloud Drive has
evicted `bookmarks.json` / `routes.json` from local storage, the user perceives
a multi-second lag between the panel rendering and the actual bookmark content
appearing.

Root cause — current sequence:

1. macOS iCloud evicts the file → local presence is `.bookmarks.json.icloud`
   placeholder; the real path doesn't exist locally.
2. Backend `BookmarkManager.__init__` runs in the FastAPI lifespan and calls
   `safe_load_json(bookmarks.json)` → `FileNotFoundError` → logs
   "No bookmark file; using defaults" → in-memory empty store.
3. Frontend mounts, `GET /api/bookmarks` returns an empty list immediately.
4. iCloud's fileproviderd downloads the file in the background.
5. The watcher fires → `_watcher_tick` reconciles → `bookmarks_changed`
   broadcast → frontend `refresh()` → real list appears.

The visible artefact is the "empty for a couple seconds, then content pops in"
flicker.

## Goal

Synchronously materialise the iCloud placeholder during backend startup so the
first `GET /api/bookmarks` (and `/api/routes`) already returns the real list.
If materialisation can't complete within a bounded timeout, fall through to
current behaviour (defaults + watcher catch-up). No frontend changes.

## Approach Survey

| Approach | Mechanism | Pros | Cons |
|---|---|---|---|
| `brctl download <path>` | Apple's iCloud Drive CLI; blocks until local copy is materialised. | Documented; simple to call; correct semantics. | macOS only; relies on external binary. |
| `NSFileCoordinator coordinateReadingItemAtURL:` via PyObjC | Cocoa file-coordinator API. | Native; no external process. | Heavy dep (PyObjC); not currently a dependency; macOS only too. |
| Passive `open(path)` | Just try to read. | Zero new code. | Doesn't work — when the placeholder exists but the real path doesn't, `open()` raises `FileNotFoundError` immediately; only triggers download when the path *does* exist as a stub (older iCloud behaviour). |

**Decision:** `brctl download` — simplest, no new Python dependency, works for
modern iCloud Drive's `.icloud` placeholder pattern. Silently no-op on
non-macOS hosts (which can't have iCloud placeholders anyway).

## Design

### New helper

```python
# backend/services/cloud_sync.py
def materialize_if_placeholder(path: Path, timeout_s: float = 10.0) -> None:
    """If *path* is an iCloud placeholder, request download and block.

    Detects either:
    - sibling ``.<name>.icloud`` placeholder file, or
    - *path* itself missing while the parent contains a placeholder sibling.

    No-op on non-macOS, when brctl is missing, when no placeholder is detected,
    or when the download command fails/times out (logs at WARNING and returns).
    """
```

Detection logic:

```python
parent = path.parent
placeholder = parent / f".{path.name}.icloud"
if not placeholder.exists():
    return  # not a placeholder situation; nothing to do
# Run: brctl download <placeholder-or-real-path>
# brctl accepts the canonical (non-placeholder) path in modern macOS;
# it materialises whichever form is on disk.
```

### Wire-up

Call `materialize_if_placeholder(self._bookmarks_path())` in
`BookmarkManager.__init__` immediately before `self._load()`. Same for
`RouteManager.__init__` with `_routes_path()`.

Manager construction already happens inside the lifespan startup hook
(`load_state()`), so a bounded wait there extends the time until uvicorn
accepts connections — but that is exactly the desired behaviour: the frontend's
first fetch will then return real data instead of empty defaults.

### Configuration

Environment variable `LOCWARP_ICLOUD_DOWNLOAD_TIMEOUT_S`. Default `10.0`.
Capped at `30.0` to prevent pathological hangs.

### Failure modes

| Condition | Behaviour |
|---|---|
| Not under iCloud (no placeholder sibling) | Skip silently. |
| `brctl` not found (non-macOS, or non-standard macOS) | Log debug, skip. |
| `brctl` exits non-zero | Log warning, fall through. |
| Timeout hit | Log warning, fall through. |

In every fall-through case, the existing watcher-driven reconcile path still
catches the download whenever it completes — so the worst case degrades to
current behaviour.

## Test plan

`backend/tests/test_icloud_materialize.py` (mocked subprocess; no real iCloud):

1. `test_no_placeholder_is_noop` — file exists, no `.icloud` sibling → `subprocess.run` not called.
2. `test_placeholder_triggers_brctl` — `.icloud` sibling present → `brctl download` invoked with the canonical path.
3. `test_timeout_does_not_raise` — `subprocess.run` raises `TimeoutExpired` → helper returns normally; warning logged.
4. `test_brctl_missing_does_not_raise` — `subprocess.run` raises `FileNotFoundError` → helper returns normally.
5. `test_non_zero_exit_does_not_raise` — `CompletedProcess` with returncode=1 → helper returns normally; warning logged.

Existing `test_sync_merge.py`, `test_migrate_pair.py`, `test_appstate_sync_migration.py` etc. must continue to pass — call sites in real code path will execute the helper but in tests under tmp paths no `.icloud` sibling exists, so it's a no-op.

## Out of scope

- Google Drive / OneDrive / Dropbox: those don't use placeholder semantics
  (files are always local-resident), so the lag this fixes does not exist
  for them. If we later see equivalent symptoms there, revisit.
- Frontend loading-spinner gate: A alone should mask the lag for the common
  case. If timeout-fallbacks become common in real usage, add a `pending`
  flag to `GET /api/cloud-sync/status` and let the UI render a spinner.
