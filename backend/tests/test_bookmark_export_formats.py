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


def test_geojson_single_category(store):
    from services.bookmark_export import to_geojson
    out = to_geojson(store, category_id="cat-kyoto")
    assert out["type"] == "FeatureCollection"
    assert out["name"] == "京都散步"
    assert len(out["features"]) == 2
    f = out["features"][0]
    assert f["type"] == "Feature"
    assert f["geometry"] == {"type": "Point", "coordinates": [135.685626, 35.200425]}
    assert f["properties"]["name"] == "京北 - 常照皇寺"
    assert f["properties"]["category"] == "京都散步"
    assert f["properties"]["country_code"] == "jp"


def test_geojson_full_store_uses_all_bookmarks(store):
    from services.bookmark_export import to_geojson
    out = to_geojson(store, category_id=None)
    assert out["name"] == "LocWarp Bookmarks"
    assert len(out["features"]) == 2  # only the kyoto two; default has none


def test_geojson_missing_category_raises(store):
    from services.bookmark_export import to_geojson
    with pytest.raises(KeyError):
        to_geojson(store, category_id="missing")


def test_csv_single_category(store):
    import csv
    import io
    from services.bookmark_export import to_csv
    out = to_csv(store, category_id="cat-kyoto")
    # CSV begins with UTF-8 BOM for Excel compatibility
    assert out.startswith("﻿")
    rows = list(csv.DictReader(io.StringIO(out.lstrip("﻿"))))
    assert [r["name"] for r in rows] == ["京北 - 常照皇寺", "京北 - 山國神社"]
    assert rows[0]["lat"] == "35.200425"
    assert rows[0]["lng"] == "135.685626"
    assert rows[0]["category"] == "京都散步"


def test_csv_full_store(store):
    import csv
    import io
    from services.bookmark_export import to_csv
    out = to_csv(store, category_id=None)
    rows = list(csv.DictReader(io.StringIO(out.lstrip("﻿"))))
    assert len(rows) == 2  # only kyoto bookmarks; default has zero


def test_csv_quotes_names_with_commas(store):
    from models.schemas import Bookmark
    from services.bookmark_export import to_csv
    store.bookmarks.append(Bookmark(id="b3", name="a,b", lat=0.0, lng=0.0,
                                    category_id="cat-kyoto",
                                    created_at="", last_used_at=""))
    out = to_csv(store, category_id="cat-kyoto")
    assert '"a,b"' in out


def test_json_single_category_wraps_with_meta(store):
    from services.bookmark_export import to_json
    out = to_json(store, category_id="cat-kyoto", exported_at="2026-05-09T08:30:00Z")
    assert out["_meta"] == {
        "exported_at": "2026-05-09T08:30:00Z",
        "format_version": 1,
        "scope": "category",
    }
    assert out["category"]["id"] == "cat-kyoto"
    assert out["category"]["name"] == "京都散步"
    assert len(out["bookmarks"]) == 2
    # internal bookmark ids preserved (round-trip needs them)
    assert {b["id"] for b in out["bookmarks"]} == {"b1", "b2"}


def test_json_full_store_unchanged_shape(store):
    from services.bookmark_export import to_json
    out = to_json(store, category_id=None, exported_at="2026-05-09T08:30:00Z")
    # Whole-store mirrors BookmarkStore for round-trip with existing import
    assert "_meta" not in out
    assert {c["id"] for c in out["categories"]} == {"default", "cat-kyoto"}
    assert len(out["bookmarks"]) == 2


def test_json_missing_category_raises(store):
    from services.bookmark_export import to_json
    with pytest.raises(KeyError):
        to_json(store, category_id="missing")
