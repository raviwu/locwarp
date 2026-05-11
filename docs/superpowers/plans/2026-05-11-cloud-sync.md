# Cloud Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in bookmark sync across devices via the OS cloud drive (iCloud / Drive / OneDrive / Dropbox) with watchdog-based reactive reload and optimistic concurrency merge.

**Architecture:** Pure diff/merge functions extracted to a new module. `BookmarkManager` keeps a baseline snapshot and disk mtime, runs a watchdog observer on the bookmarks file's parent folder, and reapplies local pending edits on stale writes. Path becomes configurable via existing `~/.locwarp/settings.json`. UI adds a Cloud Sync section to `SettingsModal` and surfaces `bookmarks_changed` WebSocket events as toasts.

**Tech Stack:** Python 3 / FastAPI / pydantic / pytest (backend); React / TypeScript (frontend); `watchdog` for file events.

**Spec:** `docs/superpowers/specs/2026-05-11-cloud-sync-via-os-drive-design.md`

---

## File Structure

**Create:**
- `backend/services/bookmark_merge.py` — pure diff & merge functions
- `backend/services/cloud_sync.py` — path detection, setup, migration helpers
- `backend/tests/test_bookmark_merge.py`
- `backend/tests/test_cloud_sync.py`
- `backend/tests/test_bookmark_concurrency.py` — watcher, stale-write, two-instance e2e
- `frontend/src/components/CloudSyncSection.tsx`

**Modify:**
- `backend/requirements.txt` — add `watchdog>=3.0`
- `backend/config.py` — `BOOKMARKS_FILE` becomes a function reading from settings
- `backend/main.py` — extend `AppState` settings persistence with `bookmarks_path`, `cloud_sync_dismissed`
- `backend/services/bookmarks.py` — track snapshot/mtime, integrate merge, start watcher, broadcast
- `backend/api/bookmarks.py` — add `/cloud-sync/*` endpoints
- `frontend/src/components/SettingsModal.tsx` — embed `<CloudSyncSection />`
- `frontend/src/services/api.ts` — add cloud sync API client methods
- `frontend/src/hooks/useWebSocket.ts` (callers) — handle `bookmarks_changed`

---

## Task 1: Add `watchdog` dependency

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements-dev.txt`

- [ ] **Step 1: Add watchdog to requirements.txt**

Append to `backend/requirements.txt`:

```
watchdog>=3.0
```

- [ ] **Step 2: Install and verify import**

Run:
```bash
cd backend && pip install -r requirements.txt
python -c "from watchdog.observers import Observer; from watchdog.events import FileSystemEventHandler; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "build(deps): add watchdog for file-event-driven bookmark reload"
```

---

## Task 2: Pure diff function for BookmarkStore

**Files:**
- Create: `backend/services/bookmark_merge.py`
- Create: `backend/tests/test_bookmark_merge.py`

- [ ] **Step 1: Write failing test for empty diff**

Create `backend/tests/test_bookmark_merge.py`:

```python
from datetime import datetime, timezone

from models.schemas import Bookmark, BookmarkCategory, BookmarkStore
from services.bookmark_merge import diff_store, StoreDiff


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store(categories=None, bookmarks=None) -> BookmarkStore:
    return BookmarkStore(
        categories=categories or [
            BookmarkCategory(id="default", name="預設", color="#000", sort_order=0, created_at=_ts())
        ],
        bookmarks=bookmarks or [],
    )


def _bm(id: str, name: str = "X", lat: float = 1.0, lng: float = 2.0, category_id: str = "default") -> Bookmark:
    return Bookmark(
        id=id,
        name=name,
        lat=lat,
        lng=lng,
        address="",
        category_id=category_id,
        created_at=_ts(),
        last_used_at=_ts(),
        country_code="",
    )


def test_diff_identical_stores_is_empty():
    a = _store()
    b = _store()
    d = diff_store(current=a, baseline=b)
    assert d == StoreDiff(
        bookmarks_created=[],
        bookmarks_modified=[],
        bookmarks_deleted=set(),
        categories_created=[],
        categories_modified=[],
        categories_deleted=set(),
    )
```

- [ ] **Step 2: Run test, verify it fails**

Run:
```bash
cd backend && pytest tests/test_bookmark_merge.py -v
```

Expected: FAIL (ImportError: cannot import name 'diff_store' from 'services.bookmark_merge')

- [ ] **Step 3: Implement minimal diff + StoreDiff**

Create `backend/services/bookmark_merge.py`:

```python
"""Pure diff and merge for BookmarkStore.

No I/O, no side effects, no logger. Two functions only:

- diff_store(current, baseline) -> StoreDiff
- merge_local_wins(remote, local_diff) -> BookmarkStore

Tested separately from BookmarkManager so persistence concerns do not
leak into the merge logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from models.schemas import Bookmark, BookmarkCategory, BookmarkStore


@dataclass
class StoreDiff:
    bookmarks_created: list[Bookmark] = field(default_factory=list)
    bookmarks_modified: list[Bookmark] = field(default_factory=list)
    bookmarks_deleted: set[str] = field(default_factory=set)
    categories_created: list[BookmarkCategory] = field(default_factory=list)
    categories_modified: list[BookmarkCategory] = field(default_factory=list)
    categories_deleted: set[str] = field(default_factory=set)

    def is_empty(self) -> bool:
        return not (
            self.bookmarks_created
            or self.bookmarks_modified
            or self.bookmarks_deleted
            or self.categories_created
            or self.categories_modified
            or self.categories_deleted
        )


def _by_id(items: Iterable) -> dict[str, object]:
    return {x.id: x for x in items}


def diff_store(current: BookmarkStore, baseline: BookmarkStore) -> StoreDiff:
    """Compute id-based diff of current vs baseline."""
    out = StoreDiff()

    cur_b = _by_id(current.bookmarks)
    base_b = _by_id(baseline.bookmarks)
    for bid, bm in cur_b.items():
        if bid not in base_b:
            out.bookmarks_created.append(bm)
        elif bm.model_dump() != base_b[bid].model_dump():
            out.bookmarks_modified.append(bm)
    for bid in base_b:
        if bid not in cur_b:
            out.bookmarks_deleted.add(bid)

    cur_c = _by_id(current.categories)
    base_c = _by_id(baseline.categories)
    for cid, cat in cur_c.items():
        if cid not in base_c:
            out.categories_created.append(cat)
        elif cat.model_dump() != base_c[cid].model_dump():
            out.categories_modified.append(cat)
    for cid in base_c:
        if cid not in cur_c:
            out.categories_deleted.add(cid)

    return out
```

- [ ] **Step 4: Run test, verify it passes**

Run:
```bash
cd backend && pytest tests/test_bookmark_merge.py -v
```

Expected: PASS

- [ ] **Step 5: Add more diff tests**

Append to `backend/tests/test_bookmark_merge.py`:

```python
def test_diff_detects_bookmark_created():
    baseline = _store()
    current = _store(bookmarks=[_bm("a")])
    d = diff_store(current=current, baseline=baseline)
    assert [b.id for b in d.bookmarks_created] == ["a"]
    assert not d.bookmarks_modified
    assert not d.bookmarks_deleted


def test_diff_detects_bookmark_deleted():
    baseline = _store(bookmarks=[_bm("a")])
    current = _store()
    d = diff_store(current=current, baseline=baseline)
    assert d.bookmarks_deleted == {"a"}
    assert not d.bookmarks_created
    assert not d.bookmarks_modified


def test_diff_detects_bookmark_modified():
    baseline = _store(bookmarks=[_bm("a", name="old")])
    current = _store(bookmarks=[_bm("a", name="new")])
    d = diff_store(current=current, baseline=baseline)
    assert len(d.bookmarks_modified) == 1
    assert d.bookmarks_modified[0].name == "new"


def test_diff_detects_category_changes():
    base_cat = BookmarkCategory(id="c1", name="A", color="#fff", sort_order=1, created_at=_ts())
    new_cat = BookmarkCategory(id="c2", name="B", color="#000", sort_order=2, created_at=_ts())
    baseline = _store(categories=[base_cat])
    current = _store(categories=[new_cat])
    d = diff_store(current=current, baseline=baseline)
    assert [c.id for c in d.categories_created] == ["c2"]
    assert d.categories_deleted == {"c1"}


def test_diff_is_empty_helper():
    a = _store()
    assert diff_store(current=a, baseline=a).is_empty()
```

Run and verify all pass:
```bash
cd backend && pytest tests/test_bookmark_merge.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/bookmark_merge.py backend/tests/test_bookmark_merge.py
git commit -m "feat(bookmarks): add pure diff function for BookmarkStore"
```

---

## Task 3: Pure merge function — local intent wins

**Files:**
- Modify: `backend/services/bookmark_merge.py`
- Modify: `backend/tests/test_bookmark_merge.py`

- [ ] **Step 1: Write failing tests for all merge edge cases**

Append to `backend/tests/test_bookmark_merge.py`:

```python
from services.bookmark_merge import merge_local_wins


def test_merge_both_added_disjoint_keeps_both():
    baseline = _store()
    local = _store(bookmarks=[_bm("a")])
    remote = _store(bookmarks=[_bm("b")])
    local_diff = diff_store(current=local, baseline=baseline)
    merged = merge_local_wins(remote=remote, local_diff=local_diff)
    ids = {b.id for b in merged.bookmarks}
    assert ids == {"a", "b"}


def test_merge_modify_modify_local_wins():
    baseline = _store(bookmarks=[_bm("z", name="orig")])
    local = _store(bookmarks=[_bm("z", name="local-edit")])
    remote = _store(bookmarks=[_bm("z", name="remote-edit")])
    local_diff = diff_store(current=local, baseline=baseline)
    merged = merge_local_wins(remote=remote, local_diff=local_diff)
    z = next(b for b in merged.bookmarks if b.id == "z")
    assert z.name == "local-edit"


def test_merge_local_delete_wins_over_remote_modify():
    baseline = _store(bookmarks=[_bm("q", name="orig")])
    local = _store()  # local deleted q
    remote = _store(bookmarks=[_bm("q", name="remote-edit")])
    local_diff = diff_store(current=local, baseline=baseline)
    merged = merge_local_wins(remote=remote, local_diff=local_diff)
    assert all(b.id != "q" for b in merged.bookmarks)


def test_merge_local_modify_restores_remote_delete():
    baseline = _store(bookmarks=[_bm("q", name="orig")])
    local = _store(bookmarks=[_bm("q", name="local-edit")])
    remote = _store()  # remote deleted q
    local_diff = diff_store(current=local, baseline=baseline)
    merged = merge_local_wins(remote=remote, local_diff=local_diff)
    q = next(b for b in merged.bookmarks if b.id == "q")
    assert q.name == "local-edit"


def test_merge_category_changes_same_semantics():
    baseline = _store()
    new_cat = BookmarkCategory(id="c1", name="Local", color="#fff", sort_order=1, created_at=_ts())
    local = _store(categories=[
        BookmarkCategory(id="default", name="預設", color="#000", sort_order=0, created_at=_ts()),
        new_cat,
    ])
    remote = _store()  # only default
    local_diff = diff_store(current=local, baseline=baseline)
    merged = merge_local_wins(remote=remote, local_diff=local_diff)
    cat_ids = {c.id for c in merged.categories}
    assert "c1" in cat_ids


def test_merge_no_local_changes_returns_remote_equivalent():
    baseline = _store(bookmarks=[_bm("a")])
    local = _store(bookmarks=[_bm("a")])
    remote = _store(bookmarks=[_bm("a"), _bm("b")])
    local_diff = diff_store(current=local, baseline=baseline)
    assert local_diff.is_empty()
    merged = merge_local_wins(remote=remote, local_diff=local_diff)
    ids = {b.id for b in merged.bookmarks}
    assert ids == {"a", "b"}
```

- [ ] **Step 2: Run tests, verify they fail**

Run:
```bash
cd backend && pytest tests/test_bookmark_merge.py -v -k merge
```

Expected: FAIL (ImportError on `merge_local_wins`)

- [ ] **Step 3: Implement merge_local_wins**

Append to `backend/services/bookmark_merge.py`:

```python
def merge_local_wins(remote: BookmarkStore, local_diff: StoreDiff) -> BookmarkStore:
    """Apply *local_diff* on top of *remote*, with local intent winning.

    Semantics:
    - created: append if id not already in remote.
    - modified: replace existing by id; if missing (remote deleted it),
      append back so local edits are not lost.
    - deleted: remove from remote; takes precedence over a remote modify.
    """
    out_categories = list(remote.categories)
    out_bookmarks = list(remote.bookmarks)

    cat_index = {c.id: i for i, c in enumerate(out_categories)}
    for cat in local_diff.categories_created:
        if cat.id not in cat_index:
            out_categories.append(cat)
            cat_index[cat.id] = len(out_categories) - 1
    for cat in local_diff.categories_modified:
        if cat.id in cat_index:
            out_categories[cat_index[cat.id]] = cat
        else:
            out_categories.append(cat)
            cat_index[cat.id] = len(out_categories) - 1
    if local_diff.categories_deleted:
        out_categories = [c for c in out_categories if c.id not in local_diff.categories_deleted]
        cat_index = {c.id: i for i, c in enumerate(out_categories)}

    bm_index = {b.id: i for i, b in enumerate(out_bookmarks)}
    for bm in local_diff.bookmarks_created:
        if bm.id not in bm_index:
            out_bookmarks.append(bm)
            bm_index[bm.id] = len(out_bookmarks) - 1
    for bm in local_diff.bookmarks_modified:
        if bm.id in bm_index:
            out_bookmarks[bm_index[bm.id]] = bm
        else:
            out_bookmarks.append(bm)
            bm_index[bm.id] = len(out_bookmarks) - 1
    if local_diff.bookmarks_deleted:
        out_bookmarks = [b for b in out_bookmarks if b.id not in local_diff.bookmarks_deleted]

    return BookmarkStore(categories=out_categories, bookmarks=out_bookmarks)
```

- [ ] **Step 4: Run all merge tests, verify they pass**

Run:
```bash
cd backend && pytest tests/test_bookmark_merge.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmark_merge.py backend/tests/test_bookmark_merge.py
git commit -m "feat(bookmarks): add merge_local_wins for optimistic concurrency"
```

---

## Task 4: iCloud path detection

**Files:**
- Create: `backend/services/cloud_sync.py`
- Create: `backend/tests/test_cloud_sync.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_cloud_sync.py`:

```python
from pathlib import Path

import pytest

from services.cloud_sync import detect_icloud_path


def test_detect_icloud_path_macos_returns_path_when_folder_exists(tmp_path, monkeypatch):
    monkeypatch.setattr("services.cloud_sync.sys.platform", "darwin")
    fake_home = tmp_path / "home"
    icloud = fake_home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    icloud.mkdir(parents=True)
    monkeypatch.setattr("services.cloud_sync.Path.home", staticmethod(lambda: fake_home))
    assert detect_icloud_path() == icloud


def test_detect_icloud_path_macos_returns_none_when_folder_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("services.cloud_sync.sys.platform", "darwin")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr("services.cloud_sync.Path.home", staticmethod(lambda: fake_home))
    assert detect_icloud_path() is None


def test_detect_icloud_path_windows_returns_path_when_folder_exists(tmp_path, monkeypatch):
    monkeypatch.setattr("services.cloud_sync.sys.platform", "win32")
    fake_home = tmp_path / "home"
    icloud = fake_home / "iCloudDrive"
    icloud.mkdir(parents=True)
    monkeypatch.setattr("services.cloud_sync.Path.home", staticmethod(lambda: fake_home))
    assert detect_icloud_path() == icloud


def test_detect_icloud_path_unsupported_platform_returns_none(monkeypatch):
    monkeypatch.setattr("services.cloud_sync.sys.platform", "linux")
    assert detect_icloud_path() is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run:
```bash
cd backend && pytest tests/test_cloud_sync.py -v
```

Expected: FAIL (cannot import `detect_icloud_path` from `services.cloud_sync`).

- [ ] **Step 3: Implement detect_icloud_path**

Create `backend/services/cloud_sync.py`:

```python
"""Cloud sync path detection and migration helpers.

LocWarp itself does no network I/O; it relies on the operating system
(iCloud Drive, Google Drive Desktop, OneDrive, Dropbox) to synchronise
the bookmarks file across devices. This module only knows about local
filesystem paths.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


_MACOS_ICLOUD_REL = Path("Library/Mobile Documents/com~apple~CloudDocs")
_WIN_ICLOUD_REL = Path("iCloudDrive")


def detect_icloud_path() -> Path | None:
    """Return the user's iCloud Drive root if it exists; else None.

    On macOS this is ``~/Library/Mobile Documents/com~apple~CloudDocs``;
    on Windows it is ``%USERPROFILE%\\iCloudDrive`` (requires iCloud for
    Windows to be installed and signed in). Other platforms return None.
    """
    home = Path.home()
    if sys.platform == "darwin":
        candidate = home / _MACOS_ICLOUD_REL
    elif sys.platform == "win32":
        candidate = home / _WIN_ICLOUD_REL
    else:
        return None
    return candidate if candidate.exists() else None
```

- [ ] **Step 4: Run tests, verify they pass**

Run:
```bash
cd backend && pytest tests/test_cloud_sync.py -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/cloud_sync.py backend/tests/test_cloud_sync.py
git commit -m "feat(cloud-sync): detect iCloud Drive path on macOS and Windows"
```

---

## Task 5: Sync folder setup

**Files:**
- Modify: `backend/services/cloud_sync.py`
- Modify: `backend/tests/test_cloud_sync.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_cloud_sync.py`:

```python
from services.cloud_sync import setup_sync_folder


def test_setup_sync_folder_creates_subfolder(tmp_path):
    result = setup_sync_folder(tmp_path)
    assert result == tmp_path / "LocWarp"
    assert result.is_dir()


def test_setup_sync_folder_is_idempotent(tmp_path):
    first = setup_sync_folder(tmp_path)
    second = setup_sync_folder(tmp_path)
    assert first == second
    assert second.is_dir()


def test_setup_sync_folder_rejects_non_writable_parent(tmp_path, monkeypatch):
    not_exists = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        setup_sync_folder(not_exists)
```

- [ ] **Step 2: Run tests, verify they fail**

Run:
```bash
cd backend && pytest tests/test_cloud_sync.py -v -k setup
```

Expected: FAIL on import.

- [ ] **Step 3: Implement setup_sync_folder**

Append to `backend/services/cloud_sync.py`:

```python
LOCWARP_SUBFOLDER = "LocWarp"


def setup_sync_folder(parent: Path) -> Path:
    """Create (or reuse) the LocWarp subfolder under *parent*.

    Raises FileNotFoundError if *parent* itself does not exist (we never
    create the cloud drive root for the user).
    """
    if not parent.exists():
        raise FileNotFoundError(f"Parent folder does not exist: {parent}")
    sub = parent / LOCWARP_SUBFOLDER
    sub.mkdir(exist_ok=True)
    return sub
```

- [ ] **Step 4: Run tests, verify pass**

Run:
```bash
cd backend && pytest tests/test_cloud_sync.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/cloud_sync.py backend/tests/test_cloud_sync.py
git commit -m "feat(cloud-sync): create or reuse LocWarp subfolder in sync root"
```

---

## Task 6: Migration helper with rollback

**Files:**
- Modify: `backend/services/cloud_sync.py`
- Modify: `backend/tests/test_cloud_sync.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_cloud_sync.py`:

```python
from services.cloud_sync import migrate_bookmarks


def test_migrate_bookmarks_copies_and_deletes_source(tmp_path):
    src = tmp_path / "src" / "bookmarks.json"
    src.parent.mkdir()
    src.write_text('{"categories":[],"bookmarks":[]}', encoding="utf-8")
    dst = tmp_path / "dst" / "bookmarks.json"
    dst.parent.mkdir()

    migrate_bookmarks(src=src, dst=dst)

    assert dst.read_text(encoding="utf-8") == '{"categories":[],"bookmarks":[]}'
    assert not src.exists()


def test_migrate_bookmarks_noop_when_source_missing(tmp_path):
    src = tmp_path / "missing.json"
    dst = tmp_path / "dst.json"
    # Should not raise, should not create dst
    migrate_bookmarks(src=src, dst=dst)
    assert not dst.exists()


def test_migrate_bookmarks_rollback_on_post_copy_failure(tmp_path, monkeypatch):
    src = tmp_path / "src.json"
    src.write_text("payload", encoding="utf-8")
    dst = tmp_path / "dst.json"

    original_unlink = Path.unlink

    def fail_unlink(self, missing_ok=False):
        if self == src:
            raise OSError("simulated failure deleting source")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(OSError):
        migrate_bookmarks(src=src, dst=dst)

    # Source retained; dst removed by rollback
    assert src.exists()
    assert not dst.exists()
```

- [ ] **Step 2: Run tests, verify they fail**

Run:
```bash
cd backend && pytest tests/test_cloud_sync.py -v -k migrate
```

Expected: FAIL on import.

- [ ] **Step 3: Implement migrate_bookmarks**

Append to `backend/services/cloud_sync.py`:

```python
def migrate_bookmarks(src: Path, dst: Path) -> None:
    """Move *src* to *dst* with rollback on partial failure.

    No-op if *src* does not exist. Refuses to overwrite *dst* if both
    exist with different content (caller must resolve).
    """
    if not src.exists():
        return
    if dst.exists() and dst.read_bytes() != src.read_bytes():
        raise FileExistsError(f"Destination already has different content: {dst}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    try:
        src.unlink()
    except OSError:
        # Rollback: remove dst so we don't leave duplicate
        try:
            dst.unlink(missing_ok=True)
        except OSError:
            pass
        raise
```

- [ ] **Step 4: Run all tests, verify pass**

Run:
```bash
cd backend && pytest tests/test_cloud_sync.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/cloud_sync.py backend/tests/test_cloud_sync.py
git commit -m "feat(cloud-sync): migrate bookmarks file with rollback on failure"
```

---

## Task 7: Configurable bookmarks path

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/main.py` (around lines 67-97)
- Modify: `backend/services/bookmarks.py`
- Create: `backend/tests/test_config_paths.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_config_paths.py`:

```python
import json
from pathlib import Path

from services.json_safe import safe_write_json


def test_get_bookmarks_path_default(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    from config import get_bookmarks_path
    assert get_bookmarks_path() == tmp_path / "bookmarks.json"


def test_get_bookmarks_path_uses_settings_override(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    settings = tmp_path / "settings.json"
    monkeypatch.setattr("config.SETTINGS_FILE", settings)
    override = tmp_path / "cloud" / "LocWarp" / "bookmarks.json"
    safe_write_json(settings, {"bookmarks_path": str(override)})
    from config import get_bookmarks_path
    assert get_bookmarks_path() == override


def test_get_bookmarks_path_falls_back_when_settings_malformed(monkeypatch, tmp_path):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    settings = tmp_path / "settings.json"
    settings.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr("config.SETTINGS_FILE", settings)
    from config import get_bookmarks_path
    assert get_bookmarks_path() == tmp_path / "bookmarks.json"
```

- [ ] **Step 2: Run test, verify fails**

Run:
```bash
cd backend && pytest tests/test_config_paths.py -v
```

Expected: FAIL (cannot import `get_bookmarks_path`).

- [ ] **Step 3: Add get_bookmarks_path to config.py**

In `backend/config.py`, replace the line:

```python
BOOKMARKS_FILE = DATA_DIR / "bookmarks.json"
```

with:

```python
_DEFAULT_BOOKMARKS_FILE = DATA_DIR / "bookmarks.json"


def get_bookmarks_path() -> Path:
    """Return the configured bookmarks file path.

    Reads the optional ``bookmarks_path`` key from settings.json; falls
    back to the default in DATA_DIR if the key is missing, the settings
    file is malformed, or the override path's parent is unreachable.
    """
    from services.json_safe import safe_load_json
    data = safe_load_json(SETTINGS_FILE)
    if isinstance(data, dict):
        override = data.get("bookmarks_path")
        if isinstance(override, str) and override:
            p = Path(override)
            if p.parent.exists():
                return p
    return _DEFAULT_BOOKMARKS_FILE


# Backwards-compat alias for code that imports the constant. Kept as a
# function call so tests that monkeypatch DATA_DIR see the new value.
BOOKMARKS_FILE = _DEFAULT_BOOKMARKS_FILE
```

- [ ] **Step 4: Update BookmarkManager to use get_bookmarks_path**

In `backend/services/bookmarks.py`:

Replace the import line:

```python
from config import BOOKMARKS_FILE
```

with:

```python
from config import get_bookmarks_path
```

Replace inside `_load` and `_save`:

```python
data = safe_load_json(Path(BOOKMARKS_FILE))
```
→
```python
data = safe_load_json(self._bookmarks_path())
```

```python
safe_write_json(Path(BOOKMARKS_FILE), payload)
```
→
```python
safe_write_json(self._bookmarks_path(), payload)
```

Add helper to `BookmarkManager`:

```python
def _bookmarks_path(self) -> Path:
    return get_bookmarks_path()
```

- [ ] **Step 5: Persist bookmarks_path via AppState settings**

In `backend/main.py`, inside `AppState._load_settings`, after the existing `bmExp` block, add:

```python
            bp = data.get("bookmarks_path")
            if isinstance(bp, str):
                self._bookmarks_path = bp
            cdsm = data.get("cloud_sync_dismissed")
            if isinstance(cdsm, bool):
                self._cloud_sync_dismissed = cdsm
```

In `AppState.__init__` (after the `_bookmark_expanded_categories` line):

```python
        self._bookmarks_path: str | None = None
        self._cloud_sync_dismissed: bool = False
```

In `AppState.save_settings`, extend the `data` dict:

```python
            "bookmarks_path": self._bookmarks_path,
            "cloud_sync_dismissed": self._cloud_sync_dismissed,
```

- [ ] **Step 6: Run all backend tests, verify nothing regressed**

Run:
```bash
cd backend && pytest -v
```

Expected: all existing tests PASS, plus the 3 new ones from this task.

- [ ] **Step 7: Commit**

```bash
git add backend/config.py backend/main.py backend/services/bookmarks.py backend/tests/test_config_paths.py
git commit -m "feat(bookmarks): make storage path configurable via settings.json"
```

---

## Task 8: Track last-loaded snapshot and mtime

**Files:**
- Modify: `backend/services/bookmarks.py`
- Create: `backend/tests/test_bookmark_concurrency.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_bookmark_concurrency.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from services.bookmarks import BookmarkManager


def _patch_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config._DEFAULT_BOOKMARKS_FILE", tmp_path / "bookmarks.json")


def test_manager_records_mtime_after_load(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"
    bookmarks.write_text(
        '{"categories":[{"id":"default","name":"x","color":"#fff","sort_order":0,"created_at":"2026-01-01T00:00:00+00:00"}],"bookmarks":[]}',
        encoding="utf-8",
    )
    mgr = BookmarkManager()
    assert mgr._last_loaded_mtime == bookmarks.stat().st_mtime
    assert len(mgr._last_loaded_snapshot.categories) == 1


def test_manager_records_mtime_after_save(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    mgr = BookmarkManager()
    bm = mgr.create_bookmark(name="A", lat=1.0, lng=2.0)
    assert (tmp_path / "bookmarks.json").exists()
    assert mgr._last_loaded_mtime == (tmp_path / "bookmarks.json").stat().st_mtime
    assert any(b.id == bm.id for b in mgr._last_loaded_snapshot.bookmarks)
```

- [ ] **Step 2: Run test, verify fails**

Run:
```bash
cd backend && pytest tests/test_bookmark_concurrency.py -v
```

Expected: FAIL (no attribute `_last_loaded_mtime`).

- [ ] **Step 3: Implement snapshot/mtime tracking**

In `backend/services/bookmarks.py`, modify `BookmarkManager.__init__` to add:

```python
        self._last_loaded_mtime: float = 0.0
        self._last_loaded_snapshot: BookmarkStore = BookmarkStore(categories=[], bookmarks=[])
```

(Place these after `self.store = ...` and before `self._load()`.)

At the end of `_load`, after the successful schema validation, add:

```python
            self._update_snapshot()
```

At the end of `_save`, after `safe_write_json(...)`, add:

```python
        self._update_snapshot()
```

Add new method to `BookmarkManager` (near the persistence methods):

```python
def _update_snapshot(self) -> None:
    """Capture current store as the baseline for future diffs.

    Records the disk mtime at the moment we know self.store is in sync
    with the file. A deep copy ensures later in-memory edits do not
    mutate the snapshot.
    """
    path = self._bookmarks_path()
    try:
        self._last_loaded_mtime = path.stat().st_mtime
    except FileNotFoundError:
        self._last_loaded_mtime = 0.0
    self._last_loaded_snapshot = BookmarkStore(
        **json.loads(self.store.model_dump_json())
    )
```

- [ ] **Step 4: Run all bookmark tests**

Run:
```bash
cd backend && pytest tests/test_bookmark_concurrency.py tests/test_bookmarks_api.py tests/test_bookmark_cascade_delete.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmarks.py backend/tests/test_bookmark_concurrency.py
git commit -m "feat(bookmarks): track last-loaded snapshot and mtime for concurrency"
```

---

## Task 9: Stale-write merge in `_save`

**Files:**
- Modify: `backend/services/bookmarks.py`
- Modify: `backend/tests/test_bookmark_concurrency.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_bookmark_concurrency.py`:

```python
import json as _json


def test_save_merges_when_disk_changed_externally(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"

    # Manager A creates a bookmark
    mgr_a = BookmarkManager()
    mgr_a.create_bookmark(name="A1", lat=1.0, lng=1.0)

    # Simulate device B writing a different bookmark to disk
    payload = _json.loads(bookmarks.read_text(encoding="utf-8"))
    payload["bookmarks"].append({
        "id": "external-id",
        "name": "from-device-b",
        "lat": 9.0,
        "lng": 9.0,
        "address": "",
        "category_id": "default",
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_used_at": "2026-01-01T00:00:00+00:00",
        "country_code": "",
    })
    bookmarks.write_text(_json.dumps(payload), encoding="utf-8")
    # Force a newer mtime than what mgr_a recorded
    import os
    os.utime(bookmarks, (mgr_a._last_loaded_mtime + 10, mgr_a._last_loaded_mtime + 10))

    # Now A creates another bookmark — _save should merge in B's entry
    mgr_a.create_bookmark(name="A2", lat=2.0, lng=2.0)

    final = _json.loads(bookmarks.read_text(encoding="utf-8"))
    ids = {b["id"] for b in final["bookmarks"]}
    names = {b["name"] for b in final["bookmarks"]}
    assert "external-id" in ids
    assert {"A1", "A2", "from-device-b"} <= names


def test_save_does_not_merge_when_disk_unchanged(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    mgr = BookmarkManager()
    mgr.create_bookmark(name="X", lat=1.0, lng=1.0)
    first_payload = (tmp_path / "bookmarks.json").read_text(encoding="utf-8")
    mgr.create_bookmark(name="Y", lat=2.0, lng=2.0)
    second_payload = (tmp_path / "bookmarks.json").read_text(encoding="utf-8")
    assert first_payload != second_payload
    # Sanity: both bookmarks present, no duplicates introduced
    final = _json.loads(second_payload)
    names = {b["name"] for b in final["bookmarks"]}
    assert names == {"X", "Y"}
```

- [ ] **Step 2: Run tests, verify they fail**

Run:
```bash
cd backend && pytest tests/test_bookmark_concurrency.py -v -k save
```

Expected: FAIL on `test_save_merges_when_disk_changed_externally` (device B's bookmark missing).

- [ ] **Step 3: Implement stale check in _save**

In `backend/services/bookmarks.py`, add import at the top:

```python
from services.bookmark_merge import diff_store, merge_local_wins
```

Replace `_save` with:

```python
def _save(self) -> None:
    """Persist the current store to disk, merging any external changes.

    If the disk mtime is newer than the snapshot we hold, another
    process (or another device via cloud sync) wrote to the file
    between our last load and this save. In that case we diff our
    in-memory store against the snapshot, reload the fresh disk
    state, reapply the diff on top, and only then write.
    """
    path = self._bookmarks_path()
    try:
        current_mtime = path.stat().st_mtime
    except FileNotFoundError:
        current_mtime = 0.0

    if current_mtime > self._last_loaded_mtime:
        self._reconcile_from_disk()

    payload = json.loads(self.store.model_dump_json())
    safe_write_json(path, payload)
    self._update_snapshot()


def _reconcile_from_disk(self) -> None:
    """Merge external on-disk changes into self.store using local-wins.

    No-op (besides updating snapshot) when on-disk content is invalid
    or unreadable — better to keep our in-memory copy than to wipe it
    in response to a transient read error.
    """
    path = self._bookmarks_path()
    raw = safe_load_json(path)
    if not isinstance(raw, dict):
        return
    try:
        fresh = BookmarkStore(**raw)
    except Exception as exc:
        logger.warning("Disk payload failed schema validation during reconcile: %s", exc)
        return
    local_diff = diff_store(current=self.store, baseline=self._last_loaded_snapshot)
    self.store = merge_local_wins(remote=fresh, local_diff=local_diff)
```

- [ ] **Step 4: Run all tests, verify PASS**

Run:
```bash
cd backend && pytest tests/test_bookmark_concurrency.py tests/test_bookmark_merge.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmarks.py backend/tests/test_bookmark_concurrency.py
git commit -m "feat(bookmarks): merge external writes during _save"
```

---

## Task 10: Watchdog file observer + WebSocket broadcast

**Files:**
- Modify: `backend/services/bookmarks.py`
- Modify: `backend/tests/test_bookmark_concurrency.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_bookmark_concurrency.py`:

```python
def test_reconcile_loads_external_bookmark(tmp_path, monkeypatch):
    """Directly exercise _reconcile_from_disk — bypasses watcher timing."""
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"

    mgr = BookmarkManager()
    mgr.create_bookmark(name="local", lat=1.0, lng=1.0)

    payload = _json.loads(bookmarks.read_text(encoding="utf-8"))
    payload["bookmarks"].append({
        "id": "remote-id",
        "name": "remote",
        "lat": 5.0,
        "lng": 5.0,
        "address": "",
        "category_id": "default",
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_used_at": "2026-01-01T00:00:00+00:00",
        "country_code": "",
    })
    bookmarks.write_text(_json.dumps(payload), encoding="utf-8")

    mgr._reconcile_from_disk()

    names = {b.name for b in mgr.store.bookmarks}
    assert "local" in names
    assert "remote" in names


def test_reconcile_ignores_zero_byte_placeholder(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"
    mgr = BookmarkManager()
    mgr.create_bookmark(name="local", lat=1.0, lng=1.0)
    bookmarks.write_text("", encoding="utf-8")  # iCloud placeholder
    mgr._reconcile_from_disk()
    # local bookmark survives — we did not let an empty file wipe state
    assert any(b.name == "local" for b in mgr.store.bookmarks)
```

- [ ] **Step 2: Run tests, verify failure for placeholder case**

Run:
```bash
cd backend && pytest tests/test_bookmark_concurrency.py::test_reconcile_ignores_zero_byte_placeholder -v
```

Expected: depends on `safe_load_json` behaviour. If it returns `None` for empty files, this test already passes — accept that as proof and move on. If it raises, fix `_reconcile_from_disk` to early-return on `path.stat().st_size == 0`.

- [ ] **Step 3: Add placeholder guard to _reconcile_from_disk**

Replace the start of `_reconcile_from_disk` with:

```python
def _reconcile_from_disk(self) -> None:
    path = self._bookmarks_path()
    try:
        if path.stat().st_size == 0:
            return
    except FileNotFoundError:
        return
    raw = safe_load_json(path)
    ...
```

(The rest of the method body stays the same as Task 9.)

Run the placeholder test:
```bash
cd backend && pytest tests/test_bookmark_concurrency.py::test_reconcile_ignores_zero_byte_placeholder -v
```

Expected: PASS.

- [ ] **Step 4: Add watcher infrastructure (sync, no asyncio yet)**

In `backend/services/bookmarks.py`, add imports:

```python
import threading
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
```

Add to `BookmarkManager.__init__`, after `self._load()`:

```python
        self._watcher_observer: Observer | None = None
        self._watcher_debounce_timer: threading.Timer | None = None
        self._on_external_change: callable | None = None
```

Add new methods to `BookmarkManager`:

```python
def start_watcher(self, on_change: callable) -> None:
    """Begin watching the bookmarks file for external modifications.

    *on_change* is invoked (no args) on the watcher thread AFTER
    self.store has been reconciled with disk. Callers are responsible
    for marshalling onto whatever loop/thread they need (e.g. asyncio
    via run_coroutine_threadsafe).
    """
    self.stop_watcher()
    path = self._bookmarks_path()
    parent = path.parent
    if not parent.exists():
        logger.warning("Bookmark folder does not exist; watcher not started: %s", parent)
        return
    self._on_external_change = on_change

    manager = self

    class _Handler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.is_directory:
                return
            if Path(event.src_path) != manager._bookmarks_path():
                return
            manager._schedule_reconcile()

        on_created = on_modified
        on_moved = on_modified

    self._watcher_observer = Observer()
    self._watcher_observer.schedule(_Handler(), str(parent), recursive=False)
    self._watcher_observer.start()
    logger.info("Bookmark watcher started on %s", parent)


def stop_watcher(self) -> None:
    if self._watcher_debounce_timer is not None:
        self._watcher_debounce_timer.cancel()
        self._watcher_debounce_timer = None
    if self._watcher_observer is not None:
        try:
            self._watcher_observer.stop()
            self._watcher_observer.join(timeout=2.0)
        except Exception:
            logger.exception("Failed to stop bookmark watcher cleanly")
        self._watcher_observer = None


def _schedule_reconcile(self) -> None:
    """Debounce rapid mtime events from a single sync burst."""
    if self._watcher_debounce_timer is not None:
        self._watcher_debounce_timer.cancel()
    self._watcher_debounce_timer = threading.Timer(0.5, self._watcher_tick)
    self._watcher_debounce_timer.daemon = True
    self._watcher_debounce_timer.start()


def _watcher_tick(self) -> None:
    try:
        path = self._bookmarks_path()
        current_mtime = path.stat().st_mtime
        if current_mtime <= self._last_loaded_mtime:
            return  # self-echo or already reconciled
        before_payload = self.store.model_dump_json()
        self._reconcile_from_disk()
        after_payload = self.store.model_dump_json()
        if before_payload != after_payload:
            # Persist the merged state so disk reflects local edits we
            # may have reapplied on top of the remote update.
            payload = json.loads(after_payload)
            safe_write_json(path, payload)
            self._update_snapshot()
            if self._on_external_change is not None:
                try:
                    self._on_external_change()
                except Exception:
                    logger.exception("on_external_change callback raised")
        else:
            self._update_snapshot()  # still resync mtime
    except Exception:
        logger.exception("Bookmark watcher tick failed")
```

- [ ] **Step 5: Add unit test for watcher tick (direct invocation, no real observer)**

Append to `backend/tests/test_bookmark_concurrency.py`:

```python
def test_watcher_tick_reloads_and_fires_callback(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"
    mgr = BookmarkManager()
    mgr.create_bookmark(name="A", lat=1.0, lng=1.0)

    # Simulate device B writing remotely
    payload = _json.loads(bookmarks.read_text(encoding="utf-8"))
    payload["bookmarks"].append({
        "id": "ext", "name": "B-side", "lat": 9.0, "lng": 9.0,
        "address": "", "category_id": "default",
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_used_at": "2026-01-01T00:00:00+00:00",
        "country_code": "",
    })
    bookmarks.write_text(_json.dumps(payload), encoding="utf-8")
    import os
    os.utime(bookmarks, (mgr._last_loaded_mtime + 10, mgr._last_loaded_mtime + 10))

    called = []
    mgr._on_external_change = lambda: called.append(True)
    mgr._watcher_tick()

    assert called == [True]
    assert any(b.name == "B-side" for b in mgr.store.bookmarks)


def test_watcher_tick_ignores_self_echo(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    mgr = BookmarkManager()
    mgr.create_bookmark(name="A", lat=1.0, lng=1.0)
    called = []
    mgr._on_external_change = lambda: called.append(True)
    # No disk change; mtime equals snapshot
    mgr._watcher_tick()
    assert called == []
```

- [ ] **Step 6: Wire watcher into application startup**

In `backend/main.py`, find the FastAPI startup handler (or create one if missing). Look near where `app_state` is constructed. Add a startup handler that:

1. Gets the running asyncio event loop.
2. Starts the watcher with a callback that schedules `broadcast("bookmarks_changed", {...})` on that loop via `asyncio.run_coroutine_threadsafe`.

Add this code after `app = FastAPI(...)` (or beside the existing `@app.on_event("startup")` if present):

```python
import asyncio


@app.on_event("startup")
async def _start_bookmark_watcher():
    loop = asyncio.get_running_loop()
    from api.websocket import broadcast as _bc

    def _on_change():
        asyncio.run_coroutine_threadsafe(
            _bc("bookmarks_changed", {"reason": "external_update"}),
            loop,
        )

    app_state.bookmark_manager.start_watcher(_on_change)


@app.on_event("shutdown")
async def _stop_bookmark_watcher():
    app_state.bookmark_manager.stop_watcher()
```

(If a `@app.on_event("startup")` already exists in main.py, add the watcher-start code to it and create a matching shutdown handler instead of adding new decorators.)

- [ ] **Step 7: Run all backend tests**

Run:
```bash
cd backend && pytest -v
```

Expected: all PASS. The watcher-tick tests do not need a real Observer — they call `_watcher_tick` directly.

- [ ] **Step 8: Commit**

```bash
git add backend/services/bookmarks.py backend/main.py backend/tests/test_bookmark_concurrency.py
git commit -m "feat(bookmarks): watch file for external changes, broadcast via websocket"
```

---

## Task 11: Cloud sync REST endpoints

**Files:**
- Modify: `backend/api/bookmarks.py`
- Modify: `backend/models/schemas.py`
- Create: `backend/tests/test_cloud_sync_api.py`

- [ ] **Step 1: Add response schemas**

In `backend/models/schemas.py`, add at the end:

```python
class CloudSyncStatus(BaseModel):
    enabled: bool
    detected_icloud_path: str | None = None
    current_path: str
    sync_folder: str | None = None
    bookmark_count: int = 0
    category_count: int = 0
    prompt_dismissed: bool = False


class CloudSyncEnableRequest(BaseModel):
    folder: str | None = None  # absolute path; None = use detected iCloud
```

- [ ] **Step 2: Write failing API test**

Create `backend/tests/test_cloud_sync_api.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config._DEFAULT_BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    from main import app
    return TestClient(app)


def test_cloud_sync_status_default(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/bookmarks/cloud-sync/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["current_path"].endswith("bookmarks.json")
    assert body["prompt_dismissed"] is False


def test_cloud_sync_enable_with_custom_folder(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    custom = tmp_path / "fake-icloud"
    custom.mkdir()
    r = client.post(
        "/api/bookmarks/cloud-sync/enable",
        json={"folder": str(custom)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["sync_folder"] == str(custom / "LocWarp")
    assert Path(body["current_path"]).parent == custom / "LocWarp"


def test_cloud_sync_disable_resets_path(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    custom = tmp_path / "fake-icloud"
    custom.mkdir()
    client.post("/api/bookmarks/cloud-sync/enable", json={"folder": str(custom)})
    r = client.post("/api/bookmarks/cloud-sync/disable")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False


def test_cloud_sync_dismiss_prompt(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.post("/api/bookmarks/cloud-sync/dismiss-prompt")
    assert r.status_code == 200
    assert r.json()["prompt_dismissed"] is True
```

- [ ] **Step 3: Run tests, verify fail**

Run:
```bash
cd backend && pytest tests/test_cloud_sync_api.py -v
```

Expected: FAIL (404 on the new endpoints).

- [ ] **Step 4: Implement endpoints**

In `backend/api/bookmarks.py`, add imports near the top:

```python
from services.cloud_sync import detect_icloud_path, setup_sync_folder, migrate_bookmarks
from models.schemas import CloudSyncStatus, CloudSyncEnableRequest
from config import _DEFAULT_BOOKMARKS_FILE
```

Append at the end of the file:

```python
# ── Cloud sync ────────────────────────────────────────────

@router.get("/cloud-sync/status", response_model=CloudSyncStatus)
async def cloud_sync_status():
    from main import app_state
    bm = _bm()
    current = bm._bookmarks_path()
    sync_folder = str(current.parent) if current != _DEFAULT_BOOKMARKS_FILE else None
    icloud = detect_icloud_path()
    return CloudSyncStatus(
        enabled=current != _DEFAULT_BOOKMARKS_FILE,
        detected_icloud_path=str(icloud) if icloud else None,
        current_path=str(current),
        sync_folder=sync_folder,
        bookmark_count=len(bm.list_bookmarks()),
        category_count=len(bm.list_categories()),
        prompt_dismissed=app_state._cloud_sync_dismissed,
    )


@router.post("/cloud-sync/enable", response_model=CloudSyncStatus)
async def cloud_sync_enable(req: CloudSyncEnableRequest):
    from main import app_state
    parent: Path | None = None
    if req.folder:
        parent = Path(req.folder)
    else:
        parent = detect_icloud_path()
    if parent is None:
        raise HTTPException(400, "No iCloud Drive detected and no custom folder provided")

    try:
        target_folder = setup_sync_folder(parent)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc))

    new_path = target_folder / "bookmarks.json"
    src = app_state.bookmark_manager._bookmarks_path()
    try:
        migrate_bookmarks(src=src, dst=new_path)
    except FileExistsError:
        # New folder already has a bookmarks.json (e.g. another device).
        # Adopt it: discard the in-memory local file by leaving src in
        # place and pointing settings at new_path.
        pass

    app_state._bookmarks_path = str(new_path)
    app_state.save_settings()

    # Re-init the manager so it reloads from the new path and rebinds watcher
    app_state.bookmark_manager.stop_watcher()
    from services.bookmarks import BookmarkManager
    app_state.bookmark_manager = BookmarkManager()
    # restart watcher with the same callback used at startup
    import asyncio
    from api.websocket import broadcast as _bc
    loop = asyncio.get_running_loop()
    app_state.bookmark_manager.start_watcher(
        lambda: asyncio.run_coroutine_threadsafe(
            _bc("bookmarks_changed", {"reason": "external_update"}), loop
        )
    )

    return await cloud_sync_status()


@router.post("/cloud-sync/disable", response_model=CloudSyncStatus)
async def cloud_sync_disable():
    from main import app_state
    bm = app_state.bookmark_manager
    current = bm._bookmarks_path()
    if current == _DEFAULT_BOOKMARKS_FILE:
        return await cloud_sync_status()

    # Copy back to default path so user keeps their data locally
    default = _DEFAULT_BOOKMARKS_FILE
    try:
        migrate_bookmarks(src=current, dst=default)
    except FileExistsError:
        # Default already exists; leave cloud copy in place, just unbind
        pass

    app_state._bookmarks_path = None
    app_state.save_settings()

    bm.stop_watcher()
    from services.bookmarks import BookmarkManager
    app_state.bookmark_manager = BookmarkManager()
    import asyncio
    from api.websocket import broadcast as _bc
    loop = asyncio.get_running_loop()
    app_state.bookmark_manager.start_watcher(
        lambda: asyncio.run_coroutine_threadsafe(
            _bc("bookmarks_changed", {"reason": "external_update"}), loop
        )
    )

    return await cloud_sync_status()


@router.post("/cloud-sync/dismiss-prompt", response_model=CloudSyncStatus)
async def cloud_sync_dismiss_prompt():
    from main import app_state
    app_state._cloud_sync_dismissed = True
    app_state.save_settings()
    return await cloud_sync_status()
```

- [ ] **Step 5: Run API tests**

Run:
```bash
cd backend && pytest tests/test_cloud_sync_api.py -v
```

Expected: all 4 PASS.

- [ ] **Step 6: Run full backend test suite**

Run:
```bash
cd backend && pytest -v
```

Expected: all PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
git add backend/api/bookmarks.py backend/models/schemas.py backend/tests/test_cloud_sync_api.py
git commit -m "feat(api): cloud sync status/enable/disable/dismiss endpoints"
```

---

## Task 12: Frontend — `CloudSyncSection` component

**Files:**
- Create: `frontend/src/components/CloudSyncSection.tsx`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/components/SettingsModal.tsx`

- [ ] **Step 1: Add API client methods**

In `frontend/src/services/api.ts`, locate the section where bookmark / settings endpoints live and add:

```typescript
export interface CloudSyncStatus {
  enabled: boolean
  detected_icloud_path: string | null
  current_path: string
  sync_folder: string | null
  bookmark_count: number
  category_count: number
  prompt_dismissed: boolean
}

export const cloudSync = {
  status: () =>
    fetch('/api/bookmarks/cloud-sync/status').then(
      (r) => r.json() as Promise<CloudSyncStatus>
    ),

  enable: (folder?: string) =>
    fetch('/api/bookmarks/cloud-sync/enable', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folder ?? null }),
    }).then((r) => {
      if (!r.ok) throw new Error('Failed to enable cloud sync')
      return r.json() as Promise<CloudSyncStatus>
    }),

  disable: () =>
    fetch('/api/bookmarks/cloud-sync/disable', { method: 'POST' }).then(
      (r) => r.json() as Promise<CloudSyncStatus>
    ),

  dismissPrompt: () =>
    fetch('/api/bookmarks/cloud-sync/dismiss-prompt', { method: 'POST' }).then(
      (r) => r.json() as Promise<CloudSyncStatus>
    ),
}
```

(Match the style of other groupings in the file. If the file uses a single default-exported `api` object, add a `cloudSync` key inside it instead of a separate export.)

- [ ] **Step 2: Create CloudSyncSection component**

Create `frontend/src/components/CloudSyncSection.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { cloudSync, type CloudSyncStatus } from '../services/api'

export function CloudSyncSection() {
  const [status, setStatus] = useState<CloudSyncStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = async () => {
    try {
      setStatus(await cloudSync.status())
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  const onToggle = async () => {
    if (!status) return
    setBusy(true)
    setError(null)
    try {
      const next = status.enabled
        ? await cloudSync.disable()
        : await cloudSync.enable()
      setStatus(next)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!status) return null

  const canEnable =
    status.detected_icloud_path !== null || status.current_path.includes('LocWarp')

  return (
    <section className="cloud-sync-section">
      <header>
        <span role="img" aria-label="cloud">☁️</span> Cloud Sync
      </header>

      <label className="cloud-sync-toggle">
        <input
          type="checkbox"
          checked={status.enabled}
          onChange={onToggle}
          disabled={busy || (!status.enabled && !canEnable)}
        />
        <span>
          {status.enabled
            ? 'Sync via cloud drive'
            : status.detected_icloud_path
              ? 'Enable sync via iCloud Drive'
              : 'Enable sync (use custom folder)'}
        </span>
      </label>

      {status.enabled && status.sync_folder && (
        <p className="cloud-sync-detail">
          <span>✓ Path: {status.sync_folder}</span>
          <br />
          <span>
            {status.bookmark_count} bookmarks · {status.category_count} categories
          </span>
        </p>
      )}

      {!status.enabled && status.detected_icloud_path && (
        <p className="cloud-sync-detail">
          Detected: {status.detected_icloud_path}
        </p>
      )}

      {!status.enabled && !status.detected_icloud_path && (
        <p className="cloud-sync-detail">
          iCloud Drive not detected. You can use any synced folder
          (Dropbox / Google Drive / OneDrive) — enable, then pick the
          path manually from settings.json.
        </p>
      )}

      {error && <p className="cloud-sync-error">{error}</p>}
    </section>
  )
}
```

- [ ] **Step 3: Embed in SettingsModal**

In `frontend/src/components/SettingsModal.tsx`, add the import:

```tsx
import { CloudSyncSection } from './CloudSyncSection'
```

Add `<CloudSyncSection />` inside the modal body, in a sensible location (likely near the bottom of the settings list — after coord-format and before close button).

- [ ] **Step 4: Add one-time auto-discovery prompt on app load**

The spec requires that when LocWarp launches on a second device signed
into the same Apple ID, the existing `<iCloud>/LocWarp/bookmarks.json`
is detected and the user is offered to adopt it once.

In `frontend/src/App.tsx` (or whichever component runs once at top
level), add:

```tsx
import { useEffect } from 'react'
import { cloudSync } from './services/api'

function useCloudSyncDiscovery() {
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const s = await cloudSync.status()
      if (cancelled) return
      if (s.enabled || s.prompt_dismissed || !s.detected_icloud_path) return
      // Detected iCloud Drive but not enabled and not dismissed —
      // probe whether <iCloud>/LocWarp/bookmarks.json already exists
      // by asking the backend to attempt a status under that folder.
      // Simpler heuristic: if iCloud is detected, prompt once.
      const ok = window.confirm(
        'iCloud Drive detected. Use it to sync your LocWarp bookmarks ' +
        'across all devices signed in to this Apple ID?'
      )
      if (ok) {
        await cloudSync.enable()
      } else {
        await cloudSync.dismissPrompt()
      }
    })().catch(() => { /* swallow — non-fatal */ })
    return () => { cancelled = true }
  }, [])
}
```

Invoke `useCloudSyncDiscovery()` once at the top of the root
component (e.g. inside `App()`).

If the project has a non-`window.confirm` modal pattern (look for
existing modals like `SettingsModal`), use that instead and keep the
two outcomes (enable / dismissPrompt) identical.

- [ ] **Step 5: Build the frontend and verify no TypeScript errors**

Run:
```bash
cd frontend && npm run build
```

Expected: build succeeds, no TypeScript errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/services/api.ts frontend/src/components/CloudSyncSection.tsx frontend/src/components/SettingsModal.tsx frontend/src/App.tsx
git commit -m "feat(ui): cloud sync section + one-time iCloud discovery prompt"
```

---

## Task 13: Frontend — handle `bookmarks_changed` WebSocket event

**Files:**
- Modify: `frontend/src/hooks/useWebSocket.ts` (only if `WsMessage` type needs extending)
- Modify: the component that currently fetches bookmarks (likely `BookmarkList.tsx` or `App.tsx`)
- Optional: reuse existing toast / notification mechanism

- [ ] **Step 1: Locate the current bookmark subscription**

Run:
```bash
grep -rn "subscribe\|WsMessage" frontend/src/hooks/useWebSocket.ts | head -20
grep -rn "bookmarks_changed\|/api/bookmarks" frontend/src --include="*.tsx" --include="*.ts" | head -20
```

Expected: identify how the frontend currently subscribes to ws events and which component owns the bookmark refresh.

- [ ] **Step 2: Extend WsMessage type if needed**

In `frontend/src/hooks/useWebSocket.ts`, add `'bookmarks_changed'` to the union of `event` types if such a union exists. Otherwise nothing to change (the type is `any` or `string`).

- [ ] **Step 3: Subscribe in the bookmark-owning component**

In the component identified in Step 1 (likely `BookmarkList.tsx` or wherever the GET `/api/bookmarks` is wired), add:

```tsx
useEffect(() => {
  const unsub = ws.subscribe((msg) => {
    if (msg.event === 'bookmarks_changed') {
      refetchBookmarks()
      showToast('Synced from another device')
    }
  })
  return unsub
}, [ws])
```

Adapt `refetchBookmarks` and `showToast` to the names used in that component.

If the project does not have an in-app toast helper, surface the message via the existing notification mechanism. If neither exists, drop the toast for now — the refetch alone is the contract; the toast is polish.

- [ ] **Step 4: Manually verify in dev**

Run:
```bash
make start
```

(Then in another shell, hand-edit `~/.locwarp/bookmarks.json` to add a new bookmark entry and save; observe the UI auto-refresh within ~1 second.)

Expected: bookmark appears in UI without reload.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useWebSocket.ts frontend/src/components/BookmarkList.tsx
git commit -m "feat(ui): auto-refresh bookmarks on websocket bookmarks_changed event"
```

---

## Task 14: Final integration test — two-instance simulation

**Files:**
- Modify: `backend/tests/test_bookmark_concurrency.py`

- [ ] **Step 1: Write end-to-end concurrency test**

Append to `backend/tests/test_bookmark_concurrency.py`:

```python
def test_two_managers_on_same_file_converge(tmp_path, monkeypatch):
    """Simulate two devices both editing the same bookmarks.json.

    After both have written, both reload — final state should contain
    all non-conflicting edits from both sides, with last-writer's
    modifications winning on overlapping ids per local-wins semantics.
    """
    _patch_paths(tmp_path, monkeypatch)
    bookmarks = tmp_path / "bookmarks.json"

    mgr_a = BookmarkManager()
    mgr_a.create_bookmark(name="from-A-1", lat=1.0, lng=1.0)

    mgr_b = BookmarkManager()
    # B has loaded what A wrote
    assert any(b.name == "from-A-1" for b in mgr_b.list_bookmarks())

    mgr_b.create_bookmark(name="from-B-1", lat=2.0, lng=2.0)

    # A now writes a second bookmark; should merge B's bookmark in
    mgr_a.create_bookmark(name="from-A-2", lat=3.0, lng=3.0)

    final = _json.loads(bookmarks.read_text(encoding="utf-8"))
    names = {b["name"] for b in final["bookmarks"]}
    assert names == {"from-A-1", "from-A-2", "from-B-1"}
```

- [ ] **Step 2: Run all tests**

Run:
```bash
cd backend && pytest -v
```

Expected: ALL PASS.

- [ ] **Step 3: Run frontend type-check**

Run:
```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 4: Manual smoke test**

Run:
```bash
make start
```

Verify:
- Open Settings → see Cloud Sync section.
- If on macOS with iCloud Drive: toggle enables → confirms migration → bookmarks file moves to iCloud/LocWarp/bookmarks.json.
- Toggle off → bookmarks file returns to `~/.locwarp/bookmarks.json`.
- Edit the synced file by hand in another editor → UI updates within ~1 second.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_bookmark_concurrency.py
git commit -m "test(bookmarks): two-instance convergence integration test"
```

---

## Done — Self-Review Checklist

Before merging, verify:

- [ ] All 14 tasks committed.
- [ ] `pytest -v` runs cleanly with no skipped tests.
- [ ] `npm run build` succeeds.
- [ ] Manual smoke test from Task 14 Step 4 passes.
- [ ] Settings page shows Cloud Sync section.
- [ ] External edits to bookmarks.json reflect in UI without manual reload.
- [ ] No regression in existing import/export, category, recent-bookmark behaviour.
