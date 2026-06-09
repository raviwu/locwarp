# Auto-clear stale USB host pair record — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When USB autopair fails because the host has a stale pair record but the iPhone has forgotten the host certificate, transparently clear host pair records and retry, so the iPhone's "Trust This Computer" prompt actually appears. Apply to both user-triggered `wifi/repair` and the watchdog's auto-connect path; refuse to auto-recover when the user has explicitly tapped "Don't Trust".

**Architecture:** New module `backend/services/usbmux_pair_records.py` isolates the SIP/usbmuxd workaround: it sends the raw `DeletePairRecord` plist message to usbmuxd (the only user-mode path on macOS 11+ to clear `/var/db/lockdown/<udid>.plist`) and removes `~/.pymobiledevice3/<udid>.plist`. It also exposes `autopair_with_recovery()` — the shared try/clear/retry dance used by both `wifi/repair` and `DeviceManager.connect()`. Concurrent calls for the same udid are serialized by a per-udid `asyncio.Lock`. `DeviceManager` keeps a `sticky_user_denied` set so the watchdog stops re-prompting users who tapped "Don't Trust"; `wifi/repair` clears that flag on user intent.

**Tech Stack:** Python 3.11, asyncio, pymobiledevice3 (`PlistMuxConnection` private `_send`/`_receive` for the plist message — no high-level API exists), FastAPI for the endpoint, pytest with `asyncio_mode = strict`.

**Spec reference:** `docs/superpowers/specs/2026-06-09-auto-clear-stale-pair-record-design.md`

**File structure:**

| Path | Responsibility |
|---|---|
| `backend/services/usbmux_pair_records.py` (NEW) | `delete_system_pair_record`, `delete_local_pair_record`, `acquire_pair_lock`, `_is_stale_cert_error`, `autopair_with_recovery` |
| `backend/core/device_manager.py` | Add `sticky_user_denied: set[str]`; rewire `connect()` to use `autopair_with_recovery` and add `UserDeniedPairingError` → sticky |
| `backend/main.py` | Watchdog skips udids in `dm.sticky_user_denied` |
| `backend/api/device.py` | `_humanize_pair_error()` + `wifi/repair` rewired to use `autopair_with_recovery` + clears sticky flag |
| `backend/tests/test_usbmux_pair_records.py` (NEW) | Tests for the helper module (delete_system, delete_local, classifier, lock, recovery) |
| `backend/tests/test_device_repair_endpoint.py` | Tests for the new `wifi/repair` behavior + `_humanize_pair_error` table |
| `backend/tests/test_device_pair_failure.py` | Tests for `DeviceManager.connect()` auto-recovery + sticky_user_denied |
| `CLAUDE.md` | New section "USB pair records under SIP" |

---

## Task 1: `delete_system_pair_record` helper

**Files:**
- Create: `backend/services/usbmux_pair_records.py`
- Create: `backend/tests/test_usbmux_pair_records.py`

The function sends a `DeletePairRecord` plist message to usbmuxd. pymobiledevice3 has no high-level wrapper, so we use `PlistMuxConnection`'s low-level `_send` / `_receive`. The wrapper must never raise — callers chain it from error-handling paths.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_usbmux_pair_records.py`:

```python
"""Tests for backend/services/usbmux_pair_records.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_delete_system_pair_record_sends_correct_plist(monkeypatch):
    """The wrapper must send a {MessageType: DeletePairRecord, PairRecordID: udid}
    plist message to usbmuxd via PlistMuxConnection."""
    from services.usbmux_pair_records import delete_system_pair_record

    sent_messages: list[dict] = []

    fake_conn = MagicMock()
    fake_conn._send = AsyncMock(side_effect=lambda msg: sent_messages.append(msg))
    fake_conn._receive = AsyncMock(return_value={"MessageType": "Result", "Number": 0})
    fake_conn._tag = 1
    fake_conn.close = MagicMock()

    async def fake_create_socket():
        return MagicMock()

    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection.create_usbmux_socket",
        fake_create_socket,
    )
    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection",
        lambda _sock: fake_conn,
    )

    ok = await delete_system_pair_record("00008140-DEADBEEF")

    assert ok is True
    assert len(sent_messages) == 1
    assert sent_messages[0]["MessageType"] == "DeletePairRecord"
    assert sent_messages[0]["PairRecordID"] == "00008140-DEADBEEF"


@pytest.mark.asyncio
async def test_delete_system_pair_record_idempotent_on_missing(monkeypatch):
    """usbmuxd Number=2 means 'no such record' — treat as success (idempotent)."""
    from services.usbmux_pair_records import delete_system_pair_record

    fake_conn = MagicMock()
    fake_conn._send = AsyncMock()
    fake_conn._receive = AsyncMock(return_value={"MessageType": "Result", "Number": 2})
    fake_conn._tag = 1
    fake_conn.close = MagicMock()

    async def fake_create_socket():
        return MagicMock()

    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection.create_usbmux_socket",
        fake_create_socket,
    )
    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection",
        lambda _sock: fake_conn,
    )

    ok = await delete_system_pair_record("UDID-MISSING")
    assert ok is True


@pytest.mark.asyncio
async def test_delete_system_pair_record_returns_false_on_unexpected_number(monkeypatch):
    """Any Number not in {0, 2} signals an unexpected usbmuxd error.
    Function returns False but does not raise."""
    from services.usbmux_pair_records import delete_system_pair_record

    fake_conn = MagicMock()
    fake_conn._send = AsyncMock()
    fake_conn._receive = AsyncMock(return_value={"MessageType": "Result", "Number": 5})
    fake_conn._tag = 1
    fake_conn.close = MagicMock()

    async def fake_create_socket():
        return MagicMock()

    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection.create_usbmux_socket",
        fake_create_socket,
    )
    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection",
        lambda _sock: fake_conn,
    )

    ok = await delete_system_pair_record("UDID-X")
    assert ok is False


@pytest.mark.asyncio
async def test_delete_system_pair_record_does_not_raise_on_socket_failure(monkeypatch):
    """If create_usbmux_socket itself raises (usbmuxd down), we log and return False."""
    from services.usbmux_pair_records import delete_system_pair_record

    async def boom():
        raise ConnectionRefusedError("usbmuxd not running")

    monkeypatch.setattr(
        "services.usbmux_pair_records.PlistMuxConnection.create_usbmux_socket",
        boom,
    )

    ok = await delete_system_pair_record("UDID-Y")
    assert ok is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/test_usbmux_pair_records.py -v
```
Expected: ImportError on `services.usbmux_pair_records` (module doesn't exist yet).

- [ ] **Step 3: Implement the helper**

Create `backend/services/usbmux_pair_records.py`:

```python
"""USB pair record management.

`/var/db/lockdown/<udid>.plist` is SIP-protected on macOS 11+ — even `sudo rm`
fails with "Operation not permitted". The only user-mode path to clear that
file is to ask usbmuxd to delete it via the `DeletePairRecord` plist message;
usbmuxd is SIP-exempt (system daemon, owns the directory).

pymobiledevice3 does not expose a high-level wrapper for `DeletePairRecord`,
so we send the raw plist via `PlistMuxConnection`'s private `_send`/`_receive`.
These have been stable across recent pymobiledevice3 versions, but treat them
as a private-API dependency: pin the surface area to this file so future
upgrades touch one place.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pymobiledevice3.usbmux import PlistMuxConnection

logger = logging.getLogger(__name__)


async def delete_system_pair_record(udid: str) -> bool:
    """Ask usbmuxd to delete `/var/db/lockdown/<udid>.plist`.

    Returns True on success (usbmuxd Number==0) or already-absent (Number==2).
    Returns False on any other outcome — including unexpected usbmuxd error
    codes and socket failures. Never raises; callers chain this from
    error-handling paths where raising would obscure the original fault.
    """
    try:
        sock = await PlistMuxConnection.create_usbmux_socket()
    except Exception as exc:
        logger.warning(
            "delete_system_pair_record: failed to open usbmuxd socket for %s: %s",
            udid, exc,
        )
        return False

    conn = PlistMuxConnection(sock)
    try:
        await conn._send({"MessageType": "DeletePairRecord", "PairRecordID": udid})
        resp = await conn._receive(conn._tag - 1)
    except Exception as exc:
        logger.warning(
            "delete_system_pair_record: send/receive failed for %s: %s", udid, exc,
        )
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass

    number = resp.get("Number")
    if number == 0:
        logger.info("delete_system_pair_record: cleared %s", udid)
        return True
    if number == 2:
        # No such record — already clean.
        logger.debug("delete_system_pair_record: %s already absent", udid)
        return True
    logger.warning(
        "delete_system_pair_record: unexpected usbmuxd response for %s: %r",
        udid, resp,
    )
    return False
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/python -m pytest tests/test_usbmux_pair_records.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/usbmux_pair_records.py backend/tests/test_usbmux_pair_records.py
git commit -m "feat(pair): wrap usbmuxd DeletePairRecord plist message"
```

---

## Task 2: `delete_local_pair_record` helper

**Files:**
- Modify: `backend/services/usbmux_pair_records.py` (append function)
- Modify: `backend/tests/test_usbmux_pair_records.py` (append tests)

`~/.pymobiledevice3/<udid>.plist` is the iOS 17+ RemotePairing cache. Not SIP-protected. Plain file delete.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_usbmux_pair_records.py`:

```python
def test_delete_local_pair_record_removes_existing_file(tmp_path, monkeypatch):
    """If the local file exists, delete it and return True."""
    from services.usbmux_pair_records import delete_local_pair_record

    fake_home = tmp_path / "pmd3"
    fake_home.mkdir()
    target = fake_home / "00008140-DEADBEEF.plist"
    target.write_bytes(b"<plist><dict/></plist>")

    monkeypatch.setattr(
        "services.usbmux_pair_records._local_pair_record_dir",
        lambda: fake_home,
    )

    ok = delete_local_pair_record("00008140-DEADBEEF")
    assert ok is True
    assert not target.exists()


def test_delete_local_pair_record_idempotent_on_missing(tmp_path, monkeypatch):
    """If the file does not exist, still return True (idempotent)."""
    from services.usbmux_pair_records import delete_local_pair_record

    fake_home = tmp_path / "pmd3"
    fake_home.mkdir()

    monkeypatch.setattr(
        "services.usbmux_pair_records._local_pair_record_dir",
        lambda: fake_home,
    )

    ok = delete_local_pair_record("UDID-NEVER-EXISTED")
    assert ok is True


def test_delete_local_pair_record_does_not_raise_on_permission_error(tmp_path, monkeypatch):
    """Permission error during unlink is logged and returns False, never raises."""
    from services.usbmux_pair_records import delete_local_pair_record

    fake_home = tmp_path / "pmd3"
    fake_home.mkdir()
    target = fake_home / "UDID-LOCKED.plist"
    target.write_bytes(b"data")

    monkeypatch.setattr(
        "services.usbmux_pair_records._local_pair_record_dir",
        lambda: fake_home,
    )

    def boom(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "unlink", boom)

    ok = delete_local_pair_record("UDID-LOCKED")
    assert ok is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/test_usbmux_pair_records.py -v
```
Expected: `delete_local_pair_record` ImportError; first 4 tests still pass.

- [ ] **Step 3: Implement**

Append to `backend/services/usbmux_pair_records.py` (after `delete_system_pair_record`):

```python
def _local_pair_record_dir() -> Path:
    """Return `~/.pymobiledevice3` (override target for tests)."""
    return Path.home() / ".pymobiledevice3"


def delete_local_pair_record(udid: str) -> bool:
    """Delete `~/.pymobiledevice3/<udid>.plist` if present.

    Covers the iOS 17+ RemotePairing local cache (not SIP-protected, plain
    file). Returns True on success or already-absent. Returns False on any
    OSError (e.g. read-only mount). Never raises.
    """
    target = _local_pair_record_dir() / f"{udid}.plist"
    if not target.exists():
        return True
    try:
        target.unlink()
        logger.info("delete_local_pair_record: removed %s", target)
        return True
    except OSError as exc:
        logger.warning(
            "delete_local_pair_record: could not remove %s: %s", target, exc,
        )
        return False
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/python -m pytest tests/test_usbmux_pair_records.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/usbmux_pair_records.py backend/tests/test_usbmux_pair_records.py
git commit -m "feat(pair): wrap local ~/.pymobiledevice3/<udid>.plist cleanup"
```

---

## Task 3: `_is_stale_cert_error` classifier

**Files:**
- Modify: `backend/services/usbmux_pair_records.py`
- Modify: `backend/tests/test_usbmux_pair_records.py`

The whitelist includes `ConnectionResetError`, `BrokenPipeError`, `EOFError`, `ssl.SSLError` (base — covers `SSLEOFError`, `SSLZeroReturnError`, etc.), and `pymobiledevice3.exceptions.ConnectionTerminatedError`. `ConnectionAbortedError` (USB cable unplugged) is deliberately excluded. Plus a name-based fallback so a re-wrapped exception still classifies.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_usbmux_pair_records.py`:

```python
import ssl

from pymobiledevice3.exceptions import (
    ConnectionTerminatedError,
    PairingDialogResponsePendingError,
    UserDeniedPairingError,
)


@pytest.mark.parametrize(
    "exc, expected",
    [
        # Stale-cert whitelist — these signal "host has a record but iPhone
        # has forgotten this Mac" so we should clear and retry.
        (ConnectionTerminatedError(), True),
        (ConnectionResetError("Connection reset by peer"), True),
        (BrokenPipeError(), True),
        (EOFError(), True),
        (ssl.SSLError("handshake failed"), True),
        (ssl.SSLEOFError("EOF during handshake"), True),
        # Deliberately excluded — these are NOT stale cert.
        (ConnectionAbortedError("ECONNABORTED"), False),  # USB unplug mid-flow
        (PairingDialogResponsePendingError(), False),     # user hasn't tapped Trust yet
        (UserDeniedPairingError(), False),                # user tapped Don't Trust
        (RuntimeError("something else"), False),
        (ValueError("nope"), False),
    ],
)
def test_is_stale_cert_error_table(exc, expected):
    from services.usbmux_pair_records import _is_stale_cert_error
    assert _is_stale_cert_error(exc) is expected


def test_is_stale_cert_error_name_based_fallback():
    """A re-wrapped exception whose class name contains a known signal
    must still classify as stale-cert."""
    from services.usbmux_pair_records import _is_stale_cert_error

    class _SomeWrappedConnectionTerminatedError(Exception):
        pass

    class _CustomSSLError(Exception):
        pass

    assert _is_stale_cert_error(_SomeWrappedConnectionTerminatedError()) is True
    assert _is_stale_cert_error(_CustomSSLError()) is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/test_usbmux_pair_records.py -v
```
Expected: AttributeError on `_is_stale_cert_error`; other tests still pass.

- [ ] **Step 3: Implement**

Append to `backend/services/usbmux_pair_records.py`:

```python
import ssl

from pymobiledevice3.exceptions import ConnectionTerminatedError

# Exceptions that mean "iPhone rejected the host cert during SSL handshake" —
# the iPhone has forgotten this Mac. Clearing host pair records and retrying
# autopair lets the next attempt fall through to _pair() (the trust prompt path).
#
# ConnectionAbortedError is deliberately EXCLUDED: ECONNABORTED typically means
# the USB cable was unplugged mid-handshake. Clearing pair records on a transient
# cable hiccup would be destructive.
_STALE_CERT_TYPES: tuple[type[BaseException], ...] = (
    ConnectionResetError,
    BrokenPipeError,
    EOFError,
    ssl.SSLError,
    ConnectionTerminatedError,
)

_STALE_CERT_NAME_SIGNALS: tuple[str, ...] = (
    "ConnectionTerminated",
    "SSLError",
    "SSLEOFError",
)


def _is_stale_cert_error(exc: BaseException) -> bool:
    """Return True if the exception signals a stale host pair record.

    Checks the exception type whitelist first, then falls back to class-name
    matching so a re-wrapped exception (e.g. an internal pymobiledevice3
    refactor that subclasses ConnectionTerminatedError differently) still
    routes correctly.
    """
    if isinstance(exc, _STALE_CERT_TYPES):
        return True
    name = type(exc).__name__
    return any(s in name for s in _STALE_CERT_NAME_SIGNALS)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/python -m pytest tests/test_usbmux_pair_records.py -v
```
Expected: 20 passed (7 prior + 11 parametrize cases + 2 fallback cases).

- [ ] **Step 5: Commit**

```bash
git add backend/services/usbmux_pair_records.py backend/tests/test_usbmux_pair_records.py
git commit -m "feat(pair): _is_stale_cert_error classifier"
```

---

## Task 4: Per-udid `asyncio.Lock` registry

**Files:**
- Modify: `backend/services/usbmux_pair_records.py`
- Modify: `backend/tests/test_usbmux_pair_records.py`

`wifi/repair` (user-triggered) and the watchdog's `connect()` can both try to recover the same udid concurrently. Without coordination they'd both delete + retry, possibly resulting in two trust prompts on the iPhone or one path overwriting the other's freshly-written pair record.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_usbmux_pair_records.py`:

```python
@pytest.mark.asyncio
async def test_acquire_pair_lock_same_udid_returns_same_lock():
    """Two acquires for the same udid must return the SAME Lock instance —
    otherwise concurrent callers won't serialize."""
    from services.usbmux_pair_records import acquire_pair_lock, _pair_locks

    # Isolate test from any module-level state set by earlier tests.
    _pair_locks.clear()

    lock1 = await acquire_pair_lock("UDID-A")
    lock2 = await acquire_pair_lock("UDID-A")
    assert lock1 is lock2


@pytest.mark.asyncio
async def test_acquire_pair_lock_different_udids_return_distinct_locks():
    """Locks must be per-udid — A's lock must not block B."""
    from services.usbmux_pair_records import acquire_pair_lock, _pair_locks
    _pair_locks.clear()

    lock_a = await acquire_pair_lock("UDID-A")
    lock_b = await acquire_pair_lock("UDID-B")
    assert lock_a is not lock_b


@pytest.mark.asyncio
async def test_pair_lock_serializes_concurrent_acquires_for_same_udid():
    """When two coroutines hold the same udid's lock, the second waits."""
    from services.usbmux_pair_records import acquire_pair_lock, _pair_locks
    _pair_locks.clear()

    order: list[str] = []
    release_first = asyncio.Event()

    async def first():
        lock = await acquire_pair_lock("UDID-S")
        async with lock:
            order.append("first-in")
            await release_first.wait()
            order.append("first-out")

    async def second():
        # Yield once so `first` enters its lock first.
        await asyncio.sleep(0)
        lock = await acquire_pair_lock("UDID-S")
        async with lock:
            order.append("second-in")

    task_first = asyncio.create_task(first())
    task_second = asyncio.create_task(second())
    await asyncio.sleep(0.05)  # let both reach steady state
    # At this point first is in, second is waiting
    assert order == ["first-in"]
    release_first.set()
    await asyncio.gather(task_first, task_second)
    assert order == ["first-in", "first-out", "second-in"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/test_usbmux_pair_records.py -v
```
Expected: ImportError on `acquire_pair_lock` / `_pair_locks`.

- [ ] **Step 3: Implement**

Append to `backend/services/usbmux_pair_records.py`:

```python
import asyncio

# Per-udid asyncio.Lock so concurrent autopair-with-recovery flows (watchdog +
# user-triggered wifi/repair) don't both delete + re-autopair the same device.
# Grows by one entry per udid the process ever sees; bounded by physical
# device cardinality (typically 1-3). Process restart clears it.
_pair_locks: dict[str, asyncio.Lock] = {}
_pair_locks_guard = asyncio.Lock()


async def acquire_pair_lock(udid: str) -> asyncio.Lock:
    """Return the per-udid asyncio.Lock for this udid, creating it on first
    use. Callers must `async with` the returned lock to actually hold it.

    The guard lock around the dict ensures two concurrent acquires for the
    same new udid don't race and create two different Lock instances.
    """
    async with _pair_locks_guard:
        lock = _pair_locks.get(udid)
        if lock is None:
            lock = asyncio.Lock()
            _pair_locks[udid] = lock
        return lock
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/python -m pytest tests/test_usbmux_pair_records.py -v
```
Expected: 23 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/usbmux_pair_records.py backend/tests/test_usbmux_pair_records.py
git commit -m "feat(pair): per-udid asyncio.Lock registry for repair serialization"
```

---

## Task 5: `autopair_with_recovery` — the shared try/clear/retry helper

**Files:**
- Modify: `backend/services/usbmux_pair_records.py`
- Modify: `backend/tests/test_usbmux_pair_records.py`

This is the core integration: wraps `create_using_usbmux(autopair=True)`, holds the per-udid lock, and on a stale-cert exception clears host pair records and retries exactly once. Both `wifi/repair` (Task 7) and `DeviceManager.connect()` (Task 8) call this instead of `create_using_usbmux` directly.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_usbmux_pair_records.py`:

```python
@pytest.mark.asyncio
async def test_autopair_with_recovery_passes_through_on_success(monkeypatch):
    """When autopair succeeds first try, no clearing happens, stale_cleared=False."""
    from services.usbmux_pair_records import autopair_with_recovery, _pair_locks
    _pair_locks.clear()

    fake_lockdown = MagicMock(name="lockdown")
    calls: list[str] = []

    async def fake_create(serial=None, autopair=True):
        calls.append(f"create({serial}, autopair={autopair})")
        return fake_lockdown

    async def fake_delete_sys(udid):
        calls.append(f"delete_sys({udid})")
        return True

    def fake_delete_local(udid):
        calls.append(f"delete_local({udid})")
        return True

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local)

    lockdown, stale_cleared = await autopair_with_recovery("UDID-OK")
    assert lockdown is fake_lockdown
    assert stale_cleared is False
    assert calls == ["create(UDID-OK, autopair=True)"]  # no deletes ran


@pytest.mark.asyncio
async def test_autopair_with_recovery_clears_then_retries_on_stale_cert(monkeypatch):
    """Stale-cert exception triggers delete_system + delete_local + retry.
    Returns (lockdown, stale_cleared=True) when the retry succeeds."""
    from services.usbmux_pair_records import autopair_with_recovery, _pair_locks
    _pair_locks.clear()

    fake_lockdown = MagicMock(name="lockdown")
    attempts = {"n": 0}
    calls: list[str] = []

    async def fake_create(serial=None, autopair=True):
        attempts["n"] += 1
        calls.append(f"create#{attempts['n']}({serial})")
        if attempts["n"] == 1:
            raise ConnectionResetError("Connection terminated")
        return fake_lockdown

    async def fake_delete_sys(udid):
        calls.append(f"delete_sys({udid})")
        return True

    def fake_delete_local(udid):
        calls.append(f"delete_local({udid})")
        return True

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local)

    lockdown, stale_cleared = await autopair_with_recovery("UDID-STALE")
    assert lockdown is fake_lockdown
    assert stale_cleared is True
    assert calls == [
        "create#1(UDID-STALE)",
        "delete_sys(UDID-STALE)",
        "delete_local(UDID-STALE)",
        "create#2(UDID-STALE)",
    ]


@pytest.mark.asyncio
async def test_autopair_with_recovery_does_not_clear_on_non_stale_exception(monkeypatch):
    """A non-stale exception (e.g. user hasn't tapped Trust yet) must NOT
    trigger pair record deletion. It propagates unchanged."""
    from services.usbmux_pair_records import autopair_with_recovery, _pair_locks
    from pymobiledevice3.exceptions import PairingDialogResponsePendingError
    _pair_locks.clear()

    calls: list[str] = []

    async def fake_create(serial=None, autopair=True):
        calls.append("create")
        raise PairingDialogResponsePendingError()

    async def fake_delete_sys(udid):
        calls.append("delete_sys")
        return True

    def fake_delete_local(udid):
        calls.append("delete_local")
        return True

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local)

    with pytest.raises(PairingDialogResponsePendingError):
        await autopair_with_recovery("UDID-PENDING")
    assert calls == ["create"]


@pytest.mark.asyncio
async def test_autopair_with_recovery_propagates_retry_failure(monkeypatch):
    """If both attempts fail (still stale-cert), propagate the LATEST exception."""
    from services.usbmux_pair_records import autopair_with_recovery, _pair_locks
    _pair_locks.clear()

    attempts = {"n": 0}

    async def fake_create(serial=None, autopair=True):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionResetError("first fail")
        raise EOFError("second fail (different exception type, still stale)")

    async def fake_delete_sys(udid):
        return True

    def fake_delete_local(udid):
        return True

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local)

    with pytest.raises(EOFError, match="second fail"):
        await autopair_with_recovery("UDID-DEAD")


@pytest.mark.asyncio
async def test_autopair_with_recovery_serializes_concurrent_calls_for_same_udid(monkeypatch):
    """Two concurrent autopair_with_recovery calls for the same udid must
    serialize via the per-udid lock — the second must not start until the
    first releases."""
    from services.usbmux_pair_records import autopair_with_recovery, _pair_locks
    _pair_locks.clear()

    order: list[str] = []
    release_first = asyncio.Event()
    fake_lockdown = MagicMock()

    async def fake_create(serial=None, autopair=True):
        order.append(f"enter:{serial}")
        if serial == "first-marker":
            await release_first.wait()
        order.append(f"exit:{serial}")
        return fake_lockdown

    async def fake_delete_sys(udid):
        return True

    def fake_delete_local(udid):
        return True

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local)

    # First call holds; both use udid "UDID-RACE" for lock contention but the
    # serial passed to create distinguishes which call is in flight.
    async def call_first():
        # Patch the serial so we can see ordering
        await autopair_with_recovery("UDID-RACE")
    # We can't easily distinguish without changing API; instead we rely on
    # `order` only containing one in-flight at a time.

    async def call_one():
        order.append("call1-acquire")
        await autopair_with_recovery("UDID-RACE")
        order.append("call1-done")

    async def call_two():
        await asyncio.sleep(0)  # ensure call1 enters lock first
        order.append("call2-acquire")
        await autopair_with_recovery("UDID-RACE")
        order.append("call2-done")

    # To make ordering visible we sidestep release_first and use a simple
    # in-flight counter: at most ONE create() may be running at a time for
    # the same udid. Re-define fake_create to enforce that.
    in_flight = {"n": 0}
    max_seen = {"n": 0}

    async def fake_create_serial(serial=None, autopair=True):
        in_flight["n"] += 1
        max_seen["n"] = max(max_seen["n"], in_flight["n"])
        await asyncio.sleep(0.02)  # let any concurrent call try to enter
        in_flight["n"] -= 1
        return fake_lockdown

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create_serial)

    await asyncio.gather(call_one(), call_two())
    assert max_seen["n"] == 1, "lock did not serialize — both calls ran concurrently"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/test_usbmux_pair_records.py -v
```
Expected: ImportError on `autopair_with_recovery`; the new 5 tests fail.

- [ ] **Step 3: Implement**

Append to `backend/services/usbmux_pair_records.py`:

```python
from pymobiledevice3.lockdown import create_using_usbmux


async def autopair_with_recovery(udid: str, autopair: bool = True):
    """Try `create_using_usbmux(serial=udid, autopair=autopair)`. If a
    stale-cert exception fires, clear host pair records (system + local)
    once and retry. Returns `(lockdown_client, stale_cleared)`.

    Acquires the per-udid pair lock for the entire flow so concurrent
    callers (watchdog + user-triggered repair) don't double-clear.

    Non-stale exceptions propagate unchanged — in particular,
    `PairingDialogResponsePendingError` and `UserDeniedPairingError` are
    NOT treated as stale-cert and never trigger record deletion.
    """
    lock = await acquire_pair_lock(udid)
    async with lock:
        try:
            lockdown = await create_using_usbmux(serial=udid, autopair=autopair)
            return lockdown, False
        except Exception as exc:
            if not _is_stale_cert_error(exc):
                raise
            logger.info(
                "autopair_with_recovery: stale-cert detected for %s (%s: %s); "
                "clearing host pair records and retrying once",
                udid, type(exc).__name__, exc,
            )
            await delete_system_pair_record(udid)
            delete_local_pair_record(udid)
            # Retry exactly once. If THIS attempt fails, propagate whatever
            # exception came out — the caller decides what to surface to
            # the user.
            lockdown = await create_using_usbmux(serial=udid, autopair=autopair)
            return lockdown, True
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/python -m pytest tests/test_usbmux_pair_records.py -v
```
Expected: 28 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/usbmux_pair_records.py backend/tests/test_usbmux_pair_records.py
git commit -m "feat(pair): autopair_with_recovery wraps stale-cert clear + retry"
```

---

## Task 6: `_humanize_pair_error` in api/device.py

**Files:**
- Modify: `backend/api/device.py` (add function near the existing `_classify_repair_error`)
- Modify: `backend/tests/test_device_repair_endpoint.py`

User-facing error messages should be specific to the failure mode, not the generic "tap Trust" that misleads users when there's no prompt available.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_device_repair_endpoint.py`:

```python
import pytest as _pytest

from pymobiledevice3.exceptions import (
    PairingDialogResponsePendingError,
    UserDeniedPairingError,
    ConnectionTerminatedError,
)


@_pytest.mark.parametrize(
    "exc, stale_cleared, expected_substring",
    [
        (PairingDialogResponsePendingError(), False, "請在 iPhone 解鎖畫面"),
        (UserDeniedPairingError(), False, "重置位置與隱私權"),
        (ConnectionTerminatedError(), True, "已重置配對紀錄"),
        (RuntimeError("某種未知錯誤"), False, "USB 配對失敗"),
    ],
)
def test_humanize_pair_error_table(exc, stale_cleared, expected_substring):
    from api.device import _humanize_pair_error
    msg = _humanize_pair_error(exc, stale_cleared=stale_cleared)
    assert expected_substring in msg
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_repair_endpoint.py::test_humanize_pair_error_table -v
```
Expected: ImportError on `_humanize_pair_error`.

- [ ] **Step 3: Implement**

Add to `backend/api/device.py`. Place the function just below the existing `_classify_repair_error` function (around line 134):

```python
def _humanize_pair_error(exc: BaseException, *, stale_cleared: bool) -> str:
    """Map a USB pair failure to a specific, actionable user-facing message.

    The branches are ordered so a "user hasn't tapped Trust yet" case wins
    over the post-stale-clear fallback — if both could apply, the more
    specific message helps the user more.
    """
    name = type(exc).__name__
    msg = str(exc)
    lower = msg.lower()

    if "PairingDialogResponsePending" in name or "consent" in lower:
        return "請在 iPhone 解鎖畫面上按「信任」"

    if "UserDeniedPairing" in name or "denied" in lower:
        return (
            "之前在 iPhone 上點了「不信任」。請到 iPhone Settings → 一般 → "
            "移轉或重置 iPhone → 重置 → 重置位置與隱私權，然後重插 USB"
        )

    if stale_cleared:
        return (
            "已重置配對紀錄但 iPhone 仍未跳信任提示。請確認 iPhone 已解鎖、"
            "USB 線可傳輸資料；如仍不出現，請走 Settings → 一般 → 移轉或重置 "
            "iPhone → 重置 → 重置位置與隱私權"
        )

    return f"USB 配對失敗:{exc}"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_repair_endpoint.py -v
```
Expected: all tests pass, including 4 new parametrize cases.

- [ ] **Step 5: Commit**

```bash
git add backend/api/device.py backend/tests/test_device_repair_endpoint.py
git commit -m "feat(repair): _humanize_pair_error — specific msg per failure mode"
```

---

## Task 7: Rewire `wifi/repair` to use `autopair_with_recovery` + humanized errors

**Files:**
- Modify: `backend/api/device.py:179-191` (the existing `try: lockdown = await create_using_usbmux(...)` block in `wifi_repair`)
- Modify: `backend/tests/test_device_repair_endpoint.py`

Replace the bare autopair call with `autopair_with_recovery`. On success, response carries `stale_cleared` so logs and future telemetry can see whether the recovery fired. On failure, use `_humanize_pair_error` for richer messages. Also clear the `sticky_user_denied` flag on the DeviceManager (added in Task 8 — for this task, just call `dm.sticky_user_denied.discard(udid)`; the attribute exists after Task 8 is merged; for now write the call defensively with `getattr(dm, "sticky_user_denied", set()).discard(udid)` so the test order is independent).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_device_repair_endpoint.py`:

```python
def test_wifi_repair_clears_stale_cert_and_retries(monkeypatch):
    """A stale-cert exception on first autopair triggers cleanup + retry;
    successful retry returns 200 with stale_cleared=True in the response."""
    from fastapi.testclient import TestClient
    from main import app

    raw_dev = MagicMock(serial="UDID-STALE", connection_type="USB")

    async def fake_mux_list():
        return [raw_dev]

    attempts = {"n": 0}
    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {"ProductVersion": "16.5", "DeviceName": "Stale iPhone"}

    async def fake_create(serial=None, autopair=True):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionResetError("Connection terminated")
        return fake_lockdown

    deletes: list[str] = []

    async def fake_delete_sys(udid):
        deletes.append(f"sys:{udid}")
        return True

    def fake_delete_local(udid):
        deletes.append(f"local:{udid}")
        return True

    monkeypatch.setattr("pymobiledevice3.usbmux.list_devices", fake_mux_list, raising=False)
    monkeypatch.setattr("pymobiledevice3.lockdown.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": "UDID-STALE"})

    # Body of the response varies slightly depending on the iOS-17+ branch;
    # we only assert what's relevant to recovery.
    assert resp.status_code == 200
    body = resp.json()
    assert body["udid"] == "UDID-STALE"
    assert body.get("stale_cleared") is True
    # Both clear paths fired exactly once during recovery.
    assert "sys:UDID-STALE" in deletes
    assert "local:UDID-STALE" in deletes
    # Exactly two autopair attempts.
    assert attempts["n"] == 2


def test_wifi_repair_does_not_clear_on_pairing_pending(monkeypatch):
    """A PairingDialogResponsePendingError must NOT trigger pair record
    deletion. Response is 500 with `trust_failed` code and the specific
    'tap Trust' message."""
    from fastapi.testclient import TestClient
    from main import app

    raw_dev = MagicMock(serial="UDID-PEND", connection_type="USB")

    async def fake_mux_list():
        return [raw_dev]

    async def fake_create(serial=None, autopair=True):
        raise PairingDialogResponsePendingError()

    deletes: list[str] = []

    async def fake_delete_sys(udid):
        deletes.append(udid)
        return True

    def fake_delete_local(udid):
        deletes.append(udid)
        return True

    monkeypatch.setattr("pymobiledevice3.usbmux.list_devices", fake_mux_list, raising=False)
    monkeypatch.setattr("pymobiledevice3.lockdown.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": "UDID-PEND"})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["code"] == "trust_failed"
    assert detail["stale_cleared"] is False
    assert "請在 iPhone 解鎖畫面" in detail["message"]
    # Critically: NO deletion fired.
    assert deletes == []


def test_wifi_repair_user_denied_message_mentions_reset(monkeypatch):
    """UserDeniedPairingError produces the 'Reset Location & Privacy' message."""
    from fastapi.testclient import TestClient
    from main import app

    raw_dev = MagicMock(serial="UDID-DENY", connection_type="USB")

    async def fake_mux_list():
        return [raw_dev]

    async def fake_create(serial=None, autopair=True):
        raise UserDeniedPairingError()

    monkeypatch.setattr("pymobiledevice3.usbmux.list_devices", fake_mux_list, raising=False)
    monkeypatch.setattr("pymobiledevice3.lockdown.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": "UDID-DENY"})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["code"] == "trust_failed"
    assert "重置位置與隱私權" in detail["message"]


def test_wifi_repair_retry_failure_uses_clearer_message(monkeypatch):
    """When clearing + retry both fail, response uses
    `trust_prompt_unavailable` code with the post-retry humanized message."""
    from fastapi.testclient import TestClient
    from main import app

    raw_dev = MagicMock(serial="UDID-DEAD", connection_type="USB")

    async def fake_mux_list():
        return [raw_dev]

    async def fake_create(serial=None, autopair=True):
        raise ConnectionResetError("still stale")

    async def fake_delete_sys(udid):
        return True

    def fake_delete_local(udid):
        return True

    monkeypatch.setattr("pymobiledevice3.usbmux.list_devices", fake_mux_list, raising=False)
    monkeypatch.setattr("pymobiledevice3.lockdown.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": "UDID-DEAD"})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["code"] == "trust_prompt_unavailable"
    assert detail["stale_cleared"] is True
    assert "已重置配對紀錄" in detail["message"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_repair_endpoint.py -v
```
Expected: the 4 new tests fail. The first one fails because the current code doesn't retry; the second fails because the current code might still delete records; the third fails because UserDenied currently maps to the generic message; the fourth fails because the `trust_prompt_unavailable` code doesn't exist yet.

- [ ] **Step 3: Rewire `wifi_repair`**

Edit `backend/api/device.py`. The current Step-1 block (around lines 179-191) looks like:

```python
udid = usb_dev.serial
_tunnel_logger.info("Re-pair requested for USB device %s", udid)

# Step 1: USB lockdown autopair — pops Trust prompt if USB record missing.
try:
    lockdown = await create_using_usbmux(serial=udid, autopair=True)
except Exception as e:
    raise HTTPException(
        status_code=500,
        detail={
            "code": "trust_failed",
            "message": f"USB 信任失敗 — 請在 iPhone 解鎖畫面上點「信任」後再試:{e}",
            "udid": udid,
        },
    )
```

Replace with:

```python
udid = usb_dev.serial
_tunnel_logger.info("Re-pair requested for USB device %s", udid)

# Clear any sticky "user denied" flag from the watchdog — explicit user
# intent (they clicked Re-trust) overrides the watchdog's auto-skip.
dm = _dm()
try:
    dm.sticky_user_denied.discard(udid)
except AttributeError:
    pass  # set will exist once Task 8 lands; defensive for ordering

# Step 1: USB lockdown autopair via the shared recovery helper. If the
# host has a stale pair record (iPhone has forgotten this Mac), the
# helper clears it and retries exactly once — that's the only way to
# coax the iPhone into showing the "Trust This Computer" prompt again
# under macOS 11+ SIP rules (sudo rm of /var/db/lockdown/ does not work).
from services.usbmux_pair_records import autopair_with_recovery
try:
    lockdown, stale_cleared = await autopair_with_recovery(udid, autopair=True)
except Exception as exc:
    # Distinguish the "we already cleared, but iPhone still won't prompt"
    # case from "first attempt failed, never cleared" — the former gets
    # a different code so the UI can show a stronger guidance string.
    if _is_stale_cert_error_from_pair_records(exc):
        raise HTTPException(
            status_code=500,
            detail={
                "code": "trust_prompt_unavailable",
                "message": _humanize_pair_error(exc, stale_cleared=True),
                "udid": udid,
                "stale_cleared": True,
            },
        )
    raise HTTPException(
        status_code=500,
        detail={
            "code": "trust_failed",
            "message": _humanize_pair_error(exc, stale_cleared=False),
            "udid": udid,
            "stale_cleared": False,
        },
    )
```

Also add a thin re-export at the top of `wifi_repair` (or as a module-level helper above it) so the handler can decide which code path it's in without importing the private classifier inline:

```python
def _is_stale_cert_error_from_pair_records(exc: BaseException) -> bool:
    """Thin alias so the handler doesn't import a private symbol inline."""
    from services.usbmux_pair_records import _is_stale_cert_error
    return _is_stale_cert_error(exc)
```

Place this helper near `_humanize_pair_error` (added in Task 6).

For the success path, the existing code already builds the response dict at the bottom of `wifi_repair`. Find that response (look for `return {"status": "paired", ...}`) and add `stale_cleared` to it:

```python
return {
    "status": "paired",
    "udid": udid,
    "name": name,
    "ios_version": ios_version,
    "remote_record_regenerated": remote_record_regenerated,
    "stale_cleared": stale_cleared,
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_repair_endpoint.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Run the full backend suite**

```bash
cd backend && .venv/bin/python -m pytest -q
```
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add backend/api/device.py backend/tests/test_device_repair_endpoint.py
git commit -m "feat(repair): wifi/repair auto-clears stale cert + richer error messages"
```

---

## Task 8: `sticky_user_denied` set + `DeviceManager.connect()` recovery + watchdog gate

**Files:**
- Modify: `backend/core/device_manager.py` (add `sticky_user_denied` on `DeviceManager.__init__`; rewire `connect()`)
- Modify: `backend/main.py` (watchdog skips udids in `dm.sticky_user_denied`)
- Modify: `backend/tests/test_device_pair_failure.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_device_pair_failure.py`:

```python
def test_device_manager_has_empty_sticky_user_denied_set():
    """DeviceManager must expose an instance-level set for sticky 'don't trust' udids."""
    from core.device_manager import DeviceManager
    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()
    assert hasattr(dm, "sticky_user_denied")
    assert dm.sticky_user_denied == set()


def test_connect_auto_clears_stale_cert_and_retries(monkeypatch):
    """DeviceManager.connect() should use autopair_with_recovery; on a
    stale-cert first failure, the recovery helper clears and retries, and
    connect() proceeds as if the first attempt had succeeded."""
    from core.device_manager import DeviceManager

    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()

    attempts = {"n": 0}
    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {
        "DeviceName": "Stale iPhone",
        "ProductVersion": "16.5",
    }
    fake_lockdown.get_developer_mode_status = AsyncMock(return_value=False)

    async def fake_create(serial=None, autopair=True):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionResetError("Connection terminated")
        return fake_lockdown

    async def fake_delete_sys(udid):
        return True

    def fake_delete_local(udid):
        return True

    # autopair_with_recovery imports create_using_usbmux from itself
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("services.usbmux_pair_records.delete_system_pair_record", fake_delete_sys)
    monkeypatch.setattr("services.usbmux_pair_records.delete_local_pair_record", fake_delete_local)
    # ... and DeviceManager.connect imports it from device_manager
    monkeypatch.setattr("core.device_manager.create_using_usbmux", fake_create)

    asyncio.run(dm.connect("00008140-STALE"))

    assert attempts["n"] == 2
    assert "00008140-STALE" in dm._connections


def test_connect_marks_user_denied_sticky(monkeypatch):
    """When create_using_usbmux raises UserDeniedPairingError, connect() must
    add the udid to dm.sticky_user_denied and re-raise."""
    from core.device_manager import DeviceManager
    from pymobiledevice3.exceptions import UserDeniedPairingError

    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()

    async def fake_create(serial=None, autopair=True):
        raise UserDeniedPairingError()

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)
    monkeypatch.setattr("core.device_manager.create_using_usbmux", fake_create)

    with pytest.raises(UserDeniedPairingError):
        asyncio.run(dm.connect("00008140-DENIED"))

    assert "00008140-DENIED" in dm.sticky_user_denied
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_pair_failure.py -v
```
Expected: 3 new tests fail.

- [ ] **Step 3: Add `sticky_user_denied` to `DeviceManager.__init__`**

In `backend/core/device_manager.py`, find the existing `class DeviceManager:` `__init__` (around line 207) which currently looks like:

```python
def __init__(self) -> None:
    self._connections: Dict[str, _ActiveConnection] = {}
    self._lock = asyncio.Lock()
```

Replace with:

```python
def __init__(self) -> None:
    self._connections: Dict[str, _ActiveConnection] = {}
    self._lock = asyncio.Lock()
    # Udids the user has explicitly tapped "Don't Trust" on the iPhone for.
    # The watchdog refuses to auto-connect these (would just trigger another
    # ignored prompt cycle). User clicking the in-app Re-trust button clears
    # the flag for that udid (see api/device.py wifi_repair handler).
    self.sticky_user_denied: set[str] = set()
```

- [ ] **Step 4: Rewire `DeviceManager.connect()` to use `autopair_with_recovery`**

In `backend/core/device_manager.py`, find the `connect()` method's first `create_using_usbmux` call (around line 434). The current block looks like:

```python
# Create a fresh lockdown client to read the iOS version.
try:
    lockdown = await create_using_usbmux(serial=udid)
except Exception:
    logger.exception("Cannot create lockdown client for %s via %s", udid, connection_type)
    raise
```

Replace with:

```python
# Use the shared autopair-with-recovery helper. If the host has a stale
# pair record (iPhone has forgotten this Mac), the helper transparently
# clears the host-side records and retries — which lets the iPhone show
# its "Trust This Computer" prompt without any user-side action other
# than tapping Trust when it appears.
from services.usbmux_pair_records import autopair_with_recovery
from pymobiledevice3.exceptions import UserDeniedPairingError as _UserDenied

try:
    lockdown, _stale_cleared = await autopair_with_recovery(udid, autopair=True)
except _UserDenied:
    # User tapped "Don't Trust". Don't auto-retry forever — mark sticky so
    # the watchdog stops re-prompting. The in-app Re-trust button clears
    # this flag (api/device.py wifi_repair).
    self.sticky_user_denied.add(udid)
    logger.warning(
        "User denied pairing for %s — marked sticky_user_denied", udid,
    )
    raise
except Exception:
    logger.exception("Cannot create lockdown client for %s via %s", udid, connection_type)
    raise
```

- [ ] **Step 5: Gate the watchdog**

In `backend/main.py`, find the `for udid in new_udids:` loop in `_usbmux_presence_watchdog()` (around line 714). At the very top of the loop body, add a sticky check BEFORE the cooldown check:

```python
for udid in new_udids:
    if len(dm._connections) >= MAX_DEVICES:
        break
    # Stop trying to auto-connect a device the user has tapped "Don't Trust" on.
    # The user can break the spell by hitting the in-app Re-trust button,
    # which clears this set entry (see api/device.py wifi_repair handler).
    if udid in dm.sticky_user_denied:
        continue
    fail_count = reconnect_failure_count.get(udid, 0)
    # ... rest of existing loop body unchanged
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_pair_failure.py -v
```
Expected: 3 new tests pass; all prior tests still pass.

- [ ] **Step 7: Run the full backend suite**

```bash
cd backend && .venv/bin/python -m pytest -q
```
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add backend/core/device_manager.py backend/main.py backend/tests/test_device_pair_failure.py
git commit -m "feat(device): connect() uses autopair_with_recovery + sticky user_denied"
```

---

## Task 9: CLAUDE.md note

**Files:**
- Modify: `CLAUDE.md`

Add a new section after the existing "Bookmark / Route store: CRDT merge semantics" section so future debug sessions find the SIP / usbmuxd workaround in seconds instead of hours.

- [ ] **Step 1: Locate the insertion point**

```bash
grep -n "## Personal repo conventions" CLAUDE.md
```
The new section goes immediately before `## Personal repo conventions`. Confirm the line number.

- [ ] **Step 2: Insert the section**

Find the line `## Personal repo conventions` in `CLAUDE.md`. Just before it, add:

```markdown
## USB pair records under SIP

`/var/db/lockdown/<udid>.plist` is SIP-protected on macOS 11+. Even
`sudo rm` fails with "Operation not permitted". The only user-mode
path to clear that file is to send a `DeletePairRecord` plist message
to `usbmuxd` (which is SIP-exempt, being a system daemon that owns
the directory).

`pymobiledevice3` does not wrap this in a high-level API. The wrapper
lives at `backend/services/usbmux_pair_records.py`:

- `delete_system_pair_record(udid)` — sends the raw plist to usbmuxd.
- `delete_local_pair_record(udid)` — removes `~/.pymobiledevice3/<udid>.plist`
  (iOS 17+ RemotePairing cache; not SIP-protected).
- `autopair_with_recovery(udid)` — the shared "try autopair → on stale-cert
  clear records → retry once" dance used by both `wifi/repair` and
  `DeviceManager.connect()`.

The stale-cert classifier (`_is_stale_cert_error`) whitelists
`ConnectionResetError`, `BrokenPipeError`, `EOFError`, `ssl.SSLError`,
and `pymobiledevice3.exceptions.ConnectionTerminatedError`.
`ConnectionAbortedError` (USB cable unplugged) is deliberately excluded
— that's a transient hardware event, not a stale cert.

**Do NOT auto-clear on `UserDeniedPairingError`** — that's the user
deliberately tapping "Don't Trust"; resetting that choice without
asking would be silently overriding user intent. `DeviceManager.connect()`
adds the udid to `dm.sticky_user_denied` and the watchdog refuses to
auto-connect it until the user explicitly triggers re-pair via the
in-app Re-trust button (which clears the flag).

---
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): document USB pair records under SIP workaround"
```

---

## Task 10: Manual end-to-end verification (Ravi runs)

This is the user-facing proof that the implementation works. Cannot be delegated — requires the physical iPhone.

- [ ] **Step 1: Rebuild + install**

```bash
cd /Users/ravi.wu/personal/locwarp
make build-install
```

- [ ] **Step 2: Reproduce the 2026-06-09 stale-cert state**

With a USB iPhone connected that has been paired before, and whose host pair record is intact:

```bash
make kill
# Send the DeletePairRecord plist (this is what the new code does
# AUTOMATICALLY when the recovery fires — running it here just sets up
# a guaranteed-broken state for the test).
cd backend && .venv/bin/python -c "
import asyncio
from pymobiledevice3.usbmux import PlistMuxConnection
UDID = '<your-USB-iPhone-udid>'
async def nuke():
    sock = await PlistMuxConnection.create_usbmux_socket()
    conn = PlistMuxConnection(sock)
    await conn._send({'MessageType': 'DeletePairRecord', 'PairRecordID': UDID})
    print(await conn._receive(conn._tag - 1))
    conn.close()
asyncio.run(nuke())
"
# Also clear local cache so the test is a clean stale state
rm -f ~/.pymobiledevice3/<udid>.plist
```

Now intentionally re-pair (briefly tap Trust on the iPhone) to create a fresh host pair record on the Mac. Then **immediately after**, in iPhone Settings → 一般 → 移轉或重置 iPhone → 重置 → 重置位置與隱私權, to make the iPhone forget the Mac's cert *while* the Mac still has its pair record. (The simpler way is to just leave the Mac alone for a long enough period that iOS's pair record TTL expires, but that's not reliable; the Reset Location & Privacy + freshly-re-paired sequence reliably puts you in the stale-cert state.)

- [ ] **Step 3: Plug USB, launch LocWarp, watch for auto-recovery**

```bash
make start
```

**Expected:**
- Within ~5 seconds of LocWarp launching (or USB plug-in), the iPhone shows the "Trust This Computer" prompt.
- No shell intervention required.
- After tapping Trust + entering passcode, the device row in the UI flips to green within one poll cycle.

- [ ] **Step 4: Verify the click path**

If the auto-recovery happened in the watchdog (likely), the chip never appeared. To exercise the click path:
- Repeat steps 2-3 but DON'T tap Trust when the prompt appears; dismiss it.
- Within seconds the chip "需要信任" should appear.
- Click "重新信任". A second Trust prompt fires immediately on the iPhone. Tap Trust → device goes green.

- [ ] **Step 5: Verify sticky user_denied**

- Repeat step 2 to put the device back in stale state.
- Plug USB. When the Trust prompt fires, tap **Don't Trust** on the iPhone.
- Watch the LocWarp backend log — expected: ONE failure logged, then no further `Auto-connect` attempts for that udid.
- The UI chip should stay "需要信任".
- Click the in-app "重新信任" button. A fresh Trust prompt fires. Tap Trust. Device goes green.

- [ ] **Step 6: Verify response shape**

```bash
curl -s http://127.0.0.1:8777/api/device/list | python3 -m json.tool
```
Each device entry should have `pair_status` (from the earlier feature). After a successful repair, the udid that triggered recovery should be back to `"pair_status": "ok"`.

- [ ] **Step 7: Done**

If all three flows above complete without typing any shell command, the implementation is shipped.

---

## Self-Review

**Spec coverage:**

| Spec section | Plan task |
|---|---|
| Goal 1: user clicks Re-trust once, prompt appears | Task 7 (wifi/repair recovery) + Task 10 step 4 |
| Goal 2: watchdog also recovers | Task 8 (DeviceManager.connect rewire) + Task 10 step 3 |
| Goal 3: error messages tell user what to do next | Task 6 (_humanize_pair_error) + Task 7 (handler uses it) |
| Goal 4: CLAUDE.md note | Task 9 |
| Module `usbmux_pair_records.py` | Tasks 1-5 |
| `_is_stale_cert_error` whitelist + name fallback | Task 3 |
| `_humanize_pair_error` 4 branches | Task 6 |
| Per-udid `asyncio.Lock` for serialization | Task 4 + tested in Task 5 |
| `sticky_user_denied` set, watchdog gating, wifi/repair clears | Task 8 |
| Spec tests 1-3 (delete_system) | Task 1 (4 tests; spec had 3) |
| Spec test 4 (delete_local) | Task 2 (3 tests; spec had 1) |
| Spec test 5 (`_is_stale_cert_error`) | Task 3 |
| Spec test 6 (`_humanize_pair_error` table) | Task 6 |
| Spec tests 7-10 (wifi/repair behaviors) | Task 7 |
| Spec test 11 (lock serialization) | Task 4 + Task 5 |
| Spec tests 12-14 (connect auto-recovery + sticky) | Task 8 |
| Spec tests 15-17 (manual e2e) | Task 10 |

No gaps.

**Placeholder scan:** Searched for "TBD", "TODO", "implement later", "similar to Task" — none present. Every step has runnable code or a runnable command.

**Type consistency check:**
- `pair_status` literal: `"ok" | "trust_required" | "error"` consistent with prior feature (not modified here)
- `autopair_with_recovery` signature: returns `(lockdown, stale_cleared: bool)` — used the same way in Tasks 5, 7, 8
- `sticky_user_denied`: `set[str]` typed in `DeviceManager.__init__` and treated as a set in `connect()` (`.add(udid)`), watchdog (`in dm.sticky_user_denied`), and wifi/repair (`.discard(udid)`)
- `_humanize_pair_error(exc, *, stale_cleared: bool) -> str` — called consistently in Task 7
- `_pair_locks` dict + `_pair_locks_guard` lock — internal; only `acquire_pair_lock(udid)` is public
