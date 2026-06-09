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

import asyncio
import logging
import ssl
from pathlib import Path

from pymobiledevice3.exceptions import ConnectionTerminatedError
from pymobiledevice3.lockdown import create_using_usbmux
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


async def autopair_with_recovery(udid: str, autopair: bool = True):
    """Try `create_using_usbmux(serial=udid, autopair=autopair)`. If a
    stale-cert exception fires, clear host pair records (system + local)
    once and retry. Returns `(lockdown_client, stale_cleared)`.

    Acquires the per-udid pair lock for the entire flow so concurrent
    callers (watchdog + user-triggered wifi/repair) don't double-clear.

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
