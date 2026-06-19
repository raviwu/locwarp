# Manual Verification — Phase 0 deferred gates

Three things the automated suite (and CI) **cannot** cover because they need real
hardware, a packaged macOS build, or a second device on the LAN. Run these by hand
after a Phase-0 change before treating it as shipped.

## Prerequisites

- A real **iPhone**: Developer Mode ON (Settings → Privacy & Security → Developer
  Mode), unlocked, **Trusted** to this Mac (tap Trust + passcode on first USB
  connect). Prefer **iOS 17+** (exercises the elevated-helper tunnel path).
- For the `/phone` test: the **phone and the Mac on the SAME WiFi** (not a guest /
  AP-isolated SSID), and the **phone has working internet** (Leaflet comes from
  `unpkg.com`, tiles from `tile.openstreetmap.org` over the public internet — the LAN
  only serves the `/phone` HTML + the API).
- Where to read the **LAN IP + 6-digit PIN**: open the **Phone Control panel** in the
  desktop UI — it calls `/api/phone/info` (localhost-only) and shows the LAN URL(s)
  and the PIN (click-to-copy).

## How to run

**Dev** (Gate 1 only — dev uses `sudo`, not the GUI elevation):

```bash
./start.sh          # or: make start
# → sudo password prompt (tunnel helper), backend on :8777, Vite on :5173, opens the browser
```

**Packaged** (REQUIRED for Gate 2 and Gate 3 — the osascript elevation only fires when
`app.isPackaged && darwin`; the strict main-app CSP only applies in the packaged build):

```bash
./build-installer-mac.sh     # or: make build   → frontend/release/mac-arm64/LocWarp.app + a .dmg
make install                 # copies LocWarp.app into /Applications
# Launch /Applications/LocWarp.app. To force the production CSP posture:
LOCWARP_CSP_MODE=strict open -a /Applications/LocWarp.app
```

---

## Gate 1 — USB-unplug DVT retry never re-crashes (Task 10: the `device_manager.py:1155` NameError fix)

**Why manual:** the unit test (`test_device_manager_fresh_dvt.py`) proves the retry
logic under a FakeClock, but it mocks `DvtProvider` — it cannot reproduce a real
`pymobiledevice3` instrument-channel drop from a physical iPhone. (Dev or packaged both
work for this gate.)

1. Plug a real iPhone in over USB → unlock → Trust → confirm Developer Mode is ON.
2. Launch LocWarp; approve the `sudo`/admin prompt so the tunnel helper comes up.
3. Wait for the iPhone to appear and connect in the desktop UI.
4. **Teleport** to any coordinate (e.g. Taipei `25.0375, 121.5637`) and confirm Apple
   Maps on the phone jumps to the pin (proves DVT is live).
5. Start a moving **navigate/route**; while it runs, gently **unseat and immediately
   re-seat the USB cable** (or lock/unlock the phone) to force the DVT channel to drop
   mid-operation.
6. **Watch the backend log** (dev: the `start.sh` terminal; packaged: Console.app
   filtered to `locwarp`, plus `/tmp/locwarp-helper-stderr.log`).
7. Repeat the unplug/replug **2–3 times** to hit transient-failure-then-success.

**Observe:** on a transient drop → a retry loop then `DVT provider re-acquired for
<udid>`, and the sim resumes / the phone keeps updating. On a permanent loss (cable left
out past ~15s) → a clean `DeviceLostError` (reason `lockdown_dead`) connection-lost
banner. **Critically: NO `NameError: name 'loop' is not defined` traceback anywhere.**

- ✅ **PASS:** every transient disturbance recovers (`DVT provider re-acquired`) and the
  sim continues; a permanent unplug yields a clean `DeviceLostError` banner — with
  **zero** `NameError` tracebacks across all repeats.
- ❌ **FAIL:** any `NameError: name 'loop' is not defined`, or the retry never recovers
  from a recoverable transient drop, or the backend process dies on the drop.

---

## Gate 2 — packaged CSP lets the real-phone `/phone` Leaflet/OSM map render (Task 13/14)

**Why manual:** the strict main-app CSP blocks `unpkg.com` + `*.tile.openstreetmap.org`;
only the route-scoped `/phone` CSP whitelists them. Whether the map actually renders
depends on the phone's browser CSP engine, the public-internet fetch, and the LAN path —
none reproducible in CI (no real phone, no second device on the WiFi). This is the
regression the whole-branch review caught.

1. **Build + launch the PACKAGED app**, ideally `LOCWARP_CSP_MODE=strict open -a
   /Applications/LocWarp.app`. Approve the admin prompt.
2. Put the phone on the **same WiFi** as the Mac (with internet).
3. In the desktop **Phone Control panel**, read the **LAN URL** (pick the wifi/primary
   one) and the **6-digit PIN**.
4. On the phone's browser, open `http://<lan-ip>:8777/phone`. (If it won't load at all,
   that's firewall / WiFi-isolation — not CSP.)
5. At the PIN gate, **enter the PIN** from the desktop and tap the button.
6. Watch the **Leaflet map**; pan/zoom to force tile fetches. Optionally remote-inspect
   via Safari Web Inspector from the Mac and check the Console.

**Observe:** real OSM **map tiles** render (streets/landmasses), **not** a blank grey
`#1a1d22`; the Leaflet `+/−` control and "© OpenStreetMap" attribution appear; the
console shows **no** `Refused to load … Content Security Policy` errors for `unpkg.com`
(script/style) or `tile.openstreetmap.org` (img).

- ✅ **PASS:** tiles render, Leaflet UI + OSM attribution show, the PIN unlocks the page,
  and the console has **zero** CSP violations against `unpkg.com` / `*.tile.openstreetmap.org`.
- ❌ **FAIL:** blank grey map (tiles blocked), missing Leaflet UI (script/style blocked),
  any CSP "Refused to load" for those origins, or the page can't be reached at the LAN IP.

---

## Gate 3 — packaged-app osascript admin elevation still works (Task 15: AppleScript escaping)

**Why manual:** the elevation path only runs when `app.isPackaged && darwin`; it pops the
native macOS admin password dialog (a macOS-owned modal automation can't drive). Dev mode
uses `sudo`, so only the installed/packaged app exercises this.

1. Build + install the packaged app (`build-installer-mac.sh` → `make install`).
2. **Clear any live helper:** `make kill`; confirm `/tmp/locwarp-helper.sock` and
   `/tmp/locwarp-helper.status` are gone (otherwise a reused helper suppresses the prompt).
3. Quit any running LocWarp; **double-click** `/Applications/LocWarp.app` fresh.
4. Watch for the macOS authentication dialog — text should read: **"LocWarp needs
   administrator access to communicate with iOS 17+ devices over USB."**
5. Enter your admin password / Touch ID and approve.
6. Confirm the helper came up: `/tmp/locwarp-helper.status` contains `READY`,
   `/tmp/locwarp-helper.sock` exists; `tail /tmp/locwarp-helper-stderr.log` shows a clean
   start (no AppleScript / path errors).
7. Connect an **iOS 17+** iPhone over USB and confirm it connects + a teleport moves it
   (iOS 17+ tunnels route through the elevated helper).

**Observe:** exactly **one** native macOS "administrator" dialog at launch with the
correct LocWarp text; after approval `status` flips to `READY` and the helper logs show a
normally-parsed command line (the app path intact even after escaping). **No** AppleScript
"syntax error" dialog and **no** `sh: …: No such file or directory` in the helper stderr.

- ✅ **PASS:** the prompt appears with the correct message, accepts the password, the
  helper reaches `READY`, and an iOS 17+ device connects + teleports — with no AppleScript
  syntax error and no broken-path errors in the helper logs.
- ❌ **FAIL:** no prompt (elevation never triggered), an AppleScript syntax-error dialog,
  a mangled/escaped path in the helper log, `status` never reaches `READY` within ~30s, or
  iOS 17+ tunnel setup fails for lack of root.
