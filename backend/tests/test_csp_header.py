"""CSP header is present on responses; dev profile is looser (allows Vite),
strict profile omits unsafe-inline for scripts. Config.CSP_MODE selects
the policy string. Note: renderer-paints-under-CSP requires Playwright/Electron
smoke (a unit test cannot exercise the rendered DOM)."""
import main
from fastapi.testclient import TestClient


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
    assert "localhost:5173" in csp or "ws:" in csp
