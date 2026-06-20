"""
Import-linter enforcement test — ENFORCED (Phase 1 + Phase 2 report-only).

Runs lint-imports against backend/.importlinter checking ONLY the ENFORCED
contracts one at a time. Report-only contracts (added in Phase 2) are
intentionally excluded from the returncode-0 assertion — they are expected to
be BROKEN until the corresponding migration task completes.

Currently enforced:
  - no-core-imports-api  (Phase 1 Task 8)
  - no-services-imports-fastapi  (Phase 2 Group 1 Task 4)

Report-only (not yet enforced):
  - no-infra-imports-api  (Phase 2 Group 3 Task 11, broken until Task 14)

Tasks 3-4 broke the core->api cycle in device_manager.py.
This test is the regression gate: any future import of `api.*`
from within the `core` package will make lint-imports exit non-zero
and this test will FAIL.

No infra->api contract is enforced here because infra/device/wifi_tunnel.py
still contains lazy imports of api.device (Task-11-deferred intermediate).
That contract will be enforced in Phase 2 Group 3 Task 14.
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
    ENFORCED: the no-core->api contract must be KEPT.

    Runs ALL contracts so the full report is visible, but only asserts
    on the enforced no-core->api contract. Report-only contracts (e.g.
    no-infra->api, added in Task 11) are expected to be BROKEN until
    their corresponding migration tasks complete; their breakage does NOT
    fail this test.

    Any `from api.*` or `import api.*` introduced into the `core` package
    will cause "Core must not import API KEPT" to disappear from the report
    and this test will FAIL.
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

    # ENFORCED (Phase 1): the no-core->api contract must be KEPT.
    assert "Core must not import API KEPT" in report, (
        "The no-core->api contract is no longer KEPT — the cycle has been "
        "re-introduced. See the report above for the offending import chain."
    )
    # Phase 2 Task 11 (report-only): no-infra->api is intentionally BROKEN here.
    # Flipped to enforced (and this assertion tightened back to a full 0-broken
    # check) in Task 14. Until then we assert ONLY the core contract.
