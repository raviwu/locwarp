# In-Process Rotating Backup — Implementation Plan

> **For agentic workers:** Execute task-by-task. Each task = failing tests → implement → green →
> commit. Backend suite stays green + import-linter `7 kept, 0 broken` after every commit.

**Goal:** A lifespan-owned asyncio task snapshots the live bookmark + route stores to
`~/.locwarp/backups/` every 5 min, archiving a timestamped copy only on data change, pruning past 72h.

**Spec:** `docs/superpowers/specs/2026-06-22-bookmark-route-rotating-backup-design.md`

## Global Constraints

- No new HTTP/WS/IPC surface. Behavior freeze on all existing endpoints.
- Backend pytest suite green after every commit. Pin baseline first:
  `cd backend && .venv/bin/python -m pytest --collect-only -q`.
- import-linter `7 kept, 0 broken` after every commit (`.venv/bin/lint-imports`). No new contract.
- Rings: `domain` (stdlib+pydantic only) ← `infra`/`services` ← `bootstrap`/`main`. `services` never
  imports `infra` or `fastapi`. `infra → services.json_safe` is the one allowed services edge (precedent: `json_store.py:14`).
- Backups live ONLY under `~/.locwarp/backups/` (`config.BACKUP_DIR`), never the iCloud sync_folder.
- Reference `config.BACKUP_DIR` lazily everywhere — never `from config import BACKUP_DIR` (so the
  conftest monkeypatch works).
- Retention = 72h. Interval = 300s. File scheme identical to `scripts/desktop_backup.py`.

---

### Task 1: config constants + conftest isolation guard

**Files:** Modify `backend/config.py`, `backend/tests/conftest.py`. Test: `backend/tests/conftest.py` self-asserting via any existing test + a new guard test.

**Step 1 — add constants** to `backend/config.py` (after `STICKY_DENIED_FILE`, line ~87):
```python
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_INTERVAL_S = 300          # 5 minutes
BACKUP_RETENTION_HOURS = 72      # 3 days
```

**Step 2 — extend the autouse guard** in `backend/tests/conftest.py` `_isolate_real_data_paths`: add
```python
monkeypatch.setattr("config.BACKUP_DIR", tmp_path / "backups", raising=False)
```
alongside the existing `config.DATA_DIR` / `SETTINGS_FILE` / ... redirects.

**Step 3 — guard test** `backend/tests/test_backup_isolation.py`:
```python
def test_backup_dir_is_isolated_to_tmp(tmp_path):
    import config
    assert str(config.BACKUP_DIR).startswith(str(tmp_path)) or "/.locwarp/backups" not in str(config.BACKUP_DIR)
```
(The autouse fixture redirects it; this pins that the redirect exists.)

**Step 4 — run** `pytest -q` + `lint-imports`. **Commit:** `feat(backup): config constants + conftest BACKUP_DIR isolation guard`.

---

### Task 2: `domain/backup.py` — pure policy

**Files:** Create `backend/domain/backup.py`, `backend/tests/test_backup_domain.py`.

**Step 1 — failing tests** `test_backup_domain.py`:
```python
from datetime import datetime, timedelta
from domain import backup

def test_fingerprint_ignores_meta_and_detects_data_change():
    a = {"bookmarks": [{"id": "x"}]}; r = {"routes": []}
    assert backup.data_fingerprint(a, r) == backup.data_fingerprint(dict(a), dict(r))
    assert backup.data_fingerprint(a, r) != backup.data_fingerprint({"bookmarks": [{"id": "y"}]}, r)

def test_stamp_roundtrip():
    now = datetime(2026, 6, 22, 14, 30, 5)
    name = f"{backup.SNAPSHOT_PREFIX}{backup.snapshot_stamp(now)}{backup.SNAPSHOT_SUFFIX}"
    assert backup.parse_snapshot_stamp(name) == now

def test_parse_rejects_non_matching():
    assert backup.parse_snapshot_stamp(backup.LATEST_NAME) is None
    assert backup.parse_snapshot_stamp("random.json") is None

def test_select_stale_drops_old_keeps_recent_ignores_latest():
    now = datetime(2026, 6, 22, 12, 0, 0)
    old = f"{backup.SNAPSHOT_PREFIX}{backup.snapshot_stamp(now - timedelta(hours=80))}{backup.SNAPSHOT_SUFFIX}"
    recent = f"{backup.SNAPSHOT_PREFIX}{backup.snapshot_stamp(now - timedelta(hours=10))}{backup.SNAPSHOT_SUFFIX}"
    names = [old, recent, backup.LATEST_NAME, "noise.json"]
    assert backup.select_stale_snapshots(names, now, 72) == [old]

def test_build_snapshot_shape():
    snap = backup.build_snapshot({"categories": [], "bookmarks": [{"id": "a"}]},
                                 {"categories": [], "routes": []}, datetime(2026,6,22,1,2,3), "in-process")
    assert snap["bookmarks"]["bookmarks"] == [{"id": "a"}]
    assert snap["_backup_meta"]["bookmark_count"] == 1 and snap["_backup_meta"]["route_count"] == 0
    assert snap["_backup_meta"]["source"] == "in-process"
```

**Step 2 — implement** `backend/domain/backup.py`:
```python
"""Pure backup policy: fingerprint, snapshot naming, and retention. stdlib only."""
from __future__ import annotations
import json
from datetime import datetime

LATEST_NAME = "locwarp-latest-backup.json"
SNAPSHOT_PREFIX = "locwarp-backup-"
SNAPSHOT_SUFFIX = ".json"
_STAMP_FMT = "%Y%m%d-%H%M%S"

def data_fingerprint(bookmarks: dict, routes: dict) -> str:
    return json.dumps({"bookmarks": bookmarks, "routes": routes}, sort_keys=True, ensure_ascii=False)

def snapshot_stamp(now: datetime) -> str:
    return now.strftime(_STAMP_FMT)

def parse_snapshot_stamp(filename: str):
    if not (filename.startswith(SNAPSHOT_PREFIX) and filename.endswith(SNAPSHOT_SUFFIX)):
        return None
    core = filename[len(SNAPSHOT_PREFIX):-len(SNAPSHOT_SUFFIX)]
    try:
        return datetime.strptime(core, _STAMP_FMT)
    except ValueError:
        return None

def select_stale_snapshots(filenames: list[str], now: datetime, retention_hours: int) -> list[str]:
    stale = []
    for name in filenames:
        ts = parse_snapshot_stamp(name)
        if ts is not None and (now - ts).total_seconds() > retention_hours * 3600:
            stale.append(name)
    return stale

def build_snapshot(bookmarks: dict, routes: dict, now: datetime, source: str) -> dict:
    return {
        "_backup_meta": {
            "captured_at": now.astimezone().isoformat(timespec="seconds"),
            "source": source,
            "bookmark_count": len(bookmarks.get("bookmarks", [])),
            "route_count": len(routes.get("routes", [])),
            "note": "Insurance snapshot of LocWarp live state. 'bookmarks' and 'routes' are each "
                    "re-importable via LocWarp's import endpoints.",
        },
        "bookmarks": bookmarks,
        "routes": routes,
    }
```

**Step 3 — green + lint-imports.** **Commit:** `feat(backup): pure domain policy (fingerprint, stamp, prune)`.

---

### Task 3: port + `infra/persistence/backup_store.py`

**Files:** Create `backend/domain/ports/backup_repository.py`, `backend/infra/persistence/backup_store.py`,
`backend/tests/test_backup_store.py`.

**Step 1 — port** `backend/domain/ports/backup_repository.py`:
```python
from __future__ import annotations
from pathlib import Path
from typing import Protocol

class BackupRepository(Protocol):
    def read_latest(self) -> dict | None: ...
    def write_latest(self, payload: dict) -> None: ...
    def write_snapshot(self, payload: dict, stamp: str) -> Path: ...
    def list_snapshot_names(self) -> list[str]: ...
    def delete_snapshots(self, names: list[str]) -> list[str]: ...
```

**Step 2 — failing tests** `test_backup_store.py` (uses `tmp_path`):
```python
from pathlib import Path
from infra.persistence.backup_store import FileBackupStore
from domain import backup

def _store(tmp_path): return FileBackupStore(lambda: tmp_path / "backups")

def test_write_and_read_latest_roundtrip(tmp_path):
    s = _store(tmp_path)
    assert s.read_latest() is None
    s.write_latest({"_backup_meta": {}, "bookmarks": {"bookmarks": []}, "routes": {"routes": []}})
    assert s.read_latest()["bookmarks"] == {"bookmarks": []}

def test_write_snapshot_and_list(tmp_path):
    s = _store(tmp_path)
    p = s.write_snapshot({"x": 1}, "20260622-120000")
    assert Path(p).name == f"{backup.SNAPSHOT_PREFIX}20260622-120000{backup.SNAPSHOT_SUFFIX}"
    s.write_latest({"x": 0})  # latest must NOT appear in snapshot list
    assert s.list_snapshot_names() == [f"{backup.SNAPSHOT_PREFIX}20260622-120000{backup.SNAPSHOT_SUFFIX}"]

def test_delete_snapshots_best_effort(tmp_path):
    s = _store(tmp_path)
    s.write_snapshot({"x": 1}, "20260622-120000")
    name = s.list_snapshot_names()[0]
    assert s.delete_snapshots([name, "does-not-exist.json"]) == [name]
    assert s.list_snapshot_names() == []
```

**Step 3 — implement** `backend/infra/persistence/backup_store.py`:
```python
from __future__ import annotations
import logging
from pathlib import Path
from typing import Callable

from domain import backup
from services.json_safe import safe_load_json, safe_write_json

logger = logging.getLogger(__name__)

class FileBackupStore:
    def __init__(self, dir_provider: Callable[[], Path]):
        self._dir_provider = dir_provider

    def _dir(self) -> Path:
        d = Path(self._dir_provider()); d.mkdir(parents=True, exist_ok=True); return d

    def read_latest(self) -> dict | None:
        p = self._dir() / backup.LATEST_NAME
        return safe_load_json(p) if p.exists() else None

    def write_latest(self, payload: dict) -> None:
        safe_write_json(self._dir() / backup.LATEST_NAME, payload)

    def write_snapshot(self, payload: dict, stamp: str) -> Path:
        p = self._dir() / f"{backup.SNAPSHOT_PREFIX}{stamp}{backup.SNAPSHOT_SUFFIX}"
        safe_write_json(p, payload); return p

    def list_snapshot_names(self) -> list[str]:
        return sorted(f.name for f in self._dir().iterdir()
                      if backup.parse_snapshot_stamp(f.name) is not None)

    def delete_snapshots(self, names: list[str]) -> list[str]:
        deleted = []
        d = self._dir()
        for name in names:
            try:
                (d / name).unlink(); deleted.append(name)
            except OSError as exc:
                logger.warning("backup prune skip %s: %s", name, exc)
        return deleted
```
> Verify `safe_load_json`/`safe_write_json` signatures during implementation; if `safe_load_json`
> returns `{}`/raises on missing, adapt `read_latest` accordingly (the existence check guards it).

**Step 4 — green + lint-imports** (confirm `infra` still passes — it imports only `domain` + `services.json_safe`). **Commit:** `feat(backup): BackupRepository port + FileBackupStore infra adapter`.

---

### Task 4: `services/backup_service.py`

**Files:** Create `backend/services/backup_service.py`, `backend/tests/test_backup_service.py`.

**Step 1 — failing tests** `test_backup_service.py` (fake in-memory repo + provider):
```python
from datetime import datetime, timedelta
from services.backup_service import BackupService
from domain import backup

class FakeRepo:
    def __init__(self): self.latest=None; self.snaps={}
    def read_latest(self): return self.latest
    def write_latest(self, p): self.latest=p
    def write_snapshot(self, p, stamp): self.snaps[f"{backup.SNAPSHOT_PREFIX}{stamp}{backup.SNAPSHOT_SUFFIX}"]=p; return stamp
    def list_snapshot_names(self): return list(self.snaps)
    def delete_snapshots(self, names): [self.snaps.pop(n,None) for n in names]; return names

def _svc(repo, bms, rts, retention=72):
    return BackupService(repo, lambda: (bms, rts), retention)

def test_skip_when_empty_writes_nothing():
    r = FakeRepo(); _svc(r, {"bookmarks":[]}, {"routes":[]}).tick(datetime(2026,6,22,12,0,0))
    assert r.latest is None and r.snaps == {}

def test_latest_always_refreshed_snapshot_only_on_change():
    r = FakeRepo()
    s = _svc(r, {"categories":[],"bookmarks":[{"id":"a"}]}, {"categories":[],"routes":[]})
    s.tick(datetime(2026,6,22,12,0,0)); assert len(r.snaps)==1 and r.latest is not None
    s.tick(datetime(2026,6,22,12,5,0)); assert len(r.snaps)==1   # unchanged -> no new snapshot
    # change the data and tick again
    s2 = _svc(r, {"categories":[],"bookmarks":[{"id":"a"},{"id":"b"}]}, {"categories":[],"routes":[]})
    s2.tick(datetime(2026,6,22,12,10,0)); assert len(r.snaps)==2

def test_prune_runs_each_tick():
    r = FakeRepo()
    r.snaps[f"{backup.SNAPSHOT_PREFIX}{backup.snapshot_stamp(datetime(2026,6,18,0,0,0))}{backup.SNAPSHOT_SUFFIX}"]={}
    _svc(r, {"categories":[],"bookmarks":[{"id":"a"}]}, {"categories":[],"routes":[]}).tick(datetime(2026,6,22,12,0,0))
    assert all("20260618" not in n for n in r.snaps)

def test_payload_is_restore_compatible_shape():
    r = FakeRepo()
    _svc(r, {"categories":[],"bookmarks":[{"id":"a"}]}, {"categories":[],"routes":[]}).tick(datetime(2026,6,22,12,0,0))
    assert set(r.latest) == {"_backup_meta","bookmarks","routes"}
    assert "bookmarks" in r.latest["bookmarks"] and "routes" in r.latest["routes"]
```

**Step 2 — implement** `backend/services/backup_service.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from domain import backup
from domain.ports.backup_repository import BackupRepository

@dataclass
class BackupTickResult:
    bookmark_count: int = 0
    route_count: int = 0
    changed: bool = False
    pruned: int = 0
    skipped: str | None = None

class BackupService:
    def __init__(self, repo: BackupRepository,
                 snapshot_provider: Callable[[], tuple[dict, dict]],
                 retention_hours: int, source: str = "in-process"):
        self._repo = repo
        self._snapshot_provider = snapshot_provider
        self._retention_hours = retention_hours
        self._source = source

    def tick(self, now: datetime) -> BackupTickResult:
        bookmarks, routes = self._snapshot_provider()
        bm = len(bookmarks.get("bookmarks", [])); rt = len(routes.get("routes", []))
        if bm == 0 and rt == 0:
            return BackupTickResult(skipped="empty")
        prev = self._repo.read_latest()
        changed = prev is None or backup.data_fingerprint(bookmarks, routes) != \
            backup.data_fingerprint(prev.get("bookmarks", {}), prev.get("routes", {}))
        payload = backup.build_snapshot(bookmarks, routes, now, self._source)
        self._repo.write_latest(payload)
        if changed:
            self._repo.write_snapshot(payload, backup.snapshot_stamp(now))
        stale = backup.select_stale_snapshots(self._repo.list_snapshot_names(), now, self._retention_hours)
        deleted = self._repo.delete_snapshots(stale)
        return BackupTickResult(bm, rt, changed, len(deleted))
```

**Step 3 — green + lint-imports** (confirm `services` does not import fastapi/infra). **Commit:** `feat(backup): BackupService.tick orchestration use-case`.

---

### Task 5: manager `snapshot_export()` seams

**Files:** Modify `backend/services/bookmarks.py`, `backend/services/route_store.py`. Tests:
`backend/tests/test_backup_snapshot_seam.py`.

**Step 1 — failing tests** (build managers via `bootstrap.factories`, add items, assert shapes + that the
bookmark snapshot is taken under the lock):
```python
from bootstrap.factories import make_bookmark_manager, make_route_manager

def test_bookmark_snapshot_export_shape(tmp_path, monkeypatch):
    bm = make_bookmark_manager()
    cat = bm.create_category(name="C")
    bm.create_bookmark(name="b", lat=1.0, lng=2.0, category_id=cat.id)
    snap = bm.snapshot_export()
    assert set(snap) == {"categories", "bookmarks"} and len(snap["bookmarks"]) == 1

def test_route_snapshot_export_shape(tmp_path, monkeypatch):
    rm = make_route_manager()
    snap = rm.snapshot_export()
    assert set(snap) == {"categories", "routes"}
```

**Step 2 — implement** on `BookmarkManager` (uses the existing `_store_lock`):
```python
def snapshot_export(self) -> dict:
    """Consistent {categories, bookmarks} read under _store_lock (no torn read vs watcher/_save)."""
    with self._store_lock:
        return {
            "categories": [c.model_dump(mode="json") for c in self.store.categories],
            "bookmarks": [b.model_dump(mode="json") for b in self.store.bookmarks],
        }
```
on `RouteManager` (no lock needed — watcher never writes):
```python
def snapshot_export(self) -> dict:
    return {
        "categories": [c.model_dump(mode="json") for c in self.list_categories()],
        "routes": [r.model_dump(mode="json") for r in self.list_routes()],
    }
```
> Verify the exact attribute names (`self.store.categories`/`.bookmarks`, `self._store_lock`,
> `list_categories`/`list_routes`) against the current files before writing.

**Step 3 — green + lint-imports.** **Commit:** `feat(backup): manager snapshot_export seams (locked bookmark read)`.

---

### Task 6: factory + lifespan wiring + loop

**Files:** Modify `backend/bootstrap/factories.py`, `backend/main.py`. Tests:
`backend/tests/test_backup_loop.py`, extend `backend/tests/test_lifespan.py`.

**Step 1 — factory** in `backend/bootstrap/factories.py`:
```python
def make_backup_service(snapshot_provider, dir_provider=None, retention_hours=None, source="in-process"):
    import config
    from infra.persistence.backup_store import FileBackupStore
    from services.backup_service import BackupService
    repo = FileBackupStore(dir_provider or (lambda: config.BACKUP_DIR))
    return BackupService(repo, snapshot_provider,
                         retention_hours if retention_hours is not None else config.BACKUP_RETENTION_HOURS,
                         source)
```

**Step 2 — loop** (module level in `backend/main.py`, near `_usbmux_presence_watchdog`):
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

**Step 3 — loop test** `test_backup_loop.py` (injected sleep that cancels after K iterations + advancing now):
```python
import asyncio, pytest
from datetime import datetime, timedelta
from main import _bookmark_backup_loop

class Clock:
    def __init__(self): self.t = datetime(2026,6,22,12,0,0)
    def now(self): self.t += timedelta(minutes=5); return self.t

@pytest.mark.asyncio
async def test_loop_ticks_until_cancelled():
    calls = []
    class Svc:
        def tick(self, now): calls.append(now)
    n = {"i": 0}
    async def fake_sleep(_):
        n["i"] += 1
        if n["i"] >= 3: raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await _bookmark_backup_loop(Svc(), interval_s=300, sleep=fake_sleep, now_provider=Clock().now)
    assert len(calls) == 3   # ticks once before each sleep
```
> Match the project's async-test convention (anyio/asyncio marker) used by existing async tests.

**Step 4 — wire lifespan** in `backend/main.py`:
- After `DATA_DIR.mkdir(...)` (line ~771): `config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)`.
- In `AppState.load_state` after managers built:
  ```python
  def _backup_provider():
      return self.bookmark_manager.snapshot_export(), self.route_manager.snapshot_export()
  self.backup_service = make_backup_service(_backup_provider)
  ```
  (init `self.backup_service = None` in `AppState.__init__`.)
- Near `watchdog_task = asyncio.create_task(...)` (line ~852):
  ```python
  backup_task = asyncio.create_task(
      _bookmark_backup_loop(app_state.backup_service, interval_s=config.BACKUP_INTERVAL_S))
  ```
- In shutdown near `watchdog_task.cancel()` (line ~902):
  ```python
  backup_task.cancel()
  try:
      await backup_task
  except (asyncio.CancelledError, Exception):
      pass
  ```

**Step 5 — lifespan test** (extend `test_lifespan.py`): assert `app_state.backup_service is not None`
inside the lifespan `yield`; assert the backup task is cancelled on teardown (no leaked task / a tick
ran). Follow the file's existing lifespan-driving pattern.

**Step 6 — full suite + lint-imports + collect-count delta check.** **Commit:** `feat(backup): lifespan-owned 5-min backup loop + DI wiring`.

---

### Final: whole-branch review + docs

- Update `CLAUDE.md` + `AGENTS.md`: add a short note that `~/.locwarp/backups/` holds the in-process
  rotating snapshots (5-min, change-only, 72h), restorable via `make merge-bookmarks` / `merge-routes`.
- Dispatch the adversarial whole-branch review (multi-dimension → verify), fix confirmed findings.
- `finishing-a-development-branch`: tests green → present merge options to Ravi.
