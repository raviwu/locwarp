from datetime import datetime, timezone

from models.schemas import Bookmark, BookmarkCategory, BookmarkStore
from services.bookmark_merge import diff_store, StoreDiff


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


_DEFAULT_CATEGORY = BookmarkCategory(id="default", name="預設", color="#000", sort_order=0, created_at="2026-05-11T00:00:00+00:00")


def _store(categories=None, bookmarks=None) -> BookmarkStore:
    return BookmarkStore(
        categories=categories or [_DEFAULT_CATEGORY],
        bookmarks=bookmarks or [],
    )


def _bm(id: str, name: str = "X", lat: float = 1.0, lng: float = 2.0, category_id: str = "default") -> Bookmark:
    return Bookmark(
        id=id,
        name=name,
        lat=lat,
        lng=lng,
        address="",
        category_id=category_id,
        created_at=_ts(),
        last_used_at=_ts(),
        country_code="",
    )


def test_diff_identical_stores_is_empty():
    a = _store()
    b = _store()
    d = diff_store(current=a, baseline=b)
    assert d == StoreDiff(
        bookmarks_created=[],
        bookmarks_modified=[],
        bookmarks_deleted=set(),
        categories_created=[],
        categories_modified=[],
        categories_deleted=set(),
    )


def test_diff_detects_bookmark_created():
    baseline = _store()
    current = _store(bookmarks=[_bm("a")])
    d = diff_store(current=current, baseline=baseline)
    assert [b.id for b in d.bookmarks_created] == ["a"]
    assert not d.bookmarks_modified
    assert not d.bookmarks_deleted


def test_diff_detects_bookmark_deleted():
    baseline = _store(bookmarks=[_bm("a")])
    current = _store()
    d = diff_store(current=current, baseline=baseline)
    assert d.bookmarks_deleted == {"a"}
    assert not d.bookmarks_created
    assert not d.bookmarks_modified


def test_diff_detects_bookmark_modified():
    baseline = _store(bookmarks=[_bm("a", name="old")])
    current = _store(bookmarks=[_bm("a", name="new")])
    d = diff_store(current=current, baseline=baseline)
    assert len(d.bookmarks_modified) == 1
    assert d.bookmarks_modified[0].name == "new"


def test_diff_detects_category_changes():
    base_cat = BookmarkCategory(id="c1", name="A", color="#fff", sort_order=1, created_at=_ts())
    new_cat = BookmarkCategory(id="c2", name="B", color="#000", sort_order=2, created_at=_ts())
    baseline = _store(categories=[base_cat])
    current = _store(categories=[new_cat])
    d = diff_store(current=current, baseline=baseline)
    assert [c.id for c in d.categories_created] == ["c2"]
    assert d.categories_deleted == {"c1"}


def test_diff_is_empty_helper():
    a = _store()
    assert diff_store(current=a, baseline=a).is_empty()
