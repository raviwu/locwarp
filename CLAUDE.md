# LocWarp — Claude Code Instructions

Project-specific instructions for Claude / agentic workers. Layered on top of `~/personal/CLAUDE.md` and `~/.claude-work/CLAUDE.md`.

> Tool-agnostic project rules also live in [`AGENTS.md`](AGENTS.md) (read by Codex / Gemini / other agents). Keep the two in sync when changing shared conventions.

---

## Clean Architecture (Pragmatic Hexagonal-lite) — target layering

**Status (2026-06-22):** Phase 0 + Phase 1 + Phase 2 + Phase 3 merged to main (2026-06-22); **Phase 4a (backend repository inversion) IMPLEMENTED on branch `chore/clean-arch-p4a` (2026-06-22), pending real-data smoke + merge**. Inward-only rings enforced; **seven import-linter contracts ENFORCED (`7 kept, 0 broken`)**. P3 carved `domain/movement.py` (EtaTracker + `build_resume_snapshot` + RouteInterpolator, killing the `core→services` interpolator edge) under `no-domain-imports-outer`. **P4a** inverted bookmark/route **file-I/O** behind `BookmarkRepository`/`RouteRepository` ports (`infra/persistence/json_store.py` built ONLY at the composition root — services never import infra), moved `merge_stores` to `domain/store_merge.py` (shim in services), added a shared `force_seed_items` primitive encoding the empty-`updated_at` pitfall, and added `no-infra-imports-fastapi`. Watcher/lock/mtime stay on the managers; **no RouteManager lock** (review proved no disk-write race). Phase 4b (frontend god-component decomposition) + Phase 5 deferred. Do not start P4b / Phase 5 without explicit approval from Ravi.

**Why Pragmatic Hexagonal-lite, not strict L1–L4:** real clean architecture (inward-only rings, inner-owned ports, repository, composition-root DI, CI-enforced layering) **without** per-verb interactor classes, numbered `l1–l4` folders, or a presenter layer (`response_model` already serves that role). For a solo dev on real hardware, the strict form multiplies file count for substitutability we never use.

**Backend rings — dependencies point inward only:**
`bootstrap/` (composition root, the ONLY ring that imports every other ring) → `api/` + `infra/` (outermost adapters) → `services/` (use-cases) → `core/` (engine + movers) → `domain/` (pure: models, `events.py`, `movement.py`, `errors.py`, `ports/`).

**Import bans (will become import-linter contracts — the "353rd test"):**
- `domain/` imports stdlib + pydantic ONLY — never fastapi, httpx, asyncio I/O, pymobiledevice3, or any outer ring.
- `core/` imports `domain/` only (may depend on ports, never on infra impls / services / api).
- `services/` raises **domain errors**, never `fastapi.HTTPException`.
- **No `core→api` edge** (forbids the whole `api` package; validated by `grep 'from api\.'` under `core/` == 0 — not just the `broadcast` string). **No `infra→api` edge.** `api/*` may not import another `api/*`.
- Only `bootstrap/` + `main.py` read `Settings`/env. `main.py` imports `bootstrap` only.

**Frontend (hexagon-lite):** `view (features/app)` → `hooks/` → `ports/` (interfaces) ← `adapters/` impls injected via `ServicesContext`. View MUST NOT import `adapters/api` / `services/api` directly. The `WsRouter` MUST preserve the existing **multi-subscriber fan-out** (`useWebSocket` Set/forEach + per-handler try/catch) — it is a broadcast, not route-by-type-to-single-owner. Backend origin (`8777`) lives in ONE constant (`contract/endpoints.ts` + `adapters/config.ts`).

**The three load-bearing inversions:** engine → `DevicePort` (infra `device_manager` injected); `device_manager` → `EventPublisher` (api WS publisher injected; **awaited, in-line, order-preserving** — never hold the connection-manager lock under `device_manager._lock`); `device_manager` → `TunnelRegistry` (infra `wifi_tunnel` injected, owning `_tunnels` + `_tunnels_lock`; read path snapshots under the lock). DI = one container on `app.state`, synchronous providers, no DI framework.

**Hard rules for any work under this refactor:**
- **Behavior / API freeze.** No external HTTP / WS / IPC change. The full backend pytest suite stays green after EVERY commit (current baseline ≈371 collected — pin the exact number via `cd backend && .venv/bin/python -m pytest --collect-only -q` before starting; the design-scan's "352" counted test *functions*). WS payloads compared **deep-equal JSON** (not literal bytes), serialized `exclude_unset`/`exclude_none` so absent keys stay absent. The ONE documented exception is the `device_manager.py:1155` NameError fix (a dead retry path becomes live).
- **Danger-zone-test-first.** `simulation_engine.py` + all movers + `api/location.py` + `device_manager` recovery + `phone_control.py` have **no direct tests**. Write characterization tests (driven by an injected `ClockPort` + stepped `asyncio.sleep`, asserting ordered exact tuples) **before** touching them. The frontend has zero test infra — bootstrap Vitest **first and alone** before any god-component split.
- **Thick carve-outs stay leaky.** Do NOT abstract `pymobiledevice3` / `usbmuxd` / SIP / tunnel-helper / `osascript` guts into pure cores — wrap them behind narrow ports only as a test/inversion seam.
- **CI gate before structural moves.** import-linter ships report-only in Phase 0; each contract flips to enforced at its establishing phase's exit.

---

## Before proposing API changes — survey the existing surface

**Rule:** When the task touches HTTP endpoints, WebSocket events, IPC channels, or any other RPC surface, you MUST first enumerate the existing endpoints in that surface **before** proposing additions, replacements, or new shapes.

Skipping this step risks:
- Adding a duplicate endpoint that overlaps an existing one
- Proposing a "new" design that an earlier commit already implemented under a different name
- Missing prior intent encoded in the existing route layout (e.g., a path was deliberately reused for simplicity, or deliberately split for clarity)

**How to enumerate:**

| Surface | Quick survey command |
|---------|----------------------|
| FastAPI HTTP routes | `grep -nE '@router\.(get\|post\|put\|delete\|patch)\|@app\.(get\|post\|put\|delete\|patch)' backend/api/*.py backend/main.py` |
| WebSocket message types | `grep -rn '"type"\s*:' backend/api/websocket.py` and the frontend WS dispatcher |
| Electron IPC channels | `grep -rn "ipcMain\.handle\|ipcMain\.on\|ipcRenderer\.invoke\|ipcRenderer\.send" frontend/electron frontend/src` |

After enumerating, ALSO check git history for any endpoint involved in the area:
```bash
git log --all --oneline -- backend/api/<file>.py | head -20
```
The commit messages often record original design intent ("POSTs through the existing import flow", "auto-detects full-store / single-category / geojson") that constrains where new behavior should live.

**Then** propose the change, with one of these conclusions explicitly stated in the plan:
- "Reusing existing endpoint X because …"
- "Extending endpoint X with a new parameter because …"
- "Adding a new endpoint Y because (existing endpoint, prior design intent) … does not cover this case"

This rule applies symmetrically to backend services / managers: list existing `manager.<method>` calls before proposing a new method.

---

## Bookmark / Route store: CRDT merge semantics

The bookmark store and route store are CRDT-style LWW-element-sets with tombstones (the pure rule lives in `backend/domain/store_merge.py` since P4a; `backend/services/store_merge.py` is a re-export shim). Since P4a the file-I/O is behind `BookmarkRepository`/`RouteRepository` ports (`backend/infra/persistence/json_store.py`, injected at the composition root); the managers keep CRUD + the watcher + `_store_lock` + mtime and call the repo for disk ops. The empty-`updated_at` pitfall is encoded in the shared `force_seed_items(items, now)` primitive (`domain/store_merge.py`). When working on import / sync / deletion flows, remember:

- `merge_stores(a, b)` is the single merge primitive — commutative, idempotent
- An item is alive iff there is NO tombstone for its id with `deleted_at >= item.updated_at`
- **An item with empty `updated_at = ""` always loses to a real-timestamp tombstone** — this is the source of subtle "import succeeded but nothing changed" bugs
- Tombstones GC after `TOMBSTONE_RETENTION_DAYS = 30`
- The merge is run inside `_save()` on every write, against the on-disk copy, to absorb concurrent iCloud writes

**Implication for catalog seeds / bulk imports:** if the source payload has no `updated_at`, ANY prior local tombstone will silently kill the imported item after save. Either:
1. Stamp `updated_at = now()` on incoming items so they win the merge, OR
2. Use a force-sync code path that does the same explicitly

Never assume "the item appears in `self.store.<list>` after my mutation, so it'll persist." It only persists if it survives the merge in `_save()`.

---

## Local rotating backup (`~/.locwarp/backups/`)

A lifespan-owned asyncio task (`_bookmark_backup_loop` in `main.py`) snapshots the **live**
bookmark + route stores every `BACKUP_INTERVAL_S` (5 min) to `~/.locwarp/backups/` —
local-only, **never** the iCloud sync_folder (so backups aren't re-synced/clobbered).
Design: `docs/superpowers/specs/2026-06-22-bookmark-route-rotating-backup-design.md`.

- `locwarp-latest-backup.json` is refreshed every tick; a timestamped
  `locwarp-backup-<YYYYMMDD-HHMMSS>.json` is archived **only when the data changed**
  (fingerprint excludes `_backup_meta`). Pruned past `BACKUP_RETENTION_HOURS` (72h) by the
  **filename** timestamp, not mtime.
- **Never clobbers on empty:** `BackupService.tick` skips entirely when bookmarks==0 AND
  routes==0 (guards transient iCloud eviction / startup).
- Consistent reads via `BookmarkManager.snapshot_export()` (under `_store_lock` — no torn
  read vs `_save`/`_watcher_tick`) / `RouteManager.snapshot_export()`.
- Rings: `domain/backup.py` (pure policy) + `domain/ports/backup_repository.py` (Protocol) ←
  `infra/persistence/backup_store.py` (atomic I/O via `json_safe`) ← `services/backup_service.py`
  (`tick`) ← wired at `bootstrap/factories.make_backup_service` + `main.py` lifespan. No new
  import-linter contract.
- **Restore:** `make restore-backup` restores BOTH stores from a combined snapshot (default
  `~/.locwarp/backups/locwarp-latest-backup.json`; `merge_backup.py` auto-detects the combined
  `{_backup_meta, bookmarks, routes}` shape and folds each sub-store via `merge_stores`). Bare
  per-store files still restore via `make merge-bookmarks` / `make merge-routes`. (Feeding the
  combined file straight to `merge-bookmarks` used to raise a ValidationError — `restore_combined_snapshot`
  fixes that.) The manual `make backup` (`scripts/desktop_backup.py`) writes the identical
  format/dir and stays a compatible on-demand tool; no launchd agent is installed.
- **Test isolation:** `config.BACKUP_DIR` is redirected to a tmp dir by the autouse
  `conftest._isolate_real_data_paths` guard — extend that guard for any new `~/.locwarp` path.

---

## USB pair records under SIP

`/var/db/lockdown/<udid>.plist` is SIP-protected on macOS 11+. Even
`sudo rm` fails with "Operation not permitted". The only user-mode
path to clear that file is to send a `DeletePairRecord` plist message
to `usbmuxd` (which is SIP-exempt, being a system daemon that owns
the directory).

`pymobiledevice3` does not wrap this in a high-level API. The wrapper
lives at `backend/services/usbmux_pair_records.py`:

- `delete_system_pair_record(udid)` — sends the raw plist to usbmuxd.
- `delete_local_pair_record(udid)` — removes `~/.pymobiledevice3/<udid>.plist`
  (iOS 17+ RemotePairing cache; not SIP-protected).
- `autopair_with_recovery(udid)` — the shared "try autopair → on stale-cert
  clear records → retry once" dance used by both `wifi/repair` and
  `DeviceManager.connect()`.
- `POST /api/device/{udid}/forget` — the user-facing entry point: iPhone-side
  unpair (best-effort) → session teardown → both record deletes →
  `mark_user_denied`. Discovery polls use `autopair=False` so they never pop
  the Trust dialog.

The stale-cert classifier (`_is_stale_cert_error`) whitelists
`ConnectionResetError`, `BrokenPipeError`, `EOFError`, `ssl.SSLError`,
and `pymobiledevice3.exceptions.ConnectionTerminatedError`.
`ConnectionAbortedError` (USB cable unplugged) is deliberately excluded
— that's a transient hardware event, not a stale cert.

**Do NOT auto-clear on `UserDeniedPairingError`** — that's the user
deliberately tapping "Don't Trust"; resetting that choice without
asking would be silently overriding user intent. `DeviceManager.connect()`
adds the udid to `dm.sticky_user_denied` and the watchdog refuses to
auto-connect it until the user explicitly triggers re-pair via the
in-app Re-trust button (which clears the flag). The sticky set persists to
`~/.locwarp/sticky_denied.json` (`STICKY_DENIED_FILE`) so the choice — and
any in-app Forget — survives a LocWarp restart.

---

## Personal repo conventions

This is a personal single-developer repo under `~/personal/`. Per `~/personal/dotfiles/personal-claude/AGENTS.md`:
- Ships as direct commits to main — no PR ceremony, no `/pr-review-loop`, no Copilot review
- Git identity is auto-set by `~/.gitconfig` includeIf — never pass `-c user.email=...` to git commands
- Force-push to main is allowed when amending a not-yet-merged-by-others commit; prefer `--force-with-lease`

---

## Catalog seed (`backend/static/catalog.json`)

The bundled curated event catalog. Source-of-truth for catalog-id entries (`seed-*` prefix). When editing:
- Each category gets a unique `id`, `name`, `color`, `sort_order`, `created_at`, optional `start_date` / `end_date`
- Each bookmark gets `id`, `name`, `lat`, `lng`, `category_id`, `country_code`, `created_at`, `last_used_at`
- `_meta.source_notes` should list each event with its source URL and date range — this is the human-readable changelog for the seed file
- `_meta.compiled_at` should be bumped on any data change

When ingesting coordinates from an external site:
1. Prefer URL-embedded coordinates: `!3d<lat>!4d<lng>` > `?ll=<lat>,<lng>` > `/@<lat>,<lng>,...`
2. Fall back to following short-URL redirects (`maps.app.goo.gl`, `goo.gl/maps`) and re-parsing the expanded URL
3. Last resort: geocode the address via Nominatim using a real browser User-Agent (`LocWarp-catalog-seeder/*` UA is blocked)

---

## Working directories

- Backend pytest: `cd backend && .venv/bin/python -m pytest <args>`
- Backend dev run: `cd backend && py -3.13 main.py` (Windows) or `.venv/bin/python main.py` (macOS dev)
- Frontend type check: `cd frontend && npx tsc --noEmit`
- Frontend dev: `cd frontend && npx vite --host --port 5173` (browser) or `npm run start` (Electron window)
