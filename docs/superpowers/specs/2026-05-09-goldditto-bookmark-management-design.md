# GoldDitto Bookmark Management — Design

**Date:** 2026-05-09
**Status:** Draft (pending user review)
**Author:** Ravi Wu
**Type:** Feature design (extends 2026-05-08 Pull Gold Ditto)

---

## 1. Background

The Pull Gold Ditto (拉金盆) mode shipped in `a34becc` lets the user enter a
single A coordinate (gold ditto / flower spot) and a single B coordinate
(physical real-GPS / restore point), then run a 1st-try cycle or
A↔B-alternating retries.

In real play the user collects dozens of GPS coordinates per event (e.g. a
"Pikmin Bloom 京都散步" event has 25 spots across 6 sub-regions). They keep
these spots in plain-text notes outside LocWarp and paste coordinates into the
A field one at a time. The B coordinate is also rarely a single fixed point —
the user has multiple physical locations they cycle between (home, office,
hotel).

The existing Bookmark system (categories, colors, bulk paste, JSON
import/export, multi-select bulk delete) is a strong foundation, but two gaps
block its use as a gold ditto spot list:

1. The GoldDitto panel does not consume bookmarks — A and B are free-text only.
2. Deleting a category leaves all its bookmarks orphaned in the default
   category. For ephemeral event lists ("end of this event → wipe everything"),
   this requires two manual steps and produces visual clutter in the meantime.

Export is JSON-only, integrates poorly with sharing channels (Threads, Slack,
plain-text notes), and only supports whole-store dumps.

## 2. Goals

- Let the user pick A and B from any bookmark category via a popover, without
  removing the existing free-text inputs.
- Add a "purge whole event" action that deletes a category together with all
  its bookmarks, in one confirmation.
- Surface that purge action both inside the GoldDitto picker (the natural
  end-of-event flow) and in the Library category manager.
- Support per-category export and human-friendly formats (Markdown, GeoJSON,
  CSV) so the user can share a single event list externally.
- Accept GeoJSON FeatureCollection on import as an alternative to LocWarp's
  internal JSON.

## 3. Non-Goals

- No paste-to-parse importer for free-form notes (e.g. the Threads-style
  multi-line region+spot blocks). The user accepted the existing Bulk Paste
  flow for bookmark entry.
- No new schema fields on `Bookmark` or `BookmarkCategory`. Sub-region
  information lives in the bookmark name as a prefix (e.g. `"京北 - 常照皇寺"`),
  by convention.
- No "A pool" / "B pool" tagging on categories. Any category may be selected
  as the source for either A or B.
- No keyboard hotkeys (UI buttons only at this stage).
- No cloud sync, multi-device backup, or migration tooling.
- No reconstruction of nested sub-region structure on Markdown export — the
  exporter emits a flat list (subgroup info remains visible only via the name
  prefix).

## 4. Data Model Decisions

The existing `BookmarkCategory` and `Bookmark` schemas are unchanged.
Conventions:

- A "GoldDitto event" is a `BookmarkCategory`. The category name is the event
  name (e.g. `"京都散步"`).
- Sub-regions live in the bookmark name prefix (e.g. `"京北 - 常照皇寺"`). The
  prefix is opaque to the system; it shows up wherever the name is rendered.
- Categories are not labelled "for A" or "for B". The user picks the category
  freely each time they open the picker.

## 5. Backend Changes

### 5.1 Cascade Category Delete

Extend the existing endpoint:

```
DELETE /api/bookmarks/categories/{cat_id}?cascade=<bool>
```

| `cascade` | Behaviour |
|---|---|
| `false` (default) | Existing behaviour: bookmarks in the deleted category move to `default`. |
| `true` | Bookmarks in the deleted category are deleted along with the category. |

Constraints:

- The `default` category remains undeleteable regardless of `cascade`.
- Response payload always includes `deleted_bookmarks: int`. With `cascade=false`
  the count is `0`; with `cascade=true` it is the actual count.

```json
{ "status": "deleted", "deleted_bookmarks": 25 }
```

`BookmarkManager.delete_category(cat_id, cascade=False)` becomes the canonical
method. The existing soft-delete code path is preserved for `cascade=False`.

### 5.2 Multi-format, per-category Export

Extend the existing endpoint:

```
GET /api/bookmarks/export?category_id=<id>&format=<json|markdown|geojson|csv>
```

| Param | Default | Notes |
|---|---|---|
| `category_id` | omitted = whole store | When set, the export contains only that category and its bookmarks. 404 if the id does not exist. |
| `format` | `json` | One of `json`, `markdown`, `geojson`, `csv`. |

#### 5.2.1 `json` (default) — round-trip-friendly

When `category_id` is omitted, behaviour matches today: full `BookmarkStore`
JSON.

When `category_id` is set, the response is a single-category subset wrapped
with metadata to keep the format stable across versions:

```json
{
  "_meta": {
    "exported_at": "2026-05-09T08:30:00Z",
    "format_version": 1,
    "scope": "category"
  },
  "category": { "id": "...", "name": "京都散步", "color": "#ef4444", "sort_order": 1, "created_at": "..." },
  "bookmarks": [ { "id": "...", "name": "京北 - 常照皇寺", "lat": 35.200425, "lng": 135.685626, ... } ]
}
```

This subset is accepted by `POST /api/bookmarks/import` (see §5.3).

#### 5.2.2 `markdown` — human-readable

See §7 for the exact format.

#### 5.2.3 `geojson` — interoperable

`FeatureCollection` of `Point` features. One feature per bookmark.

```json
{
  "type": "FeatureCollection",
  "name": "京都散步",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [135.685626, 35.200425] },
      "properties": { "name": "京北 - 常照皇寺", "category": "京都散步", "country_code": "jp" }
    }
  ]
}
```

Note: GeoJSON ordering is `[lng, lat]`.

#### 5.2.4 `csv` — spreadsheet-friendly

Four columns. UTF-8 with BOM for Excel compatibility.

```csv
name,lat,lng,category
"京北 - 常照皇寺",35.200425,135.685626,京都散步
```

### 5.3 Import Format Detection

Extend `POST /api/bookmarks/import` to detect input shape:

| Top-level shape | Treatment |
|---|---|
| `{ "categories": [...], "bookmarks": [...] }` | Existing full-store import. |
| `{ "_meta": ..., "category": ..., "bookmarks": [...] }` | Single-category JSON (§5.2.1). The category is appended (re-using its id if absent locally; otherwise a new id is minted to avoid collision). Bookmarks are appended with new ids when `category_id` is rewritten. |
| `{ "type": "FeatureCollection", ... }` | GeoJSON. A new category is created using `name` from the FeatureCollection (or `"Imported"` if absent). Each feature's `properties.name` is the bookmark name. |
| Any other shape | 400. |

Markdown and CSV are not accepted on import — they round-trip through their
authoring tools. A user wanting to bring data back in converts to GeoJSON or
JSON first.

## 6. Frontend Changes

### 6.1 GoldDittoPanel — A/B Picker (Popover, two-stage)

Each of the A and B inputs gains a `📚` button next to the existing free-text
input. Clicking opens a popover anchored to that button.

```
┌─ Pick A from bookmarks ────────┐
│ Category: [京都散步         ▾] │
│ ──────────────                  │
│ 京北 - 常照皇寺                  │
│   35.200425, 135.685626         │
│ 京北 - 山國神社                  │
│   35.173026, 135.655441         │
│ ...                             │
│ [Close]      [End event 🗑]    │
└─────────────────────────────────┘
```

- **Category select:** lists all categories (including `Default`). Default
  selection: the most recently used category for that side (A side and B side
  remember independently in localStorage as `goldditto.picker.A.lastCategory`
  / `.B.lastCategory`).
- **Bookmark list:** every bookmark in the selected category, with name and
  monospaced coords. Single-click writes the coords to the A or B free-text
  input, then closes the popover.
- **End event button:** see §6.2.

The free-text inputs remain editable. Picking from the popover overwrites the
text; manual edits afterwards take priority.

### 6.2 GoldDittoPanel — End Event (cascade delete from picker)

Inside the picker, an "End event" button. Clicking it opens a confirmation
modal:

```
End event "京都散步"?

⚠ This will also delete the 25 bookmarks in this category. Cannot be undone.

[Cancel]   [Delete event]
```

On confirm: call `DELETE /api/bookmarks/categories/{id}?cascade=true`, refresh
the bookmark store, close the popover. If the deleted category was the one
currently sourcing A or B, the free-text inputs keep their last value (the
cycle still works on the typed coords); only the "this came from a bookmark"
association is lost.

### 6.3 BookmarkList — Category Delete Dropdown

The trash icon on each row of the category manager becomes a small dropdown.
Hovering or clicking exposes two options:

```
京都散步      [✏]  [🗑 ▾]
                     ├ Delete category only (move bookmarks to Default)
                     └ Delete category + 25 bookmarks
```

Both options open a confirmation dialog. The cascade option uses red
highlighting on the action button. Both options are gated on the same
non-default-category rule.

### 6.4 Library — Export Popover

The current `<a download>` Export button opens a popover instead of triggering
a direct download:

```
┌─ Export ────────────────────────┐
│ Scope:                          │
│   ◯ All bookmarks               │
│   ● A single category           │
│      [京都散步              ▾]  │
│ Format:                         │
│   ● JSON (round-trip)           │
│   ◯ Markdown (human-readable)   │
│   ◯ GeoJSON                     │
│   ◯ CSV                         │
│ [Cancel]            [Download]  │
└─────────────────────────────────┘
```

The Download button issues `GET /api/bookmarks/export?...` with the chosen
params and streams the file. Filename derives from category name + format
(e.g. `京都散步.md`, `bookmarks.json` for whole-store JSON).

## 7. Markdown Export Format

```markdown
## 京都散步

Exported 2026-05-09T08:30:00Z

---

京北 - 常照皇寺
35.200425,135.685626

京北 - 山國神社
35.173026,135.655441

京北 - 金花山寶泉寺
35.167609,135.610546
```

Rules:

- Title is `## <category name>` (H2).
- Second line: `Exported <ISO8601 UTC timestamp>`.
- Thematic break `---` separates header from list.
- Each bookmark is name on one line, `lat,lng` on the next (no spaces around
  the comma; six decimal places — matching the existing `lat.toFixed(6)`
  convention used elsewhere in LocWarp).
- A blank line separates bookmarks.
- No trailing blank line at end of file.
- Category color, sort_order, ids, and created_at are not emitted.

When a bookmark name contains a literal `\n`, replace with a space (defensive;
the bookmark UI does not currently allow newlines but the API does not
explicitly forbid them).

Whole-store Markdown export (`category_id` omitted, `format=markdown`)
concatenates per-category sections separated by a blank line:

```markdown
## 京都散步

Exported 2026-05-09T08:30:00Z

---

京北 - 常照皇寺
35.200425,135.685626

...

## 我的常用點

Exported 2026-05-09T08:30:00Z

---

家
25.034897,121.545827

...
```

## 8. UX Flows

### 8.1 Run a fresh event end-to-end

1. (existing) In the Library, Bulk Paste 25 京都 spots into a new category
   "京都散步".
2. Switch SimMode to GoldDitto.
3. Click `📚` next to the A field → category dropdown shows "京都散步" → click
   "京北 - 常照皇寺" → A field is now `35.200425, 135.685626`.
4. (Optional) Same flow for B from the "我的常用點" category.
5. Press ② 1st try, play through the cycle.
6. Repeat 3–5 for other spots.
7. End of event: open the A picker again → click `End event 🗑` → confirm →
   25 bookmarks + the category are gone in one action.

### 8.2 Share an event with a friend

1. In the Library, click Export → popover opens.
2. Pick `Scope: A single category` → `京都散步`.
3. Pick `Format: Markdown`.
4. Click Download → `京都散步.md` saved.
5. Paste content into Threads / Slack / Notes.

A friend who wants to import:

1. Pastes the Markdown into a converter (out of scope) or asks the user to
   re-export as `JSON` or `GeoJSON`.
2. In the Library, click Import → choose the file → backend detects format
   per §5.3.

## 9. Error Handling

| Scenario | Behaviour |
|---|---|
| `DELETE` on `default` with `cascade=true` | 400, `Cannot delete default category` (matches current behaviour). |
| `DELETE` on missing id | 404. |
| `cascade=true` mid-flight: bookmark file write fails | Atomic `safe_write_json` already protects this. Rollback in-memory store on failure; surface 500 to caller. |
| Export with `category_id` that does not exist | 404. |
| Export with unsupported `format` value | 422 (pydantic). |
| Picker opened with no categories at all | Should not happen (Default always exists). Show the picker with Default selected and an empty list. |
| Picker opened during a cycle | Allowed — picking does not trigger the cycle. The free-text input reflects the new value when the cycle finishes. |
| User picks from popover then immediately edits the text | Free text wins (popover already closed). Next cycle uses the typed coords. |
| End-event confirm while cycle is mid-flight | Block: confirm button disabled, with hint "Wait for the cycle to finish". |
| GeoJSON import with malformed feature | Skip the bad feature, continue; report `imported: N` and `skipped: M`. |
| GeoJSON FeatureCollection with no `name` | Use `"Imported"` as category name. |
| Markdown export with bookmark name containing `,` | Allowed — only the line layout matters; the parser splits on the linebreak, not the comma. |
| Concurrent cascade-delete + cycle on different devices | The bookmark store has its own lock (`safe_write_json` is atomic); the engine's cycle lock is independent. No interaction. |

## 10. Testing

### 10.1 Backend (pytest)

- `BookmarkManager.delete_category(id, cascade=False)` keeps existing behaviour.
- `BookmarkManager.delete_category(id, cascade=True)` removes both category
  and its bookmarks.
- `BookmarkManager.delete_category("default", cascade=True)` raises (or returns
  failure handled by the API as 400).
- `delete_category` returns the count of deleted bookmarks.
- Export `format=markdown` emits the exact format in §7 (snapshot test).
- Export `format=geojson` emits a valid `FeatureCollection`; coords are
  `[lng, lat]`.
- Export `format=csv` is parseable by `csv.DictReader`; headers exact match.
- Export `category_id=<missing>` → 404.
- Export single-category JSON round-trips through Import.
- Import detects and accepts: full-store, single-category, GeoJSON.
- Import on garbage shape → 400.

### 10.2 Frontend

- GoldDittoPanel: clicking a bookmark in the popover writes its coords into
  the A or B free-text input.
- GoldDittoPanel: opening the picker remembers the last-used category per side.
- GoldDittoPanel: End event button is disabled while a cycle is in flight.
- BookmarkList category manager: dropdown exposes both delete options; cascade
  variant shows red action button.
- Library export popover: switching format updates the filename hint; Download
  hits the right URL.

### 10.3 Manual smoke

1. Create category "test-event", bulk-paste 5 spots.
2. GoldDitto panel → pick A from "test-event" → A field populated → ② 1st try
   → cycle works.
3. End event from picker → category and 5 bookmarks gone.
4. Library → Export, scope = "京都散步" (assume it exists), format = Markdown
   → file downloads, contents match §7 layout.
5. Library → Export, format = GeoJSON → drag the file into geojson.io → all
   points appear in the right map locations.

## 11. Open Questions

None at design approval time. Implementation may surface:

- Whether the existing export `<a download>` element supports the new query
  params cleanly or needs to become a `fetch + Blob` flow.
- Whether the BookmarkList category manager dropdown should also gate on
  `bookmarks.length === 0` (in which case "cascade" and "non-cascade" are
  identical and only one option needs to render).

These are mechanical and resolved in the implementation plan.
