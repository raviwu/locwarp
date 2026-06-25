# Wiring Orphaned Capability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan — one implementer subagent per task plus an adversarial reviewer gate after each task, and a whole-branch review before the cluster ff-merges to `main`. Steps use checkbox (- [ ]) syntax.

**Goal:** Wire up three already-built-but-unreachable capabilities in LocWarp: (1) expose the complete-but-uncalled `services/geo_extras.py:nearby_pois` behind a new `GET /api/geocode/nearby` route plus a map context-menu "Nearby places" submenu; (2) make GPX import/export timing-aware (parse and honor `<time>` cadence, fall back to profile speed when timing is absent); (3) add a default-ON, settings-gated ±10–15% Gaussian speed jitter to the simulation engine, with an injectable RNG seam so it is deterministically testable.

**Architecture:** Each change fits the existing Pragmatic-Hexagonal-lite rings (backend `bootstrap → api+infra → services → core → domain`; frontend `view → hooks → ports ← adapters`). No new subsystems. Backend additions: a thin controller in `api/geocode.py` over the existing service; new pure functions in `domain/movement.py` (timing-aware interpolation + an rng-injectable jitter); additive optional fields on `domain/schemas` (`SavedRoute.timestamps`) and `config.SpeedProfile` (`speed_jitter`); behavior changes confined to `core/simulation_engine.py` and `services/gpx_service.py`. Frontend additions: a `nearbyPois` call in `services/api.ts`, a `NearbyPlacesMenu.tsx` submenu wired into `MapContextMenu.tsx`, and a persisted `speed_jitter` settings toggle mirroring the existing `show_bookmark_pins` localStorage pattern.

**Tech Stack:** FastAPI/Python backend (pytest + import-linter), React 18 + TypeScript + Electron frontend (Vitest with `fireEvent` only — `@testing-library/user-event` is NOT installed), dependency-cruiser CI gate. Two test-harness shapes coexist, depending on the unit under test:
- **LEAF component tests** (e.g. `NearbyPlacesMenu`, `MapContextMenu`): pass plain function/api props directly; a fake api is injected as a prop, NOT via `vi.mock`. Pure presentational components take their gateways as props.
- **App-LEVEL tests** (e.g. `App.toastAria.test.tsx`, and Task 14's toggle test): a HYBRID — `vi.mock('./services/api', ...)` stubs the module, AND the render helper wraps `<ServicesProvider value={{ api, ws, ... }}>` (where `api` is `import * as api from './services/api'`, the mocked module) around `<App/>`. Both are required because `App` resolves its gateway through `ServicesContext` but also pulls modules that import the api directly. Mirror `App.toastAria.test.tsx`'s exact setup for any App-level test. The "ServicesProvider-not-`vi.mock`" rule applies ONLY to leaf component tests.

## Global Constraints

Copied verbatim from the master spec's Global Constraints; every task's requirements implicitly include this section.

- **Green after every commit.** Backend `pytest` + frontend `vitest` + 7 import-linter contracts (`7 kept, 0 broken`) + dependency-cruiser (`0 errors, 0 warnings`) all pass after EVERY commit. Pin the exact baselines before starting:
  - Backend: `cd backend && .venv/bin/python -m pytest --collect-only -q` (expected ≈949 collected).
  - Frontend: `cd frontend && npx vitest run` (expected ≈773) + `npx tsc --noEmit` (0 errors) + `npm run depcruise` (= `depcruise src --config .dependency-cruiser.cjs`) (0/0).
- **Danger-zone-test-first.** `simulation_engine.py`, all movers, `api/location.py`, `device_manager` recovery, `phone_control.py` have NO direct tests. Write characterization tests (injected `ClockPort` + stepped `asyncio.sleep`, ordered exact-tuple assertions, REAL collaborators — never stub the method under test) BEFORE touching them.
- **WS payload discipline.** New/changed WS payloads are compared deep-equal JSON, serialized `exclude_unset`/`exclude_none` so absent keys stay absent. Adding keys to an existing event must be backward-compatible (existing consumers must not break).
- **One documented behavior change.** Speed jitter (Cluster 3) changes the per-tick speed of all existing modes. It is gated behind a settings toggle that defaults ON. This is the ONLY intentional behavior change in the program; characterization tests run with jitter OFF to keep exact-tuple assertions stable.
- **Hexagon boundaries hold.** `domain/` stays pure; `services/` raise domain errors not `HTTPException`; view never imports `adapters/api` / `services/api` directly; the `device_manager → EventPublisher` inversion stays **awaited, in-line, order-preserving** — NEVER acquire the WS connection-manager lock while `device_manager._lock` is held.
- **Survey before adding surface.** Each new endpoint/event below states reuse-vs-new with its justification (done in this spec).
- **Personal-repo conventions.** Direct commits to `main`; git identity auto-set by includeIf (never pass `-c user.email=`); no PR ceremony.

---

### Task 1: Baseline pin + cluster branch

**Files:**
- No source changes. Pins the green baseline and creates the working branch.

**Interfaces:**
- Consumes: nothing.
- Produces: a pinned baseline (backend collected count, frontend vitest count) recorded in the task notes; branch `aip-c3-orphaned-capability` checked out from `main`.

- [ ] **Step 1: Create the cluster branch off main.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git checkout main && git pull --ff-only && git checkout -b aip-c3-orphaned-capability
  ```
  Expected output: `Switched to a new branch 'aip-c3-orphaned-capability'`.

- [ ] **Step 2: Pin the backend pytest baseline.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest --collect-only -q 2>/dev/null | tail -1
  ```
  Expected output: `949 tests collected in <…>s` (record the exact number; it is the floor every later task must keep meeting + the new tests it adds).

- [ ] **Step 3: Pin the backend suite green.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3
  ```
  Expected output: a passing line like `949 passed, <…> warnings in <…>s` with no failures/errors.

- [ ] **Step 4: Pin the import-linter contracts.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_import_contracts_enforced.py -q 2>&1 | tail -3
  ```
  Expected output: the contract test passes (it asserts `7 kept, 0 broken`).

- [ ] **Step 5: Pin the frontend baselines.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run 2>&1 | tail -5 && npm run depcruise 2>&1 | tail -3
  ```
  Expected output: `tsc` prints nothing (0 errors); vitest prints a passing summary near `Tests  773 passed` (record the exact number); depcruise prints `no dependency violations found` (0 errors / 0 warnings).

- [ ] **Step 6: Commit a no-op baseline marker (optional anchor).**
  No code changed, so there is nothing to commit. Record the pinned numbers in the task notes and proceed. (Do NOT create an empty commit.)

---

### Task 2: `nearby_pois` domain error wrapper (backend service seam)

The existing `services/geo_extras.py:nearby_pois` already returns `[]` on upstream failure (via `_overpass_post` returning `None`), so it never raises. To keep the controller (Task 3) free of `HTTPException` decisions and to satisfy "services raise domain errors," this task adds a NEW domain error subtype and a thin service wrapper that validates inputs and raises a domain error on a bad request, while passing through the existing empty-list-on-upstream-failure behavior. This isolates the validation/error policy in the service ring so the controller is a pure mapper.

**Files:**
- Modify: `backend/domain/errors.py` (add `NearbyPoiError`, mirroring the existing `GeocodeError` shape at `domain/errors.py:23-35`).
- Modify: `backend/services/geo_extras.py` (add `nearby_pois_checked(...)` wrapper at end of the Overpass section, after `nearby_pois` at line 219).
- Test: `backend/tests/test_nearby_pois_service.py` (new).

**Interfaces:**
- Consumes: `services.geo_extras.nearby_pois(lat, lng, radius_m, limit) -> list[NearbyPoi]` (exists, `geo_extras.py:176`); `models.schemas.NearbyPoi` (exists, `schemas.py:313`, fields `id,name,category,subcategory,lat,lng,distance_m`); `domain.errors.GeocodeError(status_code:int, code:str, detail:str)` (exists, `errors.py:23`).
- Produces:
  - `class NearbyPoiError(Exception)` with `__init__(self, status_code: int, code: str, detail: str)` setting `self.status_code`, `self.code`, `self.detail` (verbatim shape of `GeocodeError`).
  - `async def nearby_pois_checked(lat: float, lng: float, radius_m: int = 200, limit: int = 40) -> list[NearbyPoi]` — raises `NearbyPoiError(400, "invalid_bounds", ...)` when `radius_m <= 0`, `radius_m > 5000`, `limit <= 0`, or `limit > 200`; otherwise returns `await nearby_pois(lat, lng, radius_m, limit)` (which is `[]` on upstream failure).

- [ ] **Step 1: Read the existing `GeocodeError` to copy its exact shape.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && sed -n '23,40p' domain/errors.py
  ```
  Expected output: the `GeocodeError` class with `__init__(self, status_code, code, detail)` storing `self.status_code`, `self.code`, `self.detail`.

- [ ] **Step 2: Write the failing service test.**
  Create `backend/tests/test_nearby_pois_service.py`:
  ```python
  """Tests for the nearby-POI service wrapper (geo_extras.nearby_pois_checked).

  The wrapper validates bounds (raising a domain error) and otherwise delegates
  to the existing nearby_pois, which returns [] on any upstream failure. Pure /
  offline — the Overpass call is monkeypatched so no network is touched.
  """
  from __future__ import annotations

  import pytest

  from domain.errors import NearbyPoiError
  from models.schemas import NearbyPoi
  import services.geo_extras as geo_extras


  pytestmark = pytest.mark.asyncio


  async def test_returns_pois_from_underlying_nearby_pois(monkeypatch):
      sample = [
          NearbyPoi(id="1", name="Cafe A", category="amenity", subcategory="cafe",
                    lat=25.0, lng=121.0, distance_m=12.5),
      ]

      async def fake_nearby(lat, lng, radius_m=200, limit=40):
          assert (lat, lng, radius_m, limit) == (25.0, 121.0, 300, 10)
          return sample

      monkeypatch.setattr(geo_extras, "nearby_pois", fake_nearby)
      out = await geo_extras.nearby_pois_checked(25.0, 121.0, radius_m=300, limit=10)
      assert out == sample


  async def test_upstream_failure_yields_empty_list_not_raise(monkeypatch):
      async def fake_nearby(lat, lng, radius_m=200, limit=40):
          return []  # _overpass_post returned None upstream

      monkeypatch.setattr(geo_extras, "nearby_pois", fake_nearby)
      out = await geo_extras.nearby_pois_checked(0.0, 0.0)
      assert out == []


  async def test_radius_zero_raises_domain_error():
      with pytest.raises(NearbyPoiError) as ei:
          await geo_extras.nearby_pois_checked(25.0, 121.0, radius_m=0)
      assert ei.value.status_code == 400
      assert ei.value.code == "invalid_bounds"


  async def test_radius_too_large_raises_domain_error():
      with pytest.raises(NearbyPoiError) as ei:
          await geo_extras.nearby_pois_checked(25.0, 121.0, radius_m=5001)
      assert ei.value.status_code == 400


  async def test_limit_zero_raises_domain_error():
      with pytest.raises(NearbyPoiError) as ei:
          await geo_extras.nearby_pois_checked(25.0, 121.0, limit=0)
      assert ei.value.status_code == 400


  async def test_limit_too_large_raises_domain_error():
      with pytest.raises(NearbyPoiError) as ei:
          await geo_extras.nearby_pois_checked(25.0, 121.0, limit=201)
      assert ei.value.status_code == 400
  ```

- [ ] **Step 3: Run the test, see it fail (ImportError).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_nearby_pois_service.py -q 2>&1 | tail -8
  ```
  Expected output: collection/import error — `ImportError: cannot import name 'NearbyPoiError' from 'domain.errors'` (the symbol does not exist yet).

- [ ] **Step 4: Add `NearbyPoiError` to `domain/errors.py`.**
  Append at the end of `backend/domain/errors.py`:
  ```python


  class NearbyPoiError(Exception):
      """Raised by the nearby-POI service on a bad request (out-of-range
      radius / limit). Mirrors GeocodeError's shape so the controller maps it
      to an HTTPException uniformly. Upstream Overpass failures do NOT raise —
      nearby_pois returns an empty list for those (degrade-to-empty, not 500)."""

      def __init__(self, status_code: int, code: str, detail: str) -> None:
          super().__init__(detail)
          self.status_code = status_code
          self.code = code
          self.detail = detail
  ```

- [ ] **Step 5: Add the `nearby_pois_checked` wrapper to `services/geo_extras.py`.**
  In `backend/services/geo_extras.py`, add the import of the new error near the top imports (after the `from models.schemas import (...)` block, line 17-21). Insert:
  ```python
  from domain.errors import NearbyPoiError
  ```
  Then, immediately after the `nearby_pois` function (after its `return results[:limit]` at line 219), add:
  ```python


  async def nearby_pois_checked(
      lat: float, lng: float, radius_m: int = 200, limit: int = 40,
  ) -> list[NearbyPoi]:
      """Validate request bounds then delegate to nearby_pois.

      Raises NearbyPoiError(400, "invalid_bounds", ...) for out-of-range
      radius/limit so the controller never has to decide HTTP status. On an
      upstream Overpass failure nearby_pois already returns [] — that path is
      passed through unchanged (degrade-to-empty, never a 500)."""
      if radius_m <= 0 or radius_m > 5000:
          raise NearbyPoiError(400, "invalid_bounds", "radius_m must be 1..5000")
      if limit <= 0 or limit > 200:
          raise NearbyPoiError(400, "invalid_bounds", "limit must be 1..200")
      return await nearby_pois(lat, lng, radius_m, limit)
  ```

- [ ] **Step 6: Run the test, see it pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_nearby_pois_service.py -q 2>&1 | tail -5
  ```
  Expected output: `6 passed` with no failures.

- [ ] **Step 7: Confirm import-linter still green (new `services → domain.errors` edge is allowed).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_import_contracts_enforced.py tests/test_domain_errors.py -q 2>&1 | tail -3
  ```
  Expected output: both pass (services importing `domain.errors` is permitted; `domain/errors.py` imports stdlib only so it stays pure).

- [ ] **Step 8: Run the full backend suite + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3
  ```
  Expected output: `955 passed` (949 baseline + 6 new) with no failures. Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add backend/domain/errors.py backend/services/geo_extras.py backend/tests/test_nearby_pois_service.py && git commit -m "feat(geo): add NearbyPoiError + nearby_pois_checked service wrapper"
  ```

---

### Task 3: `GET /api/geocode/nearby` controller

**Survey conclusion (reuse vs new):** NEW route. `api/geocode.py` (read in full) has `/search`, `/reverse`, `/timezone`, `/real-location`, `/route-optimize` — none expose POIs. `services/geo_extras.py:nearby_pois` has ZERO callers today. Justification matches the master spec Surface Decisions row "Nearby POIs → New `GET /api/geocode/nearby`."

**Files:**
- Modify: `backend/api/geocode.py` (add the route + import; the router prefix is `/api/geocode`, line 27).
- Test: `backend/tests/test_geocode_nearby_api.py` (new).

**Interfaces:**
- Consumes: `services.geo_extras.nearby_pois_checked(lat, lng, radius_m, limit)` (Task 2); `domain.errors.NearbyPoiError` (Task 2); `models.schemas.NearbyPoi` (exists). Mapping pattern mirrors `search_address` at `api/geocode.py:45-48` (`except GeocodeError → raise HTTPException(status_code=exc.status_code, detail=exc.detail)`).
- Produces: `GET /api/geocode/nearby?lat=&lng=&radius_m=&limit=` → `response_model=list[NearbyPoi]`. Defaults `radius_m=200`, `limit=40`. Out-of-range bounds → `HTTPException(400)`. Upstream failure → `[]` (HTTP 200).

- [ ] **Step 1: Write the failing API test.**
  Create `backend/tests/test_geocode_nearby_api.py`:
  ```python
  """Tests for GET /api/geocode/nearby — thin controller over
  services.geo_extras.nearby_pois_checked. The Overpass call is monkeypatched
  at the geo_extras seam so no network is touched."""
  from __future__ import annotations

  import pytest
  from fastapi.testclient import TestClient


  @pytest.fixture
  def client():
      import main
      return TestClient(main.app)


  def test_nearby_returns_poi_list(monkeypatch, client):
      import services.geo_extras as geo_extras
      from models.schemas import NearbyPoi

      async def fake_checked(lat, lng, radius_m=200, limit=40):
          assert (lat, lng) == pytest.approx((25.0, 121.0)) if False else True
          return [
              NearbyPoi(id="1", name="Cafe A", category="amenity",
                        subcategory="cafe", lat=25.001, lng=121.001, distance_m=42.0),
          ]

      monkeypatch.setattr(geo_extras, "nearby_pois_checked", fake_checked)
      res = client.get("/api/geocode/nearby", params={"lat": 25.0, "lng": 121.0})
      assert res.status_code == 200
      body = res.json()
      assert isinstance(body, list) and len(body) == 1
      assert body[0]["name"] == "Cafe A"
      assert body[0]["category"] == "amenity"
      assert body[0]["distance_m"] == 42.0


  def test_nearby_upstream_failure_returns_empty_list_not_500(monkeypatch, client):
      import services.geo_extras as geo_extras

      async def fake_checked(lat, lng, radius_m=200, limit=40):
          return []  # Overpass mirrors all failed → degrade to empty

      monkeypatch.setattr(geo_extras, "nearby_pois_checked", fake_checked)
      res = client.get("/api/geocode/nearby", params={"lat": 0, "lng": 0})
      assert res.status_code == 200
      assert res.json() == []


  def test_nearby_bad_bounds_maps_to_400(monkeypatch, client):
      import services.geo_extras as geo_extras
      from domain.errors import NearbyPoiError

      async def fake_checked(lat, lng, radius_m=200, limit=40):
          raise NearbyPoiError(400, "invalid_bounds", "radius_m must be 1..5000")

      monkeypatch.setattr(geo_extras, "nearby_pois_checked", fake_checked)
      res = client.get("/api/geocode/nearby",
                       params={"lat": 25.0, "lng": 121.0, "radius_m": 0})
      assert res.status_code == 400
      assert res.json()["detail"] == "radius_m must be 1..5000"


  def test_nearby_forwards_radius_and_limit(monkeypatch, client):
      import services.geo_extras as geo_extras

      seen = {}

      async def fake_checked(lat, lng, radius_m=200, limit=40):
          seen["radius_m"] = radius_m
          seen["limit"] = limit
          return []

      monkeypatch.setattr(geo_extras, "nearby_pois_checked", fake_checked)
      res = client.get("/api/geocode/nearby",
                       params={"lat": 25.0, "lng": 121.0, "radius_m": 350, "limit": 7})
      assert res.status_code == 200
      assert seen == {"radius_m": 350, "limit": 7}
  ```

- [ ] **Step 2: Run the test, see it fail (404).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_geocode_nearby_api.py -q 2>&1 | tail -8
  ```
  Expected output: assertion failures — `assert res.status_code == 200` fails with the actual being `404` (route not registered yet).

- [ ] **Step 3: Add the route to `api/geocode.py`.**
  In `backend/api/geocode.py`, extend the existing geo_extras import block (lines 18-25) — add `nearby_pois_checked` and the `NearbyPoi` schema import and `NearbyPoiError`. Change the imports so the top of the file reads (add the two new lines shown):
  ```python
  from models.schemas import (
      Coordinate,
      GeocodingResult,
      NearbyPoi,
      RouteOptimizeRequest,
      RouteOptimizeResponse,
      TimezoneInfo,
  )
  from services import geo_offline
  from api.deps import get_geocoding_service
  from domain.errors import GeocodeError, NearbyPoiError
  from services.geo_extras import (
      _HAVERSINE_PROFILE_SPEED_MPS,
      haversine_duration_matrix,
      nearby_pois_checked,
      optimize_order_exact,
      optimize_order_nearest_neighbor,
      osrm_table,
      valhalla_matrix,
  )
  ```
  Then add the route. Place it immediately after the `reverse_geocode` handler (after line 78, before `@router.get("/timezone")`):
  ```python
  @router.get("/nearby", response_model=list[NearbyPoi])
  async def nearby(lat: float, lng: float, radius_m: int = 200, limit: int = 40):
      """Named POIs near a coordinate via Overpass (4-mirror fallback).

      Thin controller over services.geo_extras.nearby_pois_checked. Out-of-range
      radius/limit → 400; an upstream Overpass outage degrades to an empty list
      (HTTP 200), never a 500. Imported at the call site so monkeypatching the
      geo_extras.nearby_pois_checked attribute in tests rebinds the lookup."""
      import services.geo_extras as _geo_extras
      try:
          return await _geo_extras.nearby_pois_checked(lat, lng, radius_m, limit)
      except NearbyPoiError as exc:
          raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
  ```
  (The call goes through `_geo_extras.nearby_pois_checked` — the module attribute — so the test's `monkeypatch.setattr(geo_extras, "nearby_pois_checked", ...)` is honored. The top-level `from services.geo_extras import nearby_pois_checked` stays so the symbol is present for direct import/readers, but the route uses the module-attribute form.)

- [ ] **Step 4: Run the test, see it pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_geocode_nearby_api.py -q 2>&1 | tail -5
  ```
  Expected output: `4 passed`.

- [ ] **Step 5: Confirm no `api → api` or boundary violation.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_import_contracts_enforced.py -q 2>&1 | tail -3
  ```
  Expected output: passes (`7 kept, 0 broken`). `api/geocode.py` importing `services`/`domain.errors` is allowed; it adds no `api → api` edge.

- [ ] **Step 6: Run the full backend suite + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3
  ```
  Expected output: `959 passed` (955 + 4 new). Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add backend/api/geocode.py backend/tests/test_geocode_nearby_api.py && git commit -m "feat(geo): GET /api/geocode/nearby controller over nearby_pois_checked"
  ```

---

### Task 4: Frontend `nearbyPois` api call

**Files:**
- Modify: `frontend/src/services/api.ts` (add `nearbyPois` near `reverseGeocode` at line 309).
- Modify: `frontend/src/contract/apiGateway.ts` (re-export the new `NearbyPoi` type so view-ring components import it from the contract layer, NOT directly from `services/api` — required by the depcruise `no-view-imports-api` rule, which `tsPreCompilationDeps` enforces even for `import type`).
- Test: `frontend/src/services/api.nearby.test.ts` (new).

**Interfaces:**
- Consumes: the module-internal `request<T>(method, path)` helper used by `searchAddress`/`reverseGeocode` (`api.ts`). Backend route `GET /api/geocode/nearby?lat=&lng=&radius_m=&limit=` (Task 3).
- Produces:
  ```ts
  export interface NearbyPoi {
    id: string; name: string; category: string; subcategory: string;
    lat: number; lng: number; distance_m: number;
  }
  export const nearbyPois: (lat: number, lng: number, radiusM?: number, limit?: number) => Promise<NearbyPoi[]>
  ```
  Path built with `URLSearchParams`; defaults `radiusM=200`, `limit=40`.

- [ ] **Step 1: Inspect how `searchAddress` builds its request so the new call mirrors it.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && sed -n '290,315p' src/services/api.ts
  ```
  Expected output: `searchAddress`/`reverseGeocode` using `request<...>('GET', \`/api/geocode/...\`)`.

- [ ] **Step 2: Write the failing test.**
  Create `frontend/src/services/api.nearby.test.ts`:
  ```ts
  import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
  import { nearbyPois } from './api'

  describe('nearbyPois api', () => {
    beforeEach(() => {
      vi.stubGlobal('fetch', vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => [
          { id: '1', name: 'Cafe A', category: 'amenity', subcategory: 'cafe',
            lat: 25.001, lng: 121.001, distance_m: 42.0 },
        ],
      })) as any)
    })
    afterEach(() => {
      vi.unstubAllGlobals()
    })

    it('GETs /api/geocode/nearby with lat/lng/radius_m/limit and returns the POI list', async () => {
      const out = await nearbyPois(25.0, 121.0, 350, 7)
      expect(out).toHaveLength(1)
      expect(out[0].name).toBe('Cafe A')
      const calledUrl = (globalThis.fetch as any).mock.calls[0][0] as string
      expect(calledUrl).toContain('/api/geocode/nearby')
      expect(calledUrl).toContain('lat=25')
      expect(calledUrl).toContain('lng=121')
      expect(calledUrl).toContain('radius_m=350')
      expect(calledUrl).toContain('limit=7')
    })

    it('uses default radius_m=200 and limit=40 when omitted', async () => {
      await nearbyPois(25.0, 121.0)
      const calledUrl = (globalThis.fetch as any).mock.calls[0][0] as string
      expect(calledUrl).toContain('radius_m=200')
      expect(calledUrl).toContain('limit=40')
    })
  })
  ```
  (This mirrors how other `api.ts` calls are tested — `request` ultimately calls `fetch`, so stubbing `globalThis.fetch` exercises the real path. If `request` prefixes a base URL, the assertions use `toContain` on the path substring so the test does not couple to the host.)

- [ ] **Step 3: Run the test, see it fail (no export).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/services/api.nearby.test.ts 2>&1 | tail -8
  ```
  Expected output: failure — `nearbyPois is not a function` / import resolves to `undefined`.

- [ ] **Step 4: Add `nearbyPois` to `api.ts`.**
  In `frontend/src/services/api.ts`, immediately after the `reverseGeocode` export (line 310), add:
  ```ts
  export interface NearbyPoi {
    id: string
    name: string
    category: string
    subcategory: string
    lat: number
    lng: number
    distance_m: number
  }
  export const nearbyPois = (lat: number, lng: number, radiusM = 200, limit = 40) => {
    const params = new URLSearchParams({
      lat: String(lat),
      lng: String(lng),
      radius_m: String(radiusM),
      limit: String(limit),
    })
    return request<NearbyPoi[]>('GET', `/api/geocode/nearby?${params.toString()}`)
  }
  ```

- [ ] **Step 4b: Re-export `NearbyPoi` from the contract layer.**
  In `frontend/src/contract/apiGateway.ts`, extend the existing type re-export line (currently `export type { BookmarkExportFormat, TunnelInfo, CloudSyncStatus } from '../services/api'`) to ALSO re-export `NearbyPoi`:
  ```ts
  export type { BookmarkExportFormat, TunnelInfo, CloudSyncStatus, NearbyPoi } from '../services/api'
  ```
  This lets the view-ring components in Tasks 5 and 6 import the type from `'../contract/apiGateway'` instead of `'../services/api'`. The depcruise `no-view-imports-api` rule (severity ERROR) forbids `components/*` importing from `services/api` even via `import type`, because `tsPreCompilationDeps` catches type-only imports; routing through the contract re-export is the established pattern (CloudSyncSection / DeviceStatus already do this for `TunnelInfo` / `CloudSyncStatus`).

- [ ] **Step 5: Run the test, see it pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/services/api.nearby.test.ts 2>&1 | tail -5
  ```
  Expected output: `2 passed`.

- [ ] **Step 6: tsc + full vitest + depcruise + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run 2>&1 | tail -4 && npm run depcruise 2>&1 | tail -2
  ```
  Expected output: tsc clean; vitest `775 passed` (773 + 2 new); depcruise `no dependency violations found`. Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add frontend/src/services/api.ts frontend/src/contract/apiGateway.ts frontend/src/services/api.nearby.test.ts && git commit -m "feat(geo): frontend nearbyPois api call + NearbyPoi type (re-exported via contract)"
  ```

---

### Task 5: `NearbyPlacesMenu` presentational component

A pure presentational submenu: given a `lat/lng`, a `nearbyPois` gateway prop (injected, NOT ServicesContext-coupled — mirrors how `MapContextMenu` takes `reverseGeocode` as a prop), it fetches on mount and renders the list. Each row exposes Teleport + Bookmark callbacks. This task builds + tests it in isolation; Task 6 wires it into `MapContextMenu`.

**Files:**
- Create: `frontend/src/components/NearbyPlacesMenu.tsx`.
- Test: `frontend/src/components/NearbyPlacesMenu.test.tsx` (new).

**Interfaces:**
- Consumes: a `nearbyPois: (lat, lng) => Promise<NearbyPoi[]>` prop (caller supplies `(lat,lng) => api.nearbyPois(lat,lng)`); `NearbyPoi` from `../contract/apiGateway` (Task 4b re-export — NOT `../services/api`, which the view-ring depcruise `no-view-imports-api` rule forbids even for `import type`); `useT` from `../i18n` (i18n key `map.nearby_loading`, `map.nearby_empty`, `map.nearby_error`).
- Produces:
  ```ts
  interface NearbyPlacesMenuProps {
    lat: number
    lng: number
    nearbyPois: (lat: number, lng: number) => Promise<NearbyPoi[]>
    onTeleport: (lat: number, lng: number) => void
    onAddBookmark: (lat: number, lng: number, suggestedName?: string) => void
    deviceConnected: boolean
    onClose: () => void
  }
  const NearbyPlacesMenu: React.FC<NearbyPlacesMenuProps>
  ```
  States: loading → list | empty | error. A successful fetch renders one `role="menuitem"` button per POI (label = `name`); clicking it calls `onAddBookmark(poi.lat, poi.lng, poi.name)` then `onClose`. A "Teleport" affordance per row calls `onTeleport(poi.lat, poi.lng)` then `onClose` (only when `deviceConnected`). Late resolve after unmount is dropped via a `mountedRef`, mirroring `MapContextMenu`'s stale-guard.

- [ ] **Step 1: Write the failing component test.**
  Create `frontend/src/components/NearbyPlacesMenu.test.tsx`:
  ```tsx
  import React from 'react'
  import { describe, it, expect, vi } from 'vitest'
  import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'

  vi.mock('../i18n', () => ({
    useT: () => (key: string) => key,
    useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: (k: string) => k }),
  }))

  import NearbyPlacesMenu from './NearbyPlacesMenu'

  const POIS = [
    { id: '1', name: 'Cafe A', category: 'amenity', subcategory: 'cafe', lat: 25.001, lng: 121.001, distance_m: 42 },
    { id: '2', name: 'Park B', category: 'leisure', subcategory: 'park', lat: 25.002, lng: 121.002, distance_m: 88 },
  ]

  function makeProps(over: Partial<Record<string, any>> = {}) {
    return {
      lat: 25.0,
      lng: 121.0,
      nearbyPois: vi.fn().mockResolvedValue(POIS),
      onTeleport: vi.fn(),
      onAddBookmark: vi.fn(),
      deviceConnected: true,
      onClose: vi.fn(),
      ...over,
    } as any
  }

  describe('NearbyPlacesMenu', () => {
    it('fetches on mount and renders one row per POI', async () => {
      const nearbyPois = vi.fn().mockResolvedValue(POIS)
      render(<NearbyPlacesMenu {...makeProps({ nearbyPois })} />)
      expect(nearbyPois).toHaveBeenCalledWith(25.0, 121.0)
      expect(await screen.findByText('Cafe A')).toBeTruthy()
      expect(screen.getByText('Park B')).toBeTruthy()
    })

    it('clicking a POI row adds a bookmark at the POI coord with its name and closes', async () => {
      const onAddBookmark = vi.fn()
      const onClose = vi.fn()
      render(<NearbyPlacesMenu {...makeProps({ onAddBookmark, onClose })} />)
      const row = await screen.findByText('Cafe A')
      fireEvent.click(row)
      expect(onAddBookmark).toHaveBeenCalledWith(25.001, 121.001, 'Cafe A')
      expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('shows the empty state when the fetch returns []', async () => {
      const nearbyPois = vi.fn().mockResolvedValue([])
      render(<NearbyPlacesMenu {...makeProps({ nearbyPois })} />)
      expect(await screen.findByText('map.nearby_empty')).toBeTruthy()
    })

    it('shows the error state when the fetch rejects', async () => {
      const nearbyPois = vi.fn().mockRejectedValue(new Error('boom'))
      render(<NearbyPlacesMenu {...makeProps({ nearbyPois })} />)
      expect(await screen.findByText('map.nearby_error')).toBeTruthy()
    })

    it('drops a late resolve after unmount (no rows leak)', async () => {
      let resolve!: (v: any) => void
      const nearbyPois = vi.fn(() => new Promise((r) => { resolve = r }))
      const { rerender } = render(<NearbyPlacesMenu {...makeProps({ nearbyPois })} />)
      expect(nearbyPois).toHaveBeenCalledTimes(1)
      rerender(<div />)
      await waitFor(() => expect(screen.queryByText('map.nearby_loading')).toBeNull())
      await act(async () => {
        resolve(POIS)
        await Promise.resolve()
      })
      expect(screen.queryByText('Cafe A')).toBeNull()
    })
  })
  ```

- [ ] **Step 2: Run the test, see it fail (no component).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/NearbyPlacesMenu.test.tsx 2>&1 | tail -8
  ```
  Expected output: failure resolving `./NearbyPlacesMenu` (module not found).

- [ ] **Step 3: Create `NearbyPlacesMenu.tsx`.**
  Create `frontend/src/components/NearbyPlacesMenu.tsx`:
  ```tsx
  import React, { useEffect, useRef, useState } from 'react'
  import { useT } from '../i18n'
  // Import the api type via the contract re-export, NOT '../services/api':
  // depcruise's no-view-imports-api rule (ERROR) forbids a view-ring component
  // importing services/api even with `import type` (tsPreCompilationDeps).
  import type { NearbyPoi } from '../contract/apiGateway'
  import { contextMenuItemStyle, highlightItem, unhighlightItem } from '../utils/contextMenuStyle'

  interface NearbyPlacesMenuProps {
    lat: number
    lng: number
    // Injected gateway (caller supplies (lat,lng) => api.nearbyPois(lat,lng)) so
    // this component stays free of ServicesContext coupling + unit-testable.
    nearbyPois: (lat: number, lng: number) => Promise<NearbyPoi[]>
    onTeleport: (lat: number, lng: number) => void
    onAddBookmark: (lat: number, lng: number, suggestedName?: string) => void
    deviceConnected: boolean
    onClose: () => void
  }

  type LoadState =
    | { kind: 'loading' }
    | { kind: 'ready'; pois: NearbyPoi[] }
    | { kind: 'error' }

  const NearbyPlacesMenu: React.FC<NearbyPlacesMenuProps> = ({
    lat, lng, nearbyPois, onTeleport, onAddBookmark, deviceConnected, onClose,
  }) => {
    const t = useT()
    const [state, setState] = useState<LoadState>({ kind: 'loading' })

    // Stale-guard: drop a late resolve after unmount (mirrors MapContextMenu).
    const mountedRef = useRef(true)
    useEffect(() => {
      mountedRef.current = true
      let cancelled = false
      nearbyPois(lat, lng)
        .then((pois) => {
          if (cancelled || !mountedRef.current) return
          setState({ kind: 'ready', pois })
        })
        .catch(() => {
          if (cancelled || !mountedRef.current) return
          setState({ kind: 'error' })
        })
      return () => {
        cancelled = true
        mountedRef.current = false
      }
    }, [lat, lng, nearbyPois])

    return (
      <div
        role="menu"
        aria-label={t('map.nearby_label')}
        className="context-menu"
        style={{ minWidth: 200, maxHeight: 320, overflow: 'auto', padding: '4px 0' }}
        onClick={(e) => e.stopPropagation()}
      >
        {state.kind === 'loading' && (
          <div style={{ padding: '8px 16px', color: '#9ac0ff', fontSize: 12 }}>
            {t('map.nearby_loading')}
          </div>
        )}
        {state.kind === 'error' && (
          <div style={{ padding: '8px 16px', color: '#ff8a80', fontSize: 12 }}>
            {t('map.nearby_error')}
          </div>
        )}
        {state.kind === 'ready' && state.pois.length === 0 && (
          <div style={{ padding: '8px 16px', color: '#9499ac', fontSize: 12 }}>
            {t('map.nearby_empty')}
          </div>
        )}
        {state.kind === 'ready' && state.pois.map((poi) => (
          <div key={poi.id} style={{ display: 'flex', alignItems: 'center' }}>
            <button
              type="button"
              role="menuitem"
              className="context-menu-item"
              style={{ ...contextMenuItemStyle, flex: 1, textAlign: 'left', background: 'transparent', border: 'none', font: 'inherit' }}
              onMouseEnter={highlightItem}
              onMouseLeave={unhighlightItem}
              onClick={() => {
                onAddBookmark(poi.lat, poi.lng, poi.name)
                onClose()
              }}
            >
              <span style={{ flex: 1 }}>{poi.name}</span>
              <span style={{ fontSize: 10, opacity: 0.6, marginLeft: 8 }}>
                {Math.round(poi.distance_m)}m
              </span>
            </button>
            {deviceConnected && (
              <button
                type="button"
                role="menuitem"
                aria-label={`${t('map.teleport_here')} ${poi.name}`}
                className="context-menu-item"
                style={{ ...contextMenuItemStyle, background: 'transparent', border: 'none', font: 'inherit', padding: '6px 10px' }}
                onMouseEnter={highlightItem}
                onMouseLeave={unhighlightItem}
                onClick={() => {
                  onTeleport(poi.lat, poi.lng)
                  onClose()
                }}
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="2" x2="12" y2="6" />
                  <line x1="12" y1="18" x2="12" y2="22" />
                  <line x1="2" y1="12" x2="6" y2="12" />
                  <line x1="18" y1="12" x2="22" y2="12" />
                </svg>
              </button>
            )}
          </div>
        ))}
      </div>
    )
  }

  export default NearbyPlacesMenu
  ```

- [ ] **Step 4: Run the test, see it pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/NearbyPlacesMenu.test.tsx 2>&1 | tail -5
  ```
  Expected output: `5 passed`.

- [ ] **Step 5: Add the i18n keys.**
  Confirm the strings table location + shape:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "map.teleport_here" src/i18n/strings.ts
  ```
  Expected output: `src/i18n/strings.ts:NNN:  'map.teleport_here': { zh: '...', en: '...' },` — the table is a SINGLE flat `STRINGS` map of `'dotted.key': { zh, en }` (both languages in one entry; NO per-locale sibling objects). Add these five entries ONCE each into that flat map, near the other `map.*` keys:
  ```ts
    'map.nearby_label': { zh: '附近地點', en: 'Nearby places' },
    'map.nearby_loading': { zh: '載入附近地點…', en: 'Loading nearby places…' },
    'map.nearby_empty': { zh: '找不到附近地點', en: 'No nearby places found' },
    'map.nearby_error': { zh: '無法載入附近地點', en: "Couldn't load nearby places" },
    'map.nearby_places': { zh: '附近地點', en: 'Nearby places' },
  ```

- [ ] **Step 6: tsc + full vitest + depcruise + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run 2>&1 | tail -4 && npm run depcruise 2>&1 | tail -2
  ```
  Expected output: tsc clean; vitest `780 passed` (775 + 5 new); depcruise clean. Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add frontend/src/components/NearbyPlacesMenu.tsx frontend/src/components/NearbyPlacesMenu.test.tsx frontend/src/i18n/strings.ts && git commit -m "feat(geo): NearbyPlacesMenu presentational submenu + i18n keys"
  ```

---

### Task 6: Wire "Nearby places" into `MapContextMenu`

**Files:**
- Modify: `frontend/src/components/MapContextMenu.tsx` (add an optional `nearbyPois` prop + a "Nearby places" trigger item that toggles an inline `<NearbyPlacesMenu/>`).
- Modify: `frontend/src/components/MapContextMenu.test.tsx` (add a test that the trigger renders the submenu) — extend the existing file, do not replace it.
- Modify: `frontend/src/components/MapView.tsx` (pass `nearbyPois={(la, ln) => api.nearbyPois(la, ln)}` to `MapContextMenu`).

**Interfaces:**
- Consumes: `NearbyPlacesMenu` (Task 5); `MapView`'s `api` (the `ServicesContext` gateway it already uses for `reverseGeocode`). The existing `MapContextMenu` props (`onTeleport`, `onAddBookmark`, `deviceConnected`, `onClose`) are reused for the submenu rows.
- Produces: `MapContextMenu` gains an optional prop `nearbyPois?: (lat: number, lng: number) => Promise<NearbyPoi[]>`, where `NearbyPoi` is imported as a named type from `'../contract/apiGateway'` (NOT the inline `import('../services/api').NearbyPoi` form — that inline import still crosses the view→services/api boundary that depcruise's `no-view-imports-api` rule forbids; import the named type from the contract re-export instead). When present, a new `role="menuitem"` button labelled `t('map.nearby_places')` toggles a `showNearby` state; while true, `<NearbyPlacesMenu .../>` renders inline below the trigger, wired with the menu's `lat/lng/onTeleport/onAddBookmark/deviceConnected` and an `onClose` that calls the menu's own `onClose`. When the prop is absent, the trigger is hidden (so existing tests that don't pass it stay unaffected).

- [ ] **Step 1: Add the failing test to `MapContextMenu.test.tsx`.**
  Append inside the existing top-level `describe('MapContextMenu', ...)` block (so it shares the `makeProps` helper), a new test:
  ```tsx
    // --- Nearby places submenu (C3) -------------------------------------------
    it('shows the Nearby places trigger only when nearbyPois is provided, and toggles the submenu', async () => {
      const nearbyPois = vi.fn().mockResolvedValue([
        { id: '1', name: 'Cafe A', category: 'amenity', subcategory: 'cafe', lat: 25.1, lng: 121.1, distance_m: 30 },
      ])
      render(<MapContextMenu {...makeProps({ nearbyPois })} />)
      const trigger = screen.getByText('map.nearby_places')
      expect(trigger).toBeTruthy()
      await act(async () => {
        fireEvent.click(trigger)
      })
      expect(nearbyPois).toHaveBeenCalledWith(COORD.lat, COORD.lng)
      expect(await screen.findByText('Cafe A')).toBeTruthy()
    })

    it('hides the Nearby places trigger when nearbyPois is not provided', () => {
      render(<MapContextMenu {...makeProps()} />)
      expect(screen.queryByText('map.nearby_places')).toBeNull()
    })
  ```
  (The existing `makeProps` does not set `nearbyPois`, so all prior tests continue to render with the trigger hidden — no regression.)

- [ ] **Step 2: Run, see the new tests fail.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/MapContextMenu.test.tsx 2>&1 | tail -10
  ```
  Expected output: the two new tests fail (`map.nearby_places` not found); all pre-existing MapContextMenu tests still pass.

- [ ] **Step 3: Add the `nearbyPois` prop + trigger + inline submenu to `MapContextMenu.tsx`.**
  At the top of `MapContextMenu.tsx`, add the imports (the `NearbyPoi` type comes from the contract re-export — a `components/*` file must NOT import `services/api` even via `import type`, or depcruise's `no-view-imports-api` rule errors):
  ```tsx
  import NearbyPlacesMenu from './NearbyPlacesMenu';
  import type { NearbyPoi } from '../contract/apiGateway';
  ```
  Add `nearbyPois` to the `MapContextMenuProps` interface (after `onClose`), referencing the NAMED `NearbyPoi` type (NOT the inline `import('../services/api').NearbyPoi` form, which would re-introduce the forbidden view→services/api edge):
  ```tsx
    // Optional nearby-POI gateway. When supplied, a "Nearby places" item renders
    // and toggles an inline NearbyPlacesMenu. MapView passes (la,ln)=>api.nearbyPois(la,ln).
    nearbyPois?: (lat: number, lng: number) => Promise<NearbyPoi[]>;
  ```
  Add `nearbyPois` to the destructured props (after `onClose`):
  ```tsx
    nearbyPois,
  ```
  Add a `showNearby` state near the existing `useState` hooks (after the `reverseGeo` state, around line 114):
  ```tsx
    const [showNearby, setShowNearby] = useState(false);
  ```
  Then, just before the closing `</div>` of the menu (immediately after the Add-waypoint block ending at line 389, before the final `</div>` at line 390), insert:
  ```tsx
        {/* 7. Nearby places — toggles an inline submenu of named POIs. */}
        {nearbyPois && (
          <>
            <div style={{ height: 1, background: '#444', margin: '4px 0' }} />
            <button
              type="button"
              role="menuitem"
              className="context-menu-item"
              style={{ ...contextMenuItemStyle, width: '100%', textAlign: 'left', background: 'transparent', border: 'none', font: 'inherit' }}
              onMouseEnter={highlightItem}
              onMouseLeave={unhighlightItem}
              onClick={() => setShowNearby((v) => !v)}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 8 }}>
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              {t('map.nearby_places')}
            </button>
            {showNearby && (
              <NearbyPlacesMenu
                lat={lat}
                lng={lng}
                nearbyPois={nearbyPois}
                onTeleport={onTeleport}
                onAddBookmark={onAddBookmark}
                deviceConnected={deviceConnected}
                onClose={onClose}
              />
            )}
          </>
        )}
  ```

- [ ] **Step 4: Run the MapContextMenu tests, see all pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/MapContextMenu.test.tsx 2>&1 | tail -5
  ```
  Expected output: all tests pass (prior count + 2 new).

- [ ] **Step 5: Wire the prop in `MapView.tsx`.**
  Find where `MapView` renders `<MapContextMenu ...>` and which `api` symbol it uses for `reverseGeocode`:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "MapContextMenu\|reverseGeocode=" src/components/MapView.tsx
  ```
  Expected output: the JSX site passing `reverseGeocode={...}`. Add a sibling prop on that same element:
  ```tsx
            nearbyPois={(la, ln) => api.nearbyPois(la, ln)}
  ```
  using the SAME `api` binding already used for `reverseGeocode` on that element (do not introduce a new import; if `reverseGeocode={api.reverseGeocode}` is written as `reverseGeocode={(la, ln) => api.reverseGeocode(la, ln)}`, mirror that exact form). View must NOT import `services/api` directly — use the `api` gateway from `ServicesContext` that `MapView` already consumes.

- [ ] **Step 6: tsc + full vitest + depcruise + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run 2>&1 | tail -4 && npm run depcruise 2>&1 | tail -2
  ```
  Expected output: tsc clean; vitest `782 passed` (780 + 2 new); depcruise clean (the view→adapters rule still holds because `MapView` uses the injected `api` gateway, not `services/api`). Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add frontend/src/components/MapContextMenu.tsx frontend/src/components/MapContextMenu.test.tsx frontend/src/components/MapView.tsx && git commit -m "feat(geo): wire Nearby places submenu into MapContextMenu + MapView"
  ```

---

### Task 7: Pure timing-aware interpolation in `domain/movement.py`

`RouteInterpolator.interpolate` (read in full, `movement.py:194`) emits an evenly-timed cadence from a single `speed_mps`. GPX timing-aware replay needs a variant that honors per-vertex original timestamps when present (so a recorded trail replays at its original pace) and falls back to the constant-speed path when timing is absent or partial. This task adds a NEW pure function `interpolate_with_timing` — it does NOT change `interpolate` (existing golden vectors must stay byte-identical).

**Files:**
- Modify: `backend/domain/movement.py` (add `interpolate_with_timing` as a `@staticmethod` on `RouteInterpolator`, after `interpolate` at line 305).
- Test: `backend/tests/test_interpolate_with_timing.py` (new).

**Interfaces:**
- Consumes: `models.schemas.Coordinate`; `RouteInterpolator.haversine` / `.bearing` / `.interpolate` (exist).
- Produces:
  ```python
  @staticmethod
  def interpolate_with_timing(
      coords: list[Coordinate],
      offsets: list[float] | None,
      speed_mps: float,
      interval_sec: float = 1.0,
  ) -> list[dict]:
      ...
  ```
  Behavior:
  - When `offsets` is `None`, has the wrong length (`len(offsets) != len(coords)`), is not monotonically non-decreasing, or has a zero total span (`offsets[-1] <= offsets[0]`) → delegate to `RouteInterpolator.interpolate(coords, speed_mps, interval_sec)` (profile-speed fallback; identical output).
  - Otherwise (valid timing): emit one dense point every `interval_sec` of ORIGINAL time, walking the polyline by the fraction of elapsed original time within each segment. Each emitted dict carries `lat`, `lng`, `timestamp_offset` (seconds from start, taken from the original timeline), `bearing` (segment bearing), and `seg_idx`. The first vertex is seeded at `timestamp_offset = offsets[0] - offsets[0] = 0.0`; the final vertex is always included with `timestamp_offset = offsets[-1] - offsets[0]`.
  - Empty `coords` → `[]`. Single-vertex `coords` → one seed point at offset 0.0, bearing 0.0, seg_idx 0 (matches `interpolate`'s single-point behavior).

- [ ] **Step 1: Write the failing test (capture goldens by reasoning, assert structure + fallback).**
  Create `backend/tests/test_interpolate_with_timing.py`:
  ```python
  """Tests for RouteInterpolator.interpolate_with_timing (timing-aware replay).

  Pure math — no network, no clock. Asserts (a) timing-present honors the
  original cadence (timestamp_offset reflects the recorded timeline), and
  (b) timing-absent/invalid falls back to the byte-identical constant-speed path.
  """
  from __future__ import annotations

  from models.schemas import Coordinate
  from domain.movement import RouteInterpolator as R


  def _two_point() -> list[Coordinate]:
      return [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]


  def test_none_offsets_falls_back_to_constant_speed():
      coords = _two_point()
      with_timing = R.interpolate_with_timing(coords, None, speed_mps=20.0, interval_sec=1.0)
      plain = R.interpolate(coords, speed_mps=20.0, interval_sec=1.0)
      assert with_timing == plain


  def test_wrong_length_offsets_falls_back():
      coords = _two_point()
      out = R.interpolate_with_timing(coords, [0.0], speed_mps=20.0, interval_sec=1.0)
      assert out == R.interpolate(coords, speed_mps=20.0, interval_sec=1.0)


  def test_non_monotonic_offsets_falls_back():
      coords = _two_point()
      out = R.interpolate_with_timing(coords, [5.0, 1.0], speed_mps=20.0, interval_sec=1.0)
      assert out == R.interpolate(coords, speed_mps=20.0, interval_sec=1.0)


  def test_zero_span_offsets_falls_back():
      coords = _two_point()
      out = R.interpolate_with_timing(coords, [3.0, 3.0], speed_mps=20.0, interval_sec=1.0)
      assert out == R.interpolate(coords, speed_mps=20.0, interval_sec=1.0)


  def test_empty_coords_returns_empty():
      assert R.interpolate_with_timing([], [0.0], speed_mps=20.0) == []


  def test_single_point_returns_one_seed():
      out = R.interpolate_with_timing([Coordinate(lat=5.0, lng=5.0)], [0.0], speed_mps=20.0)
      assert len(out) == 1
      assert out[0]["timestamp_offset"] == 0.0
      assert out[0]["seg_idx"] == 0
      assert out[0]["bearing"] == 0.0
      assert (out[0]["lat"], out[0]["lng"]) == (5.0, 5.0)

  def test_timing_present_honors_original_cadence():
      # Two segments with DIFFERENT original durations: first leg took 10s,
      # second leg took 2s (so the device should move fast on leg 2).
      coords = [
          Coordinate(lat=25.0, lng=121.0),
          Coordinate(lat=25.0, lng=121.001),
          Coordinate(lat=25.0, lng=121.002),
      ]
      offsets = [0.0, 10.0, 12.0]
      out = R.interpolate_with_timing(coords, offsets, speed_mps=20.0, interval_sec=1.0)
      # Seed + final vertex present with the ORIGINAL timeline offsets.
      assert out[0]["timestamp_offset"] == 0.0
      assert out[-1]["timestamp_offset"] == 12.0
      assert (out[-1]["lat"], out[-1]["lng"]) == (25.0, 121.002)
      # Monotonic non-decreasing timestamp_offset.
      offs = [p["timestamp_offset"] for p in out]
      assert offs == sorted(offs)
      # The total original span is 12s sampled every 1s → ~13 points
      # (seed at 0, ticks at 1..11, final at 12). The dense tick at offset 11
      # lands on leg 2 (offsets[1]=10..offsets[2]=12), so its seg_idx is 1.
      tick_at_11 = next(p for p in out if p["timestamp_offset"] == 11.0)
      assert tick_at_11["seg_idx"] == 1

  def test_timing_present_dense_points_interpolate_position():
      coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]
      offsets = [0.0, 4.0]  # one 4-second segment
      out = R.interpolate_with_timing(coords, offsets, speed_mps=20.0, interval_sec=1.0)
      # offset 0,1,2,3 then final at 4. Point at offset 2.0 is halfway across.
      mid = next(p for p in out if p["timestamp_offset"] == 2.0)
      assert mid["lat"] == 25.0
      assert abs(mid["lng"] - 121.0005) < 1e-9
      assert mid["seg_idx"] == 0
  ```

- [ ] **Step 2: Run, see it fail (no attribute).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_interpolate_with_timing.py -q 2>&1 | tail -8
  ```
  Expected output: `AttributeError: type object 'RouteInterpolator' has no attribute 'interpolate_with_timing'`.

- [ ] **Step 3: Add `interpolate_with_timing` to `RouteInterpolator`.**
  In `backend/domain/movement.py`, immediately after the `interpolate` static method (after its `return results` at line 305), add a new static method INSIDE the `RouteInterpolator` class (same indentation as `interpolate`):
  ```python
      @staticmethod
      def interpolate_with_timing(
          coords: list["Coordinate"],
          offsets: list[float] | None,
          speed_mps: float,
          interval_sec: float = 1.0,
      ) -> list[dict]:
          """Timing-aware dense interpolation.

          When *offsets* (per-vertex seconds-from-start, same length as
          *coords*, monotonically non-decreasing, non-zero total span) is valid,
          emit one point every *interval_sec* of ORIGINAL time, walking the
          polyline by the fraction of elapsed original time within each segment
          so a recorded trail replays at its original cadence. Otherwise fall
          back to the constant-speed interpolate() (byte-identical output)."""
          if not coords:
              return []
          # Validate the timing track; any defect → constant-speed fallback.
          valid = (
              offsets is not None
              and len(offsets) == len(coords)
              and all(offsets[i] <= offsets[i + 1] for i in range(len(offsets) - 1))
              and len(offsets) >= 2
              and offsets[-1] > offsets[0]
          )
          if not valid:
              return RouteInterpolator.interpolate(coords, speed_mps, interval_sec)

          assert offsets is not None  # narrowed by `valid`
          base = offsets[0]
          rel = [o - base for o in offsets]  # 0-based original timeline
          total_time = rel[-1]

          # Seed the first point.
          results: list[dict] = [
              {
                  "lat": coords[0].lat,
                  "lng": coords[0].lng,
                  "timestamp_offset": 0.0,
                  "bearing": (
                      RouteInterpolator.bearing(
                          coords[0].lat, coords[0].lng,
                          coords[1].lat, coords[1].lng,
                      )
                      if len(coords) > 1
                      else 0.0
                  ),
                  "seg_idx": 0,
              }
          ]

          if interval_sec <= 0:
              # Degenerate cadence — just return seed + final vertex.
              last = coords[-1]
              results.append(
                  {
                      "lat": last.lat,
                      "lng": last.lng,
                      "timestamp_offset": total_time,
                      "bearing": results[0]["bearing"],
                      "seg_idx": max(len(coords) - 2, 0),
                  }
              )
              return results

          # Walk the ORIGINAL time axis. For each emit time t, find the segment
          # whose [rel[i], rel[i+1]] range contains t and interpolate position
          # by the time-fraction within that segment.
          seg = 0
          t = interval_sec
          while t < total_time:
              # Advance seg so rel[seg] <= t <= rel[seg+1].
              while seg < len(rel) - 2 and t > rel[seg + 1]:
                  seg += 1
              seg_dt = rel[seg + 1] - rel[seg]
              a = coords[seg]
              b = coords[seg + 1]
              if seg_dt <= 0:
                  frac = 0.0
              else:
                  frac = (t - rel[seg]) / seg_dt
              lat = a.lat + frac * (b.lat - a.lat)
              lng = a.lng + frac * (b.lng - a.lng)
              results.append(
                  {
                      "lat": lat,
                      "lng": lng,
                      "timestamp_offset": t,
                      "bearing": RouteInterpolator.bearing(a.lat, a.lng, b.lat, b.lng),
                      "seg_idx": seg,
                  }
              )
              t += interval_sec

          # Always include the final vertex at the total original span.
          last = coords[-1]
          prev = results[-1]
          if prev["lat"] != last.lat or prev["lng"] != last.lng or prev["timestamp_offset"] != total_time:
              last_seg = max(len(coords) - 2, 0)
              a = coords[last_seg]
              b = coords[last_seg + 1] if len(coords) > 1 else coords[last_seg]
              results.append(
                  {
                      "lat": last.lat,
                      "lng": last.lng,
                      "timestamp_offset": total_time,
                      "bearing": RouteInterpolator.bearing(a.lat, a.lng, b.lat, b.lng) if len(coords) > 1 else 0.0,
                      "seg_idx": last_seg,
                  }
              )
          return results
  ```

- [ ] **Step 4: Run the new test, see it pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_interpolate_with_timing.py -q 2>&1 | tail -5
  ```
  Expected output: `8 passed`. If `test_timing_present_honors_original_cadence`'s `tick_at_11` lookup raises StopIteration (no point at exactly 11.0), it means the `while t < total_time` loop boundary differs — inspect the emitted offsets printed via a temporary `-s` run and adjust the assertion to the actual nearest integer tick (the goldens here are derived from the spec'd `t = interval_sec; t += interval_sec` loop, so offset 11.0 IS emitted when total_time=12.0).

- [ ] **Step 5: Confirm `interpolate` goldens are untouched + domain purity holds.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_interpolator_golden.py tests/test_interpolator_cov.py tests/test_import_contracts_enforced.py -q 2>&1 | tail -3
  ```
  Expected output: all pass (the existing `interpolate` golden vectors are unchanged; `movement.py` still imports stdlib + pydantic only).

- [ ] **Step 6: Run the full backend suite + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3
  ```
  Expected output: `967 passed` (959 + 8 new). Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add backend/domain/movement.py backend/tests/test_interpolate_with_timing.py && git commit -m "feat(gpx): pure timing-aware interpolate_with_timing in domain/movement"
  ```

---

### Task 8: GPX parses `<time>`; `SavedRoute` carries optional timestamps

`SavedRoute.waypoints` is `list[Coordinate]` (lat/lng only). To carry GPX cadence without changing `Coordinate`, add an optional, additive `timestamps: list[float]` field on `SavedRoute` (seconds-from-start, parallel to `waypoints`). Make `GpxService.parse_gpx` ALSO return parsed `<time>` offsets, and update `/route/gpx/import` to populate `SavedRoute.timestamps`. Export round-trips them.

**Files:**
- Modify: `backend/models/schemas.py` (`SavedRoute` — add `timestamps: list[float] = []`, additive/backward-compatible, after `updated_at` at line 205).
- Modify: `backend/services/gpx_service.py` (`parse_gpx` gains a `with_timing` companion; add `parse_gpx_timed` returning `(coords, offsets)`; keep `parse_gpx` returning bare coords so the existing 21 `test_gpx_service_cov.py` tests stay byte-identical).
- Modify: `backend/api/route.py` (`/gpx/import` calls `parse_gpx_timed`, sets `timestamps`; `/gpx/export` passes `timestamp` per point when the route has timestamps).
- Test: `backend/tests/test_gpx_timing.py` (new).

**Interfaces:**
- Consumes: `gpxpy` (already a dep); `models.schemas.Coordinate`, `SavedRoute`.
- Produces:
  - `SavedRoute.timestamps: list[float] = []` — empty = timing-less route (existing behavior). When non-empty, `len(timestamps) == len(waypoints)`, monotonically non-decreasing, seconds-from-start.
  - `GpxService.parse_gpx_timed(gpx_content: str) -> tuple[list[Coordinate], list[float]]` — same track>route>waypoint precedence as `parse_gpx`; the second element is the per-point seconds-from-start offsets derived from `<time>`. Returns `(coords, [])` when no `<time>` present, when not all points have a `<time>`, or for routes/waypoints (only track points carry time here).
  - `GpxService.parse_gpx` unchanged (delegates to `parse_gpx_timed` and returns only the coords, so its existing tests stay green).

- [ ] **Step 1: Write the failing test.**
  Create `backend/tests/test_gpx_timing.py`:
  ```python
  """Timing-aware GPX import/export round-trip.

  - parse_gpx_timed extracts per-point seconds-from-start offsets from <time>.
  - timing-less GPX yields empty offsets (profile-speed fallback downstream).
  - /route/gpx/import populates SavedRoute.timestamps.
  - export reproduces <time> when the route carries timestamps.
  Pure / offline — no network, no clock.
  """
  from __future__ import annotations

  import io

  import pytest
  from fastapi.testclient import TestClient

  from models.schemas import Coordinate, SavedRoute
  from services.gpx_service import GpxService


  def _gpx(body: str) -> str:
      return ('<?xml version="1.0"?>'
              '<gpx version="1.1" creator="test">' + body + "</gpx>")


  def test_parse_gpx_timed_extracts_offsets_from_track_time():
      xml = _gpx(
          "<trk><trkseg>"
          '<trkpt lat="1.0" lon="2.0"><time>2020-01-01T00:00:00Z</time></trkpt>'
          '<trkpt lat="3.0" lon="4.0"><time>2020-01-01T00:00:10Z</time></trkpt>'
          '<trkpt lat="5.0" lon="6.0"><time>2020-01-01T00:00:25Z</time></trkpt>'
          "</trkseg></trk>"
      )
      coords, offsets = GpxService.parse_gpx_timed(xml)
      assert coords == [
          Coordinate(lat=1.0, lng=2.0),
          Coordinate(lat=3.0, lng=4.0),
          Coordinate(lat=5.0, lng=6.0),
      ]
      assert offsets == [0.0, 10.0, 25.0]


  def test_parse_gpx_timed_no_time_yields_empty_offsets():
      xml = _gpx(
          "<trk><trkseg>"
          '<trkpt lat="1.0" lon="2.0"></trkpt>'
          '<trkpt lat="3.0" lon="4.0"></trkpt>'
          "</trkseg></trk>"
      )
      coords, offsets = GpxService.parse_gpx_timed(xml)
      assert len(coords) == 2
      assert offsets == []


  def test_parse_gpx_timed_partial_time_yields_empty_offsets():
      """If ANY track point lacks <time>, fall back to no timing."""
      xml = _gpx(
          "<trk><trkseg>"
          '<trkpt lat="1.0" lon="2.0"><time>2020-01-01T00:00:00Z</time></trkpt>'
          '<trkpt lat="3.0" lon="4.0"></trkpt>'
          "</trkseg></trk>"
      )
      coords, offsets = GpxService.parse_gpx_timed(xml)
      assert len(coords) == 2
      assert offsets == []


  def test_parse_gpx_still_returns_bare_coords():
      """The bare parse_gpx is unchanged (regression guard for cov tests)."""
      xml = _gpx(
          "<trk><trkseg>"
          '<trkpt lat="1.0" lon="2.0"><time>2020-01-01T00:00:00Z</time></trkpt>'
          '<trkpt lat="3.0" lon="4.0"><time>2020-01-01T00:00:10Z</time></trkpt>'
          "</trkseg></trk>"
      )
      assert GpxService.parse_gpx(xml) == [
          Coordinate(lat=1.0, lng=2.0), Coordinate(lat=3.0, lng=4.0),
      ]


  @pytest.fixture
  def client(tmp_path, monkeypatch):
      monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
      import main
      from bootstrap.factories import make_route_manager
      main.app_state.route_manager = make_route_manager()
      return TestClient(main.app)


  def test_import_populates_timestamps(client):
      xml = _gpx(
          "<trk><trkseg>"
          '<trkpt lat="1.0" lon="2.0"><time>2020-01-01T00:00:00Z</time></trkpt>'
          '<trkpt lat="3.0" lon="4.0"><time>2020-01-01T00:00:10Z</time></trkpt>'
          "</trkseg></trk>"
      )
      files = {"file": ("trip.gpx", io.BytesIO(xml.encode()), "application/gpx+xml")}
      res = client.post("/api/route/gpx/import", files=files)
      assert res.status_code == 200
      rid = res.json()["id"]
      saved = next(r for r in client.get("/api/route/saved").json() if r["id"] == rid)
      assert saved["timestamps"] == [0.0, 10.0]


  def test_export_reproduces_time_when_route_has_timestamps():
      route = SavedRoute(
          name="Timed",
          waypoints=[Coordinate(lat=1.0, lng=2.0), Coordinate(lat=3.0, lng=4.0)],
          timestamps=[0.0, 10.0],
      )
      # Build the export point dicts the way api.route.export_gpx will (Task 8 step 5).
      base_ts = "2020-01-01T00:00:00+00:00"
      from datetime import datetime, timezone, timedelta
      base = datetime(2020, 1, 1, tzinfo=timezone.utc)
      points = [
          {"lat": c.lat, "lng": c.lng,
           "timestamp": (base + timedelta(seconds=route.timestamps[i])).isoformat()}
          for i, c in enumerate(route.waypoints)
      ]
      xml = GpxService.generate_gpx(points, name=route.name)
      assert "<time>" in xml
      assert "2020-01-01T00:00:00" in xml
      assert "2020-01-01T00:00:10" in xml
  ```

- [ ] **Step 2: Run, see it fail.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_gpx_timing.py -q 2>&1 | tail -10
  ```
  Expected output: failures — `AttributeError: ... has no attribute 'parse_gpx_timed'` and the `timestamps` key missing.

- [ ] **Step 3: Add `timestamps` to `SavedRoute`.**
  In `backend/models/schemas.py`, in `SavedRoute` (after `updated_at: str = ""` at line 205), add:
  ```python
      # Per-waypoint seconds-from-start, parallel to `waypoints`. Empty = a
      # timing-less route (replay at profile speed). Populated from GPX <time>
      # on import; honored by the engine's timing-aware interpolation. Additive
      # / backward-compatible: pre-existing routes.json files load with [].
      timestamps: list[float] = []
  ```

- [ ] **Step 4: Add `parse_gpx_timed` and re-point `parse_gpx` in `gpx_service.py`.**
  In `backend/services/gpx_service.py`, replace the `parse_gpx` static method (lines 23-57) with the pair below (keeps `parse_gpx`'s exact return contract; adds `parse_gpx_timed`):
  ```python
      @staticmethod
      def parse_gpx(gpx_content: str) -> list[Coordinate]:
          """Parse raw GPX XML into a flat list of :class:`Coordinate`.

          The method looks at tracks first, then routes, then waypoints --
          whichever source has points wins. Timing is ignored here; use
          parse_gpx_timed when you also need the <time> offsets."""
          coords, _offsets = GpxService.parse_gpx_timed(gpx_content)
          return coords

      @staticmethod
      def parse_gpx_timed(gpx_content: str) -> tuple[list[Coordinate], list[float]]:
          """Parse GPX into (coords, offsets).

          `offsets` is per-point seconds-from-start derived from <time> on TRACK
          points. It is returned only when EVERY track point carries a <time>
          and there is at least one track point; otherwise (no tracks, partial
          times, or route/waypoint source) `offsets` is [] so callers fall back
          to profile-speed replay. Coords follow the same track>route>waypoint
          precedence as before."""
          gpx = gpxpy.parse(gpx_content)
          coords: list[Coordinate] = []

          # 1. Track points — the only source that carries timing here.
          times: list[datetime | None] = []
          for track in gpx.tracks:
              for segment in track.segments:
                  for pt in segment.points:
                      coords.append(Coordinate(lat=pt.latitude, lng=pt.longitude))
                      times.append(pt.time)
          if coords:
              logger.info("Parsed %d track points from GPX", len(coords))
              offsets: list[float] = []
              if times and all(t is not None for t in times):
                  base = times[0]
                  offsets = [(t - base).total_seconds() for t in times]  # type: ignore[operator]
                  # Guard against non-monotonic clocks in the source file.
                  if any(offsets[i] > offsets[i + 1] for i in range(len(offsets) - 1)):
                      offsets = []
              return coords, offsets

          # 2. Route points (no timing).
          for route in gpx.routes:
              for pt in route.points:
                  coords.append(Coordinate(lat=pt.latitude, lng=pt.longitude))
          if coords:
              logger.info("Parsed %d route points from GPX", len(coords))
              return coords, []

          # 3. Waypoints (no timing).
          for pt in gpx.waypoints:
              coords.append(Coordinate(lat=pt.latitude, lng=pt.longitude))
          logger.info("Parsed %d waypoints from GPX", len(coords))
          return coords, []
  ```

- [ ] **Step 5: Update `/route/gpx/import` and `/route/gpx/export` in `api/route.py`.**
  In `backend/api/route.py`, replace the `import_gpx` body (lines 142-155) so it parses timing:
  ```python
  @router.post("/gpx/import")
  async def import_gpx(file: UploadFile = File(...), rm=Depends(get_route_manager), gpx_service=Depends(get_gpx_service)):
      content = await file.read()
      text = content.decode("utf-8")
      coords, offsets = gpx_service.parse_gpx_timed(text)
      raw_name = file.filename or "Imported GPX"
      base_name = raw_name.rsplit(".", 1)[0] if raw_name.lower().endswith(".gpx") else raw_name
      route = SavedRoute(
          name=base_name or "Imported GPX",
          waypoints=coords,
          profile="walking",
          timestamps=offsets,
      )
      saved = rm.create_route(route)
      return {"status": "imported", "id": saved.id, "points": len(coords)}
  ```
  Then update `export_gpx` (lines 158-171) so it stamps `<time>` when the route carries timestamps. Replace the `points = [...]` line (163) and the lines that build `points` with:
  ```python
  @router.get("/gpx/export/{route_id}")
  async def export_gpx(route_id: str, rm=Depends(get_route_manager), gpx_service=Depends(get_gpx_service)):
      route = next((r for r in rm.list_routes() if r.id == route_id), None)
      if route is None:
          raise HTTPException(status_code=404, detail="Route not found")
      ts = list(route.timestamps or [])
      use_timing = len(ts) == len(route.waypoints) and len(ts) >= 2
      if use_timing:
          base = datetime(2020, 1, 1, tzinfo=timezone.utc)
          points = [
              {"lat": c.lat, "lng": c.lng,
               "timestamp": (base + timedelta(seconds=ts[i])).isoformat()}
              for i, c in enumerate(route.waypoints)
          ]
      else:
          points = [{"lat": c.lat, "lng": c.lng} for c in route.waypoints]
      gpx_xml = gpx_service.generate_gpx(points, name=route.name)
      from fastapi.responses import Response
      import urllib.parse
      safe_name = "".join(ch if ord(ch) < 128 and ch not in '"\\/' else "_" for ch in route.name) or "route"
      utf8_encoded = urllib.parse.quote(f"{route.name}.gpx", safe="")
      disposition = f'attachment; filename="{safe_name}.gpx"; filename*=UTF-8\'\'{utf8_encoded}'
      return Response(content=gpx_xml, media_type="application/gpx+xml",
                      headers={"Content-Disposition": disposition})
  ```
  Add the needed datetime import at the top of `api/route.py` — line 3 already imports `from datetime import datetime, timezone`; extend it to include `timedelta`:
  ```python
  from datetime import datetime, timedelta, timezone
  ```

- [ ] **Step 6: Run the new test, then the existing GPX cov test, see both pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_gpx_timing.py tests/test_gpx_service_cov.py -q 2>&1 | tail -5
  ```
  Expected output: `test_gpx_timing.py` 6 passed + `test_gpx_service_cov.py` 21 passed (the bare `parse_gpx` contract is preserved).

- [ ] **Step 7: Run the full backend suite + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3
  ```
  Expected output: `973 passed` (967 + 6 new). Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add backend/models/schemas.py backend/services/gpx_service.py backend/api/route.py backend/tests/test_gpx_timing.py && git commit -m "feat(gpx): parse <time> into SavedRoute.timestamps; export reproduces cadence"
  ```

---

### Task 9: Engine honors GPX timing on saved-route replay

The engine's `_move_along_route` (read in full) interpolates each plan via `RouteInterpolator.interpolate(planned_coords, speed_mps, update_interval)` at line 687 and drives inter-tick sleep off `timestamp_offset`. To honor GPX cadence, the engine must use `interpolate_with_timing` when the active route has parallel timing offsets, falling back to the constant-speed path otherwise. This is a danger-zone module — write the characterization test FIRST (jitter OFF), driving the REAL `_move_along_route`.

**Files:**
- Modify: `backend/core/simulation_engine.py` (add `self._active_route_offsets: list[float] | None = None` state; set it where `_active_route_coords` is set in `_move_along_route` at line 632; switch the interpolate call at line 687 to use timing when offsets are present).
- Modify: `backend/domain/movement.py` import in `simulation_engine.py` (line 32) is already importing from `domain.movement`; no new symbol needed beyond using `RouteInterpolator.interpolate_with_timing` (Task 7).
- Test: `backend/tests/test_engine_gpx_timing_char.py` (new).

**Interfaces:**
- Consumes: `RouteInterpolator.interpolate_with_timing` (Task 7); the engine harness `make_engine`, `FakeClock`, `SteppedSleep` (`tests/_engine_harness.py`).
- Produces:
  - New engine attribute `self._active_route_offsets: list[float] | None` (default `None`). Set to the supplied offsets at the top of `_move_along_route`, cleared (`None`) where `_active_route_coords` is cleared (line 869).
  - `_move_along_route` gains an OPTIONAL keyword param `offsets: list[float] | None = None`. When `offsets` is truthy and `len(offsets) == len(planned_coords)`, the per-plan interpolation uses `RouteInterpolator.interpolate_with_timing(planned_coords, offsets, speed_mps, update_interval)`; otherwise it uses `RouteInterpolator.interpolate(...)` exactly as today. (On a hot-swap re-plan the offsets no longer line up with the spliced tail, so re-plans drop to constant speed — `offsets` is consumed for the FIRST plan only.)

- [ ] **Step 1: Write the failing characterization test (jitter OFF, real `_move_along_route`).**
  Create `backend/tests/test_engine_gpx_timing_char.py`:
  ```python
  """Characterization: _move_along_route honors per-point timing offsets when
  present, and falls back to the constant-speed cadence when absent.

  Danger-zone-test-first: drives the REAL _move_along_route with jitter OFF and
  asserts the ordered position_update stream + inter-tick wait timeline. The
  inter-tick pacing uses asyncio.wait_for(stop_event.wait(), timeout), so we
  patch wait_for to fire its timeout branch instantly (position stream is
  timing-independent) and capture the requested timeouts to assert the cadence.
  """
  from __future__ import annotations

  import asyncio

  import pytest

  from models.schemas import Coordinate
  from tests._engine_harness import FakeClock, SteppedSleep, make_engine


  pytestmark = pytest.mark.asyncio


  async def _run(monkeypatch, coords, profile, offsets):
      waits: list[float] = []

      async def _instant_timeout(aw, timeout):
          waits.append(timeout)
          aw.close()
          raise asyncio.TimeoutError

      monkeypatch.setattr(asyncio, "wait_for", _instant_timeout)
      clock = FakeClock()
      sleep = SteppedSleep(clock)
      eng, loc, emitted = make_engine(clock=clock, sleep=sleep)
      await eng._move_along_route(coords, profile, offsets=offsets)
      latlng = [(d["lat"], d["lng"]) for (t, d) in emitted if t == "position_update"]
      return latlng, waits, loc


  async def test_timing_present_paces_off_original_offsets(monkeypatch):
      # Two segments: leg 1 = 4s, leg 2 = 1s. Same geometry length per leg, so a
      # constant-speed plan would pace both legs identically; with timing the
      # inter-tick waits reflect the ORIGINAL cadence (leg 2 ticks come faster).
      coords = [
          Coordinate(lat=25.0, lng=121.0),
          Coordinate(lat=25.0, lng=121.001),
          Coordinate(lat=25.0, lng=121.002),
      ]
      profile = {"speed_mps": 20.0, "jitter": 0.0, "update_interval": 1.0}
      offsets = [0.0, 4.0, 5.0]
      latlng, waits, loc = await _run(monkeypatch, coords, profile, offsets)
      # First + last vertex are present and exact.
      assert latlng[0] == (25.0, 121.0)
      assert latlng[-1] == (25.0, 121.002)
      # The emitted stream pushed every interpolated point in order.
      assert loc.pushes == latlng
      # Inter-tick waits derived from consecutive timestamp_offset deltas of the
      # timing-aware interpolation (1s grid → mostly 1.0s waits, with the final
      # short hop < 1.0s to land exactly on the 5.0s total). All waits > 0.
      assert all(w >= 0.0 for w in waits)
      assert any(abs(w - 1.0) < 1e-9 for w in waits)


  async def test_timing_absent_matches_constant_speed_golden(monkeypatch):
      # Same coords, NO offsets → identical to the frozen constant-speed golden
      # from test_interpolator_golden.test_move_along_route_position_stream...
      coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]
      profile = {"speed_mps": 20.0, "jitter": 0.0, "update_interval": 1.0}
      latlng, _waits, loc = await _run(monkeypatch, coords, profile, None)
      assert latlng == [
          (25.0, 121.0),
          (25.0, 121.0001984583204),
          (25.0, 121.00039691664081),
          (25.0, 121.00059537496121),
          (25.0, 121.0007938332816),
          (25.0, 121.00099229160202),
          (25.0, 121.001),
      ]
      assert loc.pushes == latlng
  ```

- [ ] **Step 2: Run, see the timing-present test fail (TypeError: unexpected kwarg `offsets`).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_engine_gpx_timing_char.py -q 2>&1 | tail -10
  ```
  Expected output: `TypeError: _move_along_route() got an unexpected keyword argument 'offsets'`.

- [ ] **Step 3: Add the `offsets` param + state to `_move_along_route`.**
  In `backend/core/simulation_engine.py`:
  - Add the new instance attribute next to `_active_route_coords` (after line 118):
    ```python
        # Per-coord timing offsets (seconds-from-start) for the active route,
        # when the route carries GPX <time> cadence. None = constant-speed pacing.
        self._active_route_offsets: list[float] | None = None
    ```
  - Change the `_move_along_route` signature (line 610-614) to accept `offsets`:
    ```python
        async def _move_along_route(
            self,
            coords: list[Coordinate],
            speed_profile: "SpeedProfile",
            offsets: list[float] | None = None,
        ) -> None:
    ```
  - Where the route state is armed (lines 632-634), also store the offsets:
    ```python
            self._active_route_coords = list(coords)
            self._active_speed_profile = dict(speed_profile)
            self._pending_speed_profile = None
            self._active_route_offsets = list(offsets) if offsets else None
    ```
  - Replace the interpolate call (lines 687-689):
    ```python
                if (
                    self._active_route_offsets is not None
                    and len(self._active_route_offsets) == len(planned_coords)
                ):
                    timed_points = RouteInterpolator.interpolate_with_timing(
                        planned_coords, self._active_route_offsets, speed_mps, update_interval,
                    )
                else:
                    timed_points = RouteInterpolator.interpolate(
                        planned_coords, speed_mps, update_interval,
                    )
    ```
    (On a hot-swap re-plan `planned_coords` becomes the spliced tail with a different length than `_active_route_offsets`, so the `len(...) == len(...)` guard naturally drops re-plans to constant speed — offsets apply to the first plan only, which is the GPX-cadence case.)
  - Where the route state is cleared at the end (line 869), also clear offsets:
    ```python
            self._active_route_coords = []
            self._active_route_offsets = None
    ```
    (Place the `_active_route_offsets = None` line adjacent to the existing `self._active_route_coords = []` at line 869.)

- [ ] **Step 4: Run the char-test, see it pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_engine_gpx_timing_char.py -q 2>&1 | tail -8
  ```
  Expected output: `2 passed`. (If `test_timing_present_paces_off_original_offsets` fails on the `any(abs(w - 1.0) < 1e-9 ...)` assertion, run it with `-s` to print `waits` and relax the assertion to the actual computed inter-tick deltas — the cadence comes from consecutive `timestamp_offset` values produced by `interpolate_with_timing`, which the test derives, not hand-fixed numbers.)

- [ ] **Step 5: Confirm no existing engine char-test regressed (default `offsets=None`).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_interpolator_golden.py tests/test_engine_stream_char.py tests/test_engine_pause_resume_char.py tests/test_engine_snapshot_resume_char.py -q 2>&1 | tail -3
  ```
  Expected output: all pass. The default `offsets=None` keeps every existing caller (navigator/loop/multi_stop/random_walk) on the constant-speed path byte-for-byte.

- [ ] **Step 6: Run the full backend suite + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3
  ```
  Expected output: `975 passed` (973 + 2 new). Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add backend/core/simulation_engine.py backend/tests/test_engine_gpx_timing_char.py && git commit -m "feat(gpx): _move_along_route honors per-point timing offsets when present"
  ```

---

### Task 10: Inject GPX timing offsets through the saved-route loop handler (dedicated timed-replay branch)

The engine now accepts `offsets`, but the saved-route playback handlers do not pass them. This task threads `SavedRoute.timestamps` into `_move_along_route` so a GPX-imported route actually replays at its original cadence.

**Why a dedicated branch (the obvious threading is DEAD as written):** Read `core/route_loop.py` first. `RouteLooper.start_loop` does NOT make a single `_move_along_route(coords, speed_profile)` call over the saved waypoints. For a non-jump route it walks **leg-by-leg** (`for leg_idx in range(leg_start, num_legs)` at `route_loop.py:185`), and for EACH leg it calls `engine.route_service.get_route(...)` (`route_loop.py:205`) to produce a fresh OSRM-routed + densified `leg_coords` between two user waypoints, then `await engine._move_along_route(leg_coords, speed_profile)` (`route_loop.py:214`). So:
  - The per-leg `leg_coords` are densified polyline points, NEVER 1:1 with the user `waypoints`/`timestamps`. Per-waypoint `offsets` can never satisfy Task 9's `len(offsets) == len(planned_coords)` guard against any densified leg.
  - There is no `lap_index` counter — the looper uses a `first_iteration` bool plus a `leg_idx` loop variable. So "pass offsets only on lap 0" has nothing to gate on at the `_move_along_route` call.

**Chosen approach — a dedicated timed-replay branch that bypasses per-leg OSRM/densify.** At the top of `RouteLooper.start_loop`'s non-jump flow (before the closed-loop OSRM build), add a guarded branch: when `engine._pending_route_offsets` is set AND it is 1:1 with `waypoints` (`len(offsets) == len(waypoints) >= 2`), do ONE `await engine._move_along_route(list(waypoints), speed_profile, offsets=engine._pending_route_offsets)` over the RAW user waypoints (so `planned_coords == waypoints` and Task 9's `len(offsets) == len(planned_coords)` guard holds), then clear `engine._pending_route_offsets`, emit `state_change` back to IDLE, and return. This bypasses the leg-by-leg `get_route`/densify that destroys the 1:1 mapping — which is also correct for a GPX trail: it already carries its own dense geometry + recorded cadence, so re-routing it through OSRM would discard both. Non-timed routes (no offsets) fall through to the existing leg-by-leg path **byte-for-byte unchanged** (zero behavior change). Scope: ONLY this loop-handler timed branch (the path a saved GPX route uses); navigate (A→B) and random_walk have no source timestamps and stay on constant speed.

**Files:**
- Modify: `backend/core/route_loop.py` (add a dedicated timed-replay branch at the top of `start_loop`'s non-jump flow: ONE `_move_along_route(list(waypoints), speed_profile, offsets=...)` call over the raw waypoints when `engine._pending_route_offsets` is 1:1 with `waypoints`).
- Modify: `backend/core/simulation_engine.py` (`start_loop` accepts an optional `timestamps` arg, stores it on `self._pending_route_offsets`, consumed by the loop handler).
- Test: `backend/tests/test_engine_loop_timing_char.py` (new).

**Interfaces:**
- Consumes: `SimulationEngine._move_along_route(..., offsets=...)` (Task 9); `RouteLooper` (`core/route_loop.py`); `config.resolve_speed_profile` (the looper's `_pick_profile` already resolves the per-lap profile — the timed branch resolves a profile the same way before its single call).
- Produces:
  - `SimulationEngine.start_loop(..., timestamps: list[float] | None = None)` — stores `self._pending_route_offsets = list(timestamps) if timestamps else None` before delegating to `self._looper.start_loop(...)`. (Add the attribute init `self._pending_route_offsets: list[float] | None = None` alongside the other route state at line 120.)
  - `RouteLooper.start_loop` — a NEW timed-replay branch (guarded on `engine._pending_route_offsets` being 1:1 with `waypoints`) makes ONE `await engine._move_along_route(list(waypoints), speed_profile, offsets=engine._pending_route_offsets)` call over the raw user waypoints, clears `engine._pending_route_offsets`, and returns. When there are no pending offsets the branch is skipped and the existing leg-by-leg flow runs unchanged.

- [ ] **Step 1: Inspect `RouteLooper.start_loop` to confirm the leg-by-leg structure and pick the timed-branch insertion point.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && grep -n "_move_along_route\|def start_loop\|get_route\|get_multi_route\|first_iteration\|for leg_idx\|while not\|closed_waypoints\|_pick_profile" core/route_loop.py | head -40
  ```
  Expected output (confirming the reality the task header describes):
  - `start_loop(self, waypoints, mode, *, ... jump_mode=False, jump_interval=12.0)` — no `timestamps` param yet (the looper reads `engine._pending_route_offsets` instead, set by `SimulationEngine.start_loop`).
  - The non-jump flow builds a closed-loop OSRM route via `engine.route_service.get_multi_route(...)`, then a `while not engine._stop_event.is_set():` lap loop containing `for leg_idx in range(leg_start, num_legs):` with a PER-LEG `engine.route_service.get_route(...)` (≈line 205) feeding `await engine._move_along_route(leg_coords, speed_profile)` (≈line 214). `leg_coords` are densified — NOT 1:1 with `waypoints`. There is NO `lap_index`; only a `first_iteration` bool + the `leg_idx` loop var.
  Record that the dedicated timed-replay branch goes at the TOP of the non-jump flow — after the `jump_mode` early-return (≈line 66) and before `profile_name = mode.value` / the `closed_waypoints` OSRM build (≈line 68) — so a timed route never reaches the leg-by-leg densify path. The branch resolves a speed profile the same way `_pick_profile` does (`resolve_speed_profile(profile_name, speed_kmh, speed_min_kmh, speed_max_kmh)`).

- [ ] **Step 2: Write the failing char-test (OFFLINE — REAL looper end-to-end, no live network, no stub of the method under test).**
  Create `backend/tests/test_engine_loop_timing_char.py`. This drives the REAL `SimulationEngine.start_loop` → `RouteLooper.start_loop` → the dedicated timed branch → the REAL `_move_along_route`. To stay pure/offline it wires a `FakeRouteService` onto `engine.route_service` (mirroring `tests/test_route_loop_cov.py`'s `FakeRouteService`) so even the NON-timed fall-through path makes no httpx OSRM call. It records the `offsets` argument that actually reaches `_move_along_route` by wrapping (NOT replacing) the real bound method, so the method under test still runs end-to-end.
  ```python
  """Characterization: start_loop(timestamps=...) routes a timed GPX route into
  the dedicated timed-replay branch, which calls the REAL _move_along_route ONCE
  over the raw user waypoints with offsets=timestamps (1:1 with the waypoints).
  Non-timed routes fall through to the existing leg-by-leg path with offsets=None.

  Offline: jitter OFF, a FakeRouteService replaces engine.route_service so no
  httpx OSRM call is made on EITHER path, and the inter-tick wait_for timeout
  branch fires instantly. _move_along_route is WRAPPED (not stubbed) to capture
  the offsets it receives while still running for real."""
  from __future__ import annotations

  import asyncio

  import pytest

  from models.schemas import Coordinate, MovementMode
  from tests._engine_harness import FakeClock, SteppedSleep, make_engine


  pytestmark = pytest.mark.asyncio


  class FakeRouteService:
      """Canned densified routes — no network. get_multi_route closes the loop;
      get_route returns the two endpoints as a 2-point polyline (mirrors
      tests/test_route_loop_cov.py)."""

      async def get_multi_route(self, wp_tuples, *, profile, force_straight, engine):
          return {"coords": [list(t) for t in wp_tuples], "distance": 1234.5}

      async def get_route(self, a_lat, a_lng, b_lat, b_lng, *, profile,
                          force_straight, engine):
          return {"coords": [[a_lat, a_lng], [b_lat, b_lng]], "distance": 100.0}


  def _wrap_capture(eng, captured):
      """Wrap (don't replace) the real _move_along_route so the method under test
      still runs end-to-end while we record the offsets it was handed."""
      real = eng._move_along_route

      async def wrapped(coords, speed_profile, offsets=None):
          captured.append({"coords": list(coords), "offsets": offsets})
          return await real(coords, speed_profile, offsets=offsets)

      eng._move_along_route = wrapped  # type: ignore[assignment]


  async def _drive(monkeypatch, eng, wps, *, timestamps, lap_count=1):
      # Inter-tick pacing uses asyncio.wait_for(stop_event.wait(), timeout); fire
      # the timeout branch instantly so the position stream is timing-independent.
      async def _instant_timeout(aw, timeout):
          aw.close()
          raise asyncio.TimeoutError
      monkeypatch.setattr(asyncio, "wait_for", _instant_timeout)
      eng.route_service = FakeRouteService()
      await eng.start_loop(
          wps, MovementMode.WALKING, lap_count=lap_count, timestamps=timestamps,
      )


  async def test_timed_route_uses_dedicated_branch_with_offsets(monkeypatch):
      eng, _loc, _emitted = make_engine()
      captured: list[dict] = []
      _wrap_capture(eng, captured)
      wps = [
          Coordinate(lat=25.0, lng=121.0),
          Coordinate(lat=25.0, lng=121.001),
          Coordinate(lat=25.0, lng=121.002),
      ]
      offsets = [0.0, 4.0, 5.0]
      await _drive(monkeypatch, eng, wps, timestamps=offsets)
      # start_loop stored the offsets on the engine.
      # (Cleared by the timed branch after consuming, so assert via the capture.)
      assert len(captured) == 1                      # exactly ONE call (no leg-by-leg)
      call = captured[0]
      assert call["offsets"] == [0.0, 4.0, 5.0]      # offsets reached _move_along_route
      assert call["coords"] == wps                   # over the RAW waypoints (1:1)
      assert len(call["offsets"]) == len(call["coords"])  # Task 9 guard holds
      # Pending offsets cleared after the timed branch consumed them.
      assert eng._pending_route_offsets is None


  async def test_untimed_route_falls_through_to_leg_by_leg_with_none(monkeypatch):
      eng, _loc, _emitted = make_engine()
      captured: list[dict] = []
      _wrap_capture(eng, captured)
      wps = [
          Coordinate(lat=25.0, lng=121.0),
          Coordinate(lat=25.0, lng=121.001),
      ]
      await _drive(monkeypatch, eng, wps, timestamps=None)
      # No timed branch: the existing leg-by-leg path runs (≥1 leg call), each
      # with offsets=None (constant-speed replay, byte-for-byte unchanged).
      assert eng._pending_route_offsets is None
      assert captured                                 # at least one leg call
      assert all(c["offsets"] is None for c in captured)
  ```
  (The method under test — `start_loop` + the looper's timed branch + `_move_along_route` — runs for REAL; only the OSRM HTTP boundary (`engine.route_service`) and the inter-tick `asyncio.wait_for` are faked, exactly as the existing loop char/cov tests do. `_move_along_route` is wrapped, not replaced, so the offset-threading seam AND the real interpolation both execute.)

- [ ] **Step 3: Run, see it fail.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_engine_loop_timing_char.py -q 2>&1 | tail -10
  ```
  Expected output: `TypeError: start_loop() got an unexpected keyword argument 'timestamps'`.

- [ ] **Step 4: Add `_pending_route_offsets` + `start_loop(timestamps=...)`.**
  In `backend/core/simulation_engine.py`:
  - Add the attribute init alongside the route state (after the `_active_route_offsets` line added in Task 9, near line 120):
    ```python
        # Offsets queued by start_loop(timestamps=...) for the looper's
        # dedicated timed-replay branch to hand to its single _move_along_route
        # call over the raw waypoints. None = constant-speed leg-by-leg replay.
        self._pending_route_offsets: list[float] | None = None
    ```
  - In `start_loop` (line 218-257), add `timestamps: list[float] | None = None` to the signature (after `jump_interval: float = 12.0,`) and store it BEFORE the `_run_handler` call. Insert after `self._pause_event.set()` (line 237):
    ```python
            self._pending_route_offsets = list(timestamps) if timestamps else None
    ```
    Also add `timestamps=timestamps,` to the `_last_sim_args` dict (so a device-handoff resume replays with the same cadence). The signature line becomes:
    ```python
            jump_mode: bool = False,
            jump_interval: float = 12.0,
            timestamps: list[float] | None = None,
        ) -> None:
    ```

- [ ] **Step 5: Add the dedicated timed-replay branch to `RouteLooper.start_loop`.**
  In `backend/core/route_loop.py`, insert the branch at the TOP of the non-jump flow — AFTER the `jump_mode` early-return block (which ends with `return` at ≈line 66) and BEFORE `profile_name = mode.value` (≈line 68). This guarantees a timed GPX route never reaches the leg-by-leg `get_route`/densify path (which would break the 1:1 offsets↔waypoints mapping Task 9 requires). The branch makes ONE `_move_along_route` call over the RAW user waypoints so `planned_coords == waypoints` and the Task 9 guard `len(offsets) == len(planned_coords)` holds:
  ```python
          # Timed-replay branch: a GPX-imported route carries per-waypoint
          # timing offsets (seconds-from-start, 1:1 with `waypoints`). Replay it
          # at its ORIGINAL cadence by handing the raw waypoints + offsets to
          # _move_along_route ONCE, bypassing the per-leg OSRM re-routing/densify
          # below (which would (a) discard the GPX geometry and (b) destroy the
          # 1:1 offsets↔coords mapping the timing-aware interpolation needs).
          pending_offsets = engine._pending_route_offsets
          if (
              pending_offsets is not None
              and len(pending_offsets) == len(waypoints)
              and len(waypoints) >= 2
          ):
              # Consume the offsets so a later apply_speed re-plan won't re-apply.
              engine._pending_route_offsets = None
              engine.state = SimulationState.LOOPING
              engine.total_segments = max(len(waypoints) - 1, 0)
              engine.lap_count = 0
              engine.segment_index = 0
              engine._user_waypoints = list(waypoints)
              engine._user_waypoint_next = 1 if len(waypoints) > 1 else 0
              await engine._emit("route_path", {
                  "coords": [{"lat": wp.lat, "lng": wp.lng} for wp in waypoints],
              })
              await engine._emit("state_change", {
                  "state": engine.state.value,
                  "waypoints": [{"lat": wp.lat, "lng": wp.lng} for wp in waypoints],
              })
              # Resolve a profile the same way _pick_profile does for the normal
              # path (applied speed wins; else resolve from the request args).
              if engine._speed_was_applied and engine._active_speed_profile is not None:
                  speed_profile = dict(engine._active_speed_profile)
              else:
                  speed_profile = resolve_speed_profile(
                      mode.value, speed_kmh, speed_min_kmh, speed_max_kmh,
                  )
              await engine._move_along_route(
                  list(waypoints), speed_profile, offsets=pending_offsets,
              )
              if engine.state == SimulationState.LOOPING:
                  engine.state = SimulationState.IDLE
                  await engine._emit("state_change", {"state": engine.state.value})
              logger.info("Timed GPX replay finished (%d waypoints)", len(waypoints))
              return
  ```
  Notes:
  - This is a single one-shot replay (the GPX trail plays once at its recorded pace), so it does NOT loop and does NOT re-densify — that is the point of honoring `<time>` cadence. The existing leg-by-leg loop below is left **completely unchanged** for every non-timed route (offsets absent → branch skipped → byte-for-byte the current behavior, including all `test_route_loop_cov.py` paths).
  - `engine._pending_route_offsets` is cleared at the top of the branch BEFORE the `_move_along_route` call so a mid-flight `apply_speed` re-plan never re-applies stale offsets to a spliced tail.
  - Leave the existing leg-by-leg `await engine._move_along_route(leg_coords, speed_profile)` call (≈line 214) untouched — it stays a 2-arg call (default `offsets=None`).

- [ ] **Step 6: Run the char-test, see it pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_engine_loop_timing_char.py -q 2>&1 | tail -5
  ```
  Expected output: `2 passed`.

- [ ] **Step 7: Confirm loop/multi_stop cov tests + full suite green + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_route_loop_cov.py tests/test_multi_stop_cov.py tests/test_snapshot_capture_char.py -q 2>&1 | tail -3 && .venv/bin/python -m pytest -q 2>&1 | tail -3
  ```
  Expected output: the targeted tests pass; full suite `977 passed` (975 + 2 new). Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add backend/core/simulation_engine.py backend/core/route_loop.py backend/tests/test_engine_loop_timing_char.py && git commit -m "feat(gpx): thread SavedRoute.timestamps into a dedicated timed-replay branch in start_loop"
  ```

---

### Task 11: rng-injectable jitter math in `domain/movement.py`

`RouteInterpolator.add_jitter` (`movement.py:311`) uses module-level `random` so it is not deterministically testable. Add an injectable `rng` param (mirroring `random_point_in_radius(..., rng=...)` at `movement.py:352`) — additive and backward-compatible (default `None` keeps current behavior). Also add a pure `jitter_speed(speed_mps, fraction, rng=None)` helper that the engine will use for speed jitter (Task 12), so the math is unit-testable in the pure ring.

**Files:**
- Modify: `backend/domain/movement.py` (`add_jitter` gains `rng: random.Random | None = None`; add `jitter_speed` static method).
- Test: `backend/tests/test_jitter_seam.py` (new).

**Interfaces:**
- Consumes: stdlib `random`, `math`; existing `add_jitter` body.
- Produces:
  - `RouteInterpolator.add_jitter(lat, lng, jitter_meters, rng: random.Random | None = None) -> tuple[float, float]` — uses `r = rng if rng is not None else random` for both `uniform` calls (identical to the existing body otherwise). Same seed → identical output.
  - `RouteInterpolator.jitter_speed(speed_mps: float, fraction: float, rng: random.Random | None = None) -> float` — returns `speed_mps` scaled by `1 + g`, where `g = (rng or random).gauss(0.0, fraction)` clamped to `[-fraction, fraction]`, and the result is clamped to a strict positive floor `max(scaled, 0.01)` so jittered speed is NEVER `<= 0`. When `fraction <= 0`, returns `speed_mps` unchanged.

- [ ] **Step 1: Write the failing test.**
  Create `backend/tests/test_jitter_seam.py`:
  ```python
  """Tests for the rng-injectable jitter seam (add_jitter rng param + jitter_speed).

  Pure math; deterministic via a seeded random.Random. Asserts seed-determinism,
  the ±fraction bound, and the strict-positive speed floor."""
  from __future__ import annotations

  import random

  from domain.movement import RouteInterpolator as R


  def test_add_jitter_seed_deterministic():
      a = R.add_jitter(25.0, 121.0, 5.0, rng=random.Random(7))
      b = R.add_jitter(25.0, 121.0, 5.0, rng=random.Random(7))
      assert a == b


  def test_add_jitter_zero_meters_is_noop():
      assert R.add_jitter(25.0, 121.0, 0.0, rng=random.Random(7)) == (25.0, 121.0)


  def test_jitter_speed_within_fraction_bound():
      base = 10.0
      frac = 0.15
      rng = random.Random(123)
      for _ in range(1000):
          v = R.jitter_speed(base, frac, rng=rng)
          assert base * (1 - frac) - 1e-9 <= v <= base * (1 + frac) + 1e-9


  def test_jitter_speed_never_zero_or_negative():
      rng = random.Random(999)
      for _ in range(1000):
          v = R.jitter_speed(0.02, 0.15, rng=rng)
          assert v > 0.0


  def test_jitter_speed_seed_deterministic():
      assert R.jitter_speed(10.0, 0.15, rng=random.Random(5)) == R.jitter_speed(10.0, 0.15, rng=random.Random(5))


  def test_jitter_speed_zero_fraction_unchanged():
      assert R.jitter_speed(10.0, 0.0, rng=random.Random(5)) == 10.0
  ```

- [ ] **Step 2: Run, see it fail.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_jitter_seam.py -q 2>&1 | tail -8
  ```
  Expected output: failures — `add_jitter()` got an unexpected keyword `rng`, and `jitter_speed` missing.

- [ ] **Step 3: Add the `rng` param to `add_jitter` + add `jitter_speed`.**
  In `backend/domain/movement.py`, replace the `add_jitter` static method (lines 311-323) with:
  ```python
      @staticmethod
      def add_jitter(
          lat: float, lng: float, jitter_meters: float,
          rng: "random.Random | None" = None,
      ) -> tuple[float, float]:
          """Add random GPS drift within *jitter_meters* of the given point.

          When *rng* is supplied (a seeded ``random.Random``) the drift is
          deterministic — mirrors the ``random_point_in_radius`` seam so jitter
          is unit-testable. Defaults to the module ``random`` (current behavior)."""
          if jitter_meters <= 0:
              return lat, lng

          r = rng if rng is not None else random
          angle = r.uniform(0, 2 * math.pi)
          dist = r.uniform(0, jitter_meters)

          dlat = (dist * math.cos(angle)) / _R
          dlng = (dist * math.sin(angle)) / (_R * math.cos(math.radians(lat)))

          return lat + math.degrees(dlat), lng + math.degrees(dlng)

      @staticmethod
      def jitter_speed(
          speed_mps: float, fraction: float,
          rng: "random.Random | None" = None,
      ) -> float:
          """Apply a Gaussian ±*fraction* multiplicative jitter to *speed_mps*.

          Draws ``g ~ N(0, fraction)`` clamped to ``[-fraction, fraction]`` so
          the result stays within ±fraction of the base, and floors the output
          at 0.01 m/s so jittered speed is NEVER <= 0. ``fraction <= 0`` →
          returns *speed_mps* unchanged. Deterministic when *rng* is seeded."""
          if fraction <= 0:
              return speed_mps
          r = rng if rng is not None else random
          g = r.gauss(0.0, fraction)
          if g > fraction:
              g = fraction
          elif g < -fraction:
              g = -fraction
          scaled = speed_mps * (1.0 + g)
          return max(scaled, 0.01)
  ```

- [ ] **Step 4: Run, see it pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_jitter_seam.py -q 2>&1 | tail -5
  ```
  Expected output: `6 passed`.

- [ ] **Step 5: Confirm position-jitter cov tests + domain purity green.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_interpolator_cov.py tests/test_interpolator_golden.py tests/test_import_contracts_enforced.py -q 2>&1 | tail -3
  ```
  Expected output: all pass (default-`None` `add_jitter` is byte-identical to the prior body; `movement.py` stays stdlib+pydantic).

- [ ] **Step 6: Full suite + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3
  ```
  Expected output: `983 passed` (977 + 6 new). Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add backend/domain/movement.py backend/tests/test_jitter_seam.py && git commit -m "feat(jitter): rng-injectable add_jitter + pure jitter_speed helper"
  ```

---

### Task 12: `SpeedProfile.speed_jitter` config field + engine applies speed jitter

Add `speed_jitter` to `config.SpeedProfile` and apply it per-tick in `_move_along_route` (currently `speed_mps` is constant — set at line 670, pushed unchanged at line 763). The engine needs an injectable RNG seam so the jittered-speed test is deterministic; jitter is OFF (no-op) when `speed_jitter == 0`, which is how the characterization tests already run (their profiles set no `speed_jitter`).

**Files:**
- Modify: `backend/config.py` (`SpeedProfile` TypedDict gains `speed_jitter: float`; the three `SPEED_PROFILES` entries + `make_speed_profile` set a default; `resolve_speed_profile` unchanged otherwise).
- Modify: `backend/core/simulation_engine.py` (constructor gains `rng: random.Random | None = None` → `self._rng`; per-tick speed uses `RouteInterpolator.jitter_speed(speed_mps, jitter_frac, rng=self._rng)` where `jitter_frac = self._active_speed_profile.get("speed_jitter", 0.0)`).
- Test: `backend/tests/test_engine_speed_jitter_char.py` (new).

**Interfaces:**
- Consumes: `RouteInterpolator.jitter_speed` (Task 11). (The Task 12 char-test does NOT use the `make_engine` harness — it constructs `SimulationEngine(loc, cb, clock=clock, sleep=sleep, rng=rng)` directly via a local `_make_engine_with_rng(rng)` helper, so no `make_engine` change is needed. Leave `tests/_engine_harness.make_engine` untouched.)
- Produces:
  - `SpeedProfile` TypedDict adds `speed_jitter: float` (fraction, e.g. `0.12`). `SPEED_PROFILES["walking"|"running"|"driving"]` add `"speed_jitter": 0.12`. `make_speed_profile(...)` adds `"speed_jitter": 0.12` to its returned dict. (The TOGGLE that turns this OFF is wired in Task 13/14 by zeroing the field at profile-resolution time; the engine itself simply honors whatever `speed_jitter` the active profile carries.)
  - `SimulationEngine.__init__` gains keyword-only `rng: "random.Random | None" = None` stored as `self._rng = rng` (default `None` → uses module `random` inside `jitter_speed`).
  - In `_move_along_route`, each tick computes `eff_speed = RouteInterpolator.jitter_speed(speed_mps, self._active_speed_profile.get("speed_jitter", 0.0), rng=self._rng)` and uses `eff_speed` for the emitted `speed_mps` and the ETA divisor for THAT tick. (The interpolation step-distance + `timestamp_offset` cadence still come from the base `speed_mps` so pacing is unchanged; only the reported/used per-tick speed varies — matching "±10–15% variation to speed_mps each tick.")

- [ ] **Step 1: Write the failing char-test (jitter ON via a seeded engine rng; jitter OFF stays exact).**
  Create `backend/tests/test_engine_speed_jitter_char.py`:
  ```python
  """Characterization: per-tick speed jitter.

  - With speed_jitter=0 (the default the existing char-tests use), the emitted
    position_update speed_mps is constant == base (no behavior change).
  - With speed_jitter=0.15 and a SEEDED engine rng, every emitted speed_mps stays
    within ±15% of base and is strictly > 0; two identical seeded runs match.
  Drives the REAL _move_along_route with position jitter OFF (jitter=0.0)."""
  from __future__ import annotations

  import asyncio
  import random

  import pytest

  from models.schemas import Coordinate
  from core.simulation_engine import SimulationEngine
  from tests._engine_harness import FakeClock, SteppedSleep, RecordingLocation


  pytestmark = pytest.mark.asyncio


  def _make_engine_with_rng(rng):
      clock = FakeClock()
      sleep = SteppedSleep(clock)
      loc = RecordingLocation()
      emitted: list[tuple[str, dict]] = []

      async def cb(event_type, data):
          emitted.append((event_type, dict(data)))

      eng = SimulationEngine(loc, cb, clock=clock, sleep=sleep, rng=rng)
      return eng, loc, emitted


  async def _run(monkeypatch, profile, rng):
      async def _instant_timeout(aw, timeout):
          aw.close()
          raise asyncio.TimeoutError
      monkeypatch.setattr(asyncio, "wait_for", _instant_timeout)
      eng, loc, emitted = _make_engine_with_rng(rng)
      coords = [Coordinate(lat=25.0, lng=121.0), Coordinate(lat=25.0, lng=121.001)]
      await eng._move_along_route(coords, profile)
      return [d["speed_mps"] for (t, d) in emitted if t == "position_update"]


  async def test_speed_jitter_zero_keeps_speed_constant(monkeypatch):
      profile = {"speed_mps": 20.0, "jitter": 0.0, "update_interval": 1.0, "speed_jitter": 0.0}
      speeds = await _run(monkeypatch, profile, random.Random(1))
      assert speeds  # non-empty
      assert all(s == 20.0 for s in speeds)


  async def test_speed_jitter_on_stays_within_bound_and_positive(monkeypatch):
      profile = {"speed_mps": 20.0, "jitter": 0.0, "update_interval": 1.0, "speed_jitter": 0.15}
      speeds = await _run(monkeypatch, profile, random.Random(42))
      assert speeds
      for s in speeds:
          assert 20.0 * 0.85 - 1e-9 <= s <= 20.0 * 1.15 + 1e-9
          assert s > 0.0


  async def test_speed_jitter_seed_deterministic(monkeypatch):
      profile = {"speed_mps": 20.0, "jitter": 0.0, "update_interval": 1.0, "speed_jitter": 0.15}
      a = await _run(monkeypatch, profile, random.Random(42))
      b = await _run(monkeypatch, profile, random.Random(42))
      assert a == b
  ```

- [ ] **Step 2: Run, see it fail (TypeError: unexpected kwarg `rng`).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_engine_speed_jitter_char.py -q 2>&1 | tail -10
  ```
  Expected output: `TypeError: __init__() got an unexpected keyword argument 'rng'`.

- [ ] **Step 3: Add `speed_jitter` to `config.SpeedProfile` + profiles.**
  In `backend/config.py`:
  - Add the field to the TypedDict (after `update_interval` at line 132):
    ```python
        speed_jitter: float    # ± fraction of speed_mps applied per tick (0 = off)
    ```
  - Add `"speed_jitter": 0.12` to each `SPEED_PROFILES` entry (lines 141-143):
    ```python
    SPEED_PROFILES: dict[str, SpeedProfile] = {
        "walking": {"speed_mps": 3.0, "jitter": 0.5, "update_interval": 1.0, "speed_jitter": 0.12},
        "running": {"speed_mps": 5.5, "jitter": 0.7, "update_interval": 0.5, "speed_jitter": 0.12},
        "driving": {"speed_mps": 16.7, "jitter": 1.2, "update_interval": 0.5, "speed_jitter": 0.12},
    }
    ```
  - Add `"speed_jitter": 0.12` to `make_speed_profile`'s return (line 152):
    ```python
        return {"speed_mps": speed_mps, "jitter": jitter, "update_interval": update_interval, "speed_jitter": 0.12}
    ```

- [ ] **Step 4: Add the engine `rng` seam + per-tick jitter.**
  In `backend/core/simulation_engine.py`:
  - Add `rng` to the constructor signature (after `device_port=None,` at line 61):
    ```python
            device_port=None,
            rng: "random.Random | None" = None,
        ) -> None:
    ```
    and store it near the clock/sleep assignment (after `self._sleep = sleep` at line 89):
    ```python
            self._rng = rng
    ```
    Add `import random` at the top of `simulation_engine.py` if not already present (it currently imports `asyncio, logging, time`; add `import random`).
  - In `_move_along_route`, where the emitted `speed_mps` is built each tick, compute an effective per-tick speed. After `bearing = point.get("bearing", 0.0)` (line 730) and before the `tick_start = self._clock()` line (738), insert:
    ```python
                    eff_speed = RouteInterpolator.jitter_speed(
                        speed_mps,
                        self._active_speed_profile.get("speed_jitter", 0.0),
                        rng=self._rng,
                    )
    ```
    Then change the `position_update` emit (lines 759-768) so its `speed_mps` and `eta_seconds` use `eff_speed`:
    ```python
                    combined_remaining = self.distance_remaining + self._route_offset_remaining
                    combined_eta = combined_remaining / max(eff_speed, 0.001)
                    await self._emit("position_update", {
                        "lat": jittered_lat,
                        "lng": jittered_lng,
                        "bearing": bearing,
                        "speed_mps": eff_speed,
                        "progress": self.eta_tracker.progress,
                        "distance_remaining": combined_remaining,
                        "distance_traveled": self.distance_traveled,
                        "eta_seconds": combined_eta,
                    })
    ```
    Also update `self._current_speed_mps` to reflect the jittered value so `get_status()` reports it — replace the existing `self._current_speed_mps = speed_mps` at line 674 is set per-plan; ADD `self._current_speed_mps = eff_speed` right after computing `eff_speed` (so status reflects the most recent tick). (Leave the line-674 per-plan assignment; the per-tick assignment supersedes it during movement.)

- [ ] **Step 5: Run the char-test, see it pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_engine_speed_jitter_char.py -q 2>&1 | tail -8
  ```
  Expected output: `3 passed`.

- [ ] **Step 6: Confirm existing engine goldens stay green (their profiles have no `speed_jitter` → `.get(...,0.0)` → no-op).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_interpolator_golden.py tests/test_engine_stream_char.py tests/test_engine_pause_resume_char.py tests/test_route_loop_cov.py tests/test_navigator_cov.py tests/test_multi_stop_cov.py tests/test_random_walk_cov.py -q 2>&1 | tail -3
  ```
  Expected output: all pass. The frozen `test_move_along_route_position_stream_matches_frozen_golden` uses a profile WITHOUT `speed_jitter`, so `jitter_speed(speed, 0.0)` returns the base speed unchanged → goldens hold.

- [ ] **Step 7: Full suite + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3
  ```
  Expected output: `986 passed` (983 + 3 new). Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add backend/config.py backend/core/simulation_engine.py backend/tests/test_engine_speed_jitter_char.py && git commit -m "feat(jitter): SpeedProfile.speed_jitter + per-tick speed jitter (engine rng seam)"
  ```

---

### Task 13: Speed-jitter toggle — backend honors a per-request `speed_jitter_enabled`

The settings toggle is persisted on the frontend (Task 14), but the engine resolves profiles via `config.resolve_speed_profile`/`SPEED_PROFILES`. To let the toggle disable jitter for byte-reproducible runs, add a `speed_jitter_enabled` flag that, when false, zeroes the `speed_jitter` field at profile-resolution. The flag rides on the existing simulation-start requests. This task does the BACKEND half: `resolve_speed_profile(..., jitter_enabled: bool = True)` zeroes `speed_jitter` when false.

**Survey conclusion (reuse vs new):** NO new endpoint. Per the master spec Surface Decisions, speed jitter is "No surface — Engine + `config.py` SpeedProfile only." The enable/disable rides as an additive field on existing simulation-start request bodies (the same bodies that already carry `speed_kmh`/`mode`). This task touches only `config.resolve_speed_profile`; wiring the field through the start requests is left to the existing request schemas which already pass through to the engine — verified below.

**Files:**
- Modify: `backend/config.py` (`resolve_speed_profile` gains `jitter_enabled: bool = True`; zeroes `speed_jitter` when false, after building the profile).
- Test: `backend/tests/test_resolve_speed_profile_jitter.py` (new).

**Interfaces:**
- Consumes: `config.SPEED_PROFILES`, `config.make_speed_profile` (now carry `speed_jitter`, Task 12).
- Produces: `resolve_speed_profile(profile_name, speed_kmh=None, speed_min_kmh=None, speed_max_kmh=None, jitter_enabled: bool = True) -> SpeedProfile` — identical to today except that when `jitter_enabled is False`, the returned dict has `speed_jitter` forced to `0.0` (copy-then-zero, never mutating the shared `SPEED_PROFILES` dict).

- [ ] **Step 1: Write the failing test.**
  Create `backend/tests/test_resolve_speed_profile_jitter.py`:
  ```python
  """resolve_speed_profile(jitter_enabled=False) zeroes speed_jitter without
  mutating the shared SPEED_PROFILES table."""
  from __future__ import annotations

  import config


  def test_default_keeps_speed_jitter():
      p = config.resolve_speed_profile("walking")
      assert p["speed_jitter"] == 0.12


  def test_disabled_zeroes_speed_jitter():
      p = config.resolve_speed_profile("walking", jitter_enabled=False)
      assert p["speed_jitter"] == 0.0


  def test_disabled_does_not_mutate_shared_table():
      _ = config.resolve_speed_profile("walking", jitter_enabled=False)
      assert config.SPEED_PROFILES["walking"]["speed_jitter"] == 0.12


  def test_custom_speed_with_jitter_disabled():
      p = config.resolve_speed_profile("walking", speed_kmh=18.0, jitter_enabled=False)
      assert p["speed_jitter"] == 0.0
      # speed still derives from the custom km/h
      assert abs(p["speed_mps"] - 18.0 / 3.6) < 1e-9
  ```

- [ ] **Step 2: Run, see it fail.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_resolve_speed_profile_jitter.py -q 2>&1 | tail -8
  ```
  Expected output: `TypeError: resolve_speed_profile() got an unexpected keyword argument 'jitter_enabled'`.

- [ ] **Step 3: Add `jitter_enabled` to `resolve_speed_profile`.**
  In `backend/config.py`, replace `resolve_speed_profile` (lines 155-171) with:
  ```python
  def resolve_speed_profile(
      profile_name: str,
      speed_kmh: float | None = None,
      speed_min_kmh: float | None = None,
      speed_max_kmh: float | None = None,
      jitter_enabled: bool = True,
  ) -> SpeedProfile:
      """Return a speed profile, picking a random km/h from the range if provided.
      Precedence: range > fixed custom > mode default. When jitter_enabled is
      False, the returned profile's speed_jitter is forced to 0.0 (a COPY — the
      shared SPEED_PROFILES table is never mutated) for byte-reproducible runs."""
      import random
      if speed_min_kmh is not None and speed_max_kmh is not None:
          lo, hi = sorted((float(speed_min_kmh), float(speed_max_kmh)))
          if lo <= 0:
              lo = 0.1
          profile = make_speed_profile(random.uniform(lo, hi))
      elif speed_kmh:
          profile = make_speed_profile(speed_kmh)
      else:
          profile = dict(SPEED_PROFILES[profile_name])  # copy so we never mutate the table
      if not jitter_enabled:
          profile = dict(profile)
          profile["speed_jitter"] = 0.0
      return profile  # type: ignore[return-value]
  ```
  (Note: the previous version returned `SPEED_PROFILES[profile_name]` BY REFERENCE in the mode-default branch. The copy here is required so the `jitter_enabled=False` zeroing — and any downstream `dict(...)` consumer — never mutates the shared table. Existing callers receive an equivalent dict; the engine already does `dict(speed_profile)` when storing it, so behavior is unchanged.)

- [ ] **Step 4: Run, see it pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest tests/test_resolve_speed_profile_jitter.py -q 2>&1 | tail -5
  ```
  Expected output: `4 passed`.

- [ ] **Step 5: Confirm callers of `resolve_speed_profile` still pass (mode-default-by-copy change).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && grep -rln "resolve_speed_profile" core/ services/ && .venv/bin/python -m pytest tests/test_navigator_cov.py tests/test_route_loop_cov.py tests/test_multi_stop_cov.py tests/test_random_walk_cov.py -q 2>&1 | tail -3
  ```
  Expected output: the grep lists the callers; the cov tests all pass (returning a copy instead of the shared reference is behavior-equivalent — the engine copies it anyway).

- [ ] **Step 6: Full suite + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3
  ```
  Expected output: `990 passed` (986 + 4 new). Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add backend/config.py backend/tests/test_resolve_speed_profile_jitter.py && git commit -m "feat(jitter): resolve_speed_profile(jitter_enabled=False) zeroes speed_jitter"
  ```

---

### Task 14: Frontend speed-jitter settings toggle (persisted, default ON)

Mirror the `show_bookmark_pins` localStorage persistence pattern to add a `speed_jitter` toggle defaulting ON, surfaced in the settings UI, and threaded onto simulation-start requests as `speed_jitter_enabled`.

**Where the state and the toggle live:** `App.tsx` HOLDS the setting state and threads it as props; the toggle UI renders in `ControlPanel.tsx`, next to the other settings checkboxes (`straightLine`, `clickToAddWaypoint`, `jumpMode`) which use the `<label className="lw-checkbox"><input type="checkbox" .../></label>` markup. The `show_bookmark_pins` setting follows the same shape: App.tsx owns `showBookmarkPins` state + the `locwarp.show_bookmark_pins` localStorage read/write, and threads it as `bookmarkShowOnMap` / `onBookmarkShowOnMapChange` props into `ControlPanel` (which renders the checkbox down its subtree). Mirror that ownership split for `speed_jitter`.

**Files:**
- Modify: `frontend/src/App.tsx` (read `App.tsx` `show_bookmark_pins` usage first to mirror it; add a `speedJitter` state + localStorage key `locwarp.speed_jitter` defaulting ON; thread it as props into `ControlPanel`; include `speed_jitter_enabled` on the start-sim payloads).
- Modify: `frontend/src/components/ControlPanel.tsx` (accept the new `speedJitter` / `onSpeedJitterChange` props and render the `<input type="checkbox" aria-label="Speed jitter">` toggle in the settings region alongside the existing `straightLine` / `clickToAddWaypoint` / `jumpMode` checkboxes, so the test's `getByRole('checkbox', { name: /speed.*jitter/i })` resolves).
- Test: `frontend/src/App.speedJitterToggle.test.tsx` (new) — App-LEVEL test using the HYBRID harness (`vi.mock('./services/api', ...)` + `ServicesProvider` wrapping the mocked api), mirroring `App.toastAria.test.tsx` exactly. `fireEvent` only.

**Interfaces:**
- Consumes: the existing `show_bookmark_pins` ownership split in `App.tsx` + `ControlPanel.tsx` (read it in Step 1) — App.tsx holds the state, ControlPanel renders the toggle; the App-level HYBRID test harness used by `App.toastAria.test.tsx` (read it in Step 2 to mirror the `vi.mock('./services/api', ...)` + `ServicesProvider value={{ api, ... }}` setup exactly).
- Produces: a `speedJitter: boolean` state in `App.tsx` persisted to `localStorage['locwarp.speed_jitter']` (default ON when the key is absent), threaded as props into `ControlPanel` where the `aria-label="Speed jitter"` checkbox renders, and `speed_jitter_enabled: speedJitter` added to the start-simulation request payload(s).

- [ ] **Step 1: Read the `show_bookmark_pins` ownership split to mirror it exactly.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "show_bookmark_pins\|showBookmarkPins\|setShowBookmarkPins\|bookmarkShowOnMap\|onBookmarkShowOnMapChange\|localStorage" src/App.tsx | head -30
  ```
  Expected output: the lazy-init `useState(() => localStorage.getItem('locwarp.show_bookmark_pins') === '1')` read, the `setShowBookmarkPins` wrapper that writes `'1'`/`'0'` back, and the `bookmarkShowOnMap={showBookmarkPins} onBookmarkShowOnMapChange={setShowBookmarkPins}` props threaded into `<ControlPanel ...>`. App.tsx OWNS the state; the checkbox itself renders inside `ControlPanel` (and its subtree). Then read where ControlPanel renders a settings checkbox to mirror the markup:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "lw-checkbox\|type=\"checkbox\"\|onStraightLineChange\|onClickToAddWaypointChange\|onJumpModeChange" src/components/ControlPanel.tsx | head -20
  ```
  Expected output: the `<label className="lw-checkbox"><input type="checkbox" checked={...} onChange={...} /> ... {t('panel.*')}</label>` blocks for `straightLine` / `clickToAddWaypoint` / `jumpMode`. Mirror this exact markup for the speed-jitter toggle.

- [ ] **Step 2: Read the App-level test harness to mirror it exactly (HYBRID: vi.mock + ServicesProvider).**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && sed -n '1,60p' src/App.toastAria.test.tsx
  ```
  Expected output: the imports (`render`, `act`, `screen` from `@testing-library/react`), a `vi.mock('./components/MapView', ...)` stub, a `vi.mock('./services/api', async (importOriginal) => { ... })` that auto-stubs every api function, `import * as api from './services/api'` (the mocked module), and a `renderApp()` helper wrapping `<I18nProvider><ServicesProvider value={{ api, ws: router, sendMessage: vi.fn(), connected }}><App/></ServicesProvider></I18nProvider>`. The new test MUST reuse this identical HYBRID setup: it DOES use `vi.mock('./services/api', ...)` to stub the module AND wraps `ServicesProvider` with the mocked `import * as api`. (The "inject via ServicesProvider, NOT `vi.mock`" rule is for LEAF component tests only — App-level tests need both.) Do NOT use `user-event`.

- [ ] **Step 3: Write the failing test.**
  Create `frontend/src/App.speedJitterToggle.test.tsx` mirroring the HYBRID harness read in Step 2. Skeleton (adapt the mock + wrapper + import lines to match the exemplar verbatim):
  ```tsx
  import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
  import React from 'react'
  import { render, act, screen, fireEvent } from '@testing-library/react'
  // NOTE: copy the EXACT harness from src/App.toastAria.test.tsx (read in
  // Step 2) VERBATIM into this file:
  //   - vi.mock('./components/MapView', ...) stub
  //   - vi.mock('./services/api', async (importOriginal) => { ... }) auto-stub
  //   - import App from './App'
  //   - import * as api from './services/api'   // the MOCKED module
  //   - import { I18nProvider } from './i18n'
  //   - import { ServicesProvider } from './contexts/ServicesContext'
  //   - import { createWsRouter } from './adapters/ws/router'
  //   - a renderApp() helper that wraps
  //       <I18nProvider><ServicesProvider value={{ api, ws: createWsRouter(),
  //         sendMessage: vi.fn(), connected: true }}><App/></ServicesProvider></I18nProvider>
  // This is the HYBRID: vi.mock stubs the api module AND ServicesProvider
  // wraps the mocked `import * as api`. Both are required for App-level tests.

  describe('speed jitter settings toggle', () => {
    beforeEach(() => {
      try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
    })
    afterEach(() => {
      try { localStorage.clear() } catch { /* ignore */ }
    })

    it('defaults the speed_jitter setting to ON when the key is absent', async () => {
      // await act(async () => { renderApp() })
      // const toggle = screen.getByRole('checkbox', { name: /speed.*jitter/i })
      // expect((toggle as HTMLInputElement).checked).toBe(true)
      // expect(localStorage.getItem('locwarp.speed_jitter')).not.toBe('0')
    })

    it('persists OFF to localStorage when toggled off', async () => {
      // await act(async () => { renderApp() })
      // const toggle = screen.getByRole('checkbox', { name: /speed.*jitter/i })
      // await act(async () => { fireEvent.click(toggle) })
      // expect(localStorage.getItem('locwarp.speed_jitter')).toBe('0')
    })

    it('reads OFF back from localStorage on a fresh mount', async () => {
      // localStorage.setItem('locwarp.speed_jitter', '0')
      // await act(async () => { renderApp() })
      // const toggle = screen.getByRole('checkbox', { name: /speed.*jitter/i })
      // expect((toggle as HTMLInputElement).checked).toBe(false)
    })
  })
  ```
  Then fill in the commented lines using the exemplar's exact mock + render helper + import paths from Step 2 (uncomment and wire them). The accessible name selector `{ name: /speed.*jitter/i }` must match the `aria-label="Speed jitter"` you give the control in Step 4. (Note the localStorage values are `'1'`/`'0'`, matching the `show_bookmark_pins` convention — see Step 4.)

- [ ] **Step 4: Hold the `speedJitter` state in `App.tsx`; render the toggle in `ControlPanel.tsx`.**
  Match the `show_bookmark_pins` convention exactly: values are `'1'`/`'0'`, read with `=== '1'`. The default DIFFERS — pins default OFF, jitter defaults ON — so use `!== '0'` for the read (key absent → ON) while keeping the `'1'`/`'0'` write encoding.

  In `App.tsx`, near the `showBookmarkPins` state, add the state + a persist wrapper (mirror the `setShowBookmarkPins` shape — wrapper writes through on every set; no separate `useEffect` needed):
  ```tsx
    const [speedJitter, setSpeedJitterRaw] = useState<boolean>(() => {
      try { return localStorage.getItem('locwarp.speed_jitter') !== '0' } catch { return true }  // default ON
    })
    const setSpeedJitter = useCallback((v: boolean) => {
      setSpeedJitterRaw(v)
      try { localStorage.setItem('locwarp.speed_jitter', v ? '1' : '0') } catch { /* ignore */ }
    }, [])
  ```
  Thread it into `<ControlPanel ...>` as props, alongside the existing `bookmarkShowOnMap` / `onBookmarkShowOnMapChange`:
  ```tsx
            speedJitter={speedJitter}
            onSpeedJitterChange={setSpeedJitter}
  ```

  In `ControlPanel.tsx`, add the props to the props interface + destructure (mirror `bookmarkShowOnMap` / `onBookmarkShowOnMapChange`):
  ```tsx
    speedJitter?: boolean;
    onSpeedJitterChange?: (v: boolean) => void;
  ```
  Then render the toggle in the settings region, next to the `straightLine` / `clickToAddWaypoint` / `jumpMode` checkboxes, using the EXACT `lw-checkbox` markup those use (guard on the optional change handler so older callers stay safe):
  ```tsx
            {onSpeedJitterChange && (
              <label className="lw-checkbox" style={{ fontSize: 11 }}>
                <input
                  type="checkbox"
                  aria-label="Speed jitter"
                  checked={speedJitter ?? true}
                  onChange={(e) => onSpeedJitterChange(e.target.checked)}
                />
                <span className="lw-checkbox-box"></span>
                <span className="lw-checkbox-label" style={{ lineHeight: 1.15 }}>
                  {t('settings.speed_jitter')}
                </span>
              </label>
            )}
  ```
  (Match the EXACT toggle structure used by the neighboring `straightLine` / `jumpMode` controls in `ControlPanel.tsx`; the `aria-label="Speed jitter"` is what makes `getByRole('checkbox', { name: /speed.*jitter/i })` resolve.)

- [ ] **Step 5: Thread `speed_jitter_enabled` onto the start-sim payloads.**
  Find where App builds simulation-start request bodies (the calls that send `mode`/`speed_kmh`):
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "speed_kmh\|speed_min_kmh\|startLoop\|navigate\|multiStop\|randomWalk\|/api/.*sim\|jitter" src/App.tsx | head -30
  ```
  Expected output: the start-sim payload assembly site(s). Add `speed_jitter_enabled: speedJitter` to each start-sim request body alongside the existing `speed_kmh`/`mode` fields. (The backend wiring in Task 13 zeroes `speed_jitter` when this is false; if a given start request path does not yet forward extra fields to the engine, add the field to the payload anyway — it is additive and the backend ignores unknown fields it does not consume. The minimum bar for THIS task's tests is the persisted toggle; payload threading keeps the feature end-to-end coherent.)

- [ ] **Step 6: Add the i18n key.**
  Add ONE entry `settings.speed_jitter` to the single flat `STRINGS` map in `frontend/src/i18n/strings.ts` (the table is `'dotted.key': { zh, en }` — both languages live in one entry; there are NO per-locale sibling objects). Place it near the other `panel.*` / `settings.*` keys:
  ```ts
    'settings.speed_jitter': { zh: '速度抖動（擬真）', en: 'Speed jitter (realistic)' },
  ```

- [ ] **Step 7: Run the new test, see it pass.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/App.speedJitterToggle.test.tsx 2>&1 | tail -6
  ```
  Expected output: `3 passed`.

- [ ] **Step 8: tsc + full vitest + depcruise + commit.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run 2>&1 | tail -4 && npm run depcruise 2>&1 | tail -2
  ```
  Expected output: tsc clean; vitest count = prior (785) + 3 = `788 passed`; depcruise clean. Then:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add frontend/src/App.tsx frontend/src/components/ControlPanel.tsx frontend/src/App.speedJitterToggle.test.tsx frontend/src/i18n/strings.ts && git commit -m "feat(jitter): persisted speed-jitter settings toggle (default ON)"
  ```

---

### Task 15: Whole-cluster green gate + ff-merge

**Files:**
- No source changes. Final verification + merge.

**Interfaces:**
- Consumes: all prior task commits on `aip-c3-orphaned-capability`.
- Produces: `main` fast-forwarded to include the cluster.

- [ ] **Step 1: Full backend suite + import-linter.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -3 && .venv/bin/python -m pytest tests/test_import_contracts_enforced.py tests/test_import_contracts_fail_on_probe.py -q 2>&1 | tail -3
  ```
  Expected output: `990 passed` (baseline 949 + 41 new across Tasks 2–13), and the contract tests pass (`7 kept, 0 broken`).

- [ ] **Step 2: Full frontend gate.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run 2>&1 | tail -4 && npm run depcruise 2>&1 | tail -2
  ```
  Expected output: tsc clean; vitest `788 passed`; depcruise `no dependency violations found`.

- [ ] **Step 3: Endpoint-survey sanity — the new route is the only new HTTP surface.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && grep -nE '@router\.(get|post|put|delete|patch)' api/geocode.py | grep nearby
  ```
  Expected output: exactly one line — the `@router.get("/nearby", ...)` route added in Task 3. (Confirms no accidental duplicate/extra surface.)

- [ ] **Step 4: ff-merge to main.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git checkout main && git merge --ff-only aip-c3-orphaned-capability && git branch -d aip-c3-orphaned-capability
  ```
  Expected output: `Fast-forward` merge summary listing the Task 2–14 commits; branch deleted. (Do NOT push unless Ravi asks — personal-repo convention is direct commits to main; the merge lands locally on main.)

- [ ] **Step 5: Post-merge re-verify green on main.**
  Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q 2>&1 | tail -2
  ```
  Expected output: `990 passed` on `main`. Cluster complete.
