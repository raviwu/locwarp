"""Frozen-binary import self-check.

Run via `locwarp-backend --self-check` (wired in main.py BEFORE the heavy
backend imports are needed, but AFTER they would normally happen — see
main.py). Imports the whole fragile native chain that PyInstaller has
historically failed to bundle metadata for, and exits non-zero on the first
failure so build-installer-mac.sh can turn "dev-good / DMG-broken" into a
build-time red.

This module imports NOTHING from the backend at module load (only stdlib),
so the --self-check branch stays cheap and isolated. The native packages are
imported lazily inside run_self_check via importlib.

The probed chain mirrors the three documented metadata fixes in
locwarp-backend.spec:
  1. mobile_image_mounter -> pyimg4 -> apple_compress  (DDI mount path)
  2. service_connection   -> prompt_toolkit            (IPython edge)
  3. geo_offline          -> timezonefinder -> h3       (offline geo path)
"""
from __future__ import annotations

import importlib
import sys

# (human_label, dotted_module) — ordered. The first failing import wins.
NATIVE_IMPORT_CHAIN: list[tuple[str, str]] = [
    ("mobile_image_mounter", "pymobiledevice3.services.mobile_image_mounter"),
    ("pyimg4", "pyimg4"),
    ("apple_compress", "apple_compress"),
    ("service_connection", "pymobiledevice3.service_connection"),
    ("prompt_toolkit", "prompt_toolkit"),
    ("timezonefinder", "timezonefinder"),
    ("h3", "h3"),
]


def run_self_check(out=sys.stdout) -> int:
    """Import each native-chain module in order. Return 0 if all import,
    1 on the first failure (printing the offending module + exception)."""
    for label, module in NATIVE_IMPORT_CHAIN:
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 — surface ANY import-time failure
            print(
                f"SELF-CHECK FAILED: {label} ({module}): "
                f"{type(exc).__name__}: {exc}",
                file=out,
            )
            return 1
    print(f"SELF-CHECK OK: {len(NATIVE_IMPORT_CHAIN)} native imports", file=out)
    return 0
