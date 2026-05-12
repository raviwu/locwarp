# Elevated Tunnel Helper — Architecture Split

**Date:** 2026-05-12
**Status:** Design — awaiting review before implementation plan
**Driver:** TCC sandbox blocks the root-elevated backend from reading
`~/Library/Mobile Documents/com~apple~CloudDocs/` (iCloud Drive). User-owned
files like bookmarks, settings, and routes return `EPERM` to the elevated
process even when POSIX permissions allow it. Existing mitigations
(`chmod 644`, `chmod 755` on the iCloud subfolder) do not bypass TCC.
Every fresh ad-hoc-signed build also loses prior TCC approvals, so a
rebuild silently breaks the bookmark UI.

## 1. Goal

Run LocWarp's Python backend as the regular user. Move only the work that
actually needs root — opening `/dev/utunN` and running the user-space QUIC
tunnel for iOS 17+ devices — into a dedicated helper process.

After this change:

- Backend can read and write `~/.locwarp/` and iCloud Drive without TCC
  interference. The bookmark loader works on first launch, every launch,
  on every rebuild.
- Helper holds the TUN device and the `pymobiledevice3` tunnel context.
  Backend talks to iOS over the kernel-routed RSD address via plain TCP.
- Sudo prompt UX stays the same: one `osascript`-driven admin prompt at
  app launch (cancel = app unusable, matching today's behaviour).

## 2. Non-Goals

- Replacing or auditing `pymobiledevice3`. The helper imports it; the
  backend imports it for the non-TUN paths (lockdown, RSD, DTX). No
  changes to vendored library code.
- Codesigning with a stable Developer ID. Ad-hoc signing stays; this
  design works because TCC is no longer in the critical path for
  bookmarks.
- Cross-platform parity. Windows ships a single elevated binary today
  and is unaffected. The helper split applies only to macOS packaged
  builds.
- Lazy / on-demand admin prompting. Future work; out of scope here.

## 3. Why This Works — Kernel-Level TUN Routing

`pytun_pmd3.TunTapDevice` opens `/dev/utunN`, assigns an IPv6 address
(e.g. `fd7d:a20b:b0ce::1`), and brings the interface up. From that
moment the kernel routes packets destined for that address through the
utun interface, regardless of which process opened it. Reading and
writing the raw TUN file descriptor still requires that fd (i.e. needs
root and the original opener), but **any user-space process can open a
TCP socket to the routed IPv6 address**.

LocWarp's iOS-facing traffic after the tunnel is established is plain
TCP:

- `RemoteServiceDiscoveryService((address, port))` opens TCP to the
  routed address.
- `DvtSecureSocketProxyService` over the RSD link.
- Location simulation over DvtSecureSocketProxy.

None of these need the TUN fd directly. The QUIC packet pump (TUN ↔ iOS)
runs entirely in the helper's `start_tcp_tunnel` context; the backend
sees only TCP.

## 4. Process Model

```
┌─────────────────────────────────────────────────────────────┐
│  Electron main.js                       (uid: raviwu)       │
│                                                             │
│   ├── spawn (no admin) ──► locwarp-backend                  │
│   │                         (uid: raviwu)                   │
│   │                         • FastAPI on 127.0.0.1:NNNN     │
│   │                         • bookmarks/settings/routes I/O │
│   │                         • device_manager, simulation    │
│   │                         • opens RSD as plain TCP        │
│   │                                                         │
│   └── osascript admin ──► locwarp-backend --tunnel-helper   │
│                            (uid: root)                      │
│                            • opens /dev/utunN               │
│                            • runs pymobiledevice3 QUIC      │
│                            • listens on Unix socket         │
│                                                             │
│   Backend ◄── Unix socket ──► Helper                        │
│             /tmp/locwarp-helper.sock                        │
│             mode 0660, owner root:<user-primary-gid>        │
│             (see §6.2 for the bind/chown sequence)          │
└─────────────────────────────────────────────────────────────┘
```

Both backend and helper are the same PyInstaller-built executable. The
helper mode is selected by the `--tunnel-helper` CLI flag at process
start. PyInstaller spec stays single-binary; no new build artefact.

## 5. Lifecycle

### 5.1 Startup

1. Electron `main.js` spawns two children **in parallel**:
   - `locwarp-backend` as the regular user (no `osascript`).
   - `osascript -e 'do shell script "locwarp-backend --tunnel-helper
     --parent-pid=N" with administrator privileges with prompt "…"'`
     where `N` is the backend PID.
2. Helper, in this exact order: (a) binds `/tmp/locwarp-helper.sock`,
   (b) `chmod 0660` + `chgrp <parent-uid's primary gid>` on the socket
   node, (c) starts accepting connections, (d) atomically writes
   `READY\n` to `/tmp/locwarp-helper.status` via tmp-and-rename. Steps
   a–c finish before d, so the status file appearing implies the socket
   is connectable.
3. Backend polls for the status file (every 200ms, total wait budget
   30s). Once present, it connects to the socket and issues `ping`. On
   either timeout or a non-OK ping, backend logs and exits — Electron
   sees the backend gone and shows a clear error.
4. User-cancelled `osascript`: the admin prompt closes without spawning.
   Helper never starts; backend's socket poll times out. App is
   unusable, per agreed Q2.a behaviour. Electron surfaces a "Please
   restart and grant admin access" message.

### 5.2 Steady state

- Backend issues helper RPCs only when establishing or tearing down a
  device tunnel. Once a tunnel exists, hot-path location simulation
  traffic does not touch the helper.
- Helper monitors backend liveness: every 5 seconds, `os.kill(parent_pid,
  0)`. On `ProcessLookupError`, helper closes all tunnels and exits.
- Backend monitors helper liveness via the Unix socket; a closed socket
  triggers a single reconnect attempt. If the helper is permanently
  gone, backend marks all WiFi-tunnel devices as disconnected and stops
  accepting new tunnel requests until restart.

### 5.3 Shutdown

- Normal quit (user closes Electron window or `Cmd+Q`):
  1. `main.js` issues `POST /api/system/shutdown` to backend.
  2. Backend, before exiting, calls helper `shutdown()` RPC.
  3. Helper closes all active tunnels (which releases TUN devices),
     unlinks the socket, exits.
  4. Backend exits.
  5. `main.js` quits.
- Crash / SIGKILL of either process: the surviving side's liveness
  watchdog (PID poll for helper, socket-EOF for backend) cleans up.
- Stale sockets from a prior unclean exit: helper unlinks on bind if
  the existing socket has no listening peer (`connect` with `EAGAIN`
  → safe to remove).

## 6. Helper RPC Protocol

### 6.1 Wire format

JSON-RPC 2.0, one request per line, one response per line, over the
Unix socket. Newline-delimited keeps parsing trivial and lets us tail
the socket with `socat` during debugging.

```json
{"jsonrpc":"2.0","id":1,"method":"open_wifi_tunnel",
 "params":{"udid":"…","ip":"192.168.1.29","port":51236}}
```

```json
{"jsonrpc":"2.0","id":1,"result":
 {"rsd_address":"fd7d:a20b:b0ce::1","rsd_port":59830,
  "interface":"utun7","protocol":"quic"}}
```

Errors use JSON-RPC error envelopes. Error codes:

| Code | Meaning |
|---|---|
| -32001 | TUN allocation failed |
| -32002 | RemotePairing handshake failed |
| -32003 | Tunnel already exists for this UDID |
| -32004 | Unknown tunnel ID (close/status) |
| -32099 | Internal helper error (with `data.traceback`) |

### 6.2 Socket permissions

The helper binds the socket as root. Backend connects as the regular
user. macOS Unix socket permission semantics:

- `bind()` creates the socket node with the process umask, so a root
  process produces `srwx------ root wheel` by default. The backend
  cannot connect.
- Helper explicitly `chmod`s the socket to `0660` and `chown`s the
  group to the backend user's primary group after bind.
- Helper resolves the target gid from the `--parent-uid=N` arg that
  Electron passes through (Electron knows its own uid; it forwards as
  helper CLI arg). Helper validates the gid exists before applying.

This restricts socket access to (root) ∪ (members of the user's primary
group). On a single-user macOS install this is just `raviwu` and root.

### 6.3 Methods

| Method | Params | Result | Notes |
|---|---|---|---|
| `open_wifi_tunnel` | `udid, ip, port` | `{tunnel_id, rsd_address, rsd_port, interface}` | iOS 17+ WiFi pair |
| `open_usb_tunnel` | `udid` | `{tunnel_id, rsd_address, rsd_port, interface}` | iOS 17+ USB; helper builds its own usbmux+lockdown |
| `close_tunnel` | `tunnel_id` | `{closed: true}` | Releases TUN, exits the QUIC task |
| `list_tunnels` | — | `[{tunnel_id, udid, …}]` | Debugging / health check |
| `migrate_user_state` | `home, uid, gid` | `{chowned, skipped, failed}` | One-shot ownership repair for `~/.locwarp/` and iCloud `LocWarp/`; safe to re-call |
| `ping` | — | `{ok: true, helper_pid}` | Liveness probe; cheap |
| `shutdown` | — | `{ok: true}` | Close all tunnels + exit (idempotent) |

`tunnel_id` is the UDID. One tunnel per device; second `open_*` for the
same UDID returns `-32003`. Backend resolves "is this device already
tunneled" via `list_tunnels` on reconnect.

## 7. Code Changes — File-by-File

### Backend (`uid: user`)

- **`backend/main.py`** — startup: detect `--tunnel-helper` flag and
  dispatch to helper main (see Helper section). Otherwise: before
  `BookmarkManager()` and friends, call
  `helper_client.connect()` + `helper_client.migrate_user_state(...)`.
  Shutdown handler calls `helper_client.shutdown()` before exiting.
- **`backend/core/wifi_tunnel.py`** — user-side `TunnelRunner` shrinks
  to a thin facade: `start()` calls `helper_client.open_wifi_tunnel(
  udid, ip, port)`, stores the returned RSD info in `self.info`, waits
  on `self._stop`, then calls `helper_client.close_tunnel(udid)`. No
  `pymobiledevice3` import on the user side.
- **`backend/core/device_manager.py`** — `_connect_tunnel` for iOS 17+
  USB calls `helper_client.open_usb_tunnel(udid)` instead of building
  `CoreDeviceTunnelProxy` locally. The result is consumed exactly as
  today (build `RemoteServiceDiscoveryService` from `(address, port)`,
  proceed with DDI mounting and simulation setup).
- **`backend/services/cloud_sync.py`** — remove the root-only chmod
  branches and the EPERM swallowing for `dst.read_bytes()`. Backend
  now runs as the file owner; `setup_sync_folder` simplifies to
  `mkdir(exist_ok=True)`, no chmod. `migrate_bookmarks` drops its
  `OSError → same = False` workaround.
- **`backend/services/tunnel_helper_client.py`** *(new)* — Unix socket
  JSON-RPC client. Single connection, async lock around send/recv,
  numeric request-id counter. ~150 lines.

### Helper (`uid: root`)

- **`backend/main.py`** — when invoked with `--tunnel-helper`, branch
  immediately into `tunnel_helper_main.run()`; never start FastAPI,
  never load `BookmarkManager`, never touch `~/.locwarp/`.
- **`backend/tunnel_helper_main.py`** *(new)* — bind Unix socket,
  accept connections in an asyncio loop, dispatch JSON-RPC. Owns a
  `tunnels: dict[str, TunnelRunner]` map. PID-watch task. ~250 lines.
- **`backend/core/_tunnel_runner.py`** *(new, helper-internal)* — the
  original `pymobiledevice3`-using `TunnelRunner` body moves here
  verbatim. Helper imports it; the user-side facade in
  `core/wifi_tunnel.py` does not. Leading underscore signals
  "helper-only, do not import from backend code". This keeps the user
  side free of `pymobiledevice3.remote.tunnel_service` (and therefore
  of the `pytun_pmd3` C extension that opens `/dev/tun`).

### Electron (`main.js`)

- Replace the single elevated `startBackend()` with two child spawns:
  - User-context backend: plain `spawn(backendPath, [], …)`.
  - Root-context helper: `spawn('osascript', ['-e', script], …)` where
    `script` runs `backendPath --tunnel-helper --parent-pid=N
    --parent-uid=M` with admin privileges and the existing prompt.
- `stopBackend()` issues `POST /api/system/shutdown` to backend (which
  in turn shuts down helper). Helper is no longer reachable from
  Electron directly — backend is the only client.

### Build / packaging

- `locwarp-backend.spec` — no change. Same binary services both modes.
- `build-installer-mac.sh` — no change to the build flow. The bootstrap
  fix landed in 404bec9 already covers fresh-machine setup.
- `cleanup` — old `cloud_sync.py` chmod logic, old `migrate_bookmarks`
  `OSError` swallow, can be deleted.

### Dev mode (`start.sh` / `start.py`)

Today `start.sh` is `exec sudo python3 start.py` — the whole dev
backend runs as root, inheriting the same iCloud TCC problem. The
refactor: `start.py` becomes the user-context entrypoint (no sudo);
internally it spawns the helper via a `sudo python3 -m
tunnel_helper_main --parent-pid=$$ --parent-uid=$(id -u)` subprocess
that prompts for the dev password once. `start.sh` itself stops
`exec sudo`-ing — instead it runs `python3 start.py`, which spawns
the privileged helper internally. The dev's existing sudo timestamp
(typical 5-min cache) makes this near-invisible after the first run
of the session.

## 8. Migration — Existing State Files

Today many users have `~/.locwarp/*` files owned by `root:staff` (left
over from the elevated backend). After this change, the user-context
backend cannot write to them and reads may succeed but writes will
`EACCES`.

`chown` of a root-owned file requires root, so the migration runs **in
the helper** via a dedicated `migrate_user_state` RPC that the backend
invokes once before doing any disk I/O of its own. Helper-side sketch:

```python
def migrate_user_state(home: str, uid: int, gid: int) -> dict:
    """Reassign ownership of any LocWarp state files to (uid, gid).
    Returns counts of chowned/skipped/failed entries."""
    targets = [Path(home) / ".locwarp"]
    icloud = Path(home) / "Library/Mobile Documents/com~apple~CloudDocs/LocWarp"
    if icloud.exists():
        targets.append(icloud)

    chowned = skipped = failed = 0
    for root in targets:
        for entry in [root, *root.rglob("*")]:
            try:
                st = entry.stat()
                if st.st_uid == uid:
                    skipped += 1
                    continue
                os.chown(entry, uid, gid)
                chowned += 1
            except OSError as exc:
                failed += 1
                logger.warning("could not chown %s: %s", entry, exc)
    return {"chowned": chowned, "skipped": skipped, "failed": failed}
```

RPC sequencing:

1. Backend starts (user). Connects to helper.
2. Backend calls `helper.migrate_user_state(home="/Users/raviwu",
   uid=getuid(), gid=getgid())`.
3. Helper returns counts. Backend logs them.
4. Backend proceeds with `BookmarkManager()` and friends.

If migration fails (e.g. helper not yet ready), the bookmark load may
hit `EACCES` instead of `EPERM`. That is a regression from "works
silently" but a clear, actionable error. We surface it via the existing
`safe_load_json` corrupt-file logging.

## 9. Testing Strategy

### 9.1 Unit tests

- `tests/test_tunnel_helper_client.py` — mock Unix socket, verify
  JSON-RPC framing, error code handling, single-flight requests.
- `tests/test_cloud_sync.py` — existing tests still apply; remove the
  ones that asserted on chmod side effects.
- `tests/test_bookmarks.py` — unchanged. Backend-only code; helper
  not involved.

### 9.2 Integration tests

- `tests/integration/test_helper_handshake.py` — spawn the helper
  binary (not via osascript — directly under `sudo` in CI; skipped
  outside CI), assert socket appears, ping succeeds, shutdown is
  clean.
- `tests/integration/test_state_migration.py` — pre-seed `~/.locwarp/`
  with root-owned files in a tmp HOME, run migration, verify
  ownership. Requires `sudo` to set up the fixture.

### 9.3 Manual smoke tests (BAT-style)

These run on the developer's Mac before release.

1. Fresh install: build, install, open. Admin prompt appears once.
   Bookmarks render from iCloud. Local `~/.locwarp/bookmarks.json` is
   either absent or user-owned.
2. Cancel admin prompt: app fails to start, error visible to user.
3. iOS 17+ USB connect: device appears, location simulation works.
4. iOS 17+ WiFi connect: same.
5. Quit app: both backend and helper processes exit within 3s.
6. Force-kill backend: helper exits within 10s (PID watchdog).
7. Force-kill helper: backend logs the loss, marks tunneled devices as
   disconnected, accepts no new tunnel requests, app remains usable
   for non-tunnel work (bookmarks, etc.).

## 10. Rollback Plan

If the split introduces regressions we cannot fix quickly, revert to
the elevated-backend model. The revert is a single git revert + rebuild
+ reinstall. The only state we mutate is file ownership in
`~/.locwarp/` and iCloud `LocWarp/`. Reverted code paths still tolerate
user-owned files (they were the original assumption); root-owned files
that the reverted code wrote will continue to work because root can
read its own files. So no special rollback steps are needed for state.

## 11. Open Questions

None blocking. The following are deliberate forward-deferrals:

- Lazy admin prompting (Q2.b in brainstorming) — revisit after we have
  the split in place; trivial to add later as a backend-side mode that
  skips the `osascript` spawn until first iOS 17+ device is detected.
- Stable codesigning — orthogonal; would also help, but the split
  removes the need for it on the bookmark path.
- Helper auto-update — out of scope. The whole app updates together;
  the helper is part of the same binary.

## 12. Acceptance Criteria

1. `make build-install` on a clean checkout produces a DMG where, on
   first run, bookmarks load successfully from
   `~/Library/Mobile Documents/com~apple~CloudDocs/LocWarp/bookmarks.json`.
2. `ps auxww | grep locwarp-backend` shows two processes:
   one under the user, one under root.
3. `~/.locwarp/bookmarks.json` (if present) is owned by the user, not
   root, after first launch.
4. Closing the app cleanly leaves no orphaned helper process.
5. `backend.log` contains no `Operation not permitted` entries from
   `services.json_safe`.
6. iOS 17+ USB and WiFi tunneling work end-to-end: connect, see
   device, simulate location.

---

**Next step after approval:** invoke `superpowers:writing-plans` to
turn this into an actionable implementation plan with TDD checkpoints.
