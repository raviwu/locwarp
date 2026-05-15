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
