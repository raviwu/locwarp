"""All five import-linter contracts must be ENFORCED and pass (the architecture gate)."""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

REQUIRED_CONTRACTS = {
    "no-core-imports-api", "no-services-imports-fastapi", "no-infra-imports-api",
    "no-api-imports-api", "no-api-imports-main",
}


def test_importlinter_config_declares_all_five_contracts():
    cfg = (BACKEND / ".importlinter").read_text()
    for name in REQUIRED_CONTRACTS:
        assert f"contract:{name}]" in cfg, f"missing contract: {name}"
    for pkg in ("api", "core", "services", "models", "domain", "infra"):
        assert pkg in cfg, f"root_packages missing {pkg}"


def test_lint_imports_passes_with_zero_broken():
    proc = subprocess.run(
        [sys.executable, "-m", "importlinter.cli", "lint"],
        cwd=str(BACKEND), capture_output=True, text=True)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"lint-imports failed (exit {proc.returncode}):\n{combined}"
    tail = combined.lower().split("contracts:")[-1]
    assert "broken" not in tail or "0 broken" in tail, f"a contract is broken:\n{combined}"
