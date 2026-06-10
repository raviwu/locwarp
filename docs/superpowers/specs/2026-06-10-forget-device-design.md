# Forget this device

**Date:** 2026-06-10
**Status:** Design — approved by Ravi (in-session)
**Type:** Small feature + one bug fix rider. Follow-up to
`2026-06-09-auto-clear-stale-pair-record-design.md`.

## Problem

LocWarp has no way to remove a device pairing from the UI. The existing
"中斷此裝置 / Disconnect this device" chip-menu action calls
`DELETE /api/device/{udid}/connect`, which is session-only teardown —
by design, the usbmux watchdog auto-reconnects within ~1 second, so to
the user the action appears to do nothing. Resetting pairing state
(the 2026-06-10 e2e prep scenario) currently requires shell commands
against usbmuxd.

### Bug discovered during design (must fix, not polish)

`discover_devices()` calls `create_using_usbmux(serial=...)` with
pymobiledevice3's default `autopair=True`. The frontend polls
`/api/device/list` every few seconds, so **every poll re-triggers the
iOS Trust dialog for any unpaired device**. This silently defeats the
`sticky_user_denied` feature shipped on 2026-06-09: sticky gates the
watchdog's `connect()`, but not the discovery poll's autopair side
effect. e2e Variant C (tap "Don't Trust" → expect no more prompts)
would fail — the prompt would keep re-appearing from the poll loop.

Fix: pass `autopair=False` in `discover_devices()`. Consequences:

- Unpaired device → fast `NotPairedError` (empty message) → existing
  name-based classifier branch → `trust_required` chip, same as today.
- Stale-cert device → `ConnectionTerminatedError` propagates from
  `validate_pairing` before the autopair decision — identical
  classification either way.
- First-plug pairing UX unchanged: the watchdog's `connect()` (via
  `autopair_with_recovery`) still pops the Trust prompt within ~1-2 s
  of plug-in for non-sticky devices.
- Discovery gets faster (never blocks waiting on a pair dialog).

## Survey conclusion (per CLAUDE.md API-surface rule)

14 existing `/api/device/*` endpoints enumerated; git history has no
prior forget/unpair endpoint.

- `DELETE /{udid}/connect` — session disconnect only; watchdog
  reconnects by design. Overloading it with `?forget=true` would make
  one endpoint half-destructive; rejected.
- `POST /wifi/repair` — the inverse operation (re-pair); rejected.

**Adding a new endpoint `POST /api/device/{udid}/forget`** because no
existing endpoint covers "remove pairing state + suppress re-pair".
Action-verb POST matches house style (`amfi/reveal-developer-mode`,
`wifi/repair`).

## Goals

1. One UI action removes the pairing: iPhone-side unpair (best-effort),
   session teardown, host pair records cleared, watchdog suppressed.
2. Forgotten state survives a LocWarp restart.
3. The `sticky_user_denied` feature actually works: after "Don't Trust"
   or Forget, no Trust prompts re-appear from any code path while the
   device stays plugged in.
4. Recovery is the existing Re-trust button — no new recovery UI.

## Non-goals (deferred)

- Forget action on non-connected rows in the DeviceStatus dropdown
  (trust_required devices). v1 surfaces Forget only on connected-device
  chips; a broken-pair device can be unplugged instead.
- iPhone-side "Reset Location & Privacy" guided wizard.
- Undo for forget.

## Architecture

### Endpoint: `POST /api/device/{udid}/forget`

Placed with the other generic `/{udid}/*` routes (after all `/wifi/*`
routes). The whole flow holds `acquire_pair_lock(udid)` so it
serializes against the watchdog's `autopair_with_recovery` and
`wifi/repair`.

Five steps, in order:

1. **iPhone-side unpair (best-effort).** If the device is connected,
   call `await lockdown.unpair()` on the existing session
   (`conn.usbmux_lockdown or conn.lockdown` — same fallback chain as
   the AMFI endpoint; `LockdownClient.unpair(host_id=None)` unpairs
   the current host). Wrapped in try/except: failure logs at debug and
   continues — host-side cleanup below is sufficient for LocWarp's own
   behavior.
2. **Session teardown.** If a WiFi tunnel is registered for this udid,
   reuse `_tear_down_tunnel` + `_cleanup_wifi_connection_for` (already
   in `api/device.py`). For USB connections, stop the simulation
   engine and call `dm.disconnect(udid)` + drop the engine — the same
   teardown sequence as `disconnect_device`.
3. **Clear host records.** `await delete_system_pair_record(udid)` and
   `delete_local_pair_record(udid)` (both idempotent, never raise).
4. **Suppress re-pair.** `dm.sticky_user_denied.add(udid)`. The
   watchdog skips sticky udids; the Re-trust button (and `wifi/repair`)
   clears the flag — that is the user's path back.
5. **Notify.** Broadcast `device_disconnected` with
   `reason: "forgotten"`. Return
   `{"status": "forgotten", "udid": ..., "system_cleared": bool,
   "local_cleared": bool}`.

Forget is **idempotent**: calling it for an unknown or already-forgotten
udid still returns 200 (steps 1-2 no-op, step 3 helpers are idempotent,
step 4 set-add is idempotent).

### Sticky persistence

`sticky_user_denied` is currently in-memory; a LocWarp restart would
resurrect the watchdog's re-pair prompts for forgotten devices. Persist
the set to `STICKY_DENIED_FILE = DATA_DIR / "sticky_denied.json"`
(new constant in `config.py`, same pattern as `DEVICE_NAMES_FILE`):

- `DeviceManager.__init__` loads the file via `safe_load_json` (list of
  udid strings; tolerate missing/corrupt file → empty set).
- A `_persist_sticky()` helper writes via `safe_write_json` after every
  mutation. Mutations happen in three places: `connect()` (add on
  UserDenied), `wifi/repair` (discard), and the new forget endpoint
  (add). Wrap mutation+persist in small `DeviceManager` methods —
  `mark_user_denied(udid)` / `clear_user_denied(udid)` — so callers
  can't forget to persist. Direct set reads (`in` checks) stay as-is.

Side effect (accepted): a "Don't Trust" tap now also survives restarts.
That is more correct, not less — the user's choice should not be
forgotten because the app restarted.

### Discovery fix

`discover_devices()` changes one call:
`create_using_usbmux(serial=raw.serial, autopair=False)`. A test pins
the kwarg so a future refactor can't silently regress it.

## Frontend

- `DeviceChip.tsx`: new `onForget` prop; menu item
  `t('device.chip_forget')` ("忘記此裝置" / "Forget this device")
  appended after the existing disconnect item. Follows the existing
  `onDisconnect` prop chain up to the parent that wires chips.
- Clicking opens a confirm modal (destructive action) styled after the
  existing repair-confirm modal: title, body explaining that pairing
  records will be removed and the iPhone will need to be re-trusted,
  cancel + confirm buttons. On confirm: `POST /{udid}/forget` via a new
  `forgetDevice(udid)` helper in `services/api.ts`, then refresh the
  device list.
- Post-forget UI state needs no new code: the chip disappears
  (disconnected), and the dropdown row shows the existing
  "需要信任" chip + "重新信任" button (discovery's `NotPairedError`
  routes through the existing classifier).
- i18n keys: `device.chip_forget`, `device.forget_confirm_title`,
  `device.forget_confirm_body`, `device.forget_ok`,
  `device.forget_cancel` (zh + en).

## Test plan

**Backend (pytest)**

1. `test_forget_full_flow` — connected USB device: unpair called on the
   session lockdown, engine dropped, `dm.disconnect` called, both
   delete helpers called, udid in `sticky_user_denied`, broadcast
   fired, 200 with `status=forgotten`.
2. `test_forget_idempotent_for_unknown_udid` — udid not connected, no
   records: still 200, sticky contains udid.
3. `test_forget_tears_down_wifi_tunnel` — udid has a registered
   TunnelRunner: tunnel torn down via the per-udid teardown path.
4. `test_forget_unpair_failure_does_not_block` — `lockdown.unpair`
   raises: flow continues, 200, records still cleared.
5. `test_discover_passes_autopair_false` — capture kwargs of
   `create_using_usbmux` from `discover_devices`; assert
   `autopair is False`.
6. `test_sticky_persists_across_manager_instances` — `mark_user_denied`
   writes the file; a freshly constructed `DeviceManager` loads it;
   `clear_user_denied` updates the file.
7. `test_sticky_load_tolerates_missing_or_corrupt_file` — no file /
   garbage JSON → empty set, no raise.
8. `test_wifi_repair_clear_persists` — repair's discard goes through
   `clear_user_denied` and updates the file.

**Frontend**

9. `npx tsc --noEmit` clean. (No frontend test infra in this repo.)

**Manual e2e (Ravi — merges with the pending stale-cert Task 10)**

10. Connected device → chip menu → 忘記此裝置 → confirm. Expect:
    chip disappears; no Trust prompt re-appears while plugged
    (sticky + discovery autopair=False); dropdown row shows 需要信任 +
    重新信任; `~/.locwarp/sticky_denied.json` contains the udid.
11. Restart LocWarp with the cable still plugged. Expect: still no
    Trust prompt (persistence); row still shows 需要信任.
12. Click 重新信任 → confirm → Trust prompt appears on iPhone → tap
    Trust → device reconnects, chip returns, sticky file no longer
    contains the udid.
13. (Variant C from the previous feature, now actually verifiable)
    Re-forget, replug, tap "Don't Trust" when re-pairing — watchdog
    logs one failure then goes quiet; no prompt loop from discovery.

## Risks

- **`lockdown.unpair()` on an iOS 17 RSD session** — unpair is a
  lockdown-domain request; the RSD lockdown may not accept it. The
  `usbmux_lockdown or lockdown` fallback covers the common case, and
  the call is best-effort — a failure leaves the iPhone remembering a
  host whose records we deleted, which is exactly today's status quo.
- **Sticky persistence file as a new shared state** — three writers
  (connect, repair, forget) all funnel through two `DeviceManager`
  methods, single asyncio thread, so no write races. File corruption
  degrades to empty set (fail-open: watchdog resumes auto-pair, which
  is annoying but never data-destructive).
- **`autopair=False` behavior drift across pymobiledevice3 upgrades** —
  pinned by test 5.

## CLAUDE.md update

Extend the existing "USB pair records under SIP" section with two
lines: the forget endpoint as the user-facing entry point, and
`sticky_denied.json` as the persistence file for `sticky_user_denied`.
