# Tunnel in-use guard (B′) — Implementation Plan

> **For agentic workers:** danger-zone tunnel/recovery code → **test-first**, one task at a time. Full backend
> `pytest` stays green after every task. No external HTTP/WS/helper-protocol change except the ONE new
> documented response (a refused cross-transport WiFi open → clean **409**, replacing today's misleading 500).

**Goal:** Stop `open_tunnel_with_reconcile` from tearing down a healthy, in-use connection when a WiFi tunnel
is opened over an already-connected device. Genuinely-stale tunnels still self-heal (commit `cd12916`).

**Approach (B′, approved 2026-06-23):** inject an `is_udid_in_use` predicate; on the helper's `-32003`
("tunnel already exists"), if the open is a **WiFi** open AND the udid is an active backend connection, do
**not** close+retry — raise a distinct `TunnelBusyError` the handler surfaces as a clean 409. Otherwise
(USB open, or not-in-use) keep today's close+retry stale-heal.

**Why WiFi-only + in-use-only:** the helper is one-tunnel-per-udid, so close+retry destroys whatever exists.
The dangerous case is *WiFi-open destroys a live USB tunnel* (DVT → "No route to host" → ~27s reconnect).
USB-open-takes-over (plug-in while on WiFi) stays close+retry — USB is the preferred transport and the usbmux
watchdog already skips already-connected udids, so that path is both wanted and rarely hit. A not-in-use
`-32003` is a genuine stale leftover → keep self-healing.

## Global Constraints
- Backend full `pytest` green after EVERY task (baseline **906**). `lint-imports` stays **7 kept, 0 broken**
  (no new contract; the injected predicate is a plain `Callable`, composition-root wired — `core/wifi_tunnel.py`
  gains no new outward import; it already imports `services.tunnel_helper_client`, an existing un-forbidden edge).
- Behavior freeze EXCEPT: a WiFi open refused because the device is connected on another transport now returns
  **409 `{code:"tunnel_busy_other_transport"}`** instead of the prior generic 500 `tunnel_spawn_failed`.
- Default predicate is `lambda _udid: False` → absent injection preserves the exact prior close+retry behavior
  (so existing `test_tunnel_reconcile.py` cases stay green untouched).

---

### Task 1: `TunnelBusyError` + char test for the guard (test-first)

**Files:** Modify `backend/services/tunnel_helper_client.py`; modify `backend/tests/test_tunnel_reconcile.py`.

- [ ] **Step 1 — add the error** (next to `HelperError`, ~line 34):
```python
class TunnelBusyError(Exception):
    """A tunnel open was refused because the udid already has a healthy, in-use
    connection on another transport — closing it (one-tunnel-per-udid helper)
    would destroy a live connection, so we refuse instead of close+retry."""

    def __init__(self, udid: str, message: str) -> None:
        super().__init__(f"tunnel busy for {udid}: {message}")
        self.udid = udid
        self.message = message
```

- [ ] **Step 2 — failing tests.** Append to `test_tunnel_reconcile.py` (the `_FakeHelper` already records
  `close_calls` / `open_wifi_calls` / `open_usb_calls`; `first_open_error_code=-32003` makes the first open
  raise). Use `wt.set_in_use_predicate(...)` + reset it in `finally` alongside `set_helper_client(None)`:
```python
@pytest.mark.asyncio
async def test_wifi_open_refuses_when_udid_in_use_instead_of_closing():
    from services.tunnel_helper_client import TunnelBusyError
    fake = _FakeHelper(first_open_error_code=-32003)
    wt.set_helper_client(fake)
    wt.set_in_use_predicate(lambda udid: udid == "UDID-USB")
    try:
        with pytest.raises(TunnelBusyError):
            await wt.open_tunnel_with_reconcile("open_wifi_tunnel", "UDID-USB", ip="1.2.3.4", port=49152)
    finally:
        wt.set_in_use_predicate(lambda _u: False)
        wt.set_helper_client(None)
    assert fake.close_calls == []            # the live tunnel was NOT torn down
    assert len(fake.open_wifi_calls) == 1    # opened once (got -32003), did NOT retry

@pytest.mark.asyncio
async def test_wifi_open_still_self_heals_when_not_in_use():
    fake = _FakeHelper(first_open_error_code=-32003)
    wt.set_helper_client(fake)
    wt.set_in_use_predicate(lambda _u: False)  # explicit: not in use
    try:
        info = await wt.open_tunnel_with_reconcile("open_wifi_tunnel", "UDID-STALE", ip="1.2.3.4", port=49152)
    finally:
        wt.set_in_use_predicate(lambda _u: False)
        wt.set_helper_client(None)
    assert fake.close_calls == ["UDID-STALE"]   # stale tunnel closed
    assert len(fake.open_wifi_calls) == 2       # retried once
    assert info["rsd_address"] == "fd00::2"

@pytest.mark.asyncio
async def test_usb_open_still_self_heals_even_when_in_use():
    # Guard is WiFi-only: a USB open over a stale tunnel keeps self-healing.
    fake = _FakeHelper(first_open_error_code=-32003)
    wt.set_helper_client(fake)
    wt.set_in_use_predicate(lambda _u: True)
    try:
        info = await wt.open_tunnel_with_reconcile("open_usb_tunnel", "UDID-X")
    finally:
        wt.set_in_use_predicate(lambda _u: False)
        wt.set_helper_client(None)
    assert fake.close_calls == ["UDID-X"]
    assert fake.open_usb_calls == 2
    assert info["rsd_address"] == "fd00::1"
```

- [ ] **Step 3 — run, expect FAIL:** `cd backend && .venv/bin/python -m pytest tests/test_tunnel_reconcile.py -q`
  → the two new in-use/regression tests fail (no `set_in_use_predicate`, no guard yet). Commit after Task 2.

---

### Task 2: predicate + guard in `core/wifi_tunnel.py`

**Files:** Modify `backend/core/wifi_tunnel.py`.

- [ ] **Step 1 — imports:** add `from typing import Callable` (Optional already imported); add `TunnelBusyError`
  to the existing `from services.tunnel_helper_client import TunnelHelperClient, HelperError` line.
- [ ] **Step 2 — module state + setter** (next to `_helper_client` / `set_helper_client`):
```python
# Injected at the composition root: "does this udid have a live, healthy backend
# connection right now?" Defaults to always-False so absent injection preserves the
# prior close+retry stale-heal behavior.
_in_use_predicate: Callable[[str], bool] = lambda _udid: False


def set_in_use_predicate(pred: Callable[[str], bool]) -> None:
    global _in_use_predicate
    _in_use_predicate = pred
```
- [ ] **Step 3 — guard inside `open_tunnel_with_reconcile`**, in the `except HelperError as exc:` branch,
  AFTER the `code != -32003: raise` line and BEFORE the existing close+retry log/close:
```python
        # Never tear down a healthy in-use connection just to open a WiFi tunnel
        # over it. The helper is one-tunnel-per-udid, so close+retry would destroy
        # a live USB connection; if the WiFi open then failed the device would be
        # left with NO tunnel (DVT "No route to host" -> ~27s reconnect). Only a
        # GENUINELY stale tunnel (not in use) is auto-healed. Guard is WiFi-only:
        # a USB open is the preferred-transport takeover and stays close+retry.
        if method == "open_wifi_tunnel" and _in_use_predicate(udid):
            raise TunnelBusyError(
                udid,
                "device is connected on another transport; disconnect to switch",
            ) from exc
```
- [ ] **Step 4 — run Task 1 tests, expect PASS** + full suite green:
  `cd backend && .venv/bin/python -m pytest tests/test_tunnel_reconcile.py -q && .venv/bin/python -m pytest -q`.
  Commit: `fix(tunnel): refuse to tear down an in-use connection on a WiFi -32003 (don't thrash the USB tunnel)`.

---

### Task 3: handler maps `TunnelBusyError` → clean 409

**Files:** Modify `backend/api/device.py`.

- [ ] **Step 1:** ensure `TunnelBusyError` is imported (the module already imports `HelperError` from
  `services.tunnel_helper_client` — add `TunnelBusyError` there).
- [ ] **Step 2:** in `wifi_tunnel_start`'s candidate loop (`api/device.py:~1045`), add an `except TunnelBusyError`
  BEFORE the generic `except Exception:` that bails with a clean 409 (don't try other candidates — this exact
  udid is a live device):
```python
            except TunnelBusyError as e:
                _tunnel_logger.info(
                    "WiFi tunnel refused for udid=%s: already connected on another "
                    "transport; not tearing it down", cand,
                )
                raise HTTPException(
                    status_code=409,
                    detail={"code": "tunnel_busy_other_transport",
                            "message": "裝置已透過 USB 連線,請先中斷再切換 WiFi"},
                ) from e
```
- [ ] **Step 3 — test the mapping.** Add to an existing device-API test module (or a new
  `tests/test_wifi_tunnel_busy_409.py`): with `set_in_use_predicate` forcing in-use + a fake helper that raises
  `-32003`, POST `/api/device/wifi/tunnel/start` → assert **409** + `code == "tunnel_busy_other_transport"`.
  (Reuse the app/client fixture + `core.wifi_tunnel.set_helper_client` injection used by existing device tests.)
- [ ] **Step 4:** full suite green. Commit: `fix(tunnel): surface an in-use WiFi-open refusal as 409, not a misleading 500`.

---

### Task 4: wire the predicate at the composition root

**Files:** Modify `backend/core/device_manager.py`; modify `backend/main.py`.

- [ ] **Step 1 — public accessor** on `DeviceManager` (next to other small query methods):
```python
    def is_connected(self, udid: str) -> bool:
        """True if a live connection (any transport) exists for udid."""
        return udid in self._connections
```
- [ ] **Step 2 — wire** in `main.py` where `set_helper_client` is called (`:835-836`), using the same
  `DeviceManager` instance the container holds (confirm the in-scope handle — `dm` / `container.device_manager`):
```python
        from core.wifi_tunnel import set_helper_client, set_in_use_predicate
        set_helper_client(helper_client)
        set_in_use_predicate(lambda udid: device_manager.is_connected(udid))
```
- [ ] **Step 3:** full suite green; `lint-imports` 7 kept/0 broken. Commit:
  `fix(tunnel): wire the in-use predicate (DeviceManager.is_connected) at the composition root`.

---

### Final: verify + finish
- Full backend `pytest` green (906 + the new tests); `lint-imports` 7 kept/0 broken; WS/HTTP payloads unchanged
  except the documented 409.
- Adversarial review of the diff (refute-verified): does the guard ever block `device_manager`'s OWN legitimate
  USB (re)connect? (It must not — dm adds to `_connections` only AFTER a successful open, and reconnect
  disconnects first; the guard is WiFi-only regardless.) Does a genuine stale tunnel still self-heal? Is there a
  lock/ordering hazard reading `_connections` from the predicate?
- **Manual hardware smoke (the real gate):** USB-connect a route-capable iPhone, trigger a WiFi connect for the
  same device while still on USB → expect a clean "disconnect to switch" 409 and the **USB route keeps running**
  (no "No route to host", no ~27s reconnect). Then unplug → WiFi connect succeeds (no -32003, since USB is gone).
- `finishing-a-development-branch`: this is direct-to-main (personal repo); commit per task, then it's done.
- **Out of scope (noted):** seamless try-then-restore (A′) and any helper `list_tunnels` type/param extension.
