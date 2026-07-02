# USB Transport Auto-Promotion — Design

**Date:** 2026-07-02
**Status:** Approved
**Author:** Ravi + Claude

## Problem

User report: "when I connect the USB, the panel still shows WiFi connected."
Expectation: plugging in USB should mean LocWarp no longer needs the WiFi
tunnel.

## Root cause

Traced via `~/.locwarp/logs/backend.log` (2026-07-02 boot) plus a full read of
`DeviceManager.connect()`/`_connect_locked()`:

1. At boot, this iPhone connects via **Network** (11:20:42.718,
   `Connecting to 00008140-... via Network`) — most likely usbmuxd's native
   "Wi-Fi Sync" entry, seen before/independent of the USB cable's own
   enumeration. `_connect_locked` (`device_manager.py:500-513`) already
   prefers USB "if device shows up as both" at connect time, but at that
   instant only a Network entry was visible to it.
2. `DeviceManager.connect()` (`device_manager.py:493-495`) is unconditional
   once connected:
   ```python
   if udid in self._connections:
       logger.info("Device %s is already connected", udid)
       return
   ```
   No transport comparison. Once connected via *any* transport, every later
   `connect()` call for that UDID is a no-op — there is currently no code
   path anywhere that re-asserts "prefer USB" after the fact.
3. The usbmux watchdog (`main.py`) correctly sees the device present via USB
   every poll (`present_usb_original`), but this morning's busy-loop fix
   (`compute_usb_reconnect_targets`, commit `e46ee42`) dedups its "new
   device" list against **all** `dm._connections.keys()`, any transport — so
   an already-Network-connected UDID is filtered out before `connect()` is
   ever called, silently. (This is not a regression: before that fix, the
   watchdog would still have called `connect()` every ~1.3s for this UDID,
   but `connect()`'s unconditional no-op guard, unchanged and pre-existing,
   swallowed it just the same. Transport was already stuck; today's fix only
   removed the last visible log signal that no promotion path exists.)

Net effect: nothing in the codebase ever revisits transport choice for an
already-connected device. The user's expectation matches the app's own
stated intent (`_connect_locked`'s "Prefer USB if device shows up as both"
comment) — it just isn't re-evaluated after first connect.

## Fix: watchdog-driven Network→USB promotion

### New pure helper — `backend/services/device_presence.py`

Add alongside the existing `compute_usb_reconnect_targets` (same module,
stdlib-only):

```python
from collections.abc import Iterable, Mapping


def compute_usb_promotion_targets(
    connections: Mapping[str, str],
    present_usb_serials: Iterable[str],
) -> list[str]:
    """UDIDs connected via a non-USB transport that are now present on USB.

    ``connections`` maps udid (in the exact casing DeviceManager stores it
    under in ``_connections`` — the caller must use that same casing for its
    disconnect()/connect() calls) to its current connection_type. A udid
    already on USB is never a promotion target — nothing to promote.
    Comparison against ``present_usb_serials`` is case-insensitive, matching
    ``compute_usb_reconnect_targets``. No ``max_devices`` cap: promotion
    swaps one already-counted connection's transport, it never changes the
    connected-device count.
    """
    present_lc = {s.lower() for s in present_usb_serials}
    return sorted(
        udid for udid, conn_type in connections.items()
        if conn_type != "USB" and udid.lower() in present_lc
    )
```

### Watchdog wiring — `backend/main.py`

**Structural gotcha to get right:** the existing appearance block early-exits
the whole watchdog tick when there's nothing new to connect:

```python
new_udids = compute_usb_reconnect_targets(...)
if not new_udids:
    continue          # <-- skips the REST of this tick, every tick, when
                       #     new_udids is empty (the common case)
```

A promotion block placed *after* this `continue` would never run except on a
tick that also happens to have a genuinely new device. `promotable` must be
computed **before** that early-exit, and the exit condition widened:

```python
MAX_DEVICES = 3
from services.device_presence import (
    compute_usb_promotion_targets,
    compute_usb_reconnect_targets,
)
new_udids = compute_usb_reconnect_targets(
    connected_udids=dm._connections.keys(),
    present_usb_serials=present_usb_original.values(),
    max_devices=MAX_DEVICES,
)
promotable = compute_usb_promotion_targets(
    connections={u: c.connection_type for u, c in dm._connections.items()},
    present_usb_serials=present_usb_original.values(),
)
if not new_udids and not promotable:
    continue

# (unchanged) stale-backoff-reset block, then `now = time.monotonic()`,
# then the existing `for udid in new_udids:` loop, unchanged.

# NEW: promotion loop, placed after the existing new_udids loop, same tick.
for udid in promotable:
    fail_count = reconnect_failure_count.get(udid, 0)
    cooldown = min(
        reconnect_cooldown_base * (2 ** fail_count),
        reconnect_cooldown_max,
    )
    last = last_reconnect_attempt.get(udid, 0.0)
    if now - last < cooldown:
        continue
    last_reconnect_attempt[udid] = now
    logger.info(
        "usbmux watchdog: promoting %s from Network to USB (fail_count=%d, cooldown=%.0fs)",
        udid, fail_count, cooldown,
    )
    try:
        await dm.disconnect(udid)
        await dm.connect(udid)
        try:
            devs = await dm.discover_devices()
            info = next((d for d in devs if d.udid == udid), None)
            await broadcast("device_connected", {
                "udid": udid,
                "name": info.name if info else "",
                "ios_version": info.ios_version if info else "",
                "connection_type": info.connection_type if info else "USB",
            })
        except Exception:
            logger.exception("watchdog: broadcast (promoted) failed")
        logger.info("Promotion to USB succeeded for %s", udid)
        reconnect_failure_count.pop(udid, None)
    except Exception:
        reconnect_failure_count[udid] = fail_count + 1
        next_cooldown = min(
            reconnect_cooldown_base * (2 ** (fail_count + 1)),
            reconnect_cooldown_max,
        )
        logger.warning(
            "Promotion to USB for %s failed (attempt %d, will retry in %.0fs)",
            udid, fail_count + 1, next_cooldown,
            exc_info=fail_count < 3,
        )
```

**Deliberately reuses**, shared with the existing new-device loop: the
`reconnect_failure_count` / `last_reconnect_attempt` cooldown maps (so a
flaky USB enumeration doesn't hammer disconnect/reconnect cycles), and the
`device_connected` WS broadcast (the frontend already re-renders
`connection_type` from this event — no frontend changes needed).

**Deliberately skipped**, vs. the new-device loop:
- `sticky_user_denied` check — a currently-connected device already passed
  pairing; this set can't contain it.
- `MAX_DEVICES` cap — promotion doesn't add a connection, it swaps one
  already-counted entry's transport.
- `_auto_sync_new_device_to_primary(udid)` — that call is for a device
  *newly joining* group mode (teleport it to match the primary / replay the
  primary's current action). The promoted device was already in sync; that
  call is not needed and, per the "replay the action" branch, risks
  restarting the promoted device's own in-progress route from scratch.

**No changes to `device_manager.py`.** `connect()`'s "prefer USB if shown as
both" logic already does the right thing once a fresh `connect()` is forced;
this fix doesn't touch `connect()`'s semantics or the connect-latch
machinery the sibling USB-reconnect plan (`c00b6b6`) just hardened.

## Superseded: the original lazy-self-heal reasoning below

**Status update (post-implementation):** the final whole-branch review found
that the lazy-self-heal reasoning originally written here does not hold for
a route actively running *during* the promotion — the multi-second window
where `_connections[udid]` is empty (between `disconnect()` and `connect()`
completing autopair + tunnel + RSD) has no wait/retry on the reader side, so
a route push landing in that window raised `DeviceLostError` immediately and
aborted the route. The shipped implementation replaces the lazy self-heal
below with a **proactive park-then-resume** sequence, mirroring the existing
WiFi-tunnel-restart watchdog pattern (`services/wifi_tunnel_service.py`) and
the reference success path (`infra/device/tunnel_restart.py`):

1. Before tearing anything down: capture `old_eng.capture_resumable_snapshot()`
   and park the engine (`state = DISCONNECTED`, `_stop_event.set()`,
   `_pause_event.set()`, cancel `_active_task`) so its task cannot attempt a
   push during the empty-connection window.
2. Tear down the WiFi tunnel explicitly via `api.device._tear_down_tunnel`
   (see "Fixed: WiFi tunnel leak" below) *before* `dm.disconnect()`.
3. `dm.disconnect(udid)` then `dm.connect(udid)`, as originally designed.
4. Rebuild the engine with `create_engine_for_device(udid, force=True)` —
   the old engine's cached `location_service` pointed at the now-closed
   connection, so (unlike the original reasoning) it **is** recreated here,
   matching `attempt_tunnel_restart`'s reference behavior.
5. If a snapshot was captured, `resume_from_snapshot` on the new engine.

**Known residual characteristic** (accepted, not fixed): a device that is
*idle* (teleported to a position but not running a dynamic route/loop, so
`capture_resumable_snapshot()` returns `None`) loses `current_position` on
promotion, since step 4 unconditionally rebuilds the engine. This is
identical to the pre-existing `attempt_tunnel_restart` reference path's
behavior (also unconditional `force=True`), not a new gap this feature
introduces — a subsequent navigate/loop after an idle promotion would need
the user to re-teleport first, same as any other reconnect scenario.

## Fixed: WiFi tunnel leak

`DeviceManager.disconnect()` → `_teardown_connection()` explicitly skips
closing WiFi tunnels (only USB helper tunnels) — so a live `TunnelRunner` +
its per-tunnel watchdog task, registered for a saved-IP auto-connected
device, would leak on every promotion. An orphaned watchdog could later
"recover" the dead tunnel and silently demote the device back to WiFi.
Fixed by calling `api.device._tear_down_tunnel(udid, caller=...)` — which
cancels the watchdog and stops the runner, popping both from the shared
`_tunnels`/`_tunnel_watchdogs` registry — before `dm.disconnect()`. It's an
idempotent no-op for a device that was never registered there (e.g. a
native usbmuxd "WiFi Sync" connection that never went through LocWarp's own
`connect_wifi_tunnel` flow).

### Original reasoning (superseded, kept for history)

`DeviceManager.disconnect()` → `_teardown_connection()` calls
`conn.location_service.clear()`, which restores real GPS on the device
before the connection is torn down. This means a promotion briefly reverts
the phone's Find My / Maps position to its real location.

The original design argued this self-heals rather than abandoning the
simulation because the `SimulationEngine` object is never recreated and its
next scheduled position push discovers the dead DVT session and self-heals
via `get_fresh_dvt_provider`. That reasoning holds for a *degraded* session
(DVT dead but the connection object still exists) but not for a fully
*absent* connection (`conn is None`, which `get_fresh_dvt_provider` treats
as an immediate, non-retryable `DeviceLostError`) — exactly the case a
voluntary disconnect+reconnect creates. See "Superseded" above for the
mechanism that actually shipped.

## Testing

**New pure-function tests** — extend `backend/tests/test_device_presence.py`
with `compute_usb_promotion_targets` cases, mirroring the existing style:
- connected via `"Network"` and present on USB → promoted.
- connected via `"USB"` and present on USB → NOT promoted (nothing to do).
- connected via `"Network"` but absent from `present_usb_serials` → NOT
  promoted (nothing to promote to).
- case-insensitive match (connections key uppercase, present serial
  lowercase, or vice versa) → still promoted.
- not connected at all → NOT promoted (that's `compute_usb_reconnect_targets`'s
  job, not this function's — mutually exclusive by construction, no udid can
  satisfy both functions' inputs at once).

**No new `main.py`-level test.** Consistent with how the watchdog's existing
appearance/disappearance logic is scoped (see this morning's Task 1): the
loop stays an untested thin wrapper over the tested pure helper. File
logging and the live watchdog loop are exercised only by the manual runtime
smoke step below.

**Runtime smoke (manual, requires physical device):** with the iPhone
already connected via Network (WiFi Sync or a saved-IP auto-connect), plug
in the USB cable and confirm within a few seconds: (a) the backend log shows
`"promoting <udid> from Network to USB"` then `"Promotion to USB succeeded"`,
(b) the frontend DeviceChip panel updates its connection badge to USB, (c)
if a route/multi-stop was running at the moment of promotion, it resumes
(rather than aborting) after the brief flicker.

## Constraints

- Backend suite green after the commit; import-linter `services/` ring
  contract (`device_presence.py` stays stdlib-only) unaffected —
  `7 kept, 0 broken`.
- No frontend changes — `device_connected` is an existing WS event the
  DeviceChip UI already renders `connection_type` from.
- No new settings/toggle — always-on, matching the user's directly stated
  expectation. (If a future need arises to keep a device on WiFi despite
  USB being present — e.g. charge-only cable scenarios don't need this,
  since a charge-only cable never shows up in usbmuxd's device list at all
  — a toggle can be added then.)
- Single task, single commit; no changes to `device_manager.py` or any
  frontend file.

## Execution

One task, direct commit to `main` (personal repo — no branch/PR ceremony):
add `compute_usb_promotion_targets` + its tests (TDD), wire the two-line
early-exit widening + the new promotion loop into `main.py`'s existing
`_usbmux_presence_watchdog`. Subagent-Driven Development, matching this
morning's Log-Sweep Follow-ups cluster.
