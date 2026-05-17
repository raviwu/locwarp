# History Menu Stay-Open + Offline Reverse-Geocode Fallback — Design

**Date:** 2026-05-17
**Status:** Draft (pending user review)
**Author:** Ravi Wu
**Type:** Two bugfixes in one PR (related UX area)

---

## 1. Background

Two issues surfaced after the history context-menu feature shipped:

**Issue 1 — Context menu closes the history dropdown.** When the user
right-clicks a history row or clicks its `⋮` icon, the helper
`openMenuAt` (`MapView.tsx:2338-2347`) opens the context menu AND calls
`setRecentOpen(false)`, dismissing the entire history dropdown. The user
expects the dropdown to stay open — they may want to act on the menu
result (e.g. copy coords, then close the menu and pick another row).

The `setRecentOpen(false)` call was added in the original implementation
to mirror the left-click re-fly behaviour (which closes the dropdown
because the user has navigated). That mirror is incorrect for the menu
path: opening a menu doesn't conclude the user's interaction with the
list.

**Issue 2 — "What's here?" returns 500 when Nominatim is unavailable.**
The context menu's top "What's here?" row calls
`frontend/src/services/api.ts:reverseGeocode()` →
`GET /api/geocode/reverse` → `geocoding_service.reverse()`
(`backend/services/geocoding.py:151`), which hits Nominatim's public
endpoint (`nominatim.openstreetmap.org`). When Nominatim rate-limits,
times out, or returns a server error, the service's
`resp.raise_for_status()` propagates the exception, FastAPI returns
HTTP 500, and the frontend displays the raw error text to the user
("Internal Server Error" or similar).

LocWarp already ships with an offline geocoding database
(`backend/services/geo_offline.py:resolve`) used by the bookmarks
reconciliation sweep. It returns `(country_code, timezone, city, region)`
for any global coordinate (TimezoneFinderL covers the whole globe; the
nearest city tables cover populated land). The data is loaded once at
process startup and never depends on network.

Using the offline database as a fallback path turns Nominatim outages
from a hard error into a graceful degradation — the user gets a less
detailed location string but always gets *something* useful.

## 2. Goals

- The history dropdown stays open when the context menu is opened from
  a row's right-click or `⋮` icon.
- The "What's here?" reverse-geocode lookup never surfaces a 500-style
  error string to the user when the offline DB has data for the
  coordinate. Nominatim failures become silent fallbacks.
- Zero new UI components, zero new i18n strings, no schema changes.

## 3. Non-goals

- Visible "(offline)" indicator distinguishing Nominatim vs. offline
  results in the UI. The display string itself (city/region/country
  vs. street address) is the only signal the user gets. If the user
  later wants explicit source labelling, that's a follow-up.
- Caching reverse-geocode results to reduce Nominatim load. Out of
  scope; the existing per-click flow is fine.
- Changing the reconciliation sweep that backfills bookmark
  `country_code` / `city` / `timezone`. That path already uses
  `geo_offline.resolve` directly and is unaffected.
- Adding rate-limit handling, retries, or throttling against
  Nominatim. The existing `fetchWithRetry` (15 attempts) handles
  transient connection errors; this design only adds the post-failure
  fallback.
- Changing `reverseGeocode` callers in the frontend (e.g. the Add
  Bookmark dialog's name pre-fill). Same backend endpoint, same
  response shape — fallback applies transparently.

## 4. Design

### 4.1 Issue 1 — Remove the dropdown-close call in `openMenuAt`

In `frontend/src/components/MapView.tsx`, the `openMenuAt` helper at
line 2338–2347:

```tsx
const openMenuAt = (x: number, y: number) => {
  setContextMenu({
    visible: true,
    x, y,
    lat: entry.lat,
    lng: entry.lng,
    name: entry.name || undefined,
  });
  setRecentOpen(false);  // ← REMOVE this line
};
```

Becomes:

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

**Interaction model after the change:**

| Trigger | Menu | Dropdown |
|---------|------|----------|
| Click history button | n/a | toggles |
| Left-click row body | (none) | closes (re-fly path, unchanged) |
| Right-click row | opens | **stays open** |
| Click `⋮` on row | opens | **stays open** |
| Click outside menu (incl. inside dropdown whitespace) | closes (existing outside-click handler at `:1641`) | stays |
| Click a menu item (Teleport / Navigate / Copy / Add bookmark / …) | closes (item handler calls `closeContextMenu`) | stays (unless re-fly path runs) |

No new event handlers are added. The dropdown has no document-level
outside-click handler today (verified via grep on `setRecentOpen` and
`addEventListener('click'`), so removing the close call simply lets
the dropdown persist until the user explicitly toggles it via the
history button.

### 4.2 Issue 2 — Offline fallback in the backend reverse-geocode handler

In `backend/api/geocode.py`, the current handler:

```python
@router.get("/reverse", response_model=GeocodingResult | None)
async def reverse_geocode(lat: float, lng: float):
    return await geocoding_service.reverse(lat, lng)
```

Becomes:

```python
@router.get("/reverse", response_model=GeocodingResult | None)
async def reverse_geocode(lat: float, lng: float):
    """Reverse-geocode a coordinate. Tries Nominatim first; falls back
    to the offline city/region/country database when Nominatim is
    unreachable, rate-limited, or returns an error. Returns ``None``
    only when both layers have nothing.
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

New imports:
- `geo_offline` from `services.geo_offline`
- `GeocodingResult` (already in scope via the existing response_model
  declaration's reference; verify the explicit import is present, add
  if missing)
- `logger` (already present in the module if it logs anything;
  otherwise add a module-level `logger = logging.getLogger(__name__)`)

### 4.3 Fallback display-name composition

`geo_offline.resolve` returns `(country_code, timezone, city, region)`,
any of which may be empty strings.

The composition rule (`parts` loop above) joins non-empty values with
", " and dedupes consecutive duplicates (city often equals region for
top-level prefectures like Tokyo, Singapore, etc.). country_code is
uppercased so it renders as a familiar 2-letter code (e.g. `JP`, `US`).

Examples:

| Offline tuple | Composed `display_name` |
|---------------|-------------------------|
| `('jp', 'Asia/Tokyo', 'Tokyo', 'Tokyo')` | `Tokyo, JP` |
| `('us', 'America/Los_Angeles', 'San Francisco', 'California')` | `San Francisco, California, US` |
| `('', 'Etc/GMT-5', '', '')` | `None` (all empty → no result) |
| `('tw', 'Asia/Taipei', '台北市', '台北市')` | `台北市, TW` |
| `('jp', 'Asia/Tokyo', 'Roppongi', 'Tokyo')` | `Roppongi, Tokyo, JP` |

The `short_name` field becomes `city or region or country_code_upper`,
preserving the existing semantic ("best human-friendly label for UI").

### 4.4 Behavioural matrix after both fixes

| Nominatim | Offline | UI shows |
|-----------|---------|----------|
| OK | n/a | Full street display_name (unchanged) |
| Network error / 4xx / 5xx | has data | Composed offline display_name (this PR) |
| Network error / 4xx / 5xx | no data | `map.whats_here_empty` "No address found" (unchanged) |
| 200 with no result | n/a | `map.whats_here_empty` (unchanged) |

### 4.5 Bookmark dialog side effect (intentional)

`App.tsx:handleAddBookmark` calls `api.reverseGeocode(lat, lng)` to
pre-fill the bookmark dialog's name field. After this change, if
Nominatim fails, the pre-fill becomes the offline city name (e.g.
`Roppongi`) instead of staying empty. This is a strict improvement —
no design changes needed in App.tsx.

## 5. Files touched

| File | What changes |
|------|--------------|
| `frontend/src/components/MapView.tsx` | Line 2346: remove `setRecentOpen(false)` from the `openMenuAt` helper. |
| `backend/api/geocode.py` | `reverse_geocode` wraps the Nominatim call in `try/except`, falls back to `geo_offline.resolve` with a composed display_name when the call fails or returns `None`. New imports as needed (`geo_offline`, `logging`/`logger`, `GeocodingResult`). |

No new files, no i18n changes, no frontend API signature changes, no
schema changes, no backend service-layer changes.

## 6. Testing

- Frontend: no automated suite (`tsc --noEmit` clean, `npm run build`
  green).
- Backend: `pytest backend/tests/test_geo_offline.py` exists for the
  offline resolver itself. We add one new pytest in
  `backend/tests/test_geocode_api.py` (or extend if it exists)
  exercising the fallback path with a monkeypatched
  `geocoding_service.reverse` that raises.

### 6.1 New backend test

```python
# backend/tests/test_geocode_api.py
import pytest
from fastapi.testclient import TestClient

import services.geocoding as geo_svc
import services.geo_offline as geo_offline


def test_reverse_falls_back_to_offline_when_nominatim_raises(monkeypatch, client):
    async def boom(lat, lng):
        raise RuntimeError("simulated Nominatim outage")
    monkeypatch.setattr(geo_svc.geocoding_service, "reverse", boom)
    # Pick a coord the offline DB definitely has data for: Tokyo Tower.
    res = client.get("/api/geocode/reverse", params={"lat": 35.6586, "lng": 139.7454})
    assert res.status_code == 200
    body = res.json()
    assert body is not None
    assert body["country_code"] == "jp"
    assert "Tokyo" in body["display_name"]
    assert body["short_name"]  # non-empty


def test_reverse_returns_none_when_nominatim_raises_and_offline_empty(monkeypatch, client):
    async def boom(lat, lng):
        raise RuntimeError("simulated Nominatim outage")
    monkeypatch.setattr(geo_svc.geocoding_service, "reverse", boom)
    monkeypatch.setattr(geo_offline, "resolve", lambda lat, lng: ("", "", "", ""))
    res = client.get("/api/geocode/reverse", params={"lat": 0, "lng": 0})
    assert res.status_code == 200
    assert res.json() is None
```

If `backend/tests/conftest.py` already exposes a `client` fixture
(via `TestClient(app)`), the test reuses it. If not, the test file
constructs one inline:

```python
@pytest.fixture
def client():
    from main import app
    return TestClient(app)
```

### 6.2 Manual smoke matrix

1. Open the history dropdown, right-click any row. Context menu opens;
   dropdown remains visible. Move the cursor over other rows — they
   still respond to hover. Close the menu by clicking outside (in the
   dropdown's whitespace). Menu closes; dropdown stays.
2. Click the `⋮` icon on a row. Same expectations as (1).
3. Click a context-menu item (e.g. Copy). Menu closes; dropdown stays
   open. (Copy is the cleanest test — no navigation side effect.)
4. With internet disabled (or Nominatim blocked via /etc/hosts), open
   the map context menu on any well-known land coordinate (e.g.
   somewhere in Tokyo). Click the "What's here?" header — the row
   resolves to `Tokyo, JP` (or similar) instead of an error. With
   internet re-enabled, the same click resolves to a full street
   address.
5. Same flow but on the Add Bookmark dialog with Nominatim
   unavailable: the dialog's Name field pre-fills with the offline
   city name rather than staying blank.
6. Coord with no offline data (open ocean far from any populated
   location): `What's here?` shows the existing "no address found"
   message. Behaviour unchanged.

## 7. Risks and rollback

- **Risk: offline composition produces unexpected text for some
  locales** (e.g. CJK city names alongside ASCII country codes mix
  scripts: `台北市, TW`). Acceptable — same mixing already happens in
  bookmark geo lines. If a user complains, we can localise country
  codes later.
- **Risk: `geo_offline.resolve` is slow at first call** (numpy
  allocations, lazy-loaded tables). Mitigation: the bookmarks
  reconciliation sweep already triggers initial load at app startup
  in practice; even cold, the call is sub-ms after the first
  TimezoneFinder lookup. Not a concern for a single user-triggered
  click.
- **Risk: a malicious Nominatim response could throw a non-Exception
  (e.g. `BaseException`)**. The `except Exception` covers all the
  realistic cases (HTTP error, JSON parse error, schema mismatch);
  `KeyboardInterrupt` / `SystemExit` should propagate.
- **Risk: bookmark dialog pre-fill change surprises existing users.**
  Pre-fill is editable, so the worst case is the user clears the
  suggested city name and types their own. No data corruption risk.
- **Rollback:** Each fix is contained to one file. Reverting the diff
  in either file restores prior behaviour.

## 8. Out of scope (revisit later)

- UI indicator (badge / muted color / icon) marking offline-sourced
  reverse-geocode results.
- Localised country names in the offline composition (currently shows
  uppercase ISO code).
- Switching the bookmark Add dialog to ALWAYS try offline first (skip
  Nominatim) for speed. Offline-first would lose street-level fidelity
  on the happy path — orthogonal decision.
- Throttling or queuing Nominatim requests across multiple rapid
  clicks. The existing single-call-per-header-click pattern is fine.
- Caching reverse-geocode results so repeat clicks on the same coord
  skip both Nominatim and the offline lookup.
