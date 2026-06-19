"""CSP header is present on responses; dev profile is looser (allows Vite),
strict profile omits unsafe-inline for scripts. Config.CSP_MODE selects
the policy string. Note: renderer-paints-under-CSP requires Playwright/Electron
smoke (a unit test cannot exercise the rendered DOM).

Also verifies that /phone gets a route-specific relaxed CSP (Leaflet + OSM
tiles) while non-phone responses keep the stricter default policy."""
import re
from pathlib import Path

import main
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PHONE_HTML = Path(__file__).resolve().parent.parent / "static" / "phone.html"


def _parse_csp(csp: str) -> dict[str, str]:
    """Return a dict mapping directive name -> directive value (remainder)."""
    result = {}
    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        pieces = part.split(None, 1)
        key = pieces[0].lower()
        val = pieces[1] if len(pieces) > 1 else ""
        result[key] = val
    return result


def _extract_phone_html_origins() -> dict:
    """
    Parse phone.html and return a dict describing what the page actually loads:
      - external_script_origins: set of https://... hosts referenced in <script src>
      - external_style_origins:  set of https://... hosts referenced in <link href>
      - tile_origins:            set of https://... tile URL patterns in JS
      - has_inline_script:       bool — page has an inline <script> block
      - has_inline_style:        bool — page has an inline <style> block
    """
    src = PHONE_HTML.read_text(encoding="utf-8")

    external_script_origins: set[str] = set()
    for m in re.finditer(r'<script[^>]+src=["\']?(https://[^"\'>\s]+)', src, re.I):
        url = m.group(1)
        # Normalise to scheme://host (strip path)
        parsed = re.match(r'(https://[^/]+)', url)
        if parsed:
            external_script_origins.add(parsed.group(1))

    external_style_origins: set[str] = set()
    for m in re.finditer(r'<link[^>]+href=["\']?(https://[^"\'>\s]+)', src, re.I):
        url = m.group(1)
        parsed = re.match(r'(https://[^/]+)', url)
        if parsed:
            external_style_origins.add(parsed.group(1))

    # Tile URLs e.g. 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
    tile_origins: set[str] = set()
    for m in re.finditer(r"['\"]?(https://[^'\">\s]*tile[^'\">\s]*)['\"]?", src, re.I):
        url = m.group(1)
        parsed = re.match(r'(https://[^/]+)', url)
        if parsed:
            origin = parsed.group(1)
            # Wildcard: {s}.tile.openstreetmap.org -> *.tile.openstreetmap.org
            origin = re.sub(r'\{[^}]+\}\.', '*.', origin)
            tile_origins.add(origin)

    has_inline_script = bool(re.search(r'<script(?![^>]*src)[^>]*>', src, re.I))
    has_inline_style = bool(re.search(r'<style[^>]*>', src, re.I))

    return {
        "external_script_origins": external_script_origins,
        "external_style_origins": external_style_origins,
        "tile_origins": tile_origins,
        "has_inline_script": has_inline_script,
        "has_inline_style": has_inline_style,
    }


# ---------------------------------------------------------------------------
# Existing tests (unchanged)
# ---------------------------------------------------------------------------

def test_csp_header_present():
    c = TestClient(main.app)
    r = c.get("/")
    csp = r.headers.get("content-security-policy")
    assert csp is not None
    assert "default-src" in csp


def test_strict_profile_omits_unsafe_inline_for_scripts(monkeypatch):
    monkeypatch.setattr("main.CSP_MODE", "strict")
    c = TestClient(main.app)
    r = c.get("/")
    csp = r.headers.get("content-security-policy", "")
    seg = next((p for p in csp.split(";") if p.strip().startswith("script-src")), "")
    assert "'unsafe-inline'" not in seg


def test_dev_profile_allows_vite(monkeypatch):
    monkeypatch.setattr("main.CSP_MODE", "dev")
    c = TestClient(main.app)
    r = c.get("/")
    csp = r.headers.get("content-security-policy", "")
    assert "ws://localhost:5173" in csp
    assert "localhost:5173" in csp


# ---------------------------------------------------------------------------
# /phone CSP: derived from phone.html actual contents
# ---------------------------------------------------------------------------

def test_phone_csp_admits_all_phone_html_dependencies():
    """
    Parse phone.html's actual external dependencies and assert every one is
    admitted by the CSP served on GET /phone.

    This test is intentionally data-driven from phone.html — adding a new
    external CDN or tile provider to phone.html without updating the CSP will
    fail this test.
    """
    info = _extract_phone_html_origins()
    c = TestClient(main.app)
    r = c.get("/phone")
    csp = r.headers.get("content-security-policy", "")
    directives = _parse_csp(csp)

    script_src = directives.get("script-src", "")
    style_src = directives.get("style-src", "")
    img_src = directives.get("img-src", "")

    # Every external <script src="https://..."> must be in script-src
    for origin in info["external_script_origins"]:
        assert origin in script_src, (
            f"phone.html loads external script from {origin!r} but "
            f"the /phone CSP script-src does not admit it: {script_src!r}"
        )

    # Every external <link href="https://..."> must be in style-src
    for origin in info["external_style_origins"]:
        assert origin in style_src, (
            f"phone.html loads external stylesheet from {origin!r} but "
            f"the /phone CSP style-src does not admit it: {style_src!r}"
        )

    # Inline script must be permitted
    if info["has_inline_script"]:
        assert "'unsafe-inline'" in script_src, (
            "phone.html has inline <script> but the /phone CSP script-src "
            f"does not include 'unsafe-inline': {script_src!r}"
        )

    # Inline style must be permitted
    if info["has_inline_style"]:
        assert "'unsafe-inline'" in style_src, (
            "phone.html has inline <style> but the /phone CSP style-src "
            f"does not include 'unsafe-inline': {style_src!r}"
        )

    # Tile origins (wildcard-normalised) must be in img-src
    for origin in info["tile_origins"]:
        # Convert wildcard pattern *.foo.bar to a regex for checking
        # CSP wildcards: *.foo.bar matches *.foo.bar OR a.foo.bar etc.
        # We just check the domain suffix appears in img-src.
        suffix = origin.lstrip("*")  # e.g. ".tile.openstreetmap.org"
        assert suffix in img_src, (
            f"phone.html loads tiles from {origin!r} (suffix={suffix!r}) but "
            f"the /phone CSP img-src does not cover it: {img_src!r}"
        )


def test_phone_csp_allows_connect_self():
    """phone.html makes fetch() calls to same-origin /api/phone/* endpoints."""
    c = TestClient(main.app)
    r = c.get("/phone")
    csp = r.headers.get("content-security-policy", "")
    directives = _parse_csp(csp)
    connect_src = directives.get("connect-src", directives.get("default-src", ""))
    assert "'self'" in connect_src, (
        f"phone.html makes same-origin API calls but connect-src lacks 'self': {connect_src!r}"
    )


# ---------------------------------------------------------------------------
# Default (non-phone) CSP must NOT admit unpkg.com or OSM tiles
# ---------------------------------------------------------------------------

def test_default_csp_does_not_admit_unpkg_or_osm(monkeypatch):
    """
    The relaxation for /phone must be scoped — the default CSP must NOT
    allow unpkg.com or tile.openstreetmap.org, proving the widening is
    confined to the /phone route.
    """
    # Test both profiles
    for mode in ("strict", "dev"):
        monkeypatch.setattr("main.CSP_MODE", mode)
        c = TestClient(main.app)
        r = c.get("/")
        csp = r.headers.get("content-security-policy", "")
        assert "unpkg.com" not in csp, (
            f"Default CSP ({mode} profile) must not admit unpkg.com but it does: {csp!r}"
        )
        assert "openstreetmap.org" not in csp, (
            f"Default CSP ({mode} profile) must not admit openstreetmap.org but it does: {csp!r}"
        )


def test_api_response_uses_default_csp_not_phone_csp():
    """An API endpoint (non-/phone path) must get the default CSP, not the phone one."""
    c = TestClient(main.app)
    # /api/phone/info is localhost-only so use a simpler endpoint
    r = c.get("/api/phone/_reach")
    csp = r.headers.get("content-security-policy", "")
    assert "unpkg.com" not in csp, (
        f"API response should not receive the phone CSP: {csp!r}"
    )
    assert "openstreetmap.org" not in csp, (
        f"API response should not receive the phone CSP: {csp!r}"
    )
