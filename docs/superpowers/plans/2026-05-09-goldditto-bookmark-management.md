# GoldDitto Bookmark Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the GoldDitto panel pick A/B from bookmark categories, support cascade-delete an entire event, and export per-category in human-friendly formats (Markdown / GeoJSON / CSV).

**Architecture:** No schema changes. `BookmarkManager.delete_category` gains a `cascade` flag. Format-specific exporters live in a new `services/bookmark_export.py`. Format-detecting import logic lives in a new `services/bookmark_import.py`. Frontend gains two reusable popovers (`BookmarkPickerPopover`, `ExportPopover`); existing `BookmarkList` and `GoldDittoPanel` consume them.

**Tech Stack:** FastAPI · pydantic · React 18 · TypeScript · Leaflet · Vite. Tests use pytest (already bootstrapped in `backend/tests/`).

**Spec:** `docs/superpowers/specs/2026-05-09-goldditto-bookmark-management-design.md`

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/services/bookmarks.py` | Modify | `delete_category(cat_id, cascade=False)` |
| `backend/services/bookmark_export.py` | Create | `to_json`, `to_markdown`, `to_geojson`, `to_csv` per-category exporters |
| `backend/services/bookmark_import.py` | Create | `detect_and_import(manager, raw)` — full-store / single-category / GeoJSON |
| `backend/api/bookmarks.py` | Modify | `?cascade=` on DELETE; `?category_id=&format=` on GET export; format detection on POST import |
| `backend/tests/test_bookmark_cascade_delete.py` | Create | Unit tests for cascade behaviour |
| `backend/tests/test_bookmark_export_formats.py` | Create | Unit tests for each export format |
| `backend/tests/test_bookmark_import_formats.py` | Create | Unit tests for import detection |
| `backend/tests/test_bookmarks_api.py` | Create | FastAPI TestClient — query params + import detection |
| `frontend/src/services/api.ts` | Modify | `deleteCategory(id, cascade)`; replace `bookmarksExportUrl` with `bookmarksExportUrl({...})`; add `categoriesBookmarkCount` helper |
| `frontend/src/i18n/strings.ts` | Modify | Add `bm.export.*`, `bm.delete.*`, `goldditto.picker.*` keys |
| `frontend/src/components/BookmarkPickerPopover.tsx` | Create | Two-stage popover (category select + bookmark list + End-event button) |
| `frontend/src/components/ExportPopover.tsx` | Create | Library export popover (scope + format + download trigger) |
| `frontend/src/components/GoldDittoPanel.tsx` | Modify | `📚` button next to A and B; popover state; coord-fill callback |
| `frontend/src/components/BookmarkList.tsx` | Modify | Replace single trash icon in category manager with two-option dropdown; replace `<a download>` Export with popover trigger |
| `frontend/src/components/ControlPanel.tsx` | Modify | Pass new `onCategoryDeleteCascade` prop through to BookmarkList |
| `frontend/src/App.tsx` | Modify | Wire `onCategoryDeleteCascade` → `api.deleteCategory(id, true)` |

---

## Task 1: Cascade flag on `BookmarkManager.delete_category`

**Files:**
- Modify: `backend/services/bookmarks.py:115-135`
- Create: `backend/tests/test_bookmark_cascade_delete.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_bookmark_cascade_delete.py`:

```python
"""Unit tests for cascade-delete behaviour on BookmarkManager."""
from __future__ import annotations

import pytest


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """Fresh BookmarkManager backed by a tmp file (so the user's
    real ~/.locwarp/bookmarks.json is never touched)."""
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    from services.bookmarks import BookmarkManager
    return BookmarkManager()


def test_delete_category_cascade_false_keeps_bookmarks(manager):
    cat = manager.create_category(name="evt")
    bm = manager.create_bookmark(name="x", lat=0.0, lng=0.0, category_id=cat.id)
    manager.delete_category(cat.id, cascade=False)
    assert any(b.id == bm.id for b in manager.store.bookmarks)
    assert manager._find_bookmark(bm.id).category_id == "default"


def test_delete_category_cascade_true_deletes_bookmarks(manager):
    cat = manager.create_category(name="evt")
    bm1 = manager.create_bookmark(name="x", lat=0.0, lng=0.0, category_id=cat.id)
    bm2 = manager.create_bookmark(name="y", lat=1.0, lng=1.0, category_id=cat.id)
    manager.delete_category(cat.id, cascade=True)
    assert not any(b.id in {bm1.id, bm2.id} for b in manager.store.bookmarks)
    assert manager._find_category(cat.id) is None


def test_delete_default_category_blocked_even_with_cascade(manager):
    bm = manager.create_bookmark(name="x", lat=0.0, lng=0.0)
    assert manager.delete_category("default", cascade=True) is False
    assert manager._find_bookmark(bm.id) is not None


def test_delete_returns_count_of_deleted_bookmarks(manager):
    cat = manager.create_category(name="evt")
    manager.create_bookmark(name="x", lat=0.0, lng=0.0, category_id=cat.id)
    manager.create_bookmark(name="y", lat=1.0, lng=1.0, category_id=cat.id)
    manager.create_bookmark(name="other", lat=2.0, lng=2.0)  # default
    result = manager.delete_category(cat.id, cascade=True)
    # New return contract: dict with status + deleted count
    assert result == {"deleted": True, "deleted_bookmarks": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_bookmark_cascade_delete.py -v`
Expected: FAIL — `delete_category` rejects the `cascade=` kwarg, plus return type mismatch.

- [ ] **Step 3: Implement cascade on `BookmarkManager.delete_category`**

Replace lines 115-135 of `backend/services/bookmarks.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_bookmark_cascade_delete.py -v`
Expected: PASS — all four tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmarks.py backend/tests/test_bookmark_cascade_delete.py
git commit -m "feat(backend): cascade flag on BookmarkManager.delete_category"
```

---

## Task 2: API DELETE accepts `?cascade=`

**Files:**
- Modify: `backend/api/bookmarks.py:98-105`
- Create: `backend/tests/test_bookmarks_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_bookmarks_api.py`:

```python
"""FastAPI integration tests for /api/bookmarks endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient with the bookmark store redirected to tmp_path."""
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    # Force a fresh BookmarkManager so the patched path takes effect.
    import main
    from services.bookmarks import BookmarkManager
    main.app_state.bookmark_manager = BookmarkManager()
    return TestClient(main.app)


def _create_category(client, name="evt"):
    resp = client.post("/api/bookmarks/categories", json={"name": name})
    assert resp.status_code == 200
    return resp.json()


def _create_bookmark(client, cat_id, name="x", lat=0.0, lng=0.0):
    resp = client.post("/api/bookmarks", json={
        "name": name, "lat": lat, "lng": lng, "category_id": cat_id,
    })
    assert resp.status_code == 200
    return resp.json()


def test_delete_category_cascade_false_default(client):
    cat = _create_category(client)
    bm = _create_bookmark(client, cat["id"])
    resp = client.delete(f"/api/bookmarks/categories/{cat['id']}")
    assert resp.status_code == 200
    assert resp.json()["deleted_bookmarks"] == 0
    # Bookmark still present, in default
    listing = client.get("/api/bookmarks").json()
    surviving = [b for b in listing["bookmarks"] if b["id"] == bm["id"]]
    assert surviving and surviving[0]["category_id"] == "default"


def test_delete_category_cascade_true_removes_bookmarks(client):
    cat = _create_category(client)
    bm = _create_bookmark(client, cat["id"])
    resp = client.delete(f"/api/bookmarks/categories/{cat['id']}?cascade=true")
    assert resp.status_code == 200
    assert resp.json()["deleted_bookmarks"] == 1
    listing = client.get("/api/bookmarks").json()
    assert not any(b["id"] == bm["id"] for b in listing["bookmarks"])


def test_delete_default_category_with_cascade_blocked(client):
    resp = client.delete("/api/bookmarks/categories/default?cascade=true")
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_bookmarks_api.py -v`
Expected: FAIL — `cascade=true` is silently ignored or response shape lacks `deleted_bookmarks`.

- [ ] **Step 3: Update the route to accept `cascade`**

Replace lines 98-105 of `backend/api/bookmarks.py`:

```python
@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: str, cascade: bool = False):
    bm = _bm()
    if cat_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete default category")
    result = bm.delete_category(cat_id, cascade=cascade)
    if result is False:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"status": "deleted", "deleted_bookmarks": result["deleted_bookmarks"]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_bookmarks_api.py -v`
Expected: PASS — all three tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/api/bookmarks.py backend/tests/test_bookmarks_api.py
git commit -m "feat(backend): cascade query param on DELETE /bookmarks/categories"
```

---

## Task 3: Markdown exporter

**Files:**
- Create: `backend/services/bookmark_export.py`
- Create: `backend/tests/test_bookmark_export_formats.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_bookmark_export_formats.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_bookmark_export_formats.py -v`
Expected: FAIL — `services.bookmark_export` does not exist yet.

- [ ] **Step 3: Implement the exporter**

Create `backend/services/bookmark_export.py`:

```python
"""Per-format bookmark exporters.

Each function takes the in-memory ``BookmarkStore`` plus an optional
``category_id`` and returns a ``str`` (markdown / csv / json) or ``dict``
(geojson / json structured form).

Whole-store exports concatenate per-category output where the format
permits it. The Markdown emitter emits one ``## <category-name>`` section
per category, blank-line separated.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from models.schemas import Bookmark, BookmarkCategory, BookmarkStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_name(name: str) -> str:
    return name.replace("\n", " ").replace("\r", " ")


def _category_bookmarks(store: BookmarkStore, cat_id: str) -> list[Bookmark]:
    return [b for b in store.bookmarks if b.category_id == cat_id]


def _markdown_section(cat: BookmarkCategory, bms: Iterable[Bookmark], exported_at: str) -> str:
    lines = [f"## {cat.name}", "", f"Exported {exported_at}", "", "---", ""]
    bm_list = list(bms)
    for i, bm in enumerate(bm_list):
        lines.append(_safe_name(bm.name))
        lines.append(f"{bm.lat:.6f},{bm.lng:.6f}")
        if i != len(bm_list) - 1:
            lines.append("")
    return "\n".join(lines) + "\n"


def to_markdown(
    store: BookmarkStore,
    category_id: str | None = None,
    exported_at: str | None = None,
) -> str:
    exported_at = exported_at or _now_iso()
    if category_id is not None:
        cat = next((c for c in store.categories if c.id == category_id), None)
        if cat is None:
            raise KeyError(category_id)
        return _markdown_section(cat, _category_bookmarks(store, cat.id), exported_at)

    sections = []
    for cat in sorted(store.categories, key=lambda c: c.sort_order):
        sections.append(_markdown_section(cat, _category_bookmarks(store, cat.id), exported_at))
    return "\n".join(sections)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_bookmark_export_formats.py -v`
Expected: PASS — four tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmark_export.py backend/tests/test_bookmark_export_formats.py
git commit -m "feat(backend): markdown bookmark exporter (per-category + full-store)"
```

---

## Task 4: GeoJSON exporter

**Files:**
- Modify: `backend/services/bookmark_export.py` (append)
- Modify: `backend/tests/test_bookmark_export_formats.py` (append)

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/test_bookmark_export_formats.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && python3 -m pytest tests/test_bookmark_export_formats.py::test_geojson_single_category -v`
Expected: FAIL — `to_geojson` not defined.

- [ ] **Step 3: Append implementation**

Append to `backend/services/bookmark_export.py`:

```python
def to_geojson(store: BookmarkStore, category_id: str | None = None) -> dict:
    if category_id is not None:
        cat = next((c for c in store.categories if c.id == category_id), None)
        if cat is None:
            raise KeyError(category_id)
        cats = {cat.id: cat}
        bms = _category_bookmarks(store, cat.id)
        name = cat.name
    else:
        cats = {c.id: c for c in store.categories}
        bms = list(store.bookmarks)
        name = "LocWarp Bookmarks"

    features = []
    for bm in bms:
        cat_name = cats.get(bm.category_id).name if bm.category_id in cats else ""
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [bm.lng, bm.lat]},
            "properties": {
                "name": bm.name,
                "category": cat_name,
                "country_code": bm.country_code,
            },
        })

    return {"type": "FeatureCollection", "name": name, "features": features}
```

- [ ] **Step 4: Run all export tests**

Run: `cd backend && python3 -m pytest tests/test_bookmark_export_formats.py -v`
Expected: PASS — markdown + geojson tests all green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmark_export.py backend/tests/test_bookmark_export_formats.py
git commit -m "feat(backend): geojson bookmark exporter"
```

---

## Task 5: CSV exporter

**Files:**
- Modify: `backend/services/bookmark_export.py` (append)
- Modify: `backend/tests/test_bookmark_export_formats.py` (append)

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/test_bookmark_export_formats.py`:

```python
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
```

- [ ] **Step 2: Run failing test**

Run: `cd backend && python3 -m pytest tests/test_bookmark_export_formats.py::test_csv_single_category -v`
Expected: FAIL — `to_csv` not defined.

- [ ] **Step 3: Append implementation**

Append to `backend/services/bookmark_export.py`:

```python
def to_csv(store: BookmarkStore, category_id: str | None = None) -> str:
    import csv
    import io

    cats_by_id = {c.id: c for c in store.categories}
    if category_id is not None:
        if category_id not in cats_by_id:
            raise KeyError(category_id)
        bms = _category_bookmarks(store, category_id)
    else:
        bms = list(store.bookmarks)

    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM for Excel
    writer = csv.DictWriter(buf, fieldnames=["name", "lat", "lng", "category"])
    writer.writeheader()
    for bm in bms:
        cat_name = cats_by_id.get(bm.category_id).name if bm.category_id in cats_by_id else ""
        writer.writerow({
            "name": bm.name,
            "lat": f"{bm.lat:.6f}",
            "lng": f"{bm.lng:.6f}",
            "category": cat_name,
        })
    return buf.getvalue()
```

- [ ] **Step 4: Run all export tests**

Run: `cd backend && python3 -m pytest tests/test_bookmark_export_formats.py -v`
Expected: PASS — markdown + geojson + csv all green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmark_export.py backend/tests/test_bookmark_export_formats.py
git commit -m "feat(backend): csv bookmark exporter (UTF-8 BOM)"
```

---

## Task 6: Per-category JSON exporter with `_meta`

**Files:**
- Modify: `backend/services/bookmark_export.py` (append)
- Modify: `backend/tests/test_bookmark_export_formats.py` (append)

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/test_bookmark_export_formats.py`:

```python
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
```

- [ ] **Step 2: Run failing test**

Run: `cd backend && python3 -m pytest tests/test_bookmark_export_formats.py::test_json_single_category_wraps_with_meta -v`
Expected: FAIL — `to_json` not defined.

- [ ] **Step 3: Append implementation**

Append to `backend/services/bookmark_export.py`:

```python
def to_json(
    store: BookmarkStore,
    category_id: str | None = None,
    exported_at: str | None = None,
) -> dict:
    if category_id is None:
        # Whole-store: shape matches BookmarkStore for round-trip with existing import.
        return {
            "categories": [c.model_dump() for c in store.categories],
            "bookmarks": [b.model_dump() for b in store.bookmarks],
        }

    cat = next((c for c in store.categories if c.id == category_id), None)
    if cat is None:
        raise KeyError(category_id)

    return {
        "_meta": {
            "exported_at": exported_at or _now_iso(),
            "format_version": 1,
            "scope": "category",
        },
        "category": cat.model_dump(),
        "bookmarks": [b.model_dump() for b in _category_bookmarks(store, category_id)],
    }
```

- [ ] **Step 4: Run all export tests**

Run: `cd backend && python3 -m pytest tests/test_bookmark_export_formats.py -v`
Expected: PASS — all formats green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmark_export.py backend/tests/test_bookmark_export_formats.py
git commit -m "feat(backend): per-category json exporter with _meta wrapper"
```

---

## Task 7: API GET export accepts `category_id` and `format`

**Files:**
- Modify: `backend/api/bookmarks.py:108-115`
- Modify: `backend/tests/test_bookmarks_api.py` (append)

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/test_bookmarks_api.py`:

```python
def test_export_default_full_store_json(client):
    cat = _create_category(client)
    _create_bookmark(client, cat["id"])
    resp = client.get("/api/bookmarks/export")
    assert resp.status_code == 200
    body = resp.json()
    assert "categories" in body and "bookmarks" in body


def test_export_single_category_json(client):
    cat = _create_category(client, name="京都散步")
    _create_bookmark(client, cat["id"], name="常照皇寺", lat=35.200425, lng=135.685626)
    resp = client.get(f"/api/bookmarks/export?category_id={cat['id']}&format=json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["_meta"]["scope"] == "category"
    assert body["category"]["name"] == "京都散步"
    assert body["bookmarks"][0]["name"] == "常照皇寺"


def test_export_markdown(client):
    cat = _create_category(client, name="京都散步")
    _create_bookmark(client, cat["id"], name="常照皇寺", lat=35.200425, lng=135.685626)
    resp = client.get(f"/api/bookmarks/export?category_id={cat['id']}&format=markdown")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    text = resp.text
    assert text.startswith("## 京都散步\n")
    assert "常照皇寺\n35.200425,135.685626\n" in text


def test_export_geojson(client):
    cat = _create_category(client, name="京都散步")
    _create_bookmark(client, cat["id"], name="常照皇寺", lat=35.200425, lng=135.685626)
    resp = client.get(f"/api/bookmarks/export?category_id={cat['id']}&format=geojson")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/geo+json")
    body = resp.json()
    assert body["type"] == "FeatureCollection"


def test_export_csv(client):
    cat = _create_category(client, name="京都散步")
    _create_bookmark(client, cat["id"], name="常照皇寺", lat=35.200425, lng=135.685626)
    resp = client.get(f"/api/bookmarks/export?category_id={cat['id']}&format=csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "name,lat,lng,category" in resp.text


def test_export_unknown_category_404(client):
    resp = client.get("/api/bookmarks/export?category_id=nope&format=json")
    assert resp.status_code == 404


def test_export_invalid_format_422(client):
    resp = client.get("/api/bookmarks/export?format=yaml")
    assert resp.status_code == 422
```

- [ ] **Step 2: Run a failing test**

Run: `cd backend && python3 -m pytest tests/test_bookmarks_api.py::test_export_single_category_json -v`
Expected: FAIL — current endpoint ignores `category_id` and `format`.

- [ ] **Step 3: Update the export route**

Replace lines 108-115 of `backend/api/bookmarks.py`:

```python
from typing import Literal

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

    cat_slug = "bookmarks"
    if category_id is not None:
        cat = next(c for c in store.categories if c.id == category_id)
        cat_slug = cat.name.replace("/", "_")
    filename = f"{cat_slug}.{_FORMAT_TO_FILENAME_EXT[format]}"

    return Response(
        content=content,
        media_type=_FORMAT_TO_MEDIA[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 4: Run all API tests**

Run: `cd backend && python3 -m pytest tests/test_bookmarks_api.py -v`
Expected: PASS — all export and delete tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/api/bookmarks.py backend/tests/test_bookmarks_api.py
git commit -m "feat(backend): per-category + multi-format export query params"
```

---

## Task 8: Single-category JSON import

**Files:**
- Create: `backend/services/bookmark_import.py`
- Create: `backend/tests/test_bookmark_import_formats.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_bookmark_import_formats.py`:

```python
"""Unit tests for format-detecting bookmark import."""
from __future__ import annotations

import json
import pytest


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    from services.bookmarks import BookmarkManager
    return BookmarkManager()


def test_full_store_import(manager):
    from services.bookmark_import import detect_and_import
    payload = json.dumps({
        "categories": [
            {"id": "cat-x", "name": "事件 A", "color": "#ef4444",
             "sort_order": 1, "created_at": "2026-05-09T00:00:00Z"},
        ],
        "bookmarks": [
            {"id": "b1", "name": "p1", "lat": 1.0, "lng": 2.0,
             "category_id": "cat-x", "created_at": "", "last_used_at": ""},
        ],
    })
    result = detect_and_import(manager, payload)
    assert result["scope"] == "full_store"
    assert result["imported"] == 1
    assert any(c.id == "cat-x" for c in manager.store.categories)


def test_single_category_import(manager):
    from services.bookmark_import import detect_and_import
    payload = json.dumps({
        "_meta": {"exported_at": "2026-05-09T08:30:00Z", "format_version": 1, "scope": "category"},
        "category": {"id": "cat-shared", "name": "京都散步", "color": "#ef4444",
                     "sort_order": 1, "created_at": "2026-05-09T00:00:00Z"},
        "bookmarks": [
            {"id": "b1", "name": "常照皇寺", "lat": 35.2, "lng": 135.7,
             "category_id": "cat-shared", "created_at": "", "last_used_at": ""},
        ],
    })
    result = detect_and_import(manager, payload)
    assert result["scope"] == "category"
    assert result["imported"] == 1
    cat = next(c for c in manager.store.categories if c.name == "京都散步")
    assert any(b.category_id == cat.id for b in manager.store.bookmarks)


def test_single_category_import_collision_mints_new_ids(manager):
    """When the incoming category id collides locally, mint a new id and
    rewrite bookmark category_ids to point at it."""
    from services.bookmark_import import detect_and_import
    # Pre-create a local category named "Existing" with id "cat-foo"
    pre = manager.create_category(name="Existing")
    payload = json.dumps({
        "_meta": {"exported_at": "x", "format_version": 1, "scope": "category"},
        "category": {"id": pre.id, "name": "Imported", "color": "#fff",
                     "sort_order": 9, "created_at": ""},
        "bookmarks": [
            {"id": "b9", "name": "p", "lat": 0.0, "lng": 0.0,
             "category_id": pre.id, "created_at": "", "last_used_at": ""},
        ],
    })
    result = detect_and_import(manager, payload)
    assert result["imported"] == 1
    # New category exists with a fresh id
    imported_cat = next(c for c in manager.store.categories if c.name == "Imported")
    assert imported_cat.id != pre.id
    # The bookmark's category_id was rewritten
    bm = next(b for b in manager.store.bookmarks if b.name == "p")
    assert bm.category_id == imported_cat.id


def test_garbage_payload_raises(manager):
    from services.bookmark_import import detect_and_import, InvalidImportError
    with pytest.raises(InvalidImportError):
        detect_and_import(manager, json.dumps({"random": "shape"}))
```

- [ ] **Step 2: Run failing test**

Run: `cd backend && python3 -m pytest tests/test_bookmark_import_formats.py -v`
Expected: FAIL — `services.bookmark_import` does not exist.

- [ ] **Step 3: Implement import detection (full-store + single-category)**

Create `backend/services/bookmark_import.py`:

```python
"""Format-detecting bookmark import.

Accepts three top-level shapes:
  1. Full-store: ``{"categories": [...], "bookmarks": [...]}``
  2. Single-category JSON: ``{"_meta": {...}, "category": {...}, "bookmarks": [...]}``
  3. GeoJSON FeatureCollection (added in Task 9)
"""
from __future__ import annotations

import json
import logging
import uuid

from models.schemas import Bookmark, BookmarkCategory

logger = logging.getLogger(__name__)


class InvalidImportError(ValueError):
    """Raised when the import payload does not match any supported shape."""


def detect_and_import(manager, raw: str | bytes) -> dict:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidImportError(f"Not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise InvalidImportError("Top-level payload must be a JSON object")

    if "categories" in payload and "bookmarks" in payload:
        return _import_full_store(manager, payload)
    if "_meta" in payload and "category" in payload and "bookmarks" in payload:
        return _import_single_category(manager, payload)

    raise InvalidImportError("Unrecognised import shape")


def _import_full_store(manager, payload: dict) -> dict:
    # Reuse the existing path that merges by id (skips duplicates).
    text = json.dumps(payload)
    imported = manager.import_json(text)
    return {"scope": "full_store", "imported": imported, "skipped": 0}


def _import_single_category(manager, payload: dict) -> dict:
    raw_cat = payload["category"]
    raw_bms = payload.get("bookmarks", [])

    existing_ids = {c.id for c in manager.store.categories}
    incoming_id = raw_cat.get("id") or str(uuid.uuid4())
    if incoming_id in existing_ids:
        new_id = str(uuid.uuid4())
    else:
        new_id = incoming_id

    cat = BookmarkCategory(
        id=new_id,
        name=raw_cat["name"],
        color=raw_cat.get("color", "#6c8cff"),
        sort_order=raw_cat.get("sort_order", 0),
        created_at=raw_cat.get("created_at", ""),
    )
    manager.store.categories.append(cat)

    existing_bm_ids = {b.id for b in manager.store.bookmarks}
    imported = 0
    for raw_bm in raw_bms:
        bm_id = raw_bm.get("id") or str(uuid.uuid4())
        if bm_id in existing_bm_ids:
            bm_id = str(uuid.uuid4())
        bm = Bookmark(
            id=bm_id,
            name=raw_bm["name"],
            lat=float(raw_bm["lat"]),
            lng=float(raw_bm["lng"]),
            address=raw_bm.get("address", ""),
            category_id=new_id,
            country_code=raw_bm.get("country_code", ""),
            created_at=raw_bm.get("created_at", ""),
            last_used_at=raw_bm.get("last_used_at", ""),
        )
        manager.store.bookmarks.append(bm)
        existing_bm_ids.add(bm_id)
        imported += 1

    if imported or True:  # always persist (we appended a category)
        manager._save()

    return {"scope": "category", "imported": imported, "skipped": 0}
```

- [ ] **Step 4: Run failing tests except the geojson ones**

Run: `cd backend && python3 -m pytest tests/test_bookmark_import_formats.py -v`
Expected: PASS — all 4 single-category / full-store / garbage tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmark_import.py backend/tests/test_bookmark_import_formats.py
git commit -m "feat(backend): single-category JSON import with id collision handling"
```

---

## Task 9: GeoJSON import detection

**Files:**
- Modify: `backend/services/bookmark_import.py` (append)
- Modify: `backend/tests/test_bookmark_import_formats.py` (append)

- [ ] **Step 1: Append failing test**

Append to `backend/tests/test_bookmark_import_formats.py`:

```python
def test_geojson_import_creates_category_and_features(manager):
    from services.bookmark_import import detect_and_import
    payload = json.dumps({
        "type": "FeatureCollection",
        "name": "京都散步",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [135.685626, 35.200425]},
             "properties": {"name": "常照皇寺", "country_code": "jp"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [135.655441, 35.173026]},
             "properties": {"name": "山國神社"}},
        ],
    })
    result = detect_and_import(manager, payload)
    assert result["scope"] == "geojson"
    assert result["imported"] == 2
    cat = next(c for c in manager.store.categories if c.name == "京都散步")
    bms = [b for b in manager.store.bookmarks if b.category_id == cat.id]
    assert {b.name for b in bms} == {"常照皇寺", "山國神社"}


def test_geojson_import_no_name_uses_default_label(manager):
    from services.bookmark_import import detect_and_import
    payload = json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [121.5, 25.0]},
             "properties": {"name": "X"}},
        ],
    })
    result = detect_and_import(manager, payload)
    assert result["imported"] == 1
    assert any(c.name == "Imported" for c in manager.store.categories)


def test_geojson_import_skips_malformed_feature(manager):
    from services.bookmark_import import detect_and_import
    payload = json.dumps({
        "type": "FeatureCollection",
        "name": "test",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [121.0, 25.0]},
             "properties": {"name": "good"}},
            {"type": "Feature", "geometry": None, "properties": {"name": "broken"}},
            {"type": "Feature",
             "geometry": {"type": "LineString", "coordinates": []}, "properties": {"name": "wrong-geom"}},
        ],
    })
    result = detect_and_import(manager, payload)
    assert result["imported"] == 1
    assert result["skipped"] == 2
```

- [ ] **Step 2: Run failing test**

Run: `cd backend && python3 -m pytest tests/test_bookmark_import_formats.py::test_geojson_import_creates_category_and_features -v`
Expected: FAIL — geojson shape currently rejected as "Unrecognised import shape".

- [ ] **Step 3: Append GeoJSON branch**

Modify `backend/services/bookmark_import.py`:

In `detect_and_import`, add this branch before the final `raise`:

```python
    if payload.get("type") == "FeatureCollection" and isinstance(payload.get("features"), list):
        return _import_geojson(manager, payload)
```

Then append:

```python
def _import_geojson(manager, payload: dict) -> dict:
    name = payload.get("name") or "Imported"
    cat = manager.create_category(name=name)

    existing_bm_ids = {b.id for b in manager.store.bookmarks}
    imported = 0
    skipped = 0
    for feat in payload.get("features", []):
        try:
            geom = feat.get("geometry") or {}
            if geom.get("type") != "Point":
                skipped += 1
                continue
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                skipped += 1
                continue
            lng, lat = float(coords[0]), float(coords[1])
            props = feat.get("properties") or {}
            bm_name = props.get("name") or "(unnamed)"

            bm_id = str(uuid.uuid4())
            while bm_id in existing_bm_ids:
                bm_id = str(uuid.uuid4())

            bm = Bookmark(
                id=bm_id,
                name=bm_name,
                lat=lat,
                lng=lng,
                category_id=cat.id,
                country_code=str(props.get("country_code", "")).lower(),
                created_at="",
                last_used_at="",
            )
            manager.store.bookmarks.append(bm)
            existing_bm_ids.add(bm_id)
            imported += 1
        except (KeyError, TypeError, ValueError):
            skipped += 1

    manager._save()
    return {"scope": "geojson", "imported": imported, "skipped": skipped}
```

- [ ] **Step 4: Run all import tests**

Run: `cd backend && python3 -m pytest tests/test_bookmark_import_formats.py -v`
Expected: PASS — all import tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/services/bookmark_import.py backend/tests/test_bookmark_import_formats.py
git commit -m "feat(backend): GeoJSON FeatureCollection import"
```

---

## Task 10: Wire format detection into POST /import

**Files:**
- Modify: `backend/api/bookmarks.py:117-123`
- Modify: `backend/tests/test_bookmarks_api.py` (append)

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/test_bookmarks_api.py`:

```python
def test_import_full_store_via_api(client):
    payload = {
        "categories": [
            {"id": "cat-x", "name": "X", "color": "#ef4444", "sort_order": 1, "created_at": ""},
        ],
        "bookmarks": [
            {"id": "b1", "name": "p", "lat": 1.0, "lng": 2.0, "category_id": "cat-x",
             "created_at": "", "last_used_at": ""},
        ],
    }
    resp = client.post("/api/bookmarks/import", json=payload)
    assert resp.status_code == 200
    assert resp.json()["imported"] == 1


def test_import_single_category_via_api(client):
    payload = {
        "_meta": {"exported_at": "2026-05-09T08:30:00Z", "format_version": 1, "scope": "category"},
        "category": {"id": "shared-id", "name": "京都散步", "color": "#ef4444",
                     "sort_order": 1, "created_at": ""},
        "bookmarks": [
            {"id": "b1", "name": "常照皇寺", "lat": 35.2, "lng": 135.7,
             "category_id": "shared-id", "created_at": "", "last_used_at": ""},
        ],
    }
    resp = client.post("/api/bookmarks/import", json=payload)
    assert resp.status_code == 200
    assert resp.json()["scope"] == "category"
    assert resp.json()["imported"] == 1


def test_import_geojson_via_api(client):
    payload = {
        "type": "FeatureCollection",
        "name": "from-geojson",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [121.5, 25.0]},
             "properties": {"name": "x"}},
        ],
    }
    resp = client.post("/api/bookmarks/import", json=payload)
    assert resp.status_code == 200
    assert resp.json()["scope"] == "geojson"
    assert resp.json()["imported"] == 1


def test_import_garbage_returns_400(client):
    resp = client.post("/api/bookmarks/import", json={"random": True})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run failing test**

Run: `cd backend && python3 -m pytest tests/test_bookmarks_api.py::test_import_geojson_via_api -v`
Expected: FAIL — current import only handles full-store shape.

- [ ] **Step 3: Replace import route**

Replace lines 117-123 of `backend/api/bookmarks.py`:

```python
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
```

- [ ] **Step 4: Run all API tests**

Run: `cd backend && python3 -m pytest tests/test_bookmarks_api.py -v`
Expected: PASS — all import / export / delete tests green.

- [ ] **Step 5: Run full backend test suite**

Run: `cd backend && python3 -m pytest -v`
Expected: PASS — every existing goldditto test plus the new bookmark tests green.

- [ ] **Step 6: Commit**

```bash
git add backend/api/bookmarks.py backend/tests/test_bookmarks_api.py
git commit -m "feat(backend): POST /import auto-detects full-store / single-category / geojson"
```

---

## Task 11: Frontend API client updates

**Files:**
- Modify: `frontend/src/services/api.ts:256-258`

- [ ] **Step 1: Replace export URL helper and delete signature**

Replace line 256:

```typescript
export const deleteCategory = (id: string, cascade = false) =>
  request<{ status: string; deleted_bookmarks: number }>(
    'DELETE',
    `/api/bookmarks/categories/${id}${cascade ? '?cascade=true' : ''}`,
  )
```

Replace line 258:

```typescript
export type BookmarkExportFormat = 'json' | 'markdown' | 'geojson' | 'csv'

export interface BookmarkExportOptions {
  category_id?: string | null
  format?: BookmarkExportFormat
}

export const bookmarksExportUrl = (opts: BookmarkExportOptions = {}): string => {
  const params = new URLSearchParams()
  if (opts.category_id) params.set('category_id', opts.category_id)
  if (opts.format) params.set('format', opts.format)
  const qs = params.toString()
  return `${API}/api/bookmarks/export${qs ? `?${qs}` : ''}`
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS — no callsite errors. App.tsx still calls `bookmarksExportUrl()` with no args, which is the new default.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat(frontend): deleteCategory cascade flag + multi-format export URL"
```

---

## Task 12: i18n keys

**Files:**
- Modify: `frontend/src/i18n/strings.ts`

- [ ] **Step 1: Add new keys**

Insert (alphabetised by prefix is the existing convention; place in the `bm.*` block and a new `goldditto.picker.*` block):

```typescript
  // Bookmark picker (used by GoldDitto panel)
  'bm.picker.title_a': { zh: '從書籤選 A 點', en: 'Pick A from bookmarks' },
  'bm.picker.title_b': { zh: '從書籤選 B 點', en: 'Pick B from bookmarks' },
  'bm.picker.category_label': { zh: '分類', en: 'Category' },
  'bm.picker.empty': { zh: '此分類沒有書籤', en: 'No bookmarks in this category' },
  'bm.picker.close': { zh: '關閉', en: 'Close' },
  'bm.picker.end_event': { zh: '結束此活動 🗑', en: 'End event 🗑' },
  'bm.picker.end_event_disabled_cycling': { zh: '請先等本次拉金盆完成', en: 'Wait for the cycle to finish' },

  // Cascade-delete confirm
  'bm.delete.cascade_title': { zh: '結束「{name}」?', en: 'End event "{name}"?' },
  'bm.delete.cascade_body': { zh: '⚠ 將同時刪除分類內的 {n} 個書籤,無法復原。', en: '⚠ This will also delete the {n} bookmarks in this category. Cannot be undone.' },
  'bm.delete.cascade_confirm': { zh: '刪除活動', en: 'Delete event' },
  'bm.delete.softdelete_label': { zh: '只刪分類 (書籤搬到預設)', en: 'Delete category only (move bookmarks to Default)' },
  'bm.delete.cascade_label': { zh: '連書籤一起刪 ({n} 個)', en: 'Delete category + {n} bookmarks' },

  // Export popover
  'bm.export.title': { zh: '匯出', en: 'Export' },
  'bm.export.scope_all': { zh: '全部', en: 'All bookmarks' },
  'bm.export.scope_one': { zh: '單一分類', en: 'A single category' },
  'bm.export.format_label': { zh: '格式', en: 'Format' },
  'bm.export.format_json': { zh: 'JSON (round-trip)', en: 'JSON (round-trip)' },
  'bm.export.format_markdown': { zh: 'Markdown (人類可讀)', en: 'Markdown (human-readable)' },
  'bm.export.format_geojson': { zh: 'GeoJSON', en: 'GeoJSON' },
  'bm.export.format_csv': { zh: 'CSV', en: 'CSV' },
  'bm.export.download': { zh: '下載', en: 'Download' },

  // GoldDitto panel — picker entry buttons
  'goldditto.pick_from_bookmarks': { zh: '📚', en: '📚' },
  'goldditto.pick_from_bookmarks_tooltip_a': { zh: '從書籤選 A 點', en: 'Pick A from bookmarks' },
  'goldditto.pick_from_bookmarks_tooltip_b': { zh: '從書籤選 B 點', en: 'Pick B from bookmarks' },
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/strings.ts
git commit -m "feat(frontend): i18n keys for bookmark picker, cascade delete, export popover"
```

---

## Task 13: BookmarkPickerPopover component

**Files:**
- Create: `frontend/src/components/BookmarkPickerPopover.tsx`

- [ ] **Step 1: Create the component**

```tsx
import React, { useState, useEffect, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useT } from '../i18n'

interface Bookmark {
  id?: string
  name: string
  lat: number
  lng: number
  category_id?: string
  // Tolerate either the new `category_id` from backend or the legacy
  // `category` (name) field used elsewhere in the UI; the popover only
  // renders bookmarks already filtered by the parent.
  category?: string
}

interface Category {
  id: string
  name: string
  color?: string
}

interface Props {
  open: boolean
  side: 'A' | 'B'
  anchorRect: DOMRect | null  // anchor button bounding rect from getBoundingClientRect
  categories: Category[]
  bookmarksByCategoryId: Record<string, Bookmark[]>
  initialCategoryId: string | null  // last-used per side
  isCycling: boolean  // disables End-event button
  onClose: () => void
  onPickCoord: (bm: Bookmark) => void
  onCategoryChange: (catId: string) => void  // parent persists last-used per side
  onEndEvent?: (catId: string, bookmarkCount: number) => void  // omit for B side if you want
}

const POPOVER_WIDTH = 280
const POPOVER_MAX_HEIGHT = 360

export const BookmarkPickerPopover: React.FC<Props> = ({
  open, side, anchorRect, categories, bookmarksByCategoryId,
  initialCategoryId, isCycling, onClose, onPickCoord, onCategoryChange, onEndEvent,
}) => {
  const t = useT()
  const [selectedCatId, setSelectedCatId] = useState<string | null>(initialCategoryId)

  useEffect(() => { setSelectedCatId(initialCategoryId) }, [initialCategoryId, open])

  // Dismiss on outside click / ESC
  useEffect(() => {
    if (!open) return
    const onOutside = (e: Event) => {
      const target = e.target as Element | null
      if (target && target.closest?.('[data-bookmark-picker-popover]')) return
      onClose()
    }
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    const id = setTimeout(() => {
      document.addEventListener('pointerdown', onOutside)
      document.addEventListener('keydown', onEsc)
    }, 0)
    return () => {
      clearTimeout(id)
      document.removeEventListener('pointerdown', onOutside)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open, onClose])

  const visible = useMemo(() => {
    if (!selectedCatId) return [] as Bookmark[]
    return bookmarksByCategoryId[selectedCatId] ?? []
  }, [selectedCatId, bookmarksByCategoryId])

  if (!open || !anchorRect) return null

  const top = Math.min(anchorRect.bottom + 4, window.innerHeight - POPOVER_MAX_HEIGHT - 8)
  const left = Math.min(anchorRect.left, window.innerWidth - POPOVER_WIDTH - 8)

  return createPortal(
    <div
      data-bookmark-picker-popover
      onClick={(e) => e.stopPropagation()}
      style={{
        position: 'fixed', top, left,
        width: POPOVER_WIDTH, maxHeight: POPOVER_MAX_HEIGHT,
        background: '#1e1e22',
        border: '1px solid rgba(108, 140, 255, 0.3)',
        borderRadius: 8,
        boxShadow: '0 12px 28px rgba(0,0,0,0.5)',
        padding: 10,
        display: 'flex', flexDirection: 'column', gap: 8,
        zIndex: 9999,
        color: '#e0e0e0', fontSize: 12,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 600 }}>
        {side === 'A' ? t('bm.picker.title_a') : t('bm.picker.title_b')}
      </div>
      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ opacity: 0.7 }}>{t('bm.picker.category_label')}</span>
        <select
          value={selectedCatId ?? ''}
          onChange={(e) => {
            const v = e.target.value || null
            setSelectedCatId(v)
            if (v) onCategoryChange(v)
          }}
          style={{
            background: '#1e1e22', color: '#e0e0e0',
            border: '1px solid rgba(255,255,255,0.15)',
            borderRadius: 4, padding: '4px 6px',
          }}
        >
          <option value="" disabled>—</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </label>

      <div style={{ flex: 1, overflowY: 'auto', minHeight: 80, paddingRight: 2 }}>
        {visible.length === 0 ? (
          <div style={{ opacity: 0.5, padding: '12px 0', textAlign: 'center' }}>
            {t('bm.picker.empty')}
          </div>
        ) : (
          visible.map((bm) => (
            <div
              key={bm.id ?? `${bm.lat}-${bm.lng}`}
              onClick={() => { onPickCoord(bm); onClose() }}
              style={{
                padding: '6px 4px',
                borderBottom: '1px solid rgba(255,255,255,0.06)',
                cursor: 'pointer',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#2a2a2e' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
            >
              <div>{bm.name}</div>
              <div style={{ fontFamily: 'monospace', fontSize: 10, opacity: 0.55 }}>
                {bm.lat.toFixed(6)}, {bm.lng.toFixed(6)}
              </div>
            </div>
          ))
        )}
      </div>

      <div style={{ display: 'flex', gap: 6 }}>
        <button className="action-btn" onClick={onClose} style={{ flex: 1, fontSize: 11 }}>
          {t('bm.picker.close')}
        </button>
        {onEndEvent && selectedCatId && selectedCatId !== 'default' && (
          <button
            className="action-btn"
            disabled={isCycling || visible.length === 0 && !selectedCatId}
            title={isCycling ? t('bm.picker.end_event_disabled_cycling') : undefined}
            onClick={() => {
              if (selectedCatId) onEndEvent(selectedCatId, visible.length)
            }}
            style={{
              flex: 1, fontSize: 11,
              color: '#ff6b6b',
              borderColor: 'rgba(255,107,107,0.4)',
              opacity: isCycling ? 0.5 : 1,
            }}
          >
            {t('bm.picker.end_event')}
          </button>
        )}
      </div>
    </div>,
    document.body,
  )
}

export default BookmarkPickerPopover
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/BookmarkPickerPopover.tsx
git commit -m "feat(frontend): BookmarkPickerPopover component (category dropdown + bookmark list)"
```

---

## Task 14: Wire picker into GoldDittoPanel

**Files:**
- Modify: `frontend/src/components/GoldDittoPanel.tsx`

- [ ] **Step 1: Update Props and import**

At the top of `GoldDittoPanel.tsx`, after the existing imports:

```tsx
import BookmarkPickerPopover from './BookmarkPickerPopover'
```

Update `Props`:

```tsx
interface Bookmark {
  id?: string
  name: string
  lat: number
  lng: number
  category_id?: string
}

interface Category {
  id: string
  name: string
  color?: string
}

interface Props {
  connectedUdids: string[]
  isCycling: boolean
  mapCenter: { lat: number; lng: number } | null
  externalAValue: { coord: string } | null
  // New: bookmark sources for the picker
  bookmarks: Bookmark[]
  categories: Category[]
  onConfirmLocation: (lat: number, lng: number) => Promise<void> | void
  onCycle: (
    target: 'A' | 'B' | 'auto',
    args: { lat_a: number; lng_a: number; lat_b: number; lng_b: number; wait_seconds: number },
  ) => Promise<void> | void
  // New: cascade delete callback. Returning a Promise lets the panel close
  // the popover only after the API roundtrip succeeds.
  onCategoryDeleteCascade: (categoryId: string) => Promise<void> | void
}
```

- [ ] **Step 2: Add picker state and refs near the existing useState block**

Inside the component, after the existing `useState` block:

```tsx
  const [pickerSide, setPickerSide] = useState<'A' | 'B' | null>(null)
  const [pickerAnchor, setPickerAnchor] = useState<DOMRect | null>(null)
  const aBtnRef = React.useRef<HTMLButtonElement | null>(null)
  const bBtnRef = React.useRef<HTMLButtonElement | null>(null)

  const [pickerCatA, setPickerCatA] = useState<string | null>(
    () => localStorage.getItem('goldditto.picker.A.lastCategory'),
  )
  const [pickerCatB, setPickerCatB] = useState<string | null>(
    () => localStorage.getItem('goldditto.picker.B.lastCategory'),
  )

  const bookmarksByCategoryId = useMemo(() => {
    const out: Record<string, Bookmark[]> = {}
    for (const bm of bookmarks) {
      const cid = bm.category_id ?? 'default'
      if (!out[cid]) out[cid] = []
      out[cid].push(bm)
    }
    return out
  }, [bookmarks])

  const [confirmEnd, setConfirmEnd] = useState<{ catId: string; count: number } | null>(null)
```

- [ ] **Step 3: Add picker handlers**

Inside the component, before the `return`:

```tsx
  const openPicker = (side: 'A' | 'B', btn: HTMLButtonElement | null) => {
    if (!btn) return
    setPickerSide(side)
    setPickerAnchor(btn.getBoundingClientRect())
  }

  const handlePick = (bm: { lat: number; lng: number }) => {
    const text = `${bm.lat.toFixed(6)}, ${bm.lng.toFixed(6)}`
    if (pickerSide === 'A') setAText(text)
    else if (pickerSide === 'B') setBText(text)
  }

  const handleCategoryChange = (catId: string) => {
    if (pickerSide === 'A') {
      setPickerCatA(catId)
      try { localStorage.setItem('goldditto.picker.A.lastCategory', catId) } catch { /* ignore */ }
    } else if (pickerSide === 'B') {
      setPickerCatB(catId)
      try { localStorage.setItem('goldditto.picker.B.lastCategory', catId) } catch { /* ignore */ }
    }
  }

  const handleEndEventRequest = (catId: string, count: number) => {
    setConfirmEnd({ catId, count })
  }

  const handleEndEventConfirm = async () => {
    if (!confirmEnd) return
    await onCategoryDeleteCascade(confirmEnd.catId)
    setConfirmEnd(null)
    setPickerSide(null)
  }
```

- [ ] **Step 4: Add `📚` button next to the A and B inputs**

In the JSX where the A input lives (existing label block), wrap the input in a flex row and add the picker button:

```tsx
      <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{t('goldditto.a_label')}</span>
        <div style={{ display: 'flex', gap: 4 }}>
          <input
            type="text"
            value={aText}
            onChange={(e) => setAText(e.target.value)}
            placeholder="lat, lng"
            style={{
              flex: 1,
              padding: '6px 8px',
              border: aValid || aText === '' ? '1px solid #4b5563' : '1px solid #f87171',
              borderRadius: 4,
              background: '#1f2937',
              color: '#fff',
            }}
          />
          <button
            ref={aBtnRef}
            type="button"
            className="action-btn"
            title={t('goldditto.pick_from_bookmarks_tooltip_a')}
            onClick={() => openPicker('A', aBtnRef.current)}
            style={{ padding: '6px 8px', fontSize: 12 }}
          >📚</button>
        </div>
      </label>
```

Apply the same pattern (`bBtnRef`, `tooltip_b`, target B) to the B input.

- [ ] **Step 5: Render the popover and confirm dialog at the end of the JSX, before the closing `</div>`**

```tsx
      <BookmarkPickerPopover
        open={pickerSide !== null}
        side={pickerSide ?? 'A'}
        anchorRect={pickerAnchor}
        categories={categories}
        bookmarksByCategoryId={bookmarksByCategoryId}
        initialCategoryId={pickerSide === 'A' ? pickerCatA : pickerCatB}
        isCycling={isCycling}
        onClose={() => setPickerSide(null)}
        onPickCoord={handlePick}
        onCategoryChange={handleCategoryChange}
        onEndEvent={handleEndEventRequest}
      />

      {confirmEnd && createPortal(
        <div
          onClick={() => setConfirmEnd(null)}
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(8,10,20,0.55)',
            backdropFilter: 'blur(4px)',
            zIndex: 10000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'rgba(26,29,39,0.96)',
              border: '1px solid rgba(255,107,107,0.35)',
              borderRadius: 12,
              padding: 18, width: 320,
              boxShadow: '0 20px 60px rgba(12,18,40,0.65)',
              color: '#e0e0e0',
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>
              {t('bm.delete.cascade_title').replace('{name}',
                categories.find(c => c.id === confirmEnd.catId)?.name ?? '')}
            </div>
            <div style={{ fontSize: 12, marginBottom: 14 }}>
              {t('bm.delete.cascade_body').replace('{n}', String(confirmEnd.count))}
            </div>
            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
              <button className="action-btn" onClick={() => setConfirmEnd(null)}>
                {t('generic.cancel')}
              </button>
              <button
                className="action-btn"
                onClick={handleEndEventConfirm}
                style={{ color: '#ff6b6b', borderColor: 'rgba(255,107,107,0.4)' }}
              >
                {t('bm.delete.cascade_confirm')}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
```

Add `import { createPortal } from 'react-dom'` to the top imports if not already present.

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: FAIL — `ControlPanel.tsx` does not yet pass `bookmarks`, `categories`, `onCategoryDeleteCascade` to `<GoldDittoPanel>`. That is fixed in Task 15.

(Step 6 is intentionally a known-failing intermediate state. Continue.)

- [ ] **Step 7: Commit (intermediate)**

```bash
git add frontend/src/components/GoldDittoPanel.tsx
git commit -m "feat(frontend): GoldDittoPanel picker buttons, popover wiring, end-event modal"
```

---

## Task 15: Pipe `bookmarks`, `categories`, `onCategoryDeleteCascade` through ControlPanel and App

**Files:**
- Modify: `frontend/src/components/ControlPanel.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Update ControlPanel Props and forward to GoldDittoPanel**

Find the existing GoldDittoPanel render in `ControlPanel.tsx`. Add to `Props`:

```tsx
  bookmarks: any[]
  categories: any[]
  onCategoryDeleteCascade: (categoryId: string) => Promise<void> | void
```

Forward to GoldDittoPanel:

```tsx
            <GoldDittoPanel
              connectedUdids={connectedUdids}
              isCycling={goldDittoCycling}
              mapCenter={mapCenter}
              externalAValue={goldDittoExternalA}
              onConfirmLocation={onGoldDittoConfirm}
              onCycle={onGoldDittoCycle}
              bookmarks={bookmarks}
              categories={categories}
              onCategoryDeleteCascade={onCategoryDeleteCascade}
            />
```

- [ ] **Step 2: Extend the `useBookmarks` hook**

Modify `frontend/src/hooks/useBookmarks.ts`:

Replace lines 96-102 (the existing `deleteCategory`) with:

```tsx
  const deleteCategory = useCallback(
    async (id: string, cascade = false) => {
      await api.deleteCategory(id, cascade)
      await refresh()
    },
    [refresh],
  )
```

The hook already exposes `deleteCategory` in its return object (line 122) — no further export changes needed. Existing callsite `bm.deleteCategory(cat.id)` in `App.tsx:1254` still works (cascade defaults to `false`).

- [ ] **Step 3: Wire from App.tsx**

In `App.tsx` where `<ControlPanel ... />` is rendered (search for `bookmarks={bm.bookmarks.map`), add new props:

```tsx
            bookmarks={bm.bookmarks}
            categories={bm.categories}
            onCategoryDeleteCascade={(categoryId: string) =>
              bm.deleteCategory(categoryId, true)
            }
```

Note: this reuses `bm.deleteCategory` from step 2 with the cascade flag. The existing `onCategoryDelete` callback (line 1252) stays untouched — it continues to call the no-arg form.

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS — types align across hook, panel, control panel, and app.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ControlPanel.tsx frontend/src/App.tsx frontend/src/hooks/useBookmarks.ts
git commit -m "feat(frontend): wire cascade delete + bookmark sources into GoldDittoPanel"
```

---

## Task 16: BookmarkList — category delete dropdown

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx`

- [ ] **Step 1: Add `onCategoryDeleteCascade` prop**

In `BookmarkListProps`:

```tsx
  onCategoryDelete: (name: string) => void;
  onCategoryDeleteCascade?: (name: string, bookmarkCount: number) => void;
```

Destructure it in the component signature.

- [ ] **Step 2: Replace the single trash icon with a small dropdown**

In the category manager loop, find the existing delete button (around lines 842-858). Replace it with:

```tsx
              {cat !== 'Default' && cat !== '預設' && (
                <CategoryDeleteDropdown
                  category={cat}
                  bookmarkCount={(bookmarksByCategory[cat] ?? []).length}
                  onSoftDelete={() => onCategoryDelete(cat)}
                  onCascadeDelete={
                    onCategoryDeleteCascade
                      ? () => onCategoryDeleteCascade(cat, (bookmarksByCategory[cat] ?? []).length)
                      : undefined
                  }
                />
              )}
```

At the bottom of the file (above `export default`) add the inline dropdown:

```tsx
interface DropdownProps {
  category: string
  bookmarkCount: number
  onSoftDelete: () => void
  onCascadeDelete?: () => void
}

const CategoryDeleteDropdown: React.FC<DropdownProps> = ({
  category, bookmarkCount, onSoftDelete, onCascadeDelete,
}) => {
  const t = useT()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onOutside = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onOutside)
    return () => document.removeEventListener('pointerdown', onOutside)
  }, [open])

  const confirmCascade = () => {
    if (!onCascadeDelete) return
    const msg = t('bm.delete.cascade_body').replace('{n}', String(bookmarkCount))
    if (window.confirm(`${t('bm.delete.cascade_title').replace('{name}', category)}\n\n${msg}`)) {
      onCascadeDelete()
    }
  }

  const confirmSoft = () => {
    // Existing pattern: hand to onSoftDelete; parent shows native confirm.
    onSoftDelete()
  }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          background: 'none', border: 'none',
          color: '#f44336', cursor: 'pointer',
          padding: '2px 4px', fontSize: 11,
        }}
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="3,6 5,6 21,6" />
          <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
        </svg>
      </button>
      {open && (
        <div
          style={{
            position: 'absolute',
            top: '100%', right: 0, zIndex: 50,
            background: '#2a2a2e',
            border: '1px solid rgba(255,255,255,0.15)',
            borderRadius: 6,
            padding: '4px 0',
            minWidth: 240,
            boxShadow: '0 6px 18px rgba(0,0,0,0.5)',
          }}
        >
          <div
            onClick={() => { setOpen(false); confirmSoft() }}
            style={{ padding: '6px 12px', fontSize: 11, cursor: 'pointer' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
          >
            {t('bm.delete.softdelete_label')}
          </div>
          {onCascadeDelete && (
            <div
              onClick={() => { setOpen(false); confirmCascade() }}
              style={{
                padding: '6px 12px', fontSize: 11, cursor: 'pointer',
                color: '#ff6b6b',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
            >
              {t('bm.delete.cascade_label').replace('{n}', String(bookmarkCount))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

Add to imports if missing:

```tsx
import { useRef } from 'react'
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: FAIL — ControlPanel.tsx does not yet forward `onCategoryDeleteCascade` to `<BookmarkList>`. Patched in step 4.

- [ ] **Step 4: Forward `onCategoryDeleteCascade` from ControlPanel to BookmarkList**

In `ControlPanel.tsx` where `<BookmarkList .../>` is rendered, add:

```tsx
  onCategoryDeleteCascade={(name, _count) => {
    const cat = categories.find(c => c.name === name)
    if (cat) onCategoryDeleteCascade(cat.id)
  }}
```

`categories` is the prop carrying the same shape Task 15 added; we already have it.

- [ ] **Step 5: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/BookmarkList.tsx frontend/src/components/ControlPanel.tsx
git commit -m "feat(frontend): BookmarkList category-delete dropdown with cascade option"
```

---

## Task 17: ExportPopover component

**Files:**
- Create: `frontend/src/components/ExportPopover.tsx`

- [ ] **Step 1: Create the component**

```tsx
import React, { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useT } from '../i18n'
import { bookmarksExportUrl, BookmarkExportFormat } from '../services/api'

interface Category { id: string; name: string }

interface Props {
  open: boolean
  anchorRect: DOMRect | null
  categories: Category[]
  onClose: () => void
}

export const ExportPopover: React.FC<Props> = ({ open, anchorRect, categories, onClose }) => {
  const t = useT()
  const [scope, setScope] = useState<'all' | 'one'>('all')
  const [categoryId, setCategoryId] = useState<string>(categories[0]?.id ?? 'default')
  const [format, setFormat] = useState<BookmarkExportFormat>('json')
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onOutside = (e: Event) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const id = setTimeout(() => {
      document.addEventListener('pointerdown', onOutside)
      document.addEventListener('keydown', onEsc)
    }, 0)
    return () => {
      clearTimeout(id)
      document.removeEventListener('pointerdown', onOutside)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open, onClose])

  if (!open || !anchorRect) return null

  const top = Math.min(anchorRect.bottom + 4, window.innerHeight - 280)
  const left = Math.min(anchorRect.left, window.innerWidth - 280)

  const url = bookmarksExportUrl({
    category_id: scope === 'one' ? categoryId : null,
    format,
  })

  return createPortal(
    <div
      ref={ref}
      onClick={(e) => e.stopPropagation()}
      style={{
        position: 'fixed', top, left, width: 260,
        background: '#1e1e22',
        border: '1px solid rgba(108,140,255,0.3)',
        borderRadius: 8,
        padding: 12,
        boxShadow: '0 12px 28px rgba(0,0,0,0.5)',
        zIndex: 9999,
        color: '#e0e0e0', fontSize: 12,
        display: 'flex', flexDirection: 'column', gap: 8,
      }}
    >
      <div style={{ fontWeight: 600 }}>{t('bm.export.title')}</div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <input type="radio" checked={scope === 'all'} onChange={() => setScope('all')} />
        {t('bm.export.scope_all')}
      </label>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <input type="radio" checked={scope === 'one'} onChange={() => setScope('one')} />
        {t('bm.export.scope_one')}
      </label>
      {scope === 'one' && (
        <select
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
          style={{
            background: '#1e1e22', color: '#e0e0e0',
            border: '1px solid rgba(255,255,255,0.15)',
            borderRadius: 4, padding: '4px 6px',
          }}
        >
          {categories.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      )}
      <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)', margin: '4px 0' }} />
      <div style={{ fontSize: 11, opacity: 0.7 }}>{t('bm.export.format_label')}</div>
      {(['json', 'markdown', 'geojson', 'csv'] as BookmarkExportFormat[]).map((f) => (
        <label key={f} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="radio" checked={format === f} onChange={() => setFormat(f)} />
          {t(`bm.export.format_${f}` as any)}
        </label>
      ))}
      <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
        <button className="action-btn" onClick={onClose} style={{ flex: 1 }}>
          {t('generic.cancel')}
        </button>
        <a
          className="action-btn primary"
          href={url}
          download
          onClick={() => onClose()}
          style={{ flex: 1, textAlign: 'center' }}
        >
          {t('bm.export.download')}
        </a>
      </div>
    </div>,
    document.body,
  )
}

export default ExportPopover
```

- [ ] **Step 2: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS — file is self-contained.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ExportPopover.tsx
git commit -m "feat(frontend): ExportPopover (scope + format radios, anchor-positioned)"
```

---

## Task 18: Replace `<a download>` Export with ExportPopover trigger in BookmarkList

**Files:**
- Modify: `frontend/src/components/BookmarkList.tsx`
- Modify: `frontend/src/components/ControlPanel.tsx`

- [ ] **Step 1: Replace BookmarkList Export button**

In `BookmarkList.tsx`, the existing `exportUrl ? <a download .../>` block. Update `BookmarkListProps`:

```tsx
  // Replaces exportUrl. The legacy single-URL property is retained for
  // backward compat but ignored when onExportClick is wired.
  onExportClick?: (anchor: DOMRect) => void;
  exportUrl?: string;
```

Replace the `exportUrl && <a ... />` block with:

```tsx
        {(onExportClick || exportUrl) && (
          <button
            className="action-btn"
            onClick={(e) => {
              if (onExportClick) {
                onExportClick((e.currentTarget as HTMLButtonElement).getBoundingClientRect())
              }
            }}
            style={{ padding: '3px 6px', fontSize: 12, marginLeft: 'auto', display: 'inline-flex', alignItems: 'center' }}
            title={t('bm.export_tooltip')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
          </button>
        )}
```

Destructure `onExportClick` in the component signature.

- [ ] **Step 2: Wire ExportPopover from ControlPanel**

In `ControlPanel.tsx`, near where `<BookmarkList .../>` is rendered, add component-local state:

```tsx
  const [exportAnchor, setExportAnchor] = useState<DOMRect | null>(null)
```

Add to imports:

```tsx
import ExportPopover from './ExportPopover'
```

Pass `onExportClick`:

```tsx
                  onExportClick={(rect) => setExportAnchor(rect)}
```

After `<BookmarkList .../>` (still inside the same wrapper), add:

```tsx
                <ExportPopover
                  open={exportAnchor !== null}
                  anchorRect={exportAnchor}
                  categories={categories}
                  onClose={() => setExportAnchor(null)}
                />
```

- [ ] **Step 3: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/BookmarkList.tsx frontend/src/components/ControlPanel.tsx
git commit -m "feat(frontend): replace export <a> with ExportPopover (scope + format)"
```

---

## Task 19: Manual smoke + dev build

**Files:** none (verification only)

- [ ] **Step 1: Backend test suite**

Run: `cd backend && python3 -m pytest -v`
Expected: PASS — all goldditto tests + new bookmark tests green.

- [ ] **Step 2: Frontend typecheck + build**

Run: `cd frontend && npm run build`
Expected: PASS — no TS errors, vite produces `dist/`.

- [ ] **Step 3: Local smoke (manual)**

1. Start LocWarp (`./start.sh` on macOS, `LocWarp.bat` on Windows).
2. In Library, create category `test-event` and bulk-paste 3 sample coords.
3. Switch SimMode to GoldDitto. Click `📚` next to A → select `test-event` → click a bookmark → A field updated.
4. Click `📚` next to A again → click `End event 🗑` → confirm modal → confirm → category and bookmarks gone.
5. In Library, click Export → popover opens. Pick scope `single category` → pick `test-event` (or any remaining one if test-event was deleted) → format `Markdown` → Download. Open the file; verify §7 layout.
6. Pick format `GeoJSON` → Download → drop the file into [geojson.io](https://geojson.io) — points appear at correct map locations.
7. In Library category manager, click any non-Default category's trash icon → dropdown appears with two options. Pick the cascade variant; confirm; verify both category and bookmarks are gone.
8. In Library, Import a previously-exported single-category JSON file. Verify the category and bookmarks reappear.

- [ ] **Step 4: Commit (only if any tweaks needed; otherwise skip)**

```bash
git status
# If files were touched during smoke, commit; otherwise nothing to do.
```

---

## Self-Review Checklist (run before handing off)

- [ ] Every spec section in `2026-05-09-goldditto-bookmark-management-design.md` has a corresponding task.
- [ ] No "TBD" / "TODO" / placeholder steps.
- [ ] Function names align across tasks: `delete_category(cat_id, cascade)`, `to_markdown / to_geojson / to_csv / to_json`, `detect_and_import`, `BookmarkPickerPopover`, `ExportPopover`, `bookmarksExportUrl`, `deleteCategory(id, cascade)`.
- [ ] Cascade-vs-soft delete invariants hold: `default` cannot be deleted regardless; `?cascade=true` returns `deleted_bookmarks > 0` only when bookmarks existed.
- [ ] Markdown format in Task 3 test matches `§7` of the spec exactly (header, blank line, `Exported`, `---`, blank line, name + coord pairs blank-line separated, no trailing blank).
- [ ] GeoJSON coordinates ordered `[lng, lat]`.
- [ ] Frontend follows existing inline-popover / `createPortal` pattern (no new generic ConfirmModal abstraction).
