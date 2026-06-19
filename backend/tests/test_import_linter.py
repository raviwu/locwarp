"""
Import-linter report-only test.

Runs lint-imports against backend/.importlinter and PRINTS the full
violation report so it is visible in `pytest -s` output. The test is
GREEN regardless of violations — we expect the core→api contract to be
BROKEN in Phase 0.

Phase 1 flips this to enforced (assert returncode == 0).
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


def test_import_linter_report_only():
    """
    Run lint-imports in report-only mode.

    Asserts only that:
    1. The linter executed (process didn't crash unexpectedly).
    2. The output mentions the contract by name, confirming the graph
       was built and the contract was evaluated.

    Violations are expected and intentionally NOT asserted against.
    # Phase 1 flips this to enforced (assert returncode == 0).
    """
    result = subprocess.run(
        [str(LINT_IMPORTS), "--config", str(IMPORTLINTER_CFG)],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_DIR),
    )

    report = result.stdout + result.stderr
    print("\n--- import-linter report ---\n")
    print(report)
    print("--- end report (exit code:", result.returncode, ") ---\n")

    # The linter must have run and evaluated at least one contract.
    assert "Core must not import API" in report, (
        "Expected the contract name 'Core must not import API' in lint-imports output. "
        f"Got:\n{report}"
    )
    # Confirm the expected violation is visible (documents Phase 0 state).
    assert "BROKEN" in report or "broken" in report.lower(), (
        "Expected at least one broken contract in Phase 0 — "
        "core.device_manager deferred imports of api.* were not detected."
    )
    # Phase 1 flips this to enforced (assert returncode == 0).
