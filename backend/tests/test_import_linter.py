"""
Import-linter enforcement test — ENFORCED (Phase 1 + Phase 2 Groups 1-4 + Task 29).

All contracts are now enforced; lint-imports must exit 0.

Currently enforced:
  - no-core-imports-api  (Phase 1 Task 8)
  - no-services-imports-fastapi  (Phase 2 Group 1 Task 4; cloud_sync_service
    HTTPException whitelisted in ignore_imports — Task 29)
  - no-infra-imports-api  (Phase 2 Group 3 Task 14)
  - no-api-imports-api  (Phase 2 Group 4 Task 19)

Tasks 3-4 broke the core->api cycle in device_manager.py.
Tasks 12-13 relocated tunnel state + restart fn out of wifi_tunnel.py,
removing the last infra->api import edge.
Task 14 flips no-infra->api from report-only to enforced.
Tasks 15-18 removed all api->api cross-imports (only api.deps DI shim remains).
Task 19 enforces no-api-imports-api with api.deps exempt.
Task 29 adds the ignore_imports whitelist and asserts all four contracts KEPT.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
IMPORTLINTER_CFG = BACKEND_DIR / ".importlinter"

# Resolve lint-imports relative to the running interpreter so this works on
# both Unix (.venv/bin/lint-imports) and Windows (.venv/Scripts/lint-imports.exe).
_bindir = Path(sys.executable).parent
_name = "lint-imports.exe" if os.name == "nt" else "lint-imports"
LINT_IMPORTS = _bindir / _name
if not LINT_IMPORTS.exists():
    LINT_IMPORTS = shutil.which("lint-imports") or str(LINT_IMPORTS)


def test_import_linter_enforced():
    """
    ENFORCED (Task 29): all four established contracts must be present and KEPT.

    Runs ALL contracts so the full report is visible. Asserts that:
      - Core must not import API         (no-core-imports-api)
      - Services must not import FastAPI (no-services-imports-fastapi;
        cloud_sync_service HTTPException is whitelisted — retained to
        preserve the frozen cloud-sync 400/500 HTTP status surface)
      - Infra must not import API        (no-infra-imports-api)
      - API modules must not import each other (no-api-imports-api)

    And that lint-imports exits 0 (no broken contracts).
    """
    result = subprocess.run(
        [
            str(LINT_IMPORTS),
            "--config", str(IMPORTLINTER_CFG),
        ],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_DIR),
    )

    report = result.stdout + result.stderr
    print("\n--- import-linter report ---\n")
    print(report)
    print("--- end report (exit code:", result.returncode, ") ---\n")

    # All four established contracts must be KEPT.
    assert "Core must not import API" in report, (
        f"Expected 'Core must not import API' in lint-imports output. Got:\n{report}")
    assert "Services must not import FastAPI" in report, (
        f"Expected 'Services must not import FastAPI' in lint-imports output. Got:\n{report}")
    assert "Infra must not import API" in report, (
        f"Expected 'Infra must not import API' in lint-imports output. Got:\n{report}")
    assert "API modules must not import each other" in report, (
        f"Expected 'API modules must not import each other' in lint-imports output. Got:\n{report}")
    # ENFORCED: exit 0 means all contracts kept, 0 broken.
    assert result.returncode == 0, (
        "lint-imports reported broken contracts — one of the four enforced "
        "contracts (no-core->api, no-services->fastapi, no-infra->api, "
        f"no-api->api) is BROKEN. Report:\n{report}")


def test_no_api_imports_api_contract_enforced():
    """
    ENFORCED (Task 19): API modules must not import each other.

    The sole sanctioned exception is the DI shim: any api.* module may import
    api.deps (so FastAPI Depends() wiring works). All other api->api imports
    are forbidden. Tasks 15-18 removed every such import; this test locks the
    invariant so no future commit re-introduces one.

    Any `from api.<x> import` (where x != deps) introduced into any api module
    will cause this test to FAIL.
    """
    result = subprocess.run(
        [
            str(LINT_IMPORTS),
            "--config", str(IMPORTLINTER_CFG),
        ],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_DIR),
    )

    report = result.stdout + result.stderr
    print("\n--- import-linter report ---\n")
    print(report)
    print("--- end report (exit code:", result.returncode, ") ---\n")

    # Contract must appear in the report and be KEPT.
    assert "API modules must not import each other" in report, (
        f"Expected 'API modules must not import each other' in lint-imports output. Got:\n{report}"
    )
    # ENFORCED: exit 0 means all contracts kept, 0 broken.
    assert result.returncode == 0, (
        "lint-imports reported broken contracts — the no-api-imports-api contract "
        "(or another contract) is BROKEN. Check the report above."
    )


def test_no_api_imports_main_contract_present_and_kept():
    """The Phase-2 cycle-gate: api/* must not import the composition root."""
    result = subprocess.run(
        [str(LINT_IMPORTS), "--config", str(IMPORTLINTER_CFG)],
        capture_output=True, text=True, cwd=str(BACKEND_DIR))
    report = result.stdout + result.stderr
    assert "API must not import main" in report, (
        f"Expected the no-api-imports-main contract in output. Got:\n{report}")
    assert result.returncode == 0, (
        "no-api-imports-main is BROKEN — a `from main import ...` survives in "
        f"the api package. Report:\n{report}")


def test_zero_from_main_import_under_api():
    """Defense-in-depth grep gate: no `from main import` anywhere in api/."""
    api_dir = BACKEND_DIR / "api"
    offenders = []
    for path in api_dir.rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            if "from main import" in line:
                offenders.append(f"{path.relative_to(BACKEND_DIR)}:{i}: {line.strip()}")
    assert not offenders, "Residual `from main import` in api/:\n" + "\n".join(offenders)
