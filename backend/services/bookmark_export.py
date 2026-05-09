"""Per-format bookmark exporters.

Each function takes the in-memory ``BookmarkStore`` plus an optional
``category_id`` and returns a ``str`` (markdown / csv / json) or ``dict``
(geojson / json structured form).

Whole-store exports concatenate per-category output where the format
permits it. The Markdown emitter emits one ``## <category-name>`` section
per category, blank-line separated.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from models.schemas import Bookmark, BookmarkCategory, BookmarkStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_name(name: str) -> str:
    return name.replace("\n", " ").replace("\r", " ")


def _category_bookmarks(store: BookmarkStore, cat_id: str) -> list[Bookmark]:
    return [b for b in store.bookmarks if b.category_id == cat_id]


def _markdown_section(cat: BookmarkCategory, bms: Iterable[Bookmark], exported_at: str) -> str:
    lines = [f"## {cat.name}", "", f"Exported {exported_at}", "", "---", ""]
    bm_list = list(bms)
    for i, bm in enumerate(bm_list):
        lines.append(_safe_name(bm.name))
        lines.append(f"{bm.lat:.6f},{bm.lng:.6f}")
        if i != len(bm_list) - 1:
            lines.append("")
    return "\n".join(lines) + "\n"


def to_markdown(
    store: BookmarkStore,
    category_id: str | None = None,
    exported_at: str | None = None,
) -> str:
    exported_at = exported_at or _now_iso()
    if category_id is not None:
        cat = next((c for c in store.categories if c.id == category_id), None)
        if cat is None:
            raise KeyError(category_id)
        return _markdown_section(cat, _category_bookmarks(store, cat.id), exported_at)

    sections = []
    for cat in sorted(store.categories, key=lambda c: c.sort_order):
        sections.append(_markdown_section(cat, _category_bookmarks(store, cat.id), exported_at))
    return "\n".join(sections)


def to_geojson(store: BookmarkStore, category_id: str | None = None) -> dict:
    if category_id is not None:
        cat = next((c for c in store.categories if c.id == category_id), None)
        if cat is None:
            raise KeyError(category_id)
        cats = {cat.id: cat}
        bms = _category_bookmarks(store, cat.id)
        name = cat.name
    else:
        cats = {c.id: c for c in store.categories}
        bms = list(store.bookmarks)
        name = "LocWarp Bookmarks"

    features = []
    for bm in bms:
        cat_name = cats.get(bm.category_id).name if bm.category_id in cats else ""
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [bm.lng, bm.lat]},
            "properties": {
                "name": bm.name,
                "category": cat_name,
                "country_code": bm.country_code,
            },
        })

    return {"type": "FeatureCollection", "name": name, "features": features}


def to_csv(store: BookmarkStore, category_id: str | None = None) -> str:
    import csv
    import io

    cats_by_id = {c.id: c for c in store.categories}
    if category_id is not None:
        if category_id not in cats_by_id:
            raise KeyError(category_id)
        bms = _category_bookmarks(store, category_id)
    else:
        bms = list(store.bookmarks)

    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM for Excel
    writer = csv.DictWriter(buf, fieldnames=["name", "lat", "lng", "category"])
    writer.writeheader()
    for bm in bms:
        cat_name = cats_by_id.get(bm.category_id).name if bm.category_id in cats_by_id else ""
        writer.writerow({
            "name": bm.name,
            "lat": f"{bm.lat:.6f}",
            "lng": f"{bm.lng:.6f}",
            "category": cat_name,
        })
    return buf.getvalue()
