# Security Gate + Repo-Reference Cleanup + Reliability Hardening — Design

**Date:** 2026-06-28
**Status:** Approved (design) — pending implementation plan
**Scope:** Four independent workstreams, shippable as separate commits:
A. Close the LAN device-control auth hole (security)
B. Fix the cross-platform repo references in app + docs (distribution)
C. `DeviceManager.connect()` same-udid race + discovery fd-leak (reliability)
D. Quick wins (correctness / CI safety / perf)

Derived from the 2026-06-27 multi-dimension audit (44 findings, 8 dimensions). The
audit's full backlog is **not** in scope here — the deferred perf "bigger wins"
(store-write fast-path, engine generator, geo KDTree, Library memoize) were
re-verified as correctly dropped and stay dropped.

---

## Context

LocWarp is a **fork** of `keezxc1223/locwarp` (configured as git `upstream`):

| Repo | Role | Latest | Installer |
|------|------|--------|-----------|
| `keezxc1223/locwarp` (upstream) | Windows-first original, actively shipping | v0.2.187 | `LocWarp.Setup.*.exe` |
| `raviwu/locwarp` (origin, this fork) | adds the macOS line + the engineering programs | v0.3.0 | `LocWarp-*-arm64.dmg` |

The fork's `release.yml` is **macOS-only** (single `macos:` job → `*.dmg`). This
cross-platform split is the reason the repo references are inconsistent, and it
constrains the #2 fix (we cannot point Windows users at a repo with no `.exe`).

Architecture invariants that constrain the work (from `CLAUDE.md`):
- Clean-arch rings; **`api/*` may not import another `api/*`** (import-linter
  contract). → shared web helpers must live in `domain/` (pure) or at the
  composition root (`main.py`/`bootstrap/`), never as an api→api edge.
- Behavior / API freeze: no external HTTP/WS contract change **except** the new
  rejection of illegitimate callers. Full pytest + vitest green after every commit.
- Danger-zone-test-first: `device_manager`, `simulation_engine`, movers,
  `api/location`, `phone_control` have no direct tests — write characterization
  tests **before** editing them.

---

## Workstream A — Close the LAN device-control hole (security)

### Threat model

`API_HOST = "0.0.0.0"` (`config.py:211`) is **intentional** — the `/phone` control
page is served to a real iPhone over WiFi. The bind is not the problem; the
missing authorization is. Today only `/api/phone/*` is gated (token via
`_check_token`, or `_is_localhost` for the desktop-only sub-endpoints). The entire
main API and the joystick WebSocket are open:

- `POST /api/location/teleport` etc. — only `Depends(get_engine_registry)`, no auth
  (`api/location.py:117`).
- `POST /api/route/*`, `POST /api/device/{udid}/forget` — no auth.
- `POST /api/system/shutdown` — bare `os.kill(SIGTERM)`, no guard (`api/system.py:88`).
- `GET /api/system/info` — leaks udid / iOS version, no guard.
- `WS /ws/status` — unconditional `await ws.accept()` then accepts `joystick_input`
  (`api/websocket.py:31`).

The in-code comment at `config.py:209-210` ("LAN exposure is closed by the
phone-control PIN/token gate ... and the CORS allowlist") is **false** for the main
API — that false assertion is how the gap survived. This workstream makes it true.

**Two distinct attackers:**
1. **LAN peer** (other host on the same WiFi) — passive bystander; the
   high-severity case. Closed by a loopback gate.
2. **Drive-by web page** in the user's *own* browser on the same machine — its
   requests originate from loopback, so a loopback gate does **not** stop it.
   - HTTP JSON endpoints: already protected — a JSON body forces a CORS preflight,
     and `CORS_ORIGINS` (`config.py:217`) does not include a remote origin, so the
     preflight fails and the request is never sent.
   - `WS /ws/status`: **not** subject to CORS → needs an explicit `Origin` check.

### Design input: the desktop UI is always loopback

`frontend/src/adapters/config.ts:3` hardcodes the backend origin to
`127.0.0.1:8777`. The whole desktop UI + its WebSocket are loopback clients. The
iPhone uses the separate `/api/phone/*` surface. Therefore a **loopback-only** gate
on the main API breaks no legitimate caller — simpler and safer than
"loopback-OR-token". (Decision confirmed with the maintainer.)

### A1 — HTTP chokepoint (fail-closed)

A new `@app.middleware("http")` in `main.py`, beside the existing CSP middleware
(composition root — no api→api edge):

```
ALLOW if client is loopback (127.0.0.0/8, ::1)
ALLOW if request.url.path startswith "/api/phone" OR == "/phone"   # token-gated LAN surface
else  -> 403 JSONResponse {"code": "lan_forbidden"}
```

- **Fail-closed**: any *future* endpoint is auto-protected unless explicitly
  allowlisted — prevents the "forgot to gate a new route" recurrence.
- `request.client.host` is trustworthy: uvicorn binds directly, no reverse proxy,
  so no `X-Forwarded-For` spoofing surface.
- The phone desktop-only sub-endpoints keep their own `_is_localhost` 403 →
  defense in depth, no behavior change.
- Loopback predicate: broaden the existing `_is_localhost` notion to the full
  `127.0.0.0/8` block + `::1`. Implement inline in the middleware (do **not**
  refactor `phone_control._is_localhost` — avoids the api→api question; optional
  later: promote a pure `is_loopback(host)` to `domain/`).

### A2 — WebSocket guard

In `api/websocket.py`, before `await ws.accept()`:

- **Core (guaranteed-safe, ships now):** reject if `ws.client.host` is not
  loopback → `await ws.close(code=1008)`. Closes the LAN-peer joystick takeover.
- **Origin enhancement (drive-by webpage):** additionally reject when an `Origin`
  header is present **and** is a remote `http(s)` origin not in the allowlist.
  - **Risk:** the production Electron renderer loads via `file://`, whose WS
    `Origin` is `file://`/`null` — **not** in `CORS_ORIGINS`. A naive allowlist
    would break the shipped app.
  - **Gate:** the Origin check is implemented only after the implementation plan
    **empirically confirms** the Electron renderer's actual `Origin` (inspect
    `frontend/electron/main.js` window-load + a real-app capture). Rule shape:
    *allow if Origin is absent / `null` / `file://` / in `CORS_ORIGINS`; reject
    otherwise.* If confirmation is impractical in this pass, ship A2-core
    (loopback-only) and track the Origin check as a follow-up — do not guess the
    allowlist.

### A3 — CORS hardening

`allow_credentials=True → False` (`main.py:1143`). No cookies / credentialed auth
exist; with the loopback gate + JSON-preflight protection, credentials are
unneeded. Low risk (the dev `:5173` fetch flow uses no cookies).

### A4 — Fix the false comment

Rewrite `config.py:207-210` to state the real model: LAN exposure on the main API
is closed by the loopback middleware (A1) + WS guard (A2); `/api/phone/*` remains
the only LAN-reachable surface, gated by its PIN/token.

### A5 — Tests first (danger zone)

Characterization tests **before** the edits:
- non-loopback HTTP (mutating + `GET /api/system/info`) → 403
- loopback HTTP → unaffected (200/existing behavior)
- non-loopback request to `/api/phone/*` and `/phone` → **still reaches** the
  router (its own token/`_is_localhost` gate then applies)
- WS from non-loopback client → closed (1008)
- WS from loopback → accepted (and, if A2-Origin ships: bad-Origin → closed,
  `file://`/null/allowlisted Origin → accepted)

---

## Workstream B — Repo references (distribution) + UA quick-win

**Goal:** the app's *own* surfaces (which ship inside the mac DMG) point at the
fork `raviwu/locwarp`; the Windows-only surfaces stay at upstream `keezxc1223`.

### B1 — One shared constant

Introduce `REPO_SLUG = 'raviwu/locwarp'` (frontend) as the single source. Route
through it:
- `UpdateChecker.tsx:5` — **keep** `raviwu` (correct for DMG users), via the constant.
- `ControlPanel.tsx:1061` + `:1075` (About link + display text) → `raviwu`.

### B2 — Backend UA (folds in quick-win)

`geo_extras.py:142`: `"LocWarp/0.2.77 (https://github.com/keezxc1223/locwarp)"` →
build version from `config.VERSION` and repo → `raviwu`. Extend
`test_version_sync.py` to grep for any `LocWarp/<digits>` literal anywhere in
`backend/` so the version can never silently drift again.

### B3 — Release footer

`.github/release-footer.md:4-5` README links → `raviwu` (these are appended to
**raviwu** mac releases).

### B4 — README (platform-aware, the nuance)

`README.md` / `README.en.md`:
- **Download / releases links** (`:75`, `:283`, `:391` zh; `:75`, `:282`, `:321`
  en): split into **macOS → `raviwu/locwarp/releases`** and **Windows →
  `keezxc1223/locwarp/releases`**. Do **not** blindly repoint all to raviwu — the
  fork ships no `.exe`; that would strand Windows users.
- **Open decision (spec review):** Issues links (`:44`, `:65`) and the iOS-16
  community PR (`:60`, `#9 @bitifyChen`). Recommendation: Issues → `raviwu` (you
  maintain the fork and respond there); the historical PR reference stays
  `keezxc1223`. Maintainer to confirm.

---

## Workstream C — `DeviceManager` race + fd-leak (reliability, danger zone)

### C1 — `connect()` atomic claim

`core/device_manager.py`: `connect()` checks membership under `_lock`
(`:477-480`), releases it, does the heavy connect (autopair + tunnel/legacy) with
**no** lock, then reinstalls with a bare `self._connections[udid] = conn`
(`:539-540`). Two concurrent `connect(udid)` (routine: HTTP `/connect` + 1s usbmux
watchdog + startup autoconnect + `full_reconnect`) both pass the check, both open a
tunnel, and the second clobbers the first → an orphaned root-helper utun tunnel
that is never torn down.

**Fix** (mirror the sibling `connect_wifi_tunnel:1053-1058`): under `_lock` at the
reinstall site, `displaced = self._connections.pop(udid, None);
self._connections[udid] = conn`; after releasing the lock, tear down `displaced`.
Verify the legacy iOS-16 path doesn't double-close (there `lockdown` and
`usbmux_lockdown` are the same object).

### C2 — `discover_devices` fd-leak

The success branch (`:378-403`) appends `DeviceInfo` but never closes the lockdown
client (only the `except` branch `:404-416` does), and it runs on every UI refresh
/ watchdog tick → slow usbmuxd-socket exhaustion → "iPhone not detected" until
restart. Wrap the per-device body in `try/finally` so the success path closes too.
Audit `_teardown_connection` / `scan_wifi_devices` probes for the same pattern.

### C3 — Tests first

A characterization test firing two concurrent `connect()` coroutines (model on the
existing `test_device_manager_wifi_tunnel_race_char`), asserting exactly one
connection survives and the displaced tunnel's teardown is called. Plus an
fd/close-count assertion for the discovery success path.

---

## Workstream D — Quick wins

### D1 — Deferred-enrich broadcast (correctness)

`main.py:997-1003` `_deferred_enrich` calls `manager.enrich_all()` but never
broadcasts. The comment `:992-993` falsely claims the watcher broadcasts it —
impossible, because `_save` records its own mtime so `_watcher_tick` suppresses the
self-write. Result: offline-geo fields fill on disk but the UI doesn't refresh
until the next unrelated event. **Fix:** after `enrich_all()`, if it changed > 0,
`await broadcast('bookmarks_changed', {'reason': 'enrich'})`; fix the comment.
(Plan to confirm `enrich_all()` returns a changed-count; if not, add one.)

### D2 — Test timeouts (CI safety)

Add `pytest-timeout` to `requirements-dev.txt` and `@pytest.mark.timeout(10)` on
the blocking-`Event`/spawn char-tests (`test_lifespan_autoconnect_defer_char.py`,
and the group/usbmux char-tests as applicable) so a future boot-defer regression
fails CI cleanly instead of hanging it. CI is the only gate on the direct-to-main
flow.

### D3 — `React.memo` (perf, zero-risk)

Wrap `DeviceStatus.tsx` and `DeviceChipRow.tsx` in `React.memo` — the profiler
flagged both as zero-risk (their `device.*` props don't change on a position tick).
Keep `App.profiler.bench.test.tsx` green.

### D4 — (Optional) "Add to route" bookmark action

Small feature: an "add to route" action on the bookmark popover/context menu
calling the existing `handleAddWaypoint` contract. Pure frontend. **Deferrable** —
include only if the rest lands comfortably; otherwise its own task.

---

## Out of scope (explicitly)

- Deferred perf "bigger wins" — re-verified as correctly dropped.
- Per-platform UpdateChecker detection (#2 option C) — not chosen.
- Loopback-OR-token gate (#1) — not chosen; loopback-only.
- Other audit `noted_but_deferred` items (engine `mark_disconnected` extraction,
  api-ring Demeter leaks, WiFi `find_port` early-exit, tunnel-liveness bounding,
  universal mac build, `App.tsx` decomposition, Py-version alignment).

## Invariants

- Behavior-freeze except the new 403/WS-close for illegitimate callers.
- Full backend pytest + frontend vitest green after **every** commit
  (pin the exact collected counts before starting).
- Danger-zone files (A: middleware/WS touch the api edge; C: `device_manager`) get
  characterization tests before edits.
- All 7 import-linter contracts + depcruise stay green.

## Open decisions for spec review

1. README Issues links → `raviwu` vs keep `keezxc1223` (B4).
2. Whether to ship A2-Origin in this pass or defer it (depends on confirming the
   Electron renderer Origin) — A2-core (loopback) ships regardless.
3. Whether D4 is in or out of this pass.
