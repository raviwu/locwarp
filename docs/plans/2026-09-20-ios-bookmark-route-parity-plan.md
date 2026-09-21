# LocWarp-iOS — Bookmark / Route Feature Parity Plan

**Date:** 2026-09-20
**Status:** Draft — awaiting approval (Plan-First; no code written against this plan yet)
**Repo:** `~/personal/locwarp-ios` (implementation) — this document lives in `~/personal/locwarp` per existing convention (`docs/plans/2026-05-15-bookmark-hide-category-design.md`, `docs/plans/2026-05-15-bookmark-geo-info-design.md`, `docs/plans/2026-09-19-ios-standalone-feasibility-evaluation.md`).
**Builds on:** the 2026-09-19 feasibility evaluation (decision D9: iCloud Drive shared folder + full CRDT port, Mac app stays in service) and the shipped Phase 1.0 spike (read-only bookmarks + teleport, read-only saved routes + multi-stop movement).

## 0. Current state (baseline, verified against the running build)

| Area | iOS today |
|---|---|
| Bookmarks tab | Flat, unsorted `List`. No category grouping, no collapse, no sort, no hide. Read-only — teleport only. `Bookmark.swift` already decodes `countryCode/timezone/city/region`, but nothing renders them. |
| Route tab | Flat `List` of saved routes, unsorted (`SavedRouteRepository.reload` assigns `categories = store.categories` and `routes = store.aliveRoutes` with no ordering). 3-way walking/cycling/driving speed picker at replay time; no visible km/h. |
| Write path | None. Both repositories are read-only decoders of `<sync_folder>/{bookmarks,routes}.json`, filtered by tombstone-alive only — no merge, no per-unit CRDT, no writes. |
| Backup | None on iOS. Mac has a 5-minute rotating local backup (`~/.locwarp/backups/`), unrelated to the sync folder. |
| Geo/country info | Decoded, not displayed. |

Everything below is additive to this baseline; nothing here proposes changing the sync-folder file format, since the Mac app keeps writing it and both sides must keep decoding it identically.

---

## 1. Requirement-by-requirement design

### R1 — Bookmark category display: collapse / sort / hide

**Mac semantics** (`docs/plans/2026-05-15-bookmark-hide-category-design.md`, `backend/services/bookmarks.py:413`):
- **Sort** — `list_categories()` returns categories ordered by `sort_order` ascending. `sort_order` is a domain field on `BookmarkCategory` (synced, part of `CATEGORY_MERGE_UNITS`), set to `max(existing) + 1` on create. The Mac frontend has no drag-to-reorder UI for categories — `sort_order` is creation-order only, not user-adjustable today.
- **Collapse** and **hide** are both *per-device UI state*, not domain data: stored in `~/.locwarp/settings.json` (`bookmark_expanded_categories`, `bookmark_hidden_categories`), never written into `bookmarks.json`, never synced. Each is a `Set<categoryId>`. Hidden categories disappear entirely from the browse view (header + items); an "N hidden ▸" affordance at the bottom lists them with an un-hide action. Search bypasses both — a hidden category's bookmarks still show up in search results.
- Stale IDs (a since-deleted category) are intersected out of the persisted sets on every load, so nothing lingers.

**iOS design:**
- Rewrite `BookmarkListView.swift`'s flat `List` into `Section`-grouped-by-category, sections ordered by `BookmarkCategory.sortOrder` ascending (matches Mac's `list_categories`).
- New small local-only store, `CategoryUIState` (a thin `UserDefaults`-backed `ObservableObject`, one instance shared by Bookmarks and Route tabs, keyed by store kind + category id) holding `expanded: Set<String>` and `hidden: Set<String>`. This mirrors the Mac's "not iCloud-synced, personal view preference" semantics exactly — `UserDefaults` is per-device by construction, so no extra work is needed to keep it from leaking into the shared folder.
- Section header: name, count, chevron (collapse toggle), eye-off button (hide toggle, same interaction as Mac: tap sets `hidden`, `stopPropagation` equivalent so it doesn't also toggle collapse).
- Bottom "N hidden ▸" row, expandable, each row has an eye button to restore.
- On reload, intersect both sets against the live category id set (stale cleanup).
- Sort is display-only in this slice — see Decision 5 below on whether Ravi also wants a drag-to-reorder UI that writes `sort_order` back.

**Files:** `LocWarpIOS/BookmarkListView.swift` (rewrite), new `LocWarpIOS/Services/CategoryUIState.swift`.
**Effort:** 1–2 days.

### R2 — Bookmark write path: add / edit / delete across devices via the sync folder

This is the largest single item. It requires porting the CRDT write path, not just reading it.

**Mac semantics** (`backend/services/bookmarks.py`, `backend/domain/store_merge.py`):

| Operation | Behavior |
|---|---|
| `create_bookmark(name, lat, lng, address, category_id, country_code)` | New UUID, rounds coordinates, invalid `category_id` falls back to `"default"`, stamps `created_at`/`updated_at`/`last_used_at` = now, then `enrich_bookmark()` fills empty geo fields. |
| `update_bookmark(id, **kwargs)` | Partial update over `{name, lat, lng, address, category_id, last_used_at, country_code}`. Diffs before mutating — **a no-op call skips `_save()` entirely** (must not re-stamp `updated_at` on a no-change save, or it reverts a peer's un-synced edit on the next merge). If `lat`/`lng` changed, re-resolves geo fields with `force=True`. Stamps only the merge **units** actually touched (`stamp_units`, not a whole-record touch). |
| `delete_bookmark(id)` | Removes the record, appends a tombstone `{id, kind: "bookmark", deleted_at: now}`. |
| `create_category` / `update_category` (same no-op-skips-save rule) / `delete_category(cascade)` | Cascade=false reparents that category's bookmarks to `default` (bumping their `updated_at`); cascade=true tombstones each bookmark individually. `default` can never be deleted. |
| **Save** | Every `_save()` is an *unconditional read-merge-write*: re-read the on-disk file, `merge_stores(in-memory, on-disk)`, write the merged result, and that merged result becomes the new in-memory state. This is what makes concurrent writers (two Macs, or a Mac + this iOS app) converge instead of clobbering. |

Merge unit tables (`backend/domain/store_merge.py:64-77`, confirmed by direct read):
```
BOOKMARK_MERGE_UNITS = {
    "name":        ("name",),
    "coords":      ("lat", "lng", "country_code", "timezone", "city", "region"),
    "address":     ("address",),
    "category_id": ("category_id",),
    "last_used_at":("last_used_at",),
}
CATEGORY_MERGE_UNITS = {
    "name": ("name",), "color": ("color",),
    "sort_order": ("sort_order",), "dates": ("start_date", "end_date"),
}
```
The geo fields ride inside the `coords` unit — they are never stamped on their own, since `enrich_bookmark` is their sole author and it never stamps.

**iOS design:**
- Port `stamp_units`, `merge_records` (per-unit LWW: newer unit stamp wins → tie on record `updated_at` → tie on a symmetric content sort), `merge_stores`, and the two merge-unit tables above into a new `LocWarpIOS/Domain/BookmarkMerge.swift`, field-for-field, mirroring the existing `RouteInterpolator.swift` porting style (pure functions, no I/O).
- Every local mutation (add/edit/delete bookmark or category) follows the Mac's exact read-merge-write shape: reload a fresh `BookmarkStoreFile` from disk → apply the mutation with the same diff-before-mutate / no-op-skips-write / partial-update rules as `update_bookmark`/`update_category` → `merge_stores(mutated, freshDiskRead)` → write via the same `NSFileCoordinator` pattern `SavedRouteRepository`/`BookmarkRepository` already use for reads.
- New `LocWarpIOS/Services/BookmarkWriter.swift` (or extend `BookmarkRepository`) exposing `createBookmark`, `updateBookmark`, `deleteBookmark`, `createCategory`, `updateCategory`, `deleteCategory(cascade:)` — signatures mirroring the Python methods above.
- UI: an Add sheet (name, category picker, address optional, location via a MapKit pin-drop or manual lat/lng entry — reuse `RouteMovementEngine`'s map affordances if any exist, otherwise a simple `MapKit` tap-to-pin), an Edit sheet (same fields), swipe-to-delete / long-press context menu on each row, and a "move to category" action.
- **Cross-language correctness fixtures**: port the Python `test_store_merge_per_field.py` fixed-seed (`20260827`) property test's input/output pairs into JSON fixtures a Swift test target asserts against field-for-field — the feasibility doc explicitly recommends this (§5.1) and no such fixture exists yet on either side.

**Decision points (flagged, not decided here — see §4):**
- Geo enrichment on iOS-originated bookmarks (full offline resolver vs. leave blank for the next Mac sweep to fill).
- Whether category create/rename/delete ships in this round or only bookmark-level CRUD against existing categories.

**Files:** new `Domain/BookmarkMerge.swift`, `Services/BookmarkWriter.swift`, new Add/Edit SwiftUI sheets, edits to `BookmarkListView.swift`.
**Effort:** 6–9 days (the CRDT port alone is comparable to the Mac's own 391-line `store_merge.py` plus fixture work; UI add/edit/delete is another 2–3 days on top).

### R3 — iOS-side backup

**Mac semantics** (already fully documented in this repo's top-level `CLAUDE.md` — no re-derivation needed): `BackupService.tick` runs every 5 minutes, writes `locwarp-latest-backup.json` unconditionally and a timestamped archive only when the data actually changed (fingerprint excludes `_backup_meta`), skips entirely when both stores are empty (guards transient iCloud eviction), retains 720h/30 days pruned by filename timestamp, and — since the 2026-09-18 fix — snapshots carry tombstones so a restore cannot resurrect a deletion. Combined snapshot shape: `{_backup_meta, bookmarks: {categories, items, tombstones}, routes: {...}}`. Lives at `~/.locwarp/backups/`, deliberately outside the synced folder.

**iOS design:**
- Same shape, same location semantics: write to the app's own `Documents/Backups/` (sandboxed, private to the app — the iOS equivalent of "outside the synced folder," since it's outside the shared iCloud Drive folder entirely).
- Cadence: iOS has no persistent background timer (per the 2026-09-19 feasibility doc's background-execution findings, a Mac-style always-on 5-minute loop does not survive backgrounding on iOS). Practical substitute: snapshot on **app foreground** and **immediately after every successful local write** (R2), using the identical fingerprint-excluding-`_backup_meta` dedup and 30-day retention-by-filename rule. This gives a rescue copy without needing background execution entitlements.
- **Restore scope for v1** is a decision point (§4): a full in-place restore is a destructive, hard-to-reverse write against the *shared* sync folder — this crosses the guardrail that irreversible/outward-facing actions need explicit confirmation. Recommend v1 ships snapshot-taking + a read-only "view latest backup" screen only; a guarded restore flow (dry-run diff shown before commit, matching the Mac's `DRY_RUN=1`-first culture) is a follow-up once R2's write path has some mileage on it.

**Files:** new `LocWarpIOS/Services/BackupService.swift`, a small viewer in `SettingsView.swift` or a new tab.
**Effort:** 2–3 days for snapshot-only v1; +2–3 days if a guarded restore ships in the same round.

### R4 — Route category display

Identical treatment to R1, applied to `RouteView.swift`. `RouteCategory` already has the same `sortOrder` field; `ROUTE_CATEGORY_MERGE_UNITS` (`name`, `color`, `sort_order` — no dates) is the route-side equivalent, already confirmed in `store_merge.py`. Reuse the `CategoryUIState` component built for R1 rather than duplicating it — the only difference is which store kind it's keyed under.

**Open question:** the original ask only requested hide for bookmarks ("書籤的「Category」可以顯示摺合、Sort、隱藏"), and separately "Route 也需要有 Category 的顯示" without repeating "隱藏." Recommend applying collapse + sort to routes now and hide as well for consistency (it's the same component, near-zero marginal cost) — flagged in §4 in case Ravi wants routes to stay simpler.

**Files:** `LocWarpIOS/RouteView.swift` (rewrite grouping), reuses `CategoryUIState.swift`.
**Effort:** 0.5–1 day (mostly free once R1's component exists).

### R5 — Route speed parity with Mac + visible km/h

**Mac's `SPEED_PROFILES`** (`backend/config.py:175-179`, confirmed by direct read):

| Mode | m/s | km/h | tick interval |
|---|---|---|---|
| walking | 3.0 | 10.8 | 1.0s |
| running | 5.5 | 19.8 | 0.5s |
| driving | 16.7 | 60.1 | 0.5s |

iOS's current `RouteProfile` (`Services/OSRMRouteService.swift`) has walking (3.0, matches) and driving (16.7, matches), plus **cycling** (4.17 m/s / 15 km/h) which **Ravi explicitly requested last turn** and which **has no Mac-side equivalent**. Mac's third mode is **running** (5.5 m/s), which iOS currently lacks entirely.

"跟 Mac APP 一樣" is ambiguous between two readings, and reversing last turn's explicit request without confirming would be a mistake either way — this is **Decision 1** in §4: keep the walking/cycling/driving set (already shipped; "same as Mac" then means the two shared modes' numbers match, which they already do), or replace cycling with running for an exact 3-mode mirror of the Mac.

Regardless of which mode set is chosen, the second half of the ask — **visibly showing the configured km/h** — is independent and straightforward: display `"\(mode.label) · \(Int(mode.speedMps * 3.6)) km/h"` in the segmented picker or the status bar, computed directly from the already-correct `speedMps` values (no new source of truth needed, no risk of drifting from Mac's numbers since walking/driving are literal copies of `SPEED_PROFILES`).

**Files:** `LocWarpIOS/Services/OSRMRouteService.swift` (mode set, pending Decision 1), `LocWarpIOS/RouteView.swift` (km/h label).
**Effort:** <0.5 day for the km/h display; the mode-set change (if any) is a one-line edit either way.

### R6 — Country info on Teleport (Bookmarks tab)

**Mac design** (`docs/plans/2026-05-15-bookmark-geo-info-design.md`): every bookmark already carries `country_code`, `timezone`, `city`, `region`, populated offline on the Mac (`geo_offline.py` — `timezonefinder` + bundled GeoNames extract). The Mac frontend renders a two-line row: name, then flag · short country name · city · GMT offset (derived from the IANA zone at render time, never stored).

**iOS design:** this is purely additive rendering — the fields are already decoded (`Bookmark.swift:37-40`), nothing upstream needs to change.
- **Flag**: recommend a Unicode regional-indicator emoji derived from `countryCode` (two-line Swift function, zero network dependency, zero asset weight) instead of porting the Mac's `flagcdn.com` image dependency — more robust for a mobile app that may be offline in the field, which is exactly this app's normal operating condition.
- **Country name**: port `frontend/src/i18n/countries.ts`'s ~250-entry code→short-name table into a small Swift dictionary (or bundle it as a JSON asset).
- **GMT offset**: `TimeZone(identifier: bookmark.timezone)?.secondsFromGMT()` formatted as `GMT+8` — the direct Swift equivalent of the Mac's `Intl.DateTimeFormat(..., timeZoneName: 'shortOffset')`, and DST-correct for the same reason (computed at render time from the real `TimeZone` API, not stored).
- Apply the two-line layout to both the list row and any future detail/edit view (R2).

**Files:** `LocWarpIOS/BookmarkListView.swift`, new `LocWarpIOS/Support/Countries.swift` (or a bundled JSON asset).
**Effort:** 1 day.

---

## 2. Cross-cutting: the shared CRDT/domain port

R2 (and to a lesser extent R1/R4's sort field) all sit on top of the same Swift port of Mac's pure-function domain layer. Consolidating so it's built once:

| Python module | LOC | Swift target | Confidence |
|---|---|---|---|
| `domain/store_merge.py` | 391 | `Domain/BookmarkMerge.swift` (merge_records, merge_stores, stamp_units, unit tables) | High — pure functions, already has a fixed-seed property test to port as a fixture |
| `domain/movement.py` | 523 | *(already ported)* `Domain/RouteInterpolator.swift` | Done |
| `domain/backup.py` | 95 | folded into `Services/BackupService.swift` (R3) | High |
| `services/geo_offline.py` | — | **not ported in this round** — see Decision 2 | Deferred |

This table exists so R2's estimate isn't hiding an undiscovered dependency: everything it needs beyond what's already shipped is `store_merge.py`, and that module has no I/O and a deterministic fixed-seed test suite that transfers cleanly as JSON fixtures.

---

## 3. Survey: other Mac features worth porting

Ranked by fit for "personal + family use, standalone iOS, no companion Mac in the runtime loop" (per the 2026-09-19 feasibility doc's own scoping) — not a commitment, a backlog for Ravi to triage.

**Tier A — natural extensions of what's being built this round:**
- **Bookmark import/export** (JSON/GeoJSON/CSV) — `services/bookmark_export.py` (140 LOC) is a clean port; pairs naturally with R2's write path and R3's backup viewer.
- **Route import/export + GPX import** (`api/route.py` gpx endpoints) — same rationale for routes; `vincentneo/CoreGPX` is a usable MIT dependency per the feasibility doc, but LocWarp's own track>route>waypoint priority + monotonic-timestamp rule (`gpx_service.py:23-76`) isn't provided by CoreGPX and needs a small custom layer on top.
- **Cooldown UX** (`services/cooldown.py`, 129 LOC, pure client-side anti-detection throttle on teleport) — currently absent on iOS entirely. Cheap and meaningfully protects against over-triggering a destination's anti-cheat/rate-limit heuristics.
- **Bulk move bookmarks/routes between categories** (`move_bookmarks`/`move_routes`) — becomes relevant as soon as category management (R2's category CRUD) ships.
- **Catalog seed sync** (140 curated bookmarks / 8 categories, three-way per-field merge) — nice-to-have for a fresh install, lower priority for an already-populated personal store.

**Tier B — meaningful, but a bigger lift or partially device-protocol-bound:**
- **Pause / resume / stop with a resumable snapshot** (`capture_resumable_snapshot`) — `RouteMovementEngine` today only has start/stop; pause/resume matters once multi-stop sees real use (e.g., a phone call mid-route).
- **Route loop mode, jitter, random walk** (`add_jitter`/`jitter_speed`/`random_point_in_radius` in `movement.py`) — explicitly out of scope in the 2026-09-19 doc, but the math is already 1:1-portable since it lives in the same file as the interpolator that's already ported.
- **WiFi tunnel auto-discovery** — iOS currently requires manually entering the tunnel IP in Settings; Mac auto-discovers. Lower priority since manual entry already works end-to-end.

**Tier C — Mac/desktop-specific; recommend NOT porting:**
- **Joystick mode** (200ms dead-reckoning drag loop) — high effort, low value for personal use.
- **Device pairing management / WiFi tunnel UI / `phone_control` HTML surface** (`api/device.py`, `api/phone_control.py`) — this entire surface exists because the Mac drives a *separate, remote* iPhone. On iOS-standalone the app *is* the phone; most of this is structurally inapplicable, not just low-priority.
- **Cloud-sync enable/disable onboarding prompt** — Mac-specific iCloud-detection onboarding; iOS already has its own folder-picker onboarding flow.

---

## 4. Decisions needed from Ravi

Per this project's Plan-First rule ("never make architectural or data-model decisions autonomously"), these are called out rather than assumed:

1. **Route speed 3rd mode** — keep walking/cycling/driving (already shipped) or switch to walking/running/driving for an exact Mac mirror? *Recommendation: keep cycling — it's already built and tested, and "same as Mac" is satisfied for the two modes that actually overlap; running can be added later as a 4th mode if wanted.*
2. **Geo enrichment for bookmarks created on iOS** — port the full offline resolver (tzf-swift + ~40MB bundled GeoNames data, per the feasibility doc's §5.1 gap-closure) now, or leave `timezone`/`city`/`region` blank and let them get silently backfilled the next time the Mac app runs its startup reconciliation sweep (which fills empties without bumping `updated_at`, so no merge conflict)? *Recommendation: defer the resolver — leave blank for now. It's a real app-size and complexity cost, and the backfill-on-next-Mac-launch path is already lossless by design.*
3. **Backup restore scope for v1** — snapshot-only safety net, or also a guarded restore-to-store flow in this same round? *Recommendation: snapshot-only first; a restore against the shared sync folder is exactly the kind of irreversible/outward-facing action this project's guardrails ask to slow down on.*
4. **Hide affordance on the Route tab** — apply it for consistency with Bookmarks, or keep Routes to collapse+sort only? *Recommendation: apply it — it's the same shared component, near-zero marginal cost.*
5. **Category sort semantics** — confirm "Sort" means *respect the existing `sort_order` field* (what's proposed above, matching Mac's own read-only ordering — the Mac frontend has no drag-to-reorder UI either), not a new drag-to-reorder capability that writes `sort_order`. If a reorder UI is actually wanted, that's additional write-path scope on top of R1.
6. **Category CRUD scope** — the ask was "書籤可以...新增、編輯、刪除" for bookmarks. Confirm whether category create/rename/delete ships in this round too, or only bookmark-level add/edit/delete against the categories that already exist (with category management following later).

---

## 5. Proposed phasing

| Phase | Scope | Depends on | Estimate |
|---|---|---|---|
| P1 | R1 + R4 (category display: collapse/sort/hide, both tabs) | Decisions 4–5 | 1.5–3 days |
| P2 | R5 + R6 (speed km/h display, country info rendering) | Decision 1 | 1.5 days |
| P3 | R2 (bookmark CRDT write path + add/edit/delete UI) | Decisions 2, 6 | 6–9 days |
| P4 | R3 (iOS backup) | P3 (backup-after-write hook) | 2–3 days (+2–3 if restore ships now, Decision 3) |

P1 and P2 have no dependency on P3/P4 and can ship first, independently, matching how R1–R6 were scoped above. P3 is the long pole; P4 is naturally sequenced after it since backup-on-write needs a write path to hook into.

---

## 6. Testing strategy

- **Cross-language golden fixtures** for the CRDT port (P3): export `test_store_merge_per_field.py`'s fixed-seed (`20260827`) property-test input/output pairs as JSON, assert field-for-field equality from a Swift test target. No such fixture exists on either side yet — this needs building, not just reusing.
- **Manual on-device verification** for everything UI-facing (category collapse/hide/sort, add/edit/delete, backup viewer, country info rendering) — this project has no XCUITest harness today; per this session's standing rule, UI changes get an honest "implemented, not yet verified on-device" status until Ravi confirms, same as the last two fixes (CoreDevice pairing, keyboard dismiss) that shipped without on-device confirmation yet.
- **Two-device convergence check** for P3 specifically: edit the same bookmark on the Mac and on iOS while offline from each other, then let both sync, and confirm the merge converges to the expected per-unit winner rather than one side clobbering the other — this is the one invariant that's silently wrong if the port has any bug, so it needs a deliberate test pass beyond unit fixtures.

---

## 7. Non-goals for this round

- Full offline geocoding on iOS (Decision 2, deferred by recommendation).
- Catalog seed sync, GPX import/export, bulk move (Tier A backlog — not blocking, not included unless Ravi pulls one forward).
- Anything in Tier B/C of §3.
- Any change to the on-disk JSON schema or merge semantics — this plan is additive/read-compatible with the Mac app throughout; the Mac app's own behavior is not touched.
