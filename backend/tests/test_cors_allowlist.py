"""CORS reflects only allowlisted origins; '*' is gone. Uses TestClient
against the live main.app to exercise the real middleware stack."""
import main
from fastapi.testclient import TestClient


def _client():
    return TestClient(main.app)


def test_allowlisted_vite_origin_is_reflected():
    c = _client()
    origin = "http://localhost:5173"
    r = c.get("/", headers={"Origin": origin})
    assert r.headers.get("access-control-allow-origin") == origin


def test_allowlisted_loopback_origin_is_reflected():
    c = _client()
    origin = "http://127.0.0.1:8777"
    r = c.get("/", headers={"Origin": origin})
    assert r.headers.get("access-control-allow-origin") == origin


def test_wildcard_is_not_returned():
    """Wildcard must not appear — neither as ACAO value nor reflected to an evil origin."""
    c = _client()
    r = c.get("/", headers={"Origin": "http://evil.example.com"})
    acao = r.headers.get("access-control-allow-origin", "")
    assert acao != "*"
    assert acao != "http://evil.example.com"


def test_cors_origins_config_has_no_wildcard():
    """config.CORS_ORIGINS must not contain '*'."""
    from config import CORS_ORIGINS
    assert "*" not in CORS_ORIGINS
