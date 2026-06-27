"""Guard: the backend version constant must stay in lock-step with the frontend
package.json — the canonical app version electron-builder ships. If they drift
(e.g. someone bumps package.json for a release but forgets config.VERSION), this
fails so CI catches it and you bump both together. This is the enforcement half
of the single-source-of-truth: config.VERSION is the baked Python constant, this
test pins it to package.json.
"""
import json
from pathlib import Path

import config

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"


def test_backend_version_matches_package_json():
    pkg_version = json.loads(PACKAGE_JSON.read_text("utf-8"))["version"]
    assert config.VERSION == pkg_version, (
        f"config.VERSION ({config.VERSION!r}) != frontend/package.json version "
        f"({pkg_version!r}) — bump BOTH together on a release"
    )
