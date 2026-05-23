import json
import logging
import re
import sys
from datetime import date as _date
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from models.schemas import Bookmark, BookmarkCategory, BookmarkMoveRequest

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date_range(start: str, end: str) -> None:
    """Validate ISO date strings on BookmarkCategory.

    Empty strings are allowed on either side. Non-empty values must match
    YYYY-MM-DD and be valid calendar dates. When both are non-empty,
    start must be <= end.

    Raises HTTPException(422) on any violation.
    """
    for label, val in (("start_date", start), ("end_date", end)):
        if val == "":
            continue
        if not _ISO_DATE_RE.match(val):
            raise HTTPException(422, f"{label} must be YYYY-MM-DD or empty")
        try:
            _date.fromisoformat(val)
        except ValueError:
            raise HTTPException(422, f"{label} is not a valid calendar date")
    if start and end and start > end:
        raise HTTPException(422, "start_date must be <= end_date")


def _catalog_path() -> Path:
    """Resolve catalog.json in both dev and PyInstaller-packaged layouts.

    Mirrors the convention used by ``api.phone_control._phone_page_path``.
    """
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "static" / "catalog.json")
    candidates.append(Path(__file__).resolve().parent.parent / "static" / "catalog.json")
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


router = APIRouter(prefix="/api/bookmarks", tags=["bookmarks"])


def _bm():
    from main import app_state
    return app_state.bookmark_manager


class BookmarkUiState(BaseModel):
    # Both optional: a POST updates only the fields it carries, so the
    # frontend can persist expand and hide independently without one
    # request clobbering the other.
    expanded_categories: list[str] | None = None
    hidden_categories: list[str] | None = None


# ── Bookmarks ─────────────────────────────────────────────

@router.get("", response_model=dict)
async def list_bookmarks():
    bm = _bm()
    return {
        "categories": [c.model_dump() for c in bm.list_categories()],
        "bookmarks": [b.model_dump() for b in bm.list_bookmarks()],
    }


@router.post("", response_model=Bookmark)
async def create_bookmark(bookmark: Bookmark):
    bm = _bm()
    return bm.create_bookmark(
        name=bookmark.name,
        lat=bookmark.lat,
        lng=bookmark.lng,
        address=bookmark.address,
        category_id=bookmark.category_id,
        country_code=bookmark.country_code,
    )


@router.put("/{bookmark_id}", response_model=Bookmark)
async def update_bookmark(bookmark_id: str, bookmark: Bookmark):
    bm = _bm()
    updated = bm.update_bookmark(
        bookmark_id,
        name=bookmark.name,
        lat=bookmark.lat,
        lng=bookmark.lng,
        address=bookmark.address,
        category_id=bookmark.category_id,
        country_code=bookmark.country_code,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return updated


@router.delete("/{bookmark_id}")
async def delete_bookmark(bookmark_id: str):
    bm = _bm()
    if not bm.delete_bookmark(bookmark_id):
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"status": "deleted"}


@router.post("/move")
async def move_bookmarks(req: BookmarkMoveRequest):
    bm = _bm()
    count = bm.move_bookmarks(req.bookmark_ids, req.target_category_id)
    return {"moved": count}


# ── Categories ────────────────────────────────────────────

@router.get("/categories", response_model=list[BookmarkCategory])
async def list_categories():
    bm = _bm()
    return bm.list_categories()


@router.post("/categories", response_model=BookmarkCategory)
async def create_category(cat: BookmarkCategory):
    _validate_date_range(cat.start_date, cat.end_date)
    bm = _bm()
    return bm.create_category(
        name=cat.name,
        color=cat.color,
        start_date=cat.start_date,
        end_date=cat.end_date,
    )


@router.put("/categories/{cat_id}", response_model=BookmarkCategory)
async def update_category(cat_id: str, cat: BookmarkCategory):
    _validate_date_range(cat.start_date, cat.end_date)
    bm = _bm()
    updated = bm.update_category(
        cat_id,
        name=cat.name,
        color=cat.color,
        start_date=cat.start_date,
        end_date=cat.end_date,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Category not found")
    return updated


@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: str, cascade: bool = False):
    bm = _bm()
    if cat_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete default category")
    result = bm.delete_category(cat_id, cascade=cascade)
    if result is False:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"status": "deleted", "deleted_bookmarks": result["deleted_bookmarks"]}


# ── Import / Export ───────────────────────────────────────

ExportFormat = Literal["json", "markdown", "geojson", "csv"]

_FORMAT_TO_MEDIA = {
    "json": "application/json",
    "markdown": "text/markdown; charset=utf-8",
    "geojson": "application/geo+json",
    "csv": "text/csv; charset=utf-8",
}

_FORMAT_TO_FILENAME_EXT = {
    "json": "json",
    "markdown": "md",
    "geojson": "geojson",
    "csv": "csv",
}


@router.get("/export")
async def export_bookmarks(
    category_id: str | None = None,
    format: ExportFormat = "json",
):
    import json as _json
    from services import bookmark_export

    bm = _bm()
    store = bm.store

    if category_id is not None and not any(c.id == category_id for c in store.categories):
        raise HTTPException(status_code=404, detail="Category not found")

    if format == "json":
        body = _json.dumps(bookmark_export.to_json(store, category_id=category_id), ensure_ascii=False, indent=2)
        content = body
    elif format == "markdown":
        content = bookmark_export.to_markdown(store, category_id=category_id)
    elif format == "geojson":
        content = _json.dumps(bookmark_export.to_geojson(store, category_id=category_id), ensure_ascii=False, indent=2)
    elif format == "csv":
        content = bookmark_export.to_csv(store, category_id=category_id)

    from urllib.parse import quote

    cat_slug = "bookmarks"
    if category_id is not None:
        cat = next(c for c in store.categories if c.id == category_id)
        cat_slug = cat.name.replace("/", "_")
    ext = _FORMAT_TO_FILENAME_EXT[format]
    filename_utf8 = f"{cat_slug}.{ext}"
    # Content-Disposition header value must be latin-1 safe; use RFC 5987
    # filename* for non-ASCII names.
    try:
        filename_utf8.encode("latin-1")
        disposition = f'attachment; filename="{filename_utf8}"'
    except UnicodeEncodeError:
        encoded = quote(filename_utf8, safe="")
        disposition = f"attachment; filename*=UTF-8''{encoded}"

    return Response(
        content=content,
        media_type=_FORMAT_TO_MEDIA[format],
        headers={"Content-Disposition": disposition},
    )


@router.post("/import")
async def import_bookmarks(data: dict):
    import json as _json
    from services.bookmark_import import detect_and_import, InvalidImportError

    bm = _bm()
    try:
        result = detect_and_import(bm, _json.dumps(data))
    except InvalidImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


# ── UI state (persists per-category collapse in ~/.locwarp/settings.json) ──

@router.get("/ui-state")
async def get_bookmark_ui_state():
    from main import app_state
    return {
        "expanded_categories": app_state._bookmark_expanded_categories,
        "hidden_categories": app_state._bookmark_hidden_categories,
    }


@router.post("/ui-state")
async def set_bookmark_ui_state(req: BookmarkUiState):
    from main import app_state
    # Per-field update: only touch a field the request actually carries.
    if req.expanded_categories is not None:
        app_state._bookmark_expanded_categories = list(req.expanded_categories)
    if req.hidden_categories is not None:
        app_state._bookmark_hidden_categories = list(req.hidden_categories)
    app_state.save_settings()
    return {
        "status": "ok",
        "expanded_categories": app_state._bookmark_expanded_categories,
        "hidden_categories": app_state._bookmark_hidden_categories,
    }


# ── Catalog (bundled curated event seed) ──────────────────

@router.get("/catalog")
async def get_catalog():
    """Return the curated event catalog bundled with the build.

    404 when the file is missing (build did not include it; UI hides
    the Refresh button). 500 when the file is unreadable or malformed.
    """
    path = _catalog_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Catalog not bundled")
    try:
        text = path.read_text(encoding="utf-8")
        json.loads(text)  # validate
    except (OSError, ValueError):
        raise HTTPException(status_code=500, detail="Catalog unreadable or malformed")
    return Response(content=text, media_type="application/json")


@router.post("/catalog/sync")
async def sync_catalog():
    """Force-sync the bundled catalog into the local store.

    Catalog ids are authoritative — entries previously deleted on this
    device come back (their tombstones lose the merge contest because
    the imported items get ``updated_at = now()``), and catalog
    corrections to lat / lng / name propagate. Local items whose ids
    are not in the catalog are untouched.

    Distinct from ``POST /import`` which keeps skip-existing semantics
    for user-supplied file imports (typical "restore backup" intent).
    """
    path = _catalog_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Catalog not bundled")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Catalog unreadable: {exc}")
    return _bm().import_catalog(text)
