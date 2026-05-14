"""list_bookmarks / list_routes return a human-sensible order.

merge_stores persists items id-sorted (UUID order) for a deterministic,
commutative file. That order is meaningless to a human, so the read path
re-sorts by category sort_order, then created_at within a category, then
id as a stable tiebreak. Bookmarks and routes get identical treatment.
"""

import pytest

from models.schemas import (
    Bookmark, BookmarkCategory, Coordinate, RouteCategory, SavedRoute,
)
from services.bookmarks import BookmarkManager
from services.route_store import RouteManager


@pytest.fixture
def bm(tmp_path, monkeypatch):
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", object())
    return BookmarkManager()


@pytest.fixture
def rm(tmp_path, monkeypatch):
    monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("services.route_store._CONFIG_DEFAULT_ROUTES_FILE", object())
    return RouteManager()


def _b(id, name, cat, created_at):
    return Bookmark(id=id, name=name, lat=0.0, lng=0.0,
                    category_id=cat, created_at=created_at)


def _r(id, name, cat, created_at):
    return SavedRoute(id=id, name=name, category_id=cat, created_at=created_at,
                      waypoints=[Coordinate(lat=1.0, lng=1.0),
                                 Coordinate(lat=2.0, lng=2.0)])


# ── bookmarks ─────────────────────────────────────────────────────────────


def test_list_bookmarks_sorted_by_category_then_created_at(bm):
    bm.store.categories = [
        BookmarkCategory(id="cat-b", name="B", sort_order=2),
        BookmarkCategory(id="cat-a", name="A", sort_order=1),
    ]
    # Inserted in a deliberately scrambled order (mimics merge's id-sort).
    bm.store.bookmarks = [
        _b("z", "b-late", "cat-b", "2026-05-14T03:00:00+00:00"),
        _b("a", "a-early", "cat-a", "2026-05-14T01:00:00+00:00"),
        _b("m", "b-early", "cat-b", "2026-05-14T02:00:00+00:00"),
    ]
    assert [x.name for x in bm.list_bookmarks()] == ["a-early", "b-early", "b-late"]


def test_list_bookmarks_unknown_category_sorts_last(bm):
    bm.store.categories = [BookmarkCategory(id="cat-a", name="A", sort_order=1)]
    bm.store.bookmarks = [
        _b("orphan", "orphan", "gone-category", "2026-05-14T01:00:00+00:00"),
        _b("normal", "normal", "cat-a", "2026-05-14T02:00:00+00:00"),
    ]
    assert [x.name for x in bm.list_bookmarks()] == ["normal", "orphan"]


def test_list_bookmarks_id_breaks_created_at_ties(bm):
    bm.store.categories = [BookmarkCategory(id="default", name="D", sort_order=0)]
    bm.store.bookmarks = [
        _b("b-id", "second", "default", "2026-05-14T01:00:00+00:00"),
        _b("a-id", "first", "default", "2026-05-14T01:00:00+00:00"),
    ]
    assert [x.name for x in bm.list_bookmarks()] == ["first", "second"]


# ── routes (identical treatment) ──────────────────────────────────────────


def test_list_routes_sorted_by_category_then_created_at(rm):
    rm.store.categories = [
        RouteCategory(id="cat-b", name="B", sort_order=2),
        RouteCategory(id="cat-a", name="A", sort_order=1),
    ]
    rm.store.routes = [
        _r("z", "b-late", "cat-b", "2026-05-14T03:00:00+00:00"),
        _r("a", "a-early", "cat-a", "2026-05-14T01:00:00+00:00"),
        _r("m", "b-early", "cat-b", "2026-05-14T02:00:00+00:00"),
    ]
    assert [x.name for x in rm.list_routes()] == ["a-early", "b-early", "b-late"]


def test_list_routes_unknown_category_sorts_last(rm):
    rm.store.categories = [RouteCategory(id="cat-a", name="A", sort_order=1)]
    rm.store.routes = [
        _r("orphan", "orphan", "gone-category", "2026-05-14T01:00:00+00:00"),
        _r("normal", "normal", "cat-a", "2026-05-14T02:00:00+00:00"),
    ]
    assert [x.name for x in rm.list_routes()] == ["normal", "orphan"]
