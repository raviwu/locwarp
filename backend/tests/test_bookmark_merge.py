from datetime import datetime, timezone

from models.schemas import Bookmark, BookmarkCategory, BookmarkStore
from services.bookmark_merge import diff_store, merge_local_wins, StoreDiff


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



def test_merge_both_added_disjoint_keeps_both():
    baseline = _store()
    local = _store(bookmarks=[_bm("a")])
    remote = _store(bookmarks=[_bm("b")])
    local_diff = diff_store(current=local, baseline=baseline)
    merged = merge_local_wins(remote=remote, local_diff=local_diff)
    ids = {b.id for b in merged.bookmarks}
    assert ids == {"a", "b"}


def test_merge_modify_modify_local_wins():
    baseline = _store(bookmarks=[_bm("z", name="orig")])
    local = _store(bookmarks=[_bm("z", name="local-edit")])
    remote = _store(bookmarks=[_bm("z", name="remote-edit")])
    local_diff = diff_store(current=local, baseline=baseline)
    merged = merge_local_wins(remote=remote, local_diff=local_diff)
    z = next(b for b in merged.bookmarks if b.id == "z")
    assert z.name == "local-edit"


def test_merge_local_delete_wins_over_remote_modify():
    baseline = _store(bookmarks=[_bm("q", name="orig")])
    local = _store()  # local deleted q
    remote = _store(bookmarks=[_bm("q", name="remote-edit")])
    local_diff = diff_store(current=local, baseline=baseline)
    merged = merge_local_wins(remote=remote, local_diff=local_diff)
    assert all(b.id != "q" for b in merged.bookmarks)


def test_merge_local_modify_restores_remote_delete():
    baseline = _store(bookmarks=[_bm("q", name="orig")])
    local = _store(bookmarks=[_bm("q", name="local-edit")])
    remote = _store()  # remote deleted q
    local_diff = diff_store(current=local, baseline=baseline)
    merged = merge_local_wins(remote=remote, local_diff=local_diff)
    q = next(b for b in merged.bookmarks if b.id == "q")
    assert q.name == "local-edit"


def test_merge_category_changes_same_semantics():
    baseline = _store()
    new_cat = BookmarkCategory(id="c1", name="Local", color="#fff", sort_order=1, created_at="2026-05-11T00:00:00+00:00")
    local = _store(categories=[
        BookmarkCategory(id="default", name="預設", color="#000", sort_order=0, created_at="2026-05-11T00:00:00+00:00"),
        new_cat,
    ])
    remote = _store()  # only default
    local_diff = diff_store(current=local, baseline=baseline)
    merged = merge_local_wins(remote=remote, local_diff=local_diff)
    cat_ids = {c.id for c in merged.categories}
    assert "c1" in cat_ids


def test_merge_no_local_changes_returns_remote_equivalent():
    # Use fixed timestamps to ensure bookmark "a" is identical in baseline and local
    fixed_ts = "2026-05-11T00:00:00+00:00"
    bm_a = Bookmark(
        id="a", name="X", lat=1.0, lng=2.0, address="", category_id="default",
        created_at=fixed_ts, last_used_at=fixed_ts, country_code=""
    )
    baseline = _store(bookmarks=[bm_a])
    local = _store(bookmarks=[bm_a])
    remote = _store(bookmarks=[bm_a, _bm("b")])
    local_diff = diff_store(current=local, baseline=baseline)
    assert local_diff.is_empty()
    merged = merge_local_wins(remote=remote, local_diff=local_diff)
    ids = {b.id for b in merged.bookmarks}
    assert ids == {"a", "b"}
