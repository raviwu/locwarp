# LocWarp — Claude Code Instructions

Project-specific instructions for Claude / agentic workers. Layered on top of `~/personal/CLAUDE.md` and `~/.claude-work/CLAUDE.md`.

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
in-app Re-trust button (which clears the flag).

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
