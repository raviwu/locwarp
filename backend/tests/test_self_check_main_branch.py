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
