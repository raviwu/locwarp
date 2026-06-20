"""Tests for domain.errors — pure, stdlib-only domain error types."""
from __future__ import annotations

import ast
import pathlib

import pytest

from domain.errors import GeocodeError


def test_geocode_error_stores_fields():
    e = GeocodeError(status_code=502, code="google_http", detail="Google geocode HTTP 403: boom")
    assert e.status_code == 502
    assert e.code == "google_http"
    assert e.detail == "Google geocode HTTP 403: boom"


def test_geocode_error_str_is_detail():
    e = GeocodeError(status_code=400, code="missing_key", detail="provider=google requires google_key")
    assert str(e) == "provider=google requires google_key"


def test_geocode_error_is_exception():
    assert issubclass(GeocodeError, Exception)
    with pytest.raises(GeocodeError):
        raise GeocodeError(status_code=400, code="x", detail="y")


def test_errors_module_imports_no_outer_rings():
    path = pathlib.Path(__file__).resolve().parent.parent / "domain" / "errors.py"
    tree = ast.parse(path.read_text())
    banned = {"fastapi", "httpx", "starlette", "api", "services", "core", "infra"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in banned, alias.name
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in banned, node.module
