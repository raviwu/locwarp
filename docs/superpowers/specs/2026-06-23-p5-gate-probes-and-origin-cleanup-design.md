# P5 — Prove the Architecture Gates Fail-on-Probe + Origin Cleanup — Design

**Date:** 2026-06-23
**Status:** Design — awaiting review
**Author:** Ravi + Claude

## Problem

Across P0–P4 the layering gates were flipped to enforced (backend import-linter `7 kept, 0 broken`; the
frontend dependency-cruiser scoped `error` rules for the BookmarkList/App/MapView trees). But "the suite is
green" only proves the gates **pass** — it does not prove they **fail on a real violation**. A gate that
can't fail is theatre. P5 (the capstone of the P0–P5 clean-arch refactor) adds **committed fail-on-probe
regression tests** for both gates, and collapses the last stray `8777` literals so each runtime has one
origin/port source.

## Decisions (locked with Ravi, 2026-06-23)

| Decision | Choice |
|----------|--------|
| **Origin collapse scope** | **Per-runtime single constant + documented carve-outs.** Each runtime (Python backend / TS renderer / Electron Node / launcher scripts) has ONE port/origin constant; cross-runtime literals can't share one (different languages), so they're documented as carve-outs that "must match backend API_PORT". |
| **Gate proof** | **Committed fail-on-probe tests** (not CI-only): a test injects a forbidden import into a temp probe, runs the linter, asserts it FAILS with the expected contract/rule, then removes the probe (try/finally). |

## Goals

1. **Backend import-linter fail-on-probe test**: prove lint-imports reports a broken contract when a
   cross-layer import is introduced — both directions (`core → api` and `services → fastapi`) — then revert.
2. **Frontend dependency-cruiser fail-on-probe test**: prove depcruise exits non-zero with the scoped
   `error` rule when a gated view file imports `services/api`, then revert.
3. **Origin cleanup**: every `8777` in CODE is either the runtime's single constant or a doc/test —
   derive `backend/config.py` `CORS_ORIGINS` from `API_PORT`; give Electron + the launcher scripts one
   documented local constant each.
4. No behavior change; the gates stay enforced (`7 kept, 0 broken` / depcruise 0 errors) on the clean tree;
   full backend pytest + frontend vitest + e2e green.

## Non-goals

- Not building a shared cross-runtime port file (rejected — marginal value, packaging-path complexity).
- Not changing any contract/rule's scope (the probes are temp + reverted; the rules are unchanged).

## Part A — Fail-on-probe tests

### A1. Backend (`backend/tests/test_import_contracts_fail_on_probe.py`)
- Writes a temp probe module under the real package tree and runs the SAME `lint-imports` console-script
  the enforcement test uses (`Path(sys.executable).parent / "lint-imports"`, cwd `backend/`).
- **Probe 1 (core → api):** `backend/core/_p5_probe.py` with `from api.device import _tunnels` (or any real
  `api.*` symbol) → assert lint-imports exit code != 0 AND the output names the core-layer contract as broken.
- **Probe 2 (services → fastapi):** `backend/services/_p5_probe.py` with `import fastapi` → assert exit != 0
  AND the no-services-imports-fastapi contract is broken.
- **Cleanup is mandatory + safe:** `try/finally` removes both probe files; a guard at test start also deletes
  any stale `_p5_probe.py` (so a crashed prior run can't poison the real gate). The test asserts the clean
  tree is back to `0 broken` at the end.

### A2. Frontend (`frontend/scripts/gate-fail-on-probe.test.ts` or a vitest spawning depcruise)
- Writes a temp probe file whose path matches a scoped `error` rule (e.g.
  `frontend/src/components/MapViewGateProbe.tsx` matches `^src/components/(MapView|…)`) containing
  `import * as _api from '../services/api'`.
- Spawns `npx depcruise src --config .dependency-cruiser.cjs` (child_process) → asserts exit code 1 AND the
  output names the scoped `error` rule (e.g. `mapview-no-direct-api`).
- `try/finally` removes the probe; a start-of-test guard deletes any stale probe; asserts the clean tree is
  back to 0 errors. (One test covers the mechanism; the three scoped rules share the same enforcement path.)
- This test spawns a subprocess, so mark it appropriately (it's slower than a unit test) — keep it a single
  focused test.

## Part B — Origin/port cleanup (per-runtime single constant)

- **`backend/config.py`**: `CORS_ORIGINS` derives from `API_PORT` — `f"http://127.0.0.1:{API_PORT}"`,
  `f"http://localhost:{API_PORT}"` (kill the two literals at :207-208). The `LOCWARP_LAN_ORIGIN` runtime
  addition (main.py) is unchanged. Update the comment. (The existing `test_config_no_env_read` /
  `test_cors_allowlist` tests assert the resulting origins — keep them green; they pin the values, which are
  unchanged.)
- **`frontend/electron/main.js`**: add ONE `const BACKEND_PORT = 8777` (or `BACKEND_ORIGIN`) at the top;
  the health-check (`:362`) + the backend load URL derive from it. Comment: "must match backend
  `config.py:API_PORT` + the renderer's `adapters/config.ts` ORIGIN_PORT (separate runtime — can't import)."
- **`start.py` / `stop.py` / `start.sh`**: each keeps its single port constant (`start.py` already has
  `BACKEND_PORT`; give `stop.py` one instead of the inline `[8777, 5173]`; `start.sh` likewise), with the
  same "must match backend API_PORT" comment.
- **FE renderer**: already a single constant (`adapters/config.ts`); no change.
- **`phone.html`**: served same-origin (uses the request origin, no hardcoded `8777`) — verify, no change.
- After the cleanup, an audit: `grep 8777` over code (excluding docs/tests/catalog-coords) shows only the
  per-runtime constants.

## Testing & verification

- Full backend `pytest` green (incl. the new A1 probe test + the existing enforcement + CORS tests);
  `lint-imports` → `7 kept, 0 broken` on the clean tree.
- Frontend `vitest` green (incl. A2); `tsc --noEmit` clean; `depcruise` → 0 errors on the clean tree; e2e green.
- The A1/A2 probe tests demonstrably FAIL the gate on the probe and leave the tree clean afterward (their
  whole point — verify they go red if the gate were neutered).
- Packaged-app smoke is a manual follow-up (the origin collapse touches Electron + CORS); note it in the plan
  as a known manual gate (not blocking the structural commits).

## Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| A probe file left behind poisons the real gate | `try/finally` cleanup + a start-of-test guard that deletes any stale `_p5_probe`/probe; final assert that the clean tree is 0 broken / 0 errors |
| Origin collapse breaks Electron preload-injected origin vs Vite-dev fallback, or the phone.html LAN origin | Derive only the literals that are truly the backend origin; leave the Vite-dev (5173) + `LOCWARP_LAN_ORIGIN` runtime paths untouched; phone.html stays same-origin |
| CORS behavior change | `CORS_ORIGINS` derives the SAME two values from `API_PORT`; the existing CORS tests pin them |
| depcruise subprocess test is slow/flaky in CI | Single focused test; reuse the existing config; assert on exit code + rule name, not full output |
