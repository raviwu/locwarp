# Auto-clear stale USB host pair record

**Date:** 2026-06-09
**Status:** Design — pending Ravi approval
**Type:** Bug fix + small backend addition. Follow-up to `2026-06-02-surface-pair-failed-devices-design.md`.

## Problem

`wifi/repair` (and the usbmux watchdog's auto-connect) calls
`create_using_usbmux(serial=udid, autopair=True)`. When the host has a
stale pair record for that udid but the iPhone has forgotten the host
certificate, `validate_pairing` fails inside `ssl_start` with
`ConnectionTerminatedError` (and friends — `SSLError`, `EOFError`,
`ConnectionResetError`, `BrokenPipeError`). pymobiledevice3's autopair
flow does **not** fall back to `_pair()` in that case, so the iPhone
"Trust This Computer" prompt never appears. The user clicks the in-app
Re-trust button and nothing happens on the iPhone — and our error
message even tells them to "tap Trust on the iPhone", which is
impossible because there's no prompt.

This was first reproduced on 2026-06-09 for udid
`00008120-0018598E1120C01E`. The only fix today is for the user to
manually clear the host pair record via raw `usbmuxd` plist message
(`/var/db/lockdown/` is SIP-protected on macOS 11+, so `sudo rm` fails
with "Operation not permitted"; `~/.pymobiledevice3/<udid>.plist` only
covers iOS 17+ RemotePairing, not the legacy USB lockdown record).

Six concrete defects motivate this design:

| # | Defect | Evidence |
|---|---|---|
| 1 | `wifi/repair` does not auto-recover from stale host cert | iPhone never showed Trust prompt during 2026-06-09 e2e |
| 2 | `/var/db/lockdown/` SIP-protected, `sudo rm` fails | `Operation not permitted` even as root |
| 3 | `pymobiledevice3` lacks a high-level wrapper for `DeletePairRecord` | The plist message exists in usbmuxd protocol but isn't exposed |
| 4 | `trust_failed` error message misleads — tells user to tap Trust when there's no prompt | `backend/api/device.py:187` |
| 5 | `CLAUDE.md` does not document the SIP constraint + workaround | Re-debug cost on next regression |
| 6 | iOS 17+ RemotePairing already has a "delete stale → retry" pattern (`api/device.py:205-217`), but USB lockdown has none | Asymmetric code path |

## Goals

1. User clicks the Re-trust button once and the iPhone shows the Trust prompt — without any shell command.
2. The usbmux watchdog's auto-connect path also recovers from stale host cert (a plugged USB cable is sufficient user intent — no extra click required).
3. Error messages tell the user what to do *next* given the actual failure, not a generic "tap Trust" that may not be possible.
4. Future maintainers can find the SIP / usbmuxd workaround in `CLAUDE.md` before they re-debug the same issue.

## Non-goals (deferred)

- Unifying `_classify_pair_error` (in `device_manager.py`) with
  `_classify_repair_error` (in `api/device.py`) — pure refactor,
  orthogonal to this fix.
- Adding a separate `/api/device/{udid}/reset-pair` endpoint — YAGNI;
  the auto-recovery inside `wifi/repair` covers the use case.
- A guided UI in the frontend for the "Reset Location & Privacy" path
  — the improved error message tells the user what to do; an in-app
  wizard is out of scope.

## Architecture

### New module: `backend/services/usbmux_pair_records.py`

Two small functions; no class. This file isolates the
`pymobiledevice3.usbmux.PlistMuxConnection` private-API trick so the
rest of the codebase can ignore the SIP / raw-plist details.

```python
async def delete_system_pair_record(udid: str) -> bool:
    """Ask usbmuxd to delete /var/db/lockdown/<udid>.plist via the
    DeletePairRecord plist message.

    /var/db/lockdown/ is SIP-protected on macOS 11+ — even `sudo rm`
    fails with "Operation not permitted". usbmuxd is SIP-exempt
    (system daemon, owns the directory) and exposes a DeletePairRecord
    plist message that does the deletion for us. pymobiledevice3 does
    not wrap this in a high-level API, so we send the raw plist.

    Returns True on success or already-absent (Number==0 or Number==2).
    Returns False on unexpected usbmuxd error. Never raises.
    """

def delete_local_pair_record(udid: str) -> bool:
    """Delete ~/.pymobiledevice3/<udid>.plist if present. Idempotent.

    Covers the iOS 17+ RemotePairing local cache. Returns True on
    success or already-absent. Never raises."""
```

Both functions are **never-raise** so callers can chain them
defensively in any error path.

### `wifi/repair` flow change

Replace the existing "Step 1: USB lockdown autopair" try/except in
`backend/api/device.py:179-191` with an auto-recover variant:

```python
udid_lock = await _acquire_pair_lock(udid)
async with udid_lock:
    stale_cleared = False
    try:
        lockdown = await create_using_usbmux(serial=udid, autopair=True)
    except Exception as exc:
        if _is_stale_cert_error(exc):
            _tunnel_logger.info(
                "Repair: clearing stale host pair records for %s", udid,
            )
            await delete_system_pair_record(udid)
            delete_local_pair_record(udid)
            stale_cleared = True
            try:
                lockdown = await create_using_usbmux(serial=udid, autopair=True)
            except Exception as retry_exc:
                raise HTTPException(
                    500,
                    detail={
                        "code": "trust_prompt_unavailable",
                        "message": _humanize_pair_error(retry_exc, stale_cleared=True),
                        "udid": udid,
                        "stale_cleared": True,
                    },
                )
        else:
            raise HTTPException(
                500,
                detail={
                    "code": "trust_failed",
                    "message": _humanize_pair_error(exc, stale_cleared=False),
                    "udid": udid,
                    "stale_cleared": False,
                },
            )
```

The rest of `wifi/repair` (the iOS 17+ RemotePairing handshake via
helper) is unchanged. The response on success grows a `stale_cleared`
field so logs and future telemetry can tell whether auto-recovery
fired this run.

### `connect()` watchdog change

`backend/core/device_manager.py` `DeviceManager.connect()` (called by
`_usbmux_presence_watchdog` in `main.py`) gets the same auto-recover
pattern, but **gated** to avoid runaway behavior:

1. The first `create_using_usbmux(autopair=True)` failure with a
   stale-cert exception triggers exactly one cleanup + retry.
2. Cleanup uses the same `delete_system_pair_record` +
   `delete_local_pair_record` helpers.
3. If retry also fails: bubble the exception up. The watchdog's
   existing `fail_count` / cooldown logic already throttles repeat
   attempts.
4. `UserDeniedPairingError` is **never** treated as stale-cert (we
   would never reset the user's deliberate "Don't Trust" choice). The
   watchdog marks this udid as `sticky_user_denied` and stops
   auto-connecting it until the user explicitly clicks Re-trust.
   `wifi/repair` (user intent) clears that flag and retries.

### Race control

`wifi/repair` and the watchdog can both call `connect()` /
`create_using_usbmux` for the same udid at the same time. Without
coordination, both could simultaneously delete the host pair record,
both call autopair, and the iPhone could receive two simultaneous
trust prompts (or one of them races and overwrites the other's
freshly-written pair record).

Solution: a per-udid `asyncio.Lock` registry in the new module:

```python
_pair_locks: dict[str, asyncio.Lock] = {}
_pair_locks_guard = asyncio.Lock()

async def acquire_pair_lock(udid: str) -> asyncio.Lock:
    async with _pair_locks_guard:
        lock = _pair_locks.get(udid)
        if lock is None:
            lock = asyncio.Lock()
            _pair_locks[udid] = lock
        return lock
```

Both `wifi/repair` and the watchdog's `connect()` acquire the lock
before the autopair attempt and release it after. Held for the full
autopair + (maybe) cleanup + retry sequence, so the second caller
waits for the first to finish before deciding whether to retry.

### Error classification

`_is_stale_cert_error(exc)` — isinstance check against the type whitelist:

```python
_STALE_CERT_TYPES = (
    ConnectionResetError,
    BrokenPipeError,
    EOFError,
    ssl.SSLError,            # covers SSLEOFError, SSLZeroReturnError, etc.
    ConnectionTerminatedError,  # pymobiledevice3.exceptions
)
```

Plus a name-based fallback (mirroring `_classify_pair_error`'s
defensive pattern) so a re-wrapped exception still classifies
correctly:

```python
def _is_stale_cert_error(exc: BaseException) -> bool:
    if isinstance(exc, _STALE_CERT_TYPES):
        return True
    name = type(exc).__name__
    return any(s in name for s in ("ConnectionTerminated", "SSLError", "SSLEOFError"))
```

`ConnectionAbortedError` (OSError subclass, ECONNABORTED) is
**deliberately excluded** — that's typically "USB cable unplugged
mid-handshake", which is not a stale cert and should not trigger pair
record deletion. Better to bubble that up so the watchdog can wait
for the next plug-in.

### Error humanization

`_humanize_pair_error(exc, stale_cleared: bool) -> str` — four
branches:

| Condition | Message (zh-tw) |
|---|---|
| `PairingDialogResponsePendingError` | 「請在 iPhone 解鎖畫面上按「信任」」 |
| `UserDeniedPairingError` | 「之前在 iPhone 上點了『不信任』。請到 iPhone Settings → 一般 → 移轉或重置 iPhone → 重置 → 重置位置與隱私權，然後重插 USB」 |
| `stale_cleared=True` (any other exception type after retry) | 「已重置配對紀錄但 iPhone 仍未跳信任提示。請確認 iPhone 已解鎖、USB 線可傳輸資料；如仍不出現請走 Reset Location & Privacy」 |
| `stale_cleared=False`, anything else | 「USB 配對失敗：{exc}」 |

## Frontend changes

**None.** The frontend already calls `/api/device/wifi/repair` with
a `udid` body and surfaces the response message in the existing
confirm modal's failed state. The auto-retry and richer messages are
transparent to the UI.

## Documentation

Add a new section to the project root `CLAUDE.md` (after the existing
"Bookmark / Route store: CRDT merge semantics" section):

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

`wifi/repair` and the usbmux watchdog's `connect()` both call these
helpers on `ConnectionTerminatedError` / `SSLError` / `EOFError` /
`ConnectionResetError` / `BrokenPipeError` ("stale host cert"
signals) to clear host-side state and let the next autopair attempt
fall through to `_pair()` — which triggers the iPhone's "Trust This
Computer" prompt.

**Do NOT auto-clear on `UserDeniedPairingError`** — that's the user
deliberately tapping "Don't Trust"; resetting that choice without
asking would be silently overriding user intent. The watchdog marks
the udid as `sticky_user_denied` and stops auto-connecting it until
the user explicitly triggers re-pair via the Re-trust UI button.
```

## Test plan

**Backend (pytest)**

1. `test_delete_system_pair_record_sends_correct_plist` — mock
   `PlistMuxConnection`; assert the sent plist is
   `{"MessageType": "DeletePairRecord", "PairRecordID": udid}`.
2. `test_delete_system_pair_record_idempotent_on_missing` — mock
   usbmuxd returning `{"Number": 2}` (no such record); assert function
   still returns True (idempotent for the "already gone" case).
3. `test_delete_system_pair_record_returns_false_on_error` — mock
   usbmuxd returning `{"Number": 5}` (unknown error); assert False;
   function does not raise.
4. `test_delete_local_pair_record_handles_missing_file` — call against
   a tmp dir without the udid file; assert True (idempotent).
5. `test_is_stale_cert_error_table` — table-driven: each exception
   type/name in the whitelist returns True;
   `ConnectionAbortedError`, `PairingDialogResponsePendingError`,
   `RuntimeError("foo")` return False.
6. `test_humanize_pair_error_table` — table-driven: each exception
   type maps to the spec'd message string (zh-tw substring match).
7. `test_wifi_repair_clears_stale_cert_and_retries` — first
   `create_using_usbmux` raises `ConnectionTerminatedError`; second
   succeeds; assert 200 response with `stale_cleared=True`, assert
   `delete_system_pair_record` was called exactly once.
8. `test_wifi_repair_does_not_clear_on_pairing_pending` — exception
   is `PairingDialogResponsePendingError`; assert `delete_system_pair_record`
   was NOT called; assert 500 response with `trust_failed` code.
9. `test_wifi_repair_user_denied_message_mentions_reset` — exception
   is `UserDeniedPairingError`; assert response message contains
   "Reset" or "重置位置與隱私權".
10. `test_wifi_repair_retry_failure_uses_richer_message` — both
    attempts fail; assert response uses `trust_prompt_unavailable`
    code with the `stale_cleared=True` branch of `_humanize_pair_error`.
11. `test_pair_lock_serializes_concurrent_repair_calls` — two
    coroutines call the wrapped autopair concurrently for the same
    udid; assert the second waits for the first to complete (use an
    `asyncio.Event` in the mock).
12. `test_connect_watchdog_auto_clears_stale_cert` — `DeviceManager.connect()`
    sees `ConnectionTerminatedError`; assert it clears + retries
    (same shape as wifi/repair test).
13. `test_connect_watchdog_marks_user_denied_sticky` — `connect()`
    sees `UserDeniedPairingError`; assert the udid is added to the
    sticky set; assert a subsequent `connect()` for the same udid
    bails out before calling `create_using_usbmux`.
14. `test_wifi_repair_clears_sticky_user_denied_flag` — udid is in
    sticky set; user calls `/wifi/repair`; assert the flag is
    cleared before autopair retries.

**Manual end-to-end (Ravi runs)**

15. Reproduce the 2026-06-09 scenario:
    - `sudo` Cannot delete `/var/db/lockdown/<udid>.plist` (SIP).
    - `~/.pymobiledevice3/` is empty.
    - iPhone has forgotten the Mac's cert.
    - Plug USB → open LocWarp → see "需要信任" chip → click "重新信任" → confirm.
    - **Expected:** iPhone Trust prompt within ~3 seconds; tap Trust → device goes green within one poll cycle.
    - **No shell commands.**

16. Variant: don't click anything in the UI — just plug the cable and
    wait. Watchdog auto-connect should trigger the same recovery and
    iPhone should prompt within ~5 seconds of plug-in.

17. Variant: tap "Don't Trust" on the iPhone the first time.
    - Watchdog should stop retrying after one failure (sticky flag).
    - UI chip stays "需要信任".
    - Clicking "重新信任" should clear the sticky flag and re-trigger
      the iPhone prompt.

## Risks

- **`PlistMuxConnection` is using a leading-underscore method (`_send`/`_receive`/`_tag`)** — this is private API; pymobiledevice3 could change it across versions. Mitigation: pin the relevant code path in `usbmux_pair_records.py` to a small set of lines that's easy to audit on upgrade. Add a smoke test in the suite that calls the wrapper end-to-end with a mocked socket so a renamed private method breaks loudly.
- **Race against iCloud sync / external tools** — Xcode and libimobiledevice could write a new pair record between our delete and our retry. Acceptable: the retry will then succeed with that new record (fine) or fail with `ConnectionTerminatedError` again (we'd loop, but the per-udid lock prevents storms; watchdog's existing `fail_count` cooldown caps the impact).
- **A user with a flaky USB cable could see repeated auto-clears** — every plug-in cycle would trigger a "stale cert" classification (because `validate_pairing` times out before completing) and re-auto-pair. This is annoying but not data-destructive; the iPhone will simply show the Trust prompt each time. Mitigation: monitor logs; if observed, add a "cleared X times in past minute" backoff. YAGNI for v1.
- **`pair_locks` dict grows unbounded over many udids** — each udid plugged in over the process lifetime adds one entry. At ~3 keys for typical multi-iPhone use, this is fine. Process restart clears it.

## Out-of-scope follow-ups

- Unify the two classifier functions (`_classify_pair_error`,
  `_classify_repair_error`, `_humanize_pair_error`) into a single
  module.
- Add structured event (`pair_recovery_attempted`, success/failure
  counters) for future telemetry — not needed for the user fix.
- iOS-side "Reset Location & Privacy" guided wizard in the frontend.
