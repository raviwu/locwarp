# Bookmark Edit Durability — E1 (catalog three-way merge) + F (partial-update PUT)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a bookmark the user edited from silently reverting to an older value. Two independent triggers are closed: the catalog force-sync wholesale-overwriting local edits (E1), and a full-record `PUT` blanking or reverting fields the user never touched (F).

**Architecture:** The store is a CRDT LWW-element-set that merges **whole records** by comparing `updated_at` strings (`backend/domain/store_merge.py:41-52`), and `update_bookmark` re-stamps `updated_at = _now_iso()` unconditionally (`backend/services/bookmarks.py:419`). Together these mean *a stale copy carrying a fresh timestamp beats a newer copy carrying an older one.* Neither E1 nor F changes that merge rule. Both work **upstream** of it, shrinking what gets written into a record in the first place: E1 decides per field whether the catalog may overwrite a local value before `_save()` runs; F stops the API layer from forwarding fields the client never sent.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, pytest. React 18 + TypeScript + Vitest. No new dependencies.

---

## Global Constraints

- **Pytest baseline: 1200 tests collected** (`cd backend && .venv/bin/python -m pytest --collect-only -q`, measured 2026-08-26 against the settled working tree, changes A–D included). Suite stays green after EVERY commit.
- **Frontend baseline: 986 vitest tests across 116 files**, `npx tsc --noEmit` clean, `depcruise` 0 violations (measured 2026-08-26, same tree). All three stay green after EVERY commit.
- **No on-disk format change to `bookmarks.json`.** This is the constraint that shapes both changes. The two Macs sync that file through iCloud; any schema change would need a coordinated upgrade. Neither E1 nor F touches it.
- **Clean-arch rings hold.** `domain/` stays pure (stdlib + pydantic, no I/O). `services/` raises domain errors, never `HTTPException`. Only `bootstrap/` + `main.py` read `Settings`/env. Import-linter must stay **7 kept, 0 broken**; dependency-cruiser **0 errors**.
- **Any new `~/.locwarp` path MUST be added to the autouse guard** `backend/tests/conftest.py::_isolate_real_data_paths`, following the `BACKUP_DIR` precedent (`conftest.py:68`) — **not** the `STICKY_DENIED_FILE` precedent (`config.py:94`), which is *not* covered by the guard and relies on every consuming test remembering to patch it.
- **English code/comments/docs.** Every user-facing string goes through `frontend/src/i18n/strings.ts` as 繁體中文 + English. Never Simplified Chinese, never Japanese.
- Personal repo: direct commits to `main`, one per task — except Tasks 4, 5 and 6, which land as one commit because E1's behavior change moves assertions all three own (see the note at Task 4). Auto git identity (never pass `-c user.email`). **Never push autonomously.**

---

## 1. Problem Statement

**Symptom:** Ravi renames a bookmark on one Mac; some time later it is back to its old name.

**Root cause (design level):** whole-record LWW plus an unconditional re-stamp.

| Evidence | What it does |
|---|---|
| `backend/domain/store_merge.py:41-52` (`_union_by_id`) | On an id collision, keeps the record with the newer `updated_at` **string** and discards the other one **whole**. No field-level merge exists. |
| `backend/services/bookmarks.py:419` | `bm.updated_at = _now_iso()` on **every** `update_bookmark` call, whether or not the caller's copy was current. |

**Two confirmed triggers.**

| # | Trigger | Evidence |
|---|---|---|
| 1 | **Catalog force-sync.** `POST /api/bookmarks/catalog/sync` → `import_catalog` → `_upsert_items(stamp_now=False, enrich_force=True)`. The update branch at `backend/services/bookmarks.py:560-565` unconditionally copies `name / lat / lng / address / category_id / country_code` from the catalog onto the live record (and `:566` copies `updated_at`); the category loop at `:653-657` does the same for `name / color / sort_order / start_date / end_date` (and `:658` stamps `updated_at = now`). `force_seed_items` (`:645-646`) stamps the incoming records so the overwrite also wins on the *other* Mac. Ravi has 140 catalog bookmarks; 139 already share one batch stamp from a past force-sync. |
| 2 | **Stale full-record `PUT`.** `backend/api/bookmarks.py:92-105` accepts a full `Bookmark` body and forwards all six mutable fields. Because `Bookmark`'s optional fields have **concrete** defaults (`address: str = ""` at `:266`, `category_id: str = "default"` at `:267`, `country_code: str = ""` at `:273` — `backend/models/schemas.py:261-284`), an omitted field arrives as its default, not `None`, so the service's `value is not None` guard (`backend/services/bookmarks.py:409`) cannot tell "omitted" from "set to blank" and **blanks the stored value**. |

Full root-cause report: ``docs/superpowers/specs/2026-08-26-bookmark-revert-root-cause.md``.

---

## 2. Scope

**In scope: E1 and F only.**

- **E1** — three-way merge for the catalog force-sync, driven by a local, non-synced baseline snapshot.
- **F** — partial-update semantics for `PUT /api/bookmarks/{bookmark_id}`, so an omitted field means "leave unchanged".

**Non-goals.**

| Not doing | Why |
|---|---|
| **G — per-field timestamps in the synced store** | **Deferred by Ravi.** It changes `bookmarks.json`'s on-disk shape, so both Macs would need a coordinated migration, and a half-migrated store would be read by a peer that does not understand it. Too much migration risk for a rare failure mode. E1 + F close both *confirmed* triggers without touching the file format; G stays available if the residual exposure in §11 ever bites in practice. |
| **Editing `backend/static/catalog.json` content** | E1 changes how the catalog is *applied*, not what it contains. `_meta.compiled_at` stays `2026-05-23`. |
| **A / B / C / D** | Separate, already in flight as uncommitted working-tree changes by other agents. This plan neither re-plans nor assumes them merged. See §2.1. |
| **Route store (`PUT /api/routes/saved/{route_id}`)** | `replace_route` (`backend/services/route_store.py:289-314`) is a documented **full-replace by design** endpoint ("the backend half of save-and-overwrite"). Same mechanical shape, different product intent. Not a bug; do not "fix" it here. |
| **`import_json` / `POST /import`** | Keeps skip-existing semantics ("restore my backup" intent). Its `_upsert_items` call (`:603`) pre-filters to new ids only (`:598`), so the overwrite branch is structurally unreachable from that path. Explicitly out of scope, and `test_import_json_resurrect.py:98-135` must stay green untouched. |
| **`force_seed`** | `backend/services/bookmarks.py:687-706`. Grep found **zero production callers**. It shares the overwrite branch and would inherit the hazard if ever wired up — flagged as latent risk in §11 (R6), not changed here. |

### 2.1 Relationship to the in-flight changes A/B/C/D

| Change | What it is | Interaction with this plan |
|---|---|---|
| **A** | `BACKUP_RETENTION_HOURS` 72 → 720 in `backend/config.py:111`, kept in lock-step with `scripts/desktop_backup.py`'s own `RETENTION_HOURS = 720` by cross-referencing comments (the script cannot import `config`). **Settled in the working tree.** | Enables the 30-day backup-diff diagnostic in §11. Nothing in this plan touches either constant. |
| **B** | Confirmation dialog before the catalog Refresh button: `frontend/src/components/CatalogRefreshConfirmDialog.tsx` (new), `useCatalog.ts`'s `catalogOverwriteCount`, the `bm.catalog.confirm_*` i18n keys, and `frontend/src/i18n/strings.test.ts` (new — a real-table guard that asserts the five dialog keys exist in both languages and that the 繁中 text carries no Simplified-only characters and no kana). **Settled in the working tree.** | **⚠ E1 invalidates both halves of B's copy — see §4.2 and Task 6.** `catalogOverwriteCount` (`useCatalog.ts:98-115`) compares **six** fields — `name`, `lat`, `lng` (both at `roundCoord` precision), `category_id`, `address`, and `country_code` (case-insensitively) — and `strings.ts:710-711` names five of them: `將覆蓋 {n} 筆既有活動書籤，其名稱、座標、分類、地址與國碼的本地修改將遺失` / "Will overwrite {n} existing event bookmarks — local edits to their name, coordinates, category, address, and country will be lost". Three things are wrong after E1: the *claim of loss* is false for the five merged fields; `country_code` is the one field E1 deliberately does **not** protect, so counting it and naming it overstate what the user keeps; and the count itself cannot carry a durability promise in either direction (§4.2, last bullet — it compares **ours vs theirs**, while E1's rule is **base**-relative). Task 6 fixes the predicate and the copy together, and lands on copy that is true whichever way a given record resolves. |
| **C** | Edit dialog submits LIVE values for untouched fields (per-field dirty tracking in `EditBookmarkDialog.tsx` / `BookmarkList.tsx`). **Settled in the working tree.** | Complementary, not a substitute. C makes the full-record body *fresh*; F lets it be *sparse*. **There are TWO spreads between the dialog and the wire, and Task 9 has to remove both:** `EditBookmarkDialog.tsx:94` builds `const patch: Partial<DialogBookmark> = { ...bookmark }` and overrides only the dirty fields, and `frontend/src/App.tsx:1090` then spreads the whole live `Bookmark` again into its own `patch`. C's dirty flags stay load-bearing — they are what selects the keys — so Task 9 keeps C and drops only the two spreads. |
| **D** | `backend/tests/test_bookmark_revert_hazards.py` (new, untracked) — **three** characterization tests that PIN today's buggy behavior. **Settled in the working tree.** | Each of the three is claimed by a different task. `test_catalog_force_sync_discards_local_rename` → **E1 inverts it** (Task 5). `test_api_put_omitting_address_field_blanks_it_today` (`:298`, the file's only `client.put` against `/api/bookmarks/{id}`, at `:319`) → **F inverts it** (Task 7). `test_stale_whole_record_update_outranks_fresher_remote_copy` is untouched by F's sparse body — its staleness lives in manager A's in-memory record, not in a request body (Task 8 walks the mechanism) — but §6.6's no-op write guard **does** reach it, because A's stale call passes values that all already match A's own record; Task 7 adjusts it per the file's own docstring. Do not delete any of the three — they are the acceptance baseline. |

Layer this plan's diffs **on top of** the working tree as-is. Do not revert C's dirty tracking or B's dialog component; update them where E1/F change what they should say.

---

## 3. API Surface Survey (required by `CLAUDE.md`)

Enumerated with `grep -nE '@router\.(get|post|put|delete|patch)' backend/api/*.py backend/main.py`.

**`backend/api/bookmarks.py` (prefix `/api/bookmarks`):**

| Method | Path | Body | Line |
|---|---|---|---|
| GET | `` | — | :72 |
| POST | `` | `Bookmark` | :80 |
| **PUT** | **`/{bookmark_id}`** | **`Bookmark` (full record)** | **:92** ← F's target |
| DELETE | `/{bookmark_id}` | — | :108 |
| POST | `/move` | `BookmarkMoveRequest` | :115 |
| GET | `/categories` | — | :123 |
| POST | `/categories` | `BookmarkCategory` | :128 |
| PUT | `/categories/{cat_id}` | `BookmarkCategory` (full record) | :139 |
| DELETE | `/categories/{cat_id}` | — | :154 |
| GET | `/export` | — | :183 |
| POST | `/import` | `dict` | :231 |
| GET | `/ui-state` | — | :245 |
| POST | `/ui-state` | `BookmarkUiState` (**all-Optional partial model**) | :250 |
| GET | `/catalog` | — | :260 |
| **POST** | **`/catalog/sync`** | **none** | **:278** ← E1's target |

**`backend/api/route.py`:** `POST /plan` :66 · `GET /saved` :76 · `POST /saved` :81 · `PUT /saved/{route_id}` :91 · `DELETE /saved/{route_id}` :106 · **`PATCH /saved/{route_id}`** :117 (`_RouteRenameRequest{name: str}`) · `POST /saved/move` :128 · `GET /saved/export` :134 · `POST /saved/import` :150 · `GET /categories` :175 · `POST /categories` :180 · `PUT /categories/{cat_id}` :185 · `DELETE /categories/{cat_id}` :193 · `POST /gpx/import` :204 · `GET /gpx/export/{route_id}` :226.

**Git-history check.** `git log --all --oneline -- backend/api/bookmarks.py backend/services/bookmarks.py backend/domain/store_merge.py` surfaced the constraining commits: `c748fef` (force-sync catalog so deleted seeds resurrect), `a41e1d9` (unify import paths via `_upsert_items`), `179c96e` (shared `force_seed_items` primitive), `e48c337` (stamp `updated_at` on `import_json` items), `6434b30` (**drop** the old whole-store three-way merge — see §11 R3), `bd4b1ff` (`POST /import` auto-detect).

**Required conclusions:**

- **E1 — Reusing endpoint `POST /api/bookmarks/catalog/sync`** because the user gesture ("Refresh public events") and its intent are unchanged; only the *resolution rule* inside `import_catalog` changes. The response body gains two additive keys (`kept_local`, `conflicts`); no key is removed or renamed. There is no second catalog endpoint to reuse and no reason to add one.
- **F — Extending endpoint `PUT /api/bookmarks/{bookmark_id}`** with a partial-update request model, because the endpoint, verb and path already mean "update this bookmark" and every caller already treats it that way (`useBookmarks.ts:73-80` types its argument `Partial<Bookmark>` today). Adding a sibling `PATCH` was considered — the repo has that precedent at `route.py:117` — and rejected in §6 because it would leave two endpoints to keep correct for one resource, with no caller left on the old one.

---

## 4. E1 Design — three-way merge for the catalog force-sync

### 4.1 Prior intent this restores

`c748fef` is **"feat(bookmark): force-sync catalog so deleted seeds resurrect"**. Its stated purpose was **resurrection of deleted seeds** plus propagation of genuine catalog corrections — see the endpoint docstring still in `backend/api/bookmarks.py:280-290` and the design doc `docs/plans/2026-05-23-catalog-force-sync-design.md`. Overwriting a *local edit to a still-alive record* was never the goal; it is an unintended side effect of reusing `_upsert_items`, whose update branch copies every field. **E1 restores the original intent and must preserve resurrect-deleted-seeds exactly.**

### 4.2 The merge rule

Per field, compare three values: **base** (the catalog value this machine last applied), **ours** (current local value), **theirs** (new catalog value).

| base vs ours | base vs theirs | Outcome | Rationale |
|---|---|---|---|
| `ours == base` | `theirs == base` | **no-op** (value unchanged) | Nobody touched anything. |
| `ours == base` | `theirs != base` | **take theirs** | Genuine catalog correction, user never touched this field. This is the behavior `c748fef` promised. |
| `ours != base` | `theirs == base` | **keep ours** | User edited it; the catalog has nothing new to say. **This is the revert being fixed.** |
| `ours != base` | `theirs != base`, **and `ours == theirs`** | **no-op, no conflict** | Both sides moved to the *same* value, so there is nothing to arbitrate. See below — this row is not a nicety. |
| `ours != base` | `theirs != base`, **and `ours != theirs`** | **keep ours + report conflict** | Both sides changed, differently. Local intent wins; the count is surfaced so the user knows a catalog correction was passed over. |

**The `ours == theirs` row is load-bearing, not defensive coding.** It is exactly the state of the *second* Mac after the first has applied a genuine catalog correction: Mac 1 takes theirs and writes it into `bookmarks.json`, the store syncs, and Mac 2 now holds the new value locally while its own baseline still records the *old* catalog value it last applied. Without this row Mac 2 would see `ours != base` and `theirs != base` and report a phantom conflict on every record the catalog legitimately corrected — and, because the resolution is "keep ours" and ours already equals theirs, it would be a conflict the user could never act on or clear. With the row, Mac 2's sync is a silent no-op that simply refreshes its baseline. Task 4 Step 1c-ii is the test that fires this row: it needs a catalog that *moves* between rounds, which is why the three-round fixture in Step 1c cannot reach it on its own.

Stated as code, the resolution for one field is: if `ours == theirs`, keep ours and report nothing; else if `ours == base`, take theirs; else if `theirs == base`, keep ours; else keep ours and report a conflict. (`base is None` — the bootstrap case, §4.7 — is handled by substituting `base := theirs` per field before this runs.)

Applies to two record sets:

| Record | Fields under three-way merge | Site today |
|---|---|---|
| Bookmark | `name`, `lat`, `lng`, `address`, `category_id` | `backend/services/bookmarks.py:560-565` |
| Category | `name`, `color`, `sort_order`, `start_date`, `end_date` | `backend/services/bookmarks.py:653-657` |

**Both must be covered.** They are separate loops in the same method and it is easy to fix one and miss the other. `lat`/`lng` are compared **after** `round_coord` so float noise below store precision never reads as a local edit.

Records **absent** from the local store (deleted, or never installed) take the ADD branch and never reach the three-way merge — see §4.5.

**`country_code` is deliberately NOT merged — it is resolver-owned, and the catalog stops writing it entirely.** The update branch does not end at the field copy: two lines later it calls `enrich_bookmark(old, force=enrich_force)` (`backend/services/bookmarks.py:567`), and `import_catalog` passes `enrich_force=True` (`:672-674`). With `force=True`, `enrich_bookmark` (`:51-87`) re-derives `country_code` / `timezone` / `city` / `region` from the coordinates and overwrites them **whenever the offline lookup resolves**. Listing `country_code` as "keep ours" would therefore be a promise the very next statement breaks.

Rather than fight the enrich, E1 accepts it. `country_code` is a *cached derivation of `lat`/`lng`*, not user intent — `update_bookmark`'s own docstring already states the rule: *"The resolver is authoritative on a coord-change re-resolve: an explicit `country_code` passed in the same call is overwritten"* (`:396-399`). Its three siblings `timezone` / `city` / `region` were never candidates for the merge list either; putting `country_code` in it was the inconsistency. The three-way merge therefore arbitrates the **source** (`lat`/`lng`) and lets the derivation follow, which also removes a whole class of states where a bookmark's flag disagrees with its coordinates.

**Leaving `country_code` out of `BOOKMARK_MERGE_FIELDS` is NOT sufficient on its own — the unconditional assignment `old.country_code = bm.country_code` (`:565`) must be DELETED.** "Not merged" and "not written" are different statements, and only the second one is safe. `enrich_bookmark` never writes an empty value ("never overwrite a known value with an empty lookup", `:83-84`), so whenever the offline resolve comes back blank — an ocean point, or a venv missing `numpy` / `timezonefinder`, both documented real failure modes — the enrich is a no-op and whatever the catalog assigned a moment earlier is what stays. The local value is clobbered by the catalog on precisely the path where the resolver was supposed to own the field. It is worse than a plain overwrite: with the resolve empty, `enrich_bookmark` returns `False` and no merged field was taken from theirs, so §4.4's conditional re-stamp leaves `updated_at` alone — the clobber is written locally and then **never propagates to the other Mac**, leaving the two stores permanently disagreeing on that field with no timestamp to reconcile them. So: after E1 the catalog writes `name`/`lat`/`lng`/`address`/`category_id` through the merge and writes nothing else onto an existing bookmark. `enrich_bookmark` is the sole author of `country_code` / `timezone` / `city` / `region`, and when it cannot resolve, the record keeps what it had.

Consequences, stated so nothing is hidden:

- `enrich_bookmark` **stays exactly as it is today** — same call, same `force=True`, same body. E1 makes no change to enrichment, so no existing enrich test can regress and `enrich_force` keeps its documented meaning.
- Because enrich runs *after* the merge, it re-derives from whichever coordinates survived: ours if the user moved the pin, theirs if the catalog corrected it. Either way the geo fields stay consistent with the stored position.
- An enrich-induced change counts as a change for stamping purposes — see §4.4.
- A user who hand-edits `country_code` alone still loses that edit on the next successful resolve. That is the pre-existing, documented rule for a derived field, not a regression E1 introduces — and it is why §4.4's stamp condition includes "enrich reported a change".
- **B's `catalogOverwriteCount` (`frontend/src/hooks/useCatalog.ts:98-115`) does need changing**, in the opposite direction from what its comment claims. It compares six fields, not four: `name`, `lat`, `lng` (both at `roundCoord`, mirroring `COORD_PRECISION = 7`), `category_id`, `address` (both sides defaulted to `""`), and `country_code` (both sides lowercased and defaulted to `""`). Five of those are exactly `BOOKMARK_MERGE_FIELDS`; the sixth, `country_code`, is the one field E1 does not protect, so a `country_code`-only divergence must stop being counted. Task 6 drops that clause and leaves the other five.

**What that count can and cannot mean after E1 — decided here, because the dialog copy depends on it.** The predicate compares **ours vs theirs** (`useCatalog.ts:105-111`: the local bookmark against the bundled catalog entry). E1's rule is **base**-relative, and the baseline lives in `~/.locwarp/catalog_baseline.json`, which no endpoint exposes — the frontend cannot read it and §3 adds no endpoint that would. So the number can only ever mean **"differs from the catalog"**. It deliberately does *not* mean "will be kept", and no change to the predicate can make it mean that:

| The record's state | Counted? | What E1 does | Would "your version is kept" be true? |
|---|---|---|---|
| `ours == base`, `theirs != base` | **yes** (`ours != theirs`) | **takes theirs** — the genuine catalog correction the Refresh button exists to deliver | **no** |
| `ours != base`, `theirs == base` | **yes** (`ours != theirs`) | keeps ours | yes |
| `ours != base`, `theirs != base`, `ours != theirs` | **yes** | keeps ours, reports a conflict | yes |
| `ours == theirs` (any base) | no | no-op | n/a |

The first row is not an edge case — it is the button's whole purpose, and it is indistinguishable from the second row with the information the frontend has. The dialog copy therefore has to be **base-agnostic and true in both branches**: it states that the {n} records differ from the catalog, that locally-edited fields are kept, and that never-edited fields take the catalog value. Task 6 carries the final wording.

### 4.3 Stamping: exactly what stays and what goes

This is the load-bearing distinction. Two things happen today that are easy to conflate:

| Operation | Purpose | E1 verdict |
|---|---|---|
| `force_seed_items(incoming.categories/bookmarks, now)` at `:645-646` — stamps `updated_at = now` on the **incoming** records | Makes an incoming record beat a pre-existing real-timestamp tombstone in `_alive()` (`domain/store_merge.py:86-91`), which is **the entire resurrection mechanism**. Nothing to do with field values. | **STAYS, unchanged.** |
| The unconditional field copy at `:560-565` and `:653-657`, plus `old.updated_at = bm.updated_at` (`:566`) / `old.updated_at = now` (`:658`) | Copies catalog values onto the live record with no awareness of local edits. | **GOES.** Replaced by the three-way decision over `BOOKMARK_MERGE_FIELDS` / `CATEGORY_MERGE_FIELDS`; `old.country_code = bm.country_code` (`:565`) is deleted outright rather than merged (§4.2); the stamp on the *live* record becomes conditional per §4.4. |

Resurrection does not need the field copy. It only needs the stamp, and only for records the merge might otherwise kill.

### 4.4 When the live record gets re-stamped

After the three-way decision, the existing record's `updated_at` is set to the sync's `now` **only if** at least one of:

1. at least one field was taken from theirs (the record genuinely changed), **or**
2. `enrich_bookmark` reported a change (it returns `True` when it rewrote a geo field — see §4.2), **or**
3. the id appears in the **tombstone id set** defined below (resurrection intent — the record must out-vote that tombstone).

Otherwise `updated_at` is **left untouched**.

**Why this matters:** an unconditional re-stamp would make a force-sync on Mac 1 bump 140 records to `now`, which then beats a genuinely newer edit made on Mac 2 that has not synced yet — i.e. clicking Refresh would *itself* become a revert trigger. Leaving no-op records unstamped makes a force-sync a true no-op for them, so it cannot revert the other Mac.

**The tombstone id set must include the on-disk tombstones, not just the in-memory ones.** This is the one place where making the stamp conditional can *lose* a record, and it has to be got right. `_save()` merges against the on-disk copy (`services/bookmarks.py:146-154`), so a tombstone written by the *other* Mac and not yet reconciled into `self.store.tombstones` is invisible to an in-memory-only check. An otherwise-unchanged record would then be left unstamped and killed by `_alive()` (`domain/store_merge.py:86-91`) inside that same `_save()` — where today's unconditional `old.updated_at = bm.updated_at` (`services/bookmarks.py:566`) would have resurrected it.

`import_catalog` therefore computes the tombstone id set **once, at the top of the method**, as the union of the in-memory tombstones and the on-disk ones:

```python
tomb_ids = {t.id for t in self.store.tombstones}
tomb_ids |= {t.id for t in self._repo.load_or_empty().tombstones}
```

`load_or_empty()` is already part of the `BookmarkRepository` port (`domain/ports/bookmark_repository.py`) and is the same parse-only read `_save` / `_watcher_tick` / `_reconcile_from_disk` use, so this adds no new port method, no new ring edge, and no new failure mode (a missing or empty file yields an empty store). The same set also feeds the `resurrected` count, which today is computed from `self.store.tombstones` alone (`:643`) and is under-counted by exactly the same window — folding both onto one set fixes the count as a side effect.

### 4.5 Resurrection is the ADD branch — unchanged

`delete_bookmark` removes the record and writes a tombstone, so on the next sync the id is **absent** from `self.store.bookmarks`. `_upsert_items` takes the `old is None` ADD branch, the record is appended already stamped by `force_seed_items`, and `_alive()` lets it out-vote the tombstone. **The three-way merge is never consulted for a resurrected record.** `backend/tests/test_bookmark_catalog_sync.py:74-90` (`test_resync_after_delete_resurrects`) must stay green with no edit beyond the response-shape key.

### 4.6 The baseline snapshot file

| Property | Value |
|---|---|
| Path | `~/.locwarp/catalog_baseline.json` (`config.CATALOG_BASELINE_FILE`) |
| Scope | **Local to one machine. Never in `sync_folder`.** |
| Written | After each successful `import_catalog`, recording **theirs** (the catalog just applied) |
| Read | Once per `import_catalog`, to supply **base** |

Format:

```json
{
  "_meta": { "format_version": 1, "compiled_at": "2026-05-23", "applied_at": "2026-08-26T09:00:00+00:00" },
  "categories": { "seed-sapporo-tour": { "name": "...", "color": "#3b82f6", "sort_order": 1, "start_date": "", "end_date": "" } },
  "bookmarks":  { "seed-sapporo-a":    { "name": "...", "lat": 43.068027, "lng": 141.350895, "address": "", "category_id": "seed-sapporo-tour" } }
}
```

Only the merged fields are stored — not `created_at` / `last_used_at` / geo fields, which the catalog does not own. `compiled_at` is recorded for diagnostics (which catalog version seeded this baseline); it is **not** used as a change-detection key, because a same-day catalog edit would not bump it and the three-way merge is correct regardless.

**Why NOT in the synced folder:** the two Macs must be able to bootstrap independently and in any order. A synced baseline would itself need merge semantics and would make the upgrade order matter.

**Why NOT a field in `bookmarks.json`:** that is the decisive reason this design was chosen over G. Adding baseline values to the store record would change the on-disk format that both Macs read, creating exactly the cross-machine migration risk the constraint forbids. Keeping the base in a separate local file means **zero** format change and zero migration.

### 4.7 Bootstrap on first run

When `catalog_baseline.json` is absent (every machine's first post-upgrade sync), **base := theirs** for every id.

Consequence, stated plainly for Ravi's live data: every already-diverged record is `ours != base, theirs == base` → **keep ours, zero conflicts**. The root-cause report measured 23 seed bookmarks whose `category_id` has diverged and 1 name divergence; all of them are silently preserved on the first sync after upgrade, and none is reported as a conflict. Field values are untouched on the first sync — it is effectively a no-op that writes the baseline. This is the intended transition behavior.

**The trade this makes, on the record.** `base := theirs` cannot distinguish *"the user edited this"* from *"the catalog changed between the last pre-E1 sync and now, and this machine never re-synced"*. Both present as `ours != base, theirs == base`. Divergence of the second kind is therefore classified as a local edit and **pinned out permanently** — every later sync also sees `ours != base` and `theirs == base`, so the genuine catalog correction never lands, and it is never reported as a conflict either. Some of the 23 measured `category_id` divergences are plausibly of exactly this kind (a seed moved between event categories in a later `catalog.json`).

This is accepted deliberately. The alternative — bootstrapping `base` from the catalog *as shipped at the time of the last sync* — would need a version history this machine does not have, and the failure it would avoid (a stale seed value) is cosmetic, while the failure it would introduce (silently overwriting a real edit on first run) is the exact bug this plan exists to fix. The escape hatch is manual and adequate: deleting the affected seed bookmark and clicking Refresh re-installs it from the catalog verbatim through the ADD branch (§4.5), which never consults the baseline. (Deleting `catalog_baseline.json` does **not** help — re-bootstrapping just sets `base := theirs` again.)

### 4.8 Conflict report shape and its consumers

`import_catalog` returns two **additive** keys. Nothing is renamed or removed.

```python
{"added": N, "updated": N, "resurrected": N, "kept_local": N, "conflicts": N}
```

- `kept_local` — records where at least one field was kept because the user had edited it (both the "catalog unchanged" and the "conflict" cases). Concretely: records whose `Resolution.kept` tuple is non-empty (§5). **This is the figure `Resolution` must be able to express, and `values`/`conflicts`/`changed` cannot** — the `ours != base, theirs == base` row (keep ours) and the `ours == base, theirs == base` row (nobody touched anything) both produce `values == ours`, `conflicts == ()` and `changed == False`, so they are indistinguishable without a fourth member. Hence `kept`.
- `conflicts` — the subset where **both** sides changed the same field. `conflicts <= kept_local` holds by construction, because `Resolution.conflicts` is a subset of `Resolution.kept` (§5).
- The invalid-JSON early return (`bookmarks.py:639`) returns all five keys as `0`.
- `updated` keeps today's meaning: an id collision, whether or not any field actually changed. Not redefined, to avoid churn in the existing assertions.

Every consumer that must learn the new keys:

| Consumer | File:line | Change |
|---|---|---|
| Success return | `backend/services/bookmarks.py:681-685` | add both keys |
| Invalid-JSON return | `backend/services/bookmarks.py:639` | add both keys as `0` |
| HTTP endpoint | `backend/api/bookmarks.py:278-298` | add a `CatalogSyncResult(BaseModel)` with all five `int` fields and set `response_model=` on the route (Q3); update the docstring |
| TS interface | `frontend/src/services/api.ts:457-461` | add `kept_local: number; conflicts: number` |
| Hook | `frontend/src/hooks/useCatalog.ts:123-132` (`refresh`) | pure passthrough — it returns `api.syncCatalog()`'s result verbatim, so no change |
| Hook test mock | `frontend/src/hooks/useCatalog.test.ts:13,66` | the mocked `syncCatalog` result and its `toEqual` both carry the 3-key shape — add the two keys so `tsc` stays clean |
| Toast handler | `frontend/src/App.tsx:876-892` | pass the new fields |
| i18n | `frontend/src/i18n/strings.ts:702-703` | extend `bm.catalog.synced`; add a conflicts line |
| **B's confirm dialog copy** | `frontend/src/i18n/strings.ts:710-712` | **rewrite both keys — the current text is now false**, and rename them `bm.catalog.confirm_diverged` / `bm.catalog.confirm_no_diverged` (§4.2, Task 6) |
| **B's divergence predicate** | `frontend/src/hooks/useCatalog.ts:14-20, 34-42, 79-115, 139` | **drop `country_code` from the comparison, the interface and both comments, and relabel** (§4.2, Task 6) |

---

## 5. E1 Ring Placement

Modelled directly on the rotating-backup feature, which is the repo's cleanest five-file example of this shape.

| Ring | Backup precedent | E1 file | Contents |
|---|---|---|---|
| `domain/` | `domain/backup.py` | **`backend/domain/catalog_merge.py`** (new) | Pure three-way resolution. stdlib + pydantic only, no clock, no I/O. `BOOKMARK_MERGE_FIELDS` / `CATEGORY_MERGE_FIELDS` tuples; `resolve_record(base: dict \| None, ours: dict, theirs: dict, fields: tuple[str, ...]) -> Resolution` where `Resolution` is a `NamedTuple(values: dict, kept: tuple[str, ...], conflicts: tuple[str, ...], changed: bool)`. Deterministic and unit-testable in isolation. |
| `domain/ports/` | `domain/ports/backup_repository.py` | **`backend/domain/ports/catalog_baseline_repository.py`** (new) | `class CatalogBaselineRepository(Protocol)` with `read() -> dict \| None` and `write(payload: dict) -> None`. |
| `infra/persistence/` | `infra/persistence/backup_store.py` | **`backend/infra/persistence/catalog_baseline_store.py`** (new) | `FileCatalogBaselineStore(path_provider: Callable[[], Path])`. Path resolved **lazily** at each call (`self._path_provider()`), never captured at construction and never `from config import …` — this is what makes the conftest monkeypatch effective. Reuses `services.json_safe.safe_load_json / safe_write_json` for the same atomic temp+replace guarantee (the `infra → services.json_safe` edge already exists in `json_store.py`). Missing/corrupt file → `read()` returns `None`. |
| `services/` | `services/backup_service.py` | **`backend/services/bookmarks.py`** (modified — no new service class) | Unlike `BackupService`, the merge needs direct read/write access to `self.store.bookmarks` / `.categories`, which a read-only snapshot service cannot give. So the logic lives in `BookmarkManager`. What *is* copied from the precedent is the **injection shape**: `BookmarkManager.__init__` gains a second injected port, `catalog_baseline: CatalogBaselineRepository \| None = None`. The `None` default is what keeps the port optional — not a compatibility shim: `grep -rn "BookmarkManager(" backend/` finds one construction site in the whole repo (`bootstrap/factories.py:17`) and none in tests. When it is `None`, `import_catalog` behaves as if no baseline exists (permanent bootstrap path) and logs a warning — see R4. |
| `bootstrap/` | `factories.make_backup_service:25-36` | **`backend/bootstrap/factories.py`** (modified) | Signature becomes `make_bookmark_manager(path_provider=None, baseline_path_provider=None)` (`:15-17` today); it builds `FileCatalogBaselineStore(baseline_path_provider or (lambda: config.CATALOG_BASELINE_FILE))` and passes it as `catalog_baseline=`. Mirrors `make_backup_service`'s `dir_provider or (lambda: config.BACKUP_DIR)` lazy pattern exactly, and mirrors the `path_provider` seam this same function already has. |
| `config.py` | `BACKUP_DIR:103` | **`backend/config.py`** (modified) | `CATALOG_BASELINE_FILE = DATA_DIR / "catalog_baseline.json"` near `STICKY_DENIED_FILE:94`, with a comment stating it is local-only, never in `sync_folder`, and must be referenced lazily. |

**The four members, and why `kept` is one of them.** Three are the obvious ones: `values` is the resolved record, `conflicts` names the fields where both sides moved apart, and `changed` is `any(values[f] != ours[f])` — i.e. "at least one field was taken from theirs", which is condition 1 of §4.4's stamp rule. `kept` is the fourth, and without it §4.8's `kept_local` is not computable: the `ours != base, theirs == base` row (the revert this plan exists to fix) and the `ours == base, theirs == base` row (nobody touched anything) both yield `values == ours`, `conflicts == ()`, `changed == False`, byte-identical. Defined per field:

| Member | Rule, per field `f` |
|---|---|
| `kept` | `ours[f] != theirs[f]` **and** `ours[f] != base[f]` — the user's value was preserved over a *differing* catalog value |
| `conflicts` | `ours[f] != theirs[f]` **and** `ours[f] != base[f]` **and** `theirs[f] != base[f]` — both sides moved, differently |
| `changed` | `values[f] != ours[f]` for some `f` — equivalently `ours[f] == base[f]` and `theirs[f] != ours[f]` |

`conflicts ⊆ kept` falls out of the definitions, which is what makes §4.8's `conflicts <= kept_local` an invariant rather than a hope. The `ours == theirs` row of §4.2 is correctly *excluded* from `kept` (nothing was passed over — the catalog agrees), so the second Mac's silent no-op reports neither a conflict nor a `kept_local`.

**Why `baseline_path_provider` is not optional polish.** The baseline is **per machine**, and the repo's only idiom for modelling two machines is two `BookmarkManager`s over one shared store file (`test_bookmark_revert_hazards.py:134,137`, inside `test_stale_whole_record_update_outranks_fresher_remote_copy`). Without a per-manager seam, `config.CATALOG_BASELINE_FILE` is one process-wide path, so both "Macs" in any such test would read and write **one** baseline — which is not the topology, and would make a two-machine test silently prove the wrong thing (Mac 2 would inherit Mac 1's base instead of bootstrapping its own). `path_provider` exists on this factory for exactly the same reason; `baseline_path_provider` is its counterpart, and §9's cross-machine convergence test depends on it.

**Import-linter: no new contract needed.** Every edge E1 adds already exists in shape and direction: `bootstrap → infra` , `bootstrap → services`, `services → domain`, `infra → domain`, `infra → services.json_safe`. `domain/catalog_merge.py` imports stdlib only, so `no-domain-imports-outer` is satisfied. The suite stays at **7 kept, 0 broken**.

---

## 6. F Design — partial-update semantics for `PUT /api/bookmarks/{bookmark_id}`

### 6.1 Today's per-field behavior vs after F

Client sends a body **omitting** the field. `Bookmark`'s defaults are concrete, not `None`, so pydantic fills the default and `value is not None` (`services/bookmarks.py:409`) can never see an omission.

| Field | Schema (`models/schemas.py`) | Today, if omitted | After F |
|---|---|---|---|
| `name` | `str` (required) | 422 — cannot be omitted | left unchanged |
| `lat` | `float` (required) | 422 — cannot be omitted | left unchanged |
| `lng` | `float` (required) | 422 — cannot be omitted | left unchanged |
| `address` | `str = ""` | **blanked to `""`** | left unchanged |
| `category_id` | `str = "default"` | **reset to `"default"`** | left unchanged |
| `country_code` | `str = ""` | **blanked to `""`** (flag lost) | left unchanged |
| `last_used_at` | `str = ""` | untouched — the API layer never forwards it | untouched (unchanged) |

### 6.2 Does any caller rely on today's blanking?

**No.** Verified across `frontend/src` and `backend/tests`:

- `frontend/src/App.tsx:1088-1099` (`onBookmarkEdit`) spreads the **full live record** into `patch` (`:1090`), then overlays only the touched fields. It never omits a field, so it never blanks one.
- `frontend/src/components/EditBookmarkDialog.tsx:94` (`handleSubmit`) spreads the live record a first time, before App spreads it a second time. Same conclusion: it never omits, so it never blanks.
- `frontend/src/components/BookmarkList.tsx:992` (`onMoveToCategory`) routes through the same handler with a genuinely sparse `{ category }`, which App then widens back into a full record.
- `api.updateBookmark` (`frontend/src/services/api.ts:367`) and `useBookmarks.updateBookmark` (`useBookmarks.ts:73-80`, already typed `Partial<Bookmark>`) are pass-throughs; grep found no third caller.
- Backend tests call the **service** directly with genuinely partial kwargs (`test_bookmark_enrich.py:117`, `test_bookmark_coord_rounding.py:50,58`, `test_bookmark_tombstones.py:29`) and already rely on omitted-means-unchanged.

There is **no caller that clears a field by omitting it**, so F breaks nothing. A caller that wants to clear `address` sends `"address": ""` explicitly, which still works.

### 6.3 Options surveyed

**Recommended — (b) a dedicated `BookmarkUpdate` request model, keeping the `PUT` verb and path.** All fields `Optional[T] = None`; the route forwards only non-`None` values into the unchanged service call. This copies the repo's own house pattern for a partial-update request body, `BookmarkUiState` (`backend/api/bookmarks.py:62-67`), whose comment already states the intent: *"a POST updates only the fields it carries, so the frontend can persist expand and hide independently without one request clobbering the other."* The partial-update *mechanism* needs **zero service change** — `update_bookmark`'s `value is not None` guard (`:407-412`) already does exactly the right thing once the API stops fabricating defaults. OpenAPI then states explicitly which fields are optional. One small service change does ride along, for a different reason: the no-op write guard in §6.6.

Rejected:

- **(a) Reuse `Bookmark` and read `model_fields_set`.** Structurally blocked for `name`/`lat`/`lng`, which are required and so cannot be omitted at all. Worse, it is inert for the caller that matters: `App.tsx:1090` spreads the full record, so `model_fields_set` would report every field as set regardless of what the user touched.
- **(c) Add a sibling `PATCH /{bookmark_id}` next to the existing `PUT`.** Has real precedent (`PATCH /saved/{route_id}`, `route.py:117`) and is the most conservative for API-freeze culture, but leaves two endpoints for one resource that must both stay correct and tested — while the single real caller migrates to the new one, leaving `PUT` with **no** caller and no reason to keep its old semantics. The route precedent is also much narrower (one field, `name`) than bookmarks' five mutable fields.

### 6.4 F is inert without a frontend change — stated plainly

The frontend sends a **full** record today, and change C does not alter that (C makes the values *fresh*, not the body *sparse*). It does so twice over: `EditBookmarkDialog.tsx:94` spreads the live record into its patch and overrides only the dirty fields, and `App.tsx:1090` then spreads the live record again into its own patch. So the backend half of F is future-proofing until Task 9 removes **both** spreads and lets the dirty flags alone decide which keys ship. **Both halves must ship for F to close trigger #2.**

This also shapes the tests. F is proven by two HTTP tests with different jobs, and neither can be the service-level characterization: `test_bookmark_revert_hazards.py::test_api_put_omitting_address_field_blanks_it_today` already drives the route with a body that omits `address` and asserts today's blanking, so **Task 7 inverts it in place** — that is the direct, minimal proof that an omitted key is now left alone. Task 8 then adds the two-manager case, which proves the property that actually matters across Macs: a sparse write no longer clobbers a field a *peer* changed.

### 6.5 Scope recommendation: categories and routes

| Surface | Same defect? | Recommendation |
|---|---|---|
| `PUT /api/bookmarks/categories/{cat_id}` (`api/bookmarks.py:139-151`) | **Yes, identical.** `BookmarkCategory`'s `color = "#6c8cff"`, `start_date = ""`, `end_date = ""` blank the same way; `update_category` (`services/bookmarks.py:273-299`) already has the correct `is not None` guard. And the category edit dialog is **still frozen-snapshot** — verified `BookmarkList.tsx:186-193` seeds local state once at open and `App.tsx:1121-1131` submits all four fields from it. Change C fixed only the bookmark dialog. | **RECOMMEND INCLUDING** as Task 10 ("F2"). Structurally identical to Task 7, plus one thing bookmarks do not have: `_validate_date_range` (`api/bookmarks.py:21-40`) is called at `:141` and would receive `None` from an all-Optional model, hitting `_ISO_DATE_RE.match(None)` → 500. That is a handful of extra lines, not a new design. Leaving Task 10 out means renaming a category stays unsafe while renaming a bookmark became safe, which will read as a bug. Ravi's call — Task 10 is separable and can be dropped without affecting Tasks 1-9. |
| `PUT /api/routes/saved/{route_id}` (`api/route.py:91-102`) | Mechanically similar but `replace_route` is **full-replace by intent**. | **DEFER.** Different design, not the same bug. |
| `PUT /api/routes/categories/{cat_id}` (`api/route.py:185-190`) | Yes, same blank-via-default shape. | **DEFER** — no reported symptom, keeps this plan's blast radius honest. |

### 6.6 The no-op write guard — closing the second half of the root cause

§1 names two root causes. A sparse body shrinks the *field copy*; on its own it leaves the **unconditional re-stamp** (`services/bookmarks.py:419`) untouched, and that half is independently sufficient to cause a revert. A `PUT` carrying **no** effective change — `{}`, or a body whose every value already equals the stored one — still bumps `updated_at`, and whole-record LWW then replaces the other Mac's un-synced copy with this Mac's. Task 9 makes this *more* reachable, not less: once the frontend sends only dirty fields, "open the Edit dialog and press Save without changing anything" becomes a literal `{}` request.

**Decision: fix it, in Task 7.** `update_bookmark` computes the effective diff over its `allowed` set *before* mutating (after `round_coord`, so coordinate noise is not a change); if no value differs, it returns the record **without** setting `updated_at` and **without** calling `_save()`.

Reasoning, and the case against:

- **Consistency.** This is the exact analogue of §4.4, which the plan already argues is load-bearing on the catalog path. A no-op write that cannot revert the other Mac is the same property, applied to the other trigger. Fixing one and not the other would be arbitrary.
- **Blast radius is small, measured, and has exactly one casualty.** `update_bookmark` has **one** production caller — `api/bookmarks.py:94` — and nine test call sites. Six of them change at least one value and are not at risk: `test_bookmark_enrich.py:109,117,135`, `test_bookmark_coord_rounding.py:50,58`, `test_bookmark_tombstones.py:29`. Two more are inside `test_bookmark_revert_hazards.py` and also change a value (`:140` renames, `:213` renames and moves). **The ninth, `test_bookmark_revert_hazards.py:154`, is a deliberate no-op, and left as written the guard would invert its outcome** — see below.
- **Left alone, the guard would invert `test_stale_whole_record_update_outranks_fresher_remote_copy` — and change D anticipated exactly this.** At `:154` manager A re-sends `name=bm.name, lat=bm.lat, lng=bm.lng, address=bm.address, category_id=bm.category_id, country_code=bm.country_code` from the snapshot `create_bookmark` returned — every one of which still equals what A's own in-memory record holds, because A never reconciled B's rename. Under the guard that call writes nothing at all, so A never saves, and the on-disk name stays `"new"` — the exact opposite of the test's `assert on_disk_bm["name"] == "old"`. The test file's own docstring calls this out in advance: it says the two assertions "only flip if a future change makes that re-stamp conditional on an actual field diff", and offers option (a), *"If the service-level re-stamp is ever made conditional, update THIS test's two assertions to match the new (fixed) outcome."* §6.6 is precisely that change. **Task 7 must handle it in the same commit or the suite goes red.** How, and the alternative considered, are in Task 7 Step 1b.
- **The honest cost.** `PUT` stops being a reliable "touch this record" primitive: a caller that wanted to force a re-stamp without changing a value no longer can. No such caller exists today, and the same effect is available by sending a real value. `enrich_bookmark` is unaffected — it runs on a coord change, which is by definition not a no-op.
- ~~**Not extended to `update_category`.**~~ Same hazard in principle, but no measured symptom at plan time and the category path was already fenced as separable (Task 10), so it was recorded in §11 rather than fixed. **Superseded after the plan shipped** — Task 10's dirty tracking made the empty category patch a live revert vector, and `update_category` now carries the identical diff guard. See §11 item 4.

Consequence for Task 7's acceptance: `PUT` with `{}` returns **200 with the record byte-identical, `updated_at` included** — not "unchanged apart from `updated_at`".

---

## 7. File Structure

| File | Change |
|---|---|
| `backend/config.py` | Modify — add `CATALOG_BASELINE_FILE` near `:94` |
| `backend/tests/conftest.py` | Modify — add `CATALOG_BASELINE_FILE` to `_isolate_real_data_paths` (`:68` area) |
| `backend/domain/catalog_merge.py` | **Create** — pure three-way resolution |
| `backend/domain/ports/catalog_baseline_repository.py` | **Create** — `CatalogBaselineRepository` Protocol |
| `backend/infra/persistence/catalog_baseline_store.py` | **Create** — `FileCatalogBaselineStore` |
| `backend/bootstrap/factories.py` | Modify `make_bookmark_manager` (`:15-17`) — add `baseline_path_provider=None` |
| `backend/services/bookmarks.py` | Modify `__init__` (`:99`), `update_bookmark` (`:407-421`, no-op guard §6.6), `_upsert_items` (`:534-574`), `import_catalog` (`:610-685`) |
| `backend/api/bookmarks.py` | Modify — `BookmarkUpdate` model + `update_bookmark` route (`:92-105`); `CatalogSyncResult` `response_model` on `:278`; docstrings |
| `backend/tests/test_catalog_merge_domain.py` | **Create** — pure-function unit tests |
| `backend/tests/test_catalog_baseline_store.py` | **Create** — infra round-trip / missing / corrupt |
| `backend/tests/test_catalog_sync_three_way.py` | **Create** — service-level matrix |
| `backend/tests/test_bookmark_update_partial_api.py` | **Create** — HTTP-level partial-update tests |
| `backend/tests/test_bookmark_revert_hazards.py` | Modify — all three tests plus the module docstring: invert `test_catalog_force_sync_discards_local_rename` (Task 5), invert `test_api_put_omitting_address_field_blanks_it_today` and re-point `test_stale_whole_record_update_outranks_fresher_remote_copy` (Task 7), add `test_sparse_put_does_not_clobber_fresher_remote_field` (Task 8) |
| `backend/tests/test_bookmark_catalog_sync.py` | Modify — response-shape keys (`:61`, `:70`, `:117`) |
| `backend/tests/test_bookmark_catalog.py` | Modify — response-shape key (`:97`) |
| `backend/tests/test_upsert_items_unify.py` | Modify — response-shape keys (`:50`, `:60`) |
| `backend/tests/test_bookmark_event_dates.py` | Modify **only if Task 10 ships** — the two HTTP category `PUT` tests, `test_put_category_updates_dates` (`:196`, request at `:203`) and `test_put_category_rejects_bad_format` (`:214`, request at `:217`), are the existing coverage of the route Task 10 changes |
| `frontend/src/services/api.ts` | Modify — `CatalogSyncResult` (`:457-461`), `updateBookmark` typing (`:367`) |
| `frontend/src/App.tsx` | Modify — `handleCatalogRefresh` (`:876-892`), `onBookmarkEdit` (`:1088-1099`), the `catalogOverwriteCount` relay (`:873`, `:1305`) |
| `frontend/src/i18n/strings.ts` | Modify — `bm.catalog.synced` (`:702-703`); rewrite + rename `bm.catalog.confirm_overwrite` (`:710-711`) → `confirm_diverged` and `bm.catalog.confirm_no_overwrite` (`:712`) → `confirm_no_diverged`, both texts fixed verbatim in Task 6; add `bm.catalog.synced_conflicts` |
| `frontend/src/i18n/strings.test.ts` | Modify — the `DIALOG_KEYS` list (`:12-18`): both confirm keys are renamed, so `:15` and `:16` change; the list stays five keys long; **change B's file, coordinate** |
| `frontend/src/hooks/useCatalog.ts` | Modify — relabel `catalogOverwriteCount` and remove `country_code` from all four places it appears: the header comment (`:14-20`), the `CatalogDiffBookmark` interface (`:34-42`), the predicate comment + `useMemo` (`:79-115`), and the returned key (`:139`); **change B's file, coordinate** |
| `frontend/src/hooks/useCatalog.test.ts` | Modify — the relabel, the two `country_code` cases (`:129-139`, `:155-165`), and the 3-key `syncCatalog` mock (`:13`, `:66`); **change B's file, coordinate** |
| `frontend/src/components/CatalogRefreshConfirmDialog.tsx` | Modify — prop comment (`:9-10`) and the prop itself at all four sites (`:11` declaration, `:28` destructuring, `:54` branch test, `:62` interpolation), component JSDoc (`:16-24`), and **both** renamed i18n keys (`:62`, `:66`); **change B's file, coordinate** |
| `frontend/src/components/BookmarkList.tsx` | Modify — the `catalogOverwriteCount` prop + its comment (`:91-94`, `:135`, `:1042`) for the relabel; `onMoveToCategory` (`:992`) is unchanged; **change B/C's file, coordinate** |
| `frontend/src/components/ControlPanel.tsx` | Modify — the `catalogOverwriteCount` relay for the relabel: prop declaration (`:120`), destructuring (`:327`), forward to `BookmarkList` (`:1019`). This is the link between `App.tsx:1305` and `BookmarkList.tsx:135` — the prop does not go directly. **change B's file, coordinate** |
| `frontend/src/components/BookmarkList.test.tsx` | Modify — the confirm-dialog key assertions (`:896-897`, `:906-907`) and the `catalogOverwriteCount` props (`:116`, `:872`, `:901`); **change B's file, coordinate** |
| `frontend/src/components/EditBookmarkDialog.tsx` | Modify — `handleSubmit` (`:81-100`) builds a sparse patch from the dirty flags instead of spreading the live record (Task 9); **change C's file, coordinate — keep the dirty flags** |
| `frontend/src/components/EditBookmarkDialog.test.tsx` | Modify — the **four** `onSubmit` shape assertions (`:79`, `:168`, `:201`, `:226`) now expect sparse patches (Task 9); the three `not.toHaveBeenCalled()` cases are untouched; **change C's file, coordinate** |

Unchanged on purpose: `backend/domain/store_merge.py`, `import_json`, `force_seed`, all route files, `backend/config.py`'s `BACKUP_RETENTION_HOURS` and `scripts/desktop_backup.py` (change A, already settled).

---

## 8. Tasks

### Task 1 — Baseline path constant + test isolation guard

**Files:** modify `backend/config.py`, `backend/tests/conftest.py`
**Acceptance:** `config.CATALOG_BASELINE_FILE == DATA_DIR / "catalog_baseline.json"`; the autouse guard redirects it to `tmp_path`. No behavior change anywhere else.

- [ ] Add the constant next to `STICKY_DENIED_FILE` (`config.py:94`) with a comment: local-only, never in `sync_folder`, reference lazily as `config.CATALOG_BASELINE_FILE`.
- [ ] Add `monkeypatch.setattr(config, "CATALOG_BASELINE_FILE", tmp_path / "catalog_baseline.json", raising=False)` beside the `BACKUP_DIR` line (`conftest.py:68`), with the same rationale comment.
- [ ] **Test that must fail before / pass after:** add `backend/tests/test_catalog_baseline_store.py::test_baseline_path_is_isolated_by_conftest`, asserting `config.CATALOG_BASELINE_FILE` is **not** under `Path.home() / ".locwarp"`. Fails before (attribute does not exist) — passes after.

### Task 2 — Pure three-way merge in `domain/`

**Files:** create `backend/domain/catalog_merge.py`, `backend/tests/test_catalog_merge_domain.py`
**Interfaces:** `BOOKMARK_MERGE_FIELDS`, `CATEGORY_MERGE_FIELDS`, `Resolution = NamedTuple(values: dict, kept: tuple[str, ...], conflicts: tuple[str, ...], changed: bool)`, `resolve_record(base, ours, theirs, fields) -> Resolution`.
**Acceptance:** stdlib-only; `base=None` ⇒ `base := theirs` per field (bootstrap); implements §4.2 exactly; all four members follow §5's per-field table; `changed` is true iff some returned value differs from `ours`; `set(conflicts) <= set(kept)` for every input.

- [ ] **Step 1 — failing tests.** One test per row of the §4.2 table, each asserting **all four** members of `Resolution`, not just `values`:
  - `ours == base, theirs == base` → `values == ours`, `kept == ()`, `conflicts == ()`, `changed is False`.
  - `ours == base, theirs != base` → `values == theirs`, `kept == ()`, `conflicts == ()`, `changed is True`.
  - `ours != base, theirs == base` → `values == ours`, **`kept == (field,)`**, `conflicts == ()`, `changed is False`. **Paired with the first row, this is the test that pins why `kept` exists** (§4.8): the two rows are byte-identical on `values` / `conflicts` / `changed` and differ only in `kept`, so a three-member `Resolution` cannot tell them apart and `kept_local` becomes uncomputable. Assert the two side by side in one test so the discrimination is visible.
  - `ours != base, theirs != base, ours == theirs` → `values == ours`, `kept == ()` (nothing was passed over — the catalog agrees), `conflicts == ()`, `changed is False`.
  - `ours != base, theirs != base, ours != theirs` → `values == ours`, `kept == (field,)`, `conflicts == (field,)`, `changed is False`.
  - Plus: `base=None` bootstrap keeps a diverged local value, reports zero conflicts and `kept == (field,)`; a field missing from `base` is treated as bootstrap for that field alone; `kept` and `conflicts` are reported per field name on a multi-field record where different rows fire on different fields; and a property-style assertion that `set(conflicts) <= set(kept)` across the whole matrix.
- [ ] **Step 2 — run, verify they fail** (module does not exist).
- [ ] **Step 3 — implement.** No clock, no I/O, no imports outside stdlib/typing.
- [ ] **Step 4 — `lint-imports` still 7 kept, 0 broken.**

### Task 3 — Baseline port + infra store + composition-root wiring

**Files:** create `backend/domain/ports/catalog_baseline_repository.py`, `backend/infra/persistence/catalog_baseline_store.py`; modify `backend/bootstrap/factories.py`, `backend/services/bookmarks.py` (`__init__` only); extend `backend/tests/test_catalog_baseline_store.py`
**Interfaces:** `make_bookmark_manager(path_provider=None, baseline_path_provider=None) -> BookmarkManager`. Both providers stay positional-or-keyword and both default to the lazy `config` lookup, so every existing `make_bookmark_manager()` call site is untouched.
**Acceptance:** `FileCatalogBaselineStore` round-trips a §4.6 payload **key-for-key** (`read() == payload`, `_meta` included); `read()` returns `None` for missing **and** corrupt files; the path is resolved lazily per call; `BookmarkManager(repo=…)` with no `catalog_baseline` still constructs (default `None`); **two managers built with two different `baseline_path_provider`s keep two independent baselines** (§5, the per-machine seam).

- [ ] **Step 1 — failing tests:** `test_baseline_round_trips_format_version_1_payload` — write §4.6's example payload verbatim and assert `read()` returns it with `==`, so a store that silently drops `_meta` or coerces a nested dict fails here rather than at sync time; missing → `None`; corrupt JSON → `None`; changing `config.CATALOG_BASELINE_FILE` **after** construction changes where the store writes (proves laziness); `make_bookmark_manager()` yields a manager with a non-`None` `catalog_baseline`; `make_bookmark_manager(baseline_path_provider=lambda: p1)` and `…(baseline_path_provider=lambda: p2)` write to `p1` and `p2` respectively and neither reads the other's file.
  - The store is deliberately **shape-agnostic** — it persists whatever dict it is handed — so the round-trip test above is the only shape assertion that belongs here. That the payload `import_catalog` *builds* actually has §4.6's field set is asserted in Task 4 Step 1d, where the payload is constructed.
- [ ] **Step 2 — run, verify they fail.**
- [ ] **Step 3 — implement.** Port = Protocol only. Store uses `safe_load_json` / `safe_write_json`. `make_bookmark_manager` mirrors `make_backup_service:25-36` for the baseline provider and its own existing `path_provider` idiom for the shape.
- [ ] **Step 4 — assert the factory wires the port** rather than grepping for constructor arity: the measured fact is that `BookmarkManager(` appears **once** in the repo (`bootstrap/factories.py:17`) and never in tests, so the real regression to guard is `factories.py` dropping the argument. Add `logger.warning` on the `catalog_baseline is None` path in `import_catalog` (R4).
- [ ] **Step 5 — full suite green (1200 + the new baseline-store tests), `lint-imports` 7 kept 0 broken.** No behavior change yet: nothing reads the baseline.

### Task 4 — Wire the three-way merge into `import_catalog` (E1's behavior change)

**⚠ Tasks 4, 5 and 6 are one commit.** Every other task in this plan is self-contained, but E1's behavior change moves assertions in files three tasks own: Task 4 flips what `import_catalog` does, which immediately reddens `test_bookmark_revert_hazards.py::test_catalog_force_sync_discards_local_rename` (Task 5's job) and the six exact-dict response-shape assertions plus the whole frontend contract (Task 6's job). Committing Task 4 alone would leave the suite red, which the Global Constraints forbid. Work them as three task bodies for review, land them as one commit, and run the full gate once at the end of Task 6. Tasks 1-3 commit independently before them (they add no behavior); Tasks 7-10 commit independently after.

**Files:** modify `backend/services/bookmarks.py` (`_upsert_items` `:534-574`, `import_catalog` `:610-685`); create `backend/tests/test_catalog_sync_three_way.py`
**Interfaces:** `_upsert_items(items, *, stamp_now, enrich_force, resolver=None)`. When `resolver is None` the update branch behaves **exactly as today** — this is what keeps `import_json` (`:603`) and `force_seed` (`:704`) untouched. When supplied, `resolver(old, incoming) -> Resolution` decides which fields are applied, whether the live record is re-stamped (`changed`), and what the call contributes to `kept_local` (`kept` non-empty) and `conflicts` (`conflicts` non-empty).

**Acceptance:**
- Bookmarks (`:560-565`, fields `name / lat / lng / address / category_id`) and categories (`:653-657`) both go through the three-way merge, including the `ours == theirs ⇒ no-op, no conflict` clause (§4.2).
- `old.country_code = bm.country_code` (`:565`) is **deleted**, not merged: after this task the catalog never writes `country_code` onto an existing bookmark, and `enrich_bookmark` is its sole author (§4.2).
- `enrich_bookmark(old, force=True)` at `:567` is **called unchanged, after** the merge applies its values, so it re-derives the geo fields from whichever coordinates survived.
- Stamping per §4.3/§4.4: `force_seed_items` at `:645-646` unchanged; the live record is re-stamped only when a field was taken from theirs, **or** `enrich_bookmark` returned `True`, **or** the id is in the tombstone set.
- The tombstone set is the union of `self.store.tombstones` and `self._repo.load_or_empty().tombstones`, computed once at the top of `import_catalog`, and also feeds `resurrected` (§4.4).
- Return shape gains `kept_local` and `conflicts` at both `:639` and `:681-685`. `kept_local` counts records whose `Resolution.kept` is non-empty and `conflicts` counts records whose `Resolution.conflicts` is non-empty (§4.8) — neither is derivable from `values` / `changed` alone, which is why `Resolution` carries four members (§5).
- Baseline is read once at the start and written once after a successful sync — asserted, not assumed: a fake `CatalogBaselineRepository` that counts calls, injected through the Task 3 factory seam, records `read == 1` and `write == 1` across one `import_catalog` call.
- `import_json` and `force_seed` behavior is byte-identical.

- [ ] **Step 1 — failing tests** in `test_catalog_sync_three_way.py`, one per §4.2 row, for **both** bookmarks and categories: catalog correction with no local edit → takes theirs; local rename with unchanged catalog → keeps ours, `kept_local == 1`, `conflicts == 0`; both changed to *different* values → keeps ours, `conflicts == 1`; **both changed to the SAME value → no-op, `conflicts == 0`, `updated_at` not bumped** (the `ours == theirs` row); nothing changed → no-op **and `updated_at` not bumped** (§4.4); bootstrap with no baseline file → diverged local value survives, `conflicts == 0`; deleted id → resurrected via the ADD branch; a second sync after the baseline was written correctly detects a *new* catalog correction.
- [ ] **Step 1b — the three edge tests §4.2/§4.4 rest on**, all easy to omit and all load-bearing:
  - **Resolver owns `country_code` when it resolves.** A record whose local `country_code` differs from the catalog's, with `lat`/`lng` unedited: patch `services.bookmarks._geo_resolve` (as `test_bookmark_enrich.py:134` does) to return a **non-empty** tuple, then sync. Assert `country_code` equals what the resolver returned — not the catalog's value and not the prior local value — and that the record **is** re-stamped because enrich reported a change.
  - **The catalog does not own `country_code` when the resolver fails.** Same fixture, but patch `_geo_resolve` to return `("", "", "", "")` — the documented empty-resolve path (ocean point, or a venv missing `numpy` / `timezonefinder`). Assert the record's `country_code` is still the **local** value, that it is *not* the catalog's value, and that `updated_at` is unchanged. **These two cases must be written as a pair.** The first one alone cannot discriminate the two implementations: with the resolver succeeding, a lingering `old.country_code = bm.country_code` is immediately overwritten by enrich, so a merged-but-still-assigned `country_code` and a deleted assignment produce identical results. Only the empty-resolve case separates them, and it is exactly the case that fails silently and permanently in production (§4.2).
  - **Off-machine tombstone still resurrects.** Write a tombstone for a catalog id **directly into the store file** (simulating the other Mac) without reconciling it into memory, then sync with no field change. The record must survive `_save()` — proving the tombstone set is read from disk, not just memory. Without the disk read this test fails by the record vanishing.
- [ ] **Step 1c — cross-machine convergence + idempotence.** Two managers over one shared `bookmarks.json` (the `test_bookmark_revert_hazards.py:134,137` idiom) but **two separate baseline files** via `baseline_path_provider` (§5). The fixture carries **two** records, because they exercise different rows: `seed-edited`, which Mac 1 renamed locally, and `seed-clean`, which neither Mac has ever touched. Catalog **v1** is what both machines bootstrap against.

  Rounds 1-3 sync **v1** on both machines — *sync → save → the other manager reconciles from disk → sync* — and assert: (a) after round 1 both machines agree on both records; (b) rounds 2 and 3 leave every merged field on both machines equal to its round-1 value, both machines report the same `kept_local` (1 — `seed-edited` only), and `conflicts == 0` on every round on both machines; (c) each baseline file records that machine's own applied catalog. Then one extra sync on each with no intervening edit, asserting the store bytes are unchanged (idempotence).

- [ ] **Step 1c-ii — the round that actually fires the `ours == theirs` row.** Rounds 1-3 above sync one fixed catalog, so `theirs == base` on every round after bootstrap and the `ours != base, theirs != base` state never arises. That row is the reason Mac 2 exists in this fixture, and it needs a catalog that *moves*. Continue the same fixture with catalog **v2**, in which `seed-clean`'s name is corrected:
  - **Round 4a — Mac 1 syncs v2.** For `seed-clean`, Mac 1 has `ours == base` (v1) and `theirs != base`, so it **takes theirs** — the genuine correction the Refresh button exists to deliver. Assert Mac 1's `seed-clean` now holds v2's name, that it *was* re-stamped (a field was taken from theirs, §4.4 condition 1), and `conflicts == 0`. Mac 1 saves; its baseline becomes v2.
  - **Round 4b — Mac 2 reconciles from disk, then syncs v2 against its still-v1 baseline.** Mac 2 now holds v2's name for `seed-clean` (it arrived through the shared store, not through a sync), while its own baseline still records v1. That is exactly `ours != base, theirs != base, ours == theirs`. **Assert `conflicts == 0`, `kept_local == 1` (`seed-edited` only, not `seed-clean`), `seed-clean`'s value unchanged, and its `updated_at` NOT bumped** (no field was taken from theirs). Mac 2's baseline then advances to v2.
  - **This is the discriminating assertion.** Without §4.2's `ours == theirs` row, round 4b falls through to "keep ours + report a conflict" and `conflicts == 1` — a conflict on a record the user never edited, which the user could never clear because the resolution already equals the catalog. `conflicts == 0` here is the only assertion in the suite that separates the two implementations; the pure-unit version in Task 2 Step 1 pins the same row in isolation.
  - **Round 5 — re-sync v2 on both** with no intervening edit: both report `conflicts == 0`, `seed-clean` is a true no-op on both, and the store bytes are unchanged.
- [ ] **Step 1d — the baseline payload's shape (§4.6).** `test_baseline_written_matches_format_version_1_shape`: after one sync, load `catalog_baseline.json` and assert its top-level keys are exactly `{"_meta", "categories", "bookmarks"}`; `_meta["format_version"] == 1` with `compiled_at` and `applied_at` present; every entry under `bookmarks` has a key set exactly equal to `set(BOOKMARK_MERGE_FIELDS)` and every entry under `categories` exactly `set(CATEGORY_MERGE_FIELDS)` — so a payload that leaks `created_at` / `last_used_at` / a geo field, or that drops one, fails here. Task 3's round-trip test proves the store persists whatever it is handed; this proves what `import_catalog` hands it.
- [ ] **Step 2 — run, verify they fail.**
- [ ] **Step 3 — implement.**
- [ ] **Step 4 — boundary checks stay green untouched:** `test_import_json_resurrect.py:98-135`, `test_force_seed.py`, `test_upsert_items_unify.py:80-88` (`force_seed`), `test_bookmark_catalog_sync.py:74-90` (resurrect), `test_bookmark_enrich.py:106-138` (enrich unchanged).

### Task 5 — Invert hazard #1 in `test_bookmark_revert_hazards.py` (change D)

**Files:** modify `backend/tests/test_bookmark_revert_hazards.py` — the `test_catalog_force_sync_discards_local_rename` body. (Anchor on the test name: change D's file is uncommitted and its line numbers move.)
**Acceptance:** that test now pins E1's behavior. Rename it to `test_catalog_force_sync_preserves_local_rename` and update its docstring from "expected to INVERT when fix E ships" to a statement of the shipped rule.

Assertions that flip — the scenario is `ours != base, theirs == base` for `name`/`lat`/`lng`, i.e. a **pure local edit, not a genuine conflict**:

| Assertion | Today | After E1 |
|---|---|---|
| final name | `reverted.name == "Catalog Original"` | `preserved.name == "My Renamed Spot"` |
| final lat | `reverted.lat == 25.0` | `preserved.lat == 26.0` |
| final lng | `reverted.lng == 121.0` | `preserved.lng == 122.0` |
| final category | `reverted.category_id == "default"` | `preserved.category_id == "default"` (unchanged in this fixture) |
| stamp | `reverted.updated_at > local_updated_at` | `preserved.updated_at == local_updated_at` |
| — | — | **add:** `result["conflicts"] == 0` and `result["kept_local"] == 1` |

`kept_local == 1` is computable here only because of `Resolution.kept` (§5): this test has no baseline file, so bootstrap sets `base := theirs`, and the record resolves as `ours != base, theirs == base` for `name` / `lat` / `lng` — the row whose `values` / `conflicts` / `changed` are indistinguishable from "nobody touched anything". `kept == ("name", "lat", "lng")` is what makes it one record kept, and `conflicts == ()` is what keeps it out of the conflict count.

The stamp assertion holds because §4.4's three conditions all stay false here: no field is taken from theirs, the id has no tombstone on either side, and `enrich_bookmark` re-resolves the *same* coordinates it resolved during the local rename, so it reports no change.

- [ ] Flip the assertions above; keep `result["updated"] >= 1` — an id collision is still an "update".
- [ ] Do **not** delete the test.

### Task 6 — Response-shape updates across existing tests + frontend, and B's dialog copy

**Files:** modify `backend/api/bookmarks.py`, `backend/tests/test_bookmark_catalog_sync.py`, `backend/tests/test_bookmark_catalog.py`, `backend/tests/test_upsert_items_unify.py`, `frontend/src/services/api.ts`, `frontend/src/App.tsx`, `frontend/src/i18n/strings.ts`, `frontend/src/i18n/strings.test.ts`, `frontend/src/hooks/useCatalog.ts`, `frontend/src/hooks/useCatalog.test.ts`, `frontend/src/components/CatalogRefreshConfirmDialog.tsx`, `frontend/src/components/BookmarkList.tsx`, `frontend/src/components/BookmarkList.test.tsx`
**Acceptance:**
- `POST /catalog/sync` declares a `response_model`; every exact-dict assertion carries the two new keys.
- The toast surfaces the conflict line: `grep -c 'bm.catalog.synced_conflicts' frontend/src/App.tsx` prints **1**. There is no App-level toast test today (`grep -rn 'catalog.synced' frontend/src` matches only `App.tsx:884` and `strings.ts:702`), and this task does not add one — the grep is the check.
- `grep -c 'country_code' frontend/src/hooks/useCatalog.ts` prints **0**. The word survives in that file at six lines today (`:16`, `:41`, `:81`, `:91`, `:92`, `:111`) and the checkbox below removes all six — deleting the clause alone leaves four behind.
- `grep -nE '覆蓋|遺失|overwrit|lost|國碼|country' frontend/src/i18n/strings.ts` matches **neither** `bm.catalog.confirm_diverged` nor `bm.catalog.confirm_no_diverged`. Both strings are quoted verbatim below; check the final text against this list, not the intent.
- `strings.test.ts` passes with `DIALOG_KEYS` updated to the two renamed keys — which is what enforces "present in both languages, 繁體 only, no kana".

Exact assertion sites (structural, not behavioral — all six still describe the same outcome):

| File:line | Add |
|---|---|
| `test_bookmark_catalog_sync.py:61` | `"kept_local": 0, "conflicts": 0` |
| `test_bookmark_catalog_sync.py:70` | `"kept_local": 0, "conflicts": 0` |
| `test_bookmark_catalog_sync.py:117` | `"kept_local": 0, "conflicts": 0` |
| `test_bookmark_catalog.py:97` | `"kept_local": 0, "conflicts": 0` |
| `test_upsert_items_unify.py:50` | `"kept_local": 0, "conflicts": 0` |
| `test_upsert_items_unify.py:60` | `"kept_local": 0, "conflicts": 0` |

`test_upsert_items_unify.py:83,86` and `test_force_seed.py:77` assert `force_seed`'s two-key shape — **leave untouched.**

- [ ] Add `class CatalogSyncResult(BaseModel)` to `backend/api/bookmarks.py` — five `int` fields, no defaults — and set `response_model=CatalogSyncResult` on the `POST /catalog/sync` route (`:278`). This is Q3, decided yes; it closes R5 by turning a backend/TS key mismatch into a startup-time failure. Name it to match the TS interface it mirrors.
- [ ] Extend the TS `CatalogSyncResult` (`api.ts:457-461`) with `kept_local: number; conflicts: number`.
- [ ] `App.tsx:876-892` passes the new fields; when `conflicts > 0` also surface the conflict line.
- [ ] i18n (繁中 + English, both locales — 繁體中文 only, never Simplified, never kana; `strings.test.ts` enforces this for the dialog's keys):
  - `bm.catalog.synced` (`strings.ts:702-703`) — append `・保留本地 {kept_local}` / `· kept local {kept_local}`. The `・` separator is the one already in that string and stays: it is a toast key, not a `DIALOG_KEYS` member, so `strings.test.ts`'s `KANA_RE` never reads it. The two dialog keys below are the ones that must avoid it.
  - **new** `bm.catalog.synced_conflicts` — **ship exactly this text:**

    ```ts
    'bm.catalog.synced_conflicts': {
      zh: '{n} 筆同時有本地與清單變更，已保留你的版本',
      en: '{n} entries had both local and catalog changes; kept yours',
    },
    ```
  - **rewrite** `bm.catalog.confirm_overwrite` (`:710-711`) and **rename it to `bm.catalog.confirm_diverged`**, so no caller can keep the old promise by accident. Today it reads `將覆蓋 {n} 筆既有活動書籤，其名稱、座標、分類、地址與國碼的本地修改將遺失` / "Will overwrite {n} existing event bookmarks — local edits to their name, coordinates, category, address, and country will be lost". Three things are wrong after E1: it promises **loss** where E1 gives durability; it names **國碼 / country**, the one field E1 does not protect; and it reads the count as a durability promise, which §4.2 shows it cannot be — the same {n} covers records that will *take* the catalog value. The replacement is base-agnostic, so it is true whichever way each record resolves. **Ship exactly this text:**

    ```ts
    'bm.catalog.confirm_diverged': {
      zh: '{n} 筆既有活動書籤與清單不同：你在本機改過的名稱、座標、分類或地址會保留，沒改過的欄位會更新為清單版本',
      en: '{n} existing event bookmarks differ from the catalog — edits you made locally to name, coordinates, category or address are kept; fields you never edited are updated to the catalog value',
    },
    ```

    **The second half is inert on a machine's first post-upgrade Refresh, by design.** §4.7 bootstraps `base := theirs` when no baseline file exists, so `theirs != base` cannot fire on that sync: every counted record is kept and nothing takes the catalog value. The same holds permanently for the pre-upgrade divergence §4.7 knowingly misclassifies. The string stays as written — it is not false, only half-idle for one sync, and rewording it would reopen the acceptance grep and `strings.test.ts` for no user-visible gain.

    Four field names, matching `BOOKMARK_MERGE_FIELDS` exactly (座標 covers `lat` + `lng`). No negated verb, so the acceptance grep above passes: neither half contains 覆蓋 / 遺失 / overwrit / lost / 國碼 / country. The 繁中 half also carries no `・` (U+30FB lives in the Katakana block and `strings.test.ts`'s `KANA_RE` would reject it) — use `：` and `，`.
  - `bm.catalog.confirm_no_overwrite` (`:712`) — today `不會覆蓋任何既有書籤的本地修改` / "No existing bookmarks will be overwritten". Still true, but it reads as a contrast with a warning that no longer warns, and it keeps the overwrite framing the sibling just dropped. Rename to `bm.catalog.confirm_no_diverged` and reword to the plain "nothing on this machine differs from the catalog" sense. **Ship exactly this text:**

    ```ts
    'bm.catalog.confirm_no_diverged': {
      zh: '既有活動書籤都與清單一致，沒有本機修改需要保留',
      en: 'All existing event bookmarks match the catalog — there are no local edits to keep',
    },
    ```
- [ ] Follow the two key renames through every consumer: `CatalogRefreshConfirmDialog.tsx:62,66`, `strings.test.ts:12-18` (`DIALOG_KEYS`), and `BookmarkList.test.tsx:896-897,906-907` (which assert on the rendered `bm.catalog.confirm_*::{...}` mock strings). Missing any one of these turns the suite red.
- [ ] `catalogOverwriteCount` (`useCatalog.ts:98-115`) is **relabelled AND narrowed by one field**:
  - Delete the `country_code` clause `(existing.country_code ?? '').toLowerCase() !== (cb.country_code ?? '').toLowerCase()` (`:111`). E1 leaves `country_code` to the geo resolver, so a `country_code`-only divergence is *not* something the user's version survives, and counting it would make the dialog promise durability the backend does not provide. The remaining five clauses — `name`, `roundCoord(lat)`, `roundCoord(lng)`, `category_id`, `address` — are exactly `BOOKMARK_MERGE_FIELDS`. Keep the `address` clause and its `?? ''` normalisation; keep `roundCoord`.
  - **Remove `country_code` from the file entirely — the clause is one of six sites.** Deleting `:111` alone leaves five, and the acceptance grep above is then unachievable. Also delete: the field declaration `country_code?: string;` on `CatalogDiffBookmark` (`:41`), the whole normalisation paragraph that justified the clause (`:86-97`, whose `address` half is folded into the rewritten comment), the field list in the predicate comment (`:81`), and the field list in the header comment (`:16`). Dropping `:41` is safe for `tsc`: `CatalogDiffBookmark` is local to this file (`grep -rn 'CatalogDiffBookmark' frontend/src` → two hits, both in `useCatalog.ts`), it describes only what the hook *reads*, and every caller — `App.tsx` and the `useCatalog.test.ts` fixtures — passes a named `const`, not a fresh object literal, so structural width subtyping applies and TypeScript's excess-property check does not fire.
  - Rename the identifier to `catalogDivergedCount` and carry it through `useCatalog.ts:139`, `App.tsx:873,1305`, `BookmarkList.tsx:94,135` and the dialog's `overwriteCount` prop → `divergedCount` at **all four** of its sites (`CatalogRefreshConfirmDialog.tsx:11` declaration, `:28` destructuring, `:54` branch test, `:62` interpolation — the destructuring is the one that is easy to miss and fails as an unused-variable/undefined-name error rather than a test) plus `BookmarkList.tsx:1042`, the three prop sites in `BookmarkList.test.tsx` (`:116`, `:872`, `:901`), and **the three sites in `ControlPanel.tsx`** (`:120` prop declaration, `:327` destructuring, `:1019` forward to `BookmarkList`) — `App.tsx` hands the count to `ControlPanel`, not straight to `BookmarkList`, so skipping this file breaks the chain at `tsc`. Update the two stale comments that name the old field list — `useCatalog.ts:14-20`, `BookmarkList.tsx:91-93` — the dialog's prop comment (`:9-10`), and the dialog's JSDoc (`:16-24`), which currently states that the sync "force-overwrites every catalog-seeded bookmark's name/lat/lng/address/category_id and re-stamps updated_at". Every rewritten comment states what §4.2 settled: the number means **differs from the catalog**, not *will be kept*.
  - `useCatalog.test.ts` changes with it: the two `country_code` cases (`:129-139` asserts `1`, `:155-165` asserts `0`) both become "a `country_code`-only divergence is **not** counted → `0`", renamed to say why (E1 leaves the field to the resolver). The `address` case (`:117-127`) and the missing-address case (`:141-153`) keep their current expectations. Rename the remaining `catalogOverwriteCount` references and update the test title at `:82`, which names the old four-field list.
- [ ] `npx tsc --noEmit` clean; vitest green; `npx depcruise` 0 errors.

### Task 7 — `BookmarkUpdate` partial-update model (F's backend half)

**Files:** modify `backend/api/bookmarks.py` (add `BookmarkUpdate`, change `update_bookmark` `:92-105`), `backend/services/bookmarks.py` (`update_bookmark` `:407-421`, the §6.6 guard), `backend/tests/test_bookmark_revert_hazards.py` (two of its three tests, §6.6 and Step 1b below); create `backend/tests/test_bookmark_update_partial_api.py`
**Interfaces:** `class BookmarkUpdate(BaseModel)` with `name: str | None = None`, `lat: float | None = None`, `lng: float | None = None`, `address: str | None = None`, `category_id: str | None = None`, `country_code: str | None = None`. Route forwards only non-`None` values; `response_model=Bookmark` and the 404 path are unchanged. The partial-update mechanism needs no service change — `update_bookmark`'s `is not None` guard (`:407-412`) is already correct. The **one** service change is the §6.6 no-op guard, which is a separate concern riding in the same task because it closes the other half of §1's root cause on the same code path.

**Acceptance:** an omitted field leaves the stored value untouched; an explicit `""` still clears; a body with only `{"name": "x"}` succeeds (no 422); unknown id still 404; **a `PUT` that changes nothing writes nothing — `updated_at` included** (§6.6).

- [ ] **Step 1 — failing tests** in the new file. The endpoint's existing HTTP coverage is exactly one test — `test_bookmark_revert_hazards.py::test_api_put_omitting_address_field_blanks_it_today` (`:298`, the suite's only `client.put` against `/api/bookmarks/{id}`, at `:319`) — which pins the defect F removes. Step 1b inverts that one; these are new cases beside it:
  - `PUT` with `{"name": "renamed"}` only → `address`, `category_id`, `country_code` all unchanged.
  - `PUT` with `{"address": ""}` explicitly → address cleared (explicit blank still works).
  - `PUT` with `{"lat": .., "lng": ..}` only → coords updated, geo re-resolved, `name` unchanged.
  - `PUT` with `{}` → 200 and the record **byte-identical, `updated_at` included** (§6.6).
  - `PUT` re-sending the values already stored → same: 200, `updated_at` unchanged, and the store file's mtime is untouched (proves `_save()` was skipped, not just the stamp).
  - `PUT` unknown id → 404.
  - Regression: a **full** body with at least one genuinely changed field still behaves exactly as before, `updated_at` bump included.
- [ ] **Step 1b — the two change-D tests this task touches.** Anchor on test names; change D's file is uncommitted and its line numbers move.
  - **`test_api_put_omitting_address_field_blanks_it_today` — invert and rename.** It creates a bookmark with `address="有地址"`, then `PUT`s `{"name": "y", "lat": 1.0, "lng": 2.0, "category_id": "default"}` and asserts `body["address"] == ""`. That final assertion becomes `body["address"] == "有地址"`; keep `body["name"] == "y"` as it is. Rename to `test_api_put_omitting_address_field_leaves_it_unchanged` so the name stops describing the removed behavior, and rewrite its docstring from "Expected (buggy, current) outcome … Fix F is expected to INVERT" into a statement of the shipped rule. This is the most direct proof F works and it costs one line.
  - **`test_stale_whole_record_update_outranks_fresher_remote_copy` — keep its assertions, give manager A a real edit.** Per §6.6 the guard makes A's write at `:154` a literal no-op, so as written the test would fail. The minimal honest repair is to have A change one field the peer did not touch — pass `address="A's own edit"` in that call instead of `address=bm.address` — and add a comment saying why. The two assertions (`on_disk_bm["name"] == "old"` and `on_disk_bm["updated_at"] > b_result.updated_at`) then stay **byte-identical and still true**, and the test pins a sharper version of the same hazard: it is now §11's residual case 1 exactly — two Macs edit *different* fields of one record, whole-record LWW takes A's copy whole, B's rename is lost. Update the module docstring accordingly.
  - *Alternative considered and rejected:* flipping this test to the guard's outcome (`on_disk_bm["name"] == "new"`, A never saved) — the file's own docstring offers it as option (a). It is correct but it deletes the suite's only pin on the residual whole-record-LWW hazard, which §11 explicitly commits to keeping pinned. The one-field edit keeps both. If Ravi prefers the flip, add a separate test for the no-op guard's cross-machine effect instead (Q6).
- [ ] **Step 2 — run, verify they fail** (today the omitted fields are blanked; the name-only body 422s on missing `lat`/`lng`; `{}` bumps `updated_at`).
- [ ] **Step 3 — implement.** The no-op guard compares **after** `round_coord`, over the same `allowed` set the mutation loop uses, so coordinate noise below store precision is not a change.
- [ ] **Step 4 — boundary check for the guard:** the six service-level callers that change a value (`test_bookmark_enrich.py:109,117,135`, `test_bookmark_coord_rounding.py:50,58`, `test_bookmark_tombstones.py:29`) must stay green **untouched** — if any needed editing, the guard is over-firing. The other three `update_bookmark` call sites in the suite are all in `test_bookmark_revert_hazards.py`: `:140` and `:213` change a value and are likewise untouched; `:154` is the no-op handled in Step 1b.
- [ ] **Step 5 — `lint-imports` 7 kept 0 broken;** full backend suite green.

### Task 8 — Add the cross-machine sparse-`PUT` test to `test_bookmark_revert_hazards.py` (change D)

**Files:** modify `backend/tests/test_bookmark_revert_hazards.py` — **add** a fourth test. Task 7 has already inverted `test_api_put_omitting_address_field_blanks_it_today` and re-pointed `test_stale_whole_record_update_outranks_fresher_remote_copy`; this task adds the case neither of those covers, the one that needs two machines.

**Anchor on test names, not line numbers.** This file is change D's, still uncommitted; the line numbers quoted elsewhere in this plan are a snapshot.

**⚠ F does not invert the service-level test, and cannot.** `test_stale_whole_record_update_outranks_fresher_remote_copy` drives `mgr_a.update_bookmark(...)` directly at the **service** layer, and its staleness lives in **manager A's in-memory record**, not in the request body. Walk it: `update_bookmark` mutates the object returned by `self._find_bookmark(id)` — A's own copy, which still holds `name="old"` because A never reconciled after B's save. It then stamps `_now_iso()` (`services/bookmarks.py:419`) and calls `_save()`, which is a read-merge-write (`:146-154`) whose `_union_by_id` (`domain/store_merge.py:41-52`) replaces the **whole** record by `updated_at`. A's record — carrying `"old"` and the newest stamp — wins. Removing `name` from the *call* changes nothing: the value is already on the object. **F fixes a stale client BODY, not a stale in-memory MANAGER**, so any assertion that that test's `on_disk["name"]` becomes `"new"` is unreachable through F. (The store-level hazard it pins is real and stays pinned; the fix for *that* one is G, deferred. What *does* reach it is §6.6's no-op guard, handled in Task 7 Step 1b.)

A cross-machine test of F must therefore (a) go through the HTTP route, and (b) put the staleness in the request body while the serving manager is **current** — which is the real topology: each Mac runs one backend whose watcher reconciles the synced file, so by the time the user presses Save, that Mac's manager already holds the peer's rename; only the dialog snapshot in the browser is stale.

**Interfaces — how the `TestClient` is bound to a chosen manager.** `deps.get_bookmark_manager` (`api/deps.py:49-53`) reads `container.bookmark_manager`, which delegates to `engine_registry.bookmark_manager` when the registry has that attribute (`bootstrap/container.py:70-81`) — and in production the registry *is* `main.app_state`. So the repo's established seam, used by ~8 fixtures (`test_bookmarks_api.py:8-19`, `test_bookmarks_di_char.py:17-28`, and change D's own `_api_client` at `test_bookmark_revert_hazards.py:287-295`), is:

```python
monkeypatch.setattr(main.app_state, "bookmark_manager", serving)
client = TestClient(main.app)
```

Use that, not `app.dependency_overrides` — it is the same one-line binding and it keeps this test consistent with every other HTTP bookmark test.

**Acceptance:**
- [ ] **Name:** `test_sparse_put_does_not_clobber_fresher_remote_field`.
- [ ] **Keep the two-manager shared-file setup** (it is what makes B's rename a genuinely *remote* value), reusing the file's own `_patch_paths(tmp_path, monkeypatch)` helper so all managers resolve to one tmp store: `mgr_a` creates `name="old"`; `mgr_b`, a second manager over the same file, renames it to `"new"` and saves (`b_result`).
- [ ] **Add a third, freshly-constructed manager as the one HTTP serves** — `serving = make_bookmark_manager()`, created **after** B's save so it loads `"new"` from disk. This is Mac A's backend after its watcher reconciled. Bind it as above. Staleness now lives **only** in the request body.
- [ ] **Assertion 1 — the sparse body (this is what F buys).** `PUT /api/bookmarks/{id}` with `{"address": "Zhongshan Rd"}` and nothing else → 200; on disk `name == "new"`, `address == "Zhongshan Rd"`, and `updated_at > b_result.updated_at`. B's rename survives *despite* A's write being strictly newer — which is the whole point.
- [ ] **Assertion 2 — the retained characterization, in the same test, immediately after.** `PUT` the same id with a **full** stale body (`name="old"` plus every other field) → 200; on disk `name == "old"`. A client that explicitly sends every field still wins by LWW. That is correct behavior, not a bug, and the two assertions side by side are what make the test document both halves.
- [ ] **Docstring** states the shipped rule and the distinction above: the body is what F narrows; the manager is already current; the residual store-level hazard is §11's.
- [ ] **Pin *why* the sparse body parses, as a standing assertion — not as a "run it before Task 7" instruction.** Task 7 lands in an earlier commit, so by the time this test exists the pre-F behavior is gone and "verify it fails first" is unrunnable. Assert the thing that was true before and must stay true: the **persisted** model still refuses the sparse body, and only the request model accepts it.

  ```python
  # The body below is parseable ONLY because the route now takes BookmarkUpdate.
  # The persisted model still requires name/lat/lng, which is why this same body
  # was a 422 before F — and why widening `Bookmark` would be the wrong fix.
  with pytest.raises(ValidationError):
      Bookmark(**{"address": "Zhongshan Rd"})
  ```

  This is objectively checkable at any commit after Task 7, it fails if someone "fixes" F by relaxing `Bookmark`'s required fields (which would change the on-disk shape), and it documents the 422 that used to be the failure mode.
- [ ] **Finish the module docstring** Task 7 started. It is a long narrative written against the pre-F tree: it says the file pins "two confirmed hazards" when there are now four tests, describes Test 2 as "expected to INVERT when fix E ships", describes Test 1's outcome as one that "would only flip if a future change makes the re-stamp itself conditional", and names `test_api_put_omitting_address_field_blanks_it_today` as "the test that fix F genuinely inverts". After Tasks 5, 7 and 8 every one of those is history. Rewrite it as a description of the shipped rules and what each of the four tests now guards.

### Task 9 — Frontend sends a sparse body (F's other half)

**Files:** modify `frontend/src/components/EditBookmarkDialog.tsx:81-100`, `frontend/src/components/EditBookmarkDialog.test.tsx`, `frontend/src/components/BookmarkList.test.tsx`, `frontend/src/App.tsx:1088-1099`, `frontend/src/services/api.ts:367`
**Acceptance:** a rename-only edit puts exactly one mutable key on the wire. `api.updateBookmark`'s `bm: any` tightens to a partial bookmark type.

**There are TWO spreads, and removing only App's is not enough.** `EditBookmarkDialog.handleSubmit` (`:94`) starts from `const patch: Partial<DialogBookmark> = { ...bookmark }` and overrides the dirty fields; `App.onBookmarkEdit` (`:1090`) then spreads the live `Bookmark` into its own `patch`. Leave the dialog's spread in place and a rename-only edit still ships `lat`, `lng`, `category`→`category_id` and `country_code` — Step 1's test cannot pass. Change C is **kept**: its per-field dirty flags are exactly what selects the keys, and omitting an untouched field is a strictly stronger version of C's "submit the live value" property, not a retreat from it.

- [ ] **Step 1 — failing vitest**, one at each layer:
  - `EditBookmarkDialog.test.tsx`: a submit with only `latDirty`/`lngDirty` set calls `onSubmit('bm-1', { id, lat, lng })` — assert `'name' in patch` is `false`.
  - `BookmarkList.test.tsx`: the same through the real dialog — `'a rename-only edit sends only { name } to updateBookmark'`, asserting `patch.name` is the typed value and `expect(patch).not.toHaveProperty(k)` for each of `lat`, `lng`, `category_id`, `address`, `country_code`.
- [ ] **Step 2 — run, verify they fail** (today both spread the live record).
- [ ] **Step 3 — implement.**
  - `EditBookmarkDialog.handleSubmit`: build `patch` from the dirty flags alone (`nameDirty`, `latDirty`, `lngDirty`), carrying `bookmark.id` through. Keep both range guards (`:85-86`) and the `if (!bookmark.id) { onClose(); return; }` early exit (`:84`). Rewrite the comment at `:87-93`, which currently explains the spread as "Backend PUT requires the full Bookmark shape" — after F it does not.
  - `App.onBookmarkEdit`: drop `const patch: any = orig ? { ...orig } : { ...data, id }`; build the patch from `data` alone. Keep the category-name → `category_id` lookup (`:1094-1097`) and keep the `orig` lookup only for that. `onMoveToCategory` (`BookmarkList.tsx:992`) already passes a sparse `{ category }` and now stays sparse all the way to the wire.
- [ ] **Step 3b — the change-C tests this moves.** `BookmarkList.test.tsx:667-699` (`'submits the LIVE name (not the one captured at open time) when only coordinates were edited'`) asserts `patch.name === 'Renamed On Other Mac'`; with the spread gone, `name` is absent. Flip it to `expect(patch).not.toHaveProperty('name')` and rename it to say the untouched field is now omitted rather than re-sent — the durability property it guards is preserved and strengthened, since an omitted key cannot lose a race at all. Its sibling at `:701-729` (the user *did* type a name) keeps `patch.name === 'User Typed Name'` unchanged. In `EditBookmarkDialog.test.tsx` the **four** `onSubmit` shape assertions that expect `{ ...ORIG, … }` (`:71-85`, `:160-174`, `:177-207`, `:209-231`) become sparse-patch expectations; the two "does not submit when lat/lng is out of range" cases and the no-id case are unaffected.
- [ ] **Step 4 — `npx tsc --noEmit` clean;** vitest green; depcruise 0 errors.
- [ ] **Step 5 — verify the dirty flags still select the keys, mechanically:** `grep -c '\.\.\.bookmark' frontend/src/components/EditBookmarkDialog.tsx` is `0`, `grep -c '\.\.\.orig' frontend/src/App.tsx` is `0`, and `nameDirty` / `latDirty` / `lngDirty` still each appear in `handleSubmit`. Change C's props and state are not removed.

### Task 10 — *(Recommended, separable)* F2: category partial update + live category dialog

**Files:** modify `backend/api/bookmarks.py:139-151` (route) **and `:21-40`** (`_validate_date_range`), `frontend/src/components/BookmarkList.tsx:186-193`, `frontend/src/App.tsx:1121-1131`; extend `backend/tests/test_bookmark_update_partial_api.py`
**Acceptance:** `PUT /api/bookmarks/categories/{cat_id}` accepts a `BookmarkCategoryUpdate` (all-Optional) body; an omitted `color` / `start_date` / `end_date` no longer blanks the stored value; an omitted date does **not** 500; the category edit dialog submits only touched fields.

**⚠ `BookmarkCategoryUpdate` is NOT a drop-in — the validator has to change with it.** The route calls `_validate_date_range(cat.start_date, cat.end_date)` at `:141`, and that function is typed `(start: str, end: str)`: it skips only the literal `""`, so a `None` falls through to `_ISO_DATE_RE.match(None)` → `TypeError` → **500**, not 422. Every omitted-date request would fail. Fix it in the same commit: make the signature `(start: str | None, end: str | None)` and treat `None` exactly like `""` (skip — "not supplied" and "cleared" are both "nothing to validate"). Keep the cross-field `start > end` check on the two supplied values only.

- [ ] **Step 1 — failing tests:** `PUT` a category with `{"name": "x"}` only → `color`, `start_date`, `end_date` unchanged **and status 200** (today: all three blanked; after a naive all-Optional model without the validator fix: 500).
- [ ] **Step 2 — implement** the API model exactly as Task 7, plus the `_validate_date_range` `None` handling (`update_category` at `services/bookmarks.py:273-299` already has the right guard — no service change).
- [ ] **Step 2b — the existing HTTP coverage of this route must stay green untouched:** `test_bookmark_event_dates.py:196-211` (`test_put_category_updates_dates` — explicit `""` still clears both dates) and `:214-222` (`test_put_category_rejects_bad_format` — a supplied malformed date is still 422, not 500). These two are the only HTTP category-`PUT` tests in the suite and are precisely the regression net for the change above.
- [ ] **Step 3 — frontend:** apply change C's per-field dirty-tracking pattern to `openEditCategory` (`BookmarkList.tsx:186-193`, which today seeds `editCatNewName` / `editCatColor` / `editCatStart` / `editCatEnd` once at open) and `onCategoryEdit` (`App.tsx:1121-1131`, which today forwards all four fields unconditionally), so the dialog sends only what changed.
  - **Named test:** `BookmarkList.test.tsx::'category edit submits only the fields the user touched'` — open the category dialog, change only the name, save, and assert the patch handed to `onCategoryEdit` satisfies `expect(patch).not.toHaveProperty('color')`, `…not.toHaveProperty('start_date')`, `…not.toHaveProperty('end_date')`, and `patch.name` is the typed value. This mirrors Task 9 Step 1's dialog test exactly.
  - **Mechanical predicate:** in `App.tsx`'s `onCategoryEdit`, `grep -c 'color: patch.color' frontend/src/App.tsx` is `0` — the unconditional four-field forward is gone, not merely reordered.
- [ ] **Drop this task** if Ravi prefers to keep the diff to the approved E1+F scope; Tasks 1-9 do not depend on it.

---

## 9. Test Plan

**New tests**

| File | Covers |
|---|---|
| `backend/tests/test_catalog_merge_domain.py` | §4.2 matrix as pure functions, asserting all four `Resolution` members per row; the `kept`-discriminates-two-identical-rows pair (§4.8); bootstrap `base=None`; per-field `kept` / `conflicts` naming; `set(conflicts) <= set(kept)` |
| `backend/tests/test_catalog_baseline_store.py` | Path isolation; key-for-key round-trip of a §4.6 `format_version` 1 payload; missing → `None`; corrupt → `None`; lazy path resolution; two managers → two independent baselines via `baseline_path_provider` |
| `backend/tests/test_catalog_sync_three_way.py` | §4.2 matrix end-to-end for bookmarks **and** categories, including the `ours == theirs` row; §4.4 stamping rule; `country_code` stays resolver-owned **on both the resolve-succeeds and the resolve-returns-empty path** (Task 4 Step 1b); an off-machine tombstone still resurrects; bootstrap-first-sync; resurrection unaffected; second-sync detects a new correction; **cross-machine three-round convergence + idempotence** (Task 4 Step 1c); **the `ours == theirs` row fired by a corrected catalog on the second Mac** (Task 4 Step 1c-ii); **the baseline payload's `format_version` 1 field set** (Task 4 Step 1d) |
| `backend/tests/test_bookmark_update_partial_api.py` | HTTP partial `PUT`; the §6.6 no-op guard |
| `backend/tests/test_bookmark_revert_hazards.py::test_sparse_put_does_not_clobber_fresher_remote_field` | The cross-machine sparse-`PUT` case: a sparse write no longer clobbers a field a peer changed (Task 8) |

**Existing tests that change meaning**

| Test | Change | Kind |
|---|---|---|
| `test_bookmark_revert_hazards.py::test_catalog_force_sync_discards_local_rename` | Assertions inverted, renamed to `…_preserves_local_rename` (Task 5) | **behavioral** |
| `test_bookmark_revert_hazards.py::test_api_put_omitting_address_field_blanks_it_today` | Final assertion inverted (`address` survives an omitting `PUT`), renamed to `…_leaves_it_unchanged` (Task 7 Step 1b) | **behavioral** |
| `test_bookmark_revert_hazards.py::test_stale_whole_record_update_outranks_fresher_remote_copy` | Assertions unchanged; manager A's call gains one genuinely-edited field so §6.6's guard does not turn it into a no-op (Task 7 Step 1b) | **fixture only** — the pinned outcome is identical |
| `test_bookmark_revert_hazards.py` module docstring | Now describes the shipped rules and four tests, not two pending fixes (Tasks 5, 7, 8) | **doc only** |
| `test_bookmark_catalog_sync.py:61,70,117` · `test_bookmark_catalog.py:97` · `test_upsert_items_unify.py:50,60` | Two keys added to exact-dict assertions (Task 6) | **structural only** — outcomes unchanged |
| `useCatalog.test.ts:129-139,155-165` | A `country_code`-only divergence stops being counted (Task 6); both fixtures keep passing `country_code` through a named `const`, which stays type-safe after the field leaves `CatalogDiffBookmark` | **behavioral** |
| `useCatalog.test.ts:13,66` · `BookmarkList.test.tsx:896-897,906-907` · `strings.test.ts:12-18` | Response-shape keys and the two renamed i18n keys (Task 6) | **structural only** |
| `BookmarkList.test.tsx:667-699` | An untouched field is now **omitted** rather than re-sent live; assertion becomes `not.toHaveProperty('name')` (Task 9 Step 3b) | **behavioral** — strengthens change C's property |
| `EditBookmarkDialog.test.tsx:71-85,160-174,177-207,209-231` | The four `{ ...ORIG, … }` submit-shape assertions become sparse patches (Task 9 Step 3b) | **behavioral** — same |

**Existing tests that must stay green untouched** (boundary proof that scope held): `test_import_json_resurrect.py:98-135` · `test_bookmark_catalog_sync.py:74-90` (resurrect) · `test_bookmark_catalog_sync.py:93-102` (catalog correction with no local edit — the `ours == base` row, and the test that pins the behavior `c748fef` promised) · `test_force_seed.py` · `test_upsert_items_unify.py:80-88` · `test_bookmark_enrich.py:106-138` (proves E1 left enrichment alone) · `test_bookmark_coord_rounding.py:47-61` · `test_bookmark_tombstones.py:26-30` · all `POST /import` tests. The last three also double as the §6.6 no-op-guard boundary: every `update_bookmark` call in them changes a value, so none may need editing. The one `update_bookmark` call in the suite that changes nothing is `test_bookmark_revert_hazards.py:154`, and it is handled in Task 7 Step 1b rather than left to fail.

**Full gate — after every commit**

```bash
cd backend && .venv/bin/python -m pytest -q          # 1200 + new tests, 0 failures
cd backend && .venv/bin/lint-imports                  # 7 kept, 0 broken
cd frontend && npx tsc --noEmit                       # clean
cd frontend && npx vitest run                         # 986 + new tests, 0 failures
cd frontend && npx depcruise --config .dependency-cruiser.cjs src   # 0 errors
```

---

## 10. Rollout Across Two Macs

**F needs no data migration.** It changes only the HTTP contract between the local Electron frontend and the local FastAPI backend — same app bundle, same machine, loopback only. Nothing F touches is serialized into `bookmarks.json`; `BookmarkUpdate` is a request-body model that never reaches the store. Verified: `models/schemas.py`'s `Bookmark` (the persisted shape) is untouched.

**E1 needs no data migration either.** `catalog_baseline.json` lives in `~/.locwarp/`, is never placed in `sync_folder`, and is bootstrapped independently on each machine at its first post-upgrade sync (§4.7). `bookmarks.json`'s format is unchanged.

**On the Mac that has NOT been upgraded yet:** it keeps today's behavior — its catalog Refresh still wholesale-overwrites, and its Edit dialog still sends full-record `PUT`s. Both stores still merge normally, because the merge rule and the file format are identical on both sides. So a revert can still originate from the un-upgraded machine until it is upgraded. This is a *reduced* exposure, not zero, and it is why the two installs should not be far apart in time.

**Recommended install order:**
1. Upgrade the **lighter-writing** Mac first, as a canary: launch, confirm bookmarks are intact, click Refresh once, and check the toast reports `kept_local` with `conflicts: 0` (expected on a bootstrap sync).
2. Upgrade the **heavier-writing** Mac the same day. It is the larger source of full-record `PUT`s, so leaving it un-upgraded keeps producing the exact writes F exists to prevent — the canary gap should be hours, not days.

**`make build-install` cannot be run from an agent session** — it needs an interactive `sudo` TTY. Ravi installs both machines by hand.

---

## 11. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **`_upsert_items` is a genuinely shared primitive** (three callers: `:603`, `:672`, `:704`). A change to its update branch could leak into `import_json` or `force_seed`. | The `resolver=None` default makes the change opt-in per call site. Task 4 Step 4 re-runs the boundary tests explicitly. |
| R2 | **The category loop is a separate code path** from the bookmark update branch, in different loops of the same method. Easy to fix one and miss the other. | Called out in §4.2; Task 4's acceptance requires both, with tests for both. |
| R3 | **E1's persisted baseline resembles a previously-rejected design.** Commit `6434b30` "drop bookmark_merge 3-way merge, retire dead snapshot field" removed a whole-store persisted base (Approach 2 in `docs/plans/2026-05-14-icloud-sync-conflict-resolution.md`). A reviewer may read E1 as resurrecting it. | **They are different in scope.** The retired base was for the *continuously-running* store sync loop across machines — it had to be correct on every write and it drifted. E1's base is **catalog-only, per-machine, non-synced, and consulted once per explicit Refresh click**. It never participates in `merge_stores`, which is unchanged. Stated here so the distinction is on the record. |
| R4 | **The `catalog_baseline=None` default silently degrades E1 to permanent bootstrap.** Measured: `grep -rn "BookmarkManager(" backend/` returns exactly **one** production site, `bootstrap/factories.py:17`, and **zero** constructions in `backend/tests/` — every test builds through `make_bookmark_manager()`. So the compatibility risk the default was added for does not exist; what the default actually buys is that a *future* path bypassing the factory would get a manager with no baseline, which reads `base := theirs` forever (§4.7) and quietly stops preserving local edits — with no error. | Keep the `None` default (it is what makes the port optional and the domain testable in isolation), but make it loud: a `logger.warning` on the first `import_catalog` with `catalog_baseline is None`, and a docstring line on `__init__` saying the composition root is the only intended constructor. Task 3 Step 4 asserts the factory-built manager has a non-`None` port, so a regression in `factories.py` fails a test rather than degrading in silence. |
| R5 | **No pydantic `response_model` on `POST /catalog/sync`** (`api/bookmarks.py:279`) — the only typed contract is the TS interface. A backend/TS key mismatch is silent until a click. | Task 6 changes both sides in one commit **and adds the `response_model`** (Q3), turning a silent mismatch into a startup-time failure. |
| R6 | **`force_seed` is latent.** It is unused in production but shares the blind-overwrite branch and would inherit the hazard if wired to a real caller. | Not changed here. Leave a comment on `force_seed` noting that a future catalog-shaped caller should pass a `resolver`. |
| R7 | **F is inert without Task 9.** Shipping only the backend half closes nothing. | §6.4 states it; Task 9 Step 5's grep predicates (`...bookmark` / `...orig` gone, dirty flags still present) are the objective check that the frontend half actually shipped, and Task 8's `ValidationError` assertion records why the sparse body could not have been sent before F. |
| R8 | **Concurrent working tree.** A/B/C/D are uncommitted changes by other agents in the same tree, touching `App.tsx`, `strings.ts`, `useCatalog.ts`, `BookmarkList.tsx`, `EditBookmarkDialog.tsx`, `config.py`. | Base every diff on the tree as-is; never revert C's dirty-tracking or B's dialog. Task 6 explicitly *updates* B's copy rather than working around it. |

**Residual exposure after E1 + F — stated honestly.**

1. **Disjoint concurrent edits.** Whole-record LWW is unchanged, so this remains possible: **two Macs edit *different* fields of the *same* bookmark between syncs.** Mac 1 changes the name, Mac 2 changes the address, neither has seen the other. Whichever save lands with the newer `updated_at` replaces the record whole, and the other machine's field is lost. E1 does not help (this is not a catalog sync) and F does not help (each machine legitimately touched its own field). Only G — per-field timestamps — would fix it, and G is deferred. This is the hazard `test_bookmark_revert_hazards.py::test_stale_whole_record_update_outranks_fresher_remote_copy` pins, and Task 7 Step 1b keeps it pinned in exactly this shape: after the guard ships, A's write in that test carries one genuine field edit, which is what makes it this case rather than a no-op.
2. **A stale in-memory manager.** F narrows the request *body*; it cannot help a backend whose own copy of a record is behind the synced file — if that manager writes for any reason, its whole stale record wins. In practice the watcher reconciles, which is why the realistic version of this is (1) rather than a standing exposure; §6.6 removes the most reachable trigger (a Save that changes nothing) but not the class.
3. **A stale baseline on a Mac that rarely clicks Refresh.** That Mac receives the peer's applied catalog correction through iCloud, so its *store* moves while its *baseline* does not. If the catalog then moves **again** before it next clicks Refresh, that record reads as `ours != base, theirs != base, ours != theirs` — one conflict reported for a field the user never edited, the newer catalog value passed over, and the record pinned thereafter exactly as in §4.7's bootstrap trade. If the catalog has *not* moved again in the interval, §4.2's `ours == theirs` row absorbs it silently and the baseline self-heals with no conflict. Clicking Refresh on both Macs after a catalog bump keeps it in the second, silent case; the escape hatch for the first is §4.7's (delete the seed and re-Refresh).
4. ~~**`update_category` keeps the unconditional re-stamp.**~~ **Closed after the plan shipped.** The guard was originally scoped to `update_bookmark` alone, to keep its blast radius to the one method with a reported bug. Task 10 then landed the category dialog's dirty tracking, which submits an **empty** patch when the user changed nothing — so the unconditional re-stamp became a live revert vector for categories, the same shape as the bookmark bug. `update_category` now carries the identical diff guard.

**How Ravi would detect it (case 1):** the backup-diff diagnostic. `~/.locwarp/backups/` archives a timestamped snapshot whenever the data changes, and under change A retention is now **720h / 30 days** (`config.py:111`, mirrored by `scripts/desktop_backup.py`), so a revert noticed weeks later still has both the before and after snapshots on disk. Diff two snapshots for the bookmark's id and check whether the lost field's value ever existed in an earlier snapshot on that machine. Judgement: this is a **rare** case — it needs simultaneous edits to disjoint fields of one record on two machines inside one sync window — and 30 days of snapshots is proportionate coverage for it.

---

## 12. Docs to Update

| Doc | Section | Why it goes stale |
|---|---|---|
| `CLAUDE.md` | *"Bookmark / Route store: CRDT merge semantics"* | Add a note that the catalog force-sync now resolves per field against a local baseline before the store merge runs, and that `merge_stores` itself is unchanged. |
| `CLAUDE.md` | *"Local rotating backup (`~/.locwarp/backups/`)"* → **Test isolation** | It says "extend that guard for any new `~/.locwarp` path" — record that `CATALOG_BASELINE_FILE` is now covered. |
| `CLAUDE.md` | *"Catalog seed (`backend/static/catalog.json`)"* | Note that editing a seed value now only propagates to records the user has not edited, and that the baseline file is what makes that distinction. |
| `CLAUDE.md` | *"Clean Architecture"* ring inventory | Add `domain/catalog_merge.py`, `domain/ports/catalog_baseline_repository.py`, `infra/persistence/catalog_baseline_store.py`; note the contract count stays 7. |
| `AGENTS.md` | Mirror of the CLAUDE.md sections above | The two files are kept in sync by repo convention. |
| `docs/plans/2026-05-23-catalog-force-sync-design.md` | Comparison table + "catalog ids are authoritative" | Add a forward-reference: authority is now **per field**, gated on whether the user edited that field. Do not rewrite history — append a note. |
| `backend/api/bookmarks.py:280-290` | `sync_catalog` docstring | "catalog corrections to lat / lng / name propagate" needs "…to fields the user has not edited locally". |
| `backend/services/bookmarks.py:611-634` | `import_catalog` docstring | The "Existing items with catalog ids are **upserted**" bullet is the sentence that most directly becomes wrong. |
| `backend/services/bookmarks.py:535-550` | `_upsert_items` docstring | "For an UPDATE (id already present) the existing record's mutable fields are overwritten" is no longer true of the catalog path, and `country_code` is no longer among the fields it writes at all. State the `resolver=None` contract and who owns `country_code`. |
| `backend/services/bookmarks.py:391-401` | `update_bookmark` docstring | Add the §6.6 rule: a call whose values all match the stored record writes nothing and leaves `updated_at` alone. |
| `CLAUDE.md` / `AGENTS.md` | *"Bookmark / Route store: CRDT merge semantics"* | Also record that `update_bookmark` no longer re-stamps on a no-op write (§6.6) — it is the kind of invariant a future refactor would otherwise "simplify" away. |

*(Note: `CLAUDE.md` and `AGENTS.md` are currently modified in the working tree by another agent — coordinate rather than overwrite.)*

---

## 13. Open Questions

| # | Question | Recommendation |
|---|---|---|
| **Q1** | **Should Task 10 (F2 — category partial update + live category dialog) be in scope?** F was approved for the bookmark endpoint only, but the category edit dialog is confirmed still frozen-snapshot (`BookmarkList.tsx:186-193`, `App.tsx:1121-1131`) and the endpoint has the identical blank-via-default defect. | **Include it.** The backend half is Task 7's model again, plus a `None`-tolerant `_validate_date_range` (`api/bookmarks.py:21-40`, which would otherwise 500 on an omitted date — see Task 10), plus the dirty-tracking pattern C already established. Leaving it out means renaming a bookmark became safe while renaming a category did not — which will present as a bug later. Task 10 is separable if Ravi disagrees; nothing in Tasks 1-9 depends on it. |
| **Q2** | **Should the conflict report list names, or just a count?** The required UI message ("N entries had both local and catalog changes; kept yours") needs only a count. | **Count only for now** (`conflicts: int`). If Ravi wants to see *which* entries, add `conflict_names: list[str]` later — additive, no migration. A count keeps the toast short and the response shape stable. |
| **Q3** | **Add a pydantic `response_model` to `POST /catalog/sync`?** There is none today (`api/bookmarks.py:279`); the only typed contract is the TS interface, so a key mismatch is silent. | **Yes — and the plan is written that way.** Task 6's first checkbox adds `CatalogSyncResult` and sets `response_model=`; §4.8 and R5 both assume it. It is cheap, it makes the contract visible in OpenAPI, and it turns R5 from a silent class of bug into a startup-time failure. Flagged here only so Ravi can strike it: removing it means deleting that one checkbox and reverting the §4.8 row to "passthrough". |
| **Q4** | **Should a true no-op sync still count as `updated`?** Today `test_bookmark_catalog_sync.py:70` asserts `updated: 3` for an unchanged re-sync, and the toast reports it. | **Keep today's meaning** — `updated` = id collision, regardless of whether a field changed. Redefining it would churn four existing assertions and change what the toast has always said, for no user benefit. `kept_local` and `conflicts` carry the new information. |
| **Q5** | **Should `update_bookmark` skip the write when a `PUT` changes nothing (§6.6)?** This is the only place the plan touches service-layer behavior beyond the approved E1+F scope, and it is what stops a no-change Save from re-stamping the record and out-voting the other Mac's un-synced edit. | **Yes, do it in Task 7.** It is the exact analogue of §4.4, which E1 already relies on, so fixing one and not the other would be arbitrary; the measured blast radius is one production caller and nine test call sites, of which exactly one is affected (`test_bookmark_revert_hazards.py:154`, handled in Task 7 Step 1b); and Task 9 makes the trigger ("open the dialog, press Save, change nothing") send a literal `{}`. The cost is that `PUT` stops being a way to force a re-stamp — no caller wants that today. Strike it and three things drop out together: the service change in Task 7, the two no-op cases in Task 7 Step 1, and both bullets of Task 7 Step 1b's second item; §11's residual list then carries the exposure. Nothing else in the plan changes, and Q6 becomes moot. |
| **Q6** | **If §6.6 ships, how should `test_stale_whole_record_update_outranks_fresher_remote_copy` be repaired?** The guard makes manager A's write in that test a literal no-op, so it must change either way. Change D's own docstring offers two honest options and does not pick one. | **Give manager A one genuine field edit** (Task 7 Step 1b): pass `address="A's own edit"` instead of `address=bm.address`. Both assertions stay byte-identical and still true, and the test becomes a precise pin on §11's residual case 1 — the whole-record-LWW hazard neither E1 nor F closes, and the one thing in this area that would otherwise go unguarded until G. The alternative — flipping it to the guard's outcome (`name == "new"`, A never saved) — is also correct but leaves that hazard with no test at all, so it would need a replacement written from scratch. If Ravi prefers the flip, say so and Task 7 Step 1b takes the second branch. |
| **Q7** | **Should the UI say anything about `country_code` no longer being protected?** E1 deliberately leaves `country_code` (and `timezone` / `city` / `region`) to the geo resolver, and Task 6 stops counting a `country_code`-only divergence in the Refresh confirm dialog. A user who hand-edited a flag will still see it re-derived, now with no dialog mentioning it. | **No extra warning.** The field is a cached derivation of `lat`/`lng`, it has behaved this way since before this plan (`update_bookmark` re-resolves it on every coord change), and there is no UI to edit it directly — the only way to set it by hand is a raw `PUT`. Naming it in the dialog would advertise a field the app does not offer to edit and would make the confirm copy longer for a case that does not arise in normal use. Recorded here so the omission is a decision, not an oversight. |
| **Q8** | **Should the Refresh dialog be able to split its count into "will keep yours" and "will take the catalog's"?** §4.2 settles that it cannot today: the predicate compares ours vs theirs, E1's rule is base-relative, and `catalog_baseline.json` is a local backend file that no endpoint exposes. The two numbers would need a new read-only dry-run on the sync endpoint (`POST /catalog/sync?dry_run=1`, or a sibling `GET /catalog/diff`) returning the per-row split without writing. | **No — ship the base-agnostic copy instead.** The dialog's job is informed consent before an explicit click, and "these {n} differ; your edits are kept, the rest take the catalog value" is complete for that purpose while being true in both branches. A dry-run buys a nicer number at the cost of a new endpoint on a surface §3 deliberately left unchanged, a second code path through the resolver that can drift from the real one, and a round-trip on every dialog open. If the split turns out to matter in use, the honest place for it is the **post-sync toast**, where `kept_local` and `conflicts` already carry the real, backend-computed answer (§4.8) at zero API cost. Recorded so the smaller copy is a decision, not an omission. |
