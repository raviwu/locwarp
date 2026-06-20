# Clean Architecture Refactor — Phase 2 (spec-literal) Implementation Plan

> **For agentic workers:** Execute this plan task-by-task using the **superpowers:subagent-driven-development** skill — one subagent per Task, TDD inner loop (write the failing test, run it red, implement the minimum, run it green, commit). Each Task is sized to one subagent + one commit. Do NOT batch tasks; the per-task pytest + import-linter gates are the safety net. Groups are ordered by dependency — execute Group 1 → Group 7 in order. Within a group, execute tasks in the numbered order.

## Goal

Complete **Phase 2 (variant C / spec-literal)** of the LocWarp clean-architecture refactor: kill the service-locator (`from main import app_state`), fold geocode `HTTPException`s into domain `GeocodeError`s mapped at the boundary, remove the last `infra→api` import edge, replace the api→api broadcast lazy-imports with the injected `EventPublisher`, lock the engine registry's teardown path, and remove the two import-time side effects in `config.py`. The terminal artifact is **five enforced import-linter contracts (`5 kept, 0 broken`)** plus an unchanged external HTTP/WS/IPC surface.

## Architecture

Backend rings, dependencies point inward only:

`bootstrap/` (composition root, the ONLY ring that imports every other ring) → `api/` + `infra/` (outermost adapters) → `services/` (use-cases) → `core/` (engine + movers) → `domain/` (pure: models, `events.py`, `movement.py`, `errors.py`, `ports/`).

The three load-bearing inversions (already partly wired in Phase 1, extended here):
- engine → `DevicePort` (infra `device_manager` injected)
- `device_manager` → `EventPublisher` (api WS publisher injected; awaited, in-line, order-preserving)
- `device_manager` → `TunnelRegistry` (infra `wifi_tunnel` injected, owning `_tunnels` + `_tunnels_lock`)

DI = one `Container` on `app.state`, synchronous providers in `api/deps.py`, no DI framework. Module-level adapter code that runs outside a request reaches the container via a process-global `bootstrap/runtime.py` handle (set once at container-build time).

## Tech Stack

- **Backend:** Python 3.13, FastAPI, pydantic, pytest (`asyncio_mode = strict` — every async test module declares `pytestmark = pytest.mark.asyncio`), import-linter (`lint-imports` / `python -m importlinter.cli lint`).
- **Frontend:** untouched by this plan (335 vitest + 2 e2e, tsc clean) except as a final-gate verification in Group 7.
- **Hardware seam:** `pymobiledevice3` / `usbmuxd` / SIP / tunnel-helper wrapped behind narrow ports; never abstracted into pure cores.

## Global Constraints

These rules are FROZEN for the entire plan and apply to EVERY task. Copy verbatim into each subagent's brief.

- **Behavior / API freeze.** No external HTTP / WS / IPC change. WS payloads are compared **deep-equal JSON** (not literal bytes), serialized `exclude_unset` / `exclude_none` so absent keys stay absent.
- **Baseline (re-pin before starting each group):** `cd backend && .venv/bin/python -m pytest --collect-only -q` → **754 collected** (verified 2026-06-20). Each task adds characterization/regression tests; the suite must stay GREEN and the 754 pre-existing tests must all still pass. Treat the per-task collected counts in the steps as **deltas over the live baseline**, not absolutes — re-run `--collect-only -q` before each commit and adjust the asserted numbers.
- **HTTP route count is frozen at 97** (`grep -rhnE '@(router|app)\.(get|post|put|delete|patch)' api/*.py main.py | wc -l` → 97). No task adds, removes, or re-shapes a route.
- **Frozen WS type set.** The migration to the injected `EventPublisher` MUST preserve the exact `(type, payload)` tuples for every emission site: `device_connected`, `device_disconnected`, `tunnel_recovered`, `tunnel_degraded`, `tunnel_lost`, `device_error`, `bookmarks_changed`, `routes_changed`. No new WS type, no payload key added/removed/renamed.
- **Danger-zone-tests-first.** `simulation_engine.py`, all movers, `api/location.py`, `device_manager` recovery, `phone_control.py`, `_attempt_tunnel_restart`, `_per_tunnel_watchdog`, `_auto_sync_new_device_to_primary`, and the cloud-sync enable/disable ordering have **no direct tests**. Write characterization tests (asserting ordered exact tuples) **before** touching them.
- **The 5 final enforced import-linter contracts** (terminal state after Group 7):
  1. `no-core-imports-api` — Core must not import API (already enforced, Phase 1; kept untouched).
  2. `no-services-imports-fastapi` — Services must not import FastAPI (services raise domain errors; the spec-mandated fold is the geocode `GeocodeError` path).
  3. `no-infra-imports-api` — Infra must not import API (the last wrong-direction edge, killed in Group 3).
  4. `no-api-imports-api` — API modules must not import each other (the `api.deps` DI shim is the sole sanctioned exception).
  5. `no-api-imports-main` — API must not import the composition root (the Phase-2 cycle gate; zero `from main import` in `api/`).
  `root_packages` must list `api core services models domain infra` (and `main` for contract 5). Each contract flips from report-only to enforced at the exit of the group that establishes its invariant; Group 7 is the terminal gate that asserts all five `kept, 0 broken`.
- **Personal-repo commit style.** This is a personal single-developer repo under `~/personal/`. Ship as direct commits to local `main` — no PR ceremony, no `/pr-review-loop`, no Copilot review. Git identity is auto-set by `~/.gitconfig` includeIf — **never pass `-c user.email=...` / `-c user.name=...`**. Commit messages are plain conventional-commits with NO `Co-Authored-By:` and NO `Claude-Session:` trailers (those trailers are for shared `~/work/` repos only). Force-push to local main is allowed only when amending a not-yet-pushed commit; prefer `--force-with-lease`.

### Shared-contract names (normalized — use these EXACT identifiers everywhere)

| Concept | Canonical name |
|---------|----------------|
| Container attr for AppState | `container.engine_registry` |
| deps provider for it | `get_engine_registry` |
| Container service/singleton attrs | `container.cooldown_timer`, `container.coord_formatter`, `container.helper_client`, `container.geocoding_service`, `container.route_service`, `container.gpx_service`, `container.bookmark_manager`, `container.route_manager`, `container.event_publisher`, `container.device_manager`, `container.tunnel_registry` |
| deps providers | `get_cooldown_timer`, `get_coord_formatter`, `get_helper_client`, `get_geocoding_service`, `get_route_service`, `get_gpx_service`, `get_bookmark_manager` (503 if None), `get_route_manager` (503 if None), `get_event_publisher`, `get_device_manager`, `get_device_service` |
| Locked engine teardown | `AppState.remove_engine(udid)` (async) |
| Force-rebuild engine | `AppState.create_engine_for_device(udid, force: bool = False)` |
| Domain error | `GeocodeError(status_code, code, detail)` |
| Tunnel registry state module | `infra/device/tunnel_state.py` (exports `_tunnels`, `_tunnels_lock`, `_tunnel_watchdogs`) |
| Relocated restart fn | `infra/device/tunnel_restart.py::attempt_tunnel_restart` |
| Extracted services | `services/group_sync_service.py::GroupSyncService`, `services/cloud_sync_service.py::CloudSyncService`, `infra/events/ws_event_publisher.py::WsEventPublisher` |
| Process-global container handle | `bootstrap/runtime.py` (`set_container` / `get_container`) |

`root_packages` and contract blocks in `.importlinter` are a **shared-file merge point** across Groups 1–7. Edits are **additive only**: each group adds its own contract block + ensures its needed root packages are present (idempotent — never duplicate a `root_packages` line or a `[importlinter:contract:*]` section). Group 7 is the de-dupe / final-shape authority.

---

## Group 1: Geocode HTTPException → domain errors

This group is self-contained and **MUST execute first** (no dependency on Groups 2–7). It pins the current behavior of the geocode service + the two uncovered endpoints (`/real-location`, `/route-optimize`) and the reverse-endpoint offline swallow with characterization tests, introduces `domain/errors.py::GeocodeError`, migrates `services/geocoding.py` off `fastapi.HTTPException`, maps the domain error back to an identical `HTTPException` at the `api/geocode.py` boundary, and flips `no-services-imports-fastapi` to ENFORCED.

**The 9 geocode failure modes — exact `(status_code, detail)` the executor MUST keep byte-identical (deep-equal JSON `{"detail": ...}`):**

| # | Trigger | status | detail string |
|---|---------|--------|---------------|
| 1 | `search(provider="google", google_key=None)` | 400 | `provider=google requires google_key` |
| 2 | Google HTTP non-200 (e.g. 403) | 502 | `Google geocode HTTP {status}: {text}` (text = `resp.text[:200]`) |
| 3 | Google `status` not in (OK, ZERO_RESULTS), with `error_message` | 502 | `Google geocode {status}: {error_message}` |
| 4 | Google `status` not in (OK, ZERO_RESULTS), no `error_message` | 502 | `Google geocode {status}: {status}` |
| 5 | Nominatim `/search` `raise_for_status()` | httpx.HTTPStatusError (NOT mapped in service; propagates) | upstream |
| 6 | Nominatim `/reverse` `raise_for_status()` | caught by api broad-except → 200 offline fallback | upstream |
| 7 | `/real-location` all 3 providers fail | 502 | `All IP geolocation providers failed ({last_err})` |
| 8 | `/route-optimize` `< 2` waypoints | 400 | `need >=2 waypoints` |

Modes #1–#4 move into `GeocodeError` (service layer); the api `/search` handler re-maps them to `HTTPException(exc.status_code, detail=exc.detail)`. Modes #5–#8 stay exactly where they are.

---

### Task 1: Strengthen char-tests for geocode service + pin the 2 uncovered endpoints + reverse offline swallow (Group 1)

**Files:**
- Modify `backend/tests/test_geocoding_cov.py` — strengthen the 2 `raise_for_status` propagation tests (lines 172-178 and 393-399) with an extra exception-identity assertion; these already pass and stay GREEN.
- Create `backend/tests/test_geocode_api_uncovered.py` — NEW char-tests for `/real-location`, `/route-optimize`, and the reverse offline-swallow-of-`httpx.HTTPStatusError` path. Pure characterization against UNCHANGED code.

**Interfaces:** Consumes nothing. Produces a frozen behavioral snapshot that Tasks 3/4 must keep green.

- [ ] Step 1: Append the exception-identity assertion to `test_nominatim_raise_for_status_propagates` (lines 172-178) and `test_reverse_raise_for_status_propagates` (lines 393-399) in `backend/tests/test_geocoding_cov.py`:

```python
@pytest.mark.asyncio
async def test_nominatim_raise_for_status_propagates(monkeypatch, svc):
    exc = httpx.HTTPStatusError("boom", request=None, response=None)
    resp = _FakeResponse(raise_exc=exc)
    _patch_client(monkeypatch, resp)
    with pytest.raises(httpx.HTTPStatusError) as ei:
        await svc.search("anything")
    # The httpx error is NOT remapped to a domain/HTTP error in the service
    # layer — it propagates verbatim (mapped at the api boundary instead).
    assert ei.value is exc
    assert str(ei.value) == "boom"
```

```python
@pytest.mark.asyncio
async def test_reverse_raise_for_status_propagates(monkeypatch, svc):
    exc = httpx.HTTPStatusError("boom", request=None, response=None)
    resp = _FakeResponse(raise_exc=exc)
    _patch_client(monkeypatch, resp)
    with pytest.raises(httpx.HTTPStatusError) as ei:
        await svc.reverse(1.0, 2.0)
    assert ei.value is exc
    assert str(ei.value) == "boom"
```

- [ ] Step 2: Create `backend/tests/test_geocode_api_uncovered.py` with char-tests for the two uncovered endpoints + the reverse offline-swallow. `/real-location` patches `api.geocode.httpx.AsyncClient` (the endpoint constructs the client directly in-module); `/route-optimize` patches the matrix helpers (`osrm_table` / `valhalla_matrix`) as imported into the `api.geocode` namespace.

```python
"""Characterization tests for the two previously-uncovered geocode endpoints
(/real-location, /route-optimize) and the reverse offline-swallow of an
httpx.HTTPStatusError. Pins CURRENT behavior before the GeocodeError migration.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


class _RLResponse:
    def __init__(self, *, json_data=None, raise_exc=None):
        self._json = json_data
        self._raise_exc = raise_exc

    def json(self):
        return self._json

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc


class _RLClient:
    """Async ctx-manager whose .get() returns canned responses in call order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        self.urls.append(url)
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _patch_rl(monkeypatch, responses):
    import api.geocode as geo_api

    def _factory(*args, **kwargs):
        return _RLClient(responses)

    monkeypatch.setattr(geo_api.httpx, "AsyncClient", _factory)


def test_real_location_happy_first_provider(monkeypatch, client):
    _patch_rl(monkeypatch, [_RLResponse(json_data={
        "success": True, "latitude": 25.04, "longitude": 121.56,
        "city": "Taipei", "country": "Taiwan"})])
    res = client.get("/api/geocode/real-location")
    assert res.status_code == 200
    assert res.json() == {"lat": 25.04, "lng": 121.56, "city": "Taipei", "country": "Taiwan"}


def test_real_location_first_provider_403_continues_to_second(monkeypatch, client):
    _patch_rl(monkeypatch, [
        httpx.HTTPStatusError("403", request=None, response=None),
        _RLResponse(json_data={"status": "success", "lat": 35.68, "lon": 139.76,
                               "city": "Tokyo", "country": "Japan"})])
    res = client.get("/api/geocode/real-location")
    assert res.status_code == 200
    assert res.json() == {"lat": 35.68, "lng": 139.76, "city": "Tokyo", "country": "Japan"}


def test_real_location_no_coords_continues_to_next(monkeypatch, client):
    _patch_rl(monkeypatch, [
        _RLResponse(json_data={"success": False}),
        _RLResponse(json_data={"status": "fail"}),
        _RLResponse(json_data={"latitude": 1.5, "longitude": 2.5,
                               "city": "X", "country_name": "Country X"})])
    res = client.get("/api/geocode/real-location")
    assert res.status_code == 200
    assert res.json() == {"lat": 1.5, "lng": 2.5, "city": "X", "country": "Country X"}


def test_real_location_all_providers_fail_raises_502(monkeypatch, client):
    _patch_rl(monkeypatch, [
        httpx.HTTPStatusError("a", request=None, response=None),
        httpx.HTTPStatusError("b", request=None, response=None),
        httpx.HTTPStatusError("c", request=None, response=None)])
    res = client.get("/api/geocode/real-location")
    assert res.status_code == 502
    assert "All IP geolocation providers failed" in res.json()["detail"]


def _wps(n):
    return [{"lat": 25.0 + i * 0.001, "lng": 121.5 + i * 0.001} for i in range(n)]


def test_route_optimize_under_two_waypoints_raises_400(client):
    res = client.post("/api/geocode/route-optimize", json={"waypoints": _wps(1)})
    assert res.status_code == 400
    assert res.json()["detail"] == "need >=2 waypoints"


def test_route_optimize_happy_used_estimate_false(monkeypatch, client):
    import api.geocode as geo_api

    async def fake_osrm(coords, profile="foot"):
        n = len(coords)
        return [[0.0 if i == j else 100.0 for j in range(n)] for i in range(n)]

    monkeypatch.setattr(geo_api, "osrm_table", fake_osrm)
    res = client.post("/api/geocode/route-optimize",
                      json={"waypoints": _wps(3), "engine": "osrm"})
    assert res.status_code == 200
    body = res.json()
    assert body["used_estimate"] is False
    assert len(body["waypoints"]) == 3
    assert body["total_duration_s"] >= 0.0
    assert body["total_distance_m"] >= 0.0


def test_route_optimize_happy_used_estimate_true_haversine_fallback(monkeypatch, client):
    import api.geocode as geo_api

    async def fake_none(coords, profile="foot"):
        return None

    monkeypatch.setattr(geo_api, "osrm_table", fake_none)
    monkeypatch.setattr(geo_api, "valhalla_matrix", fake_none)
    res = client.post("/api/geocode/route-optimize",
                      json={"waypoints": _wps(3), "engine": "osrm"})
    assert res.status_code == 200
    body = res.json()
    assert body["used_estimate"] is True
    assert len(body["waypoints"]) == 3
```

- [ ] Step 3: Run both files, expect PASS (characterization — freezes EXISTING behavior, no implementation change):
  `cd backend && .venv/bin/python -m pytest tests/test_geocoding_cov.py tests/test_geocode_api_uncovered.py -v`

- [ ] Step 4: Confirm the full suite stays green at baseline + 9 new:
  `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -5`
  Expect `763 passed` (754 baseline + 9 new; the 2 edited tests are not new collections).

- [ ] Step 5: Commit:
```bash
cd backend && git add tests/test_geocoding_cov.py tests/test_geocode_api_uncovered.py
git commit -m "test(geocode): pin real-location/route-optimize + reverse offline swallow

Characterization before the GeocodeError migration. Adds coverage for the two
previously-untested endpoints (/real-location 3-provider cascade incl all-fail
502; /route-optimize <2-waypoint 400 + used_estimate true/false) and tightens
the raise_for_status propagation chars to assert the httpx error identity."
```

---

### Task 2: Create `domain/errors.py::GeocodeError` + register `domain` in import-linter (report-only `no-services-imports-fastapi`) (Group 1)

**Files:**
- Create `backend/domain/errors.py` — stdlib-only `GeocodeError`.
- Create `backend/tests/test_domain_errors.py` — pins the constructor + stdlib-only purity.
- Modify `backend/.importlinter` (add `domain` + `infra` to `root_packages`; append a report-only contract).

**Interfaces:** Produces `domain.errors.GeocodeError(status_code: int, code: str, detail: str)` with `.status_code`, `.code`, `.detail` and `str(e) == detail`. Consumed by Task 3 (raise) and Task 4 (catch + map).

- [ ] Step 1: Write the failing test `backend/tests/test_domain_errors.py`:

```python
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
```

- [ ] Step 2: Run, expect FAIL (`ModuleNotFoundError: No module named 'domain.errors'`):
  `cd backend && .venv/bin/python -m pytest tests/test_domain_errors.py -v`

- [ ] Step 3: Create `backend/domain/errors.py`:

```python
"""Pure domain error types.

Imports: stdlib ONLY — never fastapi, httpx, starlette, or any outer ring.
The api boundary translates these into transport errors (e.g. GeocodeError
-> fastapi.HTTPException(status_code=exc.status_code, detail=exc.detail)).
"""

from __future__ import annotations


class GeocodeError(Exception):
    """Raised by the geocoding service for forward-geocode failures.

    Carries an HTTP-status *hint* (mapped 1:1 to the response status at the
    api boundary), a machine-readable ``code``, and a human-readable
    ``detail`` (the string surfaced to the client verbatim).
    """

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
```

- [ ] Step 4: Run, expect PASS (4 passed):
  `cd backend && .venv/bin/python -m pytest tests/test_domain_errors.py -v`

- [ ] Step 5: Register `domain` + `infra` as root packages and add a REPORT-ONLY `no-services-imports-fastapi` contract. Edit `backend/.importlinter` so `root_packages` reads `api / core / services / models / domain / infra`, and append after the existing `no-core-imports-api` block:

```ini
# Phase 2 (Group 1): services must not import fastapi. REPORT-ONLY here — it is
# still broken until services/geocoding.py drops `from fastapi import
# HTTPException` (next task). Flipped to ENFORCED at the end of Group 1.
[importlinter:contract:no-services-imports-fastapi]
name = Services must not import FastAPI
type = forbidden
source_modules =
    services
forbidden_modules =
    fastapi
```

  Verify `no-core-imports-api` is still KEPT and `no-services-imports-fastapi` reports BROKEN (acceptable while report-only — no test asserts on it yet):
  `cd backend && .venv/bin/lint-imports --config .importlinter 2>&1 | tail -25`
  (If `lint-imports` is not on PATH, use `.venv/bin/python -m importlinter.cli lint --config .importlinter`.)

  Then commit:
```bash
cd backend && git add domain/errors.py tests/test_domain_errors.py .importlinter
git commit -m "feat(domain): add GeocodeError + register domain/infra in import-linter

Pure stdlib-only domain error carrying (status_code, code, detail). Adds the
report-only no-services-imports-fastapi contract (still BROKEN until the
geocoding service migrates off HTTPException) and registers domain + infra as
root packages so later P2 contracts can reference them."
```

---

### Task 3: Migrate `services/geocoding.py` — raise `GeocodeError` instead of `HTTPException` (Group 1)

**Files:**
- Modify `backend/services/geocoding.py` (remove `from fastapi import HTTPException` at line 20; replace the 3 raises at lines 54-57, 110-113, 121-124).
- Modify `backend/tests/test_geocoding_cov.py` (the 3 service-level tests that assert `HTTPException` now assert `GeocodeError`, with identical `.status_code` + `.detail`).

**Interfaces:** Consumes `domain.errors.GeocodeError` (Task 2). Produces `GeocodingService.search()` raising `GeocodeError` for the 3 forward-geocode failure modes. The `raise_for_status()` httpx propagation paths are UNCHANGED.

- [ ] Step 1: Update the 3 service-level char-tests in `backend/tests/test_geocoding_cov.py`. At line 18, add `from domain.errors import GeocodeError` (keep the existing `from fastapi import HTTPException` for unchanged tests). Rewrite the 4 forward-failure tests to expect `GeocodeError` with identical status/detail:

```python
@pytest.mark.asyncio
async def test_search_google_without_key_raises_geocode_error_400(svc):
    with pytest.raises(GeocodeError) as ei:
        await svc.search("anywhere", provider="google", google_key=None)
    assert ei.value.status_code == 400
    assert ei.value.detail == "provider=google requires google_key"


@pytest.mark.asyncio
async def test_google_non_200_raises_geocode_error_502(monkeypatch, svc):
    resp = _FakeResponse(json_data=None, status_code=403, text="Forbidden body text")
    _patch_client(monkeypatch, resp)
    with pytest.raises(GeocodeError) as ei:
        await svc.search("x", provider="google", google_key="KEY")
    assert ei.value.status_code == 502
    assert ei.value.detail == "Google geocode HTTP 403: Forbidden body text"


@pytest.mark.asyncio
async def test_google_error_status_raises_geocode_error_502_with_error_message(monkeypatch, svc):
    resp = _FakeResponse(json_data={"status": "REQUEST_DENIED",
                                    "error_message": "The provided API key is invalid."})
    _patch_client(monkeypatch, resp)
    with pytest.raises(GeocodeError) as ei:
        await svc.search("x", provider="google", google_key="BAD")
    assert ei.value.status_code == 502
    assert ei.value.detail == "Google geocode REQUEST_DENIED: The provided API key is invalid."


@pytest.mark.asyncio
async def test_google_error_status_without_error_message_falls_back_to_status(monkeypatch, svc):
    resp = _FakeResponse(json_data={"status": "OVER_QUERY_LIMIT"})
    _patch_client(monkeypatch, resp)
    with pytest.raises(GeocodeError) as ei:
        await svc.search("x", provider="google", google_key="KEY")
    assert ei.value.status_code == 502
    assert ei.value.detail == "Google geocode OVER_QUERY_LIMIT: OVER_QUERY_LIMIT"
```

- [ ] Step 2: Run, expect FAIL (4 failures `DID NOT RAISE GeocodeError` — service still raises `HTTPException`):
  `cd backend && .venv/bin/python -m pytest tests/test_geocoding_cov.py -v -k "geocode_error or falls_back"`

- [ ] Step 3: Migrate `backend/services/geocoding.py`. Replace line 20 `from fastapi import HTTPException` with `from domain.errors import GeocodeError`. Replace the 3 raises:

```python
        if provider == "google":
            if not google_key:
                raise GeocodeError(
                    status_code=400,
                    code="google_missing_key",
                    detail="provider=google requires google_key",
                )
            return await self._search_google(query, limit, google_key)
```
```python
        if resp.status_code != 200:
            text = resp.text[:200] if resp.text else ""
            raise GeocodeError(
                status_code=502,
                code="google_http",
                detail=f"Google geocode HTTP {resp.status_code}: {text}",
            )
```
```python
        if status not in ("OK", "ZERO_RESULTS"):
            err_msg = data.get("error_message") or status or "unknown error"
            raise GeocodeError(
                status_code=502,
                code="google_status",
                detail=f"Google geocode {status}: {err_msg}",
            )
```

  (The two `resp.raise_for_status()` calls in `_search_nominatim` and `reverse` STAY — they raise `httpx.HTTPStatusError`, mapped at the api boundary.)

- [ ] Step 4: Run, expect PASS (renamed tests see `GeocodeError`; the 2 `raise_for_status` chars still see `httpx.HTTPStatusError`):
  `cd backend && .venv/bin/python -m pytest tests/test_geocoding_cov.py -v`

- [ ] Step 5: Commit:
```bash
cd backend && git add services/geocoding.py tests/test_geocoding_cov.py
git commit -m "refactor(geocoding): raise GeocodeError instead of fastapi HTTPException

The service layer no longer imports fastapi. The 3 forward-geocode failure
modes now raise domain.errors.GeocodeError with byte-identical detail strings.
raise_for_status httpx errors still propagate untouched, mapped at the api
boundary next."
```

---

### Task 4: Map `GeocodeError` at the api boundary + verify identical wire responses + ENFORCE `no-services-imports-fastapi` (Group 1)

**Files:**
- Modify `backend/api/geocode.py` (the `search_address` handler gains a try/except mapping `GeocodeError` → `HTTPException`; add the import).
- Create `backend/tests/test_geocode_api_error_mapping.py` — end-to-end deep-equal wire-response tests proving the 4 forward-geocode failure modes return identical `(status_code, {"detail": ...})` JSON AND the reverse endpoint swallows a `GeocodeError`/`httpx` error into a 200 offline fallback (never a 500).
- Modify `backend/.importlinter` (flip the `no-services-imports-fastapi` comment to enforced — the contract is already `forbidden`, so flipping = it must now be KEPT).

**Interfaces:** Consumes `GeocodeError` (Task 2) + the migrated service (Task 3). Produces the final api boundary mapping.

- [ ] Step 1: Write the failing wire-response test `backend/tests/test_geocode_api_error_mapping.py`:

```python
"""End-to-end wire-response tests for the GeocodeError -> HTTPException mapping."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from domain.errors import GeocodeError


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


def _raise(exc):
    async def _boom(*args, **kwargs):
        raise exc
    return _boom


def test_search_missing_google_key_maps_to_400(monkeypatch, client):
    import api.geocode as geo_api
    monkeypatch.setattr(geo_api.geocoding_service, "search",
                        _raise(GeocodeError(400, "google_missing_key",
                                            "provider=google requires google_key")))
    res = client.get("/api/geocode/search", params={"q": "x", "provider": "google"})
    assert res.status_code == 400
    assert res.json() == {"detail": "provider=google requires google_key"}


def test_search_google_http_maps_to_502(monkeypatch, client):
    import api.geocode as geo_api
    monkeypatch.setattr(geo_api.geocoding_service, "search",
                        _raise(GeocodeError(502, "google_http",
                                            "Google geocode HTTP 403: Forbidden body text")))
    res = client.get("/api/geocode/search", params={"q": "x"})
    assert res.status_code == 502
    assert res.json() == {"detail": "Google geocode HTTP 403: Forbidden body text"}


def test_search_google_status_maps_to_502(monkeypatch, client):
    import api.geocode as geo_api
    monkeypatch.setattr(geo_api.geocoding_service, "search",
                        _raise(GeocodeError(502, "google_status",
                                            "Google geocode REQUEST_DENIED: The provided API key is invalid.")))
    res = client.get("/api/geocode/search", params={"q": "x"})
    assert res.status_code == 502
    assert res.json() == {"detail": "Google geocode REQUEST_DENIED: The provided API key is invalid."}


def test_search_httpx_error_still_propagates_as_500(monkeypatch, client):
    # httpx errors are NOT GeocodeError -> not remapped; FastAPI -> 500.
    # Pins that the mapping is SCOPED to GeocodeError only.
    import api.geocode as geo_api
    monkeypatch.setattr(geo_api.geocoding_service, "search",
                        _raise(httpx.HTTPStatusError("boom", request=None, response=None)))
    res = client.get("/api/geocode/search", params={"q": "x"}, follow_redirects=False)
    assert res.status_code == 500


def test_reverse_swallows_geocode_error_into_offline_200(monkeypatch, client):
    import api.geocode as geo_api
    import services.geo_offline as geo_offline
    monkeypatch.setattr(geo_api.geocoding_service, "reverse",
                        _raise(GeocodeError(502, "x", "upstream boom")))
    monkeypatch.setattr(geo_offline, "resolve",
                        lambda _lat, _lng: ("jp", "Asia/Tokyo", "Tokyo", "Tokyo"))
    res = client.get("/api/geocode/reverse", params={"lat": 35.6586, "lng": 139.7454})
    assert res.status_code == 200
    body = res.json()
    assert body["country_code"] == "jp"
    assert "Tokyo" in body["display_name"]
```

- [ ] Step 2: Run, expect FAIL on the 3 GeocodeError-mapping tests (handler does not yet catch `GeocodeError` → FastAPI returns 500). The httpx-500 + reverse-swallow tests PASS already:
  `cd backend && .venv/bin/python -m pytest tests/test_geocode_api_error_mapping.py -v`

- [ ] Step 3: Add the boundary mapping to `backend/api/geocode.py`. Add `from domain.errors import GeocodeError` after the existing `from services.geocoding import ...` import. Wrap the `search_address` handler body:

```python
    try:
        return await geocoding_service.search(q, limit, provider, google_key)
    except GeocodeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
```

  (The reverse handler already `except Exception:` — `GeocodeError` is an `Exception`, so it is swallowed into the offline fallback unchanged. No edit there.)

- [ ] Step 4: Run, expect PASS:
  `cd backend && .venv/bin/python -m pytest tests/test_geocode_api_error_mapping.py tests/test_geocoding_cov.py tests/test_geocode_api.py tests/test_geocode_api_uncovered.py -v`

- [ ] Step 5: Flip `no-services-imports-fastapi` to ENFORCED (update the comment block above the contract to read as enforced), run the full linter + full suite, then commit. Both contracts must be KEPT:
  `cd backend && .venv/bin/lint-imports --config .importlinter 2>&1 | tail -25` → `Contracts: 2 kept, 0 broken`.
  If a `services.*` module still imports fastapi: `grep -rn "import fastapi\|from fastapi" services/ | grep -v __pycache__`.
  Full freeze check:
  `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -5`
  `cd backend && .venv/bin/python -c "import main; print('routes', len([r for r in main.app.routes if hasattr(r, 'methods')]))"`
  Then commit:
```bash
cd backend && git add api/geocode.py tests/test_geocode_api_error_mapping.py .importlinter
git commit -m "refactor(geocode): map GeocodeError at api boundary + enforce no-services-fastapi

The /search handler catches domain GeocodeError and re-raises an identical
HTTPException(status_code, detail) — byte-identical wire responses for all 4
forward failure modes. Reverse still swallows the error into the 200 offline
fallback. Flips the no-services-imports-fastapi contract to enforced (2 kept,
0 broken)."
```

**Group 1 done-criteria:** `no-core-imports-api` + `no-services-imports-fastapi` both KEPT; `services/geocoding.py` has zero fastapi imports; all 9 geocode failure modes return identical `(status_code, detail)`; full suite green; HTTP route count unchanged.

---

## Group 2: Container foundation + the concurrency lock fix

Exposes `container.engine_registry` + the service singletons as first-class Container attributes, adds the matching `api/deps.py` providers, adds the locked `AppState.remove_engine` + `create_engine_for_device(force=)`, and fixes the live `DeviceService.disconnect` race. Depends on nothing in later groups, but Groups 1/3 also touch `.importlinter` `root_packages` (additive merge — see Global Constraints). G2 only ensures `infra` is present; it adds NO new contract.

**Context (verified against current code):**
- `bootstrap/container.py` takes `engine_registry` as a ctor kwarg but does NOT store it as `self.engine_registry` — it only forwards it into `DeviceService`. (Confirmed against the live file.)
- `main.py` builds the Container from `app_state` singletons (verified at lines 976-982). `geocoding_service` / `route_service` / `gpx_service` are currently module-level singletons inside `api/geocode.py` / `api/route.py`, NOT constructed in main.py; all five service classes have zero-arg constructors.
- **LIVE RACE (confirmed):** `services/device_service.py` `disconnect` does `pop` + `_primary_udid` promote with NO `_engines_lock`, reachable via `DELETE /{udid}/connect`.

---

### Task 5: Expose `engine_registry` + service singletons as first-class Container attributes (Group 2)

**Files:**
- Modify `backend/bootstrap/container.py` (ctor).
- Modify `backend/main.py` (Container construction, lines 976-982).
- Modify `backend/tests/test_bootstrap_container.py` (append assertions; update the existing `test_container_accepts_injected_singletons` call for the new required kwargs).

**Interfaces:** Produces `container.engine_registry`, `container.cooldown_timer`, `container.coord_formatter`, `container.helper_client`, `container.geocoding_service`, `container.route_service`, `container.gpx_service`, `container.bookmark_manager` (may be None pre-load), `container.route_manager` (may be None pre-load). Consumes `app_state.cooldown_timer`, `app_state.coord_formatter`, `app_state.bookmark_manager`, `app_state.route_manager`, the module-level `helper_client`.

- [ ] Step 1: Write the failing test. Append to `backend/tests/test_bootstrap_container.py`:

```python
def test_container_stores_engine_registry():
    lock = asyncio.Lock()

    class _Fake:
        pass

    eng_reg = _Fake()
    c = Container(
        device_manager=_Fake(), event_publisher=_Fake(), tunnel_registry=_Fake(),
        engines_lock=lock, engine_registry=eng_reg,
        cooldown_timer=_Fake(), coord_formatter=_Fake(), helper_client=_Fake(),
        geocoding_service=_Fake(), route_service=_Fake(), gpx_service=_Fake(),
        bookmark_manager=None, route_manager=None,
    )
    assert c.engine_registry is eng_reg


def test_container_real_app_engine_registry_identity():
    import main
    assert main.app.state.container.engine_registry is main.app_state


def test_container_real_app_service_singletons_identity():
    import main
    c = main.app.state.container
    assert c.cooldown_timer is main.app_state.cooldown_timer
    assert c.coord_formatter is main.app_state.coord_formatter
    assert c.helper_client is main.helper_client


def test_container_real_app_lazy_managers_track_app_state():
    import main
    c = main.app.state.container
    assert c.bookmark_manager is main.app_state.bookmark_manager
    assert c.route_manager is main.app_state.route_manager


def test_container_real_app_geocode_route_gpx_singletons_present():
    import main
    from services.geocoding import GeocodingService
    from services.route_service import RouteService
    from services.gpx_service import GpxService
    c = main.app.state.container
    assert isinstance(c.geocoding_service, GeocodingService)
    assert isinstance(c.route_service, RouteService)
    assert isinstance(c.gpx_service, GpxService)
```

- [ ] Step 2: Run, expect FAIL (`TypeError: __init__() got an unexpected keyword argument 'cooldown_timer'`; `AttributeError: 'Container' object has no attribute 'engine_registry'`):
  `cd backend && .venv/bin/python -m pytest tests/test_bootstrap_container.py -v`

- [ ] Step 3: Replace the `Container.__init__` body in `backend/bootstrap/container.py`:

```python
    def __init__(
        self,
        *,
        device_manager,
        event_publisher,
        tunnel_registry,
        engines_lock: asyncio.Lock,
        engine_registry,
        cooldown_timer,
        coord_formatter,
        helper_client,
        geocoding_service,
        route_service,
        gpx_service,
        bookmark_manager,
        route_manager,
    ) -> None:
        self.clock = MonotonicClock()
        self.device_manager = device_manager
        self.event_publisher = event_publisher
        self.tunnel_registry = tunnel_registry
        self._engines_lock = engines_lock
        # engine_registry (AppState) is now a first-class attribute so api/deps.py
        # can inject it into endpoints — not just forwarded into DeviceService.
        self.engine_registry = engine_registry
        self.cooldown_timer = cooldown_timer
        self.coord_formatter = coord_formatter
        self.helper_client = helper_client
        self.geocoding_service = geocoding_service
        self.route_service = route_service
        self.gpx_service = gpx_service
        # bookmark_manager / route_manager are None until AppState.load_state().
        self.bookmark_manager = bookmark_manager
        self.route_manager = route_manager

        from services.device_service import DeviceService
        self.device_service = DeviceService(
            device_manager=self.device_manager,
            tunnel_registry=self.tunnel_registry,
            engine_registry=engine_registry,
        )
```

  Update the construction call in `backend/main.py` (lines 976-982) to pass the new kwargs:

```python
from bootstrap.container import Container as _Container
app.state.container = _Container(
    device_manager=app_state.device_manager,
    event_publisher=app_state.device_manager._events,
    tunnel_registry=app_state.device_manager._tunnels,
    engines_lock=app_state._engines_lock,
    engine_registry=app_state,
    cooldown_timer=app_state.cooldown_timer,
    coord_formatter=app_state.coord_formatter,
    helper_client=helper_client,
    geocoding_service=GeocodingService(),
    route_service=RouteService(),
    gpx_service=GpxService(),
    bookmark_manager=app_state.bookmark_manager,
    route_manager=app_state.route_manager,
)
```

  Add the three service imports near the other `from services.*` imports at the top of `backend/main.py`:

```python
from services.geocoding import GeocodingService
from services.route_service import RouteService
from services.gpx_service import GpxService
```

  Also update the existing `test_container_accepts_injected_singletons` test so its `Container(...)` call passes the new required kwargs (`cooldown_timer=object()`, `coord_formatter=object()`, `helper_client=object()`, `geocoding_service=object()`, `route_service=object()`, `gpx_service=object()`, `bookmark_manager=None`, `route_manager=None`) — the four existing `assert c.<x> is <y>` lines stay.

- [ ] Step 4: Run, expect PASS. Then full suite:
  `cd backend && .venv/bin/python -m pytest tests/test_bootstrap_container.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add bootstrap/container.py main.py tests/test_bootstrap_container.py
git commit -m "feat(container): expose engine_registry + service singletons as first-class attrs"
```

---

### Task 6: Add `api/deps.py` providers for the new Container attributes (Group 2)

**Files:**
- Modify `backend/api/deps.py` (append providers after `get_device_service`; add `HTTPException` to the fastapi import).
- Create `backend/tests/test_deps_providers.py`.

**Interfaces:** Produces `get_engine_registry`, `get_cooldown_timer`, `get_coord_formatter`, `get_helper_client`, `get_geocoding_service`, `get_route_service`, `get_gpx_service`, `get_bookmark_manager` (raises `HTTPException(503)` if None), `get_route_manager` (503 if None). Each reads `request.app.state.container.<attr>`. Consumes the Container attributes added in Task 5.

- [ ] Step 1: Create the failing test `backend/tests/test_deps_providers.py`:

```python
"""api/deps.py providers resolve the right Container attribute; the lazy-manager
providers raise 503 while the manager is still None (pre-load_state)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import deps


def _fake_request(container):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=container)))


def test_simple_providers_return_container_attrs():
    c = SimpleNamespace(
        engine_registry=object(), cooldown_timer=object(), coord_formatter=object(),
        helper_client=object(), geocoding_service=object(), route_service=object(),
        gpx_service=object())
    req = _fake_request(c)
    assert deps.get_engine_registry(req) is c.engine_registry
    assert deps.get_cooldown_timer(req) is c.cooldown_timer
    assert deps.get_coord_formatter(req) is c.coord_formatter
    assert deps.get_helper_client(req) is c.helper_client
    assert deps.get_geocoding_service(req) is c.geocoding_service
    assert deps.get_route_service(req) is c.route_service
    assert deps.get_gpx_service(req) is c.gpx_service


def test_bookmark_manager_provider_returns_when_present():
    mgr = object()
    assert deps.get_bookmark_manager(_fake_request(SimpleNamespace(bookmark_manager=mgr))) is mgr


def test_bookmark_manager_provider_raises_503_when_none():
    with pytest.raises(HTTPException) as exc:
        deps.get_bookmark_manager(_fake_request(SimpleNamespace(bookmark_manager=None)))
    assert exc.value.status_code == 503


def test_route_manager_provider_returns_when_present():
    mgr = object()
    assert deps.get_route_manager(_fake_request(SimpleNamespace(route_manager=mgr))) is mgr


def test_route_manager_provider_raises_503_when_none():
    with pytest.raises(HTTPException) as exc:
        deps.get_route_manager(_fake_request(SimpleNamespace(route_manager=None)))
    assert exc.value.status_code == 503
```

- [ ] Step 2: Run, expect FAIL (`AttributeError: module 'api.deps' has no attribute 'get_engine_registry'`):
  `cd backend && .venv/bin/python -m pytest tests/test_deps_providers.py -v`

- [ ] Step 3: Change the deps import to `from fastapi import HTTPException, Request`, then append:

```python
def get_engine_registry(request: Request):
    return request.app.state.container.engine_registry


def get_cooldown_timer(request: Request):
    return request.app.state.container.cooldown_timer


def get_coord_formatter(request: Request):
    return request.app.state.container.coord_formatter


def get_helper_client(request: Request):
    return request.app.state.container.helper_client


def get_geocoding_service(request: Request):
    return request.app.state.container.geocoding_service


def get_route_service(request: Request):
    return request.app.state.container.route_service


def get_gpx_service(request: Request):
    return request.app.state.container.gpx_service


def get_bookmark_manager(request: Request):
    mgr = request.app.state.container.bookmark_manager
    if mgr is None:
        raise HTTPException(status_code=503, detail="Bookmark manager not ready")
    return mgr


def get_route_manager(request: Request):
    mgr = request.app.state.container.route_manager
    if mgr is None:
        raise HTTPException(status_code=503, detail="Route manager not ready")
    return mgr
```

- [ ] Step 4: Run, expect PASS. Then full suite:
  `cd backend && .venv/bin/python -m pytest tests/test_deps_providers.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add api/deps.py tests/test_deps_providers.py
git commit -m "feat(deps): add providers for engine_registry + cooldown/coord/helper/geocode/route/gpx/managers"
```

---

### Task 7: Add async `AppState.remove_engine(udid)` (locked pop+promote) (Group 2)

**Files:**
- Modify `backend/main.py` (add method to `AppState` after `create_engine_for_device`).
- Modify `backend/tests/test_engines_lock.py` (append).

**Interfaces:** Produces `async AppState.remove_engine(self, udid)` — acquires `self._engines_lock`, pops `simulation_engines`, promotes `_primary_udid` to the next remaining udid (or `None`) only when the removed udid was primary. No-op for an unknown udid.

- [ ] Step 1: Append the failing tests to `backend/tests/test_engines_lock.py`:

```python
@pytest.mark.asyncio
async def test_remove_engine_pops_and_promotes_primary():
    from main import app_state
    app_state.simulation_engines.clear()
    app_state.simulation_engines["A"] = object()
    app_state.simulation_engines["B"] = object()
    app_state._primary_udid = "A"
    await app_state.remove_engine("A")
    assert "A" not in app_state.simulation_engines
    assert app_state._primary_udid == "B"
    app_state.simulation_engines.clear()
    app_state._primary_udid = None


@pytest.mark.asyncio
async def test_remove_engine_non_primary_keeps_primary():
    from main import app_state
    app_state.simulation_engines.clear()
    app_state.simulation_engines["A"] = object()
    app_state.simulation_engines["B"] = object()
    app_state._primary_udid = "A"
    await app_state.remove_engine("B")
    assert "B" not in app_state.simulation_engines
    assert app_state._primary_udid == "A"
    app_state.simulation_engines.clear()
    app_state._primary_udid = None


@pytest.mark.asyncio
async def test_remove_engine_last_engine_sets_primary_none():
    from main import app_state
    app_state.simulation_engines.clear()
    app_state.simulation_engines["A"] = object()
    app_state._primary_udid = "A"
    await app_state.remove_engine("A")
    assert app_state.simulation_engines == {}
    assert app_state._primary_udid is None


@pytest.mark.asyncio
async def test_remove_engine_unknown_udid_is_noop():
    from main import app_state
    app_state.simulation_engines.clear()
    app_state.simulation_engines["A"] = object()
    app_state._primary_udid = "A"
    await app_state.remove_engine("ZZZ")
    assert "A" in app_state.simulation_engines
    assert app_state._primary_udid == "A"
    app_state.simulation_engines.clear()
    app_state._primary_udid = None
```

- [ ] Step 2: Run, expect FAIL (`AttributeError: 'AppState' object has no attribute 'remove_engine'`):
  `cd backend && .venv/bin/python -m pytest tests/test_engines_lock.py -v`

- [ ] Step 3: Insert into `AppState` (in `backend/main.py`) immediately after `create_engine_for_device`:

```python
    async def remove_engine(self, udid: str) -> None:
        """Drop the engine for *udid* and promote a new primary if needed.

        Locked teardown counterpart of create_engine_for_device: acquires
        _engines_lock so a concurrent create_engine_for_device cannot race
        with the pop/promote. Promotes _primary_udid to the next remaining
        udid (or None) only when the removed udid was the primary. No-op for
        an unknown udid.
        """
        async with self._engines_lock:
            self.simulation_engines.pop(udid, None)
            if self._primary_udid == udid:
                self._primary_udid = next(iter(self.simulation_engines.keys()), None)
```

- [ ] Step 4: Run, expect PASS. Full suite:
  `cd backend && .venv/bin/python -m pytest tests/test_engines_lock.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add main.py tests/test_engines_lock.py
git commit -m "feat(appstate): add locked async remove_engine(udid) pop+promote"
```

---

### Task 8: Add `force: bool = False` to `create_engine_for_device` (in-lock drop) (Group 2)

**Files:**
- Modify `backend/main.py` (`create_engine_for_device` signature + the in-lock idempotency guard).
- Modify `backend/tests/test_engines_lock.py` (append).

**Interfaces:** Produces `async AppState.create_engine_for_device(self, udid, force: bool = False)`. When `force=True`, an existing engine for the udid is dropped **inside the lock** before rebuild — replaces the unlocked `pop()`-then-`create()` two-step at api callsites.

- [ ] Step 1: Append the failing tests to `backend/tests/test_engines_lock.py`:

```python
@pytest.mark.asyncio
async def test_create_force_rebuilds_in_lock(monkeypatch):
    from main import app_state
    app_state.simulation_engines.clear()
    app_state._primary_udid = None

    class FakeLocService:
        async def set(self, lat, lng):
            pass

    async def fake_get_location_service(udid):
        return FakeLocService()

    monkeypatch.setattr(app_state.device_manager, "get_location_service", fake_get_location_service)
    udid = "FORCE-UDID"
    await app_state.create_engine_for_device(udid)
    first = app_state.simulation_engines[udid]
    await app_state.create_engine_for_device(udid, force=True)
    second = app_state.simulation_engines[udid]
    assert second is not first
    assert list(app_state.simulation_engines.keys()).count(udid) == 1
    app_state.simulation_engines.clear()
    app_state._primary_udid = None


@pytest.mark.asyncio
async def test_concurrent_force_creates_no_double_insert(monkeypatch):
    from main import app_state
    app_state.simulation_engines.clear()
    app_state._primary_udid = None

    class FakeLocService:
        async def set(self, lat, lng):
            pass

    async def slow_get_location_service(udid):
        await asyncio.sleep(0)
        return FakeLocService()

    monkeypatch.setattr(app_state.device_manager, "get_location_service", slow_get_location_service)
    udid = "FORCE-RACE-UDID"
    await asyncio.gather(
        app_state.create_engine_for_device(udid, force=True),
        app_state.create_engine_for_device(udid, force=True),
    )
    assert list(app_state.simulation_engines.keys()).count(udid) == 1
    app_state.simulation_engines.clear()
    app_state._primary_udid = None
```

- [ ] Step 2: Run, expect FAIL (`TypeError: create_engine_for_device() got an unexpected keyword argument 'force'`):
  `cd backend && .venv/bin/python -m pytest tests/test_engines_lock.py::test_create_force_rebuilds_in_lock -v`

- [ ] Step 3: Change the signature to `async def create_engine_for_device(self, udid: str, force: bool = False):` and the in-lock idempotency guard to:

```python
        async with self._engines_lock:
            if udid in self.simulation_engines:
                if not force:
                    logger.debug("Simulation engine already exists for %s; preserving current_position", udid)
                    return
                # force: drop the stale engine INSIDE the lock before rebuild so
                # there is no unlocked pop->create window for a concurrent caller.
                self.simulation_engines.pop(udid, None)
```

  (The rest of the method is unchanged.)

- [ ] Step 4: Run, expect PASS. Full suite:
  `cd backend && .venv/bin/python -m pytest tests/test_engines_lock.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add main.py tests/test_engines_lock.py
git commit -m "feat(appstate): create_engine_for_device(force=) drops stale engine inside the lock"
```

---

### Task 9: Fix DeviceService.disconnect race (characterization-first) + migrate unguarded teardown pop sites (Group 2)

**Files:**
- Create `backend/tests/test_device_service_race_char.py` (characterization FIRST).
- Modify `backend/services/device_service.py` (`disconnect`).
- Modify `backend/tests/test_device_service.py` (the two disconnect unit tests — give the fake registry a working `remove_engine`).
- Modify `backend/api/device.py` (pop/promote sites: 666-669, 788-792, 1271-1272, 1283-1286, 1354-1355, 1580-1582).
- Modify `backend/api/location.py` (pop/promote site: 220-223).

**Interfaces:** Consumes `AppState.remove_engine` (Task 7), `create_engine_for_device(force=True)` (Task 8). Produces no public API change — internal teardown routes through the locked helper.

- [ ] Step 1: Write the failing characterization test FIRST. Create `backend/tests/test_device_service_race_char.py`:

```python
"""Characterization: DeviceService.disconnect must not race a concurrent
create_engine_for_device. Teardown goes through the locked remove_engine."""
from __future__ import annotations

import asyncio

import pytest

from services.device_service import DeviceService


@pytest.mark.asyncio
async def test_disconnect_does_not_race_concurrent_create():
    from main import app_state
    app_state.simulation_engines.clear()
    app_state._primary_udid = None
    app_state.simulation_engines["KEEP"] = object()
    app_state.simulation_engines["DROP"] = object()
    app_state._primary_udid = "DROP"

    started = asyncio.Event()

    class _DM:
        async def disconnect(self, udid):
            started.set()
            await asyncio.sleep(0)

    class FakeLocService:
        async def set(self, lat, lng):
            pass

    async def fake_get_location_service(udid):
        return FakeLocService()

    app_state.device_manager.get_location_service = fake_get_location_service

    svc = DeviceService(device_manager=_DM(), tunnel_registry=object(), engine_registry=app_state)

    async def do_create():
        await started.wait()
        await app_state.create_engine_for_device("NEW")

    await asyncio.gather(svc.disconnect("DROP"), do_create())

    assert "DROP" not in app_state.simulation_engines
    assert "KEEP" in app_state.simulation_engines
    assert "NEW" in app_state.simulation_engines
    assert app_state._primary_udid in ("KEEP", "NEW")
    app_state.simulation_engines.clear()
    app_state._primary_udid = None
```

- [ ] Step 2: Run, expect FAIL (disconnect currently does an unlocked pop+promote; with the slow create interleaving the primary-promotion assertion can pick stale state). Pin the failing run before the fix:
  `cd backend && .venv/bin/python -m pytest tests/test_device_service_race_char.py -v`
  > Note: this race is timing-dependent — if it happens to pass once, the structural contract (teardown routes through the locked `remove_engine`) is still the binding intent; proceed to make it correct-by-construction.

- [ ] Step 3: Replace `disconnect` in `backend/services/device_service.py`:

```python
    async def disconnect(self, udid: str) -> None:
        """Disconnect device (USB path) and drop the simulation engine.

        Teardown goes through engine_registry.remove_engine so the pop+promote
        runs under _engines_lock — a concurrent create_engine_for_device cannot
        race the registry mutation.
        """
        await self._dm.disconnect(udid)
        await self._engines.remove_engine(udid)
```

  Update the two disconnect unit tests in `backend/tests/test_device_service.py` to give the `MagicMock` registry a working async `remove_engine` (side_effect that pops `fake_engines` and re-promotes `_primary_udid`), asserting `engine_registry.remove_engine.assert_awaited_once_with(udid)`.

  Migrate the unguarded api teardown pop sites to the locked helpers:
  - `api/device.py` 666-669 (pure teardown) → `await app_state.remove_engine(udid)`
  - `api/device.py` 788-793 (pop-then-create) → `await app_state.create_engine_for_device(dev_info.udid, force=True)`
  - `api/device.py` 1271-1272 (pop-then-create) → `await app_state.create_engine_for_device(usb_dev.udid, force=True)`
  - `api/device.py` 1283-1286 (rollback teardown) → `await app_state.remove_engine(usb_dev.udid)`
  - `api/device.py` 1354-1355 (pop-then-create) → `await app_state.create_engine_for_device(info.udid, force=True)`
  - `api/device.py` 1580-1582 (forget teardown) → `await app_state.remove_engine(udid)`
  - `api/location.py` 220-223 (device_lost cleanup) → `await app_state.remove_engine(u)`

  Leave the **already-locked** watchdog pop/promote at `main.py:657-661` AS-IS — converting it to `remove_engine` would attempt a re-entrant `_engines_lock` acquire and deadlock (that block already holds the lock). Do NOT touch it.

- [ ] Step 4: Run, expect PASS:
  `cd backend && .venv/bin/python -m pytest tests/test_device_service_race_char.py tests/test_device_service.py tests/test_device_connect_disconnect_endpoint.py -v`
  Then full suite + confirm device_lost / wifi-tunnel-stop / forget / usb-fallback tests pass:
  `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add services/device_service.py api/device.py api/location.py tests/test_device_service_race_char.py tests/test_device_service.py
git commit -m "fix(device): route engine teardown through locked remove_engine / create(force=); kill disconnect race"
```

---

### Task 10: Ensure `infra` is in import-linter root_packages (Group 2)

**Files:**
- Modify `backend/.importlinter` (`root_packages` list).
- Modify `backend/tests/test_bootstrap_container.py` (append a config-shape guard).

**Interfaces:** None (config only). No new contract is added by G2 — only the `infra` root-package registration that Group 3's `no-infra-imports-api` contract depends on. Idempotent: if Group 1 already added `domain`/`infra`, this is a no-op assertion. Run AFTER Tasks 5-9.

- [ ] Step 1: Append the guard test:

```python
def test_importlinter_root_packages_include_infra():
    import configparser
    from pathlib import Path
    cfg = configparser.ConfigParser()
    cfg.read(Path(__file__).resolve().parent.parent / ".importlinter")
    roots = cfg.get("importlinter", "root_packages").split()
    assert "infra" in roots
```

- [ ] Step 2: Run, expect FAIL unless Group 1 already added `infra` (in which case it passes — still commit the test):
  `cd backend && .venv/bin/python -m pytest tests/test_bootstrap_container.py::test_importlinter_root_packages_include_infra -v`

- [ ] Step 3: Ensure `root_packages` in `backend/.importlinter` contains `api core services models domain infra` (add only the missing lines; never duplicate).

- [ ] Step 4: Run, expect PASS. Verify the existing enforced contracts still pass and run the full suite:
  `cd backend && .venv/bin/python -m pytest tests/test_bootstrap_container.py::test_importlinter_root_packages_include_infra -v && .venv/bin/lint-imports --config .importlinter 2>&1 | tail -5 && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add .importlinter tests/test_bootstrap_container.py
git commit -m "chore(importlinter): register infra as a root package for the no-infra-imports-api contract"
```

---

## Group 3: Kill the last infra→api edge (tunnel state + restart relocation)

Eliminates the two lazy `from api.device import …` statements in `backend/infra/device/wifi_tunnel.py` (lines 16 and 25) — the only remaining `infra→api` import edge. Four sequenced tasks: make the violation visible (report-only), move the registry state to `infra/device/tunnel_state.py`, relocate `attempt_tunnel_restart` into infra with all api/main collaborators injected, flip the contract to enforced.

**Pre-flight (run once before starting):**
```bash
cd backend && .venv/bin/python -m pytest --collect-only -q 2>/dev/null | tail -1   # re-pin baseline
.venv/bin/lint-imports --config .importlinter 2>&1 | tail -3                        # current contracts
```

**Coupling map (drives the task sequence):**
- `_tunnels` / `_tunnels_lock` / `_tunnel_watchdogs` are declared at `api/device.py:112-114`, referenced at ~30 sites. `infra/device/wifi_tunnel.py` reads `_tunnels` via lazy import; `core/device_manager.py` reaches them only through the `WifiTunnelRegistry` facade.
- `_attempt_tunnel_restart` references SIX api/main collaborators: `_tunnels`/`_tunnels_lock`/`_tunnel_watchdogs` (state), `_per_tunnel_watchdog` (the watchdog factory — STAYS in api), `_dm()` (device_manager), `from main import app_state`, `from main import _auto_sync_new_device_to_primary`, and `from api.websocket import broadcast`. Relocating it requires injecting all five non-state collaborators as parameters.

---

### Task 11: Add `infra` to import-linter root_packages + a REPORT-ONLY `no-infra-imports-api` contract; record violations (Group 3)

**Files:**
- Modify `backend/.importlinter` (ensure `root_packages` has `infra`; append a report-only contract).
- Modify `backend/tests/test_import_linter.py` (scope the returncode assertion to the core contract so the suite stays green with one known-broken report-only contract).

**Interfaces:** Produces a report-only `no-infra-imports-api` contract whose violation list is the "before" state Task 14 consumes.

- [ ] Step 1: Confirm the existing gate is green:
  `cd backend && .venv/bin/python -m pytest tests/test_import_linter.py -v`

- [ ] Step 2: Run, expect PASS (proves `no-core-imports-api` is untouched before editing the config).

- [ ] Step 3: Ensure `infra` is in `root_packages` (idempotent — Group 2 may already have added it) and append after the existing `no-core-imports-api` contract:

```ini
# Phase 2 (Group 3, Task 11): REPORT-ONLY. infra/device/wifi_tunnel.py still
# holds two lazy `from api.device import …` statements (lines 16, 25). This
# contract makes that violation visible without failing the build yet. Flipped
# to enforced in Task 14 once the relocation (Tasks 12-13) is complete.
[importlinter:contract:no-infra-imports-api]
name = Infra must not import API
type = forbidden
source_modules =
    infra
forbidden_modules =
    api
```

  Because `tests/test_import_linter.py` asserts `result.returncode == 0`, a broken contract would fail it. Re-scope that test's final assertion to the core contract only (so report-only stays non-failing). Replace its returncode-0 assertion block with:

```python
    # ENFORCED (Phase 1): the no-core->api contract must be KEPT.
    assert "Core must not import API KEPT" in report, (
        "The no-core->api contract is no longer KEPT — the cycle has been "
        "re-introduced. See the report above for the offending import chain."
    )
    # Phase 2 Task 11 (report-only): no-infra->api is intentionally BROKEN here.
    # Flipped to enforced (and this assertion tightened back to a full 0-broken
    # check) in Task 14. Until then we assert ONLY the core contract.
```

  Record the violation verbatim (the edge we will fix) by running:
  `cd backend && .venv/bin/lint-imports --config .importlinter 2>&1 | tee /tmp/g3_lint_before.txt`
  Expect `Infra must not import API BROKEN` listing `infra.device.wifi_tunnel -> api.device (l.16, l.25)` and `Core must not import API KEPT`.

- [ ] Step 4: Run the linter test + full collection to prove the suite stays green:
  `cd backend && .venv/bin/python -m pytest tests/test_import_linter.py -v && .venv/bin/python -m pytest --collect-only -q 2>/dev/null | tail -1`

- [ ] Step 5: Commit:
```bash
cd backend && git add .importlinter tests/test_import_linter.py
git commit -m "build(importlinter): add report-only no-infra->api contract

infra/device/wifi_tunnel.py still holds two lazy api.device imports
(l.16 _tunnels, l.25 _attempt_tunnel_restart). Recorded violation:
infra.device.wifi_tunnel -> api.device. Contract is report-only until
the relocation in the next two tasks; existing test scoped to the
no-core->api contract so the suite stays green."
```

---

### Task 12: Create `infra/device/tunnel_state.py` owning `_tunnels` / `_tunnels_lock` / `_tunnel_watchdogs`; repoint api/device.py (Group 3)

**Files:**
- Create `backend/infra/device/tunnel_state.py`.
- Modify `backend/api/device.py` lines 112-114 (declarations → alias import). The ~30 reference sites KEEP using the bare names (they resolve to the module-level aliases, which ARE the same objects).
- Modify `backend/infra/device/wifi_tunnel.py` `get_runner` (reads `_tunnels` from the new home).
- Create `backend/tests/test_tunnel_state.py`.

**Interfaces:** Produces module `infra.device.tunnel_state` exporting `_tunnels: dict`, `_tunnels_lock: asyncio.Lock`, `_tunnel_watchdogs: dict`. `api/device.py` re-binds these as module aliases so `api.device._tunnels IS infra.device.tunnel_state._tunnels` (same object) — preserves every test that does `device_mod._tunnels.clear()`.

**Behavior-neutrality guard tests (must stay green):** `tests/test_tunnel_registry.py`, `tests/test_device_forget_endpoint.py`, `tests/test_bootstrap_container.py` (`container.tunnel_registry is app_state.device_manager._tunnels` — that `_tunnels` is the `WifiTunnelRegistry` facade, NOT this dict; unaffected), `tests/test_wifi_tunnel_facade.py`, `tests/test_wifi_tunnel_discover.py`.

- [ ] Step 1: Create the failing test `backend/tests/test_tunnel_state.py`:

```python
"""tunnel_state owns the single _tunnels/_tunnels_lock/_tunnel_watchdogs.

api.device must re-bind those exact objects (not copies)."""
import asyncio

import infra.device.tunnel_state as ts


def test_tunnel_state_exports_the_three_objects():
    assert isinstance(ts._tunnels, dict)
    assert isinstance(ts._tunnel_watchdogs, dict)
    assert isinstance(ts._tunnels_lock, asyncio.Lock)


def test_api_device_aliases_are_the_same_objects():
    import api.device as device_mod
    assert device_mod._tunnels is ts._tunnels
    assert device_mod._tunnel_watchdogs is ts._tunnel_watchdogs
    assert device_mod._tunnels_lock is ts._tunnels_lock


def test_mutation_through_api_alias_is_visible_in_tunnel_state():
    import api.device as device_mod
    sentinel = object()
    device_mod._tunnels["G3_PROBE"] = sentinel
    try:
        assert ts._tunnels.get("G3_PROBE") is sentinel
    finally:
        device_mod._tunnels.pop("G3_PROBE", None)


def test_wifi_tunnel_registry_reads_the_shared_dict():
    import infra.device.tunnel_state as ts_mod
    from infra.device.wifi_tunnel import WifiTunnelRegistry

    class FakeRunner:
        target_ip = "10.0.0.9"
        target_port = 4444

        def is_running(self):
            return True

    runner = FakeRunner()
    ts_mod._tunnels["G3_REG"] = runner
    try:
        reg = WifiTunnelRegistry()
        assert reg.get_runner("G3_REG") is runner
        assert reg.is_running("G3_REG") is True
    finally:
        ts_mod._tunnels.pop("G3_REG", None)
```

- [ ] Step 2: Run, expect FAIL (`ModuleNotFoundError: No module named 'infra.device.tunnel_state'`):
  `cd backend && .venv/bin/python -m pytest tests/test_tunnel_state.py -v`

- [ ] Step 3: Create `backend/infra/device/tunnel_state.py`:

```python
"""Single home for the WiFi-tunnel registry state.

Previously these three module-level objects lived in api/device.py, forcing
infra/device/wifi_tunnel.py to lazily `from api.device import _tunnels` — the
last infra->api import edge. Hosting them in infra lets both api/device.py and
the WifiTunnelRegistry read them WITHOUT either importing the other.

api/device.py re-binds these as module aliases, so api.device._tunnels IS this
dict (same object) and the ~30 existing call sites — plus every test that does
device_mod._tunnels.clear() — keep working unchanged.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.wifi_tunnel import TunnelRunner

_tunnels: dict[str, "TunnelRunner"] = {}
_tunnel_watchdogs: dict[str, asyncio.Task] = {}
_tunnels_lock = asyncio.Lock()
```

  Replace `api/device.py` lines 112-114 with the alias import:

```python
# The registry state now lives in infra/device/tunnel_state.py so the
# WifiTunnelRegistry can read it without importing api (killing the last
# infra->api edge). These module aliases keep api.device._tunnels et al.
# pointing at the SAME objects, so every mutation/read site below — and
# every test that does device_mod._tunnels.clear() — works unchanged.
from infra.device.tunnel_state import (  # noqa: E402
    _tunnels,
    _tunnel_watchdogs,
    _tunnels_lock,
)
```

  Update `backend/infra/device/wifi_tunnel.py` `get_runner` to read the infra sibling:

```python
    def get_runner(self, udid: str):
        from infra.device.tunnel_state import _tunnels
        return _tunnels.get(udid)
```

  (Leave `attempt_restart`'s `from api.device import _attempt_tunnel_restart` UNTOUCHED — removed in Task 13. The `no-infra->api` contract stays BROKEN after this task for that one remaining import. NONE of the ~30 bare-name references change.)

- [ ] Step 4: Run, expect PASS — new test, named guard tests, full collection:
  `cd backend && .venv/bin/python -m pytest tests/test_tunnel_state.py tests/test_tunnel_registry.py tests/test_device_forget_endpoint.py tests/test_bootstrap_container.py tests/test_wifi_tunnel_facade.py tests/test_wifi_tunnel_discover.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add infra/device/tunnel_state.py api/device.py infra/device/wifi_tunnel.py tests/test_tunnel_state.py
git commit -m "refactor(infra): move tunnel registry state into infra/device/tunnel_state

_tunnels/_tunnels_lock/_tunnel_watchdogs now live in infra; api/device
re-binds them as aliases so all ~30 call sites and every device_mod._tunnels
test work unchanged. WifiTunnelRegistry.get_runner reads the infra sibling.
One lazy api import (_attempt_tunnel_restart) still remains; removed next."
```

---

### Task 13: Relocate `attempt_tunnel_restart` into infra with collaborators injected; remove both lazy api imports (Group 3)

**Files:**
- Create `backend/infra/device/tunnel_restart.py` (hosts the relocated `attempt_tunnel_restart`).
- Modify `backend/api/device.py`: replace the body of `_attempt_tunnel_restart` (lines 729-865) with a thin wrapper that injects the api/main collaborators and delegates to the infra function.
- Modify `backend/infra/device/wifi_tunnel.py`: `attempt_restart` calls the infra function with injected collaborators from a ctor resolver; remove the lazy `from api.device import _attempt_tunnel_restart`.
- Modify `backend/tests/test_tunnel_registry.py`: monkeypatch target moves from `api.device._attempt_tunnel_restart` to `infra.device.tunnel_restart.attempt_tunnel_restart`; `WifiTunnelRegistry` takes a `restart_collaborators` resolver.
- Modify `backend/main.py`: wire the `restart_collaborators` resolver into `WifiTunnelRegistry(...)`.
- Create `backend/tests/test_tunnel_restart.py` (CHARACTERIZATION, danger-zone — written FIRST).

**Interfaces:** Consumes `infra.device.tunnel_state.*` (Task 12); `container.engine_registry` + `container.event_publisher` (passed as plain callables/objects at this boundary, so no hard dependency on Groups 2/4 landing first). Produces `infra.device.tunnel_restart.attempt_tunnel_restart(udid, ip, port, snapshot, original_runner, *, engine_registry, device_manager, broadcast, auto_sync, watchdog_factory) -> bool`.

**DESIGN DECISION:** `_per_tunnel_watchdog` STAYS in `api/device.py` (it is the watchdog loop that drives restart). The infra function takes `watchdog_factory` as a **parameter** (a closure supplied by the api wrapper) — the standard "inject the outer collaborator" inversion, identical to how `WsEventPublisher` takes `broadcast` as a ctor arg.

> **Group 4 coordination:** this task injects a raw `broadcast` callable into `attempt_tunnel_restart` to preserve byte-exact WS payloads. If Group 4 (which routes broadcasts through `container.event_publisher`) lands FIRST, the api wrapper's `from api.websocket import broadcast` should instead pull `container.event_publisher.publish` (or the resolver should source `event_publisher.publish`). Since Group 3 executes before Group 4 in this plan's ordering, the raw `broadcast` form below is correct as written; Group 4 (Task 19) then re-points the `_attempt_tunnel_restart` wrapper's broadcasts.

- [ ] Step 1: Write the failing characterization test FIRST. Create `backend/tests/test_tunnel_restart.py` pinning the SUCCESS-path ordered effects (new runner start → registry swap under lock → device_manager connect → engine rebuild → watchdog re-arm → broadcasts `tunnel_recovered` then `device_connected` → snapshot resume) and the start-failure-returns-False path. Use fakes for every injected collaborator and `monkeypatch.setattr("infra.device.tunnel_restart.TunnelRunner", lambda: new_runner)`. (Full test body is the G3 draft's `test_tunnel_restart.py` — reproduce it verbatim; it asserts `new_runner.start_args == (udid, ip, port, 10.0)`, `ts._tunnels[udid] is new_runner`, `dm.connect_calls == [(rsd_address, rsd_port)]`, `[b[0] for b in broadcasts] == ["tunnel_recovered", "device_connected"]`, and `reg.simulation_engines[udid].resumed_with == snapshot`.)

- [ ] Step 2: Run, expect FAIL (`ModuleNotFoundError: No module named 'infra.device.tunnel_restart'`):
  `cd backend && .venv/bin/python -m pytest tests/test_tunnel_restart.py -v`

- [ ] Step 3: Create `backend/infra/device/tunnel_restart.py` by lifting the body of `api/device.py:729-865`, replacing `from main import app_state` with the injected `engine_registry`, `_dm()` with `device_manager`, `from api.websocket import broadcast` with the injected `broadcast`, `from main import _auto_sync_new_device_to_primary` with `auto_sync`, and `_per_tunnel_watchdog(...)` with `watchdog_factory(...)`. The function signature and docstring:

```python
async def attempt_tunnel_restart(
    udid: str, ip: str, port: int, snapshot: dict | None, original_runner,
    *, engine_registry, device_manager, broadcast, auto_sync, watchdog_factory,
) -> bool:
```

  Replace `_attempt_tunnel_restart` in `api/device.py` (lines 729-865) with a thin wrapper:

```python
async def _attempt_tunnel_restart(
    udid: str, ip: str, port: int, snapshot: dict | None, original_runner: TunnelRunner,
) -> bool:
    """Thin api-layer wrapper: resolves the live collaborators and delegates to
    the relocated infra implementation. Behavior is identical to the
    pre-relocation function; see infra/device/tunnel_restart."""
    from main import app_state, _auto_sync_new_device_to_primary
    from api.websocket import broadcast
    from infra.device.tunnel_restart import attempt_tunnel_restart

    def _watchdog_factory(u: str, runner: TunnelRunner):
        return asyncio.create_task(_per_tunnel_watchdog(u, runner))

    return await attempt_tunnel_restart(
        udid, ip, port, snapshot, original_runner,
        engine_registry=app_state, device_manager=_dm(), broadcast=broadcast,
        auto_sync=_auto_sync_new_device_to_primary, watchdog_factory=_watchdog_factory,
    )
```

  Rewrite `WifiTunnelRegistry` in `backend/infra/device/wifi_tunnel.py` to take a ctor-injected `restart_collaborators` resolver and delegate `attempt_restart` to the infra function (no `api.*` import). Wire the resolver in `main.py` (the composition root — the ONLY ring allowed to import api + infra + main) via a closure that lazily reads `main.app_state`, `api.websocket.broadcast`, `main._auto_sync_new_device_to_primary`, and an `api.device._per_tunnel_watchdog`-based `watchdog_factory`. First confirm the construction site:
  `cd backend && grep -rn 'WifiTunnelRegistry(' main.py core/device_manager.py`

  Then verify the infra files import zero api modules:
  `cd backend && grep -n 'from api\.' infra/device/wifi_tunnel.py infra/device/tunnel_restart.py` → expect no output.

  Fix `tests/test_tunnel_registry.py`: clear infra state in the fixture (`import infra.device.tunnel_state as ts; ts._tunnels.clear()`); switch reads to `infra.device.tunnel_state`; in `test_attempt_restart_delegates`, `monkeypatch.setattr("infra.device.tunnel_restart.attempt_tunnel_restart", fake_restart)` and construct `WifiTunnelRegistry(restart_collaborators=collaborators)`.

- [ ] Step 4: Run, expect PASS — characterization test, updated registry test, danger-zone neighbors, grep guard, full suite:
  `cd backend && .venv/bin/python -m pytest tests/test_tunnel_restart.py tests/test_tunnel_registry.py tests/test_tunnel_state.py tests/test_wifi_tunnel_facade.py tests/test_device_forget_endpoint.py -v`
  `cd backend && grep -n 'from api\.' infra/device/wifi_tunnel.py infra/device/tunnel_restart.py`  (expect NOTHING)
  `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add infra/device/tunnel_restart.py infra/device/wifi_tunnel.py api/device.py main.py tests/test_tunnel_restart.py tests/test_tunnel_registry.py
git commit -m "refactor(infra): relocate attempt_tunnel_restart out of api; remove last api import

attempt_tunnel_restart now lives in infra/device/tunnel_restart with all five
api/main collaborators injected. _per_tunnel_watchdog stays in api and passes
itself as the watchdog factory through a thin wrapper. WifiTunnelRegistry takes
a restart_collaborators resolver wired in main.py. Both lazy api.device imports
removed — infra/device/wifi_tunnel.py imports zero api modules. Characterization
test pins the success-path ordered effects."
```

---

### Task 14: Flip `no-infra-imports-api` to ENFORCED; tighten the import-linter test (Group 3)

**Files:**
- Modify `backend/.importlinter` (update the contract comment to enforced; no structural change — it already passes).
- Modify `backend/tests/test_import_linter.py` (re-tighten the returncode assertion now that 0 contracts are broken; assert `no-infra-imports-api` is KEPT).

**Interfaces:** Consumes the completed relocation (Tasks 12/13). Produces the enforced `no-infra-imports-api` contract + a regression test asserting BOTH `no-core-imports-api` and `no-infra-imports-api` are KEPT and `lint-imports` exits 0.

- [ ] Step 1: Update the test FIRST. In `backend/tests/test_import_linter.py`, replace the report-only assertion block (from Task 11) with:

```python
    # ENFORCED: both contracts must be KEPT.
    assert "Core must not import API" in report, (
        f"Expected 'Core must not import API' in lint-imports output. Got:\n{report}")
    assert "Infra must not import API" in report, (
        f"Expected 'Infra must not import API' in lint-imports output. Got:\n{report}")
    # ENFORCED: exit 0 means all contracts kept, 0 broken.
    assert result.returncode == 0, (
        "lint-imports reported broken contracts — either the no-core->api cycle "
        "or the no-infra->api edge has been re-introduced.")
```

  Also update the module docstring to state both contracts are now enforced.

- [ ] Step 2: Run. Because the relocation already removed the infra→api edge, this should PASS immediately:
  `cd backend && .venv/bin/python -m pytest tests/test_import_linter.py -v`
  (If it FAILS with "Infra must not import API BROKEN", an infra→api import survived Task 13 — STOP and `grep -rn 'from api\.' infra/` to find it.)

- [ ] Step 3: Update the `no-infra-imports-api` contract comment in `backend/.importlinter` from report-only to enforced (no structural change to the contract body).

- [ ] Step 4: Run the full linter + test + regression sweep:
  `cd backend && .venv/bin/lint-imports --config .importlinter 2>&1 | tail -4 && .venv/bin/python -m pytest tests/test_import_linter.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`
  Expect `Contracts: 2 kept, 0 broken` with both `Core must not import API KEPT` and `Infra must not import API KEPT`.

- [ ] Step 5: Commit:
```bash
cd backend && git add .importlinter tests/test_import_linter.py
git commit -m "build(importlinter): enforce no-infra->api contract

infra/device/wifi_tunnel.py imports zero api modules after the tunnel_state
+ tunnel_restart relocation. Contract flipped from report-only to enforced;
test now asserts BOTH no-core->api and no-infra->api are KEPT with exit 0.
2 kept, 0 broken."
```

---

## Group 4: Replace api→api broadcast lazy-imports with the injected EventPublisher

Depends on Group 2 (`container.event_publisher` already wired at `main.py` as `event_publisher=app_state.device_manager._events`). Adds `get_event_publisher`, migrates every `from api.websocket import broadcast; await broadcast(type, data)` site to `await <publisher>.publish((type, data))`, and adds the enforced `no-api-imports-api` contract.

**Design decision (chosen path):** `infra/events/ws_event_publisher.py` `WsEventPublisher.publish()` already accepts a raw `tuple[str, dict]` (the tuple branch does `event_type, data = event; await self._broadcast(event_type, dict(data))`). The injected broadcast callable IS `api.websocket.broadcast` (wired in `AppState.__init__`). So **no new method is needed** — `publish((type, data))` calls the exact same `api.websocket.broadcast(type, data)` with identical dict contents, deep-equal JSON. The injected publisher is the ALREADY-present `device_manager._events` (== `container.event_publisher`, same object by reference). The 9 `api/device.py` sites and 1 `api/location.py` site reach it via `dm._events` (`dm` already in local scope); the 4 `api/cloud_sync.py` sites use a `Depends(get_event_publisher)` provider. **`main.py`'s 6 lazy broadcasts are root→api (legal — `main.py` is not under the `api` package) and are LEFT AS-IS.**

---

### Task 15: Add `get_event_publisher` provider (Group 4)

**Files:**
- Modify `backend/api/deps.py` (append after the Group 2 providers).
- Create `backend/tests/test_event_publisher_provider.py`.

**Interfaces:** Produces `get_event_publisher(request) -> request.app.state.container.event_publisher`. Consumes `container.event_publisher` (Group 2).

- [ ] Step 1: Write the failing test `backend/tests/test_event_publisher_provider.py`:

```python
"""get_event_publisher resolves to the ONE injected publisher singleton."""
from main import app, app_state


def test_get_event_publisher_returns_container_singleton():
    from api.deps import get_event_publisher

    class _Req:
        class app:
            class state:
                container = app.state.container

    pub = get_event_publisher(_Req)
    assert pub is app.state.container.event_publisher
    assert pub is app_state.device_manager._events
```

- [ ] Step 2: Run, expect FAIL (`ImportError: cannot import name 'get_event_publisher'`):
  `cd backend && .venv/bin/python -m pytest tests/test_event_publisher_provider.py -v`

- [ ] Step 3: Append to `backend/api/deps.py`:

```python
def get_event_publisher(request: Request):
    return request.app.state.container.event_publisher
```

- [ ] Step 4: Run, expect PASS:
  `cd backend && .venv/bin/python -m pytest tests/test_event_publisher_provider.py -v`

- [ ] Step 5: Commit:
```bash
cd backend && git add api/deps.py tests/test_event_publisher_provider.py
git commit -m "feat(deps): add get_event_publisher provider resolving container.event_publisher"
```

---

### Task 16: Migrate `api/cloud_sync.py` top-level broadcast import to the injected publisher (Group 4)

**Files:**
- Modify `backend/api/cloud_sync.py` (remove top-level `from api.websocket import broadcast as _ws_broadcast` at line 14; inject `publisher = Depends(get_event_publisher)` into the two handlers that call `_ws_broadcast`).
- Create `backend/tests/test_cloud_sync_broadcast_publisher.py`.

**Interfaces:** Consumes `get_event_publisher` (Task 15). Produces zero `api.websocket` references in `api/cloud_sync.py`.

- [ ] Step 1: Read the enable/disable handler signatures verbatim first, then write the failing test asserting (a) no top-level websocket import and (b) the migrated payloads are deep-equal to today's. Create `backend/tests/test_cloud_sync_broadcast_publisher.py`:

```python
"""cloud_sync enable/disable emit the SAME (type, payload) tuples as before,
now via the injected EventPublisher instead of a top-level api.websocket import."""
import api.cloud_sync as cloud_sync_mod


def test_cloud_sync_has_no_toplevel_websocket_import():
    src = open(cloud_sync_mod.__file__, encoding="utf-8").read()
    assert "from api.websocket import" not in src
    assert "_ws_broadcast" not in src


def test_enable_disable_emit_unchanged_events(monkeypatch, tmp_path):
    from main import app
    from fastapi.testclient import TestClient

    captured = []

    class _CapPublisher:
        async def publish(self, event):
            etype, data = event
            captured.append((etype, {**data}))

    monkeypatch.setattr(app.state.container, "event_publisher", _CapPublisher())
    monkeypatch.setattr(cloud_sync_mod, "detect_icloud_path", lambda: tmp_path)
    monkeypatch.setattr(cloud_sync_mod, "setup_sync_folder", lambda *a, **k: tmp_path / "LocWarp")
    monkeypatch.setattr(cloud_sync_mod, "migrate_pair", lambda *a, **k: (0, 0))

    client = TestClient(app)
    resp = client.post("/api/cloud-sync/enable", json={})
    assert resp.status_code in (200, 409, 422, 500), resp.text
    if any(e == "bookmarks_changed" for e, _ in captured):
        assert ("bookmarks_changed", {"reason": "cloud_sync_enabled"}) in captured
        assert ("routes_changed", {"reason": "cloud_sync_enabled"}) in captured
```

- [ ] Step 2: Run the no-import assertion, expect FAIL (line 14 still present):
  `cd backend && .venv/bin/python -m pytest tests/test_cloud_sync_broadcast_publisher.py::test_cloud_sync_has_no_toplevel_websocket_import -v`

- [ ] Step 3: Delete line 14 `from api.websocket import broadcast as _ws_broadcast`; add `Depends` to the fastapi import and `from api.deps import get_event_publisher`. Add `publisher=Depends(get_event_publisher)` to the enable and disable handler signatures (keyword-only at the end), and replace each `await _ws_broadcast("<type>", {...})` with `await publisher.publish(("<type>", {...}))`.

- [ ] Step 4: Run, expect PASS:
  `cd backend && .venv/bin/python -m pytest tests/test_cloud_sync_broadcast_publisher.py -v && .venv/bin/python -m pytest tests/ -k cloud_sync -v`

- [ ] Step 5: Commit:
```bash
cd backend && git add api/cloud_sync.py tests/test_cloud_sync_broadcast_publisher.py
git commit -m "refactor(cloud_sync): emit changed events via injected EventPublisher, drop api.websocket import"
```

---

### Task 17: Migrate the 9 `api/device.py` lazy broadcast call-sites to `dm._events.publish` (Group 4)

**Files:**
- Modify `backend/api/device.py` at the 9 broadcast blocks (lines 57-58, 671-672, 831-842 [two broadcasts share one import], 899-900, 995-996, 1288-1293, 1491-1499, 1526-1527, 1593-1597).
- Create `backend/tests/test_device_broadcast_publisher.py`.

**Interfaces:** Consumes `container.event_publisher` (== `dm._events`). Produces zero `from api.websocket import` lines in `api/device.py`.

Each block has the shape `try: from api.websocket import broadcast; await broadcast("<type>", {...}) except Exception: ...`. The `dm` variable is in local scope at every block. Replace with `await dm._events.publish(("<type>", {...}))`, keeping the `try/except` intact. For `_per_tunnel_watchdog` (takes `(udid, runner)`, no `dm`), insert `dm = _dm()` at the top before the migrated broadcasts at 899 and 995. For the DELETE `/{udid}/connect` site (1526), use `device_service._dm._events`.

- [ ] Step 1: Write the failing characterization test `backend/tests/test_device_broadcast_publisher.py` — a no-import guard plus a route-driven check that `DELETE /{udid}/connect` emits `("device_disconnected", {"udid": udid, "udids": [udid], "reason": "user"})` through the injected publisher (swap `dm._events` for a `_CapPublisher`, patch `device_service.disconnect` to keep hardware out). Reproduce the G4 draft's test body.

- [ ] Step 2: Run, expect FAIL (source still contains `from api.websocket import broadcast`; `captured` empty because the route still calls `api.websocket.broadcast`):
  `cd backend && .venv/bin/python -m pytest tests/test_device_broadcast_publisher.py -v`

- [ ] Step 3: Edit each of the 9 blocks per the before/after in the G4 draft, deleting every now-unused `from api.websocket import broadcast` line. After all edits, `grep -c 'from api.websocket import broadcast' api/device.py` MUST return 0. Verify `dm` is bound before each block (e.g. confirm `_attempt_tunnel_restart`'s wrapper body binds `dm = _dm()` before the 831 block; the `_per_tunnel_watchdog` insert covers 899/995).

  > Note: Task 13 already relocated the BODY of `_attempt_tunnel_restart` into infra, where the broadcasts use the injected `broadcast` callable. The 831-842 site in `api/device.py` after Task 13 lives only if the wrapper retained an inline broadcast — verify against the post-Task-13 file. If the relocation moved those two broadcasts out of `api/device.py`, the Task 17 count drops by 2 and the wrapper's injected `broadcast` should be re-pointed to `container.event_publisher.publish` per the Group 3→4 coordination note. Re-grep the actual remaining `from api.websocket import broadcast` occurrences in `api/device.py` before editing and migrate exactly those.

- [ ] Step 4: Run, expect PASS — the new test + the load-bearing endpoint/forget tests:
  `cd backend && .venv/bin/python -m pytest tests/test_device_broadcast_publisher.py tests/test_device_connect_disconnect_endpoint.py tests/test_device_forget_endpoint.py -v`
  `cd backend && grep -c 'from api.websocket import broadcast' api/device.py` → expect `0`.

- [ ] Step 5: Commit:
```bash
cd backend && git add api/device.py tests/test_device_broadcast_publisher.py
git commit -m "refactor(device): route all WS broadcasts through injected EventPublisher, drop api.websocket lazy imports"
```

---

### Task 18: Migrate the `api/location.py` broadcast site to `dm._events.publish` (Group 4)

**Files:**
- Modify `backend/api/location.py` `_handle_device_lost` (the `from api.websocket import broadcast` import + the broadcast block).
- Create `backend/tests/test_location_device_lost_publisher.py`.

**Interfaces:** Consumes `container.event_publisher` (== `dm._events`). Produces zero `from api.websocket import` in `api/location.py`. `_handle_device_lost` already has `dm = app_state.device_manager` in scope — no extra wiring.

- [ ] Step 1: Write the failing characterization test `backend/tests/test_location_device_lost_publisher.py` — a no-import guard plus an async test that `_handle_device_lost(exc, udid)` emits `("device_disconnected", {"udids": [udid], "reason": "device_lost", "error": "device gone", "remaining_count": 0})` through a swapped `_CapPublisher`. Match the module's asyncio convention (check `asyncio_mode` — strict, so declare `pytestmark = pytest.mark.asyncio` or `@pytest.mark.asyncio`).

- [ ] Step 2: Run, expect FAIL (`from api.websocket import broadcast` still present):
  `cd backend && .venv/bin/python -m pytest tests/test_location_device_lost_publisher.py::test_location_module_has_no_websocket_import -v`

- [ ] Step 3: Delete the `from api.websocket import broadcast` line in `_handle_device_lost`; replace the broadcast block:

```python
    try:
        await dm._events.publish(("device_disconnected", {
            "udids": lost_udids,
            "reason": "device_lost",
            "error": str(exc),
            "remaining_count": len(dm._connections),
        }))
    except Exception:
        _log.exception("Failed to broadcast device_disconnected")
```

- [ ] Step 4: Run, expect PASS:
  `cd backend && .venv/bin/python -m pytest tests/test_location_device_lost_publisher.py -v`
  `cd backend && grep -c 'from api.websocket import broadcast' api/location.py` → expect `0`.
  `cd backend && .venv/bin/python -m pytest tests/ -k location -v`

- [ ] Step 5: Commit:
```bash
cd backend && git add api/location.py tests/test_location_device_lost_publisher.py
git commit -m "refactor(location): emit device_disconnected via injected EventPublisher in _handle_device_lost"
```

---

### Task 19: Add the ENFORCED `no-api-imports-api` import-linter contract (Group 4)

**Files:**
- Modify `backend/.importlinter` (add the contract; ensure `domain`/`infra` in `root_packages`).
- Modify `backend/tests/test_import_linter.py` (extend to require the new contract name + exit 0).

**Interfaces:** Consumes the zero-api→api state produced by Tasks 16-18. Produces enforced `no-api-imports-api` (the `api.deps` DI shim is the sole sanctioned exception).

First confirm there are NO remaining api→api edges other than the sanctioned `api.deps` imports:
`cd backend && grep -rn 'from api\.\|import api\.' api/*.py | grep -v 'from api.deps import'` → expect EMPTY. If anything else appears, migrate it before this contract can flip.

- [ ] Step 1: Add a `test_no_api_imports_api_contract_enforced` function to `backend/tests/test_import_linter.py` asserting `"API modules must not import each other" in report` and `result.returncode == 0`.

- [ ] Step 2: Run, expect FAIL (contract does not exist yet):
  `cd backend && .venv/bin/python -m pytest tests/test_import_linter.py::test_no_api_imports_api_contract_enforced -v`

- [ ] Step 3: Append to `backend/.importlinter` (the `forbidden` form with an `ignore_imports` whitelist for the DI shim):

```ini
[importlinter:contract:no-api-imports-api]
name = API modules must not import each other
type = forbidden
source_modules =
    api
forbidden_modules =
    api
ignore_imports =
    api.* -> api.deps
```

  > If the pinned import-linter version rejects the `api.*` wildcard form, fall back to enumerating each router explicitly (`api.device -> api.deps`, `api.cloud_sync -> api.deps`, plus any other router that imports `api.deps`). Determine the supported form with `.venv/bin/lint-imports --version`; the enumerated form is universally supported — prefer it if unsure. Group 7's final `.importlinter` uses the `independence` form for all 10 api submodules — reconcile to ONE definition there (this task may use the `forbidden`+ignore form as the interim; Group 7 normalizes).

- [ ] Step 4: Run, expect PASS:
  `cd backend && .venv/bin/python -m pytest tests/test_import_linter.py -v && .venv/bin/lint-imports --config .importlinter 2>&1 | tail -6`
  Expect exit 0, all contracts KEPT.

- [ ] Step 5: Commit:
```bash
cd backend && git add .importlinter tests/test_import_linter.py
git commit -m "feat(arch): enforce no-api-imports-api import-linter contract (api.deps DI shim exempt)"
```

---

### Task 20: Full-suite regression gate for Group 4 (Group 4)

**Files:** none (verification-only).

**Interfaces:** Consumes everything Tasks 15-19 produced.

- [ ] Step 1: Run the FULL backend suite — must be green:
  `cd backend && .venv/bin/python -m pytest -q` → 0 failed, 0 errored.

- [ ] Step 2: Confirm zero api→api edges remain (other than the `api.deps` shim):
  `cd backend && grep -rn 'from api\.\|import api\.' api/*.py | grep -v 'from api.deps import'` → expect EMPTY.
  `cd backend && grep -rcn 'from api.websocket import' api/device.py api/location.py api/cloud_sync.py` → expect all `0`.

- [ ] Step 3: Confirm the import-linter contract is enforced and KEPT:
  `cd backend && .venv/bin/lint-imports --config .importlinter` → exit 0; `no-core-imports-api`, `no-services-imports-fastapi`, `no-infra-imports-api`, `no-api-imports-api` all KEPT.

- [ ] Step 4: If any check fails, do NOT commit; surface the failing chain.

- [ ] Step 5: `cd backend && git status --porcelain` → if empty, no commit needed (verification-only task).

---

## Group 5a: Retire the trivial `from main import app_state` sites via the G2 providers

Depends on Group 2 (the `api/deps.py` providers + first-class Container attributes). Each task is one file, one commit, behavior-neutral. **Behavior preservation hinges on the G2 providers reading THROUGH the live AppState** — `get_bookmark_manager` / `get_route_manager` / `get_engine_registry` / `get_cooldown_timer` / `get_coord_formatter` resolve `request.app.state.container.<attr>` where `container.engine_registry IS main.app_state` (injected by reference). Existing fixtures reassign `main.app_state.bookmark_manager` / monkeypatch singletons AFTER the container is built; this works only because the resolution is live.

**Hard constraint:** `tests/test_goldditto_api.py` patches `api.location._engine` with a single-parameter `fake_resolver(udid)`. Any new parameter on `_engine` MUST be keyword-only-optional AND the goldditto mock widened in the SAME commit.

---

### Task 21: location.py — thread `get_engine_registry` / `get_cooldown_timer` / `get_coord_formatter`, drop all 11 `from main import app_state` (Group 5a)

**Files:**
- Modify `backend/api/location.py` (helpers `_engine`, `_cooldown`, `_coord_fmt`; inline app_state sites; route signatures that reach them).
- Modify `backend/api/deps.py` (add `_engine_registry_or_main(registry)` helper if Group 2 did not ship it — `return registry if registry is not None else __import__("main").app_state`).
- Modify `backend/tests/test_goldditto_api.py` (widen both `fake_resolver(udid)` → `fake_resolver(udid, registry=None)`).
- Create `backend/tests/test_location_di_char.py`.

**Interfaces:** Consumes `get_engine_registry`, `get_cooldown_timer`, `get_coord_formatter` (Group 2). Produces nothing for later groups (leaf swap). After this task `grep -c 'from main import' backend/api/location.py == 0`.

- [ ] Step 1: Write the characterization test `backend/tests/test_location_di_char.py` pinning the externally-observable contract BEFORE the swap: `/status` resolves the engine via `_engine` and stitches cooldown_remaining; `/cooldown/status` reads the live timer; `/settings/coord-format` PUT→GET round-trip mutates the live formatter; `/settings/initial-position` persist+clear; and the single-device cooldown 429 guard returns `{"detail": {"code": "cooldown_active"}}` without reaching the engine. (Reproduce the G5a draft's 5-test body.) These are characterization — they must PASS against current (pre-swap) code.

- [ ] Step 2: Run, expect PASS against current code (characterization lock):
  `cd backend && .venv/bin/python -m pytest tests/test_location_di_char.py -v`

- [ ] Step 3: Swap the three helpers + inline sites to the injected registry:
  - `_engine(udid: str | None = None, registry=None)` — resolve `app_state = _engine_registry_or_main(registry)`; keep `udid` first-positional so `await _engine(udid)` and the goldditto mock stay valid. The recursive internal `await _engine(action_udid)` closures fall back to main (dead static-import-free path); route-level calls pass the injected `registry`.
  - `_try_with_recovery_retry(udid, op, registry=None)` and `_handle_device_lost(exc, udid=None, registry=None)` — resolve via the same helper.
  - `_cooldown(registry)` → `return registry.cooldown_timer`; `_coord_fmt(registry)` → `return registry.coord_formatter`.
  - Thread `registry=Depends(get_engine_registry)` (and `cooldown=Depends(get_cooldown_timer)` / `fmt=Depends(get_coord_formatter)` where the handler only needs the timer/formatter) into every route that called a swapped helper: `teleport`, `get_status`, `cooldown_status`/`cooldown_settings`/`cooldown_dismiss`, `get_coord_format`/`set_coord_format`, `debug_info`, `get_initial_position`/`set_initial_position`, `apply_speed`, `navigate`, `loop`, `multi_stop`, `insert_waypoint`, `random_walk`, `joystick_start`/`joystick_stop`, `pause`, `resume`, `restore`, `goldditto_cycle`, `stop_movement`, `stop_simulation`. Pass `registry` into `_engine(udid, registry)`, `_try_with_recovery_retry(..., registry)`, `_handle_device_lost(..., registry)`. Replace inline `from main import app_state as _app_state` with `registry._primary_udid` / `registry.simulation_engines`.
  - Widen the goldditto mocks: `async def fake_resolver(udid, registry=None): return fake_engine` (both occurrences).

- [ ] Step 4: Run char + goldditto + grep guard:
  `cd backend && .venv/bin/python -m pytest tests/test_location_di_char.py tests/test_goldditto_api.py -v && grep -c 'from main import' backend/api/location.py` (expect all pass; grep `0`)
  Full suite: `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add api/location.py api/deps.py tests/test_location_di_char.py tests/test_goldditto_api.py
git commit -m "refactor(api): location DI via get_engine_registry/cooldown/coord_formatter; drop from-main imports"
```

---

### Task 22: bookmarks.py — replace `_bm()` + 2 inline `from main import app_state` with `get_bookmark_manager` / `get_engine_registry` (Group 5a)

**Files:**
- Modify `backend/api/bookmarks.py` (delete `_bm`; add `bm=Depends(get_bookmark_manager)` to the 12 routes + the catalog route; replace the 2 `ui-state` inline `from main import app_state` with `registry=Depends(get_engine_registry)`).
- Create `backend/tests/test_bookmarks_di_char.py`.

**Interfaces:** Consumes `get_bookmark_manager` (503 when None) and `get_engine_registry` (Group 2). After this task `grep -c 'from main import' backend/api/bookmarks.py == 0`.

- [ ] Step 1: Write the characterization test `backend/tests/test_bookmarks_di_char.py` pinning: list returns `{categories, bookmarks}` via the injected manager; **the 503-when-`bookmark_manager`-is-None guard** (currently `_bm()` returns None → `None.list_categories()` → 500); and the ui-state round-trip through `registry`. (Reproduce the G5a draft body — fixture monkeypatches `services.bookmarks.BOOKMARKS_FILE` to tmp + sets a fresh `BookmarkManager()`.)

- [ ] Step 2: Run, expect the 503 test to FAIL (current `_bm()` None path returns 500/AttributeError), the other two PASS:
  `cd backend && .venv/bin/python -m pytest tests/test_bookmarks_di_char.py -v`

- [ ] Step 3: Delete `_bm`; add `from fastapi import APIRouter, Depends, HTTPException` and `from api.deps import get_bookmark_manager, get_engine_registry`. Every route that did `bm = _bm()` gains `bm=Depends(get_bookmark_manager)` and drops the body line (including the catalog route's `return _bm().import_catalog(text)` → `return bm.import_catalog(text)`). The two `ui-state` routes replace inline `from main import app_state` with `registry=Depends(get_engine_registry)` and use `registry._bookmark_expanded_categories` / `registry._bookmark_hidden_categories` / `registry.save_settings()`.

- [ ] Step 4: Run char (all PASS now) + existing bookmarks suite + grep guard:
  `cd backend && .venv/bin/python -m pytest tests/test_bookmarks_di_char.py tests/test_bookmarks_api.py -v && grep -c 'from main import' backend/api/bookmarks.py` (expect pass; grep `0`)
  Full suite: `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add api/bookmarks.py tests/test_bookmarks_di_char.py
git commit -m "refactor(api): bookmarks DI via get_bookmark_manager (503 guard) + get_engine_registry; drop from-main imports"
```

---

### Task 23: route.py — replace `_rm()` with `get_route_manager`, module singletons with `get_route_service` / `get_gpx_service` (Group 5a)

**Files:**
- Modify `backend/api/route.py` (drop module singletons `route_service`/`gpx_service`; drop `_rm`; add `rm=Depends(get_route_manager)` to the 14 `_rm()` routes; inject `route_service`/`gpx_service` into `/plan`, `/gpx/import`, `/gpx/export/{route_id}`).
- Create `backend/tests/test_route_di_char.py`.

**Interfaces:** Consumes `get_route_manager` (503 when None), `get_route_service`, `get_gpx_service` (Group 2). After this task `grep -c 'from main import' backend/api/route.py == 0`. No route shapes change (survey: the two module-level singletons were import-time side effects; G2 already owns `container.route_service` / `container.gpx_service`).

- [ ] Step 1: Confirm the route-store constant module before writing the test (`grep -rn 'ROUTES_FILE' backend/services/`), then write `backend/tests/test_route_di_char.py` pinning the `route_manager`-None 503 guard + a saved-routes / categories list round-trip. Point `monkeypatch.setattr` at the actual route-store module.

- [ ] Step 2: Run, expect the 503 test to FAIL (current `_rm()` None → 500), the other two PASS:
  `cd backend && .venv/bin/python -m pytest tests/test_route_di_char.py -v`

- [ ] Step 3: Drop `route_service = RouteService()` / `gpx_service = GpxService()` + `_rm`; add `Depends` + `from api.deps import get_route_manager, get_route_service, get_gpx_service` (remove now-unused `RouteService`/`GpxService` imports). Every `_rm()` route gains `rm=Depends(get_route_manager)` (replace `_rm()` with `rm`). `/plan` injects `route_service=Depends(get_route_service)`; `/gpx/import` + `/gpx/export/{route_id}` inject `gpx_service=Depends(get_gpx_service)` (+ `rm` for export). Preserve every body verbatim apart from the substitutions.

- [ ] Step 4: Run char + route suites + grep guards:
  `cd backend && .venv/bin/python -m pytest tests/test_route_di_char.py tests/test_route_store.py tests/test_route_service_cov.py tests/test_route_watcher.py tests/test_route_loop_cov.py tests/test_route_tombstones.py -v && grep -c 'from main import' backend/api/route.py && grep -cE '^route_service = |^gpx_service = ' backend/api/route.py` (expect pass; both greps `0`)
  Full suite: `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add api/route.py tests/test_route_di_char.py
git commit -m "refactor(api): route DI via get_route_manager/route_service/gpx_service; drop module singletons + from-main import"
```

---

### Task 24: phone_control.py — DI the engine helpers + redirect the geocode singleton to `container.geocoding_service` (Group 5a)

**Files:**
- Modify `backend/api/phone_control.py` (`_engine`, `_all_engines`, `_fanout` become pure functions of the registry; inline `from main import app_state` in `phone_status`; the function-local `svc = GeocodingService()` in `phone_geocode` → injected `container.geocoding_service`).
- Create `backend/tests/test_phone_di_char.py`.

**Interfaces:** Consumes `get_engine_registry`, `get_device_manager`, `get_geocoding_service` (Group 2). After this task `grep -c 'from main import' backend/api/phone_control.py == 0`. The fresh `GeocodingService()` must be replaced so `/api/geocode/*` and `/api/phone/geocode` share ONE service.

- [ ] Step 1: Write `backend/tests/test_phone_di_char.py` pinning: the auth token gate; the no-device 503 (`{"detail": {"code": "no_device"}}`) through the injected registry; and that `/api/phone/geocode` calls `container.geocoding_service.search` (patch `container.geocoding_service.search` with an `AsyncMock` and assert `assert_awaited_once`). (Reproduce the G5a draft body.)

- [ ] Step 2: Run, expect `test_geocode_uses_injected_service` to FAIL (current `svc = GeocodingService()` is a fresh instance, so patching the container's instance has no effect), `test_teleport_503_when_no_engines` PASSES:
  `cd backend && .venv/bin/python -m pytest tests/test_phone_di_char.py -v`

- [ ] Step 3: Add `Depends` + `from api.deps import get_engine_registry, get_device_manager, get_geocoding_service`. `_engine(registry)` / `_all_engines(registry)` become pure functions of the registry (drop the lazy `from main import app_state`); `_fanout(action_name, fn, registry)` threads the registry to `_all_engines`. The four fan-out routes inject `registry=Depends(get_engine_registry)` and pass it through. `phone_status` injects `registry=Depends(get_engine_registry), dm=Depends(get_device_manager)` and substitutes `app_state.` → `registry.` mechanically (keep the JSON response byte-identical). `phone_geocode` injects `svc=Depends(get_geocoding_service)` and deletes the `from services.geocoding import GeocodingService` + `svc = GeocodingService()` lines.

- [ ] Step 4: Run char + auth-gate suite + grep guards:
  `cd backend && .venv/bin/python -m pytest tests/test_phone_di_char.py tests/test_phone_auth_gate.py -v && grep -c 'from main import' backend/api/phone_control.py && grep -c 'GeocodingService()' backend/api/phone_control.py` (expect pass; both greps `0`)
  Full suite: `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add api/phone_control.py tests/test_phone_di_char.py
git commit -m "refactor(api): phone-control DI via get_engine_registry/device_manager/geocoding_service; share one geocoding instance, drop from-main import"
```

**Group 5a exit invariant:**
`cd backend && grep -rc 'from main import' api/location.py api/bookmarks.py api/route.py api/phone_control.py` → each prints `0`.

---

## Group 5b: Retire the tricky `from main import app_state` sites + service extractions + the `no-api-imports-main` gate

Executes LAST among the import sweeps. Depends on Group 2 (DI providers + container attributes + `AppState.remove_engine`) and Group 4 (`container.event_publisher`). The final contract (Task 30) flips to enforced only once **all 34** `from main import` sites — across Group 5a and Group 5b — are gone, so Task 30 MUST run after every Group 5a sweep task.

**Baseline (re-pin):** `pytest.ini` has `asyncio_mode = strict` — every async test module declares `pytestmark = pytest.mark.asyncio`.

**Sites owned by G5b** (verified by `grep -rn 'from main import' backend/api/`): `api/device.py` (10 sites: `_dm`, 43, 192 helper_client, 631, 763, 823 `_auto_sync`, 912, 1244, 1310, 1544); `api/cloud_sync.py` (4: 34, 65, 123, 158); `api/websocket.py` (2: 47, 63, inside the async receive loop, NOT a `Depends` context).

---

### Task 25: Migrate the straightforward `device.py` module-level `_dm()` + helper-client sites to container access (Group 5b)

**Files:**
- Create `backend/bootstrap/runtime.py` (process-global container handle).
- Modify `backend/main.py` (call `set_container(app.state.container)` right after the container is built).
- Modify `backend/api/device.py` (`_dm()` reads the container; add `_engines()` + `_helper()`; remove the `from main import app_state` / `from main import helper_client` sites at 43, 192, 631, 763, 912, 1244, 1310, 1544; rewrite their use sites to `_engines()` / `_helper()`).
- Create `backend/tests/test_device_dm_via_container.py`.

**Interfaces:** Consumes `container.device_manager`, `container.engine_registry`, `container.helper_client` (Group 2). Produces `bootstrap/runtime.py` (`set_container` / `get_container`) + rewritten `api/device.py` module helpers. Many sites are inside module-level async helpers (no `request` in scope) so they cannot use `Depends` — they read the container via `get_container()`.

> Note: Task 13 already removed the `763` `_attempt_tunnel_restart` `from main import app_state` (relocated to infra) and Task 17 handled its broadcasts. Re-grep `api/device.py` for the ACTUAL remaining `from main import` lines before editing and migrate exactly those. The `823` `_auto_sync` import is migrated in Task 26 (leave it in place here so this task stays green standalone).

- [ ] Step 1: Write the failing test `backend/tests/test_device_dm_via_container.py`:

```python
"""api/device.py module-level accessors resolve dm / engines / helper from the
DI container, never via `from main import ...`."""
from pathlib import Path

import bootstrap.runtime as runtime
import api.device as device


def test_dm_and_engines_and_helper_read_container(monkeypatch):
    class _FakeDM: pass
    class _FakeEngines: pass
    class _FakeHelper: pass

    class _FakeContainer:
        device_manager = _FakeDM()
        engine_registry = _FakeEngines()
        helper_client = _FakeHelper()

    fake = _FakeContainer()
    monkeypatch.setattr(runtime, "_CONTAINER", fake)
    assert device._dm() is fake.device_manager
    assert device._engines() is fake.engine_registry
    assert device._helper() is fake.helper_client


def test_device_source_has_no_main_import_at_migrated_sites():
    src = Path(device.__file__).read_text()
    assert "from main import app_state" not in src
    assert "from main import helper_client" not in src
```

- [ ] Step 2: Run, expect FAIL (`AttributeError: module 'bootstrap.runtime' has no attribute '_CONTAINER'`; and the source-assert fails because `from main import app_state` is still present):
  `cd backend && .venv/bin/python -m pytest tests/test_device_dm_via_container.py -v`

- [ ] Step 3: Create `backend/bootstrap/runtime.py`:

```python
"""Process-global container handle.

main.py calls set_container() exactly once after building the Container. The
outer-ring adapter modules (api/*) that run OUTSIDE a FastAPI request — module-
level watchdogs, tunnel restart helpers — read the container through
get_container() instead of `from main import app_state`, which keeps api/* from
importing the composition root and lets the no-api-imports-main contract hold.

Inside a request, prefer the api/deps.py providers (Depends). This module is the
seam ONLY for the non-request module-level code paths.
"""
from __future__ import annotations

_CONTAINER = None


def set_container(container) -> None:
    global _CONTAINER
    _CONTAINER = container


def get_container():
    if _CONTAINER is None:
        raise RuntimeError(
            "Container not initialized — set_container() must run during app "
            "startup before any module-level adapter touches it."
        )
    return _CONTAINER
```

  In `main.py`, right after `app.state.container = _Container(...)`:

```python
from bootstrap.runtime import set_container as _set_container
_set_container(app.state.container)
```

  At the top of `api/device.py` replace the old `def _dm():` block with:

```python
from bootstrap.runtime import get_container as _container


def _dm():
    return _container().device_manager


def _engines():
    return _container().engine_registry


def _helper():
    return _container().helper_client
```

  Remove each remaining `from main import app_state` / `from main import helper_client` and rewrite the use sites to `_engines().*` / `_helper()` (capture `eng_reg = _engines()` once per function where multiple references appear). Leave the `823` `_auto_sync` import for Task 26.

- [ ] Step 4: Run, expect PASS — the new test + the device endpoint/forget/repair tests, then full suite:
  `cd backend && .venv/bin/python -m pytest tests/test_device_dm_via_container.py tests/test_device_forget_endpoint.py tests/test_device_connect_disconnect_endpoint.py tests/test_device_repair_endpoint.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add bootstrap/runtime.py main.py api/device.py tests/test_device_dm_via_container.py
git commit -m "refactor(api): device.py module helpers read container, drop from-main"
```

---

### Task 26: Extract `_auto_sync_new_device_to_primary` into `services/group_sync_service.py` (characterization test FIRST) (Group 5b)

**Files:**
- Create `backend/tests/test_group_sync_service_char.py` (danger-zone characterization, written BEFORE the move).
- Create `backend/services/group_sync_service.py`.
- Modify `backend/main.py` (the module-level `_auto_sync_new_device_to_primary` becomes a thin delegate so the USB watchdog keeps working; `_follow_primary_positions` moves into the service).
- Modify `backend/api/device.py` line 823 (`from main import _auto_sync_new_device_to_primary` → construct `GroupSyncService` from `_engines()` + `_dm()`).

**Interfaces:** Consumes `container.engine_registry` (AppState) + `container.device_manager` (ctor-injected, even though the current body only reads `app_state` — injected for forward-compat). Produces `class GroupSyncService` with `async def auto_sync_new_device_to_primary(self, new_udid) -> None` and `async def _follow_primary_positions(self, follower_udid, primary_udid) -> None`.

**Danger-zone behavior to pin:** (a) follower teleported to the primary's `current_position`; (b) when primary is in a dynamic sim state, a position-follower is attached that mirrors primary positions; (c) noop when there is no primary / primary == new / primary has no pos / primary is idle.

- [ ] Step 1: Write the failing characterization test `backend/tests/test_group_sync_service_char.py` (reproduce the G5b draft body — fake engines/registry; asserts teleport-then-follow ordering, the dynamic-state gate via a 0.6s real-sleep poll mirror, and the noop cases). Declare `pytestmark = pytest.mark.asyncio`.

- [ ] Step 2: Run, expect FAIL (`ModuleNotFoundError: No module named 'services.group_sync_service'`):
  `cd backend && .venv/bin/python -m pytest tests/test_group_sync_service_char.py -v`

- [ ] Step 3: Create `backend/services/group_sync_service.py` moving the two functions verbatim into a class, swapping the module-global `app_state` for `self._engines` (ctor: `__init__(self, *, engine_registry, device_manager)`). Make `main.py`'s `_auto_sync_new_device_to_primary` a thin delegate:

```python
async def _auto_sync_new_device_to_primary(new_udid: str) -> None:
    """Delegate to GroupSyncService. Kept as a module-level name because the USB
    presence watchdog calls it directly."""
    from services.group_sync_service import GroupSyncService
    svc = GroupSyncService(engine_registry=app_state, device_manager=app_state.device_manager)
    await svc.auto_sync_new_device_to_primary(new_udid)
```

  (Delete `_follow_primary_positions` from main.py — the service owns it.) Replace `api/device.py:822-828` (the follower branch) to construct `GroupSyncService(engine_registry=_engines(), device_manager=_dm())` and `asyncio.create_task(svc.auto_sync_new_device_to_primary(dev_info.udid))` inside the existing try/except.

- [ ] Step 4: Run, expect PASS — characterization + watchdog/lifespan + device suites + full:
  `cd backend && .venv/bin/python -m pytest tests/test_group_sync_service_char.py tests/test_lifespan.py tests/test_device_connect_disconnect_endpoint.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add services/group_sync_service.py main.py api/device.py tests/test_group_sync_service_char.py
git commit -m "refactor(services): extract GroupSyncService; device.py uses it, drop from-main"
```

---

### Task 27: Extract `CloudSyncService` for enable/disable/dismiss/status (characterization test FIRST) (Group 5b)

**Files:**
- Create `backend/tests/test_cloud_sync_service_char.py` (danger-zone characterization of the stop→replace→restart ordering, written BEFORE extraction).
- Create `backend/services/cloud_sync_service.py`.
- Modify `backend/api/cloud_sync.py` (the 4 endpoint bodies thin out to construct the service from the injected registry).

**Interfaces:** Consumes `container.engine_registry` (AppState — reads/writes `bookmark_manager`, `route_manager`, `_sync_folder`, `_cloud_sync_dismissed`, calls `save_settings()`, `restart_bookmark_watcher()`, `restart_route_watcher()`). Produces `class CloudSyncService` with `build_status()`, `async def enable(self, req)`, `async def disable(self)`, `def dismiss_prompt(self)`.

**Danger-zone behavior to pin:** the enable/disable ordering is `stop_watcher(old bm) → stop_watcher(old rm) → rebuild BookmarkManager/RouteManager → restart_*_watcher (RuntimeError-tolerant)`, `save_settings()` AFTER `_sync_folder` is set. **The `try/except RuntimeError` around the restart calls MUST be preserved** — the existing TestClient e2e tests rely on swallowing the no-running-loop RuntimeError.

- [ ] Step 1: Write the failing characterization test `backend/tests/test_cloud_sync_service_char.py` (reproduce the G5b draft — a spy AppState double asserting `log.index("stop:bm-old") < log.index("restart:bm")`, `save:` line carries the new sync_folder, broadcasts `["bookmarks_changed", "routes_changed"]`, managers swapped). Declare `pytestmark = pytest.mark.asyncio`.

- [ ] Step 2: Run, expect FAIL (`ModuleNotFoundError: No module named 'services.cloud_sync_service'`):
  `cd backend && .venv/bin/python -m pytest tests/test_cloud_sync_service_char.py -v`

- [ ] Step 3: Create `backend/services/cloud_sync_service.py` moving the four endpoint bodies verbatim (ctor: `__init__(self, *, app_state, broadcast)`), swapping `app_state` → `self._app` and the broadcast call → `self._broadcast`. Preserve the `try/except RuntimeError` around `restart_bookmark_watcher()` / `restart_route_watcher()`. Thin out `api/cloud_sync.py`: a `_service(app_state)` helper constructs `CloudSyncService(app_state=app_state, broadcast=<publisher>)`, and the 4 routes inject `app_state=Depends(get_engine_registry)` and delegate.

  > **Group 4 / `no-services-imports-fastapi` interaction:** `CloudSyncService.enable`/`disable` raise `HTTPException` (400/500) to preserve the frozen HTTP status surface — that is a deliberate retained fastapi import in `services/`. The spec-mandated domain-error fold is the geocode path ONLY. The `no-services-imports-fastapi` contract must therefore `ignore_imports = services.cloud_sync_service -> fastapi` (and `services.device_service -> fastapi` if it retains a lazy `HTTPException`). This is owned by Group 7's final `.importlinter` (the interim Group 1 contract had no such service; verify with `grep -rn 'from fastapi' services/` and add the ignore-list in Group 7's contract block). If this task lands BEFORE Group 7's ignore-list, the `no-services-imports-fastapi` contract will report BROKEN — that is acceptable only if no test asserts exit-0 on it yet; otherwise add the ignore-list entry to `.importlinter` in THIS task to keep the suite green.
  > **Group 4 broadcast wiring:** if Group 4 already migrated `api/cloud_sync.py` to the injected `publisher`, source `_service`'s `broadcast` from `container.event_publisher.publish` (a tuple-publishing callable). If Group 4's `_ws_broadcast` is still present (Group 4 runs before Group 5b in this ordering, so it should be migrated), wire `broadcast` to the publisher-backed callable accordingly.

- [ ] Step 4: Run, expect PASS — characterization + unified + cloud-sync suites + full:
  `cd backend && .venv/bin/python -m pytest tests/test_cloud_sync_service_char.py tests/test_cloud_sync_unified_api.py tests/test_cloud_sync.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add services/cloud_sync_service.py api/cloud_sync.py tests/test_cloud_sync_service_char.py
git commit -m "refactor(services): extract CloudSyncService; cloud_sync router drops from-main"
```

---

### Task 28: Migrate the two `websocket.py` inner-loop sites (preserve joystick multi-subscriber fan-out) (Group 5b)

**Files:**
- Create `backend/tests/test_ws_joystick_fanout_char.py`.
- Modify `backend/api/websocket.py` (`from main import app_state` at lines 47 and 63, inside the `while True` receive loop of `websocket_endpoint`).

**Interfaces:** Consumes `container.engine_registry` via `ws.app.state.container.engine_registry` (no `Depends` possible inside the receive loop). Bind the registry ONCE per connection after `ws.accept()`, read engines fresh per message. Produces nothing for later tasks.

**Behavior freeze:** the joystick fan-out MUST still hit ALL engines when no `udid` is given (`for engine in list(...simulation_engines.values())`); `joystick_input` → `engine.joystick_move(inp)` (sync); `joystick_stop` → `await engine.joystick_stop()`. Routing semantics unchanged.

- [ ] Step 1: Write the failing test `backend/tests/test_ws_joystick_fanout_char.py` (reproduce the G5b draft — fake WebSocket + fake container; asserts a no-udid `joystick_input` fans out to BOTH engines, and a udid'd `joystick_stop` routes to exactly one). Declare `pytestmark = pytest.mark.asyncio`.

- [ ] Step 2: Run, expect FAIL (the handler still does `from main import app_state` and ignores `ws.app.state.container`, so `main.app_state.simulation_engines` is empty → no engine hit):
  `cd backend && .venv/bin/python -m pytest tests/test_ws_joystick_fanout_char.py -v`

- [ ] Step 3: Bind the registry once from the WebSocket's app after `ws.accept()`:

```python
    # Bind the engine registry from the DI container once per connection.
    # Engines are read fresh per message so newly-connected devices join the
    # fan-out, but the registry handle itself never changes.
    engine_registry = ws.app.state.container.engine_registry
```

  Then use `engine_registry.get_engine(udid)` / `engine_registry.simulation_engines.values()` in both joystick branches, replacing the two `from main import app_state` lines. Keep the multi-subscriber fan-out semantics exactly.

- [ ] Step 4: Run, expect PASS — new test + existing joystick suite + full:
  `cd backend && .venv/bin/python -m pytest tests/test_ws_joystick_fanout_char.py tests/test_joystick_cov.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add api/websocket.py tests/test_ws_joystick_fanout_char.py
git commit -m "refactor(api): ws joystick handler reads container engine_registry, drop from-main"
```

---

### Task 29: Add the secondary enforced contracts review (`no-services-imports-fastapi` ignore-list, confirm `no-infra-imports-api`, `no-api-imports-api`) (Group 5b)

**Files:**
- Modify `backend/.importlinter` (ensure the `no-services-imports-fastapi` contract has the `ignore_imports` whitelist for the deliberately-retained `services.cloud_sync_service -> fastapi` / `services.device_service -> fastapi` boundary imports; confirm `no-infra-imports-api` + `no-api-imports-api` are present and KEPT).
- Modify `backend/tests/test_import_linter.py` (assert all four established contracts are KEPT).

**Interfaces:** Consumes the extracted services (Tasks 26-27) that retain `HTTPException`. Produces a stable 4-contract state ahead of the final `no-api-imports-main` gate.

**Pre-flight (run before editing):**
```bash
cd backend && grep -rn 'from fastapi\|import fastapi' services/ ; \
grep -rn 'from api\.' infra/ ; \
grep -rnE 'from api\.[a-z_]+ import|import api\.[a-z_]+' api/
```
This pins the exact `ignore_imports` entries needed so the contracts go straight to KEPT.

- [ ] Step 1: Extend `test_import_linter_enforced` (in `backend/tests/test_import_linter.py`) to require all four contract names present + exit 0: `Core must not import API`, `Services must not import FastAPI`, `Infra must not import API`, `API modules must not import each other`.

- [ ] Step 2: Run, expect FAIL if any of the four is BROKEN/missing (e.g. `services.cloud_sync_service -> fastapi` breaks `no-services-imports-fastapi` without the ignore-list):
  `cd backend && .venv/bin/python -m pytest tests/test_import_linter.py -v`

- [ ] Step 3: Add the `ignore_imports` whitelist to the `no-services-imports-fastapi` contract block (only the entries the pre-flight grep confirmed), with a comment explaining the retained boundary imports preserve the frozen HTTP status surface (cloud-sync 400/500). Confirm `no-infra-imports-api` (Group 3) + `no-api-imports-api` (Group 4) are present.

- [ ] Step 4: Run, expect PASS + lint-imports clean:
  `cd backend && .venv/bin/python -m pytest tests/test_import_linter.py -v && .venv/bin/lint-imports --config .importlinter 2>&1 | tail -8`
  Full suite: `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add .importlinter tests/test_import_linter.py
git commit -m "test(arch): whitelist retained service HTTPException imports; assert four contracts KEPT"
```

---

### Task 30: Add the `no-api-imports-main` contract (the Phase-2 cycle-gate) and prove zero `from main import` in api/ (Group 5b)

**Files:**
- Modify `backend/.importlinter` (add `main` to `root_packages`; add the `no-api-imports-main` forbidden contract).
- Modify `backend/tests/test_import_linter.py` (add the contract name to the asserted set; add a grep-based regression test that `from main import` count under `api/` is 0).

**Interfaces:** Consumes the COMPLETED state of every Group 5a + Group 5b sweep (all 34 sites gone). This is the global gate — it MUST run after every other sweep task across both groups. If any `from main import` remains in `api/`, lint-imports breaks and `test_zero_from_main_import_under_api` fails — the intended cycle-gate behavior.

**Pre-flight gate:** `cd backend && grep -rn 'from main import' api/ | wc -l` → MUST be 0. If non-zero, STOP — migrate the remaining sites first; do NOT weaken the contract.

- [ ] Step 1: Add to `backend/tests/test_import_linter.py`:

```python
def test_no_api_imports_main_contract_present_and_kept():
    """The Phase-2 cycle-gate: api/* must not import the composition root."""
    result = subprocess.run(
        [str(LINT_IMPORTS), "--config", str(IMPORTLINTER_CFG)],
        capture_output=True, text=True, cwd=str(BACKEND_DIR))
    report = result.stdout + result.stderr
    assert "API must not import main" in report, (
        f"Expected the no-api-imports-main contract in output. Got:\n{report}")
    assert result.returncode == 0, (
        "no-api-imports-main is BROKEN — a `from main import ...` survives in "
        f"the api package. Report:\n{report}")


def test_zero_from_main_import_under_api():
    """Defense-in-depth grep gate: no `from main import` anywhere in api/."""
    api_dir = BACKEND_DIR / "api"
    offenders = []
    for path in api_dir.rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            if "from main import" in line:
                offenders.append(f"{path.relative_to(BACKEND_DIR)}:{i}: {line.strip()}")
    assert not offenders, "Residual `from main import` in api/:\n" + "\n".join(offenders)
```

- [ ] Step 2: Run, expect FAIL (contract not yet in `.importlinter`; `test_zero_from_main_import_under_api` also FAILS until every Group 5a file is clean — this is the gate):
  `cd backend && .venv/bin/python -m pytest tests/test_import_linter.py::test_no_api_imports_main_contract_present_and_kept -v`

- [ ] Step 3: Add `main` to `root_packages` and append:

```ini
[importlinter:contract:no-api-imports-main]
name = API must not import main
type = forbidden
source_modules =
    api
forbidden_modules =
    main
```

- [ ] Step 4: Run, expect PASS:
  `cd backend && grep -rn 'from main import' api/ | wc -l` (expect `0`)
  `cd backend && .venv/bin/python -m pytest tests/test_import_linter.py -v && .venv/bin/lint-imports --config .importlinter 2>&1 | tail -8`
  (expect all 5 contracts KEPT, 0 broken). Full suite: `cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add .importlinter tests/test_import_linter.py
git commit -m "test(arch): enforce no-api-imports-main — Phase-2 cycle gate (zero from-main in api/)"
```

---

## Group 6: Import-time side-effect cleanup + test isolation + final baseline/contract gate + docs

**Execution order: LAST.** Runs only after Groups 1–5 have merged. Cleans up the two remaining import-time side effects in `config.py`, restores per-test isolation for the test files that still poke `main.app_state`, and ships the final baseline + 5-contract gate plus the doc/status/memory updates that flip Phase 2 to done.

Re-pin before starting (from `backend/`):
```bash
.venv/bin/python -m pytest --collect-only -q | tail -1                                       # baseline
grep -rhnE '@(router|app)\.(get|post|put|delete|patch)' api/*.py main.py | wc -l            # expect 97
```

---

### Task 31: Move `DATA_DIR.mkdir` out of config.py import time into the lifespan + add a conftest DATA_DIR fixture (Group 6)

**Files:**
- Modify `backend/config.py` (delete line 6 `DATA_DIR.mkdir(exist_ok=True)`).
- Modify `backend/main.py` (lifespan — add `DATA_DIR.mkdir(parents=True, exist_ok=True)` as the FIRST statement; add `DATA_DIR` to the config import).
- Modify `backend/tests/conftest.py` (add an autouse session fixture that guarantees `DATA_DIR` exists).
- Create `backend/tests/test_config_no_import_side_effect.py`.

**Interfaces:** Produces an import-pure `config` module w.r.t. `DATA_DIR.mkdir`; the runtime mkdir guarantee moves into `lifespan`'s first statement (before `app_state.load_state()` opens any path under `DATA_DIR`).

- [ ] Step 1: Write the failing test `backend/tests/test_config_no_import_side_effect.py`:

```python
"""config.py must not create ~/.locwarp at import time."""
import importlib
import sys
from pathlib import Path


def test_importing_config_does_not_mkdir_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.modules.pop("config", None)
    cfg = importlib.import_module("config")
    try:
        expected = Path(tmp_path) / ".locwarp"
        assert cfg.DATA_DIR == expected
        assert not expected.exists(), "importing config created DATA_DIR — import-time mkdir leaked back in"
    finally:
        sys.modules.pop("config", None)
        importlib.import_module("config")
```

- [ ] Step 2: Run, expect FAIL (`AssertionError: importing config created DATA_DIR`):
  `cd backend && .venv/bin/python -m pytest tests/test_config_no_import_side_effect.py -v`

- [ ] Step 3: In `backend/config.py`, delete `DATA_DIR.mkdir(exist_ok=True)` (line 6) and add a comment that the directory is created at RUNTIME in the lifespan. In `backend/main.py`, add `DATA_DIR` to the config import (line 25) and make `DATA_DIR.mkdir(parents=True, exist_ok=True)` the first statement of `lifespan`, before the helper handshake / `load_state()`. In `backend/tests/conftest.py`, append a session-scoped autouse `_ensure_data_dir` fixture that calls `config.DATA_DIR.mkdir(parents=True, exist_ok=True)` (belt-and-suspenders for tests that build managers without the lifespan).

- [ ] Step 4: Run, expect PASS (new test, then full suite — no FileNotFoundError):
  `cd backend && .venv/bin/python -m pytest tests/test_config_no_import_side_effect.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add config.py main.py tests/conftest.py tests/test_config_no_import_side_effect.py
git commit -m "refactor(config): move DATA_DIR.mkdir from import time into lifespan

config.py is now import-pure — no filesystem side effect. The runtime mkdir
guarantee moves to the FastAPI lifespan's first statement, before
app_state.load_state() opens any path under DATA_DIR. A session-scoped autouse
conftest fixture recreates ~/.locwarp for tests that build managers without the
lifespan."
```

---

### Task 32: Move CORS_ORIGINS + CSP_MODE env reads from config.py into main.py (config becomes pure constants) (Group 6)

**Files:**
- Modify `backend/config.py` (remove `import os as _os` at line 191; remove the `LOCWARP_LAN_ORIGIN` read at 202-204 and the `LOCWARP_CSP_MODE` read at 209; keep the static base allowlist + a `DEFAULT_CSP_MODE` constant).
- Modify `backend/main.py` (apply the env reads where CORS/CSP are wired; compute `_cors_origins` + `CSP_MODE` from env just before the middleware).
- Modify `backend/tests/test_cors_allowlist.py` / `backend/tests/test_csp_header.py` only if they read the env in config (survey first).
- Create `backend/tests/test_config_no_env_read.py`.

**Interfaces:** Produces `config.CORS_ORIGINS` as a static base allowlist (no env append); `config.CSP_MODE` no longer exists (runtime mode computed in `main.py`); `config.DEFAULT_CSP_MODE` is the fallback default. Only `bootstrap/` + `main.py` read env.

- [ ] Step 0: Survey the existing CORS/CSP test expectations first:
  `cd backend && grep -n 'CORS_ORIGINS\|CSP_MODE\|LOCWARP_LAN_ORIGIN\|LOCWARP_CSP_MODE\|monkeypatch.setenv\|reload' tests/test_cors_allowlist.py tests/test_csp_header.py`
  If a test sets `LOCWARP_*` env and reloads `config`, retarget it (in Step 3) to drive `main.py` / assert the response header via TestClient, keeping the SAME expected allowlist / CSP header value.

- [ ] Step 1: Write the failing test `backend/tests/test_config_no_env_read.py`:

```python
"""config.py must not read LOCWARP_* env vars at import time."""
import importlib
import sys


def test_config_module_has_no_os_import_and_no_csp_mode():
    sys.modules.pop("config", None)
    cfg = importlib.import_module("config")
    try:
        assert not hasattr(cfg, "_os"), "config still imports os as _os for env reads"
        assert not hasattr(cfg, "CSP_MODE"), "config still owns CSP_MODE env read"
        assert cfg.CORS_ORIGINS == [
            "http://127.0.0.1:8777", "http://localhost:8777",
            "http://127.0.0.1:5173", "http://localhost:5173",
        ]
    finally:
        sys.modules.pop("config", None)
        importlib.import_module("config")


def test_importing_config_ignores_lan_origin_env(monkeypatch):
    monkeypatch.setenv("LOCWARP_LAN_ORIGIN", "http://192.168.1.50:8777")
    sys.modules.pop("config", None)
    cfg = importlib.import_module("config")
    try:
        assert "http://192.168.1.50:8777" not in cfg.CORS_ORIGINS
    finally:
        sys.modules.pop("config", None)
        importlib.import_module("config")
```

- [ ] Step 2: Run, expect FAIL (`assert not hasattr(cfg, "_os")` is False; `CSP_MODE` / LAN-origin assertions fail):
  `cd backend && .venv/bin/python -m pytest tests/test_config_no_env_read.py -v`

- [ ] Step 3: In `backend/config.py`, replace the env-reading block with pure constants: `CORS_ORIGINS: list[str]` = the 4 loopback/dev origins, and `DEFAULT_CSP_MODE: str = "dev"`; remove `import os as _os`. In `backend/main.py`, import `DEFAULT_CSP_MODE` (instead of `CSP_MODE`), and just before the CORS middleware compute:

```python
# ── Runtime env reads (env belongs in main.py, not config.py) ──
_lan_origin = os.getenv("LOCWARP_LAN_ORIGIN", "").strip()
_cors_origins = [*CORS_ORIGINS, _lan_origin] if _lan_origin else CORS_ORIGINS
CSP_MODE = os.getenv("LOCWARP_CSP_MODE", DEFAULT_CSP_MODE)
```

  Change the CORS middleware `allow_origins=CORS_ORIGINS` → `allow_origins=_cors_origins`. The `_csp_middleware` already reads the module-level `CSP_MODE` (now defined by the line above) — no middleware-body change. Retarget the two CORS/CSP tests per Step 0 if needed, keeping every expected value byte-identical.

- [ ] Step 4: Run, expect PASS (new test + the two CORS/CSP tests + full suite). CORS allowlist + CSP header byte-identical to before:
  `cd backend && .venv/bin/python -m pytest tests/test_config_no_env_read.py tests/test_cors_allowlist.py tests/test_csp_header.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add config.py main.py tests/test_config_no_env_read.py tests/test_cors_allowlist.py tests/test_csp_header.py
git commit -m "refactor(config): move CORS LAN-origin + CSP_MODE env reads to main.py

config.py becomes a pure constants module — no os import, no LOCWARP_* env
reads. The optional LAN origin and runtime CSP mode are now read in main.py
where the middleware is wired. CORS allowlist + CSP header output unchanged."
```

---

### Task 33: Restore test isolation — point `main.app_state`-poking tests at the injected `engine_registry` handle (Group 6)

**Files (modify the endpoint test files that mutate `app_state` to stage request state):**
- `backend/tests/test_engines_lock.py`
- `backend/tests/test_device_forget_endpoint.py`
- `backend/tests/test_device_connect_disconnect_endpoint.py`
- `backend/tests/test_device_repair_endpoint.py`
- Create `backend/tests/test_engine_registry_handle.py` (guard).

**Interfaces:** Consumes `container.engine_registry` (Group 2) — `app.state.container.engine_registry IS main.app_state` (same object). Produces tests that reach the registry through the injected handle instead of the `main` module global. **No behavior change** — the mutations land on the identical object.

> **Conscious exclusions (do NOT retarget):** `tests/test_engine_determinism_and_promotion_char.py` constructs FRESH `AppState()` instances on purpose (the determinism/promotion harness) — leave its `from main import AppState`. `tests/test_lifespan.py` legitimately imports the module-level `lifespan` / `app_state` / `helper_client` to drive the lifespan directly — leave it. `tests/test_goldditto_api.py` / `tests/test_wifi_tunnel_discover.py` import `from main import app` (no app_state) — leave unless they mutate registry state.

- [ ] Step 1: Create the guard `backend/tests/test_engine_registry_handle.py`:

```python
"""The injected container.engine_registry IS main.app_state."""


def test_container_engine_registry_is_app_state():
    from main import app, app_state
    assert app.state.container.engine_registry is app_state


def test_engine_registry_exposes_expected_surface():
    from main import app
    reg = app.state.container.engine_registry
    assert hasattr(reg, "simulation_engines")
    assert hasattr(reg, "_primary_udid")
    assert hasattr(reg, "_engines_lock")
    assert callable(reg.get_engine)
    assert callable(reg.create_engine_for_device)
    assert callable(reg.remove_engine)  # added in Group 2
```

- [ ] Step 2: Run. With Groups 1-5 merged (this group runs LAST), both PASS immediately — they pin the invariant we retarget against. If `remove_engine` is missing, Group 2 has not merged — STOP and surface the ordering violation:
  `cd backend && .venv/bin/python -m pytest tests/test_engine_registry_handle.py -v`

- [ ] Step 3: Retarget the 4 endpoint test files: replace `from main import app, app_state` / bare `from main import app_state` with `from main import app` + `app_state = app.state.container.engine_registry` at each `app_state`-sourcing site. Leave all `app_state.simulation_engines[...]` / `app_state._primary_udid` / `app_state.device_manager.*` mutations and asserts unchanged (the handle is the same object).

- [ ] Step 4: Run, expect PASS — the 4 retargeted files + the guard, then full suite:
  `cd backend && .venv/bin/python -m pytest tests/test_engine_registry_handle.py tests/test_engines_lock.py tests/test_device_forget_endpoint.py tests/test_device_connect_disconnect_endpoint.py tests/test_device_repair_endpoint.py -v && .venv/bin/python -m pytest -q 2>&1 | tail -3`

- [ ] Step 5: Commit:
```bash
cd backend && git add tests/test_engine_registry_handle.py tests/test_engines_lock.py tests/test_device_forget_endpoint.py tests/test_device_connect_disconnect_endpoint.py tests/test_device_repair_endpoint.py
git commit -m "test(isolation): reach engine registry via container handle not main global

Endpoint tests now source the registry from app.state.container.engine_registry
(the injected DI handle) instead of from-main. The handle IS the same singleton
the request handlers resolve, so mutations are identical — this restores
per-test isolation and removes the import-order coupling. The lifespan and
engine-determinism characterization tests keep their direct main imports by
design."
```

---

### Task 34 (OPTIONAL — trailing, executor MAY SKIP): wrap remaining module-level mutable state into Container-owned holders (Group 6)

> **Mark clearly optional.** Low payoff, no behavior change, pure tidy-up. The executor may skip this entire task and the final gate (Task 35) still passes. Do NOT block Phase-2 completion on it. If skipped, note it in the Task 35 status line as "deferred residual import-time state."

**Files (each an independent, individually-revertable sub-commit):**
- `backend/geo_offline.py` (module-level offline-geo singleton / `_load_failed` latch).
- `backend/services/file_watcher.py` (process-wide Observer singleton).
- `backend/api/phone_control.py` (`_PhoneAuth` module-level instance).
- `backend/api/location.py` (`_bg_tasks` module-level set).

**Interfaces:** Consumes the Container ctor + `api/deps.py` provider pattern (Group 2). Produces nothing other groups depend on — leaf-state relocations; public function signatures stay identical (a thin module-level shim forwards to the container during the migration window).

For EACH file, follow the danger-zone rule: if the module has no direct test, write a characterization test pinning current behavior BEFORE wrapping. Per sub-task: (1) characterization test, (2) holder class, (3) construct in `Container.__init__` + `get_*` provider, (4) module-level shim so call sites are untouched, (5) full suite green, (6) commit (`refactor(<module>): wrap module-level state into Container holder`).

- [ ] Step 1: SKIP unless explicitly opted in. If opted in, write the per-module characterization test first.
- [ ] Step 2: Run, expect FAIL (holder class does not exist yet).
- [ ] Step 3: Introduce the holder + container wiring + module-level shim.
- [ ] Step 4: Run, expect PASS + full suite green.
- [ ] Step 5: Commit (one commit per module).

---

### Task 35 (FINAL GATE): re-pin baselines + assert all 5 import-linter contracts enforced + flip Phase 2 status in docs/spec/memory (Group 6)

**Files:**
- Modify `backend/.importlinter` (de-dupe to the canonical 5-contract shape; `root_packages` = `api core services models domain infra` + `main`; add any contract an earlier group did not / normalize `no-api-imports-api` to ONE definition).
- Create `backend/tests/test_import_contracts_enforced.py` (asserts `lint-imports` exits 0 with all contracts KEPT / 0 broken).
- Modify `/Users/raviwu/personal/locwarp/CLAUDE.md` (status line — flip Phase-2 to done).
- Modify `/Users/raviwu/personal/locwarp/AGENTS.md` (status line — mirror).
- Modify `/Users/raviwu/personal/locwarp/docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md` (line 4 Status + line 137 Phase 2 header → done).
- Modify `/Users/raviwu/.claude-work/projects/-Users-raviwu-personal-locwarp/memory/project_clean_arch_refactor_status.md` (append a P2-done paragraph; update `description:` front-matter — outside the repo, edit in place, not git-tracked).

**Interfaces:** Consumes all earlier groups — the 5 contracts `no-core-imports-api`, `no-services-imports-fastapi`, `no-infra-imports-api`, `no-api-imports-api`, `no-api-imports-main`. Produces the enforced-contract regression test (the "353rd test") + the doc/spec/memory status flip.

- [ ] Step 1: Read the current `.importlinter` (`cat .importlinter`), verify which contracts earlier groups added, **de-duplicate** so each `[importlinter:contract:*]` section appears exactly once, and ensure `root_packages` lists `api core services models domain infra main`. Normalize `no-api-imports-api` to ONE definition (reconcile the Group 4 `forbidden`+ignore form vs an `independence` form — pick the form that the pinned import-linter version accepts AND that keeps the `api.deps` DI shim exempt; verify against `main.py`'s `include_router` set: device, location, route, geocode, bookmarks, recent, websocket, system, phone_control, cloud_sync).

- [ ] Step 2: Write the failing test `backend/tests/test_import_contracts_enforced.py`:

```python
"""All five import-linter contracts must be ENFORCED and pass (the architecture gate)."""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

REQUIRED_CONTRACTS = {
    "no-core-imports-api", "no-services-imports-fastapi", "no-infra-imports-api",
    "no-api-imports-api", "no-api-imports-main",
}


def test_importlinter_config_declares_all_five_contracts():
    cfg = (BACKEND / ".importlinter").read_text()
    for name in REQUIRED_CONTRACTS:
        assert f"contract:{name}]" in cfg, f"missing contract: {name}"
    for pkg in ("api", "core", "services", "models", "domain", "infra"):
        assert pkg in cfg, f"root_packages missing {pkg}"


def test_lint_imports_passes_with_zero_broken():
    proc = subprocess.run(
        [sys.executable, "-m", "importlinter.cli", "lint"],
        cwd=str(BACKEND), capture_output=True, text=True)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"lint-imports failed (exit {proc.returncode}):\n{combined}"
    tail = combined.lower().split("contracts:")[-1]
    assert "broken" not in tail or "0 broken" in tail, f"a contract is broken:\n{combined}"
```

- [ ] Step 3: Run, expect FAIL if any contract is still missing/broken (before Step 1's `.importlinter` is complete). After Step 1, re-run — if a real source violation remains, an earlier group left an edge; STOP and surface it:
  `cd backend && .venv/bin/python -m pytest tests/test_import_contracts_enforced.py -v`

- [ ] Step 4: Run the gate + re-pin all baselines:
```bash
cd backend && .venv/bin/python -m importlinter.cli lint
cd backend && .venv/bin/python -m pytest -q 2>&1 | tail -3
cd backend && grep -rhnE '@(router|app)\.(get|post|put|delete|patch)' api/*.py main.py | wc -l
cd frontend && npx tsc --noEmit && echo "tsc OK"
cd frontend && npx vitest run --reporter=dot 2>&1 | tail -3
```
  Expect `Contracts: 5 kept, 0 broken` exit 0; backend pytest green (re-pin the exact total); route count `97`; tsc clean; vitest `335 passed`. Capture the exact pytest count for the doc updates.

- [ ] Step 5a: Flip the status lines in `CLAUDE.md` (line 11), `AGENTS.md` (line 11), and the spec (`docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md` line 4 Status → "Phase 0 + Phase 1 + Phase 2 (C / spec-literal) IMPLEMENTED + merged (2026-06-20). Phases 3–5 deferred."; line 137 Phase 2 header `**deferred**` → `**DONE (2026-06-20)**`). The CLAUDE.md/AGENTS.md status sentence should state: inward-only rings, geocode `GeocodeError`s mapped at the boundary, last `infra→api` edge gone, all `from main import app_state` retired from non-test code, api→api broadcasts via injected `EventPublisher`, and **five import-linter contracts ENFORCED (`5 kept, 0 broken`)**; Phases 3–5 deferred.

- [ ] Step 5b: Update the project memory note (`~/.claude-work/.../project_clean_arch_refactor_status.md`) — change the `description:` front-matter and append a P2-done paragraph using the exact re-pinned counts (backend pytest total, 97 routes, frontend 335 vitest + 2 e2e, tsc clean) plus the deferred residual (Task 34 module-level wraps left in place if skipped).

- [ ] Step 5c: Commit the gate test + `.importlinter` first (so the suite stays green per-commit), then the docs:
```bash
cd backend && git add .importlinter tests/test_import_contracts_enforced.py
git commit -m "test(arch): enforce all five import-linter contracts as a gate

Adds no-services-imports-fastapi, no-infra-imports-api, no-api-imports-api,
and no-api-imports-main alongside no-core-imports-api; adds domain + infra to
root_packages. A regression test shells out to lint-imports and fails on any
broken/missing contract."

cd /Users/raviwu/personal/locwarp && git add CLAUDE.md AGENTS.md docs/superpowers/specs/2026-06-19-clean-architecture-refactor-design.md
git commit -m "docs(clean-arch): flip Phase 2 (C / spec-literal) to DONE

Phase 0 + Phase 1 + Phase 2 complete: service-locator removed, geocode domain
errors, last infra->api edge killed, injected EventPublisher broadcast, five
enforced import-linter contracts. Phases 3-5 stay deferred."
```
  (The memory note at `~/.claude-work/...` is outside the repo — update it in place; not git-tracked by this repo.)

---

#### Group 6 verification summary (what "done" looks like)
- `cd backend && .venv/bin/python -m importlinter.cli lint` → `Contracts: 5 kept, 0 broken`, exit 0.
- `cd backend && .venv/bin/python -m pytest -q` → green; collected count re-pinned.
- `grep -rhnE '@(router|app)\.(get|post|put|delete|patch)' api/*.py main.py | wc -l` → `97`.
- `cd frontend && npx tsc --noEmit` → clean; `npx vitest run` → `335 passed`.
- `import config` has zero filesystem / env side effect (the Task 31/32 guard tests).
- CLAUDE.md / AGENTS.md / spec / memory note all show Phase 2 = DONE.

---

## Hardware smoke (post-merge, ~25-35 min — NOT a coded task)

The 5 import-linter contracts + the full pytest freeze cannot exercise the REAL tunnel-restart recovery (Task 13's `attempt_tunnel_restart` relocation threads engine_registry / device_manager / broadcast / auto_sync / watchdog_factory as parameters; the characterization test uses fakes). After Group 6 merges, run a real-hardware smoke covering: (1) single WiFi device — force a tunnel blip, confirm the sim resumes from snapshot at the same leg; (2) dual/triple group — blip a follower, confirm it re-locks to primary via auto_sync; (3) blip the primary, confirm promotion. Also smoke USB connect + teleport and the Trust-dialog path. This is the one risk the 754-test freeze cannot catch.
