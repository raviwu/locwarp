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
