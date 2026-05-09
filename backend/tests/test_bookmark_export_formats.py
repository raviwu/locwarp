"""Unit tests for per-format bookmark export."""
from __future__ import annotations

import pytest


@pytest.fixture
def store():
    from models.schemas import BookmarkStore, BookmarkCategory, Bookmark
    return BookmarkStore(
        categories=[
            BookmarkCategory(id="default", name="預設", color="#6c8cff", sort_order=0, created_at="2026-05-09T00:00:00Z"),
            BookmarkCategory(id="cat-kyoto", name="京都散步", color="#ef4444", sort_order=1, created_at="2026-05-09T00:00:00Z"),
        ],
        bookmarks=[
            Bookmark(id="b1", name="京北 - 常照皇寺", lat=35.200425, lng=135.685626,
                     category_id="cat-kyoto", country_code="jp",
                     created_at="2026-05-09T00:00:00Z", last_used_at=""),
            Bookmark(id="b2", name="京北 - 山國神社", lat=35.173026, lng=135.655441,
                     category_id="cat-kyoto", country_code="jp",
                     created_at="2026-05-09T00:00:00Z", last_used_at=""),
        ],
    )


def test_markdown_single_category(store):
    from services.bookmark_export import to_markdown
    out = to_markdown(store, category_id="cat-kyoto", exported_at="2026-05-09T08:30:00Z")
    assert out == (
        "## 京都散步\n"
        "\n"
        "Exported 2026-05-09T08:30:00Z\n"
        "\n"
        "---\n"
        "\n"
        "京北 - 常照皇寺\n"
        "35.200425,135.685626\n"
        "\n"
        "京北 - 山國神社\n"
        "35.173026,135.655441\n"
    )


def test_markdown_missing_category_raises(store):
    from services.bookmark_export import to_markdown
    with pytest.raises(KeyError):
        to_markdown(store, category_id="missing", exported_at="2026-05-09T08:30:00Z")


def test_markdown_full_store_concatenates_sections(store):
    from services.bookmark_export import to_markdown
    out = to_markdown(store, category_id=None, exported_at="2026-05-09T08:30:00Z")
    # Default has zero bookmarks → still emits its section header
    assert "## 預設\n" in out
    assert "## 京都散步\n" in out
    # Sections separated by blank line
    sections = out.split("\n\n## ")
    assert len(sections) == 2  # first section starts with "## ", split gives 2 chunks


def test_markdown_strips_newlines_in_name(store):
    from models.schemas import Bookmark
    from services.bookmark_export import to_markdown
    store.bookmarks.append(Bookmark(id="b3", name="weird\nname", lat=1.0, lng=2.0,
                                    category_id="cat-kyoto",
                                    created_at="", last_used_at=""))
    out = to_markdown(store, category_id="cat-kyoto", exported_at="2026-05-09T08:30:00Z")
    assert "weird name" in out
    assert "weird\nname" not in out
