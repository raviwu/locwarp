# AGENTS — LocWarp

Tool-agnostic instructions for any coding agent (Claude Code, Codex, Gemini CLI, etc.) working in this repo. Claude Code also reads [`CLAUDE.md`](CLAUDE.md), which layers Claude-specific behavior on top of these shared rules — **keep the two in sync** when changing a shared convention.

LocWarp is a macOS/Windows desktop app that spoofs iOS device GPS: a **FastAPI backend** (`backend/`, Python, ~15.5k LOC, ≈371 pytest tests collected) plus a **React + TypeScript + Electron frontend** (`frontend/`, ~19.7k LOC). Single-developer personal project.

---

## Architecture — Clean Architecture (Pragmatic Hexagonal-lite), target layering

**Status (2026-06-22):** Phase 0 + Phase 1 + Phase 2 + Phase 3 merged to main (2026-06-22); **Phase 4a (backend repository inversion) IMPLEMENTED on branch `chore/clean-arch-p4a` (2026-06-22), pending real-data smoke + merge**. Inward-only rings enforced; **seven import-linter contracts ENFORCED (`7 kept, 0 broken`)**. P3 carved `domain/movement.py` (EtaTracker + `build_resume_snapshot` + RouteInterpolator, killing the `core→services` interpolator edge) under `no-domain-imports-outer`. **P4a** inverted bookmark/route **file-I/O** behind `BookmarkRepository`/`RouteRepository` ports (`infra/persistence/json_store.py` built ONLY at the composition root — services never import infra), moved `merge_stores` to `domain/store_merge.py` (shim in services), added a shared `force_seed_items` primitive encoding the empty-`updated_at` pitfall, and added `no-infra-imports-fastapi`. Watcher/lock/mtime stay on the managers; **no RouteManager lock** (review proved no disk-write race). Phase 4b (frontend god-component decomposition) + Phase 5 deferred. **Do not start P4b / Phase 5 without explicit approval from Ravi.**

**Flavor:** real clean architecture (inward-only rings, inner-owned ports, repository, composition-root DI, CI-enforced layering) **without** per-verb interactor classes, numbered `l1–l4` folders, or a presenter layer (FastAPI `response_model` already serves that role). Strict L1–L4 was rejected: for a solo dev on real hardware it multiplies file count for substitutability that is never used.

### Backend rings (dependencies point inward only)

`bootstrap/` (composition root — the ONLY ring allowed to import every other ring) → `api/` + `infra/` (outermost adapters) → `services/` (use-cases) → `core/` (engine + movers) → `domain/` (pure: `models/`, `events.py`, `movement.py`, `errors.py`, `ports/`).

Import bans (to be enforced by import-linter as a pytest — the "353rd test"; report-only in Phase 0, enforced at each phase's exit):
- `domain/` imports stdlib + pydantic ONLY — never fastapi, httpx, asyncio I/O, pymobiledevice3, or any outer ring.
- `core/` imports `domain/` only (may depend on ports; never on infra impls / services / api).
- `services/` raises **domain errors** (`GeocodeError`, `DeviceConnectError`), never `fastapi.HTTPException`.
- **No `core→api` edge** — forbids the whole `api` package; validate with `grep 'from api\.'` under `core/` == 0 (not just the `broadcast` string). **No `infra→api` edge.** `api/*` may not import another `api/*`.
- Only `bootstrap/` + `main.py` read `Settings`/env; `main.py` imports `bootstrap` only.

### Frontend (hexagon-lite)

`view (features/, app/)` → `hooks/` (use-cases) → `ports/` (interfaces) ← `adapters/` impls injected via `ServicesContext`.
- View MUST NOT import `adapters/api` / `services/api` directly (eslint `import/no-restricted-paths`).
- The `WsRouter` MUST preserve the existing **multi-subscriber fan-out** (`useWebSocket` keeps a `Set` of subscribers delivered via `forEach` with per-handler `try/catch`) — it is a broadcast, **not** route-by-type-to-single-owner. `device_*` events are dual-handled in `useSimulation` AND `useDevice` plus two inline `App.tsx` subscribers; collapsing the fan-out would silently drop a handler.
- Backend origin (`8777`) lives in ONE constant (`contract/endpoints.ts` + `adapters/config.ts`); kill the per-file hardcodes.

### The three load-bearing inversions

- engine → `DevicePort` (infra `device_manager` injected).
- `device_manager` → `EventPublisher` (api WS publisher injected; **awaited, in-line, order-preserving** — never acquire the WS connection-manager lock while `device_manager._lock` is held → avoids a new lock-ordering inversion).
- `device_manager` → `TunnelRegistry` (infra `wifi_tunnel` injected, owning `_tunnels` + `_tunnels_lock`; the `get_fresh_dvt_provider` / `full_reconnect` read path snapshots under the lock).

DI is plain constructor injection + one container on `app.state` (AppState reframed, not rewritten); FastAPI `Depends` providers stay **synchronous** (no awaited construction in a request critical section). Repository: `force_seed(items)` stamps `updated_at = now()`, encoding the CRDT tombstone pitfall (below) into the type contract.

### Hard rules for any work under this refactor

- **Behavior / API freeze.** No external HTTP / WS / IPC change. The full backend pytest suite stays green after EVERY commit (current baseline ≈371 collected — pin via `cd backend && .venv/bin/python -m pytest --collect-only -q`; the design-scan's "352" counted test *functions*). WS payloads compared **deep-equal JSON** (not literal bytes), serialized `exclude_unset`/`exclude_none` so absent keys stay absent. The ONE documented exception is the `device_manager.py:1155` NameError fix (a dead retry path becomes live).
- **Danger-zone-test-first.** `simulation_engine.py` + all movers + `api/location.py` + `device_manager` recovery + `phone_control.py` have **no direct tests**. Write characterization tests (injected `ClockPort` + stepped `asyncio.sleep`, asserting ordered exact tuples) **before** touching them. The frontend has zero test infra — bootstrap Vitest **first and alone** before any god-component split.
- **Thick carve-outs stay leaky.** Do NOT abstract `pymobiledevice3` / `usbmuxd` / SIP / tunnel-helper / `osascript` guts into pure cores — wrap them behind narrow ports only as a test/inversion seam.

---

## Before proposing API changes — survey the existing surface

When a task touches HTTP endpoints, WebSocket events, or IPC channels, **first enumerate the existing surface** before proposing additions or new shapes — and check git history for original design intent. Quick surveys:
- FastAPI routes: `grep -nE '@router\.(get|post|put|delete|patch)' backend/api/*.py backend/main.py`
- WS message types: `grep -rn '"type"\s*:' backend/api/websocket.py` + the frontend WS dispatcher
- Electron IPC: `grep -rn "ipcMain\.handle\|ipcMain\.on\|ipcRenderer\.invoke\|ipcRenderer\.send" frontend/electron frontend/src`

State the conclusion explicitly: reusing endpoint X / extending X with a parameter / adding Y because existing surface does not cover the case. Applies symmetrically to backend services/managers — list existing `manager.<method>` calls before proposing a new method.

---

## Bookmark / Route store — CRDT merge semantics (footgun)

The bookmark and route stores are CRDT-style LWW-element-sets with tombstones (`backend/services/store_merge.py`). `merge_stores(a, b)` is the single merge primitive (commutative, idempotent), run inside `_save()` on every write against the on-disk copy. An item is alive iff there is no tombstone for its id with `deleted_at >= item.updated_at`. **An item with empty `updated_at = ""` always loses to a real-timestamp tombstone** — the source of "import succeeded but nothing changed" bugs. For catalog seeds / bulk imports, stamp `updated_at = now()` on incoming items (or use a force-sync path) so they win the merge. After the refactor this is encoded as `repository.force_seed()`. Tombstones GC after `TOMBSTONE_RETENTION_DAYS = 30`.

---

## Local rotating backup (`~/.locwarp/backups/`)

A lifespan-owned asyncio task (`_bookmark_backup_loop` in `main.py`) snapshots the **live**
bookmark + route stores every `BACKUP_INTERVAL_S` (5 min) to `~/.locwarp/backups/` —
local-only, **never** the iCloud sync_folder.
Design: `docs/superpowers/specs/2026-06-22-bookmark-route-rotating-backup-design.md`.

- `locwarp-latest-backup.json` refreshed every tick; a timestamped
  `locwarp-backup-<YYYYMMDD-HHMMSS>.json` archived **only when data changed**; pruned past
  `BACKUP_RETENTION_HOURS` (72h) by the **filename** timestamp.
- **Never clobbers on empty:** `BackupService.tick` skips when bookmarks==0 AND routes==0.
- Consistent reads via `BookmarkManager.snapshot_export()` (under `_store_lock`) /
  `RouteManager.snapshot_export()`.
- Rings: `domain/backup.py` + `domain/ports/backup_repository.py` ←
  `infra/persistence/backup_store.py` (atomic via `json_safe`) ← `services/backup_service.py` ←
  `bootstrap/factories.make_backup_service` + `main.py` lifespan. No new import-linter contract.
- **Restore:** `make restore-backup` restores BOTH stores from a combined snapshot
  (`merge_backup.py` auto-detects the `{_backup_meta, bookmarks, routes}` shape via
  `restore_combined_snapshot`); per-store files via `make merge-bookmarks` / `make merge-routes`.
  `make backup` (`scripts/desktop_backup.py`) writes the same format and stays a manual tool.
- **Test isolation:** `config.BACKUP_DIR` is redirected to tmp by the autouse
  `conftest._isolate_real_data_paths` guard.

---

## USB pair records under SIP

`/var/db/lockdown/<udid>.plist` is SIP-protected on macOS 11+ (even `sudo rm` fails). The only user-mode path is sending a `DeletePairRecord` plist to `usbmuxd`. The wrapper is `backend/services/usbmux_pair_records.py` (`delete_system_pair_record`, `delete_local_pair_record`, `autopair_with_recovery`). `POST /api/device/{udid}/forget` is the user-facing entry point. **Do NOT auto-clear on `UserDeniedPairingError`** — that is the user tapping "Don't Trust"; `DeviceManager.connect()` adds the udid to `sticky_user_denied` (persisted to `~/.locwarp/sticky_denied.json`) and the watchdog refuses to auto-connect until the in-app Re-trust button clears it. This whole subsystem is a thick carve-out — wrap it behind a port, never abstract its internals.

---

## phone.html is served to a real phone over the LAN

`phone_control.py` resolves the host LAN IP (`gethostbyname_ex` / `psutil`) so a physical phone reaches the backend over WiFi. **The backend bind must stay LAN-reachable** — never default it to `127.0.0.1`. Close the exposure with the existing 6-digit PIN/token gate + a CORS allowlist that includes the LAN origin.

---

## Personal repo conventions

Single-developer repo under `~/personal/`:
- Ships as direct commits to `main` — no PR ceremony, no Copilot review.
- Git identity is auto-set by `~/.gitconfig` includeIf (`Ravi Wu` / `raviwu@gmail.com`) — **never** pass `-c user.email=...` or set `GIT_AUTHOR_EMAIL`.
- Force-push to `main` allowed when amending a not-yet-pushed commit; prefer `--force-with-lease`.
- Plan-first for non-trivial work: brainstorm → write a design/plan under `docs/superpowers/specs/` (or `docs/plans/`) → wait for approval before code.

---

## Working directories

- Backend pytest: `cd backend && .venv/bin/python -m pytest <args>`
- Backend dev run: `cd backend && py -3.13 main.py` (Windows) or `.venv/bin/python main.py` (macOS dev)
- Frontend type check: `cd frontend && npx tsc --noEmit`
- Frontend dev: `cd frontend && npx vite --host --port 5173` (browser) or `npm run start` (Electron window)
- Frontend tests (after Phase 0a bootstrap): `cd frontend && npx vitest`
