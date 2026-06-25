"""The fragile native chain (PyInstaller metadata-gap history) must be pinned
to == in requirements.txt so every DMG builds against a byte-reproducible
import graph. Pure-Python floors may stay >=; the native chain may not.

Historical incidents this guards (see CLAUDE.md "PyInstaller copy_metadata
gap"): pyimg4 / apple_compress / prompt_toolkit / h3 each silently no-op'd
DDI mount or offline geo in the packaged app only.
"""
from __future__ import annotations

import re
from pathlib import Path

REQ_PATH = Path(__file__).resolve().parent.parent / "requirements.txt"

# Distribution names as they appear on a requirement line. pip normalizes
# underscore <-> hyphen, so we compare case-insensitively with both forms.
NATIVE_CHAIN = [
    "pymobiledevice3",
    "pyimg4",
    "apple_compress",
    "h3",
    "prompt_toolkit",
    "timezonefinder",
    "numpy",
]


def _parse_requirements() -> dict[str, str]:
    """Map normalized dist-name -> the operator+version spec on its line.

    Ignores comments and blank lines. Normalizes name by lowercasing and
    replacing '_' with '-' (PEP 503 style) so apple_compress == apple-compress.
    """
    specs: dict[str, str] = {}
    for raw in REQ_PATH.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip an inline extras spec like uvicorn[standard] before matching.
        m = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(.*)$", line)
        if not m:
            continue
        name = m.group(1).lower().replace("_", "-")
        spec = m.group(3).strip()
        specs[name] = spec
    return specs


def test_native_chain_is_pinned_with_double_equals():
    specs = _parse_requirements()
    missing: list[str] = []
    unpinned: list[str] = []
    for pkg in NATIVE_CHAIN:
        key = pkg.lower().replace("_", "-")
        if key not in specs:
            missing.append(pkg)
            continue
        spec = specs[key]
        if not spec.startswith("=="):
            unpinned.append(f"{pkg} -> {spec!r}")
    assert not missing, f"native-chain deps absent from requirements.txt: {missing}"
    assert not unpinned, f"native-chain deps not == pinned: {unpinned}"
