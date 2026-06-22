"""Composition-root factories: build the infra JsonStore + the service manager.

Lives in bootstrap (the only ring allowed to import every ring) so services
never import infra. Used by main.load_state, cloud_sync enable/disable, and tests.
"""
from infra.persistence.json_store import JsonStore
from models.schemas import BookmarkStore, RouteStore
from services.bookmarks import BookmarkManager, _bookmarks_path_default
from services.route_store import RouteManager, _routes_path_default, _inject_default_category


def make_bookmark_manager(path_provider=None) -> BookmarkManager:
    repo = JsonStore(BookmarkStore, path_provider or _bookmarks_path_default)
    return BookmarkManager(repo=repo)


def make_route_manager(path_provider=None) -> RouteManager:
    repo = JsonStore(RouteStore, path_provider or _routes_path_default, post_load=_inject_default_category)
    return RouteManager(repo=repo)
