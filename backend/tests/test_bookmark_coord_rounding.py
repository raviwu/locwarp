"""Bookmark coordinates are rounded to COORD_PRECISION on every save path,
so no bookmark persists a long-precision (jittered/interpolated/map-click)
coordinate. Clean human/map input (<=7 decimals) is preserved exactly."""
from __future__ import annotations

from bootstrap.factories import make_bookmark_manager
from domain.coords import round_coord, COORD_PRECISION


def test_round_coord_strips_float_tail():
    assert round_coord(25.03462332942381) == 25.0346233
    assert round_coord(121.54608743242391) == 121.5460874


def test_round_coord_preserves_clean_input():
    # <=7-decimal input is unchanged (this is what a human/map provides).
    assert round_coord(25.034623) == 25.034623
    assert round_coord(121.546087) == 121.546087
    assert round_coord(25.0) == 25.0


def test_coord_precision_is_seven():
    assert COORD_PRECISION == 7


# --- integration: manager write paths round on save ---
# Manager construction follows the established idiom (see
# test_bookmark_concurrency.py): data-path isolation is automatic via the
# autouse conftest guard `_isolate_real_data_paths`, so no tmp_path/patching
# is needed here.


def test_create_bookmark_rounds():
    mgr = make_bookmark_manager()
    bm = mgr.create_bookmark(name="x", lat=25.03462332942381, lng=121.54608743242391)
    assert bm.lat == 25.0346233
    assert bm.lng == 121.5460874


def test_create_bookmark_preserves_clean():
    mgr = make_bookmark_manager()
    bm = mgr.create_bookmark(name="x", lat=25.034623, lng=121.546087)
    assert bm.lat == 25.034623
    assert bm.lng == 121.546087


def test_update_bookmark_rounds_coords():
    mgr = make_bookmark_manager()
    bm = mgr.create_bookmark(name="x", lat=25.0, lng=121.0)
    updated = mgr.update_bookmark(bm.id, lat=34.33102440963247, lng=120.00000000000001)
    assert updated.lat == 34.3310244
    assert updated.lng == 120.0


def test_update_bookmark_preserves_clean():
    mgr = make_bookmark_manager()
    bm = mgr.create_bookmark(name="x", lat=25.0, lng=121.0)
    updated = mgr.update_bookmark(bm.id, lat=34.331024, lng=120.0000001)
    assert updated.lat == 34.331024
    assert updated.lng == 120.0000001


def test_import_json_rounds_coords():
    """_upsert_items (shared by import_json) rounds incoming coords too."""
    import json

    mgr = make_bookmark_manager()
    payload = {
        "categories": [],
        "bookmarks": [
            {
                "id": "imported-1",
                "name": "imported",
                "lat": 25.03462332942381,
                "lng": 121.54608743242391,
                "address": "",
                "category_id": "default",
                "created_at": "2026-01-01T00:00:00+00:00",
                "last_used_at": "2026-01-01T00:00:00+00:00",
                "country_code": "",
            }
        ],
    }
    result = mgr.import_json(json.dumps(payload))
    assert result["imported"] == 1
    bm = next(b for b in mgr.store.bookmarks if b.id == "imported-1")
    assert bm.lat == 25.0346233
    assert bm.lng == 121.5460874


def test_single_category_import_rounds_coords():
    """_import_single_category is a bypass path around import_json's
    _upsert_items rounding — it builds Bookmark(...) directly and must
    round there too."""
    import json

    from services.bookmark_import import detect_and_import

    mgr = make_bookmark_manager()
    payload = json.dumps({
        "_meta": {"exported_at": "2026-05-09T08:30:00Z", "format_version": 1, "scope": "category"},
        "category": {"id": "cat-shared", "name": "京都散步", "color": "#ef4444",
                     "sort_order": 1, "created_at": "2026-05-09T00:00:00Z"},
        "bookmarks": [
            {"id": "b1", "name": "常照皇寺",
             "lat": 25.034623329423810123, "lng": 121.546087432423910123,
             "category_id": "cat-shared", "created_at": "", "last_used_at": ""},
        ],
    })
    result = detect_and_import(mgr, payload)
    assert result["imported"] == 1
    bm = next(b for b in mgr.store.bookmarks if b.name == "常照皇寺")
    assert bm.lat == 25.0346233
    assert bm.lng == 121.5460874


def test_geojson_import_rounds_coords():
    """_import_geojson is a bypass path around import_json's
    _upsert_items rounding — it builds Bookmark(...) directly and must
    round there too."""
    import json

    from services.bookmark_import import detect_and_import

    mgr = make_bookmark_manager()
    payload = json.dumps({
        "type": "FeatureCollection",
        "name": "京都散步",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "Point",
                          "coordinates": [135.685625512340987123, 35.200424823410987123]},
             "properties": {"name": "常照皇寺", "country_code": "jp"}},
        ],
    })
    result = detect_and_import(mgr, payload)
    assert result["imported"] == 1
    bm = next(b for b in mgr.store.bookmarks if b.name == "常照皇寺")
    assert bm.lat == 35.2004248
    assert bm.lng == 135.6856255
