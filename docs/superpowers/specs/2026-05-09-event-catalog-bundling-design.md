# Event Catalog Bundling — Design

**Date:** 2026-05-09
**Status:** Draft (pending user review)
**Author:** Ravi Wu
**Type:** Feature design (extends event soft-archive 2026-05-09-event-soft-archive-design.md)

---

## 1. Background

The event soft-archive feature gives the data model a place to express
"this event runs from 2026-02-06 to 2026-06-07". The author of LocWarp
already curates Pikmin Bloom event GPS lists from the official site
(Sapporo Tour, Sanga Stadium, future events). Today this curation lives
only in `docs/samples/pikmin-bloom-events.json` and reaches end users via
manual file import — friction, plus end users don't know about it.

Goal: every release ships the curated catalog as part of the build, and
end users can pull it into their store with one click without losing
their own data.

## 2. Goals

1. Ship a curated `catalog.json` inside the build, owned by the LocWarp
   author (Ravi). One source file, version-controlled.
2. Expose a Library button "更新公開活動清單 (N new)" that fetches the
   bundled catalog and merges it into the user's store, idempotently.
3. Show the user how many entries would be added BEFORE they click
   "Confirm" — so a no-op click discovers a no-op.
4. Reuse the existing `POST /api/bookmarks/import` merge logic
   (id-collision → skip) so a user who edited a previously-imported
   bookmark name doesn't get overwritten.
5. Catalog updates ride the existing release cadence — push to git,
   build the dmg, ship.

## 3. Non-Goals

- **No auto-import on first run.** Users opt in by clicking the button.
  Avoids surprise data; keeps a single trigger path.
- **No remote-URL fetch.** Catalog ships in the build. No network calls
  for catalog updates between releases. (Trade-off: between-release
  hotfixes need a build; acceptable for monthly cadence.)
- **No deletion when curator removes an entry from catalog.json.** The
  user keeps any previously-imported bookmark even if the curator
  decides it's stale. (User can delete manually via Library.)
- **No force-overwrite mode.** Curator changes name/coords on an
  existing id → end user's local copy stays as-is. (Curator can bump
  the id to force re-add as a new entry, but that's manual.)
- **No "what's new" diff dialog.** The button label shows `(N new)`
  count; that is enough information for the user. Listing names would
  duplicate the Library after import.
- **No catalog versioning / settings tracking.** The merge endpoint is
  idempotent on id; running it twice has no extra effect.

## 4. Architecture

```
┌──────────────────────────┐         ┌──────────────────────────┐
│ backend/static/catalog.  │         │ ~/.locwarp/bookmarks.json│
│   json (in build)        │ ───────▶│  (user data, persisted)  │
│                          │  GET +  │                          │
│                          │  merge  │                          │
└──────────────────────────┘         └──────────────────────────┘
            ▲                                     ▲
            │                                     │ POST /api/bookmarks/import
            │ GET /api/bookmarks/catalog          │ (existing, reused)
            │                                     │
            │   ┌─────────────────────────────────┘
            │   │
       ┌────┴───┴────────────────────────┐
       │ Library button                  │
       │  "更新公開活動清單 (N new)"      │
       │  - fetch catalog                │
       │  - compute N                    │
       │  - on click: import             │
       └─────────────────────────────────┘
```

The frontend computes `N` by intersecting the catalog's bookmark ids
against the current store's bookmark ids. Categories alone don't bump
the counter (fewer than bookmarks; presence is implied).

## 5. Data

### 5.1 Bundled file

Location: `backend/static/catalog.json`.

Move the existing `docs/samples/pikmin-bloom-events.json` to that path
verbatim. The schema is the existing full-store import shape with the
optional `_meta` block at top:

```json
{
  "_meta": { "title": "...", "description": "...", "compiled_at": "...", "format_version": 1 },
  "categories": [ { "id": "seed-...", "name": "...", "color": "...", "sort_order": 1, "created_at": "...", "start_date": "", "end_date": "" } ],
  "bookmarks": [ { "id": "seed-...", "name": "...", "lat": ..., "lng": ..., "category_id": "seed-...", ... } ]
}
```

`_meta` is dropped by Pydantic on import (`extra='ignore'`) — already
the case today. `start_date` / `end_date` ride along.

PyInstaller already bundles `backend/static/` (it ships `phone.html`).
The new file lands automatically in the dmg. Verify with the existing
build script (`build-installer-mac.sh`) that the file appears under
`backend/static/` of the packaged app.

### 5.2 Endpoint

```
GET /api/bookmarks/catalog → application/json
```

- Reads `backend/static/catalog.json` from the install directory.
- Returns the JSON body directly (no transformation; let the
  frontend handle merging via the existing import flow).
- 200 with the body on success.
- 404 if the file is missing (non-fatal — UI hides the button).
- 500 if the file is unreadable or malformed (UI shows a generic error).

The endpoint is **read-only**. No auth, no side effects.

## 6. Frontend Changes

### 6.1 Button location

Library header row, between the existing **Import** button and **Export**
popover trigger. Visually: it's a sibling of the existing data-movement
buttons, not a separate cluster.

### 6.2 Button states

| State | Label (zh-TW) | Label (en) | Behavior |
|---|---|---|---|
| Loading catalog | `更新公開活動清單 …` | `Refresh public events …` | Disabled, spinner-style |
| `N === 0` | `已是最新` | `Up to date` | Disabled, tooltip explains |
| `N > 0` | `更新公開活動清單 ({N} new)` | `Refresh public events ({N} new)` | Enabled |
| Catalog 404 | (button hidden) | (button hidden) | No catalog bundled |
| Catalog 500 | `更新失敗` | `Update failed` | Disabled, tooltip shows error detail |

`N` is the count of catalog **bookmark** ids not present in the user's
store (`store.bookmarks` set difference). Categories are not counted —
in practice an event always brings ≥1 bookmark; a category-only delta
should be rare and fine to skip from the count.

### 6.3 Click flow

1. User clicks button.
2. Frontend sends `POST /api/bookmarks/import` with the catalog body.
3. Backend `detect_and_import` recognises the full-store shape, calls
   the existing merge path. Returns `{ scope: 'full_store', imported: K, skipped: M }`.
4. Frontend toast: `已加入 {K} 筆 (跳過 {M} 筆已存在)` /
   `Added {K} entries ({M} already present, skipped)`.
5. Refresh the bookmark list. Button label recomputes, falling to
   `已是最新` / `Up to date`.

No confirmation modal. The action is reversible (user can delete the
new categories via Library). Confirmation would be a heavy gate for
a low-stakes additive write.

### 6.4 Lifecycle

- Catalog fetched on Library mount; refreshed when the user opens the
  Library after closing it (existing pattern). No auto-refresh
  background polling.
- After a successful merge, refetch the catalog to recompute `N` (it
  should drop to 0 unless catalog was bumped between fetch and merge —
  not worth handling).

### 6.5 i18n keys (new)

```ts
'bm.catalog.refresh':              { zh: '更新公開活動清單',         en: 'Refresh public events' },
'bm.catalog.refresh_count':        { zh: '更新公開活動清單 ({n} new)', en: 'Refresh public events ({n} new)' },
'bm.catalog.up_to_date':           { zh: '已是最新',                  en: 'Up to date' },
'bm.catalog.up_to_date_tooltip':   { zh: '無新活動可加入',            en: 'No new events available' },
'bm.catalog.failed':               { zh: '更新失敗',                  en: 'Update failed' },
'bm.catalog.imported':             { zh: '已加入 {imported} 筆 (跳過 {skipped} 筆已存在)',
                                     en: 'Added {imported} entries ({skipped} already present, skipped)' },
```

## 7. Testing

### 7.1 Backend (pytest)

Append to a new `backend/tests/test_bookmark_catalog.py`:

- `test_get_catalog_returns_bundled_payload(client)` — endpoint returns
  the seed JSON (categories + bookmarks present, dates round-trip).
- `test_get_catalog_404_when_file_missing(client, tmp_path)` — patch
  the catalog path to a non-existent file, expect 404.
- `test_get_catalog_500_when_malformed(client, tmp_path)` — write
  garbage to the catalog file, expect 500.

(Existing import tests already cover the merge semantics, so no new
import-side tests are needed.)

### 7.2 Frontend (manual smoke)

1. With seed merged into local store (current state), open Library.
   Button should read `已是最新` and be disabled.
2. Delete one Sapporo bookmark. Reopen Library. Button reads
   `更新公開活動清單 (1 new)`. Click. Toast `已加入 1 筆 (跳過 12 筆已存在)`.
   Bookmark reappears.
3. Delete the Sapporo Tour category with cascade (drops 12 bookmarks).
   Reopen Library. Button reads `(12 new)`. Click → toast `已加入 12 筆`.
   The Sapporo Tour category and its 12 bookmarks reappear; Sanga
   Stadium is untouched.
4. Bump catalog locally (add a fake new spot to `catalog.json`,
   restart backend). Library button shows `(1 new)`. Click → it lands
   in the right category.

## 8. Edge Cases

| Scenario | Behavior |
|---|---|
| Catalog file missing in dev tree | 404 → button hidden. |
| Catalog file present but empty `[]` | 200; button reads `已是最新`. |
| Catalog category id collides with user-renamed local category | Existing import path appends with new uuid; user sees a duplicate-named category. Acceptable rare case (curator-controlled ids prevent collision in practice). |
| Catalog bookmark id matches a user's edited bookmark | id-collision → skip; user's edit preserved. |
| Catalog `start_date` is in the past | Imported as `ended` straight away; soft-archive default-collapses it. Correct behavior — old events ship as historical. |
| Network/IPC error fetching catalog | Button reads `更新失敗`; tooltip carries detail. Retry on next Library open. |
| User clicks rapidly twice | Second click's POST has nothing new to import (first one already merged). idempotent. |
| Catalog updated while button click is in flight | Race window narrow; second-best `N` computed from stale catalog. Refetch after import covers this. |

## 9. Open Questions

None at design approval time.
