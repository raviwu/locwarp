"""Offline lat/lng → (country_code, timezone, city, region) resolver.

Backs the bookmark geo-info feature. timezonefinder maps the point to an
IANA zone; a bundled GeoNames cities5000 extract supplies the nearest
city + admin1 region; zone_to_country.json maps the zone to a country.
Everything is offline and deterministic — no network, no rate limits.

resolve() never raises: any failure (missing data, import error, an
unexpected None from timezonefinder) yields ("", "", "", "") and the
caller leaves the bookmark's geo fields empty for the next pass.
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

    All-empty only when the offline tables are unavailable. (TimezoneFinderL
    covers the whole globe with Etc/GMT±N bands, so open-ocean points still
    resolve — to an Etc zone plus the nearest territory.) country_code is
    lowercase ISO 3166-1 alpha-2; timezone is an IANA zone string.
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
