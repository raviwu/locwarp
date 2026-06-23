"""Fail-on-probe regression for the architecture gate.

`test_import_contracts_enforced.py` proves lint-imports PASSES on the clean
tree (`7 kept, 0 broken`). It does NOT prove the gate can FAIL — a contract
that never breaks is indistinguishable from a contract that is never checked.

This test closes that hole. It plants a real cross-layer import (a "probe")
under each forbidden edge, asserts lint-imports reports that specific contract
BROKEN (non-zero exit), then removes the probe. import-linter does static
import-graph analysis, so the probe module need not be runnable.

CRITICAL — leak hygiene: a probe file left behind poisons the REAL gate for
every other test in the suite. Cleanup is guaranteed three ways:
  1. start-of-test guard (autouse fixture) deletes any stale probe from a
     crashed prior run, before AND after the test;
  2. each probe write is wrapped in try/finally that deletes the file;
  3. an end-of-test assertion re-runs lint-imports on the restored tree and
     requires `0 broken`, proving cleanup actually worked.
"""
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

# Probe modules live directly under the source rings so grimp picks them up as
# part of the `core` / `services` packages it already scans.
CORE_PROBE = BACKEND / "core" / "_p5_probe.py"
SERVICES_PROBE = BACKEND / "services" / "_p5_probe.py"

# Contract names (the `name = ...` lines in .importlinter) as import-linter
# prints them in the per-contract "BROKEN" summary line of its stdout.
CORE_API_CONTRACT = "Core must not import API"
SERVICES_FASTAPI_CONTRACT = "Services must not import FastAPI"


def _run_lint_imports() -> subprocess.CompletedProcess:
    # Use the installed console-script (Path(sys.executable).parent / 'lint-imports'),
    # exactly as test_import_contracts_enforced.py does. `python -m importlinter.cli
    # lint` has no __main__ guard and exits 0 silently — it can never detect broken
    # contracts, making any assertion vacuous.
    lint_imports_bin = Path(sys.executable).parent / "lint-imports"
    return subprocess.run(
        [str(lint_imports_bin)],
        cwd=str(BACKEND), capture_output=True, text=True)


@pytest.fixture(autouse=True)
def _no_stale_probe():
    """Belt-and-suspenders: nuke any leftover probe from a crashed run before
    this test, and again after, so neither this test nor the real gate is ever
    poisoned by a stray probe file."""
    CORE_PROBE.unlink(missing_ok=True)
    SERVICES_PROBE.unlink(missing_ok=True)
    try:
        yield
    finally:
        CORE_PROBE.unlink(missing_ok=True)
        SERVICES_PROBE.unlink(missing_ok=True)


def _assert_contract_broken(combined: str, returncode: int, contract_name: str):
    # import-linter prints "Contracts: ..." then one line per contract; broken
    # contracts read e.g. "Core must not import API BROKEN". Assert both the
    # non-zero exit AND that THIS specific contract is the one named broken, so a
    # break in some unrelated contract can't make the probe pass spuriously.
    assert "Contracts:" in combined, (
        f"lint-imports produced no 'Contracts:' output — invocation broken?\n{combined!r}"
    )
    assert returncode != 0, (
        f"lint-imports should FAIL with the probe present but exited 0:\n{combined}"
    )
    assert f"{contract_name} BROKEN" in combined, (
        f"expected contract {contract_name!r} reported BROKEN; got:\n{combined}"
    )


def test_lint_imports_breaks_on_core_to_api_probe():
    # A real, unambiguous core -> api edge. The module need not import cleanly;
    # grimp only needs the static `from api import ...` statement.
    CORE_PROBE.write_text("from api import device  # noqa: F401  (import-linter probe)\n")
    try:
        proc = _run_lint_imports()
        _assert_contract_broken(
            proc.stdout + proc.stderr, proc.returncode, CORE_API_CONTRACT)
    finally:
        CORE_PROBE.unlink(missing_ok=True)


def test_lint_imports_breaks_on_services_to_fastapi_probe():
    # A real services -> fastapi edge, the exact thing no-services-imports-fastapi
    # forbids.
    SERVICES_PROBE.write_text("import fastapi  # noqa: F401  (import-linter probe)\n")
    try:
        proc = _run_lint_imports()
        _assert_contract_broken(
            proc.stdout + proc.stderr, proc.returncode, SERVICES_FASTAPI_CONTRACT)
    finally:
        SERVICES_PROBE.unlink(missing_ok=True)


def test_clean_tree_restored_after_probes():
    # With both probes removed, the gate must be green again. This both proves
    # the per-probe cleanup worked AND guards the real gate for the rest of the
    # suite (mirrors the assertions in test_import_contracts_enforced.py).
    assert not CORE_PROBE.exists(), f"leaked probe: {CORE_PROBE}"
    assert not SERVICES_PROBE.exists(), f"leaked probe: {SERVICES_PROBE}"
    proc = _run_lint_imports()
    combined = proc.stdout + proc.stderr
    assert "Contracts:" in combined, (
        f"lint-imports produced no 'Contracts:' output — invocation broken?\n{combined!r}"
    )
    assert proc.returncode == 0, (
        f"clean tree should pass but lint-imports exited {proc.returncode}:\n{combined}"
    )
    assert "0 broken" in combined, f"contracts broken on a clean tree:\n{combined}"
