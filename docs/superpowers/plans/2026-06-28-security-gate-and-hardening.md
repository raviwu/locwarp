# Security Gate + Repo-Reference Cleanup + Reliability Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the LAN device-control auth hole, fix the cross-platform repo references, harden the DeviceManager connect/discover paths, and land four quick wins — without changing any external contract for legitimate callers.

**Architecture:** Four independently-committable workstreams. A fail-closed loopback middleware at the composition root (`main.py`) gates the main API; a pre-accept loopback+Origin guard protects `/ws/status`; a shared `REPO_SLUG` constant unifies the fork's repo references; an atomic claim + try/finally close the DeviceManager races; quick wins fix a missing broadcast, CI hang-safety, and zero-risk memoization.

**Tech Stack:** Python 3.13 / FastAPI / pytest (backend); React + TypeScript + Vite + Electron / vitest (frontend); import-linter + dependency-cruiser gates.

**Spec:** `docs/superpowers/specs/2026-06-28-security-gate-and-hardening-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Behavior freeze:** no external HTTP / WS / IPC contract change EXCEPT the new `403 {"code":"lan_forbidden"}` (HTTP) and `close(1008)` (WS) for illegitimate (non-loopback / remote-Origin) callers.
- **Test baselines (pin before starting):** backend `cd backend && .venv/bin/python -m pytest --collect-only -q` ≈ **1043** collected; frontend vitest ≈ **869**; `cd frontend && npx tsc --noEmit` clean. Full backend pytest + frontend vitest stay green after EVERY commit.
- **Gates green after every structural change:** `cd backend && .venv/bin/python -m lint_imports` (7 contracts kept, 0 broken) + frontend dependency-cruiser (0 errors).
- **Clean-arch:** `api/*` may NOT import another `api/*` — shared web helpers live inline at the composition root (`main.py`) or in `domain/` (pure). Confirmed: the loopback helper is duplicated inline in `main.py` (middleware) and `api/websocket.py` rather than crossing an api→api edge.
- **Danger-zone-test-first:** `core/device_manager.py` and the `api/` request edge have no/low direct tests — write the characterization test BEFORE the edit.
- **Distribution rule (verbatim):** frontend single constant `REPO_SLUG = 'raviwu/locwarp'`; the app's own surfaces (UpdateChecker, About, geo-UA, release-footer, README **macOS** download) point at the fork `raviwu/locwarp`; the README **Windows** download + upstream Issues / community-PR links stay `keezxc1223/locwarp` (the fork ships no `.exe`).
- **Electron Origin (confirmed):** the production renderer loads via `loadFile` → WS `Origin` is `file://` / `null`, which the A2 guard explicitly allows — so the A2-Origin enhancement ships (not deferred).
- **Personal repo:** direct commits to `main`; git identity is auto-set by includeIf — NEVER pass `-c user.email=...`.

---

## Workstream A — Close the LAN device-control hole (security, danger-zone)

### Task 1: Conftest loopback-default fixture (unblocks the gate without breaking 54 existing TestClient tests)

**Files:**
- Modify: `/Users/raviwu/personal/locwarp/backend/tests/conftest.py` (add an autouse fixture after the existing `_isolate_real_data_paths`, ~line 60+)
- Test: `/Users/raviwu/personal/locwarp/backend/tests/test_loopback_gate_fixture_char.py` (Create)

**Interfaces:**
- Consumes: `starlette.testclient.TestClient.__init__` default `client` kwarg (`("testclient", 50000)`)
- Produces: every `TestClient(main.app)` constructed without an explicit `client=` now defaults to `client=("127.0.0.1", 50000)` (loopback) — relied on by Tasks 2 and 4 so existing tests stay green once the gate lands.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_loopback_gate_fixture_char.py
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
```
- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_loopback_gate_fixture_char.py -q`
Expected: FAIL — `test_default_testclient_presents_loopback_host` asserts `'127.0.0.1' == 'testclient'` (the unpatched starlette default sentinel).
- [ ] **Step 3: Write minimal implementation**
```python
# Append to tests/conftest.py (after _isolate_real_data_paths)

@pytest.fixture(autouse=True)
def _testclient_defaults_to_loopback(monkeypatch):
    """The A1 HTTP gate rejects non-loopback callers. Starlette's TestClient
    defaults its transport client tuple to ('testclient', 50000) — a
    NON-loopback host that the gate would 403. Redirect that default to
    127.0.0.1 so the existing ~54 TestClient(main.app) suites keep exercising
    the loopback (legitimate-caller) path. Tests that want to simulate a LAN
    peer pass an explicit client=(...) which is preserved verbatim.
    """
    import starlette.testclient as _st

    _orig_init = _st.TestClient.__init__

    def _patched_init(self, *args, **kwargs):
        kwargs.setdefault("client", ("127.0.0.1", 50000))
        return _orig_init(self, *args, **kwargs)

    monkeypatch.setattr(_st.TestClient, "__init__", _patched_init)
```
- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_loopback_gate_fixture_char.py -q`
Expected: PASS (both tests)
- [ ] **Step 5: Commit**
```bash
git add backend/tests/conftest.py backend/tests/test_loopback_gate_fixture_char.py && git commit -m "test(security): default TestClient host to loopback for the A1 gate"
```

---

### Task 2: A5 HTTP gate characterization tests (test-first, danger zone)

**Files:**
- Test: `/Users/raviwu/personal/locwarp/backend/tests/test_lan_http_gate_char.py` (Create)

**Interfaces:**
- Consumes: Task 1's loopback-default fixture; `main.app`; `TestClient(main.app, client=("192.168.1.50", 9999))` to fake a LAN peer.
- Produces: the behavioral contract A3 (Task 3) must satisfy — non-loopback → 403 `{"code": "lan_forbidden"}`; loopback → unaffected; `/api/phone*` + `/phone` reach the router from any host.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_lan_http_gate_char.py
"""Characterization tests for the A1 fail-closed LAN HTTP gate.

Locks the contract BEFORE the middleware exists:
  - non-loopback caller -> 403 {"code": "lan_forbidden"} on the main API
    (mutating routes AND GET /api/system/info, which leaks udid/iOS).
  - loopback caller -> unaffected (existing behavior preserved).
  - /api/phone* and /phone reach the router from ANY host (the token /
    _is_localhost gate inside the router then applies) — the LAN surface.
"""
import main
from fastapi.testclient import TestClient

LAN = ("192.168.1.50", 9999)  # a non-loopback peer on the same WiFi


def _lan_client():
    return TestClient(main.app, client=LAN)


def _loopback_client():
    # Task-1 fixture already defaults to 127.0.0.1, but be explicit here.
    return TestClient(main.app, client=("127.0.0.1", 50000))


# --- non-loopback is rejected fail-closed ---------------------------------
def test_lan_peer_blocked_on_mutating_route():
    r = _lan_client().post("/api/location/teleport", json={"lat": 1.0, "lng": 2.0})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "lan_forbidden"


def test_lan_peer_blocked_on_system_info_leak():
    r = _lan_client().get("/api/system/info")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "lan_forbidden"


def test_lan_peer_blocked_on_system_shutdown():
    r = _lan_client().post("/api/system/shutdown")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "lan_forbidden"


def test_lan_peer_blocked_on_root():
    # Fail-closed: even the harmless banner route is gated for LAN peers.
    r = _lan_client().get("/")
    assert r.status_code == 403


# --- loopback is unaffected ------------------------------------------------
def test_loopback_reaches_root():
    r = _loopback_client().get("/")
    assert r.status_code == 200
    assert r.json()["name"] == "LocWarp"


def test_loopback_reaches_system_info():
    r = _loopback_client().get("/api/system/info")
    assert r.status_code == 200
    assert "devices" in r.json()


# --- phone surface stays LAN-reachable from any host -----------------------
def test_lan_peer_reaches_phone_token_gate_not_lan_gate():
    """A LAN peer hitting a token-gated phone endpoint must pass the A1 gate
    and be rejected by the phone TOKEN gate (401), NOT the LAN gate (403)."""
    r = _lan_client().get("/api/phone/status")  # no token
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "phone_auth_required"


def test_lan_peer_reaches_phone_page():
    r = _lan_client().get("/phone")
    assert r.status_code == 200


def test_lan_peer_reaches_phone_reach_probe():
    r = _lan_client().get("/api/phone/_reach")
    assert r.status_code == 200
```
- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lan_http_gate_char.py -q`
Expected: FAIL — no gate yet, so `_lan_client()` calls return their normal status (root → 200, system/info → 200, teleport → 4xx but not 403 `lan_forbidden`), so the `test_lan_peer_blocked_*` assertions fail.
- [ ] **Step 3: Write minimal implementation**
No implementation in this task — tests are red by design. (The gate is built in Task 3.)
- [ ] **Step 4: Run test to verify it passes**
N/A this task — proceed to Task 3, which turns these green.
- [ ] **Step 5: Commit**
```bash
git add backend/tests/test_lan_http_gate_char.py && git commit -m "test(security): A5 char tests for the fail-closed LAN HTTP gate (red)"
```

---

### Task 3: A1 fail-closed HTTP loopback middleware + A3 CORS hardening

**Files:**
- Modify: `/Users/raviwu/personal/locwarp/backend/main.py:1143` (CORS `allow_credentials`), `/Users/raviwu/personal/locwarp/backend/main.py:23-24` (add `JSONResponse` import), `/Users/raviwu/personal/locwarp/backend/main.py:~1185` (add the gate middleware adjacent to the CSP middleware)
- (turns Task 2's red tests green)

**Interfaces:**
- Consumes: Task 2's char tests; `request.client.host`; `request.url.path`.
- Produces: a fail-closed `@app.middleware("http")` gate. ALLOW loopback (`127.0.0.0/8`, `::1`) OR path under `/api/phone` / `== "/phone"`; else 403 `{"detail": {"code": "lan_forbidden"}}`.

- [ ] **Step 1: Write the failing test**
Reuse Task 2's `tests/test_lan_http_gate_char.py` (already red). No new test file.
- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lan_http_gate_char.py -q`
Expected: FAIL — the `test_lan_peer_blocked_*` cases still return 200/non-403.
- [ ] **Step 3: Write minimal implementation**

Add the import (main.py:24, after `from fastapi.middleware.cors import CORSMiddleware`):
```python
from fastapi.responses import JSONResponse
```

Flip CORS credentials (main.py:1143):
```python
    allow_credentials=False,
```

Add the gate middleware immediately AFTER the existing `_csp_middleware` definition (main.py, after line 1195). Added last → runs first (outermost), so a LAN peer is rejected before any handler work:
```python
import ipaddress as _ipaddress


def _is_loopback_host(host: str | None) -> bool:
    """True iff host is in 127.0.0.0/8 or is ::1. Broadens phone_control's
    exact-match notion to the full loopback block. uvicorn binds directly
    (no reverse proxy) so request.client.host is trustworthy — there is no
    X-Forwarded-For spoofing surface to honour."""
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return _ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# Paths reachable from the LAN (a real phone over WiFi). Everything else on
# the main API is loopback-only. The /api/phone/* router enforces its own
# PIN/token gate; /phone serves the phone page; both are intentionally LAN-open.
def _is_lan_allowed_path(path: str) -> bool:
    return path.startswith("/api/phone") or path == "/phone"


@app.middleware("http")
async def _lan_gate_middleware(request, call_next):
    """Fail-closed LAN gate: only loopback callers may reach the main API.
    Any FUTURE endpoint is auto-protected unless explicitly allowlisted —
    this is what makes the 'forgot to gate a new route' class of bug
    impossible. The phone surface (/api/phone*, /phone) stays LAN-reachable
    and keeps its own token / _is_localhost gate (defense in depth)."""
    client = request.client
    host = client.host if client else None
    if not _is_loopback_host(host) and not _is_lan_allowed_path(request.url.path):
        return JSONResponse(status_code=403, content={"detail": {"code": "lan_forbidden"}})
    return await call_next(request)
```
- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lan_http_gate_char.py tests/test_cors_allowlist.py tests/test_csp_header.py tests/test_phone_auth_gate.py tests/test_system_info_api.py -q`
Expected: PASS (the LAN gate tests go green; loopback-default fixture keeps CORS/CSP/phone/system suites green). Then run the full suite to confirm no regression across the 54 TestClient callers and that the collected count is still 1043 + the new tests:
`cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q`
- [ ] **Step 5: Commit**
```bash
git add backend/main.py && git commit -m "feat(security): fail-closed loopback gate on the main API + CORS allow_credentials=False"
```

---

### Task 4: A5 WebSocket gate characterization tests (test-first, danger zone)

**Files:**
- Test: `/Users/raviwu/personal/locwarp/backend/tests/test_ws_lan_gate_char.py` (Create)

**Interfaces:**
- Consumes: `from api.websocket import websocket_endpoint`; the existing direct-call `FakeWebSocket` pattern from `test_ws_joystick_fanout_char.py` (extended with `.client`, `.headers`, `.close()`).
- Produces: the WS-guard contract for Task 5 — non-loopback `ws.client` → `close(1008)`, never `accept()`; loopback → `accept()`; remote http(s) `Origin` → `close(1008)`; absent/`null`/`file://`/allowlisted Origin → `accept()`.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_ws_lan_gate_char.py
"""Characterization tests for the A2 WebSocket gate in api/websocket.py.

A2-core: a non-loopback ws.client is rejected with close(1008) before
accept() — closes the LAN-peer joystick takeover.

A2-Origin (shipped: the production Electron renderer loads via loadFile,
so its WS Origin is file:// / null / absent — NOT in CORS_ORIGINS): a
present REMOTE http(s) Origin not in CORS_ORIGINS is rejected; an absent /
null / file:// / allowlisted Origin is accepted.
"""
from __future__ import annotations

import pytest

from api.websocket import websocket_endpoint

pytestmark = pytest.mark.asyncio


class _State:
    pass


class _Container:
    def __init__(self, engine_registry) -> None:
        self.engine_registry = engine_registry


class _App:
    def __init__(self, container) -> None:
        self.state = _State()
        self.state.container = container


class _Registry:
    simulation_engines: dict = {}

    def get_engine(self, udid):
        return None


class _Addr:
    def __init__(self, host: str) -> None:
        self.host = host


class FakeWS:
    """Direct-call double (same approach as test_ws_joystick_fanout_char).
    Records accept/close and immediately disconnects after accept so the
    receive loop exits cleanly."""

    def __init__(self, host: str, headers: dict | None = None) -> None:
        self.app = _App(_Container(_Registry()))
        self.client = _Addr(host)
        self.headers = headers or {}
        self.accepted = False
        self.closed_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code

    async def receive_text(self) -> str:
        from fastapi import WebSocketDisconnect
        raise WebSocketDisconnect()


# --- A2-core: loopback vs LAN peer ----------------------------------------
async def test_lan_peer_ws_rejected_before_accept():
    ws = FakeWS("192.168.1.50")
    await websocket_endpoint(ws)
    assert ws.accepted is False
    assert ws.closed_code == 1008


async def test_loopback_ws_accepted():
    ws = FakeWS("127.0.0.1")
    await websocket_endpoint(ws)
    assert ws.accepted is True
    assert ws.closed_code is None


# --- A2-Origin: drive-by webpage on the same machine ----------------------
async def test_loopback_ws_with_remote_origin_rejected():
    ws = FakeWS("127.0.0.1", headers={"origin": "http://evil.example.com"})
    await websocket_endpoint(ws)
    assert ws.accepted is False
    assert ws.closed_code == 1008


async def test_loopback_ws_with_file_origin_accepted():
    # The shipped Electron renderer (loadFile) presents file:// / null.
    ws = FakeWS("127.0.0.1", headers={"origin": "file://"})
    await websocket_endpoint(ws)
    assert ws.accepted is True


async def test_loopback_ws_with_null_origin_accepted():
    ws = FakeWS("127.0.0.1", headers={"origin": "null"})
    await websocket_endpoint(ws)
    assert ws.accepted is True


async def test_loopback_ws_with_allowlisted_dev_origin_accepted():
    ws = FakeWS("127.0.0.1", headers={"origin": "http://localhost:5173"})
    await websocket_endpoint(ws)
    assert ws.accepted is True
```
- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_ws_lan_gate_char.py -q`
Expected: FAIL — current `websocket_endpoint` unconditionally `accept()`s, so `test_lan_peer_ws_rejected_before_accept` and the remote-Origin test fail (`accepted is True`, `closed_code is None`).
- [ ] **Step 3: Write minimal implementation**
No implementation in this task — red by design. Built in Task 5.
- [ ] **Step 4: Run test to verify it passes**
N/A this task — Task 5 turns these green.
- [ ] **Step 5: Commit**
```bash
git add backend/tests/test_ws_lan_gate_char.py && git commit -m "test(security): A5 char tests for the WS loopback+Origin gate (red)"
```

---

### Task 5: A2 WebSocket guard (loopback + Origin) in api/websocket.py

**Files:**
- Modify: `/Users/raviwu/personal/locwarp/backend/api/websocket.py:29-33` (insert the guard before `await ws.accept()`)
- (turns Task 4's red tests green)

**Interfaces:**
- Consumes: Task 4's char tests; `ws.client.host`; `ws.headers.get("origin")`; `config.CORS_ORIGINS`.
- Produces: a pre-accept guard. Reject (close 1008) if `ws.client.host` is not loopback; else if a remote http(s) `Origin` is present and not in `CORS_ORIGINS`, reject; else accept. `import-linter`-safe: `api/websocket.py` imports `config` (allowed), no `api/*`→`api/*` edge.

- [ ] **Step 1: Write the failing test**
Reuse Task 4's `tests/test_ws_lan_gate_char.py` (already red). No new test file.
- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_ws_lan_gate_char.py -q`
Expected: FAIL — unconditional `accept()` still in place.
- [ ] **Step 3: Write minimal implementation**

Add imports at the top of `api/websocket.py` (after the existing imports, ~line 7):
```python
import ipaddress

import config
```

Insert a module-level helper above `websocket_endpoint` (after line 13, the `_connections` list):
```python
def _ws_origin_allowed(origin: str | None) -> bool:
    """Drive-by-webpage guard. The shipped Electron renderer loads via
    loadFile() -> WS Origin is absent / 'null' / 'file://' (NOT a remote
    http(s) origin, NOT in CORS_ORIGINS). Allow those plus any allowlisted
    origin; reject a present REMOTE http(s) origin (a malicious local page
    in the user's own browser — loopback, so the client-host check alone
    cannot stop it)."""
    if not origin or origin == "null" or origin.startswith("file:"):
        return True
    if origin in config.CORS_ORIGINS:
        return True
    return False


def _ws_client_is_loopback(ws: WebSocket) -> bool:
    host = ws.client.host if ws.client else None
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
```

Replace the opening of `websocket_endpoint` (current lines 30-31):
```python
async def websocket_endpoint(ws: WebSocket):
    # Security gate (before accept): the joystick WS is loopback-only — the
    # desktop UI is a 127.0.0.1 client; the phone uses /api/phone/*. A LAN
    # peer or a drive-by remote-Origin page must never drive the device.
    if not _ws_client_is_loopback(ws) or not _ws_origin_allowed(ws.headers.get("origin")):
        await ws.close(code=1008)
        return
    await ws.accept()
```
- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_ws_lan_gate_char.py tests/test_ws_joystick_fanout_char.py -q`
Expected: PASS (new WS gate tests green; the existing fan-out char test still green — its `FakeWebSocket` has no `.client`, so confirm it provides one; if the fan-out fake lacks `.client`/`.headers`, the guard would `AttributeError`. The fan-out fake's `FakeWebSocket` must expose `client` and `headers` — extend it in this commit: add `self.client = _Addr("127.0.0.1")` and `self.headers = {}` to `test_ws_joystick_fanout_char.py`'s `FakeWebSocket`). Then run the import-linter + full suite:
`cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q && cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m lint_imports`
- [ ] **Step 5: Commit**
```bash
git add backend/api/websocket.py backend/tests/test_ws_joystick_fanout_char.py && git commit -m "feat(security): loopback + Origin guard on /ws/status before accept"
```

---

### Task 6: A4 fix the false config.py comment

**Files:**
- Modify: `/Users/raviwu/personal/locwarp/backend/config.py:207-210`
- Test: `/Users/raviwu/personal/locwarp/backend/tests/test_lan_http_gate_char.py` (extend with a doc-truth assertion)

**Interfaces:**
- Consumes: the A1 middleware (Task 3) + A2 guard (Task 5) now make the model true.
- Produces: none (documentation correctness).

- [ ] **Step 1: Write the failing test**
Append to `tests/test_lan_http_gate_char.py`:
```python
def test_config_comment_no_longer_claims_cors_closes_lan():
    """A4: the old comment falsely claimed the main API LAN surface was closed
    by the phone PIN gate + CORS allowlist. After A1/A2 the real model is the
    loopback gate. Lock that the stale 'CORS allowlist' assertion is gone and
    the loopback model is documented."""
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "config.py"
    text = src.read_text(encoding="utf-8")
    block = text[text.index("API_HOST = "):]  # the API_HOST region's comment
    # The false assertion (CORS allowlist closes the main-API LAN exposure)
    # must no longer appear in the API_HOST comment block.
    head = text[:text.index("API_HOST = ")]
    assert "loopback" in head.lower()
    assert "not by loopback bind" not in head
```
- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lan_http_gate_char.py::test_config_comment_no_longer_claims_cors_closes_lan -q`
Expected: FAIL — current comment contains "not by loopback bind" and lacks the new loopback-gate wording.
- [ ] **Step 3: Write minimal implementation**
Replace `config.py:207-210`:
```python
# Server — API_HOST must stay 0.0.0.0 (LAN bind). phone.html is served to a
# real phone over WiFi; narrowing to 127.0.0.1 would silently break it.
# Main-API LAN exposure is closed at the app layer, NOT by the bind: a
# fail-closed loopback middleware (main.py _lan_gate_middleware) rejects any
# non-loopback caller, and the /ws/status WebSocket has a loopback + Origin
# guard (api/websocket.py). The ONLY LAN-reachable surface is /api/phone/* +
# /phone, gated by its own PIN/token (api/phone_control.py).
```
- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lan_http_gate_char.py -q`
Expected: PASS
- [ ] **Step 5: Commit**
```bash
git add backend/config.py backend/tests/test_lan_http_gate_char.py && git commit -m "docs(security): correct config.py LAN-exposure comment to the loopback-gate model"
```

---

**Workstream-A wrap-up note (run before considering A done):** full backend suite + import-linter must be green —
`cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m lint_imports`
(baseline was 1043 collected; expect 1043 + the new char tests). No frontend change in Workstream A, so vitest/tsc are untouched. The A2-Origin enhancement IS included (not deferred) because the production Electron renderer was empirically confirmed to load via `loadFile` at `frontend/electron/main.js:455` → `file://`/`null` Origin, which the guard explicitly allows.

---

## Workstream B — Repo references + UA quick-win (distribution)

### Task 7: Shared `REPO_SLUG` constant (frontend) routing UpdateChecker

**Files:**
- Create: `frontend/src/contract/repo.ts`
- Create: `frontend/src/contract/repo.test.ts`
- Modify: `frontend/src/components/UpdateChecker.tsx`:5
- Modify (test): `frontend/src/components/UpdateChecker.test.tsx`:49-77

**Interfaces:**
- Consumes: none
- Produces: `export const REPO_SLUG = 'raviwu/locwarp'` and `export const REPO_URL = 'https://github.com/raviwu/locwarp'` from `frontend/src/contract/repo.ts` (consumed by Task 8)

- [ ] **Step 1: Write the failing test**
```typescript
// frontend/src/contract/repo.test.ts
import { describe, it, expect } from 'vitest'
import { REPO_SLUG, REPO_URL } from './repo'

describe('repo slug single source', () => {
  it('points the app-owned (DMG) surfaces at the raviwu fork', () => {
    // The macOS DMG is shipped from raviwu/locwarp — UpdateChecker + the
    // in-app About link must resolve here. Windows-only surfaces (README
    // .exe download) deliberately stay at keezxc1223 and do NOT use this.
    expect(REPO_SLUG).toBe('raviwu/locwarp')
  })

  it('derives the canonical repo URL from the slug (no second hardcode)', () => {
    expect(REPO_URL).toBe('https://github.com/raviwu/locwarp')
  })
})
```
- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/contract/repo.test.ts`
Expected: FAIL — module `./repo` does not exist (resolve error / "Failed to load url ./repo").
- [ ] **Step 3: Write minimal implementation**
```typescript
// frontend/src/contract/repo.ts
// Single source for the GitHub repo this app build belongs to. The macOS DMG
// ships from raviwu/locwarp, so every app-owned surface that links "home"
// (UpdateChecker's release check, the ControlPanel About link) must route
// through this constant — never re-hardcode the slug. The Windows .exe lives
// in the upstream keezxc1223/locwarp repo, so Windows-only README download
// links stay at keezxc1223 and deliberately do NOT consume this.
export const REPO_SLUG = 'raviwu/locwarp'
export const REPO_URL = `https://github.com/${REPO_SLUG}`
```
Then route `UpdateChecker.tsx` through it — replace `frontend/src/components/UpdateChecker.tsx:5`:
```typescript
// remove: const REPO = 'raviwu/locwarp';
import { REPO_SLUG } from '../contract/repo';
// ...then below the imports:
const REPO = REPO_SLUG;
```
(Concretely: change line 2 area to add the import after `import pkg from '../../package.json';`, and replace the literal on line 5 with `const REPO = REPO_SLUG;`. The rest of the file — `API_URL`, the `https://github.com/${REPO}/releases/latest` fallback — is unchanged.)

Also harden the existing UpdateChecker test so the slug is asserted, not just embedded in a fixture. Append this case to `frontend/src/components/UpdateChecker.test.tsx` inside the `describe('useUpdateCheck', ...)` block (after the line-105 `})` of the last `it`, before the closing `})`):
```typescript
  it('routes the release check through the raviwu fork repo slug', async () => {
    const fetchMock = mockFetchOnce({ tag_name: 'v9.9.9' })
    vi.stubGlobal('fetch', fetchMock)
    render(<Probe />)

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    // The hook must hit the raviwu fork's releases API (DMG home), not upstream.
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.github.com/repos/raviwu/locwarp/releases/latest',
      expect.anything(),
    )
    // The generic-fallback URL (no html_url) must also be the raviwu fork.
    expect(screen.getByTestId('url')).toHaveTextContent(
      'https://github.com/raviwu/locwarp/releases/latest',
    )
  })
```
- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/contract/repo.test.ts src/components/UpdateChecker.test.tsx && npx tsc --noEmit`
Expected: PASS — both files green, tsc clean.
- [ ] **Step 5: Commit**
```bash
git add frontend/src/contract/repo.ts frontend/src/contract/repo.test.ts frontend/src/components/UpdateChecker.tsx frontend/src/components/UpdateChecker.test.tsx && git commit -m "refactor(frontend): route UpdateChecker through shared REPO_SLUG constant"
```

---

### Task 8: ControlPanel About link routed through `REPO_SLUG`

**Files:**
- Modify: `frontend/src/components/ControlPanel.tsx`:1061 (href) + :1075 (display text)
- Test: `frontend/src/components/ControlPanel.test.tsx` (extend if present; else create)

**Interfaces:**
- Consumes: `REPO_SLUG`, `REPO_URL` from `frontend/src/contract/repo.ts` (Task 7)
- Produces: none

- [ ] **Step 1: Write the failing test**
First confirm whether a test file exists: `ls frontend/src/components/ControlPanel.test.tsx`. ControlPanel is heavy (drag/portal/many props), so a full render is brittle — assert the source instead, matching the repo's grep-as-assertion style used for non-render-friendly surfaces. Create `frontend/src/components/ControlPanel.repo.test.ts`:
```typescript
// frontend/src/components/ControlPanel.repo.test.ts
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { REPO_SLUG } from '../contract/repo'

const src = readFileSync(
  fileURLToPath(new URL('./ControlPanel.tsx', import.meta.url)),
  'utf-8',
)

describe('ControlPanel About link', () => {
  it('uses the shared REPO_SLUG, not a hardcoded keezxc1223 slug', () => {
    // The in-app footer ("LocWarp by …") ships inside the macOS DMG, so it
    // must point home to the raviwu fork via the shared constant.
    expect(src).toContain('REPO_SLUG')
    expect(src).not.toContain('keezxc1223')
  })

  it('the shared slug is the raviwu fork', () => {
    expect(REPO_SLUG).toBe('raviwu/locwarp')
  })
})
```
- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/ControlPanel.repo.test.ts`
Expected: FAIL — `src` still contains `keezxc1223` (`href="https://github.com/keezxc1223/locwarp"` at :1061 and the `keezxc1223/locwarp` display text at :1075) and does not yet reference `REPO_SLUG`.
- [ ] **Step 3: Write minimal implementation**
Add the import near the top of `ControlPanel.tsx` (with the other imports):
```typescript
import { REPO_SLUG, REPO_URL } from '../contract/repo';
```
Replace the hardcoded href at `:1061`:
```tsx
        <a
          href={REPO_URL}
```
Replace the hardcoded display text at `:1075`:
```tsx
          {REPO_SLUG}
```
(The footer label `<span>LocWarp by</span>` at :1059 and the SVG stay as-is. Net result: the link and its text both resolve to `raviwu/locwarp`.)
- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/ControlPanel.repo.test.ts && npx tsc --noEmit`
Expected: PASS — source references `REPO_SLUG`/`REPO_URL`, no `keezxc1223` remains in the file; tsc clean.
- [ ] **Step 5: Commit**
```bash
git add frontend/src/components/ControlPanel.tsx frontend/src/components/ControlPanel.repo.test.ts && git commit -m "fix(frontend): point ControlPanel About link at raviwu fork via REPO_SLUG"
```

---

### Task 9: Backend Overpass + Nominatim UA built from `config.VERSION` + raviwu, with version-sync grep guard

**Files:**
- Modify: `backend/config.py`:132 (`NOMINATIM_USER_AGENT`)
- Modify: `backend/services/geo_extras.py`:138-144 (`_OVERPASS_HEADERS`)
- Modify (test): `backend/tests/test_version_sync.py` (add the literal-grep guard)
- Modify (test): `backend/tests/test_geocoding_cov.py`:472-473 (assertion stays valid — verify only)

**Interfaces:**
- Consumes: `config.VERSION` (`"0.3.0"`), `config.NOMINATIM_USER_AGENT`
- Produces: a UA shape `LocWarp/{VERSION} (https://github.com/raviwu/locwarp)` reachable via `config.VERSION` — no bare `LocWarp/<digits>` literal anywhere under `backend/`

> **Verified nuance (drift from spec):** the spec's B2 only named `geo_extras.py:142`, but a second literal exists — `config.py:132 NOMINATIM_USER_AGENT = "LocWarp/0.1"` (consumed by `geocoding.py:36`, asserted in `test_geocoding_cov.py:473`). A strict "grep any `LocWarp/<digits>` under backend/" guard (the spec's stated intent) would catch it, so this task converts BOTH UAs to derive from `config.VERSION`. `test_geocoding_cov.py:473` asserts equality against `geocoding.NOMINATIM_USER_AGENT` (the constant, not a literal), so it stays green automatically.

- [ ] **Step 1: Write the failing test**
Extend `backend/tests/test_version_sync.py` with the grep guard + a UA-shape check:
```python
import re
import config

BACKEND_ROOT = Path(__file__).resolve().parent.parent


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
```
- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_version_sync.py -q`
Expected: FAIL — `test_no_hardcoded_locwarp_version_literal_in_backend` reports `config.py:132` (`LocWarp/0.1`) and `services/geo_extras.py:142` (`LocWarp/0.2.77 (...keezxc1223...)`); `test_overpass_ua_carries_current_version_and_fork_repo` fails (`LocWarp/0.3.0` absent, `keezxc1223` present); `test_nominatim_ua_carries_current_version` fails (`LocWarp/0.3.0` not in `LocWarp/0.1`).
- [ ] **Step 3: Write minimal implementation**
In `backend/config.py`, replace line 132 so the Nominatim UA derives from VERSION (VERSION is defined at line 9, above this point):
```python
NOMINATIM_USER_AGENT = f"LocWarp/{VERSION} (https://github.com/raviwu/locwarp)"
```
In `backend/services/geo_extras.py`, add `from config import VERSION` to the config import (line 16 currently `from config import OSRM_BASE_URL` → `from config import OSRM_BASE_URL, VERSION`), then replace the literal at `:142`:
```python
_OVERPASS_HEADERS = {
    # Overpass enforces User-Agent identification; some mirrors return 406
    # to anonymous clients (the python-httpx default UA gets caught up in
    # bot filters). Mirror what other OSM clients send. Built from
    # config.VERSION so it tracks the shipped build (test_version_sync guards it).
    "User-Agent": f"LocWarp/{VERSION} (https://github.com/raviwu/locwarp)",
    "Accept": "application/json",
}
```
- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_version_sync.py tests/test_geocoding_cov.py -q`
Expected: PASS — grep guard clean, both UA-shape tests green, and `test_headers_contains_user_agent` (geocoding) still passes since it compares against the constant.
- [ ] **Step 5: Commit**
```bash
git add backend/config.py backend/services/geo_extras.py backend/tests/test_version_sync.py && git commit -m "fix(backend): build OSM/Nominatim UA from config.VERSION + raviwu repo; guard against version drift"
```

---

### Task 10: Release-footer README links → raviwu fork

**Files:**
- Modify: `.github/release-footer.md`:4-5
- Test: grep assertion (markdown has no natural unit test)

**Interfaces:**
- Consumes: none
- Produces: none

> **Verified:** these two lines are appended to **raviwu** macOS DMG releases (the fork's `release.yml` is macOS-only), so both README links should resolve to the fork.

- [ ] **Step 1: Write the failing test**
Markdown has no runnable test — use a concrete grep assertion as the gate:
```bash
# Expect 0 keezxc1223 references in the footer that ships with raviwu releases:
test "$(grep -c 'keezxc1223' .github/release-footer.md)" -eq 0
```
- [ ] **Step 2: Run test to verify it fails**
Run: `grep -c 'keezxc1223' /Users/raviwu/personal/locwarp/.github/release-footer.md`
Expected: FAIL — prints `2` (both the zh link at :4 and the en link at :5 point at `keezxc1223`), so the `-eq 0` assertion is false.
- [ ] **Step 3: Write minimal implementation**
Edit `.github/release-footer.md` line 4 (zh) and line 5 (en), changing only the repo owner in each URL:
```markdown
📖 **Prerequisites / 使用者端需求**:
請先閱讀 [README](https://github.com/raviwu/locwarp#使用者端需求) 的安裝前置步驟(iTunes / USB 配對 / 開發者模式 / WiFi Tunnel 設定)。
See the [README](https://github.com/raviwu/locwarp/blob/main/README.en.md#prerequisites) for setup steps before installation.
```
- [ ] **Step 4: Run test to verify it passes**
Run: `grep -c 'keezxc1223' /Users/raviwu/personal/locwarp/.github/release-footer.md ; grep -c 'raviwu/locwarp' /Users/raviwu/personal/locwarp/.github/release-footer.md`
Expected: PASS — first prints `0`, second prints `2`.
- [ ] **Step 5: Commit**
```bash
git add .github/release-footer.md && git commit -m "docs(release): point release-footer README links at raviwu fork"
```

---

### Task 11: README download links platform-split (macOS→raviwu, Windows→keezxc1223)

**Files:**
- Modify: `README.md`:44, :60, :65, :75, :283, :391
- Modify: `README.en.md`:44, :60, :65, :75, :282, :321
- Test: grep assertions (markdown has no natural unit test)

**Interfaces:**
- Consumes: none
- Produces: none

> **Verified line map (against HEAD):**
> `README.md` — `:44`,`:65` Issues links · `:60` iOS-16 community PR (`pull/9`, @bitifyChen) · `:75` download badge button · `:283` GitHub-Releases data-source table row · `:391` "下載安裝檔" section header.
> `README.en.md` — `:44`,`:65` Issues · `:60` community PR · `:75` download badge · `:282` data-source row · `:321` "Download the installer" header.
>
> **Decisions applied** (resolving spec open-decisions #1):
> - **Download links** (`:75` badge, `:283`/`:282` data-source row, `:391`/`:321` section header) → **split**: present BOTH a macOS link (raviwu, ships the `.dmg`) AND a Windows link (keezxc1223, ships the `.exe`). The fork's `release.yml` is macOS-only, so blindly repointing all to raviwu would strand Windows users.
> - **Issues links** (`:44`, `:65`) → **raviwu** (you maintain the fork and triage there), per spec recommendation.
> - **iOS-16 community PR** (`:60`, `pull/9` @bitifyChen) → **stays keezxc1223** — it's a historical upstream PR reference; repointing it would create a dead/wrong link.

- [ ] **Step 1: Write the failing test**
No runnable test for markdown — gate with greps that encode every decision. After edits the expectations are: Issues + download all reachable on raviwu; the Windows download + the historical PR still on keezxc1223; the PR specifically still `pull/9`.
```bash
# Both READMEs must reference raviwu for Issues + macOS download:
grep -c 'raviwu/locwarp' README.md       # expect >= 5 after edit
grep -c 'raviwu/locwarp' README.en.md    # expect >= 5 after edit
# Remaining keezxc1223 refs are ONLY the historical PR + the Windows .exe link:
grep -n 'keezxc1223' README.md           # every hit must be pull/9 OR a Windows download line
grep -n 'keezxc1223' README.en.md
# The community PR link is preserved exactly:
grep -c 'keezxc1223/locwarp/pull/9' README.md     # expect 1
grep -c 'keezxc1223/locwarp/pull/9' README.en.md  # expect 1
```
- [ ] **Step 2: Run test to verify it fails**
Run: `grep -c 'raviwu/locwarp' /Users/raviwu/personal/locwarp/README.md /Users/raviwu/personal/locwarp/README.en.md`
Expected: FAIL — both print `0` (no raviwu references exist yet; all 6 links per file point at keezxc1223).
- [ ] **Step 3: Write minimal implementation**
Apply these edits. **Issues links** — `README.md:44` and `:65`, `README.en.md:44` and `:65`: change `https://github.com/keezxc1223/locwarp/issues` → `https://github.com/raviwu/locwarp/issues` (4 edits total).

**Download badge button** — `README.md:75` and `README.en.md:75`: the single shields.io badge points at the macOS primary (raviwu); add a sibling Windows badge. Replace the `<a>` at `:75`:
```html
  <a href="https://github.com/raviwu/locwarp/releases">
    <img alt="下載 (macOS)" src="https://img.shields.io/badge/下載_macOS-4285f4?style=for-the-badge&logo=apple&logoColor=white">
  </a>
  <a href="https://github.com/keezxc1223/locwarp/releases">
    <img alt="下載 (Windows)" src="https://img.shields.io/badge/下載_Windows-0078d4?style=for-the-badge&logo=windows&logoColor=white">
  </a>
```
(en `:75` analog: `下載_macOS`→`Download_macOS`, `下載_Windows`→`Download_Windows`.)

**Data-source table row** — `README.md:283` / `README.en.md:282` (the `GitHub Releases | frontend | …` row): the in-app update check hits the raviwu fork (matches Task 7's `REPO_SLUG`), so repoint this row to raviwu:
```markdown
| [GitHub Releases](https://github.com/raviwu/locwarp/releases) | frontend | 啟動時檢查新版本(純 HTTP,無遙測) | 否 |
```
(en `:282` keeps its English cells, URL → raviwu.)

**Download section header** — `README.md:391` (`**[下載安裝檔](...)**`) / `README.en.md:321` (`**[Download the installer](...)**`): split into per-platform links:
```markdown
**[下載 macOS 安裝檔 (.dmg)](https://github.com/raviwu/locwarp/releases)** · **[下載 Windows 安裝檔 (.exe)](https://github.com/keezxc1223/locwarp/releases)**
```
(en `:321`: `**[Download macOS installer (.dmg)](https://github.com/raviwu/locwarp/releases)** · **[Download Windows installer (.exe)](https://github.com/keezxc1223/locwarp/releases)**`)

**iOS-16 community PR** — `README.md:60` / `README.en.md:60`: **leave unchanged** (`https://github.com/keezxc1223/locwarp/pull/9` stays — historical upstream reference). Add an inline note clarifying the platform split where the download section header lives (right under `:391`/`:321`), e.g.:
```markdown
> macOS 版本由本 fork (`raviwu/locwarp`) 維護與發佈;Windows 版本請至上游 `keezxc1223/locwarp` 下載。
```
(en: `> The macOS build is maintained and released from this fork (raviwu/locwarp); for the Windows build, download from upstream keezxc1223/locwarp.`)
- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp && grep -c 'raviwu/locwarp' README.md README.en.md && grep -c 'keezxc1223/locwarp/pull/9' README.md README.en.md && grep -n 'keezxc1223' README.md README.en.md`
Expected: PASS — raviwu count ≥5 per file; `pull/9` count =1 per file; every remaining `keezxc1223` hit is either the `pull/9` line (:60) or a Windows `.exe` download line (the badge sibling at :75, the section-header Windows link). No stray keezxc1223 on the Issues/update-check rows.
- [ ] **Step 5: Commit**
```bash
git add README.md README.en.md && git commit -m "docs(readme): platform-split download links (macOS→raviwu, Windows→keezxc1223); Issues→raviwu"
```

---

## Workstream C — DeviceManager.connect() race + discover_devices fd-leak (reliability, danger-zone)

### Task 12: C3a — Characterization test for `connect()` same-udid race (danger zone, test-first)

**Files:**
- Test: `/Users/raviwu/personal/locwarp/backend/tests/test_device_manager_connect_race_char.py` (create)

**Interfaces:**
- Consumes: `DeviceManager()` (`core.device_manager`); `_ActiveConnection`; module globals `dm_mod.list_devices`, `dm_mod._remember_device_name`, `dm_mod._parse_ios_version`; lazily-imported `services.usbmux_pair_records.autopair_with_recovery`; instance hooks `DeviceManager._connect_tunnel`, `DeviceManager._teardown_connection`.
- Produces: a regression guard asserting exactly one connection survives two concurrent `connect(udid)` calls and the displaced connection is torn down (relied on by Task 13).

- [ ] **Step 1: Write the failing test**
```python
"""Characterization: DeviceManager.connect() must atomically claim the udid.

Two concurrent connect(udid) coroutines both pass the membership check under
self._lock (neither has installed yet), both run the heavy autopair+tunnel with
NO lock held, then both reinstall. On the buggy code the reinstall is a bare
``self._connections[udid] = conn`` (no pop-displaced) so the second write
silently clobbers the first WITHOUT tearing it down -> an orphaned helper-owned
utun tunnel that leaks until restart.

This test drives the REAL claim/teardown path (it stubs only the heavy I/O:
list_devices, autopair, _connect_tunnel) and asserts (a) exactly one connection
survives and (b) the displaced connection's _teardown_connection ran. It mirrors
test_device_manager_wifi_tunnel_race_char's stubbing approach: source-module
globals via monkeypatch, instance method override for the heavy connect, and a
controllable barrier so both coroutines are guaranteed past the membership check
before either reinstalls.
"""
from __future__ import annotations

import asyncio

import pytest

import core.device_manager as dm_mod
import services.usbmux_pair_records as pair_mod
from core.device_manager import DeviceManager, _ActiveConnection


class _StubLockdown:
    """Minimal stand-in for the lockdown client returned by autopair."""

    def __init__(self):
        self.all_values = {"ProductVersion": "17.5", "DeviceName": "My iPhone"}
        self.closed = False

    async def close(self):
        self.closed = True


class _Raw:
    def __init__(self, serial):
        self.serial = serial
        self.connection_type = "USB"


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_connect_same_udid_concurrent_claims_atomically(monkeypatch):
    monkeypatch.setattr(dm_mod, "list_devices", lambda: _async_value([_Raw("UDID-USB")]))
    monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)

    # autopair_with_recovery is lazily imported INSIDE connect() from its source
    # module, so patch it on services.usbmux_pair_records (not on dm_mod).
    async def _fake_autopair(udid, autopair=True):
        return _StubLockdown(), False

    monkeypatch.setattr(pair_mod, "autopair_with_recovery", _fake_autopair)

    mgr = DeviceManager()

    # Barrier: hold both coroutines inside the heavy connect (after the
    # membership check, before reinstall) until both have arrived. This
    # deterministically reproduces the interleave; without it the two awaits
    # could serialize and the second would see the first already installed.
    both_inside = asyncio.Event()
    arrived = 0
    torn_down: list[_ActiveConnection] = []

    async def _fake_connect_tunnel(self, udid, lockdown, ios_version):
        nonlocal arrived
        conn = _ActiveConnection(
            udid=udid,
            lockdown=lockdown,
            ios_version=ios_version,
            rsd=lockdown,  # so a real teardown has an rsd to close
        )
        arrived += 1
        if arrived >= 2:
            both_inside.set()
        await both_inside.wait()
        return conn

    real_teardown = mgr._teardown_connection

    async def _spy_teardown(udid, conn):
        torn_down.append(conn)
        await real_teardown(udid, conn)

    monkeypatch.setattr(
        DeviceManager, "_connect_tunnel", _fake_connect_tunnel, raising=True
    )
    mgr._teardown_connection = _spy_teardown  # type: ignore[assignment]

    await asyncio.gather(mgr.connect("UDID-USB"), mgr.connect("UDID-USB"))

    # Exactly one live connection remains for the udid.
    assert list(mgr._connections.keys()) == ["UDID-USB"]
    survivor = mgr._connections["UDID-USB"]

    # The displaced connection was torn down (not silently clobbered/leaked).
    assert len(torn_down) == 1, (
        "exactly one of the two concurrent connects must be displaced and "
        "torn down; bare reinstall leaks the loser's tunnel"
    )
    assert torn_down[0] is not survivor
    # The displaced connection's rsd was actually closed by the real teardown.
    assert torn_down[0].rsd.closed is True


def _async_value(value):
    async def _coro():
        return value

    return _coro()
```
- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_device_manager_connect_race_char.py -q`
Expected: FAIL — on the current `connect()` (bare `self._connections[udid] = conn` at lines 539-540, no pop-displaced) the second write clobbers the first without teardown, so `torn_down` stays empty and `assert len(torn_down) == 1` fails (`0 != 1`).
- [ ] **Step 3: Write minimal implementation**
No production change in this task — the test is the deliverable and is expected RED. (Implementation lands in Task 13.) Add `pytest-timeout` if not already present so `@pytest.mark.timeout(5)` is honored:
```bash
cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -c "import pytest_timeout" 2>/dev/null || echo "MISSING: add pytest-timeout to requirements-dev.txt (Workstream D2)"
```
If `pytest-timeout` is missing, drop the `@pytest.mark.timeout(5)` line for this commit and rely on the deterministic barrier (the test cannot hang on the buggy path — both coroutines complete); D2 re-adds the marker.
- [ ] **Step 4: Run test to verify it fails (RED is the deliverable for the char test)**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_device_manager_connect_race_char.py -q`
Expected: FAIL with `assert 0 == 1` (no teardown of the displaced connection). This RED state proves the test exercises the bug.
- [ ] **Step 5: Commit**
```bash
git add backend/tests/test_device_manager_connect_race_char.py && git commit -m "test(device): char test for connect() same-udid race (expected RED)"
```

---

### Task 13: C1 — `connect()` atomic claim (pop displaced under `_lock`, teardown after release)

**Files:**
- Modify: `/Users/raviwu/personal/locwarp/backend/core/device_manager.py`:539-542 (the bare reinstall at the end of `connect()`)
- Test: `/Users/raviwu/personal/locwarp/backend/tests/test_device_manager_connect_race_char.py` (from Task 12 — flips to GREEN)

**Interfaces:**
- Consumes: `self._lock` (`asyncio.Lock`, non-reentrant); `self._connections.pop`; `self._teardown_connection(udid, conn)` (must be called WITHOUT the lock — docstring at lines 628-638). Mirrors the sibling pattern at `connect_wifi_tunnel` lines 1053-1058.
- Produces: `connect()` now atomically swaps the connection and tears down any displaced same-udid connection, matching `connect_wifi_tunnel`.

- [ ] **Step 1: Test already written (Task 12) — confirm it is RED**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_device_manager_connect_race_char.py -q`
Expected: FAIL (`assert 0 == 1`) — same RED as Task 12.
- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_device_manager_connect_race_char.py::test_connect_same_udid_concurrent_claims_atomically -q`
Expected: FAIL — `assert len(torn_down) == 1` is `0 != 1` (bare reinstall clobbers without teardown).
- [ ] **Step 3: Write minimal implementation**
Replace the bare reinstall block (current lines 539-542) so it mirrors `connect_wifi_tunnel`'s pop-displaced-then-teardown. The legacy iOS-16 path does NOT double-close: for a legacy `_ActiveConnection`, `rsd is None` and `connection_type == "USB"` with version `< 17`, so `_teardown_connection` closes neither `rsd` (None) nor the helper USB tunnel (gated on `>= (17,0)` at lines 664-667) — the legacy `lockdown`/`usbmux_lockdown` (same object) is left untouched, exactly as `disconnect()` does for legacy today. No new close path is introduced.

Old (lines 539-542):
```python
        async with self._lock:
            self._connections[udid] = conn

        logger.info("Connected to %s (iOS %s) via %s", udid, ios_version_str, connection_type)
```
New:
```python
        # Atomically claim the udid: pop any stale/concurrent same-udid
        # connection and install the fresh one under the lock, so two
        # concurrent connect(udid) (HTTP /connect + usbmux watchdog + startup
        # autoconnect + full_reconnect) can't both pass the membership check
        # and then clobber each other — the loser's tunnel would leak. Mirror
        # connect_wifi_tunnel: tear the displaced connection down AFTER
        # releasing the lock via the lock-free _teardown_connection helper
        # (self._lock is non-reentrant; disconnect() would re-take it and
        # self-deadlock). For the legacy iOS-16 path _teardown_connection is a
        # no-op (rsd is None; the helper-tunnel close is gated on iOS 17+), so
        # the shared legacy lockdown/usbmux_lockdown object is not double-closed.
        async with self._lock:
            displaced = self._connections.pop(udid, None)
            self._connections[udid] = conn

        if displaced is not None:
            await self._teardown_connection(udid, displaced)

        logger.info("Connected to %s (iOS %s) via %s", udid, ios_version_str, connection_type)
```
- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_device_manager_connect_race_char.py tests/test_device_manager_wifi_tunnel_race_char.py -q`
Expected: PASS (4 passed) — `connect()` now displaces+tears down; the wifi sibling stays green.
- [ ] **Step 5: Commit**
```bash
git add backend/core/device_manager.py && git commit -m "fix(device): connect() atomically claims udid (pop displaced + teardown after lock release)"
```

---

### Task 14: C2 — `discover_devices` fd-leak: close lockdown on the success path

**Files:**
- Modify: `/Users/raviwu/personal/locwarp/backend/core/device_manager.py`:378-428 (wrap the success-branch body in `try/finally`)
- Test: `/Users/raviwu/personal/locwarp/backend/tests/test_device_manager_discover_fd_leak_char.py` (create)

**Interfaces:**
- Consumes: `DeviceManager.discover_devices()`; module globals `dm_mod.list_devices`, `dm_mod.create_using_usbmux`, `dm_mod._remember_device_name`, `dm_mod._parse_ios_version`.
- Produces: `discover_devices` closes the per-device lockdown client on BOTH the success and failure branches (no usbmuxd-socket leak per poll tick).

- [ ] **Step 1: Write the failing test**
```python
"""Characterization: discover_devices() must close the per-device lockdown
client on the SUCCESS path too, not just the except path.

The success branch (currently device_manager.py:378-403) appends a DeviceInfo
but never closes the lockdown returned by create_using_usbmux. discover runs on
every UI refresh / watchdog tick, so the un-closed usbmuxd socket leaks until
the process exits -> eventual "iPhone not detected" until restart. This test
asserts the success-path lockdown is closed exactly once. The except branch
already closes (lines 404-416); we add a second case to lock in that the
try/finally does not double-close.
"""
from __future__ import annotations

import pytest

import core.device_manager as dm_mod
from core.device_manager import DeviceManager


class _Raw:
    def __init__(self, serial, connection_type="USB"):
        self.serial = serial
        self.connection_type = connection_type


class _StubLockdown:
    """Success-path lockdown: every property/method works."""

    def __init__(self):
        self.all_values = {
            "DeviceName": "My iPhone",
            "ProductVersion": "17.5",
            "UniqueDeviceID": "UDID-OK",
        }
        self.close_calls = 0

    async def get_developer_mode_status(self):
        return True

    async def close(self):
        self.close_calls += 1


def _async_value(value):
    async def _coro():
        return value

    return _coro()


@pytest.mark.asyncio
async def test_discover_devices_closes_lockdown_on_success(monkeypatch):
    lk = _StubLockdown()

    monkeypatch.setattr(dm_mod, "list_devices", lambda: _async_value([_Raw("UDID-OK")]))
    monkeypatch.setattr(dm_mod, "_remember_device_name", lambda *a, **k: None)

    async def _fake_create(serial, autopair=False):
        return lk

    monkeypatch.setattr(dm_mod, "create_using_usbmux", _fake_create)

    mgr = DeviceManager()
    devices = await mgr.discover_devices()

    # The device is still surfaced...
    assert [d.udid for d in devices] == ["UDID-OK"]
    assert devices[0].name == "My iPhone"
    assert devices[0].developer_mode_enabled is True
    # ...and its lockdown socket was closed exactly once (no leak, no double).
    assert lk.close_calls == 1, (
        "discover_devices leaked the usbmuxd socket on the success path "
        f"(close_calls={lk.close_calls}, expected 1)"
    )
```
- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_device_manager_discover_fd_leak_char.py -q`
Expected: FAIL — `assert lk.close_calls == 1` is `0 != 1`; the success branch never calls `lockdown.close()`.
- [ ] **Step 3: Write minimal implementation**
Wrap the success-branch body in `try/finally`, reusing the same best-effort close pattern the except branch already uses (lines 409-416). The except branch's own close stays (it handles the case where a property blew up mid-body); the `finally` closes on the normal-return path. Note: `continue` inside the `except` still runs the `finally`, so a failed-query device is closed exactly once by the `finally` — remove the now-redundant explicit close from the except branch to avoid a double-close.

Old (lines 378-428):
```python
            try:
                all_values = lockdown.all_values
                # If device is already connected, report the active connection type
                active_conn = self._connections.get(raw.serial)
                if active_conn:
                    conn_type = active_conn.connection_type
                device_name = all_values.get("DeviceName", "Unknown")
                _remember_device_name(raw.serial, device_name)
                info = DeviceInfo(
                    udid=raw.serial,
                    name=device_name,
                    ios_version=all_values.get("ProductVersion", "0.0"),
                    connection_type=conn_type,
                )
                info.is_connected = raw.serial in self._connections
                # Query Developer Mode status (iOS 16+). Tolerate failure —
                # None means "unknown", frontend will hide the reveal button.
                try:
                    ver = _parse_ios_version(info.ios_version)
                    if ver >= (16, 0):
                        info.developer_mode_enabled = await lockdown.get_developer_mode_status()
                except Exception:
                    logger.debug("get_developer_mode_status failed for %s", raw.serial, exc_info=True)
                devices.append(info)
                logger.debug("Discovered device %s (%s) running iOS %s via %s (connected=%s)",
                             info.name, info.udid, info.ios_version, conn_type, info.is_connected)
            except Exception as exc:
                # Lockdown opened but a later property/method blew up — still
                # surface the device so the user knows it's there.
                # Best-effort close so we don't leak the usbmuxd socket every poll
                # cycle. Some lockdown variants expose async close(); some don't.
                try:
                    close_coro = getattr(lockdown, "close", None)
                    if close_coro is not None:
                        result = close_coro()
                        if hasattr(result, "__await__"):
                            await result
                except Exception:
                    logger.debug("close failed on lockdown for %s", raw.serial, exc_info=True)
                pair_status, pair_error = _classify_pair_error(exc)
                cached_name = _load_device_name_cache().get(raw.serial, "iPhone")
                devices.append(DeviceInfo(
                    udid=raw.serial,
                    name=cached_name,
                    ios_version="0.0",
                    connection_type=conn_type,
                    is_connected=False,
                    pair_status=pair_status,
                    pair_error=pair_error,
                ))
                logger.exception("Failed to query device %s after lockdown opened", raw.serial)
```
New:
```python
            try:
                try:
                    all_values = lockdown.all_values
                    # If device is already connected, report the active connection type
                    active_conn = self._connections.get(raw.serial)
                    if active_conn:
                        conn_type = active_conn.connection_type
                    device_name = all_values.get("DeviceName", "Unknown")
                    _remember_device_name(raw.serial, device_name)
                    info = DeviceInfo(
                        udid=raw.serial,
                        name=device_name,
                        ios_version=all_values.get("ProductVersion", "0.0"),
                        connection_type=conn_type,
                    )
                    info.is_connected = raw.serial in self._connections
                    # Query Developer Mode status (iOS 16+). Tolerate failure —
                    # None means "unknown", frontend will hide the reveal button.
                    try:
                        ver = _parse_ios_version(info.ios_version)
                        if ver >= (16, 0):
                            info.developer_mode_enabled = await lockdown.get_developer_mode_status()
                    except Exception:
                        logger.debug("get_developer_mode_status failed for %s", raw.serial, exc_info=True)
                    devices.append(info)
                    logger.debug("Discovered device %s (%s) running iOS %s via %s (connected=%s)",
                                 info.name, info.udid, info.ios_version, conn_type, info.is_connected)
                except Exception as exc:
                    # Lockdown opened but a later property/method blew up — still
                    # surface the device so the user knows it's there. The
                    # usbmuxd socket is closed by the finally below (covers this
                    # branch and the success path alike).
                    pair_status, pair_error = _classify_pair_error(exc)
                    cached_name = _load_device_name_cache().get(raw.serial, "iPhone")
                    devices.append(DeviceInfo(
                        udid=raw.serial,
                        name=cached_name,
                        ios_version="0.0",
                        connection_type=conn_type,
                        is_connected=False,
                        pair_status=pair_status,
                        pair_error=pair_error,
                    ))
                    logger.exception("Failed to query device %s after lockdown opened", raw.serial)
            finally:
                # Always release the per-device usbmuxd socket — discovery runs
                # on every UI refresh / watchdog tick, so a leak here exhausts
                # usbmuxd and the iPhone "disappears" until restart. Best-effort:
                # some lockdown variants expose async close(); some don't.
                try:
                    close_coro = getattr(lockdown, "close", None)
                    if close_coro is not None:
                        result = close_coro()
                        if hasattr(result, "__await__"):
                            await result
                except Exception:
                    logger.debug("close failed on lockdown for %s", raw.serial, exc_info=True)
```
- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_device_manager_discover_fd_leak_char.py tests/test_device_pair_failure.py tests/test_device_manager_events.py -q`
Expected: PASS — success path now closes exactly once; existing discover/pair-failure tests stay green (the except-branch device is closed by `finally` once, no double-close).
- [ ] **Step 5: Commit**
```bash
git add backend/core/device_manager.py backend/tests/test_device_manager_discover_fd_leak_char.py && git commit -m "fix(device): close lockdown on discover_devices success path (usbmuxd fd-leak)"
```

**Audit note for `scan_wifi_devices` / `_teardown_connection` (spec C2 "audit the same pattern"):**
- `scan_wifi_devices._probe` (lines 1096-1126): the lockdown opened via `create_using_tcp` (lines 1107-1114) is **also not closed** on its success path (returns the dict at 1116-1121 without closing). This is a lesser leak (manual user-triggered scan, not a per-tick poll) — flag it in the plan as a follow-up mirroring the C2 fix (wrap the inner `try` body so the `create_using_tcp` lockdown is closed in a `finally`); not required for behavior-freeze. If included, add a `_probe`-level char test asserting `close` is called.
- `_teardown_connection` (lines 628-673): correctly scoped — closes `rsd` and the helper USB tunnel only, and is always called after the conn is popped under the lock. No fd-leak; no change needed.

**Cross-task notes:**
- Baseline pinned: `1043 tests collected` (`.venv/bin/python -m pytest --collect-only -q`). Tasks 12 and 14 add 2 test files (2 new test functions): expect `1045 collected` — re-pin the exact number before starting.
- All three tasks are danger-zone (`core/device_manager.py` has characterization-test-first requirement) — Tasks 12 and 14 write the char test before the edit; Task 13 reuses Task 12's test as the red→green driver.
- No import-linter impact: edits stay within `core/device_manager.py`; tests live in `backend/tests/`. Run `.venv/bin/python -m pytest tests/test_import_linter.py -q` after Task 13 to confirm `7 kept, 0 broken`.

---

## Workstream D — Quick wins

### Task 15: D1 — Deferred-enrich broadcast (correctness)

**Files:**
- Test: `backend/tests/test_lifespan_enrich_defer_char.py` (append new tests; existing file, currently 104 lines)
- Modify: `backend/main.py:992-1005` (fix false comment at `:992-993`; add broadcast to `_deferred_enrich` body)

**Interfaces:**
- Consumes: `BookmarkManager.enrich_all(self) -> int` (returns count of bookmarks modified — confirmed at `services/bookmarks.py:474`, already returns a changed-count, no change needed); `api.websocket.broadcast(event_type: str, data: dict)` (async, `api/websocket.py:16`).
- Produces: none (internal lifespan behavior; the WS event `bookmarks_changed` with `{"reason": "enrich"}` is the observable contract).

- [ ] **Step 1: Write the failing test**
Append to `backend/tests/test_lifespan_enrich_defer_char.py`:
```python
async def test_deferred_enrich_broadcasts_when_changed(monkeypatch):
    """D1: after the deferred sweep fills geo fields (changed > 0), the
    lifespan must broadcast a bookmarks_changed event so the UI refreshes —
    the watcher cannot (its self-write is mtime-suppressed in _watcher_tick)."""
    monkeypatch.setattr("sys.platform", "darwin")

    async def fake_connect(timeout=90.0):
        return None

    async def fake_migrate(home, uid, gid):
        return {"chowned": 0, "skipped": 0, "failed": 0}

    async def fake_shutdown():
        return {"ok": True}

    async def fake_close():
        return None

    monkeypatch.setattr(helper_client, "connect", fake_connect)
    monkeypatch.setattr(helper_client, "migrate_user_state", fake_migrate)
    monkeypatch.setattr(helper_client, "shutdown", fake_shutdown)
    monkeypatch.setattr(helper_client, "close", fake_close)

    async def fake_discover():
        return []

    async def fake_disconnect_all():
        return None

    monkeypatch.setattr(app_state.device_manager, "discover_devices", fake_discover)
    monkeypatch.setattr(app_state.device_manager, "disconnect_all", fake_disconnect_all)

    app_state.bookmark_manager = None
    app_state.route_manager = None

    # Force a positive changed-count so the broadcast condition fires.
    from services.bookmarks import BookmarkManager
    monkeypatch.setattr(BookmarkManager, "enrich_all", lambda self: 3)

    events: list[tuple[str, dict]] = []

    async def spy_broadcast(event_type, data):
        events.append((event_type, data))

    # _deferred_enrich does `from api.websocket import broadcast` at call time,
    # so patch the source attribute.
    monkeypatch.setattr("api.websocket.broadcast", spy_broadcast)

    async with lifespan(None):
        for _ in range(50):
            if any(e[0] == "bookmarks_changed" for e in events):
                break
            await asyncio.sleep(0.01)

    enrich_events = [e for e in events if e[0] == "bookmarks_changed"]
    assert enrich_events, "deferred enrich must broadcast bookmarks_changed when changed > 0"
    assert enrich_events[0][1] == {"reason": "enrich"}


async def test_deferred_enrich_no_broadcast_when_unchanged(monkeypatch):
    """D1: an idempotent sweep (changed == 0) must NOT broadcast — avoids a
    spurious UI refresh on every cold start of an already-enriched store."""
    monkeypatch.setattr("sys.platform", "darwin")

    async def fake_connect(timeout=90.0):
        return None

    async def fake_migrate(home, uid, gid):
        return {"chowned": 0, "skipped": 0, "failed": 0}

    async def fake_shutdown():
        return {"ok": True}

    async def fake_close():
        return None

    monkeypatch.setattr(helper_client, "connect", fake_connect)
    monkeypatch.setattr(helper_client, "migrate_user_state", fake_migrate)
    monkeypatch.setattr(helper_client, "shutdown", fake_shutdown)
    monkeypatch.setattr(helper_client, "close", fake_close)

    async def fake_discover():
        return []

    async def fake_disconnect_all():
        return None

    monkeypatch.setattr(app_state.device_manager, "discover_devices", fake_discover)
    monkeypatch.setattr(app_state.device_manager, "disconnect_all", fake_disconnect_all)

    app_state.bookmark_manager = None
    app_state.route_manager = None

    from services.bookmarks import BookmarkManager
    monkeypatch.setattr(BookmarkManager, "enrich_all", lambda self: 0)

    events: list[tuple[str, dict]] = []

    async def spy_broadcast(event_type, data):
        events.append((event_type, data))

    monkeypatch.setattr("api.websocket.broadcast", spy_broadcast)

    async with lifespan(None):
        # Give the spawned _deferred_enrich task time to run to completion.
        await asyncio.sleep(0.1)

    enrich_events = [e for e in events if e == ("bookmarks_changed", {"reason": "enrich"})]
    assert enrich_events == [], "no enrich broadcast expected when changed == 0"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lifespan_enrich_defer_char.py::test_deferred_enrich_broadcasts_when_changed -q`
Expected: FAIL — `assert enrich_events` fails because `_deferred_enrich` currently never calls `broadcast` (the second test `test_deferred_enrich_no_broadcast_when_unchanged` already passes vacuously since no broadcast exists — it locks in the negative case).

- [ ] **Step 3: Write minimal implementation**
Edit `backend/main.py` — fix the false comment at `:991-993` and add the broadcast in `_deferred_enrich`:

Replace the comment block ending at `:993`:
```python
    # already loaded (above) so bookmarks/routes exist the instant the server
    # is up; only the offline geo fields fill a beat later. The file watcher
    # CANNOT surface that fill: enrich_all's _save records its own mtime, so
    # _watcher_tick suppresses the self-write. So _deferred_enrich itself
    # broadcasts bookmarks_changed when the sweep actually changed something.
```
Replace the `_deferred_enrich` body (`:997-1003`):
```python
        async def _deferred_enrich() -> None:
            # Warm the offline resolver off the loop (the slow data load,
            # store-free), then sweep on the loop (single-threaded → safe).
            from services import geo_offline

            await asyncio.to_thread(geo_offline._ensure_loaded)
            changed = manager.enrich_all()
            if changed:
                # The watcher won't fire (self-write mtime-suppressed), so
                # push the refresh ourselves — fill UI only on a real change.
                from api.websocket import broadcast
                await broadcast("bookmarks_changed", {"reason": "enrich"})
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_lifespan_enrich_defer_char.py -q`
Expected: PASS (4 tests: the 2 pre-existing + the 2 new)

- [ ] **Step 5: Commit**
```bash
git add backend/main.py backend/tests/test_lifespan_enrich_defer_char.py && git commit -m "fix(enrich): deferred geo sweep broadcasts bookmarks_changed on real change

The watcher cannot surface enrich_all's fill (its _save mtime is
self-suppressed in _watcher_tick), so the UI never refreshed until an
unrelated event. _deferred_enrich now broadcasts bookmarks_changed when
changed > 0, and the false 'watcher broadcasts it' comment is corrected.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

### Task 16: D2 — Test timeouts (CI safety)

**Files:**
- Modify: `backend/requirements-dev.txt:1-5` (add `pytest-timeout`)
- Modify: `backend/tests/test_lifespan_autoconnect_defer_char.py` (add `@pytest.mark.timeout(10)` to the 2 blocking-`Event` tests)
- Modify: `backend/tests/test_group_sync_service_char.py` (add `@pytest.mark.timeout(10)` to the 2 real-sleep follower tests)
- Modify: `backend/tests/test_usbmux_pair_records.py` (add `@pytest.mark.timeout(10)` to the lock-serialization test)

**Interfaces:**
- Consumes: none.
- Produces: `pytest-timeout` plugin available → `@pytest.mark.timeout(N)` decorator usable repo-wide.

- [ ] **Step 1: Write the failing test**
The "failing test" here is the gate proof: the decorated test must *use* a marker that the plugin provides. First add the marker usage; it will error at collection without the plugin installed. Decorate the most representative hang-risk test — `test_pair_lock_serializes_concurrent_acquires_for_same_udid` in `backend/tests/test_usbmux_pair_records.py` — by inserting the marker above its existing `@pytest.mark.asyncio`:
```python
@pytest.mark.timeout(10)
@pytest.mark.asyncio
async def test_pair_lock_serializes_concurrent_acquires_for_same_udid():
    """When two coroutines hold the same udid's lock, the second waits."""
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_usbmux_pair_records.py::test_pair_lock_serializes_concurrent_acquires_for_same_udid -q`
Expected: FAIL — `'timeout' not found in markers configuration option` (strict-markers is not set, so it surfaces as a `PytestUnknownMarkWarning`; with `pytest-timeout` absent the marker is inert and produces a warning rather than enforcing a timeout). Confirm absence first: `.venv/bin/python -c "import pytest_timeout"` → `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**
Add the plugin to `backend/requirements-dev.txt` (after the `pytest-cov` line):
```
pytest>=8.0
pytest-asyncio>=0.23
pytest-cov>=5.0
pytest-timeout>=2.3
httpx>=0.27
import-linter>=2.0
```
Install it: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pip install 'pytest-timeout>=2.3'`

Decorate the remaining hang-risk char-tests. In `backend/tests/test_lifespan_autoconnect_defer_char.py`, add `@pytest.mark.timeout(10)` above each of the two `async def test_...` functions (the module uses `pytestmark = pytest.mark.asyncio`, so only the timeout marker is added per-function):
```python
@pytest.mark.timeout(10)
async def test_autoconnect_is_spawned_not_awaited(monkeypatch):
```
```python
@pytest.mark.timeout(10)
async def test_autoconnect_failure_does_not_crash_startup(monkeypatch):
```
In `backend/tests/test_group_sync_service_char.py`, decorate the two real-`asyncio.sleep` follower tests (`pytestmark = pytest.mark.asyncio` is module-level):
```python
@pytest.mark.timeout(10)
async def test_follower_stops_when_primary_changes():
```
```python
@pytest.mark.timeout(10)
async def test_follower_stops_when_stop_event_set():
```

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_usbmux_pair_records.py tests/test_lifespan_autoconnect_defer_char.py tests/test_group_sync_service_char.py -q`
Expected: PASS (no `PytestUnknownMarkWarning` for `timeout`; the plugin now enforces a per-test 10s cap). Spot-check the plugin is active: `.venv/bin/python -m pytest tests/test_usbmux_pair_records.py::test_pair_lock_serializes_concurrent_acquires_for_same_udid -q -o timeout=0.001` should FAIL with `Timeout >0.001s` (proves enforcement), then revert the `-o` override.

- [ ] **Step 5: Commit**
```bash
git add backend/requirements-dev.txt backend/tests/test_usbmux_pair_records.py backend/tests/test_lifespan_autoconnect_defer_char.py backend/tests/test_group_sync_service_char.py && git commit -m "test(ci): pytest-timeout(10s) on blocking-Event/real-sleep char-tests

CI is the only gate on the direct-to-main flow; a boot-defer or
lock-serialization regression would hang the suite instead of failing
it. Cap the spawn/Event/poll char-tests at 10s so a future deadlock
fails CI cleanly.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

### Task 17: D3 — `React.memo` on `DeviceStatus` + `DeviceChipRow` (perf, zero-risk)

**Files:**
- Test: `frontend/src/components/DeviceStatus.memo.test.tsx` (create)
- Test: `frontend/src/components/DeviceChipRow.memo.test.tsx` (create)
- Modify: `frontend/src/components/DeviceStatus.tsx:58` + `:1070` (named const + `export default React.memo(...)`)
- Modify: `frontend/src/components/DeviceChipRow.tsx:21` (wrap named export in `React.memo`)
- Modify: `frontend/src/App.profiler.bench.test.tsx:76,364` (update stale "NOT memoized in production" comments — non-functional)

**Interfaces:**
- Consumes: none.
- Produces: `DeviceStatus` (default export) and `DeviceChipRow` (named export) are now `React.memo`-wrapped — referentially-stable props skip re-render.

- [ ] **Step 1: Write the failing test**
Create `frontend/src/components/DeviceStatus.memo.test.tsx`:
```tsx
import React, { Profiler } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'

vi.mock('../i18n', () => ({ useT: () => (key: string) => key }))
vi.mock('../contexts/ServicesContext', () => ({
  useServices: () => ({
    api: {
      wifiTunnelDiscover: vi.fn().mockResolvedValue({ devices: [] }),
      wifiTunnelFindPort: vi.fn().mockResolvedValue({ ports: [] }),
      wifiRepair: vi.fn().mockResolvedValue({ name: 'iPhone', ios_version: '17.0' }),
    },
  }),
}))

import DeviceStatus from './DeviceStatus'

describe('DeviceStatus is React.memo (D3)', () => {
  beforeEach(() => { localStorage.clear() })

  it('does not re-render when the parent re-renders with identical props', () => {
    // Referentially-stable props (declared once, reused across both parent renders).
    const props = {
      device: null,
      devices: [] as any[],
      isConnected: false,
      onScan: vi.fn(),
      onSelect: vi.fn(),
    }

    let commits = 0
    const onRender = () => { commits++ }

    function Parent({ tick }: { tick: number }) {
      // `tick` forces Parent to re-render but is NOT forwarded to DeviceStatus.
      return (
        <Profiler id="ds" onRender={onRender}>
          <DeviceStatus {...props} />
        </Profiler>
      )
    }

    const { rerender } = render(<Parent tick={0} />)
    const afterMount = commits
    expect(afterMount).toBeGreaterThan(0) // mounted once

    // Re-render the parent with the SAME props object passed to DeviceStatus.
    rerender(<Parent tick={1} />)

    // memo should block the child commit → no additional Profiler commit.
    expect(commits).toBe(afterMount)
  })
})
```
Create `frontend/src/components/DeviceChipRow.memo.test.tsx`:
```tsx
import React, { Profiler } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { DeviceChipRow } from './DeviceChipRow'
import type { RuntimesMap } from '../hooks/useSimulation'

vi.mock('../i18n', () => ({ useT: () => (key: string) => key }))

const emptyRuntimes: RuntimesMap = {}

describe('DeviceChipRow is React.memo (D3)', () => {
  it('does not re-render when the parent re-renders with identical props', () => {
    const props = {
      devices: [] as any[],
      runtimes: emptyRuntimes,
      onAdd: vi.fn(),
      onDisconnect: vi.fn(),
      onForget: vi.fn(),
      onRestoreOne: vi.fn(),
    }

    let commits = 0
    const onRender = () => { commits++ }

    function Parent({ tick }: { tick: number }) {
      return (
        <Profiler id="dcr" onRender={onRender}>
          <DeviceChipRow {...props} />
        </Profiler>
      )
    }

    const { rerender } = render(<Parent tick={0} />)
    const afterMount = commits
    expect(afterMount).toBeGreaterThan(0)

    rerender(<Parent tick={1} />)
    expect(commits).toBe(afterMount)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/DeviceStatus.memo.test.tsx src/components/DeviceChipRow.memo.test.tsx`
Expected: FAIL — `expected 2 to be 1` (the component re-renders on the parent's second render because it is not yet memoized, so the Profiler records a second commit).

- [ ] **Step 3: Write minimal implementation**
In `frontend/src/components/DeviceStatus.tsx`, the component is already declared as `const DeviceStatus: React.FC<DeviceStatusProps> = ({ ... }) => {`. Change only the export at line 1070:
```tsx
export default React.memo(DeviceStatus);
```
(`React` is already imported at line 1 — `import React, { useState } from 'react';`.)

In `frontend/src/components/DeviceChipRow.tsx`, add a `React` import and wrap the function. Change line 1 area to add React, and convert the export:
```tsx
import React from 'react'
import { DeviceChip, type DeviceLetter } from './DeviceChip'
```
Then change `export function DeviceChipRow({ ... }: Props) {` at line 21 to a named, memoized const. Replace:
```tsx
export function DeviceChipRow({ devices, trustRequired = [], runtimes, onAdd, onDisconnect, onForget, onRestoreOne, onReTrust, onEnableDev }: Props) {
```
with:
```tsx
export const DeviceChipRow = React.memo(function DeviceChipRow({ devices, trustRequired = [], runtimes, onAdd, onDisconnect, onForget, onRestoreOne, onReTrust, onEnableDev }: Props) {
```
and close the memo wrapper at the function's end (line 85, currently `}`) by changing the trailing `}` to `})`.

Update the now-stale comments in `frontend/src/App.profiler.bench.test.tsx` (non-functional): line 76 `// DeviceStatus — NOT memoized in production.` → `// DeviceStatus — memoized in production (D3); stub here is unmemoized to count App-driven commits.` and line 364 `(NOT memo'd — will commit)` → `(memo'd in prod; stub unmemoized here)`.

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/DeviceStatus.memo.test.tsx src/components/DeviceChipRow.memo.test.tsx src/components/DeviceStatus.test.tsx src/components/DeviceChipRow.test.tsx src/App.profiler.bench.test.tsx && npx tsc --noEmit`
Expected: PASS for all five test files (the profiler bench stays green — it mocks both components, so the real `React.memo` wrapping does not change its mocked render counts), and `tsc` reports no errors.

- [ ] **Step 5: Commit**
```bash
git add frontend/src/components/DeviceStatus.tsx frontend/src/components/DeviceChipRow.tsx frontend/src/components/DeviceStatus.memo.test.tsx frontend/src/components/DeviceChipRow.memo.test.tsx frontend/src/App.profiler.bench.test.tsx && git commit -m "perf(ui): React.memo DeviceStatus + DeviceChipRow

Profiler flagged both as zero-risk wasted commits — their device.* props
don't change on a position tick. Wrap both in React.memo so a parent
re-render with stable props skips them. Profiler bench stays green (it
mocks both); stale 'NOT memoized' comments corrected.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```

---

### Task 18: D4 (OPTIONAL — already shipped; verify-only) — "Add to route" bookmark action

**Status: OPTIONAL / DEFERRABLE.** Verification against HEAD shows this feature **already exists end-to-end** and needs no implementation:
- `BookmarkContextMenu.tsx:317-337` renders an "Add as Waypoint" menu item, gated `showWaypointOption && onAddWaypoint`, calling `onAddWaypoint(bm.lat, bm.lng)` then `onClose()` (the i18n key is `map.add_waypoint`).
- `App.tsx:514` defines `handleAddWaypoint`; it is passed as `onAddWaypoint={handleAddWaypoint}` at `App.tsx:1270` and `:1544`, and `showWaypointOption` is set from sim mode at `App.tsx:1272` / `:1546` (`Loop || MultiStop || Navigate`).
- `BookmarkList.tsx:60,112,856,860` threads `showWaypointOption` + `onAddWaypoint` through to the context menu.

Therefore **recommend: drop D4 from this pass** (the spec already marked it deferrable). If a coverage regression-guard is still wanted, the single low-cost task below adds a missing characterization test for the bookmark-popover path (the existing `onAddWaypoint` test at `MapContextMenu.test.tsx:146` covers the *map* context menu, not the *bookmark* one). Only do this if the rest of Workstream D landed comfortably.

**Files:**
- Test: `frontend/src/components/BookmarkContextMenu.test.tsx` (create if absent — confirm with `ls frontend/src/components/BookmarkContextMenu.test.tsx` first; if it exists, append the one test instead)

**Interfaces:**
- Consumes: `BookmarkContextMenu` props `onAddWaypoint?: (lat: number, lng: number) => void`, `showWaypointOption: boolean`, `bm: { lat, lng, ... }`, `onClose: () => void` (`BookmarkContextMenu.tsx:31,84`).
- Produces: none.

- [ ] **Step 1: Write the failing test**
First run `ls /Users/raviwu/personal/locwarp/frontend/src/components/BookmarkContextMenu.test.tsx`. If absent, create it modeled on `MapContextMenu.test.tsx` (read that file's `makeProps` helper for the exact prop shape `BookmarkContextMenu` requires, since props differ from `MapContextMenu`). The single assertion to add:
```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import BookmarkContextMenu from './BookmarkContextMenu'

vi.mock('../i18n', () => ({ useT: () => (key: string) => key }))

// makeProps must supply EVERY required BookmarkContextMenu prop — derive the
// exact shape from BookmarkContextMenu.tsx:20-90 (the props interface) when
// writing this; the stub below lists the load-bearing ones for this test.
function makeProps(over: Record<string, any> = {}) {
  return {
    bm: { id: 'b1', name: 'Cafe', lat: 25.0330, lng: 121.5654, category_id: 'c1' },
    x: 10, y: 10,
    showWaypointOption: true,
    onAddWaypoint: vi.fn(),
    onClose: vi.fn(),
    // ...remaining required handlers (onEdit/onDelete/onSetAsGoldDittoA/etc.)
    //    filled as vi.fn() per the props interface
    ...over,
  }
}

describe('BookmarkContextMenu add-to-route action (D4 guard)', () => {
  it('fires onAddWaypoint(lat,lng) and closes when in route mode', () => {
    const onAddWaypoint = vi.fn()
    const onClose = vi.fn()
    render(<BookmarkContextMenu {...(makeProps({ onAddWaypoint, onClose }) as any)} />)
    fireEvent.click(screen.getByText('map.add_waypoint'))
    expect(onAddWaypoint).toHaveBeenCalledWith(25.0330, 121.5654)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('hides the add-waypoint action when not in route mode', () => {
    render(<BookmarkContextMenu {...(makeProps({ showWaypointOption: false }) as any)} />)
    expect(screen.queryByText('map.add_waypoint')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/BookmarkContextMenu.test.tsx`
Expected: Initially FAIL only if a required prop is missing from `makeProps` (a render throw) — fix `makeProps` to match the real props interface at `BookmarkContextMenu.tsx`, after which the test reflects the real, already-implemented behavior. (There is no production code change in this task — the action exists; this is a coverage guard.)

- [ ] **Step 3: Write minimal implementation**
None — the feature already exists (`BookmarkContextMenu.tsx:317-337`). This task only adds the regression-guard test. If `makeProps` needs every required handler, fill the remaining ones as `vi.fn()` per the props interface.

- [ ] **Step 4: Run test to verify it passes**
Run: `cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/BookmarkContextMenu.test.tsx && npx tsc --noEmit`
Expected: PASS (2 tests) and no `tsc` errors.

- [ ] **Step 5: Commit**
```bash
git add frontend/src/components/BookmarkContextMenu.test.tsx && git commit -m "test(bookmark): guard the existing add-to-route context-menu action

D4 was already wired end-to-end (BookmarkContextMenu add-waypoint gated by
showWaypointOption, onAddWaypoint -> App.handleAddWaypoint). Add the missing
characterization test for the bookmark-popover path; no behavior change.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YDA5YujGAhKh9bgMY7W1gd"
```
