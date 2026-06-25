# Packaging Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan — one implementer subagent per task plus an adversarial reviewer, with a whole-branch review at the end. Steps use checkbox (- [ ]) syntax; tick each as you complete it. Do every step in order; never let a commit leave the suite red.

**Goal:** Turn the three historical "dev-good / DMG-broken" failure modes (PyInstaller metadata gaps, unpinned native chain, silent restart-only health latches) into build-time and live-queryable signals. Ship: a `--self-check` flag on the frozen binary that imports the whole fragile native chain and exits non-zero on the first failure (wired into `build-installer-mac.sh`), `==` pins for the native chain in `requirements.txt`, and a new `GET /api/system/info` endpoint exposing helper-aliveness, per-device `{ddi_mounted, ios}`, and `offline_geo_ok`.

**Architecture:** Fits the existing Pragmatic-Hexagonal-lite rings. `--self-check` is a `main.py` `sys.argv` branch that runs AFTER the fragile imports (opposite of the lightweight `--tunnel-helper` branch which runs BEFORE any backend import). `/api/system/info` is an additive `api/system.py` route that reads the injected `device_manager` + `helper_client` via existing `api/deps.py` providers and probes `services/geo_offline.py` at request time. A stored `ddi_mounted` flag is added to `core/device_manager._ActiveConnection`, set where `DdiMountedEvent`/`DdiNotMountedEvent` are already published. No new subsystem; one new import-linter exemption line (`api.system -> api.deps` added to the `ignore_imports =` block in `backend/.importlinter`, in the same commit as the route — without it the `independence` contract breaks because `api.system` is not pre-listed like the other api.* modules); api→services flows through `Depends` and is already permitted.

**Tech stack:** FastAPI/Python backend, PyInstaller frozen binary, pytest. (Cluster 4 is backend + build-only; no frontend/Vitest changes — but the frontend suite + tsc + depcruise must STAY green, i.e. you must not break them.)

## Global Constraints

Copied verbatim from the master spec's Global Constraints; every task's requirements implicitly include this section.

- **Green after every commit.** Backend `pytest` + frontend `vitest` + 7 import-linter contracts (`7 kept, 0 broken`) + dependency-cruiser (`0 errors, 0 warnings`) all pass after EVERY commit. Pin the exact baselines before starting:
  - Backend: `cd backend && .venv/bin/python -m pytest --collect-only -q` (expected ≈949 collected).
  - Frontend: `cd frontend && npx vitest run` (expected ≈773) + `npx tsc --noEmit` (0 errors) + `npm run depcruise` (= `depcruise src --config .dependency-cruiser.cjs`, expect 0/0).
- **Danger-zone-test-first.** `simulation_engine.py`, all movers, `api/location.py`, `device_manager` recovery, `phone_control.py` have NO direct tests. Write characterization tests (injected `ClockPort` + stepped `asyncio.sleep`, ordered exact-tuple assertions, REAL collaborators — never stub the method under test) BEFORE touching them.
- **WS payload discipline.** New/changed WS payloads are compared deep-equal JSON, serialized `exclude_unset`/`exclude_none` so absent keys stay absent. Adding keys to an existing event must be backward-compatible (existing consumers must not break).
- **One documented behavior change.** Speed jitter (Cluster 3) changes the per-tick speed of all existing modes. It is gated behind a settings toggle that defaults ON. This is the ONLY intentional behavior change in the program; characterization tests run with jitter OFF to keep exact-tuple assertions stable.
- **Hexagon boundaries hold.** `domain/` stays pure; `services/` raise domain errors not `HTTPException`; view never imports `adapters/api` / `services/api` directly; the `device_manager → EventPublisher` inversion stays **awaited, in-line, order-preserving** — NEVER acquire the WS connection-manager lock while `device_manager._lock` is held.
- **Survey before adding surface.** Each new endpoint/event below states reuse-vs-new with its justification (done in this spec).
- **Personal-repo conventions.** Direct commits to `main`; git identity auto-set by includeIf (never pass `-c user.email=`); no PR ceremony.

---

### Task 1: Pin the fragile native chain to `==`

**Files:**
- Modify: `backend/requirements.txt` (currently 20 lines; existing native lines: `pymobiledevice3>=9.9.0` L1, `timezonefinder>=8.0` L11, `numpy>=1.24` L15). Edit those 3 from `>=` to `==`; ADD 4 new direct `==` lines for the currently-transitive deps (`pyimg4`, `apple_compress`, `h3`, `prompt_toolkit`).
- Test: `backend/tests/test_requirements_native_pins.py` (Create)

**Interfaces:**
- Consumes: the known-good versions in the current `.venv` (read 2026-06-25 via `.venv/bin/pip show`): `pymobiledevice3==9.27.0`, `pyimg4==0.8.8`, `apple_compress==0.2.3` (the **PyPI dist name uses an underscore**: the requirement line is `apple_compress==0.2.3`; pip normalizes underscore↔hyphen), `h3==4.5.0`, `prompt_toolkit==3.0.52`, `timezonefinder==8.2.4`, `numpy==2.4.6`.
- Produces: a byte-reproducible native import graph; a test `test_requirements_native_pins.py` that asserts each native-chain package appears in `requirements.txt` with a `==` pin (so a future `>=` regression is caught in CI).

- [ ] **Step 1: Pin baseline check.** Run `cd backend && .venv/bin/python -m pytest --collect-only -q | tail -1`. Expected: `949 tests collected in ...`. Record this number; every later run must stay ≥ this (it grows as we add tests, never shrinks).
- [ ] **Step 2: Write the failing pin test.** Create `backend/tests/test_requirements_native_pins.py` with the COMPLETE content:
  ```python
  """The fragile native chain (PyInstaller metadata-gap history) must be pinned
  to == in requirements.txt so every DMG builds against a byte-reproducible
  import graph. Pure-Python floors may stay >=; the native chain may not.

  Historical incidents this guards (see CLAUDE.md "PyInstaller copy_metadata
  gap"): pyimg4 / apple_compress / prompt_toolkit / h3 each silently no-op'd
  DDI mount or offline geo in the packaged app only.
  """
  from __future__ import annotations

  import re
  from pathlib import Path

  REQ_PATH = Path(__file__).resolve().parent.parent / "requirements.txt"

  # Distribution names as they appear on a requirement line. pip normalizes
  # underscore <-> hyphen, so we compare case-insensitively with both forms.
  NATIVE_CHAIN = [
      "pymobiledevice3",
      "pyimg4",
      "apple_compress",
      "h3",
      "prompt_toolkit",
      "timezonefinder",
      "numpy",
  ]


  def _parse_requirements() -> dict[str, str]:
      """Map normalized dist-name -> the operator+version spec on its line.

      Ignores comments and blank lines. Normalizes name by lowercasing and
      replacing '_' with '-' (PEP 503 style) so apple_compress == apple-compress.
      """
      specs: dict[str, str] = {}
      for raw in REQ_PATH.read_text("utf-8").splitlines():
          line = raw.strip()
          if not line or line.startswith("#"):
              continue
          # Strip an inline extras spec like uvicorn[standard] before matching.
          m = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(.*)$", line)
          if not m:
              continue
          name = m.group(1).lower().replace("_", "-")
          spec = m.group(3).strip()
          specs[name] = spec
      return specs


  def test_native_chain_is_pinned_with_double_equals():
      specs = _parse_requirements()
      missing: list[str] = []
      unpinned: list[str] = []
      for pkg in NATIVE_CHAIN:
          key = pkg.lower().replace("_", "-")
          if key not in specs:
              missing.append(pkg)
              continue
          spec = specs[key]
          if not spec.startswith("=="):
              unpinned.append(f"{pkg} -> {spec!r}")
      assert not missing, f"native-chain deps absent from requirements.txt: {missing}"
      assert not unpinned, f"native-chain deps not == pinned: {unpinned}"
  ```
- [ ] **Step 3: Run it & see it fail.** Run `cd backend && .venv/bin/python -m pytest tests/test_requirements_native_pins.py -q`. Expected: FAIL with `native-chain deps absent from requirements.txt: ['pyimg4', 'apple_compress', 'h3', 'prompt_toolkit']` and/or `not == pinned: ['pymobiledevice3 -> '>=9.9.0'', ...]`.
- [ ] **Step 4: Edit the three existing native lines to `==`.** In `backend/requirements.txt` change `pymobiledevice3>=9.9.0` → `pymobiledevice3==9.27.0`, `timezonefinder>=8.0` → `timezonefinder==8.2.4`, `numpy>=1.24` → `numpy==2.4.6`. (Leave `fastapi`, `uvicorn`, `websockets`, `gpxpy`, `httpx`, `pydantic`, `python-multipart`, `psutil`, `watchdog`, `tzdata` as their existing `>=` floors — those are pure-Python and not in the metadata-gap history.)
- [ ] **Step 5: Add the four transitive pins.** Append to `backend/requirements.txt`, after the `numpy==2.4.6` line, this block (these are transitive via `pymobiledevice3` today; declaring them direct + pinned is THE point of this task):
  ```
  # Native chain pinned to == (PyInstaller metadata-gap history — see CLAUDE.md
  # "PyInstaller copy_metadata gap"). pyimg4 / apple_compress / h3 / prompt_toolkit
  # are transitive via pymobiledevice3, but each historically broke ONLY in the
  # packaged DMG (silent DDI-mount / offline-geo no-op), so they are declared
  # direct + pinned here so every build resolves the same byte-reproducible graph.
  # The frozen-import self-check (main.py --self-check) imports exactly this chain.
  pyimg4==0.8.8
  apple_compress==0.2.3
  h3==4.5.0
  prompt_toolkit==3.0.52
  ```
- [ ] **Step 6: Run it & see it pass.** Run `cd backend && .venv/bin/python -m pytest tests/test_requirements_native_pins.py -q`. Expected: `1 passed`.
- [ ] **Step 7: Confirm the venv still satisfies the pins (no reinstall needed).** Run `cd backend && .venv/bin/python -c "import pymobiledevice3, pyimg4, apple_compress, h3, prompt_toolkit, timezonefinder, numpy; print('native chain importable')"`. Expected: `native chain importable` (the venv already has these exact versions, so the `==` pins match what is installed).
- [ ] **Step 8: Run the full backend suite.** Run `cd backend && .venv/bin/python -m pytest -q`. Expected: `950 passed` (949 baseline + the 1 new test), 0 failed.
- [ ] **Step 9: Commit.** Run `cd backend && git add requirements.txt tests/test_requirements_native_pins.py && git commit -m "build(c4): pin fragile native chain to == in requirements.txt

Pin pymobiledevice3/timezonefinder/numpy to == and add direct == lines for
the transitive pyimg4/apple_compress/h3/prompt_toolkit so every DMG builds
against a byte-reproducible native import graph. Guarded by a test that
fails if any native-chain dep regresses to >=.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"`.

---

### Task 2: `self_check` import probe (pure function, .spec-cross-checked)

**Files:**
- Create: `backend/self_check.py` — a standalone module (NO backend imports at module top so the `--self-check` branch can import it cheaply, mirroring how `--tunnel-helper` imports `tunnel_helper_main`). Exposes `NATIVE_IMPORT_CHAIN` (the ordered list of `(label, import_callable_source)` chains) and `run_self_check() -> int`.
- Test: `backend/tests/test_self_check.py` (Create)

**Interfaces:**
- Produces:
  - `NATIVE_IMPORT_CHAIN: list[tuple[str, str]]` — ordered list of `(human_label, dotted_module)` covering the three `.spec`-documented chains: `mobile_image_mounter` → `pyimg4` → `apple_compress`; `service_connection` → `prompt_toolkit`; `geo_offline` → `timezonefinder` → `h3`. Concretely the dotted modules probed are:
    `("mobile_image_mounter", "pymobiledevice3.services.mobile_image_mounter")`,
    `("pyimg4", "pyimg4")`,
    `("apple_compress", "apple_compress")`,
    `("service_connection", "pymobiledevice3.service_connection")`,
    `("prompt_toolkit", "prompt_toolkit")`,
    `("timezonefinder", "timezonefinder")`,
    `("h3", "h3")`.
  - `run_self_check(out=sys.stdout) -> int` — imports each module in order via `importlib.import_module`; on the FIRST `ImportError`/`PackageNotFoundError`/any `Exception`, prints `SELF-CHECK FAILED: <label> (<module>): <ExcType>: <msg>` to `out` and returns `1`; on full success prints `SELF-CHECK OK: <n> native imports` and returns `0`.
- Consumed by: Task 3 (`main.py --self-check` branch calls `run_self_check()` and `raise SystemExit(...)`); Task 1's pin test and this module's import list are cross-checked against `backend/locwarp-backend.spec` by `test_self_check.py`.

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_self_check.py` with COMPLETE content:
  ```python
  """The --self-check import chain must (a) cover every native-chain module
  documented in locwarp-backend.spec, (b) succeed in the dev venv (the same
  chain the DMG ships), and (c) report a non-zero exit on the first failure.

  Cross-checking the list against the .spec catches drift between the spec's
  enumerated metadata fixes and what the self-check actually probes.
  """
  from __future__ import annotations

  import io
  from pathlib import Path

  import self_check

  SPEC_PATH = Path(__file__).resolve().parent.parent / "locwarp-backend.spec"

  # The native packages the .spec bundles metadata/binaries for, that the
  # self-check is responsible for proving importable. (developer_disk_image is
  # data-only — no import-time metadata.version() call — so it is NOT in the
  # self-check; numpy is pulled in transitively by timezonefinder/h3.)
  SPEC_GUARDED_PACKAGES = ["pyimg4", "apple_compress", "prompt_toolkit", "h3", "timezonefinder"]


  def test_chain_is_ordered_tuples_of_label_and_module():
      assert isinstance(self_check.NATIVE_IMPORT_CHAIN, list)
      for entry in self_check.NATIVE_IMPORT_CHAIN:
          assert isinstance(entry, tuple) and len(entry) == 2
          label, module = entry
          assert isinstance(label, str) and label
          assert isinstance(module, str) and module


  def test_every_spec_guarded_package_is_probed():
      """Each package the .spec spends a copy_metadata/collect_all on must appear
      as a probed module in the self-check chain — else a metadata gap could
      reappear undetected."""
      probed = {module for _label, module in self_check.NATIVE_IMPORT_CHAIN}
      for pkg in SPEC_GUARDED_PACKAGES:
          assert any(pkg == m or m.endswith(pkg) or m.split(".")[0] == pkg for m in probed), (
              f"{pkg} is metadata-bundled in the .spec but not probed by self_check"
          )


  def test_spec_actually_references_each_guarded_package():
      """Guard the cross-check from the other side: if someone deletes a
      copy_metadata line from the .spec, this fails so the pairing stays honest."""
      spec_text = SPEC_PATH.read_text("utf-8")
      for pkg in SPEC_GUARDED_PACKAGES:
          assert pkg in spec_text, f"{pkg} no longer referenced in locwarp-backend.spec"


  def test_run_self_check_passes_in_dev_venv():
      out = io.StringIO()
      rc = self_check.run_self_check(out=out)
      assert rc == 0, out.getvalue()
      assert "SELF-CHECK OK" in out.getvalue()


  def test_run_self_check_reports_first_failure(monkeypatch):
      """A missing module makes run_self_check return 1 and name the offender."""
      import importlib

      real_import = importlib.import_module

      def fake_import(name, *args, **kwargs):
          if name == "apple_compress":
              raise ModuleNotFoundError("No module named 'apple_compress'")
          return real_import(name, *args, **kwargs)

      monkeypatch.setattr(self_check.importlib, "import_module", fake_import)
      out = io.StringIO()
      rc = self_check.run_self_check(out=out)
      assert rc == 1
      assert "SELF-CHECK FAILED" in out.getvalue()
      assert "apple_compress" in out.getvalue()
  ```
- [ ] **Step 2: Run it & see it fail.** Run `cd backend && .venv/bin/python -m pytest tests/test_self_check.py -q`. Expected: collection/import error `ModuleNotFoundError: No module named 'self_check'` (module not created yet).
- [ ] **Step 3: Create the module.** Create `backend/self_check.py` with COMPLETE content:
  ```python
  """Frozen-binary import self-check.

  Run via `locwarp-backend --self-check` (wired in main.py BEFORE the heavy
  backend imports are needed, but AFTER they would normally happen — see
  main.py). Imports the whole fragile native chain that PyInstaller has
  historically failed to bundle metadata for, and exits non-zero on the first
  failure so build-installer-mac.sh can turn "dev-good / DMG-broken" into a
  build-time red.

  This module imports NOTHING from the backend at module load (only stdlib),
  so the --self-check branch stays cheap and isolated. The native packages are
  imported lazily inside run_self_check via importlib.

  The probed chain mirrors the three documented metadata fixes in
  locwarp-backend.spec:
    1. mobile_image_mounter -> pyimg4 -> apple_compress  (DDI mount path)
    2. service_connection   -> prompt_toolkit            (IPython edge)
    3. geo_offline          -> timezonefinder -> h3       (offline geo path)
  """
  from __future__ import annotations

  import importlib
  import sys

  # (human_label, dotted_module) — ordered. The first failing import wins.
  NATIVE_IMPORT_CHAIN: list[tuple[str, str]] = [
      ("mobile_image_mounter", "pymobiledevice3.services.mobile_image_mounter"),
      ("pyimg4", "pyimg4"),
      ("apple_compress", "apple_compress"),
      ("service_connection", "pymobiledevice3.service_connection"),
      ("prompt_toolkit", "prompt_toolkit"),
      ("timezonefinder", "timezonefinder"),
      ("h3", "h3"),
  ]


  def run_self_check(out=sys.stdout) -> int:
      """Import each native-chain module in order. Return 0 if all import,
      1 on the first failure (printing the offending module + exception)."""
      for label, module in NATIVE_IMPORT_CHAIN:
          try:
              importlib.import_module(module)
          except Exception as exc:  # noqa: BLE001 — surface ANY import-time failure
              print(
                  f"SELF-CHECK FAILED: {label} ({module}): "
                  f"{type(exc).__name__}: {exc}",
                  file=out,
              )
              return 1
      print(f"SELF-CHECK OK: {len(NATIVE_IMPORT_CHAIN)} native imports", file=out)
      return 0
  ```
- [ ] **Step 4: Run it & see it pass.** Run `cd backend && .venv/bin/python -m pytest tests/test_self_check.py -q`. Expected: `5 passed`.
- [ ] **Step 5: Sanity-run the module directly.** Run `cd backend && .venv/bin/python -c "import self_check, sys; sys.exit(self_check.run_self_check())"; echo "exit=$?"`. Expected: `SELF-CHECK OK: 7 native imports` then `exit=0`.
- [ ] **Step 6: Run the full backend suite.** Run `cd backend && .venv/bin/python -m pytest -q`. Expected: `955 passed` (950 prior + 5 new), 0 failed.
- [ ] **Step 7: Commit.** Run `cd backend && git add self_check.py tests/test_self_check.py && git commit -m "build(c4): add self_check import probe for the fragile native chain

self_check.run_self_check() imports the mobile_image_mounter/pyimg4/
apple_compress + service_connection/prompt_toolkit + timezonefinder/h3
chains in order and exits non-zero on the first PackageNotFoundError/
ImportError. Tests cross-check the probe list against the .spec metadata
fixes so spec<->self-check drift is caught.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"`.

---

### Task 3: Wire `--self-check` into `main.py` (after the fragile imports)

**Files:**
- Modify: `backend/main.py` — the `--self-check` branch goes AFTER the heavy backend imports (`core.device_manager` et al. at L26-38), in contrast to the `--tunnel-helper` branch at L6-11 which deliberately runs BEFORE any backend import. Reaching this branch means the `import core.device_manager` (which transitively imports the native chain) already succeeded; `self_check.run_self_check()` then re-imports the chain explicitly to surface a metadata gap with a precise label + exit code.
- Test: `backend/tests/test_self_check_main_branch.py` (Create)

**Interfaces:**
- Consumes: `self_check.run_self_check` (Task 2); `sys.argv` membership (same mechanism as the existing `--tunnel-helper` check at `main.py:8`).
- Produces: `locwarp-backend --self-check` exits with `run_self_check()`'s return code (0/1) WITHOUT starting uvicorn.

- [ ] **Step 1: Read the insertion point.** Open `backend/main.py`. The block ends at L38 (`from services.gpx_service import GpxService`). The `--self-check` branch is inserted immediately after that import block and before the logging-config block at L40. Confirm L39 is blank and L40 begins the `# Configure logging` comment.
- [ ] **Step 2: Write the failing test.** Create `backend/tests/test_self_check_main_branch.py` with COMPLETE content:
  ```python
  """Running the backend with --self-check must invoke self_check.run_self_check
  and exit with its return code, WITHOUT importing uvicorn.run / starting a
  server. We assert the branch by subprocess so we get the real argv path.
  """
  from __future__ import annotations

  import subprocess
  import sys
  from pathlib import Path

  BACKEND_DIR = Path(__file__).resolve().parent.parent


  def test_self_check_argv_exits_zero_in_dev_venv():
      """`python main.py --self-check` in the dev venv prints SELF-CHECK OK and
      exits 0 (the native chain is installed)."""
      proc = subprocess.run(
          [sys.executable, "main.py", "--self-check"],
          cwd=str(BACKEND_DIR),
          capture_output=True,
          text=True,
          timeout=120,
      )
      assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
      assert "SELF-CHECK OK" in proc.stdout


  def test_self_check_branch_does_not_start_uvicorn():
      """The --self-check run returns promptly (it must NOT block in uvicorn.run).
      A 0 return code from the bounded subprocess above already proves it exited;
      here we additionally assert no server banner leaked to stdout."""
      proc = subprocess.run(
          [sys.executable, "main.py", "--self-check"],
          cwd=str(BACKEND_DIR),
          capture_output=True,
          text=True,
          timeout=120,
      )
      assert "Uvicorn running" not in proc.stdout
      assert "Uvicorn running" not in proc.stderr
  ```
- [ ] **Step 3: Run it & see it fail.** Run `cd backend && .venv/bin/python -m pytest tests/test_self_check_main_branch.py -q`. Expected: FAIL — `python main.py --self-check` currently ignores the flag and tries to start uvicorn (subprocess times out at 120s, OR exits non-zero because it binds a port / hangs). Treat a timeout as the expected red.
- [ ] **Step 4: Insert the branch in `main.py`.** After the line `from services.gpx_service import GpxService` (L38) and before the blank line preceding `# Configure logging`, add:
  ```python

  # Early branch: when run with --self-check, import the whole fragile native
  # chain (the PyInstaller metadata-gap history — pyimg4 / apple_compress /
  # prompt_toolkit / h3) and exit non-zero on the first failure, then exit
  # WITHOUT starting uvicorn. Unlike --tunnel-helper (which runs before any
  # backend import to keep the elevated helper small), this branch runs AFTER
  # the heavy imports above: reaching here proves `import core.device_manager`
  # already pulled the chain in, and run_self_check re-imports it explicitly to
  # surface any metadata gap with a precise label + a clean build-log exit code.
  if "--self-check" in sys.argv:
      import self_check

      raise SystemExit(self_check.run_self_check())
  ```
- [ ] **Step 5: Run it & see it pass.** Run `cd backend && .venv/bin/python -m pytest tests/test_self_check_main_branch.py -q`. Expected: `2 passed`.
- [ ] **Step 6: Manual confirm.** Run `cd backend && .venv/bin/python main.py --self-check; echo "exit=$?"`. Expected: log lines then `SELF-CHECK OK: 7 native imports` and `exit=0` (no uvicorn banner).
- [ ] **Step 7: Run the full backend suite.** Run `cd backend && .venv/bin/python -m pytest -q`. Expected: `957 passed` (955 prior + 2 new), 0 failed.
- [ ] **Step 8: Commit.** Run `cd backend && git add main.py tests/test_self_check_main_branch.py && git commit -m "build(c4): wire --self-check into main.py (runs after the native imports)

Add a --self-check argv branch after the heavy backend imports that calls
self_check.run_self_check() and exits with its return code without starting
uvicorn — the build-time inverse of --tunnel-helper. A failed native import
now exits non-zero with the offending module named.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"`.

---

### Task 4: Run `--self-check` post-build in `build-installer-mac.sh`

**Files:**
- Modify: `build-installer-mac.sh` — after the PyInstaller `[1/3]` step (which finishes at L38) and before the Vite `[2/3]` step (L40), run the freshly built binary with `--self-check`; a non-zero exit aborts the build (the script already has `set -euo pipefail` at L6, so a failing command halts it, but we make the failure explicit + readable).
- Test: `backend/tests/test_build_self_check_wired.py` (Create) — a static assertion that the build script invokes the built binary with `--self-check` (no DMG build in CI; this guards against the wiring being dropped).

**Interfaces:**
- Consumes: the PyInstaller output path `$ROOT/dist-py/locwarp-backend/locwarp-backend` (from the existing `--distpath "$ROOT/dist-py"` at L37 + COLLECT `name='locwarp-backend'` in the `.spec`).
- Produces: a build that goes red if the frozen binary cannot import the native chain.

- [ ] **Step 1: Write the failing wiring test.** Create `backend/tests/test_build_self_check_wired.py` with COMPLETE content:
  ```python
  """build-installer-mac.sh must run the freshly built frozen binary with
  --self-check so a PyInstaller metadata gap fails the build instead of
  shipping a broken DMG. Static check — does not run the actual build.
  """
  from __future__ import annotations

  from pathlib import Path

  BUILD_SCRIPT = Path(__file__).resolve().parent.parent.parent / "build-installer-mac.sh"


  def test_build_script_invokes_self_check():
      text = BUILD_SCRIPT.read_text("utf-8")
      assert "--self-check" in text, "build-installer-mac.sh must run the binary with --self-check"


  def test_self_check_runs_after_pyinstaller_and_before_vite():
      text = BUILD_SCRIPT.read_text("utf-8")
      idx_pyinstaller = text.index("PyInstaller locwarp-backend.spec")
      idx_self_check = text.index("--self-check")
      idx_vite = text.index("Build frontend with Vite")
      assert idx_pyinstaller < idx_self_check < idx_vite, (
          "--self-check must run after the PyInstaller step and before the Vite step"
      )
  ```
- [ ] **Step 2: Run it & see it fail.** Run `cd backend && .venv/bin/python -m pytest tests/test_build_self_check_wired.py -q`. Expected: FAIL — `assert "--self-check" in text` (not wired yet).
- [ ] **Step 3: Read the build script insertion point.** In `build-installer-mac.sh`, the PyInstaller invocation ends at L38 (`--workpath "$ROOT/build-py/backend"`). The next non-blank line is the `[2/3]` Vite banner block starting L42 (`echo`). Insert between them.
- [ ] **Step 4: Insert the post-build self-check.** In `build-installer-mac.sh`, immediately after line 38 (`    --workpath "$ROOT/build-py/backend"`) and before the blank line at L39, add:
  ```bash

  echo
  echo "============================================================"
  echo " [1b/3] Frozen-binary self-check (import the fragile native chain)"
  echo "============================================================"
  # Run the freshly built binary with --self-check: it imports the whole
  # PyInstaller-fragile native chain (mobile_image_mounter/pyimg4/apple_compress,
  # service_connection/prompt_toolkit, timezonefinder/h3) and exits non-zero on
  # the first PackageNotFoundError/ImportError. set -e then fails the whole build,
  # turning every historical "dev-good / DMG-broken" metadata gap into a red here.
  SELF_CHECK_BIN="$ROOT/dist-py/locwarp-backend/locwarp-backend"
  if [[ ! -x "$SELF_CHECK_BIN" ]]; then
      echo "ERROR: built backend binary not found at $SELF_CHECK_BIN" >&2
      exit 1
  fi
  "$SELF_CHECK_BIN" --self-check
  ```
- [ ] **Step 5: Run it & see it pass.** Run `cd backend && .venv/bin/python -m pytest tests/test_build_self_check_wired.py -q`. Expected: `2 passed`.
- [ ] **Step 6: Lint the shell script (syntax only — no full build).** Run `bash -n /Users/raviwu/personal/locwarp/build-installer-mac.sh; echo "syntax=$?"`. Expected: `syntax=0` (no parse error).
- [ ] **Step 7: Run the full backend suite.** Run `cd backend && .venv/bin/python -m pytest -q`. Expected: `959 passed` (957 prior + 2 new), 0 failed.
- [ ] **Step 8: Commit.** Run `cd /Users/raviwu/personal/locwarp && git add build-installer-mac.sh backend/tests/test_build_self_check_wired.py && git commit -m "build(c4): run --self-check on the built binary in build-installer-mac.sh

After PyInstaller and before the Vite step, run the frozen binary with
--self-check; set -e fails the build on any native-chain import failure,
so a PyInstaller metadata gap becomes a build-time red instead of a
broken DMG discovered on real hardware.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"`.

---

### Task 5: Add a stored `ddi_mounted` flag on `_ActiveConnection`

**Files:**
- Modify: `backend/core/device_manager.py` — add `ddi_mounted: bool = False` to the `_ActiveConnection` dataclass (L222-237); set `conn.ddi_mounted = True` immediately before publishing `DdiMountedEvent` (L736) and `conn.ddi_mounted = False` immediately before publishing `DdiNotMountedEvent` (L748) inside `_ensure_personalized_ddi_mounted` (L691). This is the persisted latch `/api/system/info` reads in Task 6 (today `ddi_mounted` is computed locally + only emitted as a transient event; `_ActiveConnection` has no field for it).
- Test: `backend/tests/test_ddi_mounted_flag.py` (Create)

**Interfaces:**
- Consumes: existing `DeviceManager(event_publisher=...)`, `_ActiveConnection`, `_ensure_personalized_ddi_mounted(conn)` (real method, driven not stubbed — danger-zone: `device_manager` recovery is untested per Global Constraints, so this is a characterization test).
- Produces: `_ActiveConnection.ddi_mounted: bool` reflecting the last personalized-DDI status check; read by Task 6.

- [ ] **Step 1: Write the failing characterization test.** Create `backend/tests/test_ddi_mounted_flag.py` with COMPLETE content. It drives the REAL `_ensure_personalized_ddi_mounted` against a fake `MobileImageMounterService` whose `is_image_mounted` we control, and asserts both the existing event AND the new stored flag:
  ```python
  """Characterization: _ensure_personalized_ddi_mounted records the DDI status
  on the _ActiveConnection (new stored flag) in addition to the existing
  transient DdiMounted/DdiNotMounted event. Drives the REAL method; only the
  pymobiledevice3 MobileImageMounterService boundary is faked.
  """
  from __future__ import annotations

  import sys
  import types

  import pytest

  from core.device_manager import DeviceManager, _ActiveConnection


  class _FakePublisher:
      def __init__(self):
          self.events = []

      async def publish(self, event):
          payload = event.model_dump(exclude_unset=True, exclude_none=True)
          etype = payload.pop("type")
          self.events.append((etype, payload))


  class _FakeMounter:
      def __init__(self, *, lockdown=None, mounted: bool):
          self._mounted = mounted

      async def connect(self):
          return None

      async def is_image_mounted(self, image_type):
          assert image_type == "Personalized"
          return self._mounted

      async def close(self):
          return None


  def _install_fake_mounter(monkeypatch, *, mounted: bool):
      """Patch the lazily-imported MobileImageMounterService symbol that
      _ensure_personalized_ddi_mounted does `from pymobiledevice3.services.
      mobile_image_mounter import MobileImageMounterService` against."""
      mod = sys.modules.get("pymobiledevice3.services.mobile_image_mounter")
      if mod is None:
          import pymobiledevice3.services.mobile_image_mounter as mod  # noqa: F811

      def _factory(*, lockdown):
          return _FakeMounter(lockdown=lockdown, mounted=mounted)

      monkeypatch.setattr(mod, "MobileImageMounterService", _factory)


  @pytest.mark.asyncio
  async def test_ddi_mounted_sets_flag_true_and_emits_event(monkeypatch):
      pub = _FakePublisher()
      dm = DeviceManager(event_publisher=pub)
      conn = _ActiveConnection(udid="UDID-A", lockdown=object(), ios_version="17.0")
      assert conn.ddi_mounted is False  # default
      _install_fake_mounter(monkeypatch, mounted=True)

      await dm._ensure_personalized_ddi_mounted(conn)

      assert conn.ddi_mounted is True
      assert ("ddi_mounted", {"udid": "UDID-A"}) in pub.events


  @pytest.mark.asyncio
  async def test_ddi_not_mounted_sets_flag_false_and_emits_event(monkeypatch):
      pub = _FakePublisher()
      dm = DeviceManager(event_publisher=pub)
      conn = _ActiveConnection(udid="UDID-B", lockdown=object(), ios_version="17.0")
      conn.ddi_mounted = True  # pretend a stale prior True
      _install_fake_mounter(monkeypatch, mounted=False)

      await dm._ensure_personalized_ddi_mounted(conn)

      assert conn.ddi_mounted is False
      assert any(etype == "ddi_not_mounted" for etype, _ in pub.events)
  ```
- [ ] **Step 2: Run it & see it fail.** Run `cd backend && .venv/bin/python -m pytest tests/test_ddi_mounted_flag.py -q`. Expected: FAIL — `AttributeError` is avoided because the dataclass has no `ddi_mounted` yet; the first assert `conn.ddi_mounted is False` raises `TypeError`/`AttributeError` on the missing field, OR the `assert conn.ddi_mounted is True` fails. Either way, red.
- [ ] **Step 3: Add the dataclass field.** In `backend/core/device_manager.py`, in the `_ActiveConnection` dataclass, after the line `usbmux_lockdown: object = None  # Original lockdown client (for legacy fallback on iOS 17+)` (L237), add:
  ```python
      ddi_mounted: bool = False  # Last personalized-DDI status check result;
                                 # set in _ensure_personalized_ddi_mounted where
                                 # the DdiMounted/DdiNotMounted event is published.
                                 # Read by GET /api/system/info (not re-probed).
  ```
- [ ] **Step 4: Set the flag on the mounted path.** In `_ensure_personalized_ddi_mounted`, in the `if mounted:` block (L732-739), change it so the flag is set before the event. Replace:
  ```python
          if mounted:
              logger.info("Personalized DDI already mounted on %s; DVT should work", conn.udid)
              try:
                  if self._events is not None:
                      await self._events.publish(DdiMountedEvent(udid=conn.udid))
              except Exception:
                  pass
              return
  ```
  with:
  ```python
          if mounted:
              logger.info("Personalized DDI already mounted on %s; DVT should work", conn.udid)
              conn.ddi_mounted = True
              try:
                  if self._events is not None:
                      await self._events.publish(DdiMountedEvent(udid=conn.udid))
              except Exception:
                  pass
              return
  ```
- [ ] **Step 5: Set the flag on the not-mounted path.** In the same method, the warning + `DdiNotMountedEvent` publish block (L741-756). Immediately after the `logger.warning("Personalized DDI is NOT mounted ...)` call and before the `try:` that publishes `DdiNotMountedEvent`, set the flag false. Replace:
  ```python
          logger.warning(
              "Personalized DDI is NOT mounted on %s. LocWarp will not "
              "auto-mount; please mount DDI for this iPhone first, then "
              "reconnect.", conn.udid,
          )
          try:
              if self._events is not None:
                  await self._events.publish(DdiNotMountedEvent(
  ```
  with:
  ```python
          logger.warning(
              "Personalized DDI is NOT mounted on %s. LocWarp will not "
              "auto-mount; please mount DDI for this iPhone first, then "
              "reconnect.", conn.udid,
          )
          conn.ddi_mounted = False
          try:
              if self._events is not None:
                  await self._events.publish(DdiNotMountedEvent(
  ```
- [ ] **Step 6: Run it & see it pass.** Run `cd backend && .venv/bin/python -m pytest tests/test_ddi_mounted_flag.py -q`. Expected: `2 passed`.
- [ ] **Step 7: Run the existing device-manager event tests (no regression).** Run `cd backend && .venv/bin/python -m pytest tests/test_device_manager_events.py -q`. Expected: all pass (the DDI event payloads are unchanged — `ddi_mounted` is an internal field, not in the event model).
- [ ] **Step 8: Run the full backend suite.** Run `cd backend && .venv/bin/python -m pytest -q`. Expected: `961 passed` (959 prior + 2 new), 0 failed.
- [ ] **Step 9: Commit.** Run `cd backend && git add core/device_manager.py tests/test_ddi_mounted_flag.py && git commit -m "feat(c4): store ddi_mounted on _ActiveConnection at the DDI status check

_ensure_personalized_ddi_mounted now records the personalized-DDI status on
conn.ddi_mounted (in addition to the transient DdiMounted/DdiNotMounted
event) so GET /api/system/info can report it without re-probing
MobileImageMounter. Event payloads unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"`.

---

### Task 6: `GET /api/system/info` endpoint

**Files:**
- Modify: `backend/api/system.py` — add a `GET /info` route (the router prefix is already `/api/system`, so the full path is `/api/system/info`). It reads the injected `device_manager` (via `api.deps.get_device_manager`) and `helper_client` (via `api.deps.get_helper_client`), and probes `services.geo_offline` at request time. Survey conclusion (master spec): NEW endpoint — `api/system.py` only has open-log/open-log-folder/shutdown; `GET /` returns only version + initial_position.
- Modify: `backend/.importlinter` — add `    api.system -> api.deps` to the `ignore_imports =` block of the `independence` contract (right after the `api.route -> api.deps` line). This exemption is NEW (not pre-existing); without it the independence contract breaks as soon as `api/system.py` imports `api.deps`.
- Test: `backend/tests/test_system_info_api.py` (Create)

**Interfaces:**
- Consumes:
  - `get_device_manager(request)` → `DeviceManager` (`api/deps.py:13`). `DeviceManager._connections: Dict[str, _ActiveConnection]` (each conn has `.udid`, `.ios_version`, `.connection_type`, and now `.ddi_mounted` from Task 5).
  - `get_helper_client(request)` → `TunnelHelperClient` (`api/deps.py:34`). Has `.is_connected: bool` (property: `_writer`/`_reader` non-None) and `async ping() -> dict`.
  - `services.geo_offline.resolve(lat, lng) -> tuple[str,str,str,str]` — never raises; returns `("","","","")` on failure. Probe with a fixed inland coordinate.
- Produces: `GET /api/system/info` → HTTP 200 JSON:
  ```json
  {
    "version": "<from config or '0.0.0'>",
    "helper_alive": true,
    "offline_geo_ok": true,
    "devices": [{"udid": "...", "ios": "17.0", "ddi_mounted": true, "connection_type": "USB"}]
  }
  ```
  `helper_alive` = `helper_client.is_connected AND (await ping() succeeded)`; if `is_connected` is False, `helper_alive=false` and ping is NOT attempted. `offline_geo_ok` = the resolver returned a non-empty country/timezone for the probe coordinate (request-time probe; catches its own failure → `false`, never 500s the whole response). Never raises `HTTPException` for the probe paths.

- [ ] **Step 1: Confirm `config` exposes a version (or fall back).** Run `cd backend && grep -nE "^VERSION|APP_VERSION|version" config.py | head`. If a version constant exists, use it; otherwise the route uses the literal `"0.0.0"`. (Record which you found; the test below tolerates any non-empty string.)
- [ ] **Step 2: Write the failing test.** Create `backend/tests/test_system_info_api.py` with COMPLETE content. It uses the same `TestClient(main.app)` + `main.app.state.container` harness as `tests/test_geocode_api.py`:
  ```python
  """GET /api/system/info exposes helper-aliveness, per-device {ios, ddi_mounted},
  and offline_geo_ok — the otherwise restart-only health states, made queryable.
  Mirrors the TestClient + app.state.container harness used by test_geocode_api.py.
  """
  from __future__ import annotations

  import pytest
  from fastapi.testclient import TestClient


  @pytest.fixture
  def client():
      import main
      return TestClient(main.app)


  def test_info_shape_and_offline_geo_ok_true(monkeypatch, client):
      import main
      import services.geo_offline as geo_offline
      from core.device_manager import _ActiveConnection

      dm = main.app.state.container.device_manager
      # Seed one fake connected device with the new ddi_mounted flag set.
      conn = _ActiveConnection(udid="UDID-1", lockdown=object(), ios_version="17.0")
      conn.ddi_mounted = True
      conn.connection_type = "USB"
      monkeypatch.setattr(dm, "_connections", {"UDID-1": conn})

      # offline geo probe returns a real country/timezone -> ok True.
      monkeypatch.setattr(
          geo_offline, "resolve", lambda _lat, _lng: ("us", "America/New_York", "New York", "New York")
      )

      res = client.get("/api/system/info")
      assert res.status_code == 200
      body = res.json()
      assert isinstance(body["version"], str) and body["version"]
      assert body["offline_geo_ok"] is True
      assert isinstance(body["helper_alive"], bool)
      assert body["devices"] == [
          {"udid": "UDID-1", "ios": "17.0", "ddi_mounted": True, "connection_type": "USB"}
      ]


  def test_info_offline_geo_ok_false_when_resolver_blank(monkeypatch, client):
      import main
      import services.geo_offline as geo_offline

      monkeypatch.setattr(geo_offline, "resolve", lambda _lat, _lng: ("", "", "", ""))
      res = client.get("/api/system/info")
      assert res.status_code == 200
      assert res.json()["offline_geo_ok"] is False


  def test_info_offline_geo_ok_false_when_resolver_raises(monkeypatch, client):
      """The probe must catch its own failure -> offline_geo_ok False, never 500."""
      import main
      import services.geo_offline as geo_offline

      def boom(_lat, _lng):
          raise RuntimeError("simulated geo crash")

      monkeypatch.setattr(geo_offline, "resolve", boom)
      res = client.get("/api/system/info")
      assert res.status_code == 200
      assert res.json()["offline_geo_ok"] is False


  def test_info_helper_alive_false_when_not_connected(monkeypatch, client):
      import main

      helper = main.app.state.container.helper_client
      # Force is_connected False so ping is never attempted and helper_alive=False.
      monkeypatch.setattr(type(helper), "is_connected", property(lambda self: False))
      res = client.get("/api/system/info")
      assert res.status_code == 200
      assert res.json()["helper_alive"] is False
  ```
- [ ] **Step 3: Run it & see it fail.** Run `cd backend && .venv/bin/python -m pytest tests/test_system_info_api.py -q`. Expected: FAIL — `/api/system/info` returns 404 (route not added yet).
- [ ] **Step 4: Add imports + the route to `api/system.py`.** At the top of `backend/api/system.py`, after the line `from fastapi import APIRouter, HTTPException` (L9), change it to also import `Depends`:
  ```python
  from fastapi import APIRouter, Depends, HTTPException
  ```
  Then add, after the existing imports block (after `from pathlib import Path` at L7, the import edits above), a deps import:
  ```python
  from api.deps import get_device_manager, get_helper_client
  ```
  Then append this route at the END of `api/system.py` (after the `shutdown()` handler):
  ```python


  # Fixed inland probe coordinate for the offline-geo health check. Times Square,
  # NYC — far from any ocean band so a healthy resolver always returns a real
  # country/timezone. The value is irrelevant beyond "resolver returns non-empty".
  _GEO_PROBE_LAT = 40.7580
  _GEO_PROBE_LNG = -73.9855


  def _resolve_version() -> str:
      """Backend version string for the info payload. Reads config.VERSION /
      config.APP_VERSION if present; falls back to '0.0.0' so /info never 500s
      on a missing constant."""
      import config
      for attr in ("VERSION", "APP_VERSION"):
          val = getattr(config, attr, None)
          if isinstance(val, str) and val:
              return val
      return "0.0.0"


  @router.get("/info")
  async def system_info(
      device_manager=Depends(get_device_manager),
      helper_client=Depends(get_helper_client),
  ):
      """Expose the otherwise restart-only health states so they are queryable
      live: tunnel-helper aliveness, per-device {ios, ddi_mounted}, and whether
      the offline geo resolver is functioning. Never 500s on a probe failure —
      each probe degrades to a falsy field.
      """
      # helper aliveness: derived (no stored handshake flag). If not connected,
      # skip ping entirely. If connected, a successful ping confirms aliveness.
      helper_alive = False
      try:
          if helper_client is not None and helper_client.is_connected:
              await helper_client.ping()
              helper_alive = True
      except Exception:
          logger.debug("helper ping failed during /info probe", exc_info=True)
          helper_alive = False

      # offline geo: request-time probe; resolve() never raises by contract, but
      # we still guard so a stubbed/broken resolver can never 500 the response.
      offline_geo_ok = False
      try:
          import services.geo_offline as geo_offline
          cc, tz, _city, _region = geo_offline.resolve(_GEO_PROBE_LAT, _GEO_PROBE_LNG)
          offline_geo_ok = bool(cc or tz)
      except Exception:
          logger.debug("offline geo probe failed during /info", exc_info=True)
          offline_geo_ok = False

      # per-device: read the live _connections map (each conn carries the stored
      # ddi_mounted flag set in _ensure_personalized_ddi_mounted).
      devices = []
      for udid, conn in dict(device_manager._connections).items():
          devices.append({
              "udid": udid,
              "ios": getattr(conn, "ios_version", "0.0"),
              "ddi_mounted": bool(getattr(conn, "ddi_mounted", False)),
              "connection_type": getattr(conn, "connection_type", "USB"),
          })

      return {
          "version": _resolve_version(),
          "helper_alive": helper_alive,
          "offline_geo_ok": offline_geo_ok,
          "devices": devices,
      }
  ```
- [ ] **Step 5: Run it & see it pass.** Run `cd backend && .venv/bin/python -m pytest tests/test_system_info_api.py -q`. Expected: `4 passed`. If `test_info_helper_alive_false_when_not_connected` fails because `is_connected` is a property that can't be patched on the class, instead patch the instance's `_writer`/`_reader` to `None` (`monkeypatch.setattr(helper, "_writer", None)`); but try the property patch first.
- [ ] **Step 6: Add the `api.system -> api.deps` exemption to `.importlinter` AND verify import-linter stays green.** The `independence` contract's `ignore_imports =` block whitelists `api.bookmarks`, `api.device`, `api.cloud_sync`, `api.geocode`, `api.location`, `api.phone_control`, and `api.route` → `api.deps`, but NOT `api.system`. Adding `from api.deps import get_device_manager, get_helper_client` to `api/system.py` (Step 4) introduces an `api.system -> api.deps` edge that is NOT pre-exempted, which would leave import-linter RED (`7 kept` → `6 kept, 1 broken`). In the SAME commit as the route edit (Step 8), also edit `backend/.importlinter` to append `    api.system -> api.deps` to the `ignore_imports =` block (right after the `api.route -> api.deps` line). Then run `cd backend && .venv/bin/python -m pytest tests/test_import_contracts_enforced.py -q` to confirm `7 kept, 0 broken` before committing. The new route also imports `services.geo_offline`/`config` — none of which violate the forbidden edges (no `core→api`, no `infra→api`, services don't import fastapi here).
- [ ] **Step 7: Run the full backend suite.** Run `cd backend && .venv/bin/python -m pytest -q`. Expected: `965 passed` (961 prior + 4 new), 0 failed.
- [ ] **Step 8: Commit.** Run `cd backend && git add api/system.py .importlinter tests/test_system_info_api.py && git commit -m "feat(c4): add GET /api/system/info for live health states

Expose tunnel-helper aliveness (is_connected + ping), per-device
{ios, ddi_mounted}, and offline_geo_ok (request-time resolver probe) so the
otherwise restart-only latches are queryable live. Each probe degrades to a
falsy field — the endpoint never 500s on a probe failure. Reads device_manager
+ helper_client via the existing api.deps providers.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw"`.

---

### Task 7: Whole-cluster green gate + final verification

**Files:** none modified — this task only runs the full gate and (if needed) records evidence. No commit unless a fix is required (in which case that fix follows its own test-first micro-cycle).

**Interfaces:** Consumes the four CI gates named in Global Constraints.

- [ ] **Step 1: Backend suite.** Run `cd backend && .venv/bin/python -m pytest -q`. Expected: `965 passed`, 0 failed (no skips introduced by this cluster).
- [ ] **Step 2: Import-linter (all 7 contracts).** Run `cd backend && .venv/bin/python -m pytest tests/test_import_contracts_enforced.py tests/test_import_contracts_fail_on_probe.py tests/test_import_linter.py -q`. Expected: all pass — `7 kept, 0 broken`.
- [ ] **Step 3: Frontend type check (must stay green; cluster touched no frontend).** Run `cd frontend && npx tsc --noEmit`. Expected: 0 errors.
- [ ] **Step 4: Frontend vitest (must stay green).** Run `cd frontend && npx vitest run 2>&1 | tail -5`. Expected: ≈773 passed, 0 failed.
- [ ] **Step 5: Dependency-cruiser (must stay green).** Run `cd frontend && npx depcruise --config .dependency-cruiser.cjs src 2>&1 | tail -3` (use the repo's actual depcruise invocation — check `frontend/package.json` `scripts` for the exact `depcruise` command if this differs). Expected: `0 errors, 0 warnings` (`no dependency violations found`).
- [ ] **Step 6: Self-check binary smoke in dev (proves the wiring end-to-end without a full DMG).** Run `cd backend && .venv/bin/python main.py --self-check; echo "exit=$?"`. Expected: `SELF-CHECK OK: 7 native imports` and `exit=0`.
- [ ] **Step 7: Record evidence.** Confirm and report: backend `965 passed`; import-linter `7 kept, 0 broken`; tsc `0 errors`; vitest green; depcruise `0/0`; `--self-check` exit 0. This cluster is then complete and mergeable to `main` (direct commit per personal-repo conventions — no PR ceremony).
