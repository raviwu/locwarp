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

from models.schemas import Bookmark, BookmarkCategory, BookmarkMoveRequest, CloudSyncStatus, CloudSyncEnableRequest
from services.cloud_sync import detect_icloud_path, setup_sync_folder, migrate_bookmarks
import config as _config

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


def _merge_local_into_remote(local: Path, remote: Path) -> None:
    """Merge local bookmarks into the remote file using local-wins union.

    Called when enabling cloud sync and both files already exist with
    different content (e.g. re-enabling after settings were reset).

    Strategy: union of local + remote; for the same ID, local wins.
    Remote-only items (added by another device) are preserved.
    """
    import json
    from models.schemas import BookmarkStore
    from services.json_safe import safe_load_json, safe_write_json

    try:
        local_data = safe_load_json(local)
        remote_data = safe_load_json(remote)
        if not isinstance(local_data, dict) or not isinstance(remote_data, dict):
            return
        local_store = BookmarkStore(**local_data)
        remote_store = BookmarkStore(**remote_data)
    except Exception as exc:
        logger.warning("cloud sync merge: could not parse stores, skipping merge: %s", exc)
        return

    # Union merge: start with remote, overwrite with local on same ID.
    # Remote-only items (from other devices) are preserved.
    cats = {c.id: c for c in remote_store.categories}
    cats.update({c.id: c for c in local_store.categories})
    bms = {b.id: b for b in remote_store.bookmarks}
    bms.update({b.id: b for b in local_store.bookmarks})

    merged = BookmarkStore(categories=list(cats.values()), bookmarks=list(bms.values()))
    payload = json.loads(merged.model_dump_json())
    safe_write_json(remote, payload)
    logger.info(
        "cloud sync enable: merged local (%d bm) + remote (%d bm) → %d bm",
        len(local_store.bookmarks), len(remote_store.bookmarks), len(merged.bookmarks),
    )


router = APIRouter(prefix="/api/bookmarks", tags=["bookmarks"])


def _bm():
    from main import app_state
    return app_state.bookmark_manager


class BookmarkUiState(BaseModel):
    expanded_categories: list[str] | None = None


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
    return {"expanded_categories": app_state._bookmark_expanded_categories}


@router.post("/ui-state")
async def set_bookmark_ui_state(req: BookmarkUiState):
    from main import app_state
    app_state._bookmark_expanded_categories = (
        list(req.expanded_categories) if req.expanded_categories is not None else []
    )
    app_state.save_settings()
    return {"status": "ok", "expanded_categories": app_state._bookmark_expanded_categories}


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


# ── Cloud sync ────────────────────────────────────────────

@router.get("/cloud-sync/status", response_model=CloudSyncStatus)
async def cloud_sync_status():
    from main import app_state
    bm = _bm()
    current = bm._bookmarks_path()
    # Use _config._DEFAULT_BOOKMARKS_FILE at call time so monkeypatched values
    # in tests (pointing at tmp_path) compare correctly against the live default.
    default_path = _config._DEFAULT_BOOKMARKS_FILE
    is_enabled = current != default_path
    sync_folder = str(current.parent) if is_enabled else None
    icloud = detect_icloud_path()
    return CloudSyncStatus(
        enabled=is_enabled,
        detected_icloud_path=str(icloud) if icloud else None,
        current_path=str(current),
        sync_folder=sync_folder,
        bookmark_count=len(bm.list_bookmarks()),
        category_count=len(bm.list_categories()),
        prompt_dismissed=app_state._cloud_sync_dismissed,
    )


@router.post("/cloud-sync/enable", response_model=CloudSyncStatus)
async def cloud_sync_enable(req: CloudSyncEnableRequest):
    from main import app_state
    parent: Path | None = None
    if req.folder:
        parent = Path(req.folder)
    else:
        parent = detect_icloud_path()
    if parent is None:
        raise HTTPException(400, "No iCloud Drive detected and no custom folder provided")

    try:
        target_folder = setup_sync_folder(parent)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(400, str(exc))

    new_path = target_folder / "bookmarks.json"
    src = app_state.bookmark_manager._bookmarks_path()
    try:
        migrate_bookmarks(src=src, dst=new_path)
    except FileExistsError:
        # Both local and remote exist with different content.
        # Merge: apply local bookmarks on top of remote (local-wins) so the
        # user doesn't lose work done on this device since the last sync.
        _merge_local_into_remote(src, new_path)

    app_state._bookmarks_path = str(new_path)
    app_state.save_settings()

    # Re-init the manager so it reloads from the new path and rebinds watcher
    from services.bookmarks import BookmarkManager
    app_state.bookmark_manager = BookmarkManager()
    app_state.restart_bookmark_watcher()

    return await cloud_sync_status()


@router.post("/cloud-sync/disable", response_model=CloudSyncStatus)
async def cloud_sync_disable():
    from main import app_state
    bm = app_state.bookmark_manager
    current = bm._bookmarks_path()
    default_path = _config._DEFAULT_BOOKMARKS_FILE
    if current == default_path:
        return await cloud_sync_status()

    try:
        migrate_bookmarks(src=current, dst=default_path)
    except FileExistsError:
        logger.warning(
            "Cloud sync %s: destination already has different bookmarks; "
            "adopting remote copy, local file left at %s",
            "disable",
            current,
        )

    app_state._bookmarks_path = None
    app_state.save_settings()

    from services.bookmarks import BookmarkManager
    app_state.bookmark_manager = BookmarkManager()
    app_state.restart_bookmark_watcher()

    return await cloud_sync_status()


@router.post("/cloud-sync/dismiss-prompt", response_model=CloudSyncStatus)
async def cloud_sync_dismiss_prompt():
    from main import app_state
    app_state._cloud_sync_dismissed = True
    app_state.save_settings()
    return await cloud_sync_status()
