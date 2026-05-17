# History Menu Stay-Open + Offline Reverse-Geocode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the "Recent destinations" dropdown from closing when the context menu opens (right-click row / `⋮` click), and make the backend `/api/geocode/reverse` endpoint fall back to the offline geo DB when Nominatim is unreachable so "What's here?" never surfaces a 500 to the user.

**Architecture:** Two unrelated bugfixes packaged together because they sit in the same UX area. (1) Frontend: delete one line in MapView's `openMenuAt` helper. (2) Backend: wrap `geocoding_service.reverse(...)` in `try/except` inside the `/reverse` handler; on failure, compose a `GeocodingResult` from `geo_offline.resolve(lat, lng)` (which returns `(country_code, timezone, city, region)`). TDD: write a failing pytest exercising the fallback path before implementing the handler change.

**Tech Stack:** React 18 + TypeScript + Vite (`frontend/`). Python 3.13 + FastAPI + pytest (`backend/`). No tests in frontend; backend uses pytest.

**Spec:** `docs/superpowers/specs/2026-05-17-history-menu-stay-open-and-offline-reverse-geocode-design.md` (commit `03aea2c`).

---

## File Structure

| File | Why it changes |
|------|----------------|
| `frontend/src/components/MapView.tsx` | Line 2346: drop `setRecentOpen(false)` inside the `openMenuAt` helper so opening the context menu no longer dismisses the dropdown. |
| `backend/api/geocode.py` | `reverse_geocode` handler gains a `try/except`-and-fallback block. Adds `from services import geo_offline` to existing import list. |
| `backend/tests/test_geocode_api.py` | NEW file with two pytest cases that monkeypatch `geocoding_service.reverse` to raise and assert the handler returns the offline composition (or `None` if offline DB is empty). |

---

## Task 1: Stop dismissing the dropdown when the context menu opens

**Files:**
- Modify: `frontend/src/components/MapView.tsx:2338-2347`

Single-line removal inside the `openMenuAt` helper.

- [ ] **Step 1: Locate the helper**

In `frontend/src/components/MapView.tsx`, find the block at lines 2338–2347 (search for `const openMenuAt = (x: number, y: number) =>`):

```tsx
                  const openMenuAt = (x: number, y: number) => {
                    setContextMenu({
                      visible: true,
                      x, y,
                      lat: entry.lat,
                      lng: entry.lng,
                      name: entry.name || undefined,
                    });
                    setRecentOpen(false);
                  };
```

- [ ] **Step 2: Remove `setRecentOpen(false)`**

Delete the line `setRecentOpen(false);` (line 2346). The block becomes:

```tsx
                  const openMenuAt = (x: number, y: number) => {
                    setContextMenu({
                      visible: true,
                      x, y,
                      lat: entry.lat,
                      lng: entry.lng,
                      name: entry.name || undefined,
                    });
                  };
```

Do NOT touch `setRecentOpen(false)` elsewhere — the left-click re-fly path at `MapView.tsx:2371` should still close the dropdown because the user has navigated away.

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output.

- [ ] **Step 4: Production build (sanity)**

```bash
cd frontend && npm run build
```

Expected: `✓ built in <time>s`. Pre-existing dynamic-import warning unchanged.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MapView.tsx
git commit -m "fix(map): keep history dropdown open when context menu is shown"
```

---

## Task 2: Backend offline fallback for reverse-geocode

This task uses TDD: write failing tests first, then implement.

**Files:**
- Create: `backend/tests/test_geocode_api.py`
- Modify: `backend/api/geocode.py`

The backend already imports `logger`, `GeocodingResult`, `logging` (verified at `backend/api/geocode.py:1-12, 25`). Only `geo_offline` is a new import.

### Step group A: Write the failing test

- [ ] **Step A1: Create the test file**

Create `backend/tests/test_geocode_api.py` with the following contents:

```python
"""Tests for /api/geocode/reverse fallback to offline DB when Nominatim fails."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


def test_reverse_falls_back_to_offline_when_nominatim_raises(monkeypatch, client):
    """When the upstream Nominatim call throws, the handler must compose
    a GeocodingResult from the offline DB instead of returning HTTP 500.
    """
    import services.geocoding as geo_svc

    async def boom(_lat, _lng):
        raise RuntimeError("simulated Nominatim outage")

    monkeypatch.setattr(geo_svc.geocoding_service, "reverse", boom)

    # Tokyo Tower coordinates — the offline DB has Japan / Tokyo data.
    res = client.get("/api/geocode/reverse", params={"lat": 35.6586, "lng": 139.7454})
    assert res.status_code == 200
    body = res.json()
    assert body is not None
    assert body["country_code"] == "jp"
    assert "Tokyo" in body["display_name"]
    assert body["short_name"]  # non-empty
    assert body["lat"] == pytest.approx(35.6586)
    assert body["lng"] == pytest.approx(139.7454)


def test_reverse_returns_none_when_nominatim_raises_and_offline_empty(monkeypatch, client):
    """If both Nominatim and the offline DB have nothing, the handler
    returns ``null`` (HTTP 200) rather than raising — the frontend
    already handles the null path with the "no address found" message.
    """
    import services.geocoding as geo_svc
    import services.geo_offline as geo_offline

    async def boom(_lat, _lng):
        raise RuntimeError("simulated Nominatim outage")

    monkeypatch.setattr(geo_svc.geocoding_service, "reverse", boom)
    monkeypatch.setattr(geo_offline, "resolve", lambda _lat, _lng: ("", "", "", ""))

    res = client.get("/api/geocode/reverse", params={"lat": 0, "lng": 0})
    assert res.status_code == 200
    assert res.json() is None


def test_reverse_returns_nominatim_result_when_nominatim_succeeds(monkeypatch, client):
    """Happy path: Nominatim returns a result, the handler returns it
    unchanged. (Regression guard against the fallback short-circuiting
    on a successful call.)
    """
    import services.geocoding as geo_svc
    from models.schemas import GeocodingResult

    async def ok(_lat, _lng):
        return GeocodingResult(
            display_name="Real street, Real district, Real country",
            lat=35.6586,
            lng=139.7454,
            country_code="jp",
            short_name="Real POI",
        )

    monkeypatch.setattr(geo_svc.geocoding_service, "reverse", ok)

    res = client.get("/api/geocode/reverse", params={"lat": 35.6586, "lng": 139.7454})
    assert res.status_code == 200
    body = res.json()
    assert body["display_name"] == "Real street, Real district, Real country"
    assert body["short_name"] == "Real POI"
```

- [ ] **Step A2: Run the tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_geocode_api.py -v
```

Expected:
- `test_reverse_falls_back_to_offline_when_nominatim_raises` — FAIL (handler currently does not catch, returns 500)
- `test_reverse_returns_none_when_nominatim_raises_and_offline_empty` — FAIL (same reason)
- `test_reverse_returns_nominatim_result_when_nominatim_succeeds` — PASS (this is the existing behaviour, regression guard)

If `test_reverse_returns_nominatim_result_when_nominatim_succeeds` fails, stop — it would mean the existing path is broken before our change.

### Step group B: Implement the handler change

- [ ] **Step B1: Add the `geo_offline` import**

In `backend/api/geocode.py`, find the existing `from services...` import block (around line 13–17 area):

```python
from services.geocoding import GeocodingService
from services.geo_extras import (
    _HAVERSINE_PROFILE_SPEED_MPS,
```

Add a new import line immediately above the `geocoding` import (preserving alphabetical-ish grouping):

```python
from services import geo_offline
from services.geocoding import GeocodingService
from services.geo_extras import (
    _HAVERSINE_PROFILE_SPEED_MPS,
```

- [ ] **Step B2: Replace the `reverse_geocode` handler**

Find the existing handler at `backend/api/geocode.py:46-48`:

```python
@router.get("/reverse", response_model=GeocodingResult | None)
async def reverse_geocode(lat: float, lng: float):
    return await geocoding_service.reverse(lat, lng)
```

Replace with:

```python
@router.get("/reverse", response_model=GeocodingResult | None)
async def reverse_geocode(lat: float, lng: float):
    """Reverse-geocode a coordinate. Tries Nominatim first; falls back
    to the offline city/region/country DB when Nominatim is unreachable,
    rate-limited, or returns an error. Returns ``None`` only when both
    layers have nothing.
    """
    try:
        result = await geocoding_service.reverse(lat, lng)
        if result is not None:
            return result
    except Exception:
        logger.exception("Nominatim reverse failed; falling back to offline")

    cc, _tz, city, region = geo_offline.resolve(lat, lng)
    parts: list[str] = []
    for p in [city, region, cc.upper() if cc else ""]:
        if p and (not parts or parts[-1].lower() != p.lower()):
            parts.append(p)
    if not parts:
        return None
    return GeocodingResult(
        display_name=", ".join(parts),
        lat=lat,
        lng=lng,
        country_code=cc.lower(),
        short_name=city or region or (cc.upper() if cc else ""),
    )
```

- [ ] **Step B3: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_geocode_api.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step B4: Run the wider test suite to confirm no regressions**

```bash
cd backend && python -m pytest tests/ -q --timeout=60
```

Expected: all tests pass (or same set of pre-existing failures unrelated to geocode — if you see failures, run `git stash && python -m pytest tests/ -q --timeout=60` to confirm they're pre-existing, then `git stash pop`).

### Step group C: Commit

- [ ] **Step C1: Commit**

```bash
git add backend/api/geocode.py backend/tests/test_geocode_api.py
git commit -m "fix(geocode): fall back to offline DB when Nominatim reverse fails"
```

---

## Task 3: Manual smoke test verification

**Files:** none

Verification beyond `tsc --noEmit` / `pytest` requires a running app.

- [ ] **Step 1: Start the dev environment**

```bash
cd /Users/raviwu/personal/locwarp
./start.sh
```

(Do not prefix with `sudo`.) Or if you prefer the bundled Electron:

```bash
cd frontend && npm run dev
```

- [ ] **Step 2: Walk through the verification matrix**

| # | Action | Expected |
|---|--------|----------|
| 1 | Open the history dropdown, right-click any row. | Context menu opens at cursor; **history dropdown remains visible** beneath/beside the menu. Hovering other rows still highlights them. |
| 2 | With the menu still open, click outside the menu (in the dropdown's whitespace, or anywhere on the map). | Menu closes; dropdown stays open. |
| 3 | Click the `⋮` icon on any row. | Same as (1) — menu opens, dropdown stays. |
| 4 | Click a menu item that does NOT navigate (e.g. Copy coordinates). | Menu closes; dropdown stays open. |
| 5 | Click a menu item that navigates (e.g. Teleport here). | Menu closes; dropdown closes (existing re-fly behaviour, unchanged). |
| 6 | With internet enabled, click "What's here?" header inside the context menu on a well-known coord (e.g. Tokyo Tower). | Shows full Nominatim address (street + suburb + city). |
| 7 | Disable internet (or block `nominatim.openstreetmap.org` via `/etc/hosts → 127.0.0.1 nominatim.openstreetmap.org`), then click "What's here?" again on the same coord. | Shows the offline composition, e.g. `Tokyo, JP` — NOT an "Internal Server Error" string. |
| 8 | Same offline scenario but on an open-ocean coordinate (e.g. `lat=0, lng=-160`). | Shows the existing empty message (`map.whats_here_empty` → "No address found"). No crash. |
| 9 | With Nominatim blocked, open Add Bookmark dialog on a populated coord. | Name field pre-fills with offline city name (e.g. `Tokyo`) instead of staying blank. |

- [ ] **Step 3: Stop the dev environment**

`Ctrl-C` the foreground process.

- [ ] **Step 4: (no commit — manual-test task)**

If smoke test surfaces a defect, fix in a follow-up commit.

---

## Out of scope (do not implement here)

Per spec §3 / §8 — do **not** include:

- UI indicator (badge / muted colour / icon) marking offline-sourced results.
- Localised full country names in the offline composition (currently uppercase ISO code).
- Switching Add Bookmark dialog to always-try-offline-first.
- Throttling / queueing Nominatim requests across multiple clicks.
- Caching reverse-geocode results across clicks.
- Changes to the bookmarks reconciliation sweep (`backend/services/bookmarks.py`).
- Changes to `geocoding_service.reverse()` itself — fallback lives at the handler layer to keep the service single-responsibility.
