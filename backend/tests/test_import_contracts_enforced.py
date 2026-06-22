"""All required import-linter contracts must be ENFORCED and pass (the architecture gate)."""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

REQUIRED_CONTRACTS = {
    "no-core-imports-api", "no-services-imports-fastapi", "no-infra-imports-api",
    "no-api-imports-api", "no-api-imports-main", "no-domain-imports-outer",
    "no-infra-imports-fastapi",
}


def test_importlinter_config_declares_all_required_contracts():
    cfg = (BACKEND / ".importlinter").read_text()
    for name in REQUIRED_CONTRACTS:
        assert f"contract:{name}]" in cfg, f"missing contract: {name}"
    for pkg in ("api", "core", "services", "models", "domain", "infra"):
        assert pkg in cfg, f"root_packages missing {pkg}"


def test_lint_imports_passes_with_zero_broken():
    # Use the installed console-script (Path(sys.executable).parent / 'lint-imports').
    # `python -m importlinter.cli lint` has no __main__ guard and exits 0 silently —
    # it can never detect broken contracts, making any assertion vacuous.
    lint_imports_bin = Path(sys.executable).parent / "lint-imports"
    proc = subprocess.run(
        [str(lint_imports_bin)],
        cwd=str(BACKEND), capture_output=True, text=True)
    combined = proc.stdout + proc.stderr
    # Self-check: a silent no-op invocation must not masquerade as a pass.
    assert "Contracts:" in combined, (
        f"lint-imports produced no 'Contracts:' output — invocation broken?\n{combined!r}"
    )
    assert proc.returncode == 0, f"lint-imports failed (exit {proc.returncode}):\n{combined}"
    assert "0 broken" in combined, f"one or more contracts are broken:\n{combined}"
