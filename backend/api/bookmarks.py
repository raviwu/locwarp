import json
import logging
import re
import sys
from datetime import date as _date
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from api.deps import get_bookmark_manager, get_engine_registry
from models.schemas import Bookmark, BookmarkCategory, BookmarkMoveRequest

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date_range(start: str | None, end: str | None) -> None:
    """Validate ISO date strings on BookmarkCategory.

    ``None`` (the key was omitted from a partial update) and ``""`` (the client
    is clearing the date) are both "nothing supplied, nothing to validate" and
    are allowed on either side. Non-empty values must match YYYY-MM-DD and be
    valid calendar dates. When both are supplied, start must be <= end — the
    cross-field check reads only what this request carries, never the stored
    value on the other side.

    Raises HTTPException(422) on any violation.
    """
    for label, val in (("start_date", start), ("end_date", end)):
        if not val:
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


class BookmarkUiState(BaseModel):
    # Both optional: a POST updates only the fields it carries, so the
    # frontend can persist expand and hide independently without one
    # request clobbering the other.
    expanded_categories: list[str] | None = None
    hidden_categories: list[str] | None = None


class BookmarkUpdate(BaseModel):
    # Partial-update body for PUT /{bookmark_id}, same idiom as
    # BookmarkUiState above. All-Optional because Bookmark's own defaults are
    # concrete (address="", category_id="default", country_code=""), so a body
    # parsed as Bookmark cannot tell an omitted key from a deliberate blank and
    # silently wipes a field the client never touched. Omit a field to leave it
    # alone; send "" to clear it.
    name: str | None = None
    lat: float | None = None
    lng: float | None = None
    address: str | None = None
    category_id: str | None = None
    country_code: str | None = None


class BookmarkCategoryUpdate(BaseModel):
    # Partial-update body for PUT /categories/{cat_id}, same idiom as
    # BookmarkUpdate above and for the same reason: BookmarkCategory's defaults
    # (color="#6c8cff", start_date="", end_date="") are concrete, so a body
    # parsed as BookmarkCategory blanks every key the client left out. Omit a
    # field to leave it alone; send "" to clear a date.
    name: str | None = None
    color: str | None = None
    start_date: str | None = None
    end_date: str | None = None


# ── Bookmarks ─────────────────────────────────────────────

@router.get("", response_model=dict)
async def list_bookmarks(bm=Depends(get_bookmark_manager)):
    return {
        "categories": [c.model_dump() for c in bm.list_categories()],
        "bookmarks": [b.model_dump() for b in bm.list_bookmarks()],
    }


@router.post("", response_model=Bookmark)
async def create_bookmark(bookmark: Bookmark, bm=Depends(get_bookmark_manager)):
    return bm.create_bookmark(
        name=bookmark.name,
        lat=bookmark.lat,
        lng=bookmark.lng,
        address=bookmark.address,
        category_id=bookmark.category_id,
        country_code=bookmark.country_code,
    )


@router.put("/{bookmark_id}", response_model=Bookmark)
async def update_bookmark(bookmark_id: str, bookmark: BookmarkUpdate, bm=Depends(get_bookmark_manager)):
    """Apply only the fields the client actually sent.

    ``exclude_unset`` drops the keys the body omitted; the service drops any
    explicit ``null``. A body that changes nothing writes nothing at all —
    ``updated_at`` included — so pressing Save without editing anything cannot
    out-vote a fresher, still-unsynced edit on another machine.
    """
    updated = bm.update_bookmark(bookmark_id, **bookmark.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return updated


@router.delete("/{bookmark_id}")
async def delete_bookmark(bookmark_id: str, bm=Depends(get_bookmark_manager)):
    if not bm.delete_bookmark(bookmark_id):
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"status": "deleted"}


@router.post("/move")
async def move_bookmarks(req: BookmarkMoveRequest, bm=Depends(get_bookmark_manager)):
    count = bm.move_bookmarks(req.bookmark_ids, req.target_category_id)
    return {"moved": count}


# ── Categories ────────────────────────────────────────────

@router.get("/categories", response_model=list[BookmarkCategory])
async def list_categories(bm=Depends(get_bookmark_manager)):
    return bm.list_categories()


@router.post("/categories", response_model=BookmarkCategory)
async def create_category(cat: BookmarkCategory, bm=Depends(get_bookmark_manager)):
    _validate_date_range(cat.start_date, cat.end_date)
    return bm.create_category(
        name=cat.name,
        color=cat.color,
        start_date=cat.start_date,
        end_date=cat.end_date,
    )


@router.put("/categories/{cat_id}", response_model=BookmarkCategory)
async def update_category(cat_id: str, cat: BookmarkCategoryUpdate, bm=Depends(get_bookmark_manager)):
    """Apply only the fields the client actually sent.

    ``exclude_unset`` drops the keys the body omitted; ``update_category``
    drops any explicit ``null``. An omitted date therefore stays as stored
    instead of being blanked by a schema default the client never chose.
    """
    _validate_date_range(cat.start_date, cat.end_date)
    updated = bm.update_category(cat_id, **cat.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Category not found")
    return updated


@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: str, cascade: bool = False, bm=Depends(get_bookmark_manager)):
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
    bm=Depends(get_bookmark_manager),
):
    import json as _json
    from services import bookmark_export

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


@router.get("/store")
async def export_bookmark_store(bm=Depends(get_bookmark_manager)):
    """Full-fidelity store dump — categories, bookmarks AND tombstones.

    Distinct from GET "" (the UI list, a frozen {categories, bookmarks}
    contract) and from GET /export (a user-facing shareable artifact with
    per-category scoping and markdown/geojson/csv formats). Backups need
    deletion history: a snapshot without tombstones resurrects deleted
    bookmarks when restored against a peer that still holds them alive.
    Consumed by scripts/desktop_backup.py.

    export_json() takes a blocking threading.Lock that the watcher thread holds
    across a merge, so it runs off the event loop.
    """
    import asyncio

    body = await asyncio.to_thread(bm.export_json)
    return Response(content=body, media_type="application/json")


@router.post("/import")
async def import_bookmarks(data: dict, bm=Depends(get_bookmark_manager)):
    import json as _json
    from services.bookmark_import import detect_and_import, InvalidImportError

    try:
        result = detect_and_import(bm, _json.dumps(data))
    except InvalidImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


# ── UI state (persists per-category collapse in ~/.locwarp/settings.json) ──

@router.get("/ui-state")
async def get_bookmark_ui_state(registry=Depends(get_engine_registry)):
    return registry.get_bookmark_ui_state()


@router.post("/ui-state")
async def set_bookmark_ui_state(req: BookmarkUiState, registry=Depends(get_engine_registry)):
    registry.set_bookmark_ui_state(
        expanded=req.expanded_categories, hidden=req.hidden_categories
    )
    return {"status": "ok", **registry.get_bookmark_ui_state()}


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


class CatalogSyncResult(BaseModel):
    """Mirrors the TS `CatalogSyncResult` in frontend/src/services/api.ts.

    Declared as a response_model so a backend/TS key drift fails at startup
    instead of silently reaching the toast as `undefined`.
    """

    added: int
    updated: int
    resurrected: int
    kept_local: int
    conflicts: int


@router.post("/catalog/sync", response_model=CatalogSyncResult)
async def sync_catalog(bm=Depends(get_bookmark_manager)):
    """Force-sync the bundled catalog into the local store.

    Catalog ids are authoritative for entries this device deleted — their
    tombstones lose the merge contest because the imported items get
    ``updated_at = now()``. For entries that are still present, the catalog is
    authoritative **per field**: a correction to lat / lng / name / address /
    category propagates only where the user has not edited that field locally
    (see ``BookmarkManager.import_catalog``). Local items whose ids are not in
    the catalog are untouched.

    ``kept_local`` counts records whose local edit was preserved, and
    ``conflicts`` the subset where the catalog had also moved.

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
    return bm.import_catalog(text)
