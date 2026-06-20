"""
Import-linter enforcement test — ENFORCED (Phase 1 + Phase 2 Group 3).

Both contracts are now enforced; lint-imports must exit 0.

Currently enforced:
  - no-core-imports-api  (Phase 1 Task 8)
  - no-services-imports-fastapi  (Phase 2 Group 1 Task 4)
  - no-infra-imports-api  (Phase 2 Group 3 Task 14)

Tasks 3-4 broke the core->api cycle in device_manager.py.
Tasks 12-13 relocated tunnel state + restart fn out of wifi_tunnel.py,
removing the last infra->api import edge.
Task 14 flips no-infra->api from report-only to enforced and tightens
this test to assert both no-core->api AND no-infra->api are KEPT with
lint-imports exit code 0.
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
    ENFORCED: both no-core->api and no-infra->api contracts must be KEPT.

    Runs ALL contracts so the full report is visible. Asserts that both
    enforced contracts are KEPT and that lint-imports exits 0 (no broken
    contracts).

    Any `from api.*` or `import api.*` introduced into the `core` or `infra`
    packages will cause this test to FAIL.
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

    # ENFORCED: both contracts must be KEPT.
    assert "Core must not import API" in report, (
        f"Expected 'Core must not import API' in lint-imports output. Got:\n{report}")
    assert "Infra must not import API" in report, (
        f"Expected 'Infra must not import API' in lint-imports output. Got:\n{report}")
    # ENFORCED: exit 0 means all contracts kept, 0 broken.
    assert result.returncode == 0, (
        "lint-imports reported broken contracts — either the no-core->api cycle "
        "or the no-infra->api edge has been re-introduced.")
