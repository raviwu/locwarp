# Bookmark Geo Info Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every bookmark — legacy ones included — shows a country flag, a short country name, its city/region, and its timezone, resolved entirely offline.

**Architecture:** A new backend module `geo_offline.resolve(lat, lng)` maps a coordinate to `(country_code, timezone, city, region)` using `timezonefinder` plus a bundled GeoNames `cities5000` extract. A single `enrich_bookmark()` function funnels every write path (create, coordinate-edit, import, startup sweep) through that resolver. The frontend renders a two-line bookmark row, deriving the flag, localized country name, and GMT offset at display time.

**Tech Stack:** Python 3.11 / FastAPI / Pydantic backend; `timezonefinder` + `numpy` for offline resolution; React + TypeScript / Vite frontend; PyInstaller packaging.

**Spec:** `docs/plans/2026-05-15-bookmark-geo-info-design.md`

---

## File Structure

**Backend — created:**
- `backend/services/geo_offline.py` — `resolve(lat, lng) -> (country_code, timezone, city, region)`. Loads `timezonefinder` + the bundled tables lazily; never raises.
- `backend/data/geo/cities5000.json` — GeoNames cities extract (parallel arrays). Generated, committed.
- `backend/data/geo/zone_to_country.json` — IANA zone → country code. Generated, committed.
- `backend/data/geo/admin1_names.json` — `"cc.admin1"` → region name. Generated, committed.
- `scripts/build_geo_data.py` — regenerates the three files above from GeoNames.
- `backend/tests/test_bookmark_geo_schema.py`, `test_geo_offline.py`, `test_bookmark_enrich.py` — new test files.

**Backend — modified:**
- `backend/models/schemas.py` — `Bookmark` gains `timezone`, `city`, `region`.
- `backend/services/bookmarks.py` — module-level `enrich_bookmark()`; `create_bookmark` / `update_bookmark` / `import_json` call it; new `BookmarkManager.enrich_all()` sweep.
- `backend/services/bookmark_import.py` — `_import_single_category` / `_import_geojson` call `enrich_bookmark`.
- `backend/main.py` — `load_state()` runs the startup sweep.
- `backend/requirements.txt` — add `timezonefinder`.
- `backend/locwarp-backend.spec` — bundle `timezonefinder` + `backend/data/geo/`; stop excluding `numpy`.

**Frontend — created:**
- `frontend/src/utils/geoFormat.ts` — `countryName(code, lang)` + `formatGmtOffset(timezone)`, both from the browser's built-in `Intl`.
- `frontend/src/components/BookmarkGeoLine.tsx` — renders the row's second line (flag · country · city · offset).

**Frontend — modified:**
- `frontend/src/components/BookmarkList.tsx` — `Bookmark` interface gains the fields; both row render sites use `BookmarkGeoLine`.
- `frontend/src/App.tsx` — pass the new fields through; drop the now-redundant reverse-geocode calls.

**Not touched:** `build-installer-mac.sh` (it invokes the shared `.spec`, so the spec edit covers macOS too). `MapView.tsx` (it already reads `bm.country_code`; the backend now fills it for every bookmark, so map flags improve with no code change).

---

## Conventions

- **Run backend tests:** `cd backend && .venv/bin/python -m pytest <path> -v`
- **Run frontend build/typecheck:** `cd frontend && npm run build`
- Tasks 4–9 require Task 2 (the `timezonefinder` install) and Task 3 (the committed data files) to be done first.

---

### Task 1: Add `timezone` / `city` / `region` to the Bookmark schema

**Files:**
- Modify: `backend/models/schemas.py:231-246`
- Test: `backend/tests/test_bookmark_geo_schema.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_bookmark_geo_schema.py`:

```python
"""Bookmark schema carries the offline geo-metadata fields."""
from models.schemas import Bookmark


def test_bookmark_geo_fields_default_empty():
    bm = Bookmark(name="x", lat=25.03, lng=121.56)
    assert bm.timezone == ""
    assert bm.city == ""
    assert bm.region == ""


def test_bookmark_geo_fields_round_trip():
    bm = Bookmark(
        name="x", lat=25.03, lng=121.56,
        timezone="Asia/Taipei", city="Taipei", region="Taipei",
    )
    dumped = bm.model_dump()
    assert dumped["timezone"] == "Asia/Taipei"
    assert dumped["city"] == "Taipei"
    assert dumped["region"] == "Taipei"
    assert Bookmark(**dumped).timezone == "Asia/Taipei"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_geo_schema.py -v`
Expected: FAIL — `AttributeError` / pydantic rejects unknown keys (`timezone`, `city`, `region` not on the model).

- [ ] **Step 3: Add the fields**

In `backend/models/schemas.py`, the `Bookmark` class currently ends:

```python
    country_code: str = ""
    # Bumped on every mutation so the cloud-sync merge can pick the newer
    # copy on an id collision. Empty = legacy (pre-sync-merge) record.
    updated_at: str = ""
```

Replace that with:

```python
    country_code: str = ""
    # Offline-resolved geo metadata (timezonefinder + a bundled GeoNames
    # extract), populated by enrich_bookmark on create / GPS-edit / import
    # and by the startup reconciliation sweep. Empty = unresolved (an ocean
    # point, or a pre-feature record awaiting the next sweep) — the UI
    # simply skips whichever field is blank.
    timezone: str = ""   # IANA zone, e.g. 'Asia/Taipei'
    city: str = ""       # nearest notable city, ASCII name
    region: str = ""     # admin1 — province / state / county
    # Bumped on every mutation so the cloud-sync merge can pick the newer
    # copy on an id collision. Empty = legacy (pre-sync-merge) record.
    updated_at: str = ""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_geo_schema.py -v`
Expected: PASS — both tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/models/schemas.py backend/tests/test_bookmark_geo_schema.py
git commit -m "feat(bookmark): add timezone/city/region fields to the Bookmark schema"
```

---

### Task 2: Add the `timezonefinder` dependency and update the PyInstaller spec

This task has no pytest test — it is a dependency + build-config change. Verification is the import smoke-check in Step 3 and a visual review of the spec diff.

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/locwarp-backend.spec`

- [ ] **Step 1: Add the dependency**

In `backend/requirements.txt`, the last line is `watchdog>=3.0`. Append one line:

```
timezonefinder>=8.0
```

- [ ] **Step 2: Install it into the backend venv**

Run: `cd backend && .venv/bin/python -m pip install -r requirements.txt`
Expected: installs `timezonefinder`, `numpy`, `h3`, `cffi`, `flatbuffers`, `pycparser`.

- [ ] **Step 3: Verify the offline resolver library works**

Run: `cd backend && .venv/bin/python -c "from timezonefinder import TimezoneFinderL; print(TimezoneFinderL().timezone_at(lat=25.0339, lng=121.5645))"`
Expected: prints `Asia/Taipei`.

- [ ] **Step 4: Update the PyInstaller spec — collect `timezonefinder`**

In `backend/locwarp-backend.spec`, find this line (line 40):

```python
ps_datas, ps_binaries, ps_hidden = collect_all('psutil')
```

Insert immediately after it:

```python

# timezonefinder ships its boundary data as package data files and pulls
# in numpy + a compiled h3 extension; collect_all grabs data, binaries,
# and the hidden submodule imports in one shot.
tzf_datas, tzf_binaries, tzf_hidden = collect_all('timezonefinder')
```

- [ ] **Step 5: Update the PyInstaller spec — wire `timezonefinder` into the build**

In the same file, in the `hidden` list, find `*ps_hidden,` and add `*tzf_hidden,` right after it:

```python
        *ps_hidden,
        *tzf_hidden,
```

Find the `binaries=` argument of `Analysis`:

```python
    binaries=[*pmd_binaries, *pytun_binaries, *ddi_binaries, *pyimg4_binaries,
              *ps_binaries],
```

Replace with:

```python
    binaries=[*pmd_binaries, *pytun_binaries, *ddi_binaries, *pyimg4_binaries,
              *ps_binaries, *tzf_binaries],
```

Find the `datas=` argument:

```python
    datas=[*pmd_datas, *pytun_datas, *ddi_datas, *pyimg4_datas, *pyimg4_meta,
           *ps_datas,
           ('static/phone.html', 'static'),
           ('static/catalog.json', 'static')],
```

Replace with:

```python
    datas=[*pmd_datas, *pytun_datas, *ddi_datas, *pyimg4_datas, *pyimg4_meta,
           *ps_datas, *tzf_datas,
           ('static/phone.html', 'static'),
           ('static/catalog.json', 'static'),
           ('data/geo', 'data/geo')],
```

Find the `excludes=` argument (line 82):

```python
    excludes=['tkinter', 'matplotlib', 'PIL', 'numpy', 'scipy', 'pandas'],
```

Replace with (drop `'numpy'` — `timezonefinder` needs it):

```python
    excludes=['tkinter', 'matplotlib', 'PIL', 'scipy', 'pandas'],
```

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/locwarp-backend.spec
git commit -m "build(bookmark): bundle timezonefinder + backend/data/geo for offline geo"
```

---

### Task 3: Geo-data generator script + generate and commit the bundled tables

**This task requires network access to `download.geonames.org`.** It has no pytest test — it is a one-shot data generator; the resolver tests in Task 4 transitively validate the output.

**Files:**
- Create: `scripts/build_geo_data.py`
- Create (generated): `backend/data/geo/cities5000.json`, `backend/data/geo/zone_to_country.json`, `backend/data/geo/admin1_names.json`

- [ ] **Step 1: Write the generator script**

Create `scripts/build_geo_data.py`:

```python
#!/usr/bin/env python3
"""Regenerate the bundled offline geo lookup tables under backend/data/geo/.

Pulls GeoNames' cities5000 + admin1 tables, distils them to the few
columns geo_offline.resolve() needs, and writes three compact JSON files
that ship with the build. Re-run this only to refresh the GeoNames
snapshot — the committed JSON is what the app loads at runtime.

Usage:  python3 scripts/build_geo_data.py
Needs:  network access to download.geonames.org
"""
from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from pathlib import Path

CITIES_URL = "https://download.geonames.org/export/dump/cities5000.zip"
ADMIN1_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"

OUT_DIR = Path(__file__).resolve().parent.parent / "backend" / "data" / "geo"

# GeoNames cities table column indices (tab-separated, no header).
# https://download.geonames.org/export/dump/readme.txt
C_ASCIINAME = 2
C_LAT = 4
C_LNG = 5
C_COUNTRY = 8
C_ADMIN1 = 10
C_POPULATION = 14
C_TIMEZONE = 17


def _fetch(url: str) -> bytes:
    print(f"  downloading {url}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def build() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── cities5000 ────────────────────────────────────────────────
    with zipfile.ZipFile(io.BytesIO(_fetch(CITIES_URL))) as zf:
        text = zf.read("cities5000.txt").decode("utf-8")

    lat: list[float] = []
    lng: list[float] = []
    name: list[str] = []
    cc: list[str] = []
    admin1: list[str] = []
    # timezone -> (population, country_code) of the most populous city seen.
    zone_best: dict[str, tuple[int, str]] = {}

    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 18:
            continue
        try:
            row_lat = float(parts[C_LAT])
            row_lng = float(parts[C_LNG])
        except ValueError:
            continue
        country = parts[C_COUNTRY].strip().lower()
        if not country:
            continue
        lat.append(row_lat)
        lng.append(row_lng)
        name.append(parts[C_ASCIINAME].strip())
        cc.append(country)
        admin1.append(parts[C_ADMIN1].strip())

        zone = parts[C_TIMEZONE].strip()
        try:
            pop = int(parts[C_POPULATION] or "0")
        except ValueError:
            pop = 0
        if zone:
            prev = zone_best.get(zone)
            if prev is None or pop > prev[0]:
                zone_best[zone] = (pop, country)

    (OUT_DIR / "cities5000.json").write_text(
        json.dumps(
            {"lat": lat, "lng": lng, "name": name, "cc": cc, "admin1": admin1},
            ensure_ascii=False, separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"  cities5000.json — {len(lat)} cities")

    zone_to_country = {z: country for z, (_pop, country) in zone_best.items()}
    (OUT_DIR / "zone_to_country.json").write_text(
        json.dumps(zone_to_country, ensure_ascii=False, sort_keys=True, indent=0),
        encoding="utf-8",
    )
    print(f"  zone_to_country.json — {len(zone_to_country)} zones")

    # ── admin1 names ──────────────────────────────────────────────
    admin1_text = _fetch(ADMIN1_URL).decode("utf-8")
    admin1_names: dict[str, str] = {}
    for line in admin1_text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0].strip()      # e.g. "TW.04"
        label = parts[1].strip()     # e.g. "Kaohsiung"
        if not code or not label:
            continue
        # Lowercase the country prefix so the key matches geo_offline's
        # f"{cc}.{admin1}" lookup (cc is stored lowercase in cities5000.json).
        cc_part, _, a1 = code.partition(".")
        admin1_names[f"{cc_part.lower()}.{a1}"] = label
    (OUT_DIR / "admin1_names.json").write_text(
        json.dumps(admin1_names, ensure_ascii=False, sort_keys=True, indent=0),
        encoding="utf-8",
    )
    print(f"  admin1_names.json — {len(admin1_names)} admin1 regions")


if __name__ == "__main__":
    print("Building backend/data/geo/ ...")
    build()
    print("Done.")
```

- [ ] **Step 2: Run the generator**

Run: `cd /Users/ravi.wu/personal/locwarp && python3 scripts/build_geo_data.py`
Expected: prints download progress, then three lines like `cities5000.json — ~55000 cities`, `zone_to_country.json — ~400 zones`, `admin1_names.json — ~3900 admin1 regions`.

- [ ] **Step 3: Verify the generated files**

Run:
```bash
cd /Users/ravi.wu/personal/locwarp
ls -la backend/data/geo/
python3 -c "import json; d=json.load(open('backend/data/geo/cities5000.json')); print(len(d['lat']), 'cities; sample:', d['name'][:3], d['cc'][:3])"
python3 -c "import json; print('Asia/Taipei ->', json.load(open('backend/data/geo/zone_to_country.json'))['Asia/Taipei'])"
python3 -c "import json; d=json.load(open('backend/data/geo/admin1_names.json')); print('admin1 sample:', list(d.items())[:3])"
git check-ignore backend/data/geo/cities5000.json && echo 'ERROR: data is gitignored' || echo 'OK: data is committable'
```
Expected: three JSON files present; city count ~55k; `Asia/Taipei -> tw`; admin1 keys look like `"tw.04"`; the last line prints `OK: data is committable`.

- [ ] **Step 4: Commit**

```bash
git add scripts/build_geo_data.py backend/data/geo/
git commit -m "chore(bookmark): add geo-data generator + bundled GeoNames tables"
```

---

### Task 4: `geo_offline.resolve()` — offline coordinate → (country, timezone, city, region)

**Files:**
- Create: `backend/services/geo_offline.py`
- Test: `backend/tests/test_geo_offline.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_geo_offline.py`:

```python
"""Offline geo resolver — known coordinates and graceful failure.

country_code and timezone are asserted exactly: timezonefinder and the
zone_to_country table are deterministic. city / region are only checked
non-empty (plus one substring sanity check) because the exact GeoNames
string depends on the snapshot the generator pulled.
"""
from services.geo_offline import resolve


def test_resolve_taipei():
    cc, zone, city, region = resolve(25.0339, 121.5645)
    assert cc == "tw"
    assert zone == "Asia/Taipei"
    assert "taipei" in city.lower()
    assert region != ""


def test_resolve_new_york():
    cc, zone, city, region = resolve(40.7580, -73.9855)
    assert cc == "us"
    assert zone == "America/New_York"
    assert city != ""
    assert region != ""


def test_resolve_london():
    cc, zone, city, region = resolve(51.5074, -0.1278)
    assert cc == "gb"
    assert zone == "Europe/London"
    assert city != ""


def test_resolve_tokyo():
    cc, zone, city, region = resolve(35.6762, 139.6503)
    assert cc == "jp"
    assert zone == "Asia/Tokyo"


def test_resolve_open_ocean_is_empty():
    # Middle of the South Pacific — no timezone polygon.
    assert resolve(-40.0, -140.0) == ("", "", "", "")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_geo_offline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.geo_offline'`.

- [ ] **Step 3: Write the resolver**

Create `backend/services/geo_offline.py`:

```python
"""Offline lat/lng → (country_code, timezone, city, region) resolver.

Backs the bookmark geo-info feature. timezonefinder maps the point to an
IANA zone; a bundled GeoNames cities5000 extract supplies the nearest
city + admin1 region; zone_to_country.json maps the zone to a country.
Everything is offline and deterministic — no network, no rate limits.

resolve() never raises: any failure (missing data, import error, a point
with no timezone polygon) yields ("", "", "", "") and the caller leaves
the bookmark's geo fields empty for the next reconciliation pass.
"""
from __future__ import annotations

import json
import logging
import math
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_loaded = False
_load_failed = False

_tf = None                    # TimezoneFinderL instance
_lat = None                   # numpy array — city latitudes
_lng = None                   # numpy array — city longitudes
_name: list[str] = []
_cc: list[str] = []
_admin1: list[str] = []
_zone_to_country: dict[str, str] = {}
_admin1_names: dict[str, str] = {}


def _geo_data_dir() -> Path:
    """Resolve backend/data/geo/ in both dev and PyInstaller layouts.

    Mirrors the _MEIPASS convention in api.bookmarks._catalog_path.
    """
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "data" / "geo")
    candidates.append(Path(__file__).resolve().parent.parent / "data" / "geo")
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


def _ensure_loaded() -> bool:
    """Lazily load timezonefinder + the bundled tables. Returns False if
    anything is unavailable — resolve() then degrades to empty results."""
    global _loaded, _load_failed, _tf, _lat, _lng, _name, _cc, _admin1
    global _zone_to_country, _admin1_names
    if _loaded:
        return True
    if _load_failed:
        return False
    with _lock:
        if _loaded:
            return True
        if _load_failed:
            return False
        try:
            import numpy as np
            from timezonefinder import TimezoneFinderL

            data_dir = _geo_data_dir()
            cities = json.loads((data_dir / "cities5000.json").read_text("utf-8"))
            _lat = np.asarray(cities["lat"], dtype="float64")
            _lng = np.asarray(cities["lng"], dtype="float64")
            _name = cities["name"]
            _cc = cities["cc"]
            _admin1 = cities["admin1"]
            _zone_to_country = json.loads(
                (data_dir / "zone_to_country.json").read_text("utf-8")
            )
            _admin1_names = json.loads(
                (data_dir / "admin1_names.json").read_text("utf-8")
            )
            _tf = TimezoneFinderL()
            _loaded = True
            logger.info("geo_offline loaded %d cities", len(_name))
            return True
        except Exception:
            logger.exception("geo_offline failed to load; geo fields stay empty")
            _load_failed = True
            return False


def resolve(lat: float, lng: float) -> tuple[str, str, str, str]:
    """Return (country_code, timezone, city, region) for a coordinate.

    All-empty when the point has no timezone (open ocean) or the offline
    tables are unavailable. country_code is lowercase ISO 3166-1 alpha-2;
    timezone is an IANA zone string.
    """
    if not _ensure_loaded():
        return ("", "", "", "")
    try:
        import numpy as np

        zone = _tf.timezone_at(lng=lng, lat=lat)
        if not zone:
            return ("", "", "", "")

        country_code = _zone_to_country.get(zone, "")

        # Nearest city — squared euclidean with a cos(lat) longitude
        # correction so high-latitude points don't snap sideways.
        coslat = math.cos(math.radians(lat))
        d2 = (_lat - lat) ** 2 + ((_lng - lng) * coslat) ** 2
        i = int(np.argmin(d2))
        city = _name[i]
        city_cc = _cc[i]
        if not country_code:
            country_code = city_cc
        region = _admin1_names.get(f"{city_cc}.{_admin1[i]}", "")

        return (country_code, zone, city, region)
    except Exception:
        logger.exception("geo_offline.resolve failed for (%s, %s)", lat, lng)
        return ("", "", "", "")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_geo_offline.py -v`
Expected: PASS — all five tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/geo_offline.py backend/tests/test_geo_offline.py
git commit -m "feat(bookmark): offline geo_offline.resolve (timezonefinder + GeoNames)"
```

---

### Task 5: `enrich_bookmark()` — fill a bookmark's geo fields

**Files:**
- Modify: `backend/services/bookmarks.py` (imports + new module-level function)
- Test: `backend/tests/test_bookmark_enrich.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_bookmark_enrich.py`:

```python
"""enrich_bookmark — offline geo-field fill and force-refresh semantics."""
from models.schemas import Bookmark
from services.bookmarks import enrich_bookmark


def test_enrich_fills_blank_fields():
    bm = Bookmark(name="x", lat=25.0339, lng=121.5645)
    changed = enrich_bookmark(bm)
    assert changed is True
    assert bm.country_code == "tw"
    assert bm.timezone == "Asia/Taipei"
    assert bm.city != ""
    assert bm.region != ""


def test_enrich_noop_when_all_filled():
    bm = Bookmark(name="x", lat=25.0339, lng=121.5645,
                  country_code="zz", timezone="Z/Z", city="C", region="R")
    changed = enrich_bookmark(bm)
    assert changed is False
    assert bm.country_code == "zz"  # untouched


def test_enrich_force_overwrites_existing():
    bm = Bookmark(name="x", lat=25.0339, lng=121.5645,
                  country_code="zz", timezone="Z/Z", city="C", region="R")
    changed = enrich_bookmark(bm, force=True)
    assert changed is True
    assert bm.country_code == "tw"
    assert bm.timezone == "Asia/Taipei"


def test_enrich_ocean_point_leaves_fields_empty():
    bm = Bookmark(name="x", lat=-40.0, lng=-140.0)
    changed = enrich_bookmark(bm)
    assert changed is False
    assert bm.country_code == "" and bm.timezone == ""


def test_enrich_does_not_touch_updated_at():
    bm = Bookmark(name="x", lat=25.0339, lng=121.5645, updated_at="2020-01-01")
    enrich_bookmark(bm)
    assert bm.updated_at == "2020-01-01"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_enrich.py -v`
Expected: FAIL — `ImportError: cannot import name 'enrich_bookmark' from 'services.bookmarks'`.

- [ ] **Step 3: Add the import and the function**

In `backend/services/bookmarks.py`, find the import block ending:

```python
from services.json_safe import safe_load_json, safe_write_json
from services.store_merge import merge_stores
```

Add one line after it:

```python
from services.json_safe import safe_load_json, safe_write_json
from services.store_merge import merge_stores
from services.geo_offline import resolve as _geo_resolve
```

Then, immediately after the `_load_store_or_empty` function (just before `class BookmarkManager:`), add:

```python
def enrich_bookmark(bm: Bookmark, *, force: bool = False) -> bool:
    """Fill a bookmark's offline geo fields from its coordinates.

    country_code / timezone / city / region come from
    ``geo_offline.resolve``. With ``force=False`` (default) only empty
    fields are filled — an idempotent reconciliation safe to run on every
    bookmark repeatedly. With ``force=True`` every field is re-resolved
    and overwritten — used when a bookmark's coordinates change.

    Never writes an empty value: a failed or ocean-point lookup leaves
    the existing fields untouched rather than wiping them, so a transient
    data-load failure cannot destroy good data (the trade-off: moving a
    bookmark from land to open ocean keeps its now-stale labels — a rare,
    cosmetic edge). Returns True if any field changed.

    Does NOT touch ``updated_at`` — callers own that, so the startup
    sweep can fill legacy records without forcing a cloud-sync write.
    """
    blanks = not (bm.country_code and bm.timezone and bm.city and bm.region)
    if not force and not blanks:
        return False
    country_code, timezone, city, region = _geo_resolve(bm.lat, bm.lng)
    changed = False
    for field, value in (
        ("country_code", country_code),
        ("timezone", timezone),
        ("city", city),
        ("region", region),
    ):
        if not value:
            continue  # never overwrite a known value with an empty lookup
        if (force or not getattr(bm, field)) and getattr(bm, field) != value:
            setattr(bm, field, value)
            changed = True
    return changed
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_enrich.py -v`
Expected: PASS — all five tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmarks.py backend/tests/test_bookmark_enrich.py
git commit -m "feat(bookmark): enrich_bookmark fills offline geo fields"
```

---

### Task 6: `create_bookmark` enriches new bookmarks

**Files:**
- Modify: `backend/services/bookmarks.py` (`create_bookmark`, ~line 365-394)
- Test: `backend/tests/test_bookmark_enrich.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_bookmark_enrich.py`:

```python
import pytest
from services.bookmarks import BookmarkManager


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """A BookmarkManager with its store redirected to tmp_path.

    Mirrors the fixture in test_list_ordering.py: patch BOOKMARKS_FILE and
    replace the captured config default so _bookmarks_path() honours it.
    """
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", object())
    return BookmarkManager()


def test_create_bookmark_enriches(manager):
    bm = manager.create_bookmark(name="Taipei 101", lat=25.0339, lng=121.5645)
    assert bm.country_code == "tw"
    assert bm.timezone == "Asia/Taipei"
    assert bm.city != ""
    assert bm.region != ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_enrich.py::test_create_bookmark_enriches -v`
Expected: FAIL — `assert '' == 'tw'` (`create_bookmark` does not resolve geo fields yet).

- [ ] **Step 3: Call `enrich_bookmark` in `create_bookmark`**

In `backend/services/bookmarks.py`, `create_bookmark` currently ends:

```python
            country_code=country_code.lower(),
            updated_at=now,
        )
        self.store.bookmarks.append(bm)
        self._save()
        return bm
```

Replace with:

```python
            country_code=country_code.lower(),
            updated_at=now,
        )
        # Offline-resolve country / timezone / city / region. force=False
        # respects an explicitly supplied country_code; the other three are
        # always blank on a fresh bookmark and get filled.
        enrich_bookmark(bm)
        self.store.bookmarks.append(bm)
        self._save()
        return bm
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_enrich.py -v`
Expected: PASS — all tests in the file green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmarks.py backend/tests/test_bookmark_enrich.py
git commit -m "feat(bookmark): create_bookmark resolves geo fields offline"
```

---

### Task 7: `update_bookmark` re-resolves on a coordinate change

**Files:**
- Modify: `backend/services/bookmarks.py` (`update_bookmark`, ~line 396-409)
- Test: `backend/tests/test_bookmark_enrich.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_bookmark_enrich.py`:

```python
def test_update_bookmark_reresolves_on_coord_change(manager):
    bm = manager.create_bookmark(name="x", lat=25.0339, lng=121.5645)
    assert bm.country_code == "tw"
    updated = manager.update_bookmark(bm.id, lat=35.6762, lng=139.6503)  # Tokyo
    assert updated.country_code == "jp"
    assert updated.timezone == "Asia/Tokyo"


def test_update_bookmark_keeps_geo_when_coords_unchanged(manager):
    bm = manager.create_bookmark(name="x", lat=25.0339, lng=121.5645)
    tz_before, city_before = bm.timezone, bm.city
    updated = manager.update_bookmark(bm.id, name="renamed")
    assert updated.timezone == tz_before
    assert updated.city == city_before
    assert updated.name == "renamed"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_enrich.py::test_update_bookmark_reresolves_on_coord_change -v`
Expected: FAIL — `assert 'tw' == 'jp'` (`update_bookmark` does not re-resolve yet).

- [ ] **Step 3: Re-resolve on a coordinate change**

In `backend/services/bookmarks.py`, replace the whole `update_bookmark` method:

```python
    def update_bookmark(self, bm_id: str, **kwargs: object) -> Bookmark | None:
        """Update a bookmark's fields. Returns ``None`` if not found."""
        bm = self._find_bookmark(bm_id)
        if bm is None:
            return None

        allowed = {"name", "lat", "lng", "address", "category_id", "last_used_at", "country_code"}
        for key, value in kwargs.items():
            if key in allowed and value is not None:
                setattr(bm, key, value)

        bm.updated_at = _now_iso()
        self._save()
        return bm
```

with:

```python
    def update_bookmark(self, bm_id: str, **kwargs: object) -> Bookmark | None:
        """Update a bookmark's fields. Returns ``None`` if not found.

        When the coordinates change, the offline geo fields (country_code,
        timezone, city, region) are re-resolved from the new position so
        the bookmark's flag / city / timezone labels never go stale.
        """
        bm = self._find_bookmark(bm_id)
        if bm is None:
            return None

        old_lat, old_lng = bm.lat, bm.lng
        allowed = {"name", "lat", "lng", "address", "category_id", "last_used_at", "country_code"}
        for key, value in kwargs.items():
            if key in allowed and value is not None:
                setattr(bm, key, value)

        if bm.lat != old_lat or bm.lng != old_lng:
            enrich_bookmark(bm, force=True)

        bm.updated_at = _now_iso()
        self._save()
        return bm
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_enrich.py -v`
Expected: PASS — all tests in the file green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmarks.py backend/tests/test_bookmark_enrich.py
git commit -m "feat(bookmark): re-resolve geo fields when a bookmark's coords change"
```

---

### Task 8: Import paths enrich imported bookmarks

**Files:**
- Modify: `backend/services/bookmarks.py` (`import_json`, ~line 500-507)
- Modify: `backend/services/bookmark_import.py` (`_import_single_category`, `_import_geojson`)
- Test: `backend/tests/test_bookmark_enrich.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_bookmark_enrich.py`:

```python
def test_import_json_enriches_bookmarks(manager):
    payload = (
        '{"categories": [], "bookmarks": ['
        '{"id": "imp1", "name": "Tokyo Tower", "lat": 35.6586, "lng": 139.7454, '
        '"category_id": "default"}]}'
    )
    manager.import_json(payload)
    bm = next(b for b in manager.store.bookmarks if b.id == "imp1")
    assert bm.country_code == "jp"
    assert bm.timezone == "Asia/Tokyo"
    assert bm.city != ""


def test_import_geojson_enriches_bookmarks(manager):
    from services.bookmark_import import detect_and_import

    payload = (
        '{"type": "FeatureCollection", "name": "trip", "features": ['
        '{"type": "Feature", "geometry": {"type": "Point", '
        '"coordinates": [121.5645, 25.0339]}, "properties": {"name": "Taipei 101"}}]}'
    )
    detect_and_import(manager, payload)
    bm = next(b for b in manager.store.bookmarks if b.name == "Taipei 101")
    assert bm.country_code == "tw"
    assert bm.timezone == "Asia/Taipei"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_enrich.py::test_import_json_enriches_bookmarks tests/test_bookmark_enrich.py::test_import_geojson_enriches_bookmarks -v`
Expected: FAIL — `assert '' == 'jp'` / `assert '' == 'tw'`.

- [ ] **Step 3a: Enrich in `import_json`**

In `backend/services/bookmarks.py`, `import_json` has this loop:

```python
        for bm in incoming.bookmarks:
            if bm.id not in existing_bm_ids:
                # Ensure the bookmark's category exists
                if bm.category_id not in existing_cat_ids:
                    bm.category_id = "default"
                self.store.bookmarks.append(bm)
                existing_bm_ids.add(bm.id)
                imported += 1
```

Add one line — `enrich_bookmark(bm)` before the append:

```python
        for bm in incoming.bookmarks:
            if bm.id not in existing_bm_ids:
                # Ensure the bookmark's category exists
                if bm.category_id not in existing_cat_ids:
                    bm.category_id = "default"
                enrich_bookmark(bm)  # fill any geo fields the import lacked
                self.store.bookmarks.append(bm)
                existing_bm_ids.add(bm.id)
                imported += 1
```

- [ ] **Step 3b: Enrich in `bookmark_import.py`**

In `backend/services/bookmark_import.py`, add to the import block at the top of the file:

```python
from models.schemas import Bookmark, BookmarkCategory
from services.bookmarks import enrich_bookmark
```

In `_import_single_category`, the loop builds `bm` then appends:

```python
        bm = Bookmark(
            id=bm_id,
            name=raw_bm["name"],
            lat=float(raw_bm["lat"]),
            lng=float(raw_bm["lng"]),
            address=raw_bm.get("address", ""),
            category_id=new_id,
            country_code=raw_bm.get("country_code", ""),
            created_at=raw_bm.get("created_at", ""),
            last_used_at=raw_bm.get("last_used_at", ""),
        )
        manager.store.bookmarks.append(bm)
```

Insert `enrich_bookmark(bm)` between construction and append:

```python
        bm = Bookmark(
            id=bm_id,
            name=raw_bm["name"],
            lat=float(raw_bm["lat"]),
            lng=float(raw_bm["lng"]),
            address=raw_bm.get("address", ""),
            category_id=new_id,
            country_code=raw_bm.get("country_code", ""),
            created_at=raw_bm.get("created_at", ""),
            last_used_at=raw_bm.get("last_used_at", ""),
        )
        enrich_bookmark(bm)
        manager.store.bookmarks.append(bm)
```

In `_import_geojson`, the loop builds `bm` then appends:

```python
            bm = Bookmark(
                id=bm_id,
                name=bm_name,
                lat=lat,
                lng=lng,
                category_id=cat.id,
                country_code=str(props.get("country_code", "")).lower(),
                created_at="",
                last_used_at="",
            )
            manager.store.bookmarks.append(bm)
```

Insert `enrich_bookmark(bm)` between construction and append:

```python
            bm = Bookmark(
                id=bm_id,
                name=bm_name,
                lat=lat,
                lng=lng,
                category_id=cat.id,
                country_code=str(props.get("country_code", "")).lower(),
                created_at="",
                last_used_at="",
            )
            enrich_bookmark(bm)
            manager.store.bookmarks.append(bm)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_enrich.py -v`
Expected: PASS — all tests in the file green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmarks.py backend/services/bookmark_import.py backend/tests/test_bookmark_enrich.py
git commit -m "feat(bookmark): enrich imported bookmarks with offline geo fields"
```

---

### Task 9: `enrich_all()` startup reconciliation sweep + main.py wiring

**Files:**
- Modify: `backend/services/bookmarks.py` (new `BookmarkManager.enrich_all` method)
- Modify: `backend/main.py` (`load_state`, ~line 120-127)
- Test: `backend/tests/test_bookmark_enrich.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_bookmark_enrich.py`:

```python
def test_enrich_all_fills_legacy_bookmarks(manager):
    manager.store.bookmarks = [
        Bookmark(id="a", name="Taipei", lat=25.0339, lng=121.5645),
        Bookmark(id="b", name="Tokyo", lat=35.6762, lng=139.6503),
    ]
    n = manager.enrich_all()
    assert n == 2
    assert manager.store.bookmarks[0].country_code == "tw"
    assert manager.store.bookmarks[1].country_code == "jp"


def test_enrich_all_idempotent(manager):
    manager.store.bookmarks = [Bookmark(id="a", name="x", lat=25.0339, lng=121.5645)]
    assert manager.enrich_all() == 1
    assert manager.enrich_all() == 0  # second sweep changes nothing


def test_enrich_all_does_not_bump_updated_at(manager):
    manager.store.bookmarks = [
        Bookmark(id="a", name="x", lat=25.0339, lng=121.5645, updated_at="2020-01-01"),
    ]
    manager.enrich_all()
    assert manager.store.bookmarks[0].updated_at == "2020-01-01"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_enrich.py::test_enrich_all_fills_legacy_bookmarks -v`
Expected: FAIL — `AttributeError: 'BookmarkManager' object has no attribute 'enrich_all'`.

- [ ] **Step 3a: Add `enrich_all` to `BookmarkManager`**

In `backend/services/bookmarks.py`, find the end of `move_bookmarks` and the `_find_bookmark` helper:

```python
        if moved:
            self._save()
        return moved

    def _find_bookmark(self, bm_id: str) -> Bookmark | None:
        return next((b for b in self.store.bookmarks if b.id == bm_id), None)
```

Insert the `enrich_all` method between them:

```python
        if moved:
            self._save()
        return moved

    def enrich_all(self) -> int:
        """Reconciliation sweep: fill missing offline geo fields on every
        bookmark, persisting once if anything changed.

        Runs at startup. ``enrich_bookmark`` only fills blanks here
        (force=False) and does not touch ``updated_at``, so legacy records
        get their flag / city / timezone without manufacturing a
        cloud-sync conflict — every device resolves identical values from
        the same coordinates and converges. Idempotent: once every
        bookmark is filled, later sweeps change nothing and skip the save.

        Returns the number of bookmarks modified.
        """
        changed = 0
        for bm in self.store.bookmarks:
            if enrich_bookmark(bm):
                changed += 1
        if changed:
            logger.info("enrich_all filled geo fields on %d bookmarks", changed)
            self._save()
        return changed

    def _find_bookmark(self, bm_id: str) -> Bookmark | None:
        return next((b for b in self.store.bookmarks if b.id == bm_id), None)
```

- [ ] **Step 3b: Run the sweep at startup**

In `backend/main.py`, `load_state` currently reads:

```python
    async def load_state(self) -> None:
        """Load on-disk state. Must run after the helper has migrated
        any root-owned files back to the user. Idempotent — repeated
        calls rebuild the managers and re-read settings from disk."""
        self._reload_sync_folder()
        self._load_settings()
        self.bookmark_manager = BookmarkManager()
        self.route_manager = RouteManager()
```

Replace with:

```python
    async def load_state(self) -> None:
        """Load on-disk state. Must run after the helper has migrated
        any root-owned files back to the user. Idempotent — repeated
        calls rebuild the managers and re-read settings from disk."""
        self._reload_sync_folder()
        self._load_settings()
        self.bookmark_manager = BookmarkManager()
        # Reconciliation sweep: backfill country / timezone / city / region
        # on any bookmark (legacy, imported, offline-added) still missing
        # them. Offline + idempotent — a no-op once everything is filled.
        self.bookmark_manager.enrich_all()
        self.route_manager = RouteManager()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_bookmark_enrich.py -v`
Expected: PASS — all tests in the file green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmarks.py backend/main.py backend/tests/test_bookmark_enrich.py
git commit -m "feat(bookmark): startup sweep backfills geo fields on legacy bookmarks"
```

---

### Task 10: Frontend geo-formatting utils (country name + GMT offset)

The design called for a static ~250-entry country-name table. This task uses the browser's built-in `Intl.DisplayNames` and `Intl.DateTimeFormat` instead — same outcome (localized short country names, DST-correct offsets) with no table to bundle or maintain, plus a tiny override map for the handful of names too long for a label. No pytest equivalent — the frontend has no test harness; verification is the typecheck/build.

**Files:**
- Create: `frontend/src/utils/geoFormat.ts`

- [ ] **Step 1: Write the util**

Create `frontend/src/utils/geoFormat.ts`:

```typescript
// Geo display formatting for bookmark labels — short country name + GMT
// offset. Both derive from the browser's built-in Intl data, so no
// country or timezone table ships with the app.
import type { Lang } from '../i18n';

// "越短越好": Intl.DisplayNames returns the full ICU name ("United
// States", "United Kingdom"); override the handful too long for a label.
const SHORT_OVERRIDES: Record<string, { zh: string; en: string }> = {
  US: { zh: '美國', en: 'USA' },
  GB: { zh: '英國', en: 'UK' },
  AE: { zh: '阿聯', en: 'UAE' },
  KR: { zh: '南韓', en: 'S. Korea' },
  KP: { zh: '北韓', en: 'N. Korea' },
  RU: { zh: '俄羅斯', en: 'Russia' },
  CZ: { zh: '捷克', en: 'Czechia' },
  CD: { zh: '剛果（金）', en: 'DR Congo' },
};

const _displayNamesCache: Partial<Record<Lang, Intl.DisplayNames>> = {};

function displayNamesFor(lang: Lang): Intl.DisplayNames | null {
  const cached = _displayNamesCache[lang];
  if (cached) return cached;
  try {
    const locale = lang === 'zh' ? 'zh-Hant' : 'en';
    const dn = new Intl.DisplayNames([locale], { type: 'region' });
    _displayNamesCache[lang] = dn;
    return dn;
  } catch {
    return null;
  }
}

// country code (any case) -> short, localized country name. Falls back to
// the uppercased ISO code when Intl cannot resolve it.
export function countryName(code: string | undefined, lang: Lang): string {
  if (!code) return '';
  const cc = code.toUpperCase();
  const override = SHORT_OVERRIDES[cc];
  if (override) return override[lang];
  const dn = displayNamesFor(lang);
  try {
    return (dn && dn.of(cc)) || cc;
  } catch {
    return cc;
  }
}

// IANA zone -> "GMT+8" / "GMT-5:30". Empty string when the zone is blank
// or unrecognized.
export function formatGmtOffset(timezone: string | undefined): string {
  if (!timezone) return '';
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: timezone,
      timeZoneName: 'shortOffset',
    }).formatToParts(new Date());
    const tzName = parts.find((p) => p.type === 'timeZoneName')?.value ?? '';
    // shortOffset yields "GMT+8" / "GMT" (for UTC); normalize "GMT" → "GMT+0".
    return tzName === 'GMT' ? 'GMT+0' : tzName;
  } catch {
    return '';
  }
}
```

- [ ] **Step 2: Verify it typechecks and builds**

Run: `cd frontend && npm run build`
Expected: builds with no TypeScript error.

If `tsc` reports `Property 'DisplayNames' does not exist on type 'typeof Intl'` or rejects `'shortOffset'`, the project's `tsconfig.json` `lib` array is missing a recent ECMAScript lib — add `"ES2021"` (and `"ES2020.Intl"` if still needed) to `compilerOptions.lib`, then re-run the build. These APIs are present in the Electron runtime; only the type definitions lag.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/utils/geoFormat.ts
git commit -m "feat(bookmark): geoFormat util — country name + GMT offset via Intl"
```

---

### Task 11: Frontend `BookmarkGeoLine` component

No pytest equivalent — verification is the typecheck/build.

**Files:**
- Create: `frontend/src/components/BookmarkGeoLine.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/BookmarkGeoLine.tsx`:

```tsx
import React from 'react';
import { useI18n } from '../i18n';
import { countryName, formatGmtOffset } from '../utils/geoFormat';

interface BookmarkGeoLineProps {
  countryCode?: string;
  city?: string;
  timezone?: string;
}

// Line 2 of a bookmark row: flag · country · city · GMT offset.
// Each segment is omitted when its data is missing, so a bookmark the
// reconciliation sweep has not reached yet (or an ocean point) just
// shows fewer parts instead of empty separators.
export const BookmarkGeoLine: React.FC<BookmarkGeoLineProps> = ({
  countryCode,
  city,
  timezone,
}) => {
  const { lang } = useI18n();
  const country = countryName(countryCode, lang);
  const offset = formatGmtOffset(timezone);
  const textParts = [country, city, offset].filter(Boolean);

  if (!countryCode && textParts.length === 0) return null;

  return (
    <span
      style={{
        fontSize: 10,
        opacity: 0.55,
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        minWidth: 0,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}
    >
      {countryCode && (
        <img
          src={`https://flagcdn.com/w20/${countryCode}.png`}
          alt={countryCode.toUpperCase()}
          width={14}
          height={10}
          style={{
            borderRadius: 2,
            flexShrink: 0,
            boxShadow: '0 0 0 1px rgba(255,255,255,0.12)',
          }}
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = 'none';
          }}
        />
      )}
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {textParts.join(' · ')}
      </span>
    </span>
  );
};
```

- [ ] **Step 2: Verify it typechecks and builds**

Run: `cd frontend && npm run build`
Expected: builds with no TypeScript error.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/BookmarkGeoLine.tsx
git commit -m "feat(bookmark): BookmarkGeoLine component for the row's geo line"
```

---

### Task 12: Wire `BookmarkGeoLine` into BookmarkList's two row render sites

No pytest equivalent — verification is the typecheck/build plus the browser check in Task 14.

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx` (import; `Bookmark` interface ~line 14-25; search-results row ~line 1112-1137; group row ~line 1318-1356)

- [ ] **Step 1: Add the import**

In `frontend/src/components/BookmarkList.tsx`, the imports begin:

```tsx
import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useT, useI18n } from '../i18n';
import { getBookmarkUiState, setBookmarkUiState } from '../services/api';
```

Add one line after the `react-dom` import:

```tsx
import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { BookmarkGeoLine } from './BookmarkGeoLine';
import { useT, useI18n } from '../i18n';
import { getBookmarkUiState, setBookmarkUiState } from '../services/api';
```

- [ ] **Step 2: Extend the `Bookmark` interface**

The `Bookmark` interface currently reads:

```tsx
interface Bookmark {
  id?: string;
  name: string;
  lat: number;
  lng: number;
  category: string;
  // ISO 3166-1 alpha-2 (lowercase), optional. Rendered as a small flag
  // icon next to the bookmark name when present.
  country_code?: string;
  created_at?: string;  // ISO timestamp, used by 'date added' sort
  last_used_at?: string;  // ISO timestamp, used by 'last used' sort
}
```

Replace with:

```tsx
interface Bookmark {
  id?: string;
  name: string;
  lat: number;
  lng: number;
  category: string;
  // ISO 3166-1 alpha-2 (lowercase), optional. Rendered as a small flag
  // icon on the bookmark's geo line when present.
  country_code?: string;
  // Offline-resolved geo metadata (see backend geo_offline.resolve).
  timezone?: string;  // IANA zone, e.g. 'Asia/Taipei'
  city?: string;      // nearest notable city
  region?: string;    // admin1 — province / state / county
  created_at?: string;  // ISO timestamp, used by 'date added' sort
  last_used_at?: string;  // ISO timestamp, used by 'last used' sort
}
```

- [ ] **Step 3: Rewrite the search-results row**

In the search-results block, this fragment (~line 1112-1137) renders the category dot, a standalone flag image, and the name + monospace meta line:

```tsx
                  <div
                    style={{
                      width: 8, height: 8, borderRadius: '50%',
                      background: resolveColor(bm.category), flexShrink: 0,
                    }}
                    title={displayCat(bm.category)}
                  />
                  {bm.country_code && (
                    <img
                      src={`https://flagcdn.com/w20/${bm.country_code}.png`}
                      alt={bm.country_code.toUpperCase()}
                      title={bm.country_code.toUpperCase()}
                      width={14}
                      height={10}
                      style={{ borderRadius: 2, flexShrink: 0, boxShadow: '0 0 0 1px rgba(255,255,255,0.12)' }}
                      onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                    />
                  )}
                  <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                    <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {bm.name}
                    </span>
                    <span style={{ fontSize: 10, opacity: 0.55, fontFamily: 'monospace' }}>
                      {displayCat(bm.category)} · {bm.lat.toFixed(5)}, {bm.lng.toFixed(5)}
                    </span>
                  </div>
```

Replace it with — drop the standalone flag, swap the meta line for `BookmarkGeoLine`, and move category + coords + region into the column's `title` tooltip:

```tsx
                  <div
                    style={{
                      width: 8, height: 8, borderRadius: '50%',
                      background: resolveColor(bm.category), flexShrink: 0,
                    }}
                    title={displayCat(bm.category)}
                  />
                  <div
                    style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minWidth: 0 }}
                    title={`${displayCat(bm.category)} · ${bm.lat.toFixed(5)}, ${bm.lng.toFixed(5)}${bm.region ? ` · ${bm.region}` : ''}`}
                  >
                    <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {bm.name}
                    </span>
                    <BookmarkGeoLine countryCode={bm.country_code} city={bm.city} timezone={bm.timezone} />
                  </div>
```

- [ ] **Step 4: Rewrite the group row**

In the category-group block, this fragment (~line 1318-1356) renders a standalone flag image, then either an edit input or the name + monospace coords line:

```tsx
                    {bm.country_code && (
                      <img
                        src={`https://flagcdn.com/w20/${bm.country_code}.png`}
                        alt={bm.country_code.toUpperCase()}
                        title={bm.country_code.toUpperCase()}
                        width={14}
                        height={10}
                        style={{ borderRadius: 2, flexShrink: 0, boxShadow: '0 0 0 1px rgba(255,255,255,0.12)' }}
                        onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                      />
                    )}
                    {editingId === bm.id ? (
                      <input
                        type="text"
                        className="search-input"
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && bm.id) {
                            onBookmarkEdit(bm.id, { name: editName });
                            setEditingId(null);
                          }
                          if (e.key === 'Escape') setEditingId(null);
                        }}
                        onBlur={() => setEditingId(null)}
                        onClick={(e) => e.stopPropagation()}
                        style={{ flex: 1, padding: '2px 4px', fontSize: 11 }}
                        autoFocus
                      />
                    ) : (
                      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                        <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {bm.name}
                        </span>
                        <span style={{ fontSize: 10, opacity: 0.55, fontFamily: 'monospace' }}>
                          {bm.lat.toFixed(5)}, {bm.lng.toFixed(5)}
                        </span>
                      </div>
                    )}
```

Replace it with — drop the standalone flag, swap the meta line for `BookmarkGeoLine`, and move coords + region into the column's `title` tooltip:

```tsx
                    {editingId === bm.id ? (
                      <input
                        type="text"
                        className="search-input"
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && bm.id) {
                            onBookmarkEdit(bm.id, { name: editName });
                            setEditingId(null);
                          }
                          if (e.key === 'Escape') setEditingId(null);
                        }}
                        onBlur={() => setEditingId(null)}
                        onClick={(e) => e.stopPropagation()}
                        style={{ flex: 1, padding: '2px 4px', fontSize: 11 }}
                        autoFocus
                      />
                    ) : (
                      <div
                        style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minWidth: 0 }}
                        title={`${bm.lat.toFixed(5)}, ${bm.lng.toFixed(5)}${bm.region ? ` · ${bm.region}` : ''}`}
                      >
                        <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {bm.name}
                        </span>
                        <BookmarkGeoLine countryCode={bm.country_code} city={bm.city} timezone={bm.timezone} />
                      </div>
                    )}
```

- [ ] **Step 5: Verify it typechecks and builds**

Run: `cd frontend && npm run build`
Expected: builds with no TypeScript error.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/BookmarkList.tsx
git commit -m "feat(bookmark): two-line bookmark row with flag/country/city/offset"
```

---

### Task 13: App.tsx — pass the new fields through and drop the redundant reverse-geocode calls

The backend now resolves geo fields offline on create, on coordinate-edit, and via the startup sweep, so the frontend's add-time and edit-time reverse-geocode calls (`api.reverseGeocode` at App.tsx ~1560 and ~1619) are dead weight. This task removes both. Removing the edit-time backfill goes one step beyond the design's "drop the add-time race" line, but it is the direct consequence of the approved enrich table (the backend re-resolves on a coordinate change) — it is not new scope. No pytest equivalent — verification is the build plus the browser check in Task 14.

**Files:**
- Modify: `frontend/src/App.tsx` (`bookmarks` prop mapping ~1529-1538; `onBookmarkAdd` ~1551-1575; `onBookmarkEdit` ~1577-1632)

- [ ] **Step 1: Pass the new fields into the `bookmarks` prop**

The `bookmarks` prop mapping currently reads:

```tsx
          bookmarks={bm.bookmarks.map((b: any) => ({
            id: b.id,
            name: b.name,
            lat: b.lat,
            lng: b.lng,
            category: bm.categories.find(c => c.id === b.category_id)?.name || t('bm.default'),
            country_code: b.country_code || '',
            created_at: b.created_at || '',
            last_used_at: b.last_used_at || '',
          }))}
```

Replace with:

```tsx
          bookmarks={bm.bookmarks.map((b: any) => ({
            id: b.id,
            name: b.name,
            lat: b.lat,
            lng: b.lng,
            category: bm.categories.find(c => c.id === b.category_id)?.name || t('bm.default'),
            country_code: b.country_code || '',
            timezone: b.timezone || '',
            city: b.city || '',
            region: b.region || '',
            created_at: b.created_at || '',
            last_used_at: b.last_used_at || '',
          }))}
```

- [ ] **Step 2: Simplify `onBookmarkAdd`**

It currently reads:

```tsx
          onBookmarkAdd={(b: any) => {
            const cat = bm.categories.find(c => c.name === b.category)
            // Reverse-geocode first so custom-coordinate bookmarks also get a
            // country flag. If lookup fails or takes too long, save without
            // one so the user isn't blocked.
            ;(async () => {
              let cc = ''
              try {
                const geo = await Promise.race([
                  api.reverseGeocode(b.lat, b.lng),
                  new Promise<null>((resolve) => setTimeout(() => resolve(null), 4000)),
                ])
                if (geo && (geo as any).country_code) {
                  cc = String((geo as any).country_code).toLowerCase()
                }
              } catch { /* ignore */ }
              bm.createBookmark({
                name: b.name,
                lat: b.lat,
                lng: b.lng,
                category_id: cat?.id || 'default',
                country_code: cc,
              } as any)
            })()
          }}
```

Replace with:

```tsx
          onBookmarkAdd={(b: any) => {
            const cat = bm.categories.find(c => c.name === b.category)
            // Country / timezone / city / region are resolved offline by
            // the backend on create — no online reverse-geocode needed.
            bm.createBookmark({
              name: b.name,
              lat: b.lat,
              lng: b.lng,
              category_id: cat?.id || 'default',
            } as any)
          }}
```

- [ ] **Step 3: Simplify `onBookmarkEdit`**

It currently reads (App.tsx ~1577-1632):

```tsx
          onBookmarkEdit={(id: string, data: any) => {
            // BookmarkList emits UI-shape patches ({name}, or {name,lat,lng,category}).
            // Backend PUT /api/bookmarks requires the full Bookmark schema with
            // category_id (not category name), so merge the patch onto the
            // original and translate category name -> id before sending.
            //
            // If orig is missing (bm.bookmarks briefly out of sync with a
            // background refresh), fall back to the patch data — the edit
            // dialog supplies a full bookmark via spread so we still have the
            // fields we need. This prevents the silent-noop save the user saw
            // after running Fix Flags.
            const orig = bm.bookmarks.find(b => b.id === id)
            const base: any = orig ? { ...orig } : { ...data, id }
            const patch: any = base
            if (data.name != null) patch.name = data.name
            if (data.lat != null) patch.lat = data.lat
            if (data.lng != null) patch.lng = data.lng
            if (data.category != null) {
              const cat = bm.categories.find(c => c.name === data.category)
              if (cat) patch.category_id = cat.id
            }
            // Flag-backfill-on-save: trigger reverse-geocode whenever we'd
            // benefit from a fresh country_code — i.e. coords moved (stale),
            // OR the bookmark never had a flag to begin with (legacy entry
            // from before the feature shipped). Runs in the background so
            // the save itself feels instant.
            const refLat = orig ? orig.lat : base.lat
            const refLng = orig ? orig.lng : base.lng
            const coordsChanged =
              (data.lat != null && data.lat !== refLat) ||
              (data.lng != null && data.lng !== refLng)
            const flagMissing = !base.country_code
            const needsGeocode = coordsChanged || flagMissing
            if (coordsChanged) {
              // Coordinates moved — clear the stale flag so UI doesn't show
              // the wrong country while the async lookup is in flight.
              patch.country_code = ''
            }
            if (needsGeocode) {
              ;(async () => {
                try {
                  const geo = await Promise.race([
                    api.reverseGeocode(patch.lat, patch.lng),
                    new Promise<null>((resolve) => setTimeout(() => resolve(null), 4000)),
                  ])
                  const cc = geo && (geo as any).country_code
                    ? String((geo as any).country_code).toLowerCase()
                    : ''
                  if (cc) {
                    await bm.updateBookmark(id, { ...patch, country_code: cc } as any)
                  }
                } catch { /* ignore */ }
              })()
            }
            bm.updateBookmark(id, patch)
          }}
```

Replace the whole handler with:

```tsx
          onBookmarkEdit={(id: string, data: any) => {
            // BookmarkList emits UI-shape patches ({name}, or {name,lat,lng,category}).
            // Backend PUT /api/bookmarks requires the full Bookmark schema with
            // category_id (not category name), so merge the patch onto the
            // original and translate category name -> id before sending.
            //
            // If orig is missing (bm.bookmarks briefly out of sync with a
            // background refresh), fall back to the patch data — the edit
            // dialog supplies a full bookmark via spread so we still have the
            // fields we need.
            //
            // The backend re-resolves country / timezone / city / region
            // offline whenever the coordinates change, so the frontend no
            // longer reverse-geocodes here.
            const orig = bm.bookmarks.find(b => b.id === id)
            const base: any = orig ? { ...orig } : { ...data, id }
            const patch: any = base
            if (data.name != null) patch.name = data.name
            if (data.lat != null) patch.lat = data.lat
            if (data.lng != null) patch.lng = data.lng
            if (data.category != null) {
              const cat = bm.categories.find(c => c.name === data.category)
              if (cat) patch.category_id = cat.id
            }
            bm.updateBookmark(id, patch)
          }}
```

- [ ] **Step 4: Verify it typechecks and builds**

Run: `cd frontend && npm run build`
Expected: builds with no TypeScript error.

If `tsc` reports `api` is now unused, check whether `api` is still referenced elsewhere in App.tsx (`reverseGeocode` is called at ~line 352, 623, 705 for unrelated features, so the `api` import almost certainly stays). Only remove the import if `tsc` confirms it is genuinely unused.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(bookmark): pass geo fields through; drop redundant reverse-geocode"
```

---

### Task 14: Full verification

No commit — this task confirms the whole feature works end to end.

- [ ] **Step 1: Run the complete backend test suite**

Run: `cd backend && .venv/bin/python -m pytest tests/ -v`
Expected: every test passes — the new `test_bookmark_geo_schema.py`, `test_geo_offline.py`, `test_bookmark_enrich.py`, and every pre-existing test (no regressions).

- [ ] **Step 2: Build the frontend**

Run: `cd frontend && npm run build`
Expected: builds with no TypeScript error.

- [ ] **Step 3: Manual smoke test**

Start the app (`./start.sh` or `make dev`) and confirm:
- The bookmark panel shows two-line rows: the name on line 1; flag · country · city · `GMT±N` on line 2.
- Hovering a row shows coordinates (and `region`) in the tooltip.
- Adding a bookmark at a custom coordinate gives it a flag / country / city / offset within a moment (no 4-second wait).
- Editing a bookmark's coordinates updates its flag / country / city / offset.
- A pre-existing (legacy) bookmark that had no flag now shows one after the app restarts (the startup sweep filled it).
- A bookmark on open ocean shows just the name with no geo line — no crash, no broken layout.
- Switching the UI language flips the country name between Chinese and English.

- [ ] **Step 4: (Recommended, before release) Frozen-build smoke test**

The PyInstaller bundling of `timezonefinder` data + `backend/data/geo/` cannot be fully verified without a build. Before shipping, run `./build-installer-mac.sh` (or the Windows `.spec` build), launch the packaged app, and confirm bookmarks still get geo fields — i.e. `geo_offline` found its data inside the frozen bundle.

---

## Self-Review

**Spec coverage:** Data model → Task 1. Backend offline resolver → Tasks 3 (data) + 4 (resolver). Unified enrich entry point → Tasks 5 (function) + 6 (create) + 7 (update) + 8 (import) + 9 (sweep). Frontend rendering → Tasks 10 (utils) + 11 (component) + 12 (BookmarkList) + 13 (App.tsx). Build & dependencies → Task 2. Testing → per-task tests + Task 14. Every spec section maps to a task.

**Deviations from the design doc, deliberate:**
- The country-name source is `Intl.DisplayNames` rather than a static ~250-entry table — same outcome, no table to bundle (Task 10).
- The formatting code lives at `frontend/src/utils/geoFormat.ts` (a util alongside the existing `utils/categoryStatus`) rather than `frontend/src/i18n/countries.ts`, and also holds the offset formatter.
- A new `BookmarkGeoLine.tsx` component is introduced so the two row render sites share one implementation — the design's file list named only `BookmarkList.tsx`.
- `build-installer-mac.sh` needs no edit: it invokes the shared `.spec`, so Task 2's spec change covers macOS.
- Task 13 also simplifies `onBookmarkEdit` (not just the add path) — the direct consequence of the backend re-resolving on a coordinate change.

**Type consistency:** `resolve()` returns `(country_code, timezone, city, region)`; `enrich_bookmark` unpacks it in that order. `enrich_bookmark(bm, *, force=False) -> bool` is called as `enrich_bookmark(bm)` (create, import, sweep) and `enrich_bookmark(bm, force=True)` (update). `geoFormat.ts` exports `countryName(code, lang)` + `formatGmtOffset(timezone)`, both consumed by `BookmarkGeoLine`, whose props `{ countryCode, city, timezone }` match the call sites in `BookmarkList.tsx`. The generator writes `admin1_names.json` keys as `"{cc_lower}.{admin1}"`; `geo_offline.resolve` looks them up with `f"{city_cc}.{_admin1[i]}"` where `city_cc` is the lowercase `cc` from `cities5000.json` — consistent.

**Placeholder scan:** No TBD/TODO, no "add error handling", no "similar to Task N" — every code step shows complete code, every command shows its expected output.
