# Bookmark Cloud Sync via OS-Level Drive

**Date:** 2026-05-11
**Status:** Design — pending implementation plan
**Author:** Ravi Wu (with Claude Code brainstorming)

## Problem

LocWarp stores bookmarks in a local JSON file (`~/.locwarp/bookmarks.json`).
A user running LocWarp on multiple laptops (e.g., one main, one test rig) has
no way to share bookmarks across devices without manually exporting and
importing files. The existing import/export feature solves the *one-shot
transfer* problem, but not the *ongoing sync* problem.

## Goal

A single user signed into the same Apple ID (or other OS cloud account)
across multiple devices should see the same bookmark library on every
device, with minimal setup and no manual export / import clicks.

### Non-goals

- Multi-tenant sharing or public bookmark catalogs (separate concern,
  already partially served by the bundled `catalog.json`).
- Real-time collaborative editing between different humans on different
  Apple IDs.
- Building any sync server, account system, or sync protocol.
- Conflict-free CRDT or append-only event log: too much implementation
  surface for this use case.

## Approach

Use the operating system's existing cloud sync (iCloud Drive, Google Drive
desktop, OneDrive, Dropbox) as the transport layer. LocWarp only reads and
writes a single JSON file at a path inside one of these synced folders. The
OS handles cross-device transfer. LocWarp handles three new concerns:

1. **Configurable storage path** — point bookmarks at a synced folder.
2. **Reactive reload** — watch the file for external changes and refresh
   the UI without manual reload.
3. **Optimistic concurrency with merge** — detect stale writes; reapply
   the local user's pending edits on top of the freshly synced state so
   nothing is lost.

### Architecture

```
┌─────────────────┐  iCloud Drive / OneDrive / Google Drive  ┌─────────────────┐
│   Laptop A      │  ←───────  automatic two-way sync ─────→ │   Laptop B      │
│  ┌───────────┐  │                                          │  ┌───────────┐  │
│  │ LocWarp   │  │      <sync-folder>/LocWarp/bookmarks.json│  │ LocWarp   │  │
│  │  Backend  │  │              ↑                           │  │  Backend  │  │
│  │           │  │      ┌───────┴───────┐                   │  │           │  │
│  │ watchdog ─┼──┼──→ detect mtime change ──→ merge + reload│  │ watchdog  │  │
│  │ save() ───┼──┼──→ stale-check ──→ merge or write       │  │ save()    │  │
│  └───────────┘  │                                          │  └───────────┘  │
└─────────────────┘                                          └─────────────────┘
```

## Components

### 1. Path resolution and detection

**Module:** `backend/services/cloud_sync.py` (new)

**Responsibilities:**

- Detect standard iCloud Drive path on the current OS.
- Auto-create the `LocWarp/` subfolder when sync is enabled.
- Provide a path-validation helper for custom folders (writable, reachable).

**Detected paths:**

| OS      | Standard path                                                          |
|---------|------------------------------------------------------------------------|
| macOS   | `~/Library/Mobile Documents/com~apple~CloudDocs/`                      |
| Windows | `%USERPROFILE%\iCloudDrive\`                                           |

**Public API:**

```python
def detect_icloud_path() -> Path | None
def setup_sync_folder(path: Path) -> Path        # creates <path>/LocWarp/, returns subfolder
def migrate_bookmarks(src: Path, dst: Path) -> None
```

### 2. Configurable bookmarks path

**Module:** `backend/config.py` (modify)

`BOOKMARKS_FILE` becomes a function or lazy property that reads from
`~/.locwarp/settings.json` under a new key `bookmarks_path`. Default
remains `~/.locwarp/bookmarks.json` when key is absent. `BookmarkManager`
is unchanged structurally; only the path source moves.

### 3. File watcher

**Module:** `backend/services/bookmarks.py` (modify)

Add `watchdog>=3.0` to `requirements.txt`. On `BookmarkManager.__init__`,
start an `Observer` watching the parent directory of the bookmarks file.

**Handler logic** (debounced 500 ms):

```
on_modified(event):
    if event.src_path != self._bookmarks_path: return
    if disk size == 0: return                     # iCloud placeholder
    if disk content == self.store: return         # echo of our own write
    self._merge_from_disk()
```

`_merge_from_disk` runs the merge algorithm (see Section 4), updates
`self.store`, persists if any local pending diff was reapplied, and pushes
a `bookmarks_changed` event over the existing WebSocket channel.

### 4. Optimistic concurrency and merge

**Module:** `backend/services/bookmarks.py` (modify)

**New state on `BookmarkManager`:**

```python
self._last_loaded_mtime: float
self._last_loaded_snapshot: BookmarkStore   # deep copy of store after each successful load
```

**On every `_save`:**

```
current_mtime = stat(disk).st_mtime
if current_mtime > self._last_loaded_mtime:
    self._merge_from_disk()           # merge first, then write
atomic write
self._last_loaded_mtime = new_mtime
self._last_loaded_snapshot = deep copy of self.store
```

**Diff algorithm (UUID-based):**

For `categories` and `bookmarks` lists independently:

```
created  = items in current_state but not in baseline (by id)
deleted  = ids in baseline but not in current_state
modified = items in both where any field differs
```

**Merge algorithm — local intent wins:**

```
local_diff = diff(self.store, self._last_loaded_snapshot)
fresh_disk = load(disk)
merged = deep copy of fresh_disk
for item in local_diff.created:
    if item.id not in merged: merged.append(item)
for item in local_diff.modified:
    if item.id in merged: merged.replace(item)
    else: merged.append(item)            # remote deleted it; local modify revives
for id in local_diff.deleted:
    merged.remove(id)                    # local delete wins over remote modify
self.store = merged
self._last_loaded_snapshot = deep copy of merged
```

**Edge case matrix:**

| Scenario                                              | Result                                              |
|-------------------------------------------------------|-----------------------------------------------------|
| A adds bookmark X; B adds bookmark Y                  | Merged has both X and Y                             |
| A modifies bookmark Z; B modifies bookmark Z          | A wins; B's edits to Z lost (trade-off, disclosed)  |
| A deletes Q; B modifies Q                             | Q removed                                           |
| A modifies Q; B deletes Q                             | Q restored with A's edits                           |
| Both add category named "Favorites" (different UUIDs) | Two categories appear; manual cleanup by user       |
| iCloud `.icloud` placeholder (size 0)                 | Watcher ignores; waits for next mtime event         |
| Self-echo write                                       | Detected via content compare; ignored               |

## UX

### Settings page — Cloud Sync block

```
☁️  Cloud Sync
[●─] Sync via iCloud Drive
   ✓ Detected: ~/Library/Mobile Documents/com~apple~CloudDocs/LocWarp/
   Last synced: 3 seconds ago · 24 bookmarks across 3 categories
   [ Use custom folder instead... ]

[ ] Sync disabled (bookmarks stored locally only)
```

### Auto-discovery on subsequent devices

On `BookmarkManager.__init__`, if no `bookmarks_path` is configured AND
`<icloud>/LocWarp/bookmarks.json` exists, show a one-time modal:

> Synced LocWarp bookmarks detected in iCloud. Use them on this device?
> [Use synced] [Keep local only]

Choice is recorded in `settings.json` and not asked again.

### Notifications

Re-use the existing toast / notification system:

- `Synced from another device · N changes` — after a watcher-triggered reload with no local pending edits.
- `Your edits kept, merged N changes from another device` — after a merge that reapplied a local diff.
- `Cloud sync paused (sync folder unreachable)` — when watcher cannot reach the path (folder moved or unmounted).

### Migration flow (first-time enable)

1. User toggles **Sync via iCloud Drive**.
2. Modal: "Move N existing bookmarks to iCloud? They will sync across all your devices." [Move] [Cancel]
3. Atomic copy → verify checksum → delete source → update `settings.json` → re-init `BookmarkManager`.
4. On failure: rollback (restore source, clear setting), show error toast.

## Testing

| Category         | Test                                                                          | Tooling                       |
|------------------|-------------------------------------------------------------------------------|-------------------------------|
| Path detection   | macOS iCloud path detected when folder exists                                 | pytest + tmp_path             |
| Path detection   | macOS iCloud path returns None when folder absent                             | pytest + tmp_path             |
| Path detection   | Windows iCloud path detected                                                  | pytest + monkeypatch platform |
| Migration        | Move bookmarks.json from local to sync folder, verify content equal           | pytest + tmp_path             |
| Migration        | Migration failure rolls back cleanly                                          | pytest + monkeypatch write    |
| Diff             | Detect created bookmarks                                                      | pytest                        |
| Diff             | Detect deleted bookmarks (tombstone semantics)                                | pytest                        |
| Diff             | Detect modified bookmarks (field-level comparison)                            | pytest                        |
| Diff             | Diff for categories mirrors bookmark diff                                     | pytest                        |
| Merge            | A's create + B's create on disjoint ids → both kept                           | pytest                        |
| Merge            | A modifies, B modifies same id → A wins                                       | pytest                        |
| Merge            | A deletes, B modifies same id → deletion wins                                 | pytest                        |
| Merge            | A modifies, B deletes same id → A's modify restores                           | pytest                        |
| Stale write      | `mtime > _last_loaded_mtime` triggers merge before write                      | pytest + monkeypatch os.stat  |
| iCloud placeholder | size == 0 file does not overwrite in-memory store                           | pytest                        |
| Watcher          | External write triggers reload and WebSocket push                             | pytest + Mock observer        |
| Watcher          | Self-echo write does not trigger reload                                       | pytest + Mock observer        |
| Watcher          | Debounce coalesces rapid changes (~500 ms)                                    | pytest + freezegun            |
| E2E              | Two `BookmarkManager` instances on same file simulate two devices             | pytest                        |
| E2E              | Concurrent saves: one wins, other auto-merges, no data lost                   | pytest                        |

Approx 25 tests total. Existing bookmark tests should remain green.

## Dependencies

- `watchdog>=3.0` — cross-platform file watcher, ~30 KB, pure Python.

No frontend dependencies added; reuses existing settings panel, toast,
and WebSocket channel.

## Rollout

- Default behaviour unchanged for users who never enable cloud sync.
  All current code paths and tests continue to operate on
  `~/.locwarp/bookmarks.json`.
- Cloud sync is opt-in via a single toggle.
- Auto-discovery prompt appears at most once per device (`settings.json`
  records both "enabled" and "user said no").

## Risks and trade-offs

- **B's edits to a concurrently-modified bookmark are lost.** Accepted as
  a deliberate simplification for single-user-multi-device use case. The
  probability of two devices hitting the exact same record in the same
  sync window is small. Future work could add a per-field timestamp if
  needed.
- **iCloud sync latency** ranges from seconds to minutes depending on
  network and file activity. UI must not imply real-time sync. Toasts
  use the word "Synced", not "Live".
- **iCloud not enabled on Windows** is common; manual path picker covers
  the gap. Dropbox / Google Drive Desktop / OneDrive all work the same
  way through the manual picker.
- **`watchdog` adds a binary dependency.** Pure Python wheel, mature
  project, low risk.

## Open questions

- Should the auto-discovery modal also trigger when the user signs into
  iCloud after LocWarp is installed? (Probably check on every startup
  until either enabled or explicitly declined.)
- Settings page wording: "iCloud Drive" specifically vs "Cloud Drive"
  generically. Localisation note for `zh-TW` strings.
