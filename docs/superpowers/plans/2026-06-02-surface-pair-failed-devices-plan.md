# Surface pair-failed USB devices — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop silently dropping USB iPhones whose pair handshake fails. Surface them in `/api/device/list` with a `pair_status` field so the UI can show a "Trust required" chip + per-row repair button instead of pretending the device is absent.

**Architecture:** Pure additive change to `DeviceInfo`. `discover_devices()` catches per-device exceptions but now emits a stub `DeviceInfo` with `pair_status="trust_required"` or `"error"` instead of dropping the entry. The existing `/api/device/wifi/repair` endpoint gains an optional `udid` param so the per-row button can target a specific device. Frontend reads `pair_status` to decorate rows.

**Tech Stack:** Python 3.11 + FastAPI + pydantic on the backend; React + TypeScript on the frontend; pymobiledevice3 for USB lockdown. Backend pytest (asyncio strict). No frontend test infra exists in this repo — frontend verification is `npx tsc --noEmit` plus the manual e2e in Task 9.

**Spec deviation:** Spec test #5 (DeviceStatus snapshot in three states) is deferred — frontend lacks Jest/Vitest infrastructure. Coverage falls to Task 9 manual e2e.

**File structure (created or modified):**

| Path | Responsibility |
|---|---|
| `backend/models/schemas.py` | Add `pair_status` + `pair_error` to `DeviceInfo` |
| `backend/core/device_manager.py` | Add `_classify_pair_error()`; rewrite the per-device except branch in `discover_devices()` to emit a stub instead of dropping |
| `backend/api/device.py` | Add optional `udid` to `wifi_repair`; when set, target that device instead of the first USB device |
| `backend/tests/test_device_pair_failure.py` | New tests: classifier table + discover surfaces + discover mixed states |
| `backend/tests/test_device_repair_endpoint.py` | Extend existing tests: `wifi_repair` honors udid param |
| `frontend/src/hooks/useDevice.ts` | Extend TS `DeviceInfo` interface |
| `frontend/src/i18n/strings.ts` | Add chip + repair-button keys for the new states |
| `frontend/src/components/DeviceStatus.tsx` | Render pair_status chip + wire per-row repair button (pass `udid` through existing confirm modal) |

---

## Task 1: Extend DeviceInfo schema

**Files:**
- Modify: `backend/models/schemas.py:40-49`

- [ ] **Step 1: Modify the DeviceInfo class**

Edit `backend/models/schemas.py`. Replace the class body:

```python
from typing import Literal

class DeviceInfo(BaseModel):
    udid: str
    name: str
    ios_version: str
    connection_type: str = "usb"
    is_connected: bool = False
    # iOS 16+ "Developer Mode" toggle state. None means we couldn't query
    # (not connected, iOS <16, or service call failed). Frontend uses this
    # to decide whether to show the "Reveal Developer Mode option" button.
    developer_mode_enabled: bool | None = None
    # Pair-handshake state. "ok" = lockdown query succeeded; "trust_required"
    # = device is muxed but iPhone has forgotten this host (re-trust needed);
    # "error" = some other failure (text in pair_error). Default keeps legacy
    # callers green — existing happy paths leave both fields untouched.
    pair_status: Literal["ok", "trust_required", "error"] = "ok"
    pair_error: str | None = None
```

If `Literal` isn't already imported at the top of the file, add `from typing import Literal` to the existing imports block (grouped with other `typing` imports).

- [ ] **Step 2: Verify import + default**

Run:
```bash
cd backend && .venv/bin/python -c "from models.schemas import DeviceInfo; d = DeviceInfo(udid='x', name='n', ios_version='17.0'); print(d.pair_status, d.pair_error)"
```
Expected: `ok None`

- [ ] **Step 3: Commit**

```bash
git add backend/models/schemas.py
git commit -m "feat(device): add pair_status + pair_error to DeviceInfo"
```

---

## Task 2: Add `_classify_pair_error()` helper with tests

**Files:**
- Modify: `backend/core/device_manager.py` (add helper near top, after `_remember_wifi_alias`)
- Create: `backend/tests/test_device_pair_failure.py`

- [ ] **Step 1: Write the failing test for classifier**

Create `backend/tests/test_device_pair_failure.py`:

```python
"""Tests for surfacing devices that fail USB lockdown pair validation."""

import pytest

from core.device_manager import _classify_pair_error


class _FakePairingPending(Exception):
    """Stand-in for pymobiledevice3.exceptions.PairingDialogResponsePendingError."""


class _FakeNotPaired(Exception):
    """Stand-in for pymobiledevice3.exceptions.PairingError ('not paired')."""


@pytest.mark.parametrize(
    "exc,expected_status,expected_substring",
    [
        # ConnectionTerminatedError is the most common signal for a stale
        # pair record (iPhone has forgotten this host). Mapped to "trust_required".
        (ConnectionResetError("Connection terminated"), "trust_required", "重新信任"),
        # PairingDialogResponsePending: user hasn't tapped Trust yet.
        (_FakePairingPending("PairingDialogResponsePending"), "trust_required", "信任"),
        # "not paired" text from PairingError variants.
        (_FakeNotPaired("device is not paired with this host"), "trust_required", "USB"),
        # Anything else falls through to "error" with the raw message.
        (RuntimeError("unexpected backend explosion"), "error", "unexpected backend explosion"),
    ],
)
def test_classify_pair_error_maps_known_signals(exc, expected_status, expected_substring):
    status, message = _classify_pair_error(exc)
    assert status == expected_status
    assert expected_substring in message


def test_classify_pair_error_trims_long_message():
    long = "x" * 500
    status, message = _classify_pair_error(RuntimeError(long))
    assert status == "error"
    assert len(message) <= 200
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_pair_failure.py -v
```
Expected: ImportError / AttributeError — `_classify_pair_error` doesn't exist yet.

- [ ] **Step 3: Implement the classifier**

Edit `backend/core/device_manager.py`. After the `_remember_wifi_alias` function (around line 173), insert:

```python
# ---------------------------------------------------------------------------
# Pair-failure classifier
# ---------------------------------------------------------------------------
#
# Maps a create_using_usbmux() exception into a (pair_status, pair_error)
# pair the API surfaces on DeviceInfo. Mirrors _classify_repair_error() in
# api/device.py so the user sees consistent wording across the discover
# path and the explicit repair path. Kept in a small pure function so it
# can be unit-tested without touching pymobiledevice3 internals.

_PAIR_ERROR_MAX_LEN = 200


def _classify_pair_error(exc: BaseException) -> tuple[str, str]:
    """Return ``(pair_status, pair_error_message)`` for a USB pair failure."""
    name = type(exc).__name__
    msg = str(exc)
    lower = msg.lower()

    # ConnectionTerminatedError / ConnectionResetError during validate_pairing
    # means the iPhone rejected the existing host record — re-trust needed.
    if "ConnectionTerminated" in name or "ConnectionReset" in name or "connection terminated" in lower:
        return "trust_required", "iPhone 端已不認得此電腦，請重新信任"

    # User hasn't tapped Trust on the device yet.
    if "PairingDialogResponsePending" in msg or "consent" in lower:
        return "trust_required", "請在 iPhone 解鎖畫面上按「信任」"

    # PairingError / "not paired" text variants.
    if "not paired" in lower or "pairingerror" in lower:
        return "trust_required", "USB 配對失效，請重插 USB 並按信任"

    # Fallback: surface the raw message (trimmed) under the generic "error" bucket.
    trimmed = msg[:_PAIR_ERROR_MAX_LEN] if msg else f"{name}"
    return "error", trimmed
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_pair_failure.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/core/device_manager.py backend/tests/test_device_pair_failure.py
git commit -m "feat(device): classify USB pair-handshake failures"
```

---

## Task 3: `discover_devices()` surfaces failed devices instead of dropping them

**Files:**
- Modify: `backend/core/device_manager.py:235-275` (the per-device try/except inside `discover_devices`)
- Modify: `backend/tests/test_device_pair_failure.py` (add discover tests)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_device_pair_failure.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.device_manager import DeviceManager


def _make_dm() -> DeviceManager:
    """Build a DeviceManager without touching real iOS hardware."""
    dm = DeviceManager.__new__(DeviceManager)
    dm._connections = {}
    dm._lock = MagicMock()
    return dm


def _raw_mux(serial: str, connection_type: str = "USB"):
    raw = MagicMock()
    raw.serial = serial
    raw.connection_type = connection_type
    return raw


@pytest.fixture(autouse=True)
def isolated_device_cache(tmp_path, monkeypatch):
    """device_manager._load_device_name_cache reads DEVICE_NAMES_FILE — keep
    that file isolated per test so no host state leaks in."""
    fake = tmp_path / "device_names.json"
    monkeypatch.setattr("core.device_manager.DEVICE_NAMES_FILE", fake)
    yield


def test_discover_surfaces_pair_failed_device(monkeypatch):
    """A USB device whose create_using_usbmux raises should still appear
    in the returned list — with pair_status set, not silently dropped."""
    raw = _raw_mux("00008140-DEADBEEF")

    async def _fake_list_devices():
        return [raw]

    async def _exploding_lockdown(serial):
        raise ConnectionResetError("Connection terminated")

    monkeypatch.setattr("core.device_manager.list_devices", _fake_list_devices)
    monkeypatch.setattr("core.device_manager.create_using_usbmux", _exploding_lockdown)

    dm = _make_dm()
    devices = asyncio.run(dm.discover_devices())

    assert len(devices) == 1
    info = devices[0]
    assert info.udid == "00008140-DEADBEEF"
    assert info.pair_status == "trust_required"
    assert "重新信任" in info.pair_error
    assert info.is_connected is False


def test_discover_mixes_healthy_and_failed(monkeypatch):
    """Two devices: one passes lockdown, one explodes. Both must surface."""
    healthy = _raw_mux("00008110-GOOD")
    broken = _raw_mux("00008140-BAD")

    async def _fake_list_devices():
        return [healthy, broken]

    healthy_lockdown = MagicMock()
    healthy_lockdown.all_values = {
        "DeviceName": "Healthy iPhone",
        "ProductVersion": "17.5",
    }
    healthy_lockdown.get_developer_mode_status = AsyncMock(return_value=True)

    async def _conditional_lockdown(serial):
        if serial == "00008110-GOOD":
            return healthy_lockdown
        raise ConnectionResetError("Connection terminated")

    monkeypatch.setattr("core.device_manager.list_devices", _fake_list_devices)
    monkeypatch.setattr("core.device_manager.create_using_usbmux", _conditional_lockdown)

    dm = _make_dm()
    devices = asyncio.run(dm.discover_devices())

    assert len(devices) == 2
    by_udid = {d.udid: d for d in devices}

    assert by_udid["00008110-GOOD"].pair_status == "ok"
    assert by_udid["00008110-GOOD"].name == "Healthy iPhone"
    assert by_udid["00008110-GOOD"].pair_error is None

    assert by_udid["00008140-BAD"].pair_status == "trust_required"
    assert by_udid["00008140-BAD"].name == "iPhone"  # cache miss → generic fallback
    assert by_udid["00008140-BAD"].pair_error is not None


def test_discover_uses_cached_name_for_failed_device(monkeypatch, tmp_path):
    """When a previously-paired device fails this round, surface the cached
    DeviceName instead of the generic 'iPhone' fallback so the user knows
    which physical phone is in trouble."""
    import json
    (tmp_path / "device_names.json").write_text(
        json.dumps({"00008140-BAD": "Ravi's iPhone"})
    )

    raw = _raw_mux("00008140-BAD")

    async def _fake_list_devices():
        return [raw]

    async def _exploding_lockdown(serial):
        raise ConnectionResetError("Connection terminated")

    monkeypatch.setattr("core.device_manager.list_devices", _fake_list_devices)
    monkeypatch.setattr("core.device_manager.create_using_usbmux", _exploding_lockdown)

    dm = _make_dm()
    devices = asyncio.run(dm.discover_devices())

    assert len(devices) == 1
    assert devices[0].name == "Ravi's iPhone"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_pair_failure.py -v
```
Expected: 5 classifier tests pass; 3 new discover tests fail — the failed device is dropped from the list (length 0 instead of 1; length 1 instead of 2).

- [ ] **Step 3: Rewrite the per-device except branch**

Edit `backend/core/device_manager.py:235-275`. Replace the entire for-loop body in `discover_devices()` (the block that starts with `for raw in raw_devices:` and currently ends with the `except Exception: logger.exception(...)`):

```python
        for raw in raw_devices:
            conn_type = getattr(raw, "connection_type", "USB")
            # If we already saw this device via USB, skip the Network duplicate
            if raw.serial in seen_udids:
                # But upgrade to USB if this entry is USB (prefer USB info)
                if conn_type == "USB":
                    for d in devices:
                        if d.udid == raw.serial:
                            d.connection_type = "USB"
                continue
            seen_udids.add(raw.serial)

            try:
                lockdown = await create_using_usbmux(serial=raw.serial)
            except Exception as exc:
                # Pair handshake failed. Don't drop the device — surface a stub
                # so the UI can render a "needs trust" chip + per-row repair
                # button instead of silently hiding the iPhone the user just
                # plugged in. Use the cached DeviceName so the row names the
                # physical phone (else generic "iPhone" fallback).
                pair_status, pair_error = _classify_pair_error(exc)
                cached_name = _load_device_name_cache().get(raw.serial, "iPhone")
                info = DeviceInfo(
                    udid=raw.serial,
                    name=cached_name,
                    ios_version="0.0",
                    connection_type=conn_type,
                    is_connected=False,
                    pair_status=pair_status,
                    pair_error=pair_error,
                )
                devices.append(info)
                logger.warning(
                    "Pair failure for %s: %s — surfacing as %s",
                    raw.serial, exc, pair_status,
                )
                continue

            try:
                all_values = lockdown.all_values
                # If device is already connected, report the active connection type
                active_conn = self._connections.get(raw.serial)
                if active_conn:
                    conn_type = active_conn.connection_type
                device_name = all_values.get("DeviceName", "Unknown")
                _remember_device_name(raw.serial, device_name)
                info = DeviceInfo(
                    udid=raw.serial,
                    name=device_name,
                    ios_version=all_values.get("ProductVersion", "0.0"),
                    connection_type=conn_type,
                )
                info.is_connected = raw.serial in self._connections
                # Query Developer Mode status (iOS 16+). Tolerate failure —
                # None means "unknown", frontend will hide the reveal button.
                try:
                    ver = _parse_ios_version(info.ios_version)
                    if ver >= (16, 0):
                        info.developer_mode_enabled = await lockdown.get_developer_mode_status()
                except Exception:
                    logger.debug("get_developer_mode_status failed for %s", raw.serial, exc_info=True)
                devices.append(info)
                logger.debug("Discovered device %s (%s) running iOS %s via %s (connected=%s)",
                             info.name, info.udid, info.ios_version, conn_type, info.is_connected)
            except Exception:
                # Lockdown opened but a later property/method blew up — still
                # surface the device so the user knows it's there.
                pair_status, pair_error = _classify_pair_error(
                    RuntimeError("lockdown query failed after handshake")
                )
                cached_name = _load_device_name_cache().get(raw.serial, "iPhone")
                devices.append(DeviceInfo(
                    udid=raw.serial,
                    name=cached_name,
                    ios_version="0.0",
                    connection_type=conn_type,
                    is_connected=False,
                    pair_status=pair_status,
                    pair_error=pair_error,
                ))
                logger.exception("Failed to query device %s after lockdown opened", raw.serial)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_pair_failure.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Run the full backend test suite to confirm no regressions**

```bash
cd backend && .venv/bin/python -m pytest -q
```
Expected: all tests pass. If `test_device_display_name.py` or other device tests fail, the schema additive change has accidentally broken something — investigate before continuing.

- [ ] **Step 6: Commit**

```bash
git add backend/core/device_manager.py backend/tests/test_device_pair_failure.py
git commit -m "feat(device): surface USB pair-failed devices instead of dropping them"
```

---

## Task 4: `wifi_repair` accepts optional `udid`

**Files:**
- Modify: `backend/api/device.py:137-269` (the `wifi_repair` route)
- Modify: `backend/tests/test_device_repair_endpoint.py` (extend existing tests)

- [ ] **Step 1: Inspect existing test file**

```bash
head -50 backend/tests/test_device_repair_endpoint.py
```
Note its fixtures + mock pattern so the new test follows the same shape.

- [ ] **Step 2: Write the failing test**

Append to `backend/tests/test_device_repair_endpoint.py` (use the same fixtures and import style already present at the top of the file):

```python
def test_wifi_repair_targets_requested_udid(monkeypatch):
    """When the request body carries a udid, wifi_repair must use that
    specific device instead of defaulting to the first USB entry."""
    from fastapi.testclient import TestClient
    from main import app  # FastAPI app

    # Two USB devices visible at usbmux level. wifi_repair must pick the
    # one whose udid was named in the body, not the first one.
    raw_first = MagicMock(serial="UDID-FIRST", connection_type="USB")
    raw_target = MagicMock(serial="UDID-TARGET", connection_type="USB")

    async def _fake_mux_list():
        return [raw_first, raw_target]

    seen_serial = {}
    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {"ProductVersion": "16.5", "DeviceName": "Target"}

    async def _fake_lockdown(serial, autopair=False):
        seen_serial["serial"] = serial
        return fake_lockdown

    monkeypatch.setattr("api.device.mux_list_devices", _fake_mux_list, raising=False)
    monkeypatch.setattr("api.device.create_using_usbmux", _fake_lockdown, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": "UDID-TARGET"})

    assert resp.status_code == 200
    assert resp.json()["udid"] == "UDID-TARGET"
    assert seen_serial["serial"] == "UDID-TARGET"


def test_wifi_repair_without_udid_keeps_legacy_first_usb(monkeypatch):
    """Omitting udid (or sending an empty body) preserves legacy behavior:
    pick the first USB device. Existing UI button must keep working."""
    from fastapi.testclient import TestClient
    from main import app

    raw_first = MagicMock(serial="UDID-FIRST", connection_type="USB")
    raw_other = MagicMock(serial="UDID-OTHER", connection_type="USB")

    async def _fake_mux_list():
        return [raw_first, raw_other]

    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {"ProductVersion": "16.5", "DeviceName": "First"}
    seen_serial = {}

    async def _fake_lockdown(serial, autopair=False):
        seen_serial["serial"] = serial
        return fake_lockdown

    monkeypatch.setattr("api.device.mux_list_devices", _fake_mux_list, raising=False)
    monkeypatch.setattr("api.device.create_using_usbmux", _fake_lockdown, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair")

    assert resp.status_code == 200
    assert resp.json()["udid"] == "UDID-FIRST"
    assert seen_serial["serial"] == "UDID-FIRST"
```

Note: if `test_device_repair_endpoint.py` already imports `MagicMock`/`asyncio`/etc., reuse those imports rather than adding duplicates.

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_repair_endpoint.py::test_wifi_repair_targets_requested_udid tests/test_device_repair_endpoint.py::test_wifi_repair_without_udid_keeps_legacy_first_usb -v
```
Expected: first test fails — current `wifi_repair()` accepts no body and ignores any udid input.

- [ ] **Step 4: Add the request schema + thread udid through wifi_repair**

Edit `backend/api/device.py`. Just above `@router.post("/wifi/repair")` (around line 137), add:

```python
class WifiRepairRequest(BaseModel):
    """Optional body for /wifi/repair. When ``udid`` is set, repair that
    specific device; when None, fall back to the legacy "first USB device
    in the mux list" behavior so the existing global Repair button keeps
    working unchanged."""
    udid: str | None = None
```

Then change the `wifi_repair` signature from:
```python
async def wifi_repair():
```
to:
```python
async def wifi_repair(req: WifiRepairRequest | None = None):
```

And replace the USB-device selection block (currently at lines ~167-175 inside the function — the `usb_dev = next(...)` selection):

```python
    requested_udid = req.udid if req else None
    if requested_udid:
        usb_dev = next(
            (d for d in raw_devices
             if d.serial == requested_udid
             and getattr(d, "connection_type", "USB") == "USB"),
            None,
        )
        if usb_dev is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "device_not_found",
                    "message": f"找不到 USB 裝置 {requested_udid}。請確認 USB 線已接好。",
                    "udid": requested_udid,
                },
            )
    else:
        # Legacy behavior: pick the first USB-attached device.
        usb_dev = next(
            (d for d in raw_devices if getattr(d, "connection_type", "USB") == "USB"),
            None,
        )
        if usb_dev is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "repair_needs_usb",
                    "message": "請先用 USB 線連接 iPhone。重新配對需要 USB 觸發『信任這台電腦』提示。",
                },
            )
```

Keep the existing alias for the mux import — if the file currently does `from pymobiledevice3.usbmux import list_devices as mux_list_devices`, keep that. If it imports `list_devices` directly, leave the original module-level import alone and only monkeypatch what the test does. (The test in Step 2 patches `api.device.mux_list_devices` and `api.device.create_using_usbmux` with `raising=False`, so it tolerates either import shape.)

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_repair_endpoint.py -v
```
Expected: both new tests pass; previously-passing tests in the file still pass.

- [ ] **Step 6: Run full backend suite**

```bash
cd backend && .venv/bin/python -m pytest -q
```
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add backend/api/device.py backend/tests/test_device_repair_endpoint.py
git commit -m "feat(device): /wifi/repair accepts optional udid for per-row repair"
```

---

## Task 5: Extend TS DeviceInfo + add chip i18n strings

**Files:**
- Modify: `frontend/src/hooks/useDevice.ts:10` (interface DeviceInfo)
- Modify: `frontend/src/i18n/strings.ts` (append new keys)

- [ ] **Step 1: Locate the existing interface**

```bash
sed -n '8,28p' frontend/src/hooks/useDevice.ts
```
Note the exact field order so the new fields slot in cleanly.

- [ ] **Step 2: Add fields to the TS interface**

Edit `frontend/src/hooks/useDevice.ts`. In the `export interface DeviceInfo { ... }` block, add two fields after the existing optional fields:

```ts
  // Pair-handshake state from the backend. "ok" = device is healthy;
  // "trust_required" = iPhone forgot this host, needs re-trust;
  // "error" = some other lockdown failure (text in pair_error).
  // Older backends omit this field; treat undefined as "ok".
  pair_status?: 'ok' | 'trust_required' | 'error';
  pair_error?: string | null;
```

- [ ] **Step 3: Add the i18n keys**

Edit `frontend/src/i18n/strings.ts`. Just below the existing `wifi.repair_*` block (after line ~253), insert:

```ts
  'device.pair_chip_trust': { zh: '需要信任', en: 'Trust required' },
  'device.pair_chip_error': { zh: '無法連線', en: 'Cannot connect' },
  'device.pair_repair_button': { zh: '重新信任', en: 'Re-trust' },
  'device.pair_repair_tooltip': { zh: '重新觸發「信任這台電腦」提示。請先用 USB 線連接 iPhone', en: 'Re-trigger the "Trust This Computer" prompt. Connect the iPhone via USB first.' },
```

- [ ] **Step 4: Type-check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useDevice.ts frontend/src/i18n/strings.ts
git commit -m "feat(device): TS DeviceInfo + i18n for pair_status chip"
```

---

## Task 6: DeviceStatus renders pair_status chip + per-row repair button

**Files:**
- Modify: `frontend/src/components/DeviceStatus.tsx`

This file is large (~970 lines) and the existing `wifi.repair_*` confirm-modal flow lives at the bottom. Goal: reuse that modal, just parameterize it on a target udid.

- [ ] **Step 1: Locate the existing per-device row JSX**

```bash
grep -nE "devices\.map|device\.udid|connection_type" frontend/src/components/DeviceStatus.tsx | head -20
```
Identify where each device row is rendered (the `.map(device => ...)` block) and where the name/status is shown.

- [ ] **Step 2: Add chip + repair button next to the device name**

Inside the device-row JSX (the element that already shows `device.name` / connection type / connected-state indicator), append a small chip cluster that renders only when `device.pair_status` is set and not `'ok'`. The exact JSX styling should match the surrounding row aesthetic — pick the closest existing chip pattern in the file rather than inventing a new one. Skeleton:

```tsx
{device.pair_status && device.pair_status !== 'ok' && (
  <span
    style={{
      marginLeft: 8,
      padding: '2px 6px',
      borderRadius: 4,
      fontSize: 11,
      background: device.pair_status === 'trust_required' ? '#fff3cd' : '#f8d7da',
      color: device.pair_status === 'trust_required' ? '#856404' : '#721c24',
    }}
    title={device.pair_error || ''}
  >
    {device.pair_status === 'trust_required'
      ? t('device.pair_chip_trust')
      : t('device.pair_chip_error')}
  </span>
)}
{device.pair_status === 'trust_required' && (
  <button
    type="button"
    onClick={() => {
      setRepairTargetUdid(device.udid);
      setRepairState('idle');
      setRepairMessage('');
      setShowRepairConfirm(true);
    }}
    title={t('device.pair_repair_tooltip')}
    style={{ marginLeft: 6, fontSize: 11, padding: '2px 6px' }}
  >
    {t('device.pair_repair_button')}
  </button>
)}
```

- [ ] **Step 3: Thread a `repairTargetUdid` state through the existing modal**

Find the existing `useState` declarations for `showRepairConfirm`, `repairState`, `repairMessage` (around line 76-78). Add alongside them:

```tsx
const [repairTargetUdid, setRepairTargetUdid] = useState<string | null>(null);
```

Find the existing fetch call inside the confirm modal that POSTs to `/api/device/wifi/repair`. Modify the body so it includes the target udid when present:

```tsx
const body = repairTargetUdid ? { udid: repairTargetUdid } : {};
const r = await fetch(`${API}/api/device/wifi/repair`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});
```

The existing global "Repair" button (the one not tied to a specific device row) should reset `repairTargetUdid` to `null` when opening the modal, so it keeps the legacy "first USB device" behavior:

```tsx
onClick={() => {
  setRepairTargetUdid(null);
  setRepairState('idle');
  setRepairMessage('');
  setShowRepairConfirm(true);
}}
```

On modal close (cancel / success), also reset `setRepairTargetUdid(null)` so a subsequent global-button click doesn't accidentally inherit the previous row's udid.

- [ ] **Step 4: Type-check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DeviceStatus.tsx
git commit -m "feat(device): per-row pair_status chip + Re-trust button"
```

---

## Task 7: Manual end-to-end verification

This is the spec's test #6 and the only UI coverage we get (no frontend test infra). Do not skip.

- [ ] **Step 1: Rebuild + install the app**

```bash
make build-install
```
Wait for the "Done. Launch: open -a LocWarp" message.

- [ ] **Step 2: Reproduce the failure state**

With a USB iPhone connected (one that has been paired before — the host's `~/.pymobiledevice3/<udid>.plist` exists):

```bash
ls ~/.pymobiledevice3/
sudo rm ~/.pymobiledevice3/<udid>.plist
```

Unplug + replug the USB cable. Do NOT tap Trust on the iPhone yet.

- [ ] **Step 3: Launch the app and observe**

```bash
open -a LocWarp
```

Expected within ~5 seconds of the device list refreshing:
- The device row for `<udid>` appears (it would have been hidden in the old behavior).
- A yellow chip reading "需要信任" / "Trust required" sits next to the device name.
- A "重新信任" / "Re-trust" button sits next to the chip.

- [ ] **Step 4: Trigger re-trust from the UI**

Click the per-row "重新信任" button. Confirm the modal that appears. On the iPhone, tap "Trust" + enter passcode.

Expected:
- Modal shows the running / success states (reusing the existing `wifi.repair_*` flow).
- Within one device-list poll cycle, the chip + button disappear and the row goes back to its healthy state.

- [ ] **Step 5: Verify the global Repair button still works (regression check)**

If LocWarp's existing global "Repair" button is on the page, click it — without a `repairTargetUdid`, the modal should still drive a re-pair against the first USB device (legacy behavior).

- [ ] **Step 6: Verify the API shape from outside the UI**

```bash
curl -s http://127.0.0.1:8777/api/device/list | python3 -m json.tool
```

Expected: each entry has `pair_status` (and `pair_error` if applicable). Healthy entries should show `"pair_status": "ok"` (or omit it depending on how `model_dump` serializes the default — both are acceptable).

- [ ] **Step 7: Commit the verification note** (optional)

If you take a screenshot or note of the e2e result, drop it into `docs/superpowers/specs/` next to the design doc — otherwise skip.

---

## Self-Review

**Spec coverage:**
- Spec goal 1 (visible in list with status) — Task 3
- Spec goal 2 (in-app repair from row) — Task 4 (backend) + Task 6 (frontend)
- Spec goal 3 (additive contract) — Task 1 + Task 5
- Spec tests 1-4 (backend) — Task 2 + Task 3 + Task 4
- Spec test 5 (frontend snapshot) — **deferred + documented at top of plan**, no frontend test infra exists; coverage falls to Task 7 manual e2e
- Spec test 6 (manual e2e) — Task 7
- Spec out-of-scope (separate repair endpoint, WS event, "fix all" button) — not in plan, matches spec

**Type consistency:**
- `pair_status` literal values `"ok" / "trust_required" / "error"` consistent across schemas.py, classifier, tests, TS interface, JSX
- `pair_error` is `str | None` (Python) / `string | null` (TS)
- `WifiRepairRequest.udid` is `str | None` consistent with how the test sends it and the JSX sets it
- `repairTargetUdid` state type `string | null` matches what the button passes in

**Placeholders:** none.

**Scope:** single focused change, no decomposition needed.
