"""Bookmark and category management with JSON file persistence."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from config import BOOKMARKS_FILE, get_bookmarks_path
from models.schemas import Bookmark, BookmarkCategory, BookmarkStore
from services.bookmark_merge import diff_store, merge_local_wins
from services.json_safe import safe_load_json, safe_write_json

logger = logging.getLogger(__name__)

# Keep a reference to the config default so _bookmarks_path() can detect
# when tests (or other callers) have monkeypatched the module-level name.
_CONFIG_DEFAULT_BOOKMARKS_FILE = BOOKMARKS_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BookmarkManager:
    """CRUD manager for bookmarks and categories.

    State is persisted to :data:`BOOKMARKS_FILE` (JSON) on every write
    operation.
    """

    def __init__(self) -> None:
        self.store = BookmarkStore(
            categories=[
                BookmarkCategory(
                    id="default",
                    name="預設",
                    color="#6c8cff",
                    sort_order=0,
                    created_at=_now_iso(),
                )
            ],
            bookmarks=[],
        )
        self._last_loaded_mtime: float = 0.0
        self._last_loaded_snapshot: BookmarkStore = BookmarkStore(categories=[], bookmarks=[])
        self._load()
        self._watcher_observer: Observer | None = None
        self._watcher_debounce_timer: threading.Timer | None = None
        self._on_external_change: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load bookmarks from the JSON file, if it exists.

        Uses ``safe_load_json`` so a parse failure does not silently
        discard the user's data: the corrupt file is renamed aside as
        ``bookmarks.json.bak-<timestamp>`` before we fall back to the
        default empty store. Otherwise the next ``_save()`` would
        overwrite the original file with an empty bookmark list.
        """
        data = safe_load_json(self._bookmarks_path())
        if data is None:
            logger.info("No bookmark file (or unreadable); using defaults")
            return
        try:
            self.store = BookmarkStore(**data)
            logger.info(
                "Loaded %d bookmarks in %d categories",
                len(self.store.bookmarks),
                len(self.store.categories),
            )
            self._update_snapshot()
        except Exception as exc:
            logger.warning("Bookmark payload failed schema validation: %s", exc)

    def _save(self) -> None:
        """Persist the current store to disk, merging any external changes.

        If the disk mtime is newer than the snapshot we hold, another
        process (or another device via cloud sync) wrote to the file
        between our last load and this save. In that case we diff our
        in-memory store against the snapshot, reload the fresh disk
        state, reapply the diff on top, and only then write.
        """
        path = self._bookmarks_path()
        try:
            current_mtime = path.stat().st_mtime
        except FileNotFoundError:
            current_mtime = 0.0

        if current_mtime > self._last_loaded_mtime:
            self._reconcile_from_disk()

        payload = json.loads(self.store.model_dump_json())
        safe_write_json(path, payload)
        self._update_snapshot()

    def _reconcile_from_disk(self) -> None:
        """Merge external on-disk changes into self.store using local-wins.

        No-op (besides updating snapshot) when on-disk content is invalid
        or unreadable — better to keep our in-memory copy than to wipe it
        in response to a transient read error.
        """
        path = self._bookmarks_path()
        try:
            if path.stat().st_size == 0:
                return
        except FileNotFoundError:
            return
        raw = safe_load_json(path)
        if not isinstance(raw, dict):
            return
        try:
            fresh = BookmarkStore(**raw)
        except Exception as exc:
            logger.warning("Disk payload failed schema validation during reconcile: %s", exc)
            return
        local_diff = diff_store(current=self.store, baseline=self._last_loaded_snapshot)
        self.store = merge_local_wins(remote=fresh, local_diff=local_diff)

    def _update_snapshot(self) -> None:
        """Capture current store as the baseline for future diffs.

        Records the disk mtime at the moment we know self.store is in sync
        with the file. A deep copy ensures later in-memory edits do not
        mutate the snapshot.
        """
        path = self._bookmarks_path()
        try:
            self._last_loaded_mtime = path.stat().st_mtime
        except FileNotFoundError:
            self._last_loaded_mtime = 0.0
        self._last_loaded_snapshot = BookmarkStore(
            **json.loads(self.store.model_dump_json())
        )

    def _bookmarks_path(self) -> Path:
        # Allow tests to override by patching the module-level BOOKMARKS_FILE.
        # _CONFIG_DEFAULT_BOOKMARKS_FILE holds the value captured at import
        # time; if tests have patched the module-level name, it will differ.
        if BOOKMARKS_FILE is not _CONFIG_DEFAULT_BOOKMARKS_FILE:
            return Path(BOOKMARKS_FILE)
        return get_bookmarks_path()

    # ------------------------------------------------------------------
    # File watcher
    # ------------------------------------------------------------------

    def start_watcher(self, on_change: Callable[[], None]) -> None:
        """Begin watching the bookmarks file for external modifications.

        *on_change* is invoked (no args) on the watcher thread AFTER
        self.store has been reconciled with disk. Callers are responsible
        for marshalling onto whatever loop/thread they need (e.g. asyncio
        via run_coroutine_threadsafe).
        """
        self.stop_watcher()
        path = self._bookmarks_path()
        parent = path.parent
        if not parent.exists():
            logger.warning("Bookmark folder does not exist; watcher not started: %s", parent)
            return
        self._on_external_change = on_change

        manager = self

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.is_directory:
                    return
                if Path(event.src_path) != manager._bookmarks_path():
                    return
                manager._schedule_reconcile()

            on_created = on_modified

            def on_moved(self, event):
                if event.is_directory:
                    return
                bm = manager._bookmarks_path()
                if Path(event.src_path) != bm and Path(getattr(event, "dest_path", "")) != bm:
                    return
                manager._schedule_reconcile()

        self._watcher_observer = Observer()
        self._watcher_observer.schedule(_Handler(), str(parent), recursive=False)
        self._watcher_observer.start()
        logger.info("Bookmark watcher started on %s", parent)

    def stop_watcher(self) -> None:
        if self._watcher_debounce_timer is not None:
            self._watcher_debounce_timer.cancel()
            self._watcher_debounce_timer = None
        if self._watcher_observer is not None:
            try:
                self._watcher_observer.stop()
                self._watcher_observer.join(timeout=2.0)
            except Exception:
                logger.exception("Failed to stop bookmark watcher cleanly")
            self._watcher_observer = None

    def _schedule_reconcile(self) -> None:
        """Debounce rapid mtime events from a single sync burst."""
        if self._watcher_debounce_timer is not None:
            self._watcher_debounce_timer.cancel()
        self._watcher_debounce_timer = threading.Timer(0.5, self._watcher_tick)
        self._watcher_debounce_timer.daemon = True
        self._watcher_debounce_timer.start()

    def _watcher_tick(self) -> None:
        try:
            path = self._bookmarks_path()
            try:
                current_mtime = path.stat().st_mtime
            except FileNotFoundError:
                return  # transient absence (iCloud cloud-only eviction); retry on next event
            if current_mtime <= self._last_loaded_mtime:
                return  # self-echo or already reconciled
            before_payload = self.store.model_dump_json()
            self._reconcile_from_disk()
            after_payload = self.store.model_dump_json()
            if before_payload != after_payload:
                # Persist the merged state so disk reflects local edits we
                # may have reapplied on top of the remote update.
                payload = json.loads(after_payload)
                safe_write_json(path, payload)
                self._update_snapshot()
                if self._on_external_change is not None:
                    try:
                        self._on_external_change()
                    except Exception:
                        logger.exception("on_external_change callback raised")
            else:
                self._update_snapshot()  # still resync mtime
        except Exception:
            logger.exception("Bookmark watcher tick failed")

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    def create_category(
        self,
        name: str,
        color: str = "#6c8cff",
        start_date: str = "",
        end_date: str = "",
    ) -> BookmarkCategory:
        """Create and return a new category."""
        max_order = max((c.sort_order for c in self.store.categories), default=-1)
        cat = BookmarkCategory(
            id=str(uuid.uuid4()),
            name=name,
            color=color,
            sort_order=max_order + 1,
            created_at=_now_iso(),
            start_date=start_date,
            end_date=end_date,
        )
        self.store.categories.append(cat)
        self._save()
        return cat

    def update_category(
        self,
        cat_id: str,
        name: str | None = None,
        color: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> BookmarkCategory | None:
        """Update a category's mutable fields. Returns ``None`` if not found.

        ``None`` for any field means "do not modify"; pass an empty string
        to clear ``start_date`` or ``end_date``.
        """
        cat = self._find_category(cat_id)
        if cat is None:
            return None
        if name is not None:
            cat.name = name
        if color is not None:
            cat.color = color
        if start_date is not None:
            cat.start_date = start_date
        if end_date is not None:
            cat.end_date = end_date
        self._save()
        return cat

    def delete_category(self, cat_id: str, cascade: bool = False) -> dict | bool:
        """Delete a category.

        With ``cascade=False`` (default), bookmarks in the deleted category are
        moved to ``default``. With ``cascade=True``, those bookmarks are
        deleted along with the category.

        The ``default`` category cannot be deleted in either mode.

        Returns ``False`` when the category is missing or is ``default``.
        Otherwise returns ``{"deleted": True, "deleted_bookmarks": N}``.
        """
        if cat_id == "default":
            logger.warning("Cannot delete the default category")
            return False

        cat = self._find_category(cat_id)
        if cat is None:
            return False

        deleted_count = 0
        if cascade:
            kept = []
            for bm in self.store.bookmarks:
                if bm.category_id == cat_id:
                    deleted_count += 1
                else:
                    kept.append(bm)
            self.store.bookmarks = kept
        else:
            for bm in self.store.bookmarks:
                if bm.category_id == cat_id:
                    bm.category_id = "default"

        self.store.categories = [c for c in self.store.categories if c.id != cat_id]
        self._save()
        return {"deleted": True, "deleted_bookmarks": deleted_count}

    def list_categories(self) -> list[BookmarkCategory]:
        return sorted(self.store.categories, key=lambda c: c.sort_order)

    def _find_category(self, cat_id: str) -> BookmarkCategory | None:
        return next((c for c in self.store.categories if c.id == cat_id), None)

    # ------------------------------------------------------------------
    # Bookmarks
    # ------------------------------------------------------------------

    def create_bookmark(
        self,
        name: str,
        lat: float,
        lng: float,
        address: str = "",
        category_id: str = "default",
        country_code: str = "",
    ) -> Bookmark:
        """Create a new bookmark."""
        # Validate category
        if self._find_category(category_id) is None:
            category_id = "default"

        now = _now_iso()
        bm = Bookmark(
            id=str(uuid.uuid4()),
            name=name,
            lat=lat,
            lng=lng,
            address=address,
            category_id=category_id,
            created_at=now,
            last_used_at=now,
            country_code=country_code.lower(),
        )
        self.store.bookmarks.append(bm)
        self._save()
        return bm

    def update_bookmark(self, bm_id: str, **kwargs: object) -> Bookmark | None:
        """Update a bookmark's fields. Returns ``None`` if not found."""
        bm = self._find_bookmark(bm_id)
        if bm is None:
            return None

        allowed = {"name", "lat", "lng", "address", "category_id", "last_used_at", "country_code"}
        for key, value in kwargs.items():
            if key in allowed and value is not None:
                setattr(bm, key, value)

        self._save()
        return bm

    def delete_bookmark(self, bm_id: str) -> bool:
        """Delete a bookmark by ID."""
        before = len(self.store.bookmarks)
        self.store.bookmarks = [b for b in self.store.bookmarks if b.id != bm_id]
        if len(self.store.bookmarks) < before:
            self._save()
            return True
        return False

    def list_bookmarks(self) -> list[Bookmark]:
        return list(self.store.bookmarks)

    def move_bookmarks(
        self,
        bookmark_ids: list[str],
        target_category_id: str,
    ) -> int:
        """Move multiple bookmarks to *target_category_id*.

        Returns the number of bookmarks actually moved.
        """
        if self._find_category(target_category_id) is None:
            logger.warning("Target category %s does not exist", target_category_id)
            return 0

        moved = 0
        ids_set = set(bookmark_ids)
        for bm in self.store.bookmarks:
            if bm.id in ids_set and bm.category_id != target_category_id:
                bm.category_id = target_category_id
                moved += 1

        if moved:
            self._save()
        return moved

    def _find_bookmark(self, bm_id: str) -> Bookmark | None:
        return next((b for b in self.store.bookmarks if b.id == bm_id), None)

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def export_json(self) -> str:
        """Serialise the entire store to a JSON string."""
        return self.store.model_dump_json(indent=2)

    def import_json(self, data: str) -> dict:
        """Import bookmarks (and optionally categories) from a JSON string.

        Merges into the existing store -- duplicates by ID are skipped.

        Returns ``{"imported": N, "skipped": M}`` so callers can distinguish
        new entries from collisions. Returns ``{"imported": 0, "skipped": 0}``
        on parse failure.
        """
        try:
            incoming = BookmarkStore(**json.loads(data))
        except Exception as exc:
            logger.error("Invalid bookmark JSON: %s", exc)
            return {"imported": 0, "skipped": 0}

        existing_cat_ids = {c.id for c in self.store.categories}
        for cat in incoming.categories:
            if cat.id not in existing_cat_ids:
                self.store.categories.append(cat)
                existing_cat_ids.add(cat.id)

        existing_bm_ids = {b.id for b in self.store.bookmarks}
        imported = 0
        skipped = 0
        for bm in incoming.bookmarks:
            if bm.id not in existing_bm_ids:
                # Ensure the bookmark's category exists
                if bm.category_id not in existing_cat_ids:
                    bm.category_id = "default"
                self.store.bookmarks.append(bm)
                existing_bm_ids.add(bm.id)
                imported += 1
            else:
                skipped += 1

        if imported:
            self._save()
        logger.info("Imported %d bookmarks (%d skipped as duplicates)", imported, skipped)
        return {"imported": imported, "skipped": skipped}
