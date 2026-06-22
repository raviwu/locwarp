"""Composition-root factories: build the infra JsonStore + the service manager.

Lives in bootstrap (the only ring allowed to import every ring) so services
never import infra. Used by main.load_state, cloud_sync enable/disable, and tests.
"""
import config
from infra.persistence.backup_store import FileBackupStore
from infra.persistence.json_store import JsonStore
from models.schemas import BookmarkStore, RouteStore
from services.backup_service import BackupService
from services.bookmarks import BookmarkManager, _bookmarks_path_default
from services.route_store import RouteManager, _routes_path_default, _inject_default_category


def make_bookmark_manager(path_provider=None) -> BookmarkManager:
    repo = JsonStore(BookmarkStore, path_provider or _bookmarks_path_default)
    return BookmarkManager(repo=repo)


def make_route_manager(path_provider=None) -> RouteManager:
    repo = JsonStore(RouteStore, path_provider or _routes_path_default, post_load=_inject_default_category)
    return RouteManager(repo=repo)


def make_backup_service(
    snapshot_provider, dir_provider=None, retention_hours=None, source="in-process"
) -> BackupService:
    """Wire the FileBackupStore (infra) into the BackupService (services).
    dir_provider/retention default to config lazily so test isolation applies."""
    repo = FileBackupStore(dir_provider or (lambda: config.BACKUP_DIR))
    return BackupService(
        repo,
        snapshot_provider,
        retention_hours if retention_hours is not None else config.BACKUP_RETENTION_HOURS,
        source,
    )
