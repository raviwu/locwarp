# Surface pair-failed USB devices in the device list

**Date:** 2026-06-02
**Status:** Design — pending Ravi approval
**Type:** Bug fix + small contract extension

## Problem

`backend/core/device_manager.py:248-275` runs `create_using_usbmux(serial=raw.serial)` for every device usbmuxd lists. When that call raises (e.g. `ConnectionTerminatedError` during pair validation because the iPhone has forgotten the host or the on-disk pair record is stale), the per-device `try/except` catches the exception, logs it, and **omits the device from the returned list**.

A USB-attached iPhone that fails pair validation therefore disappears from `/api/device/list`. The frontend has no record it exists, so the UI says "no USB device detected". The user cannot tell whether the cable is dead, usbmuxd is dead, or the app has a bug. They also have no in-app path to repair the pair record — the existing `/api/device/wifi/repair` button only appears next to already-listed devices.

Real instance: 2026-06-02. UDID `00008140-001C75C43433001C` was visible to `pymobiledevice3.usbmux.list_devices()` but kept failing `validate_pairing` with `ConnectionTerminatedError`. Backend log captured every failure; UI showed nothing.

## Goals

1. A USB device whose pair handshake fails is still **visible** in the device list, with a clear status indicating *why*.
2. The user can trigger a re-pair from the device row without typing a shell command.
3. The new contract is purely additive — existing callers of `/api/device/list` and `DeviceInfo` keep working without changes.

## Non-goals (v1, deferred)

- Dedicated `POST /api/device/{udid}/repair-trust` endpoint. The existing `/api/device/wifi/repair` already runs the USB autopair flow we need; we extend it with an optional `udid` param instead of adding a new route.
- WebSocket event `device_pair_status_changed`. The frontend already polls `/api/device/list`; broadcasting transitions is nice-to-have, not required. Revisit if poll lag becomes noticeable.
- "Repair all failed devices" button. Auto-triggering re-pair across multiple iPhones at once would queue several Trust prompts in unpredictable order on the user's screen. Keep it one-per-row.

## Approach

Extend `DeviceInfo` with two fields:

```python
class DeviceInfo(BaseModel):
    udid: str
    name: str
    ios_version: str
    connection_type: str = "usb"
    is_connected: bool = False
    developer_mode_enabled: bool | None = None
    # NEW — additive, default keeps legacy callers green
    pair_status: Literal["ok", "trust_required", "error"] = "ok"
    pair_error: str | None = None
```

`discover_devices()` switches from "swallow and drop" to "classify and surface":

```python
try:
    lockdown = await create_using_usbmux(serial=raw.serial)
    # existing happy path: pair_status defaults to "ok"
    ...
except Exception as exc:
    pair_status, pair_error = _classify_pair_error(exc)
    cached_name = _load_device_name_cache().get(raw.serial, "iPhone")
    info = DeviceInfo(
        udid=raw.serial,
        name=cached_name,
        ios_version="0.0",
        connection_type=getattr(raw, "connection_type", "USB"),
        is_connected=False,
        pair_status=pair_status,
        pair_error=pair_error,
    )
    devices.append(info)
    logger.warning(
        "Pair failure for %s: %s — surfacing as %s",
        raw.serial, exc, pair_status,
    )
```

`_classify_pair_error(exc)` maps the exception to a `(pair_status, pair_error)` pair:

| Exception / message | pair_status | pair_error (zh-tw) |
|---|---|---|
| `ConnectionTerminatedError` | `trust_required` | "iPhone 端已不認得此電腦，請重新信任" |
| `PairingDialogResponsePendingError` (text contains "consent" / "PairingDialogResponsePending") | `trust_required` | "請在 iPhone 解鎖畫面上按「信任」" |
| message contains "not paired" / `PairingError` | `trust_required` | "USB 配對失效，請重插 USB 並按信任" |
| everything else | `error` | first 200 chars of `str(exc)` |

The classifier mirrors the existing `_classify_repair_error()` at `backend/api/device.py:116-134` so the user sees consistent wording.

## Endpoint extension

`POST /api/device/wifi/repair` already runs the USB lockdown autopair + RemotePairing regeneration we need. Today it auto-picks the first USB device in the list. Extend the request schema:

```python
class WifiRepairRequest(BaseModel):
    udid: str | None = None  # None = legacy behavior (first USB device)
```

When `udid` is set, repair that specific device. When `None`, keep today's "first USB device" behavior so the existing UI button keeps working unchanged.

The endpoint name `wifi/repair` is misleading for what is partly a USB-trust operation. We tolerate the legacy name in v1 to keep the change minimal. A rename to `/api/device/{udid}/repair` is a future cleanup.

## Frontend changes

`frontend/src/components/DeviceStatus.tsx` renders one row per device. Add status-aware decoration:

- `pair_status === "ok"` — render exactly as today, no chip.
- `pair_status === "trust_required"` — yellow chip "需要信任" + "重新信任" button. Clicking opens the existing `setShowRepairConfirm(true)` modal, passes the row's `udid` into the POST body, refreshes the device list on success.
- `pair_status === "error"` — red chip "無法連線" + tooltip showing `pair_error`. No button — these are not the user's to fix.

Failed devices sort to the bottom of the list so they don't crowd healthy devices in single-device flows.

`is_connected` stays `false` for any `pair_status !== "ok"` device. We do not invent a new "pair_pending" state on top of the existing boolean — that would force every downstream consumer to learn a new value.

## Test plan

**Backend (pytest)**

1. `test_discover_surfaces_pair_failed_device` — mock `list_devices` to return one raw entry; mock `create_using_usbmux` to raise `ConnectionTerminatedError`; assert `discover_devices()` returns a list of length 1 with `pair_status="trust_required"` and the cached device name.
2. `test_classify_pair_error_known_codes` — table-driven mapping check.
3. `test_wifi_repair_accepts_udid_param` — POSTing with `udid` targets that specific device; POSTing without `udid` falls back to first-USB behavior (existing).
4. `test_discover_preserves_ok_devices_alongside_failed` — mock two devices, one passes lockdown, one fails — assert both appear with correct `pair_status`.

**Frontend**

5. `DeviceStatus` snapshot in three states: `ok` (no chip), `trust_required` (yellow chip + button), `error` (red chip + tooltip).

**Manual end-to-end** (mirrors the 2026-06-02 incident)

6. `sudo rm ~/.pymobiledevice3/<udid>.plist`, replug USB, launch LocWarp. Expect the device row to show with a yellow "需要信任" chip and a "重新信任" button. Click the button → confirm modal → iPhone prompts for trust → tap Trust → row turns green within one poll cycle.

## Risks

- **Legacy callers reading `/api/device/list` over the WS push** — none exist in this repo; checked frontend `useDeviceList`/`DeviceStatus`. Pydantic defaults keep serialization additive.
- **`_load_device_name_cache()` called once per failed device per poll** — current poll cadence and small cache (one entry per ever-paired iPhone) make this a non-issue. If polling tightens later, move the cache to a process-level memo.
- **A device that fails for a transient reason (briefly unplugged mid-handshake) would briefly show as "trust_required"** — acceptable; the next poll restores `"ok"` once the handshake succeeds. The classifier could later add a "transient" state, but YAGNI for v1.

## Out of scope follow-ups

- Rename `/api/device/wifi/repair` to a more honest path.
- Add `device_pair_status_changed` WS event so transitions show immediately rather than at the next poll.
- Surface `pair_status` in the menu-bar / tray indicator (today only shows connected count).
