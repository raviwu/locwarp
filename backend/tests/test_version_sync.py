"""Guard: the backend version constant must stay in lock-step with the frontend
package.json — the canonical app version electron-builder ships. If they drift
(e.g. someone bumps package.json for a release but forgets config.VERSION), this
fails so CI catches it and you bump both together. This is the enforcement half
of the single-source-of-truth: config.VERSION is the baked Python constant, this
test pins it to package.json.
"""
import json
import re
from pathlib import Path

import config

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
BACKEND_ROOT = Path(__file__).resolve().parent.parent


def test_backend_version_matches_package_json():
    pkg_version = json.loads(PACKAGE_JSON.read_text("utf-8"))["version"]
    assert config.VERSION == pkg_version, (
        f"config.VERSION ({config.VERSION!r}) != frontend/package.json version "
        f"({pkg_version!r}) — bump BOTH together on a release"
    )


def test_no_hardcoded_locwarp_version_literal_in_backend():
    """No bare 'LocWarp/<digits>' string may live under backend/ — every
    User-Agent must derive from config.VERSION so the version can never
    silently drift from the shipped build again. (This test file is the
    one allowed mention, since it documents the banned pattern.)"""
    pat = re.compile(r"LocWarp/\d")
    offenders: list[str] = []
    for path in BACKEND_ROOT.rglob("*.py"):
        if path.resolve() == Path(__file__).resolve():
            continue
        if ".venv" in path.parts or "site-packages" in path.parts:
            continue
        text = path.read_text("utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{i}: {line.strip()}")
    assert not offenders, (
        "Hardcoded LocWarp/<version> literal(s) found — build the UA from "
        "config.VERSION instead:\n" + "\n".join(offenders)
    )


def test_overpass_ua_carries_current_version_and_fork_repo():
    from services import geo_extras
    ua = geo_extras._OVERPASS_HEADERS["User-Agent"]
    assert f"LocWarp/{config.VERSION}" in ua
    assert "raviwu/locwarp" in ua
    assert "keezxc1223" not in ua


def test_nominatim_ua_carries_current_version():
    assert f"LocWarp/{config.VERSION}" in config.NOMINATIM_USER_AGENT
