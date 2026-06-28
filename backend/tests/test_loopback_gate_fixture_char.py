"""The autouse conftest fixture must make a default-constructed TestClient
present a LOOPBACK client.host (127.0.0.1), not the starlette sentinel
'testclient' (which is non-loopback and would be rejected by the A1 gate).
An explicit client= must still be honoured so A5 can fake a LAN peer."""
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


def _probe_app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(request: Request):
        return {"host": request.client.host if request.client else None}

    return app


def test_default_testclient_presents_loopback_host():
    c = TestClient(_probe_app())
    assert c.get("/whoami").json()["host"] == "127.0.0.1"


def test_explicit_client_is_still_honoured():
    c = TestClient(_probe_app(), client=("192.168.1.50", 9999))
    assert c.get("/whoami").json()["host"] == "192.168.1.50"
