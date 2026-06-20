# LocWarp — Claude Code Instructions

Project-specific instructions for Claude / agentic workers. Layered on top of `~/personal/CLAUDE.md` and `~/.claude-work/CLAUDE.md`.

> Tool-agnostic project rules also live in [`AGENTS.md`](AGENTS.md) (read by Codex / Gemini / other agents). Keep the two in sync when changing shared conventions.

---

## Clean Architecture (Pragmatic Hexagonal-lite) — target layering

**Status (2026-06-20):** Phase 0 + Phase 1 + Phase 2 (C / spec-literal) IMPLEMENTED + merged (2026-06-20). Phases 3–5 deferred. Inward-only rings enforced; geocode `GeocodeError`s mapped at the boundary; last `infra→api` edge killed; all `from main import app_state` retired from non-test code; api→api broadcasts via injected `EventPublisher`; **five import-linter contracts ENFORCED (`5 kept, 0 broken`)**. Task 34 (module-level state class-wraps) deferred as a residual tidy-up — no behavior or contract impact. Do not start Phases 3–5 without explicit approval from Ravi.

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

The bookmark store and route store are CRDT-style LWW-element-sets with tombstones (see `backend/services/store_merge.py`). When working on import / sync / deletion flows, remember:

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
