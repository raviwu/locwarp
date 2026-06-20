"""
Import-linter enforcement test — ENFORCED (Phase 1 + Phase 2 report-only).

Runs lint-imports against backend/.importlinter checking ONLY the ENFORCED
contracts one at a time. Report-only contracts (added in Phase 2) are
intentionally excluded from the returncode-0 assertion — they are expected to
be BROKEN until the corresponding migration task completes.

Currently enforced:
  - no-core-imports-api  (Phase 1 Task 8)

Report-only (not checked here until flipped to ENFORCED at Group-1 exit):
  - no-services-imports-fastapi  (Phase 2 Group 1 Task 2, broken until Task 3)

Tasks 3-4 broke the core->api cycle in device_manager.py.
This test is the regression gate: any future import of `api.*`
from within the `core` package will make lint-imports exit non-zero
and this test will FAIL.

No infra->api contract is enforced here because infra/device/wifi_tunnel.py
still contains a lazy import of api.device._tunnels (Task-7-deferred
intermediate). That contract remains deferred to Phase 2.
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
    ENFORCED: the no-core->api contract must be KEPT (exit 0, 0 broken).

    Uses --contract to check ONLY the enforced no-core-imports-api contract,
    excluding report-only contracts that are intentionally still broken.

    Asserts:
    1. The linter executed and evaluated the contract (name appears in output).
    2. lint-imports exits with returncode == 0 (0 broken contracts).

    Any `from api.*` or `import api.*` introduced into the `core` package
    will break this test. The full report is printed on failure for diagnostics.
    """
    result = subprocess.run(
        [
            str(LINT_IMPORTS),
            "--config", str(IMPORTLINTER_CFG),
            "--contract", "no-core-imports-api",
        ],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_DIR),
    )

    report = result.stdout + result.stderr
    print("\n--- import-linter report ---\n")
    print(report)
    print("--- end report (exit code:", result.returncode, ") ---\n")

    # The linter must have run and evaluated the contract.
    assert "Core must not import API" in report, (
        "Expected the contract name 'Core must not import API' in lint-imports output. "
        f"Got:\n{report}"
    )

    # ENFORCED: exit 0 means all contracts kept, 0 broken.
    assert result.returncode == 0, (
        "lint-imports reported broken contracts — the no-core->api cycle has been "
        "re-introduced. See the report above for the offending import chain."
    )
