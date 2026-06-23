# P5 — Gate Fail-on-Probe Tests + Origin Cleanup — Implementation Plan

> **For agentic workers:** Execute task-by-task. The probe tests MUST clean up their temp probe files
> (try/finally + a start-of-test guard) and assert the clean tree is back to 0 broken / 0 errors. No
> behavior change; the gates stay enforced; the origin values are unchanged (only their source moves).

**Goal:** Prove both layering gates fail-on-probe (committed regression tests) + collapse the stray `8777`
literals so each runtime has one origin/port source.

**Spec:** `docs/superpowers/specs/2026-06-23-p5-gate-probes-and-origin-cleanup-design.md`

## Global Constraints

- Backend full `pytest` green; `lint-imports` → `7 kept, 0 broken` on the clean tree. Frontend `vitest` +
  `tsc --noEmit` + `depcruise` (0 errors) + e2e green.
- The probe tests create temp probe files and MUST remove them (try/finally) + guard against stale probes
  from a crashed run + end by asserting the gate is clean again.
- Origin cleanup is value-preserving: `CORS_ORIGINS` derives the SAME two origins; Electron hits the SAME
  URL. Do NOT touch the Vite-dev (5173) path, `LOCWARP_LAN_ORIGIN`, or phone.html same-origin.

---

### Task 1: Backend import-linter fail-on-probe test

**Files:** Create `backend/tests/test_import_contracts_fail_on_probe.py`.

- [ ] At test start, delete any stale `backend/core/_p5_probe.py` / `backend/services/_p5_probe.py` (guard).
- [ ] **Probe 1 (core → api):** write `backend/core/_p5_probe.py` = `from api.device import _tunnels` (use a
  real symbol; verify it exists). Run `lint-imports` (the console-script: `Path(sys.executable).parent /
  "lint-imports"`, cwd `backend/`). Assert exit code != 0 AND the output names the core-layer contract as
  broken. Remove the probe (try/finally).
- [ ] **Probe 2 (services → fastapi):** write `backend/services/_p5_probe.py` = `import fastapi`. Run
  lint-imports → assert exit != 0 AND the no-services-imports-fastapi contract broken. Remove (try/finally).
- [ ] End: assert `lint-imports` is back to `0 broken` (clean tree restored).
- [ ] `cd backend && .venv/bin/python -m pytest tests/test_import_contracts_fail_on_probe.py -q` green;
  full suite green; `lint-imports` → 7 kept/0 broken. Commit:
  `test(p5): prove import-linter fails on a cross-layer probe (core->api, services->fastapi)`.

---

### Task 2: Frontend dependency-cruiser fail-on-probe test

**Files:** Create `frontend/src/__tests__/gateFailOnProbe.test.ts` (or `frontend/scripts/` + a vitest that spawns it).

- [ ] At test start, delete any stale probe file (guard).
- [ ] Write a temp probe whose path matches a scoped `error` rule, e.g.
  `frontend/src/components/MapViewGateProbe.tsx` = `import * as _api from '../services/api'\nexport default function MapViewGateProbe(){ return null }` (confirm the path matches `^src/components/(MapView|…)` in `.dependency-cruiser.cjs`).
- [ ] Spawn `npx depcruise src --config .dependency-cruiser.cjs` (child_process, cwd `frontend/`). Assert
  exit code === 1 AND the stdout names the scoped error rule (e.g. `mapview-no-direct-api`). Remove the
  probe (try/finally).
- [ ] End: assert a clean `depcruise` run exits 0. Mark the test as the slower subprocess test it is.
- [ ] `cd frontend && npx vitest run src/__tests__/gateFailOnProbe.test.ts` green; full vitest green; tsc
  clean; `depcruise` 0 errors. Commit: `test(p5): prove dependency-cruiser fails on a view->services/api probe`.

---

### Task 3: Backend CORS origin cleanup (derive from API_PORT)

**Files:** Modify `backend/config.py`.

- [ ] Change `CORS_ORIGINS`'s two literals (`"http://127.0.0.1:8777"`, `"http://localhost:8777"`) to derive
  from `API_PORT`: `f"http://127.0.0.1:{API_PORT}"`, `f"http://localhost:{API_PORT}"`. Update the comment.
  Keep any other entries unchanged. (config.py stays import-pure.)
- [ ] `cd backend && .venv/bin/python -m pytest tests/test_config_no_env_read.py tests/test_cors_allowlist.py -q`
  green (the values are unchanged); full suite green. Commit:
  `refactor(p5): derive backend CORS origins from API_PORT (kill the 8777 literals)`.

---

### Task 4: Electron + launcher origin cleanup + audit

**Files:** Modify `frontend/electron/main.js`, `stop.py`, `start.sh` (and `start.py` if its constant isn't
already used everywhere).

- [ ] `frontend/electron/main.js`: add ONE `const BACKEND_PORT = 8777;` (top), derive the health-check URL
  (`:362`) + any backend load URL from it. Comment: "must match backend config.py API_PORT + the renderer's
  adapters/config.ts ORIGIN_PORT (separate runtime — can't import)."
- [ ] `stop.py`: replace the inline `[8777, 5173]` with named constants (`BACKEND_PORT = 8777`,
  `VITE_PORT = 5173`) + the comment. `start.sh`: a single `BACKEND_PORT=8777` shell var + comment.
  `start.py`: confirm its `BACKEND_PORT` is the single source for its 8777 uses.
- [ ] **Audit:** `grep -rn 8777` over code (excluding docs/tests/`catalog.json` coords) shows only the
  per-runtime constants (`config.py:API_PORT`, `adapters/config.ts:ORIGIN_PORT`, `electron BACKEND_PORT`,
  the launcher constants). Record the audit result in the commit.
- [ ] Frontend `vitest` + `tsc` + e2e green; backend suite green. Commit:
  `refactor(p5): single per-runtime port constant for Electron + launchers (documented carve-outs)`.

---

### Final: audit + whole-branch review + finish

- Confirm: backend `lint-imports` 7 kept/0 broken, frontend `depcruise` 0 errors, both probe tests green
  (and demonstrably go red on a neutered gate), full backend pytest + frontend vitest + e2e green, the 8777
  audit clean.
- Dispatch the adversarial whole-branch review (probe-test correctness + cleanup-safety, CORS value parity,
  no gate weakened, no stray probe left, origin-collapse doesn't touch the Vite/LAN/phone paths),
  refute-verified. Fix confirmed findings.
- `finishing-a-development-branch`: present merge options. Note the manual packaged-app smoke (Electron +
  CORS) as a follow-up. **With P5 merged, the entire P0→P5 clean-architecture refactor is complete.**
