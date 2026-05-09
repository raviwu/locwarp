"""Format-detecting bookmark import.

Accepts three top-level shapes:
  1. Full-store: ``{"categories": [...], "bookmarks": [...]}``
  2. Single-category JSON: ``{"_meta": {...}, "category": {...}, "bookmarks": [...]}``
  3. GeoJSON FeatureCollection (added in Task 9)
"""
from __future__ import annotations

import json
import logging
import uuid

from models.schemas import Bookmark, BookmarkCategory

logger = logging.getLogger(__name__)


class InvalidImportError(ValueError):
    """Raised when the import payload does not match any supported shape."""


def detect_and_import(manager, raw: str | bytes) -> dict:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidImportError(f"Not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise InvalidImportError("Top-level payload must be a JSON object")

    if "categories" in payload and "bookmarks" in payload:
        return _import_full_store(manager, payload)
    if "_meta" in payload and "category" in payload and "bookmarks" in payload:
        return _import_single_category(manager, payload)

    if payload.get("type") == "FeatureCollection" and isinstance(payload.get("features"), list):
        return _import_geojson(manager, payload)

    raise InvalidImportError("Unrecognised import shape")


def _import_full_store(manager, payload: dict) -> dict:
    # Reuse the existing path that merges by id (skips duplicates).
    text = json.dumps(payload)
    imported = manager.import_json(text)
    return {"scope": "full_store", "imported": imported, "skipped": 0}


def _import_single_category(manager, payload: dict) -> dict:
    raw_cat = payload["category"]
    raw_bms = payload.get("bookmarks", [])

    existing_ids = {c.id for c in manager.store.categories}
    incoming_id = raw_cat.get("id") or str(uuid.uuid4())
    if incoming_id in existing_ids:
        new_id = str(uuid.uuid4())
    else:
        new_id = incoming_id

    cat = BookmarkCategory(
        id=new_id,
        name=raw_cat["name"],
        color=raw_cat.get("color", "#6c8cff"),
        sort_order=raw_cat.get("sort_order", 0),
        created_at=raw_cat.get("created_at", ""),
    )
    manager.store.categories.append(cat)

    existing_bm_ids = {b.id for b in manager.store.bookmarks}
    imported = 0
    for raw_bm in raw_bms:
        bm_id = raw_bm.get("id") or str(uuid.uuid4())
        if bm_id in existing_bm_ids:
            bm_id = str(uuid.uuid4())
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
        existing_bm_ids.add(bm_id)
        imported += 1

    manager._save()  # always persist (we appended a category)

    return {"scope": "category", "imported": imported, "skipped": 0}


def _import_geojson(manager, payload: dict) -> dict:
    name = payload.get("name") or "Imported"
    cat = manager.create_category(name=name)

    existing_bm_ids = {b.id for b in manager.store.bookmarks}
    imported = 0
    skipped = 0
    for feat in payload.get("features", []):
        try:
            geom = feat.get("geometry") or {}
            if geom.get("type") != "Point":
                skipped += 1
                continue
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                skipped += 1
                continue
            lng, lat = float(coords[0]), float(coords[1])
            props = feat.get("properties") or {}
            bm_name = props.get("name") or "(unnamed)"

            bm_id = str(uuid.uuid4())
            while bm_id in existing_bm_ids:
                bm_id = str(uuid.uuid4())

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
            existing_bm_ids.add(bm_id)
            imported += 1
        except (KeyError, TypeError, ValueError):
            skipped += 1

    manager._save()
    return {"scope": "geojson", "imported": imported, "skipped": skipped}
