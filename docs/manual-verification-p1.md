# Manual Verification — Phase 1 (break-the-cycle) residual gates

The P1 refactor was **behavior-frozen** and is covered by the automated suite
(backend pytest + frontend vitest + a Playwright WS e2e) plus the import-linter
cycle gate. That suite proves all the **structure** and **frozen behavior**
against *mocked* I/O seams. The gates below are the residual risk the suite
**cannot** reach because CI replaces every real-I/O leaf (real iPhone USB/WiFi,
usbmuxd/SIP, a real WebSocket, the packaged build) with a fake.

> **Budget:** this is a **~25–35 minute targeted smoke, not a full re-test.**
> Do NOT manually re-verify DI singletons, event ordering/payloads, the
> subscriber migration, or the USB happy-path connect — the automated suite
> already proves those (a regression fails CI, not runtime). Spend the time on
> Gates 1–4 below; 5–8 are lower-ROI top-ups.

The two sharpest items (Gates 1 and 4) guard P1 commits whose **exact changed
lines have zero automated coverage**: `961e0ff` (WiFi-tunnel recovery, the only
fresh-DVT test forces `USB` and skips the WiFi branch) and `093428a` (the
single-WS-connection fix — the e2e predates it and never counts connections).

## Prerequisites

Same as [`manual-verification-p0.md`](manual-verification-p0.md): a real iPhone
(Developer Mode ON, Trusted, prefer iOS 17+), and for the WiFi gates the phone
+ Mac on the **same non-isolated WiFi**. Read the LAN IP / 6-digit PIN from the
desktop **Phone Control panel**. Dev (`./start.sh`) is fine for everything here
**except** Gate 7 (needs the packaged `.app`).

---

## Gate 1 — WiFi-tunnel-dead recovery (commit `961e0ff`) ⭐ highest priority

**Why manual:** `961e0ff` changed the Network branch to check
`is_running()` on the *returned* tunnel runner (single-object parity) during a
tunnel-restart race. `test_device_manager_fresh_dvt.py` explicitly forces
`connection_type='USB'` and skips the WiFi branch — so `device_manager.py`
lines ~1148–1158 have **no** coverage. Only a real WiFi tunnel killed mid-sim
exercises them.

1. Pair an iPhone **over a WiFi tunnel** (iOS 17+; let the tunnel come up).
2. Connect it in the desktop UI; **teleport** to confirm the DVT path is live.
3. Start a moving **navigate / route / loop**.
4. While it runs, **kill the tunnel**: toggle the Mac's Wi-Fi off→on, or drop
   the phone's Wi-Fi, mid-simulation.
5. Watch BOTH the backend log (dev: the `start.sh` terminal) AND the desktop UI.

**Observe (backend):** the recovery either re-acquires a fresh DVT provider and
the sim resumes, **or** raises a clean `REASON_TUNNEL_DEAD` / connection-lost
banner — **without hanging** and without an unhandled traceback.

**Observe (UI — the three-state wiring, commit `8bc77cf`):** the moment the
tunnel drops, an **amber "重新連線中… / reconnecting…" banner** appears
(top-center) for the retry window. Then either: on success → the amber banner
clears and a **"WiFi Tunnel 已恢復 / Wi-Fi tunnel restored" toast** flashes; or
on terminal loss (all retries fail) → the amber banner is replaced by the
**red terminal banner**. The amber and red banners must never show at once.

- ✅ **PASS:** clean recovery or a clean tunnel-dead banner; no hang, no
  unhandled exception; AND the UI shows amber-reconnecting → (restored toast |
  red terminal banner) with correct transitions.
- ❌ **FAIL:** the recovery hangs / throws on the runner / the backend dies; OR
  the amber banner never appears, gets stuck after recovery, the restored toast
  never fires, or both banners show simultaneously.

---

## Gate 2 — DDI-mounted event branch + live wiring ⭐

**Why manual:** `_ensure_personalized_ddi_mounted` / `_ensure_classic_ddi_mounted`
pick **which** of `ddi_mounting` / `ddi_mounted` / `ddi_not_mounted` to publish;
no test drives those methods (the event tests call `publish()` by hand). It also
proves the **production wiring is live** — that `self._events` is a real
`WsEventPublisher` (non-`None`) so the event actually reaches the UI.

1. Take an iPhone with **no Developer Disk Image mounted** (a fresh phone, or one
   not recently used for development). Connect it.
2. Watch the desktop UI for the **`ddi_not_mounted`** banner / hint (zh copy).
3. Then connect an iPhone that **already has DDI mounted** (used recently for a
   sim).
4. Confirm it reports **`ddi_mounted`** (no not-mounted banner).

**Observe:** the correct DDI state surfaces in the UI for each phone — proving
both the branch selection and that the injected `EventPublisher` reaches the WS.

- ✅ **PASS:** not-mounted phone → not-mounted banner; mounted phone → no banner.
  The UI reflects DDI state (events are wired through to the renderer).
- ❌ **FAIL:** wrong/missing banner, or DDI state never appears (events not
  reaching the UI → `self._events` likely `None` in production).

---

## Gate 3 — `forget` actually clears the SIP pair record → re-Trust ⭐

**Why manual:** `test_usbmux_pair_records.py` mocks `PlistMuxConnection` and
`test_device_forget_endpoint.py` patches both record-delete functions to
list-appending fakes — so the **real usbmuxd `DeletePairRecord` wire protocol**
and the SIP-exempt delete of `/var/db/lockdown/<udid>.plist` are never hit. The
pair-lock / `_tunnels_lock` ordering (the reason `forget` was *not* lifted into
`DeviceService`) is also untested against real locks.

1. Connect + Trust a real iPhone.
2. In the UI, **Forget this device** (confirm the modal).
3. **Reconnect** the same iPhone.

**Observe:** the iPhone **re-prompts the iOS Trust dialog** on reconnect (proving
the on-disk SIP-protected pair record was genuinely cleared), and the forget
itself did not hang/deadlock.

- ✅ **PASS:** reconnect pops a fresh **Trust** dialog; no hang during forget.
- ❌ **FAIL:** reconnect trusts silently (pair record was NOT cleared), or forget
  hangs/deadlocks (pair-lock vs `_tunnels_lock` ordering).

---

## Gate 4 — exactly one real WebSocket connection (commit `093428a`)

**Why manual:** `093428a` fixed App opening a **second** WS connection. The e2e
(`ws.spec.ts`) was authored *before* the fix, broadcasts to all intercepted
routes, and asserts marker/banner visibility — it passes identically with 1 **or**
2 connections. (A vitest now also guards the construction count, but only a real
backend proves the steady-state single connection end-to-end.)

1. Open LocWarp against the **real backend** (`./start.sh`).
2. Browser **DevTools → Network → WS**.

**Observe:** exactly **one** `/ws/status` connection in steady state. (A brief
dev StrictMode double-mount that immediately closes one is fine — count the
*steady* state.)

- ✅ **PASS:** one live `/ws/status` socket in steady state.
- ❌ **FAIL:** two (or more) persistent `/ws/status` sockets — the double-connect
  regressed.

---

## Gate 5 — real-WebSocket reconnect survives a backend restart

**Why manual:** `useWebSocket.ts` `onclose → scheduleReconnect` (3s→30s ×1.5
backoff) has no unit test; the e2e uses a pure `routeWebSocket` mock that never
closes/reopens. (Pre-dates P1 — not a P1 regression, just never covered.)

1. With LocWarp connected to the real backend, **kill the backend** (Ctrl-C the
   `start.sh` terminal) mid-session.
2. Confirm the UI shows disconnected, then **restart** the backend.
3. After it reconnects, start a sim (or teleport) and confirm a fresh
   `position_update` still drives the map marker.

- ✅ **PASS:** the client reconnects on its own and live events resume driving
  the map.
- ❌ **FAIL:** no reconnect, or events stop arriving after the reconnect
  (subscriptions lost).

---

## Gate 6 — "Don't Trust" sticky block survives a restart

**Why manual:** the real pairing handshake + the actual
`UserDeniedPairingError` type + the `sticky_denied.json` persistence only have
meaning against a real iPhone raising the real exception (CI uses synthetic
exceptions + a MagicMock dm).

1. Connect an iPhone and tap **Don't Trust** on the iOS dialog.
2. Confirm LocWarp does **not** auto-reconnect it (sticky block).
3. **Quit and relaunch** LocWarp; confirm the device is still blocked (the
   sticky choice persisted via `~/.locwarp/sticky_denied.json`).
4. Use the in-app **Re-trust** button → confirm it clears the block and re-pairs.

- ✅ **PASS:** denied device stays blocked across a restart; Re-trust clears it.
- ❌ **FAIL:** the block is lost on restart, or the device auto-reconnects despite
  Don't Trust.

---

## Gate 7 — packaged build defaults to strict CSP

**Why manual:** `test_csp_header.py` monkeypatches `CSP_MODE='strict'` — it proves
the branch, not that the **packaged launcher exports it**. P1's deletion of the
parallel `create_app` was pure dead-code removal (byte-identical CSP block), so
it did not change this wiring — but strict-by-default in the packaged build was
never verified by CI. (Extends P0 Gate 2.)

1. Build + launch the **packaged** app with a plain **double-click** (NOT a
   `LOCWARP_CSP_MODE=strict` override): `/Applications/LocWarp.app`.
2. Hit a non-`/phone` endpoint and inspect the response headers (e.g. open
   DevTools on the main window, or `curl -I http://localhost:8777/` if reachable).

**Observe:** the main-app `Content-Security-Policy` is the **strict** one — no
`'unsafe-inline'` in `script-src`.

- ✅ **PASS:** strict CSP present by default on a plain double-click launch.
- ❌ **FAIL:** the looser dev CSP (`'unsafe-inline'` in `script-src`) ships in the
  packaged app without an explicit override.

---

## Gate 8 — engine coordinate push through `LocationServiceDevicePort` (lower ROI)

**Why manual:** `d004ee8` routes engine pushes through the injected
`DevicePort`; `test_engine_device_push.py` substitutes a `FakeLocationService`
whose `.set` just appends to a list — the real `pymobiledevice3` DTX
`simulate-location` call is never issued. USB happy-path is the **best-covered**
lifecycle path, so this is the last thing to spend time on.

1. USB-connect a device. **Teleport** → confirm the pin jumps.
2. Run a **navigate / loop**; confirm `current_position` is preserved and the dot
   actually **moves** smoothly.

- ✅ **PASS:** teleport + a moving sim both drive the phone via the real DTX path.
- ❌ **FAIL:** teleport works but a moving sim never updates, or `current_position`
  resets between mode switches.
