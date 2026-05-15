# Bookmark — Geo Info (Flag · Country · City/Region · Timezone) — Design

**Date:** 2026-05-15
**Status:** Approved (design) — pending spec review, then implementation plan

## Problem

A bookmark shows a country flag only when its `country_code` is set. That field
is populated once, at add time, by an online reverse-geocode that races a
4-second timeout (`frontend/src/App.tsx` ~line 1551). So legacy bookmarks,
offline-added bookmarks, and bookmarks whose geocode timed out carry no flag at
all — only *some* bookmarks show one.

The user wants every bookmark — old ones included — to show country flag, a
short country name, city/region, and timezone, reliably.

## Scope

Backend-led: an offline geo resolver, three new schema fields, and a single
enrich pipeline that every write path funnels through. Plus one frontend
rendering change. One PR.

## Decisions

Recorded with rationale, since each was a fork during design:

1. **Resolve offline, not via online APIs** — bundle `timezonefinder`. Offline
   gives 100% coverage including legacy bookmarks, deterministic results, no
   rate limits, no network dependency. The online path is the direct cause of
   today's partial coverage.
2. **`TimezoneFinderL` (lightweight), not the full dataset** — label-level
   accuracy is enough; ~5MB of data instead of ~50MB.
3. **Country code derived from the IANA zone via a static map**, not a
   reverse-geocoding library — `reverse_geocoder` and `reverse_geocode` both
   pull in scipy (~80MB unpacked). The zone-to-country map is ~10KB.
4. **City/region from a bundled GeoNames `cities5000` extract + a numpy
   nearest-neighbor search** — scipy-free, since `timezonefinder` already
   bundles numpy. A brute-force vectorized search over ~55k cities runs in
   under a millisecond.
5. **Store raw fields only** (`country_code`, `timezone`, `city`, `region`);
   derive flag, country name, and GMT offset at render time — single source of
   truth, localizable, DST-correct.
6. **The startup backfill does not bump `updated_at`; an explicit GPS edit
   does** — the backfill writes derived, deterministic data, so synced devices
   converge without it; a coordinate edit is a real user mutation.

---

## 1 — Data model

`Bookmark` (`backend/models/schemas.py:231`) gains three fields, additive, in
the same style as the existing `country_code` and `updated_at`:

```python
timezone: str = ""   # IANA zone, e.g. 'Asia/Taipei'. Empty = ocean / no zone.
city: str = ""       # Nearest notable city, ASCII name, e.g. 'Kaohsiung'.
region: str = ""     # admin1 — province / state / county, e.g. 'California'.
```

`country_code` (already present, line 243) and `address` (the online
reverse-geocode street result, used for auto-naming) stay unchanged. Country
name, flag, and GMT offset are derived at render time and never stored.

## 2 — Backend offline resolver

New module `backend/services/geo_offline.py`, one entry point:

```
resolve(lat, lng) -> (country_code, timezone, city, region)
```

Resolution runs in order, and the IANA zone gates everything:

1. `TimezoneFinderL().timezone_at(lat, lng)` → IANA zone. If it returns `None`
   (open ocean, no timezone polygon), `resolve` returns all four fields empty
   and stops — a far-away nearest-city must not stand in for an ocean point.
2. `zone_to_country.json` → `country_code`, from the zone.
3. GeoNames `cities5000` extract + numpy nearest-neighbor → nearest city row →
   `city` (ASCII name) and its admin1 code. The city row also carries a country
   code, the fallback for step 2 when the zone is absent from the map.
4. `admin1_names.json` → `region`, from the admin1 code + country code.

An empty field — an ocean point, or a gap in a lookup table — makes the UI skip
that element; the next startup sweep retries it, cheap and offline.

Bundled data, committed under `backend/data/geo/`:

| File | Size | Source |
|------|------|--------|
| `zone_to_country.json` | ~10KB | IANA `zone1970.tab` |
| `cities5000` packed extract | a few MB | GeoNames `cities5000` — asciiname, lat, lng, country code, admin1 code only |
| `admin1_names.json` | ~150KB | GeoNames `admin1CodesASCII.txt` |

A generator script under `scripts/` rebuilds these from the raw GeoNames and
IANA sources. The committed packed files keep the build itself offline.

## 3 — Unified enrich entry point

One function, `enrich_bookmark(bm, force=False)`, fills `country_code`,
`timezone`, `city`, and `region`. By default it fills only empty fields
(idempotent); `force=True` re-resolves all four. Every write path calls it:

| Trigger | Behaviour | Bumps `updated_at` |
|---------|-----------|--------------------|
| Create bookmark (`BookmarkManager.create_bookmark`) | Resolve offline, authoritative | Yes — new record |
| Update bookmark, lat/lng changed (PUT) | `force=True` — re-resolve all four | Yes — user mutation |
| Update bookmark, lat/lng unchanged | Skip enrich | — |
| Import bookmarks | Enrich each (fill empties) | Yes — new records |
| Startup reconciliation sweep | Enrich every bookmark (fill empties only), write once via the safe-write path | **No** — derived, deterministic, converges across synced devices |

The shared entry point makes the guarantee structural: the startup sweep
catches every historical gap, and create / update / import all run the same
resolver, so no write path can leave the fields stale or empty. The sweep
skipping `updated_at` avoids sync churn — each synced device resolves identical
values from the same coordinates, so they converge without a conflict.

On the create path, the frontend today races a 4-second timeout against
`api.reverseGeocode()` to obtain `country_code`. With the backend resolving
offline, that race goes away; the frontend keeps an online reverse-geocode only
where it feeds `address` / auto-naming.

## 4 — Frontend rendering

`frontend/src/components/BookmarkList.tsx` — the bookmark row becomes two lines:

```
●  Lotus Pond
   🇹🇼 Taiwan · Kaohsiung · GMT+8
```

- Line 1: category dot + bookmark name.
- Line 2: flag · country name · city · GMT offset.
- **Flag** — the existing `flagcdn.com` image (`flagcdn.com/w20/{cc}.png`), now
  shown for every bookmark since every bookmark has a `country_code`. `onError`
  still hides it offline.
- **Country name** — a new static table `frontend/src/i18n/countries.ts`,
  country code → `{ zh, en }` short names (~250 entries). English uses short
  common names, with the long ones hand-shortened (USA, UK, UAE). The displayed
  name follows the active i18n language.
- **GMT offset** — `Intl.DateTimeFormat(locale, { timeZone, timeZoneName:
  'shortOffset' })` derives `GMT+8` from the IANA zone: no bundled data,
  DST-correct. A small fallback covers runtimes without `shortOffset`.
- **Coordinates and `region`** move to the hover tooltip / expanded view. Five
  elements on line 2 is too dense; coordinates read poorly, and `region` is
  context rather than the primary label.

Both render sites get the two-line treatment — the main list row (~line 1110)
and the expanded detail (~line 1318). The expanded detail additionally shows
`region` and coordinates.

## 5 — Build & dependencies

- `backend/requirements.txt`: add `timezonefinder` (pulls `numpy`, `h3`,
  `cffi`, `flatbuffers`).
- `backend/locwarp-backend.spec`: remove `'numpy'` from the `excludes` list
  (line 82) — `timezonefinder` needs it. Add the `timezonefinder` (L-variant)
  data and `backend/data/geo/` to `datas`. Optionally prune the full-precision
  `timezonefinder` data, keeping only what `TimezoneFinderL` loads.
- `build-installer-mac.sh`: confirm the macOS build bundles the same data.
- Size: `TimezoneFinderL` data ~5MB + the geo extract a few MB + `numpy` ~30MB
  unpacked ≈ **+~40MB** to the bundle.

## Files touched

| File | Change |
|------|--------|
| `backend/models/schemas.py` | `Bookmark` gains `timezone`, `city`, `region` |
| `backend/services/geo_offline.py` | New — `resolve(lat, lng)`; loads `timezonefinder` + bundled geo data |
| `backend/services/bookmarks.py` | `enrich_bookmark`; `create_bookmark` and import call it; `update_bookmark` detects a lat/lng change and re-resolves with `force=True`; the startup reconciliation sweep |
| `backend/main.py` | Invoke the startup reconciliation sweep |
| `backend/data/geo/` | New — `zone_to_country.json`, `cities5000` packed extract, `admin1_names.json` |
| `scripts/` | New generator that rebuilds `backend/data/geo/` from raw GeoNames + IANA sources |
| `backend/requirements.txt` | Add `timezonefinder` |
| `backend/locwarp-backend.spec` | Un-exclude `numpy`; bundle `timezonefinder` + `backend/data/geo/` |
| `build-installer-mac.sh` | Bundle the same data on macOS |
| `frontend/src/i18n/countries.ts` | New — country code → `{ zh, en }` short names |
| `frontend/src/components/BookmarkList.tsx` | Two-line row; line 2 = flag · country · city · offset; coords + region to tooltip/expand |
| `frontend/src/App.tsx` | Drop the add-time reverse-geocode-for-country race (~line 1551); keep reverse-geocode that feeds auto-naming |

## Testing

**Backend** (pytest, alongside the existing `backend/tests/test_bookmark*.py`):

- `geo_offline.resolve` returns the correct country / zone / city / region for
  known coordinates (Taipei, Kaohsiung, New York, London), and empty fields for
  an ocean point.
- `enrich_bookmark` fills only empty fields by default; `force=True`
  re-resolves all four.
- `create_bookmark` populates all four fields.
- PUT with a lat/lng change re-resolves and bumps `updated_at`; PUT without a
  coordinate change leaves the fields and `updated_at` untouched.
- Import enriches each imported bookmark.
- The startup sweep is idempotent, fills only empties, and does not bump
  `updated_at`.

**Frontend**: no test harness exists; verify in the browser — every bookmark
shows flag + country + city + offset, the two-line layout holds, an ocean-point
bookmark degrades gracefully, and editing a bookmark's coordinates updates its
labels.

## Out of scope

- **Localizing city and region names** — needs the GeoNames `alternateNames`
  dataset (very large), unlike the ~250-entry country table.
- **Offline flag images** — `flagcdn.com` stays; it renders on Windows and
  degrades gracefully offline.
- **Repointing `/api/geocode/timezone`** (the simulation-status display) to the
  offline resolver — it would remove the hardcoded TimezoneDB API key, but it
  is a separate concern.
