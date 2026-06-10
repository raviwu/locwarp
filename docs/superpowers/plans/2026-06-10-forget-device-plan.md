# Forget this device — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One UI action ("忘記此裝置") removes a device pairing end-to-end — iPhone-side unpair (best-effort), session teardown, host pair-record removal, persistent watchdog suppression — plus fix the discovery-poll `autopair=True` bug that silently defeats `sticky_user_denied`.

**Architecture:** New endpoint `POST /api/device/{udid}/forget` composes the existing building blocks (`acquire_pair_lock`, `delete_system_pair_record`, `delete_local_pair_record`, WiFi teardown helpers, `sticky_user_denied`). `sticky_user_denied` mutations get wrapped in two `DeviceManager` methods (`mark_user_denied` / `clear_user_denied`) that persist to a new `~/.locwarp/sticky_denied.json`. `discover_devices()` switches to `autopair=False` so the device-list poll never pops the iOS Trust dialog. Frontend adds a chip-menu item + confirm modal.

**Tech Stack:** Python 3.11 + FastAPI + pymobiledevice3; pytest (asyncio strict); React + TypeScript.

**Spec reference:** `docs/superpowers/specs/2026-06-10-forget-device-design.md`

**File structure:**

| Path | Responsibility |
|---|---|
| `backend/config.py` | New `STICKY_DENIED_FILE` constant |
| `backend/core/device_manager.py` | Sticky load-on-init + `mark_user_denied` / `clear_user_denied` / `_persist_sticky`; `connect()` uses `mark_user_denied`; `discover_devices()` passes `autopair=False` |
| `backend/api/device.py` | `wifi_repair` uses `clear_user_denied`; new `forget_device` route |
| `backend/main.py` | (no change — watchdog already reads the set) |
| `backend/tests/test_device_pair_failure.py` | Sticky-file isolation fixture; persistence tests; mock-signature updates for `autopair=False`; discover-kwarg pin test |
| `backend/tests/test_device_repair_endpoint.py` | Sticky-file isolation fixture; repair-persists test |
| `backend/tests/test_device_forget_endpoint.py` (NEW) | 4 forget-endpoint tests |
| `frontend/src/services/api.ts` | `forgetDevice(udid)` |
| `frontend/src/i18n/strings.ts` | 5 new keys |
| `frontend/src/components/DeviceChip.tsx` | `onForget` prop + menu item + confirm modal |
| `frontend/src/components/DeviceChipRow.tsx` | Thread `onForget` per-device |
| `frontend/src/App.tsx` | Wire `onForget` → `forgetDevice` + refresh |
| `CLAUDE.md` | Extend "USB pair records under SIP" section |

**Task ordering constraint:** Task 1 first (defines `mark_user_denied`/`clear_user_denied`); Tasks 2-4 depend on it. Tasks 5-6 independent of 2-4 but run after for clean review chunks.

---

## Task 1: Sticky persistence — config constant + DeviceManager methods

**Files:**
- Modify: `backend/config.py` (after `WIFI_ALIASES_FILE`, line ~79)
- Modify: `backend/core/device_manager.py` (`__init__` at ~250; `connect()` UserDenied branch at ~452)
- Modify: `backend/tests/test_device_pair_failure.py` (extend autouse fixture + new tests)

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_device_pair_failure.py`, FIRST extend the existing autouse fixture `isolated_device_cache` so every test in the file also gets an isolated sticky file (without this, `dm.__init__()` would read — and persistence tests would write — the real `~/.locwarp/sticky_denied.json`):

```python
@pytest.fixture(autouse=True)
def isolated_device_cache(tmp_path, monkeypatch):
    """device_manager reads DEVICE_NAMES_FILE and STICKY_DENIED_FILE — keep
    both isolated per test so no host state leaks in or out."""
    fake = tmp_path / "device_names.json"
    monkeypatch.setattr("core.device_manager.DEVICE_NAMES_FILE", fake)
    monkeypatch.setattr(
        "core.device_manager.STICKY_DENIED_FILE", tmp_path / "sticky_denied.json"
    )
    yield
```

(Replace the existing fixture body — same name, one added line.)

Then append the new tests:

```python
def test_sticky_persists_across_manager_instances(tmp_path):
    """mark_user_denied writes the file; a fresh DeviceManager loads it;
    clear_user_denied updates the file."""
    from core.device_manager import DeviceManager

    dm1 = DeviceManager.__new__(DeviceManager)
    dm1.__init__()
    dm1.mark_user_denied("UDID-PERSIST")

    sticky_file = tmp_path / "sticky_denied.json"
    assert sticky_file.exists()
    import json
    assert json.loads(sticky_file.read_text()) == ["UDID-PERSIST"]

    dm2 = DeviceManager.__new__(DeviceManager)
    dm2.__init__()
    assert "UDID-PERSIST" in dm2.sticky_user_denied

    dm2.clear_user_denied("UDID-PERSIST")
    assert json.loads(sticky_file.read_text()) == []

    dm3 = DeviceManager.__new__(DeviceManager)
    dm3.__init__()
    assert dm3.sticky_user_denied == set()


def test_sticky_load_tolerates_missing_or_corrupt_file(tmp_path):
    """No file → empty set. Garbage JSON → empty set. Wrong shape → empty
    set (or string-filtered). Never raises."""
    from core.device_manager import DeviceManager

    # Missing file
    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()
    assert dm.sticky_user_denied == set()

    sticky_file = tmp_path / "sticky_denied.json"

    # Corrupt JSON
    sticky_file.write_text("{not json[")
    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()
    assert dm.sticky_user_denied == set()

    # Wrong shape (dict instead of list)
    sticky_file.write_text('{"udid": true}')
    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()
    assert dm.sticky_user_denied == set()

    # Mixed list — non-strings dropped
    sticky_file.write_text('["GOOD-UDID", 42, null]')
    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()
    assert dm.sticky_user_denied == {"GOOD-UDID"}


def test_connect_user_denied_persists_to_file(monkeypatch, tmp_path):
    """connect()'s UserDenied branch must go through mark_user_denied so
    the sticky flag survives a restart."""
    from core.device_manager import DeviceManager
    from pymobiledevice3.exceptions import UserDeniedPairingError

    dm = DeviceManager.__new__(DeviceManager)
    dm.__init__()

    async def fake_create(serial=None, autopair=True):
        raise UserDeniedPairingError()

    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create)

    with pytest.raises(UserDeniedPairingError):
        asyncio.run(dm.connect("UDID-DENY-PERSIST"))

    import json
    sticky_file = tmp_path / "sticky_denied.json"
    assert sticky_file.exists()
    assert "UDID-DENY-PERSIST" in json.loads(sticky_file.read_text())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_pair_failure.py -v
```
Expected: 3 new tests fail (`STICKY_DENIED_FILE` doesn't exist → fixture AttributeError, or `mark_user_denied` missing). Prior tests still pass.

- [ ] **Step 3: Add the config constant**

In `backend/config.py`, immediately after the `WIFI_ALIASES_FILE` block (line ~79), insert:

```python
# Persisted set of udids the user has explicitly refused to pair with
# ("Don't Trust" on the iPhone, or the in-app Forget action). The usbmux
# watchdog skips these so it never re-pops the Trust dialog uninvited;
# the in-app Re-trust button (wifi/repair) clears the entry.
# Shape: JSON list of udid strings.
STICKY_DENIED_FILE = DATA_DIR / "sticky_denied.json"
```

- [ ] **Step 4: Wire persistence into DeviceManager**

In `backend/core/device_manager.py`:

1. Extend the config import (line ~35) from
   `from config import DEVICE_NAMES_FILE, WIFI_ALIASES_FILE` to
   `from config import DEVICE_NAMES_FILE, STICKY_DENIED_FILE, WIFI_ALIASES_FILE`.

2. Replace the `__init__` sticky line (`self.sticky_user_denied: set[str] = set()`, ~line 255) with a load-from-disk:

```python
        # Udids the user has explicitly tapped "Don't Trust" on the iPhone
        # for, or forgotten via the in-app Forget action. The watchdog
        # refuses to auto-connect these (would just trigger another ignored
        # prompt cycle). The in-app Re-trust button clears the flag per udid
        # (see api/device.py wifi_repair handler). Persisted so the user's
        # choice survives a LocWarp restart; corrupt/missing file degrades
        # to an empty set (fail-open: watchdog resumes auto-pair).
        raw_sticky = safe_load_json(STICKY_DENIED_FILE)
        self.sticky_user_denied: set[str] = (
            {u for u in raw_sticky if isinstance(u, str)}
            if isinstance(raw_sticky, list) else set()
        )
```

3. Add the two mutation methods right after `__init__`:

```python
    def mark_user_denied(self, udid: str) -> None:
        """Add *udid* to the sticky no-auto-re-pair set and persist."""
        self.sticky_user_denied.add(udid)
        self._persist_sticky()

    def clear_user_denied(self, udid: str) -> None:
        """Remove *udid* from the sticky set (user explicitly re-trusts)
        and persist."""
        self.sticky_user_denied.discard(udid)
        self._persist_sticky()

    def _persist_sticky(self) -> None:
        safe_write_json(STICKY_DENIED_FILE, sorted(self.sticky_user_denied))
```

(`safe_load_json` / `safe_write_json` are already imported in this module.)

4. In `connect()`'s UserDenied branch (~line 452), replace
   `self.sticky_user_denied.add(udid)` with `self.mark_user_denied(udid)`.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_pair_failure.py -v
```
Expected: all pass (prior count + 3).

- [ ] **Step 6: Full backend suite**

```bash
cd backend && .venv/bin/python -m pytest -q
```
Expected: green. NOTE: if `test_device_repair_endpoint.py`'s sticky test now writes the real `~/.locwarp/sticky_denied.json` (it uses the `app_state` singleton and `wifi_repair` still calls raw `.discard`), that is addressed in Task 2 — a raw `.discard` does NOT persist, so no file write happens yet. If any test fails on the real-file path, STOP and report.

- [ ] **Step 7: Commit**

```bash
git add backend/config.py backend/core/device_manager.py backend/tests/test_device_pair_failure.py
git commit -m "feat(device): persist sticky_user_denied to ~/.locwarp/sticky_denied.json"
```

---

## Task 2: `wifi_repair` uses `clear_user_denied`

**Files:**
- Modify: `backend/api/device.py:242`
- Modify: `backend/tests/test_device_repair_endpoint.py`

- [ ] **Step 1: Write the failing test**

First add a sticky-isolation autouse fixture at module level in `backend/tests/test_device_repair_endpoint.py` (this file exercises the real `app_state.device_manager` singleton through `TestClient`, so without isolation the new persistence would write the real `~/.locwarp/sticky_denied.json` during tests):

```python
@pytest.fixture(autouse=True)
def isolated_sticky_file(tmp_path, monkeypatch):
    """wifi_repair → dm.clear_user_denied persists; keep the file in tmp."""
    monkeypatch.setattr(
        "core.device_manager.STICKY_DENIED_FILE", tmp_path / "sticky_denied.json"
    )
    yield
```

Then append the test:

```python
def test_wifi_repair_clear_persists_to_file(monkeypatch, tmp_path):
    """wifi_repair's sticky clear must go through clear_user_denied so the
    removal survives a restart (file updated, not just in-memory set)."""
    from fastapi.testclient import TestClient
    from main import app, app_state

    udid = "UDID-STICKY-PERSIST"
    dm = app_state.device_manager
    dm.mark_user_denied(udid)  # writes tmp file via the autouse fixture
    import json
    sticky_file = tmp_path / "sticky_denied.json"
    assert udid in json.loads(sticky_file.read_text())

    raw_dev = MagicMock(serial=udid, connection_type="USB")

    async def fake_mux_list():
        return [raw_dev]

    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {"ProductVersion": "16.5", "DeviceName": "P"}

    async def fake_create(serial=None, autopair=True):
        return fake_lockdown

    monkeypatch.setattr("pymobiledevice3.usbmux.list_devices", fake_mux_list, raising=False)
    monkeypatch.setattr("pymobiledevice3.lockdown.create_using_usbmux", fake_create, raising=False)
    monkeypatch.setattr("services.usbmux_pair_records.create_using_usbmux", fake_create, raising=False)

    client = TestClient(app)
    resp = client.post("/api/device/wifi/repair", json={"udid": udid})

    assert resp.status_code == 200
    assert udid not in dm.sticky_user_denied
    assert udid not in json.loads(sticky_file.read_text())
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_repair_endpoint.py::test_wifi_repair_clear_persists_to_file -v
```
Expected: FAIL on the final assertion — the raw `.discard()` mutates the set but never rewrites the file, so the udid is still in `sticky_denied.json`.

- [ ] **Step 3: Switch the call**

In `backend/api/device.py:242`, replace:

```python
    dm.sticky_user_denied.discard(udid)
```

with:

```python
    dm.clear_user_denied(udid)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_repair_endpoint.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/api/device.py backend/tests/test_device_repair_endpoint.py
git commit -m "fix(repair): persist sticky clear so re-trust survives restart"
```

---

## Task 3: `discover_devices()` passes `autopair=False`

**Files:**
- Modify: `backend/core/device_manager.py:294`
- Modify: `backend/tests/test_device_pair_failure.py`

This fixes the bug where the frontend's device-list poll re-pops the iOS Trust dialog every few seconds for unpaired devices, defeating `sticky_user_denied`.

- [ ] **Step 1: Update the four existing mock signatures**

The change adds `autopair=False` to the call, which would `TypeError` against the existing single-arg mocks. In `backend/tests/test_device_pair_failure.py`, update these four (lines ~99, ~131, ~168, ~200):

```python
    async def _exploding_lockdown(serial, autopair=True):   # was (serial)
    async def _conditional_lockdown(serial, autopair=True):  # was (serial)
    async def _open_lockdown(serial, autopair=True):         # was (serial)
```

(Both `_exploding_lockdown` occurrences.) Bodies unchanged.

- [ ] **Step 2: Write the failing pin test**

Append to `backend/tests/test_device_pair_failure.py`:

```python
def test_discover_passes_autopair_false(monkeypatch):
    """The device-list poll must NEVER trigger the iOS Trust dialog.
    autopair=True here would re-pop the dialog every few seconds for any
    unpaired device — defeating sticky_user_denied (the watchdog gate
    doesn't cover the discovery path). Pin the kwarg."""
    captured = {}

    raw = _raw_mux("00008140-PIN")

    async def _fake_list_devices():
        return [raw]

    fake_lockdown = MagicMock()
    fake_lockdown.all_values = {"DeviceName": "Pin", "ProductVersion": "17.0"}
    fake_lockdown.get_developer_mode_status = AsyncMock(return_value=False)

    async def _capturing_lockdown(serial, autopair=True):
        captured["autopair"] = autopair
        return fake_lockdown

    monkeypatch.setattr("core.device_manager.list_devices", _fake_list_devices)
    monkeypatch.setattr("core.device_manager.create_using_usbmux", _capturing_lockdown)

    dm = _make_dm()
    asyncio.run(dm.discover_devices())

    assert captured["autopair"] is False
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_pair_failure.py::test_discover_passes_autopair_false -v
```
Expected: FAIL — `captured["autopair"]` is `True` (the pymobiledevice3 default reaches the mock's default).

- [ ] **Step 4: Change the call**

In `backend/core/device_manager.py:294` (inside `discover_devices`'s for-loop), change:

```python
                lockdown = await create_using_usbmux(serial=raw.serial)
```

to:

```python
                # autopair=False: discovery is a read-only poll — it must
                # never pop the iOS Trust dialog. Pairing prompts belong to
                # connect() (autopair_with_recovery), which respects
                # sticky_user_denied. Unpaired devices raise NotPairedError
                # here, which the classifier routes to "trust_required".
                lockdown = await create_using_usbmux(serial=raw.serial, autopair=False)
```

- [ ] **Step 5: Run tests + full suite**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_pair_failure.py -v
cd backend && .venv/bin/python -m pytest -q
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/core/device_manager.py backend/tests/test_device_pair_failure.py
git commit -m "fix(device): discovery poll uses autopair=False — stop re-popping Trust dialog"
```

---

## Task 4: `POST /{udid}/forget` endpoint

**Files:**
- Modify: `backend/api/device.py` (new route after `disconnect_device`, ~line 1530, before `/{udid}/info`)
- Create: `backend/tests/test_device_forget_endpoint.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_device_forget_endpoint.py`:

```python
"""Tests for POST /api/device/{udid}/forget."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_sticky_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.device_manager.STICKY_DENIED_FILE", tmp_path / "sticky_denied.json"
    )
    yield


@pytest.fixture(autouse=True)
def clean_dm_state():
    """Tests mutate the app_state singleton; restore it afterwards."""
    from main import app_state
    dm = app_state.device_manager
    yield
    dm._connections.clear()
    dm.sticky_user_denied.clear()
    app_state.simulation_engines.clear()
    app_state._primary_udid = None


def _patch_record_deletes(monkeypatch, deletes: list):
    async def fake_delete_sys(udid):
        deletes.append(f"sys:{udid}")
        return True

    def fake_delete_local(udid):
        deletes.append(f"local:{udid}")
        return True

    monkeypatch.setattr(
        "services.usbmux_pair_records.delete_system_pair_record",
        fake_delete_sys, raising=False,
    )
    monkeypatch.setattr(
        "services.usbmux_pair_records.delete_local_pair_record",
        fake_delete_local, raising=False,
    )


def test_forget_full_flow_for_connected_usb_device(monkeypatch, tmp_path):
    """Connected USB device: unpair called on the session lockdown, session
    torn down, both record deletes called, sticky marked + persisted,
    200 with status=forgotten."""
    from main import app, app_state

    udid = "UDID-FORGET-USB"
    dm = app_state.device_manager

    fake_usb_lockdown = MagicMock()
    fake_usb_lockdown.unpair = AsyncMock()
    conn = MagicMock()
    conn.connection_type = "USB"
    conn.usbmux_lockdown = fake_usb_lockdown
    conn.lockdown = MagicMock()
    dm._connections[udid] = conn
    app_state.simulation_engines[udid] = MagicMock()
    app_state._primary_udid = udid

    disconnected = []

    async def fake_disconnect(u):
        disconnected.append(u)
        dm._connections.pop(u, None)

    monkeypatch.setattr(dm, "disconnect", fake_disconnect)

    deletes: list = []
    _patch_record_deletes(monkeypatch, deletes)

    client = TestClient(app)
    resp = client.post(f"/api/device/{udid}/forget")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "forgotten"
    assert body["udid"] == udid
    assert body["system_cleared"] is True
    assert body["local_cleared"] is True

    fake_usb_lockdown.unpair.assert_awaited_once()
    assert disconnected == [udid]
    assert udid not in app_state.simulation_engines
    assert app_state._primary_udid is None
    assert f"sys:{udid}" in deletes
    assert f"local:{udid}" in deletes
    assert udid in dm.sticky_user_denied
    sticky_file = tmp_path / "sticky_denied.json"
    assert udid in json.loads(sticky_file.read_text())


def test_forget_idempotent_for_unknown_udid(monkeypatch, tmp_path):
    """Forget for a udid with no connection and no records: still 200,
    sticky marked. Re-posting is also 200."""
    from main import app, app_state

    udid = "UDID-NEVER-SEEN"
    deletes: list = []
    _patch_record_deletes(monkeypatch, deletes)

    client = TestClient(app)
    resp1 = client.post(f"/api/device/{udid}/forget")
    resp2 = client.post(f"/api/device/{udid}/forget")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert udid in app_state.device_manager.sticky_user_denied


def test_forget_tears_down_wifi_tunnel(monkeypatch, tmp_path):
    """A udid with a registered TunnelRunner gets the per-udid tunnel
    teardown (runner.stop awaited, registry entry removed)."""
    from main import app, app_state
    import api.device as device_mod

    udid = "UDID-FORGET-WIFI"
    dm = app_state.device_manager

    conn = MagicMock()
    conn.connection_type = "Network"
    conn.usbmux_lockdown = None
    conn.lockdown = MagicMock()
    conn.lockdown.unpair = AsyncMock()
    dm._connections[udid] = conn

    async def fake_disconnect(u):
        dm._connections.pop(u, None)

    monkeypatch.setattr(dm, "disconnect", fake_disconnect)

    runner = MagicMock()
    runner.stop = AsyncMock()
    runner.is_running = MagicMock(return_value=True)
    device_mod._tunnels[udid] = runner

    deletes: list = []
    _patch_record_deletes(monkeypatch, deletes)

    client = TestClient(app)
    resp = client.post(f"/api/device/{udid}/forget")

    assert resp.status_code == 200
    runner.stop.assert_awaited_once()
    assert udid not in device_mod._tunnels


def test_forget_unpair_failure_does_not_block(monkeypatch, tmp_path):
    """lockdown.unpair raising must not abort the flow — records are still
    cleared and the response is still 200."""
    from main import app, app_state

    udid = "UDID-UNPAIR-FAIL"
    dm = app_state.device_manager

    bad_lockdown = MagicMock()
    bad_lockdown.unpair = AsyncMock(side_effect=RuntimeError("unpair exploded"))
    conn = MagicMock()
    conn.connection_type = "USB"
    conn.usbmux_lockdown = bad_lockdown
    conn.lockdown = MagicMock()
    dm._connections[udid] = conn

    async def fake_disconnect(u):
        dm._connections.pop(u, None)

    monkeypatch.setattr(dm, "disconnect", fake_disconnect)

    deletes: list = []
    _patch_record_deletes(monkeypatch, deletes)

    client = TestClient(app)
    resp = client.post(f"/api/device/{udid}/forget")

    assert resp.status_code == 200
    assert f"sys:{udid}" in deletes
    assert udid in dm.sticky_user_denied
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_forget_endpoint.py -v
```
Expected: 4 failures — 404/405 (route doesn't exist).

- [ ] **Step 3: Implement the endpoint**

In `backend/api/device.py`, after the `disconnect_device` route (ends ~line 1530) and BEFORE `/{udid}/info`, insert:

```python
@router.post("/{udid}/forget")
async def forget_device(udid: str):
    """Forget a device — Bluetooth-style. iPhone-side unpair (best-effort),
    session teardown, host pair-record removal, and persistent watchdog
    suppression via sticky_user_denied.

    Idempotent: forgetting an unknown or already-forgotten udid still
    returns 200 (record deletes are idempotent; set-add is idempotent).
    The user's path back is the Re-trust button (wifi/repair), which
    clears the sticky flag and re-triggers the iPhone Trust prompt.
    """
    from main import app_state
    from services.usbmux_pair_records import (
        acquire_pair_lock,
        delete_local_pair_record,
        delete_system_pair_record,
    )

    dm = _dm()
    lock = await acquire_pair_lock(udid)
    async with lock:
        # 1. iPhone-side unpair (best-effort) — needs the live session.
        #    Failure is fine: host-side cleanup below is sufficient for
        #    LocWarp's own behavior; the iPhone merely keeps a dangling
        #    host entry (today's status quo for every stale record).
        conn = dm._connections.get(udid)
        if conn is not None:
            unpair_lockdown = getattr(conn, "usbmux_lockdown", None) or conn.lockdown
            try:
                await unpair_lockdown.unpair()
                _tunnel_logger.info("Forget: iPhone-side unpair OK for %s", udid)
            except Exception:
                _tunnel_logger.debug(
                    "Forget: iPhone-side unpair failed for %s (continuing)",
                    udid, exc_info=True,
                )

        # 2. Session teardown. WiFi path mirrors wifi_tunnel_stop's
        #    per-udid sequence; USB path mirrors disconnect_device.
        async with _tunnels_lock:
            await _cleanup_wifi_connection_for(udid, caller="forget_device")
            await _tear_down_tunnel(udid, caller="forget_device")
        if udid in dm._connections:
            try:
                await dm.disconnect(udid)
            except Exception:
                _tunnel_logger.exception("Forget: disconnect failed for %s", udid)
        app_state.simulation_engines.pop(udid, None)
        if app_state._primary_udid == udid:
            app_state._primary_udid = next(iter(app_state.simulation_engines), None)

        # 3. Clear host pair records (both idempotent, never raise).
        system_cleared = await delete_system_pair_record(udid)
        local_cleared = delete_local_pair_record(udid)

        # 4. Suppress the watchdog's auto-re-pair (persisted across restarts).
        dm.mark_user_denied(udid)

    # 5. Notify the frontend.
    try:
        from api.websocket import broadcast
        await broadcast("device_disconnected", {
            "udid": udid, "udids": [udid], "reason": "forgotten",
        })
    except Exception:
        pass

    return {
        "status": "forgotten",
        "udid": udid,
        "system_cleared": system_cleared,
        "local_cleared": local_cleared,
    }
```

Lock-ordering note (verify, don't change): pair lock is OUTER, `_tunnels_lock` INNER. No existing code path takes `_tunnels_lock` then a pair lock, so there is no cycle. If you find one, STOP and report BLOCKED.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/test_device_forget_endpoint.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Full backend suite**

```bash
cd backend && .venv/bin/python -m pytest -q
```
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add backend/api/device.py backend/tests/test_device_forget_endpoint.py
git commit -m "feat(device): POST /{udid}/forget — unpair, teardown, clear records, sticky"
```

---

## Task 5: Frontend — chip menu item + confirm modal + wiring

**Files:**
- Modify: `frontend/src/services/api.ts` (~line 128, next to `disconnectDevice`)
- Modify: `frontend/src/i18n/strings.ts` (~line 132, after `device.chip_disconnect`)
- Modify: `frontend/src/components/DeviceChip.tsx`
- Modify: `frontend/src/components/DeviceChipRow.tsx`
- Modify: `frontend/src/App.tsx` (~line 1463, the `<DeviceChipRow` callsite)

- [ ] **Step 1: API helper**

In `frontend/src/services/api.ts`, after `disconnectDevice` (line 128):

```ts
export const forgetDevice = (udid: string) => request<any>('POST', `/api/device/${udid}/forget`)
```

- [ ] **Step 2: i18n keys**

In `frontend/src/i18n/strings.ts`, after `device.chip_disconnect` (line 132):

```ts
  'device.chip_forget': { zh: '忘記此裝置', en: 'Forget this device' },
  'device.forget_confirm_title': { zh: '忘記此裝置?', en: 'Forget this device?' },
  'device.forget_confirm_body': { zh: '將移除與此 iPhone 的配對紀錄並停止自動重連。之後要再使用,請在裝置列表按「重新信任」並於 iPhone 上重新按「信任」。', en: 'This removes the pairing records for this iPhone and stops auto-reconnect. To use it again, click "Re-trust" in the device list and tap Trust on the iPhone.' },
  'device.forget_ok': { zh: '忘記', en: 'Forget' },
  'device.forget_cancel': { zh: '取消', en: 'Cancel' },
```

- [ ] **Step 3: DeviceChip — prop, menu item, confirm modal**

In `frontend/src/components/DeviceChip.tsx`:

1. Add to `Props`: `onForget: () => void`
2. Add to the destructured params: `onForget`
3. Add state next to `menu`: `const [confirmForget, setConfirmForget] = useState(false)`
4. In the portal menu, after the disconnect `MenuItem`:

```tsx
          <MenuItem onClick={() => { setMenu(null); setConfirmForget(true) }}>{t('device.chip_forget')}</MenuItem>
```

5. After the menu portal (sibling), add the confirm modal portal. Match the menu's dark glassy styling:

```tsx
      {confirmForget && createPortal(
        <div
          onClick={() => setConfirmForget(false)}
          style={{
            position: 'fixed', inset: 0, zIndex: 10000,
            background: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: 'rgba(20,22,28,0.96)',
              backdropFilter: 'blur(18px) saturate(160%)',
              border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: 10, padding: 16, maxWidth: 320,
              color: '#eaeaea', fontSize: 13,
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>
              {t('device.forget_confirm_title')}
            </div>
            <div style={{ opacity: 0.8, lineHeight: 1.5, marginBottom: 14 }}>
              {t('device.forget_confirm_body')}
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" onClick={() => setConfirmForget(false)}>
                {t('device.forget_cancel')}
              </button>
              <button
                type="button"
                onClick={() => { setConfirmForget(false); onForget() }}
                style={{ background: '#c0392b', color: '#fff' }}
              >
                {t('device.forget_ok')}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
```

(Adapt button styling minimally to whatever base `<button>` styles the app ships; the destructive red on the confirm button is the one required accent.)

- [ ] **Step 4: DeviceChipRow — thread the prop**

In `frontend/src/components/DeviceChipRow.tsx`:
1. Add `onForget: (udid: string) => void` to its Props interface (next to `onDisconnect`).
2. Destructure it.
3. Pass to each chip alongside `onDisconnect` (line ~36):

```tsx
            onForget={() => onForget(d.udid)}
```

- [ ] **Step 5: App wiring**

In `frontend/src/App.tsx` at the `<DeviceChipRow` callsite (~line 1463): inspect the existing `onDisconnect={...}` handler to find the device-refresh call used after disconnect, then add `onForget` following the same shape:

```tsx
          onForget={async (udid) => {
            try {
              await forgetDevice(udid)
            } catch (e) {
              console.error('forget failed', e)
            }
            // same refresh the onDisconnect handler uses (e.g. device.refresh()/scan)
          }}
```

Import `forgetDevice` from `./services/api` alongside the existing imports. Copy the EXACT refresh invocation from the `onDisconnect` handler — do not invent a new one.

- [ ] **Step 6: Type-check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: 0 errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/services/api.ts frontend/src/i18n/strings.ts frontend/src/components/DeviceChip.tsx frontend/src/components/DeviceChipRow.tsx frontend/src/App.tsx
git commit -m "feat(device): Forget this device — chip menu item + confirm modal"
```

---

## Task 6: CLAUDE.md extension

**Files:**
- Modify: `CLAUDE.md` (the "USB pair records under SIP" section)

- [ ] **Step 1: Extend the section**

In `CLAUDE.md`, the section "USB pair records under SIP" lists the three wrapper functions. After the `autopair_with_recovery` bullet, add one bullet; and after the UserDeniedPairingError paragraph, append one sentence. Result of the edited region:

```markdown
- `autopair_with_recovery(udid)` — the shared "try autopair → on stale-cert
  clear records → retry once" dance used by both `wifi/repair` and
  `DeviceManager.connect()`.
- `POST /api/device/{udid}/forget` — the user-facing entry point: iPhone-side
  unpair (best-effort) → session teardown → both record deletes →
  `mark_user_denied`. Discovery polls use `autopair=False` so they never pop
  the Trust dialog.
```

and extend the final paragraph's last sentence so it reads:

```markdown
in-app Re-trust button (which clears the flag). The sticky set persists to
`~/.locwarp/sticky_denied.json` (`STICKY_DENIED_FILE`) so the choice — and
any in-app Forget — survives a LocWarp restart.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): forget endpoint + sticky persistence in SIP section"
```

---

## Task 7: Manual end-to-end (Ravi runs — merges with the pending stale-cert e2e)

- [ ] **Step 1: Rebuild + install** — `make build-install`, launch.
- [ ] **Step 2: Forget flow** — connected device → chip menu → 忘記此裝置 → confirm. Expect: chip disappears; NO Trust prompt re-appears while plugged (sticky + discovery autopair=False); dropdown row shows 需要信任 + 重新信任; `cat ~/.locwarp/sticky_denied.json` contains the udid.
- [ ] **Step 3: Restart persistence** — quit + relaunch LocWarp, cable still plugged. Expect: still silent, row still 需要信任.
- [ ] **Step 4: Re-trust recovery** — click 重新信任 → confirm → Trust prompt on iPhone → tap Trust → device reconnects, chip returns, `sticky_denied.json` no longer contains the udid.
- [ ] **Step 5: Variant C (Don't Trust), now verifiable** — re-forget, replug, click 重新信任 but tap **Don't Trust** on the prompt. Expect: one failure in the log, watchdog quiet, NO prompt loop from the discovery poll (this was the bug), chip stays 需要信任.
- [ ] **Step 6: Stale-cert auto-recovery (original Task 10 Variant A)** — with the device trusted+connected, on the iPhone run Settings → 一般 → 移轉或重置 iPhone → 重置 → 重置位置與隱私權, then replug USB. Expect: watchdog hits stale-cert → auto-clears → Trust prompt appears without any shell command → tap Trust → green.

---

## Self-Review

**Spec coverage:**

| Spec item | Plan task |
|---|---|
| Goal 1 (one action removes pairing) | Task 4 + 5 |
| Goal 2 (survives restart) | Task 1 (persistence) + e2e step 3 |
| Goal 3 (sticky actually works — no prompts from any path) | Task 3 (discovery fix) + e2e step 5 |
| Goal 4 (recovery = existing Re-trust) | Task 2 (clear persists) + e2e step 4 |
| 5-step endpoint flow | Task 4 (code matches spec steps 1-5) |
| `mark_user_denied`/`clear_user_denied` funnel | Task 1 defines; Tasks 2/4 consume; connect() switched in Task 1 |
| Spec tests 1-4 (forget) | Task 4 |
| Spec test 5 (autopair pin) | Task 3 |
| Spec tests 6-7 (persistence + corrupt tolerance) | Task 1 |
| Spec test 8 (repair clear persists) | Task 2 |
| Spec test 9 (tsc) | Task 5 step 6 |
| Spec e2e 10-13 | Task 7 (steps 2-5, plus step 6 folding in the older pending e2e) |
| Frontend i18n/API/chip/confirm | Task 5 |
| CLAUDE.md update | Task 6 |
| Non-goals (row-level forget, wizard, undo) | absent from plan ✓ |

**Placeholder scan:** none — every code step has complete code; the one
deliberately-deferred lookup (App.tsx refresh call) instructs the
implementer to copy the existing onDisconnect refresh verbatim rather
than inventing one.

**Type consistency:** `mark_user_denied`/`clear_user_denied` names match
across Tasks 1, 2, 4, 6; `STICKY_DENIED_FILE` constant name consistent in
config, device_manager import, and all three test fixtures; forget
response shape `{status, udid, system_cleared, local_cleared}` matches
between Task 4 code and tests; `onForget` prop signature `() => void` at
chip level vs `(udid: string) => void` at row level matches the existing
`onDisconnect` convention at each level.

**Test-isolation audit:** all three test files that can touch
`STICKY_DENIED_FILE` (pair_failure, repair_endpoint, forget_endpoint)
get an autouse monkeypatch fixture; forget tests restore the `app_state`
singleton via `clean_dm_state`.
