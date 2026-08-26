# Bookmark text reverts on a two-Mac iCloud setup — root-cause report

Lead investigator synthesis over 6 investigator sweeps + 6 adversarial verifications.
All file:line claims below were re-checked by me directly against the working tree
(commit `e991b1c`, branch `main`) unless explicitly marked *unverified*.

---

## Summary

The store's conflict resolution is **whole-record last-write-wins keyed on a
server-stamped `updated_at`** (`backend/domain/store_merge.py:35-52`). There is no
field-level merge anywhere. Combined with a write API that is **whole-record only**
(`PUT /api/bookmarks/{id}` takes a full `Bookmark`; `name`/`lat`/`lng` have no
defaults — `backend/models/schemas.py:261-264`), this means:

> **Any write that carries a stale copy of a field wins over the fresher copy,
> because the backend unconditionally re-stamps `updated_at = now()` on every
> update (`backend/services/bookmarks.py:419`), regardless of which fields changed.**

That is the whole bug family. The reported symptom — "I edited the text, later it
came back as the old value" — is produced by *any* subsequent write on either Mac
that happens to be holding a pre-edit copy of that record.

The dominant instance needs **no clock skew, no iCloud eviction, and no watcher
misfire**: the Edit dialog freezes a full snapshot of the bookmark at open time and
resubmits every field on Save, including `name`, even when the user only changed the
coordinates.

**Ranked (confidence in parentheses):**

| # | Cause | Confidence |
|---|-------|-----------|
| 1 | Whole-record PUT carrying a stale client snapshot (Edit dialog freeze + cached list) | **high — prime suspect** |
| 2 | Same defect for **categories** (`EditCategoryModal`) — category name is user-visible text too | **high** |
| 3 | Backend re-stamps a stale in-memory record with no client payload — `delete_category(cascade=False)` reparent loop | **medium** |
| 4 | Catalog force-sync (`POST /api/bookmarks/catalog/sync`) wholesale-overwrites `seed-*` records | **medium — real, currently gated on this Mac** |
| 5 | Watcher `current_mtime <= _last_loaded_mtime` skip — *amplifier*, widens #1/#3's stale window | **medium** |
| 6 | `JsonStore.load_or_empty()` never materializes an evicted iCloud placeholder — whole-store clobber | **low, wrong symptom shape** |
| 7 | Wall-clock skew between the two Macs — no defense exists, but no evidence it fires | **low / theoretical** |

**Corrections I had to make to the verifiers' work** (they erred in both directions):

- `_union_by_id` is at `backend/domain/store_merge.py:41-52` (`_newer` at `:35-38`,
  the replace check at `:49-50`). Several findings cited `:39-49` — wrong.
- `Bookmark.name/lat/lng` are **required** (`backend/models/schemas.py:262-264`),
  but `address`/`category_id`/`country_code` default to `""`. Since
  `update_bookmark`'s guard is `value is not None`
  (`backend/services/bookmarks.py:409`), an **omitted `address` arrives as `""` and
  blanks the stored address** — it is not "ignored". Relevant if 描述 means `address`.
- The "prime suspect" label was attached in one sweep to `catalog-sync`. Live data
  says the trigger button is **currently disabled on this Mac** (`catalogNewCount == 0`,
  measured — see Diagnostics), so it is demoted to #4.
- `whole-record-move-backend-stale-store` was correctly refuted: `useBookmarks.moveBookmarks`
  is exported at `frontend/src/hooks/useBookmarks.ts:82,140` with **zero component
  consumers** (grep confirmed) — `POST /api/bookmarks/move` is dead in the UI. But the
  *same class* is live via `delete_category` (cause #3), which the refutation missed.

---

## Ranked causes

### 1. Whole-record PUT carrying a stale client snapshot — **PRIME SUSPECT**

#### Mechanism

`EditBookmarkDialog` and `App.onBookmarkEdit` both reconstruct the *entire* Bookmark
from client-side state and PUT it. Two independent sources of staleness feed it:

- **(a) Frozen dialog snapshot (no race required).** `BookmarkList.tsx:914-918`
  copies the bookmark into four pieces of parent state on open
  (`setEditDialog(bm); setEditDialogName(bm.name); …`). `BookmarkList.tsx` contains
  **zero `useEffect` hooks** (grep verified), and `setEditDialog` is written at only
  two places (`:915`, `:958`). Nothing re-syncs the dialog to the live `bookmarks`
  prop. A `bookmarks_changed` WS refresh updates `bm.bookmarks` but cannot reach the
  frozen snapshot. On Save, `EditBookmarkDialog.tsx:77-82` emits
  `{...bookmark, name: name.trim(), lat, lng}` — `name` is **always** present, never
  omitted. The window is *however long the dialog is open*.
- **(b) Stale cached list.** `App.tsx:1088` builds `patch = {...orig}` from
  `bm.bookmarks`. If the WS broadcast was lost (no server replay —
  `backend/main.py:1273-1280`, and `App.tsx:203-216`'s own comment says so) or iCloud
  hasn't propagated yet, `orig` is pre-edit for every field the caller doesn't override.

Backend then applies it wholesale and re-stamps:
`backend/api/bookmarks.py:92-105` forwards all six mutable fields verbatim →
`backend/services/bookmarks.py:407-412` `setattr`s each non-`None` one →
`backend/services/bookmarks.py:419` `bm.updated_at = _now_iso()` **unconditionally**,
even for a no-op save. The reverted value therefore carries the *newest* timestamp,
so it is not a merge loser — it wins `_union_by_id` on both Macs, durably.

#### Evidence

- `frontend/src/components/BookmarkList.tsx:914-918` — snapshot frozen at open
- `frontend/src/components/BookmarkList.tsx:946-959` — dialog wired to that state; no re-sync
- `frontend/src/components/EditBookmarkDialog.tsx:76-82` — `{...bookmark, name: name.trim(), …}`; the comment "Backend PUT requires the full Bookmark shape" documents the forced round-trip
- `frontend/src/App.tsx:1087-1097` — `patch = orig ? {...orig} : {...data, id}`, then `if (data.name != null) patch.name = data.name` (the clobber line is `:1090`)
- `frontend/src/hooks/useBookmarks.ts:73-79` — PUTs `data` verbatim
- `backend/api/bookmarks.py:92-105` — all six fields forwarded
- `backend/services/bookmarks.py:407` (`allowed` set), `:409` (`value is not None`), `:419` (unconditional stamp)
- `backend/models/schemas.py:262-264` — `name/lat/lng` required → partial PUT impossible by design
- `backend/domain/store_merge.py:35-38`, `:41-52` — whole-record strict-greater LWW, no field merge
- `backend/infra/persistence/json_store.py:63-67` — `merge_stores(store, load_or_empty())` then write
- `frontend/src/components/EditBookmarkDialog.test.tsx:72-77` — an existing test **pins** the always-send-full-shape behavior (confirmatory, not refuting)

#### Two-machine scenario

1. **10:00 — Mac A.** Right-click bookmark *X* → Edit. Dialog opens with `name = "舊名"`.
   Ravi starts fiddling with the coordinates, then walks away / closes the lid.
2. **10:05 — Mac B.** Renames *X* to `"新名"`. `update_bookmark` stamps
   `updated_at = 10:05` (`bookmarks.py:419`) and writes to the iCloud file.
3. **10:07 — iCloud converges.** Mac A's watcher fires, `_reconcile_from_disk`
   (`bookmarks.py:156-169`) merges `"新名"` into Mac A's store, and
   `main.py:1273-1280` broadcasts `bookmarks_changed`. Mac A's list correctly shows `"新名"`.
   **Mac A's still-open dialog state does not change.**
4. **10:10 — Mac A.** Ravi finishes the coordinate tweak and clicks Save.
   `EditBookmarkDialog` submits `{...snapshot, name: "舊名", lat, lng}`.
   `App.tsx:1090` overwrites the fresh `orig.name` with `"舊名"`.
5. Backend PUT sets `name = "舊名"` and stamps `updated_at = 10:10`.
   `json_store.save` merges: `10:10 > 10:05`, so the stale record wins.
6. iCloud carries the file to Mac B. `_union_by_id` picks the 10:10 copy.
   **Both Macs now show `"舊名"`. The rename is gone, durably.**

Variant (b), same outcome without an open dialog: Mac A's WS dropped at 10:00
(backend restart, sleep/wake). Mac B renames at 10:05. Mac A's backend reconciles but
the broadcast is lost and never replayed, so the React list still shows `"舊名"`.
Any edit Ravi makes to *X* at 10:10 — even a coordinate nudge — re-sends `"舊名"`.

#### Proposed fix (smallest correct change)

Make the update endpoint **field-scoped instead of whole-record**, so a client that
did not intend to touch `name` cannot overwrite it.

- **File:** `backend/api/bookmarks.py:92-105` (+ a new `BookmarkUpdate` model in
  `backend/models/schemas.py` with every field `| None = None`).
- **Change:** accept `BookmarkUpdate`; pass through **only keys the client actually
  sent** (`bookmark.model_dump(exclude_unset=True)`) into `update_bookmark(**fields)`.
  `update_bookmark`'s `allowed`/`is not None` loop (`bookmarks.py:407-412`) already
  handles a partial kwargs set correctly — no service change needed.
  This is backward-compatible with the current frontend (a full body still works,
  which is why the frontend fix below is a *separate* second step).
- **Frontend follow-up (same defect, other half):** `EditBookmarkDialog.tsx:77-82`
  should send only `{name, lat, lng}` and `App.tsx:1088` should stop spreading `orig`
  — send `data` alone once the backend accepts partials.

**Characterization test (must FAIL before, PASS after)**
`backend/tests/test_bookmark_partial_update.py`:

```
def test_put_without_name_does_not_overwrite_a_newer_name(client, bm):
    # bookmark X exists with name "new" and updated_at T1 (simulating a
    # remote rename already reconciled into this manager)
    # client PUTs only {"lat": 1.0, "lng": 2.0} for X
    # ASSERT: X.name == "new"   <-- fails today (becomes "" / the stale value)
    # ASSERT: X.updated_at > T1 (the coord edit still stamps)
```

Plus a merge-level characterization test proving the *outcome*, which is the one that
really pins the bug:
`backend/tests/test_bookmark_stale_put_revert.py` — two `BookmarkManager`s over one
temp file (the existing two-manager harness in
`backend/tests/test_bookmark_concurrency.py:41-101` is the template; it only covers
distinct ids today, which is exactly why this bug is uncaught):

```
mgr_a, mgr_b share tmp bookmarks.json, both hold X{name:"old"}
mgr_b.update_bookmark(X, name="new")                 # T1
mgr_a.update_bookmark(X, name="old", lat=1.0)        # T2 > T1, stale whole-record PUT
mgr_a._reconcile_from_disk(); mgr_b._reconcile_from_disk()
ASSERT both see name == "new"                        # FAILS today
```

---

### 2. The identical defect for **categories** (`EditCategoryModal`)

#### Mechanism
Exact structural sibling of #1, and a category name is user-visible text a user could
call 描述. `BookmarkList.tsx:175-187` freezes `newName`/`color`/`start`/`end` at open;
`EditCategoryModal.tsx:54-64` always sends all four; `App.tsx:1124-1128` forwards them
unconditionally; `backend/api/bookmarks.py:139-151` forwards verbatim;
`backend/services/bookmarks.py:286-297` re-stamps `cat.updated_at = _now_iso()` at `:297`.

Two extra sharp edges specific to categories:
- `BookmarkCategory.start_date`/`end_date` default to `""`
  (`backend/models/schemas.py:253-255`), so an omitted date **clears** the field.
- `App.tsx:1119-1121` resolves the category by its **old name**
  (`bm.categories.find(c => c.name === oldName)`) and silently `return`s if not found —
  so if the remote change *was* a category rename, the user's edit is dropped entirely
  with no error. Different failure (lost edit, not revert) but same root.

#### Two-machine scenario
Mac A opens Edit-Category "Events" at 10:00. Mac B renames it to "Events 2026" at 10:05.
Mac A adjusts only the end-date and saves at 10:10 → the old name is re-sent with a
fresh stamp and wins. Mac B's rename disappears.

#### Fix + test
Same shape as #1, one layer up: partial-update model on `PUT /api/bookmarks/categories/{cat_id}`
(`backend/api/bookmarks.py:139-151`).
Test: `test_put_category_without_name_does_not_overwrite_a_newer_name` — PUT only
`{start_date: ...}` and assert `name` and `end_date` are untouched. Fails today.

---

### 3. Backend re-stamps a stale in-memory record with **no client payload**

#### Mechanism
`delete_category(cat_id, cascade=False)` reparents every bookmark of the deleted
category to `"default"` and stamps `bm.updated_at = now` on **the local in-memory
copy** (`backend/services/bookmarks.py:333-338`, `now` taken at `:322`). Whatever
`name`/`address` that local copy holds is republished with a winning timestamp. This
needs no stale *frontend* cache at all — only a stale *backend* store, which cause #5
can sustain for a long time. It is reachable from real UI
(`frontend/src/hooks/useBookmarks.ts:96-118`).

`move_bookmarks` (`backend/services/bookmarks.py:466-477`, stamp at `:476`) is the
same shape and is a latent duplicate — currently unreachable from the UI (verified:
`moveBookmarks` has no component consumer), so it is not the live path today.

#### Two-machine scenario
1. 10:00 Mac B renames bookmark *X* (in category "Trips") → `updated_at = 10:00`.
2. 10:01 iCloud delivers the file to Mac A, but Mac A's watcher skips it
   (cause #5, or the app was asleep). Mac A's in-memory *X* still says `"舊名"`.
3. 10:05 Mac A deletes the category "Trips" **without cascade**. Every bookmark in it,
   including *X*, is reparented and stamped `10:05` — carrying `"舊名"`.
4. `_save` merges (`10:05 > 10:00`) and writes. iCloud converges. Rename gone —
   and this reverts **many records in one action**, which matches "sometimes a bunch
   of things look wrong" better than a single-record path.

#### Fix + test
- **File:** `backend/services/bookmarks.py`, `delete_category` (and `move_bookmarks`
  for symmetry).
- **Change:** call `self._reconcile_from_disk()` at the top of any bulk mutator that
  re-stamps records it did not receive from the client (it already runs under
  `_store_lock` via `_save`; note `_watcher_tick:220` holds the same non-reentrant
  lock, so reconcile must be called *before* taking it, or the private
  `self._repo`/merge path used directly). Smallest correct version: reconcile-before-mutate
  in `delete_category`.
- **Test:** `backend/tests/test_bookmark_reparent_does_not_revert.py` — two managers
  over one temp file; `mgr_b` renames X; `mgr_a` (deliberately not reconciled) deletes
  X's category with `cascade=False`; assert X's name is still the new one after both
  reconcile. Fails today.

---

### 4. Catalog force-sync wholesale-overwrites `seed-*` records

#### Mechanism
`POST /api/bookmarks/catalog/sync` (`backend/api/bookmarks.py:278-298`) →
`import_catalog` (`backend/services/bookmarks.py:610`). It stamps **one shared `now`**
across every incoming item (`force_seed_items` at `:645-646`), then `_upsert_items`'
update branch overwrites `old.name / lat / lng / address / category_id / country_code /
updated_at` for any id already present, with **no "locally edited since" check**
(`backend/services/bookmarks.py:558-567`). Categories get the same treatment inline at
`:650-659`. This is deliberate and documented (`:611-627`) and pinned by a passing test
(`backend/tests/test_bookmark_catalog_sync.py:93-102` asserts the **name** overwrite).

**Live measurement on this Mac (read-only, see Diagnostics):** 139 of the 140 `seed-*`
bookmarks in the iCloud store share one identical stamp
`2026-05-24T02:53:56.751078+00:00` — the batch-stamp fingerprint of a past catalog
force-sync. So this path **has been exercised**. Currently `catalogNewCount == 0`, so
the Refresh button is disabled (`frontend/src/components/BookmarkList.tsx:434-441`,
count at `frontend/src/hooks/useCatalog.ts:52-56`) and it cannot fire *on this Mac,
on this build*. But 1 seed bookmark's name and 23 seed bookmarks' `category_id`
currently diverge from the bundled catalog — all of those are queued to be reverted by
the next Refresh click. Every one of the 140 catalog entries carries `address: ""`, so
a Refresh also **blanks** any user-typed address on a seeded bookmark.

#### Two-machine scenario (the variant that needs no manual rename)
The two Macs run **different LocWarp builds** whose bundled `backend/static/catalog.json`
disagree for a stable id — this has happened: commit `dd56444` (2026-05-09,
"data(catalog): simplify bookmark names") changed 8 names with ids untouched.
1. Mac A (newer build) is on the current catalog: *X* reads `"新名"`.
2. Mac B (older build) has a seed id missing locally, so its Refresh button enables.
   Ravi clicks it to pick up the new events.
3. `import_catalog` force-stamps Mac B's **older** catalog name with `now()`.
4. iCloud converges; the fresh stamp wins on Mac A. *X* spontaneously reverts on the
   machine that did nothing. Matches "comes back as the OLD value later" precisely.

#### Fix + test
- **File:** `backend/services/bookmarks.py`, `_upsert_items` update branch (`:558-567`).
- **Change:** in the update branch, only overwrite a field when the *local* record's
  `updated_at` is not newer than the catalog compile time — i.e. add a
  `respect_local_edits: bool` parameter, and when set, skip `old.name/address` if
  `old.updated_at > catalog._meta.compiled_at`. Keep the coordinate correction and the
  tombstone-beating stamp (both are the feature's point).
- **Test:** `backend/tests/test_bookmark_catalog_sync.py::test_catalog_sync_preserves_a_locally_renamed_seed`
  — seed the catalog, rename a `seed-*` bookmark, run `import_catalog`, assert the
  rename survives and the coordinates still get corrected. Fails today (the existing
  test at `:93-102` asserts the opposite and will need to be re-scoped to a
  non-locally-edited record).

---

### 5. Watcher `current_mtime <= _last_loaded_mtime` skip — **amplifier**

`backend/services/bookmarks.py:212` is the **only** discriminator between a self-echo
and a real external write, and `_watcher_tick` is the **only** in-session reconcile
trigger (grep for `_reconcile_from_disk`: callers are `:222` and tests only; there is
no periodic poll and `GET /api/bookmarks` does not reconcile). `_record_disk_mtime`
(`:171-178`) is called after every load **and every save** (`:154`). So if iCloud
materializes Mac A's earlier edit **after** Mac B has saved something of its own,
`T_incoming <= T_last_saved` and the whole external change is silently dropped —
no merge, no `bookmarks_changed` broadcast, stale UI *and* stale backend store.
`backend/services/route_store.py:156` is byte-identical for routes.

Two corrections to the sweeps: it is **not permanent** —
`backend/services/bookmarks.py:153` (`self.store = self._repo.save(self.store)`) folds
the disk copy back into memory on the next local write of any kind, so the staleness
survives only for the one record that write itself re-stamps. And the guard is
deliberate and test-pinned in the skip direction
(`backend/tests/test_bookmark_concurrency.py:169-176`; `:65,:159` must force
`mtime + 10` to get any reconcile at all).

**Why it matters here:** it is what turns causes #1(b) and #3 from a 0.5s race into a
window that lasts until the next local write. It does not revert an edit on its own.

**Fix:** replace the mtime scalar with a content fingerprint (hash of the last
payload this process wrote) so a non-monotonic external mtime still reconciles.
**Test:** `test_watcher_reconciles_when_external_mtime_is_not_newer` — write a differing
payload externally with `os.utime(path, mtime_recorded - 1)`, tick, assert the callback
fires and the store converged. Fails today.
**Unverified premise:** that macOS iCloud materialization actually produces a
non-monotonic local mtime. Nothing in the repo establishes it; see Open questions.

---

### 6. `load_or_empty()` never materializes an evicted iCloud placeholder

`backend/infra/persistence/json_store.py:38-40` — `load()` calls
`materialize_if_placeholder`. `:53-60` — `load_or_empty()` does **not**, and `save()`
at `:63-67` merges against `load_or_empty()`. If iCloud has evicted `bookmarks.json`
to a `.bookmarks.json.icloud` placeholder at save time, the canonical path does not
exist (`backend/services/cloud_sync.py:43-64`), the merge base is an **empty store**,
and `merge_stores(local, empty) == local` — the whole file is rewritten from this
Mac's possibly-stale memory, bypassing per-item LWW entirely.
`_reconcile_from_disk` has the same blind spot but fails safe (early return at
`bookmarks.py:161-168`).

Related: `backend/services/json_safe.py:76-82` **unlinks** a zero-byte file before
returning `None` — on an iCloud file caught mid-download at 0 bytes this deletes the
shared cloud file, which is then recreated from the local store.

**Why ranked low for *this* report:** the failure mode is a wholesale store
replacement (many records at once), not "one text field shows its old value". Fix it
anyway — add `materialize_if_placeholder(self.path())` to `load_or_empty()`.
Test: `test_save_does_not_clobber_when_store_file_is_an_icloud_placeholder`.
**Live check:** no `.icloud` placeholders and no conflict copies currently exist in
`~/Library/Mobile Documents/com~apple~CloudDocs/LocWarp/` (measured).

---

### 7. Wall-clock skew — no defense exists, no evidence it fires

`_now_iso()` is a bare `datetime.now(timezone.utc).isoformat()`
(`backend/services/bookmarks.py:29-30`; identical in `route_store.py:36-37`,
`route_distance_service.py:25-26`, `main.py:1071`). `_newer` is a bare lexicographic
`>` (`store_merge.py:35-38`). Grep for a monotonic clamp / HLC / NTP check across
`services/`, `domain/`, `infra/`: nothing. The design doc names this as the one
accepted weakness (`docs/plans/2026-05-14-icloud-sync-conflict-resolution.md:69,:100`,
with `:943` proposing an HLC as the hardening).

One sweep's stated mechanism was correctly refuted — `_save` stamps nothing
(`bookmarks.py:146-154` → `json_store.py:63-67`), so an unrelated write on Mac B does
**not** re-stamp Mac B's stale copy of a different bookmark. The residual real risk is
narrow: if the *same* bookmark's last write on the ahead-clock Mac is later-stamped
than the other Mac's genuinely-newer edit, the older content wins. On two NTP-synced
Macs that needs gross skew. **Do not promote without an actual measured clock offset.**

Also confirmed clean: the live store has exactly **one** timestamp shape
(`+00:00` with microseconds) apart from empty strings — no `Z` suffix, no naive-local,
no non-UTC offset. `backend/services/bookmark_export.py:20` uses a different `Z`-suffixed
shape but it only ever reaches export metadata, never a stored `updated_at`.

---

## Refuted, and why

| Hypothesis | Verdict |
|---|---|
| `bootstrap-migrate-tie-keeps-local` (cloud-sync enable/disable tie order) | **Refuted.** The tie branch fires only on byte-equal `updated_at`. Every mutation that can change `name`/`address` stamps a fresh microsecond-precision `_now_iso()` (`bookmarks.py:297,338,419,476,566,658`), so two copies with identical stamps cannot disagree about text. Also one-shot behind an explicit toggle, and `cloud_sync.py:141-149` short-circuits on byte-equal files. |
| `whole-record-move-backend-stale-store` (via `POST /api/bookmarks/move`) | **Refuted as stated** — the route is unreachable from the UI: `moveBookmarks` is defined and exported (`frontend/src/hooks/useBookmarks.ts:82,140`) with no component consumer (grep verified); the only category-move UI (`BookmarkList.tsx:941`) goes through `onBookmarkEdit` → PUT, i.e. cause #1. The *class* survives via `delete_category` — cause #3. |
| `import-json-stale-file-overwrite` (re-importing an old export) | **Refuted.** `backend/services/bookmarks.py:598` filters out every id already present before `_upsert_items`, so the overwrite branch is unreachable from `import_json`. `_import_single_category` re-ids collisions (`bookmark_import.py:79-81`) and `_import_geojson` always mints a fresh uuid (`:124-126`). Worst case is duplicates, not a revert. |
| `merge-tie-break-order-dependent` (commutativity violation) | **Refuted as a revert path.** Real docstring defect (`store_merge.py:8` and `:44-46` claim byte-identical results; `:49-50` is a strict `>`, so a tie keeps the left/first-seen copy). But every live caller passes the **local** store as `left` (`json_store.py:66`, `bookmarks.py:169`, `route_store.py:162`, `sync_merge.py:69,87`), so a tie always *preserves* local — the opposite of a revert. The only reachable tie is `"" == ""`, i.e. two never-edited legacy records. Pinned as intended by `backend/tests/test_sync_merge.py:61-78`. |
| `contextmenu-edit-not-remounted-per-open` (missing `key` on `EditBookmarkDialog`) | **Refuted.** All four state values are re-seeded on every open (`BookmarkList.tsx:914-918`), and `useRawCoordText.ts:26-34` has an explicit reopen guard. Decisively: the stale value lives in **the parent's** state (`BookmarkList.tsx:195`), so adding a `key` to the child would not fix cause #1 at all. |
| `legacy-empty-updated-at-format-gap` | **Not refuted, but not a revert.** `""` always sorts oldest (`store_merge.py:35-38`, pinned by `test_store_merge.py:98-102`), so a legacy record can only ever *lose*. It is a data-loss-on-future-tombstone risk. Live: 5 bookmarks and 2 categories carry `""` (measured). |
| `clock-skew-lww-reversion` **as stated** | **Refuted** (the "any unrelated write re-stamps the stale copy" step is false — `_save` stamps nothing). Residual narrow form kept as cause #7. |

---

## Diagnostic commands — run these now (all strictly read-only, no names printed)

Copy-paste as-is. They only read; nothing is written, moved, or deleted. Output is
counts and ids, never bookmark names or addresses.

**D0 — locate the stores and check for iCloud damage (placeholders / conflict copies):**

```bash
python3 -c "import json,os;p=os.path.expanduser('~/.locwarp/settings.json');print('sync_folder =', (json.load(open(p)) if os.path.exists(p) else {}).get('sync_folder'))"
SF="$(python3 -c "import json,os;p=os.path.expanduser('~/.locwarp/settings.json');print((json.load(open(p)) if os.path.exists(p) else {}).get('sync_folder') or os.path.expanduser('~/.locwarp'))")"
ls -la "$SF"
find "$SF" \( -name '*.icloud' -o -name '*conflict*' -o -name '* 2.json' \) -print
```

Fingerprint of cause #6: any `.icloud` placeholder, or a `bookmarks 2.json`.
(On this Mac, right now: **none** — measured.)

**D1 — timestamp shapes, empty stamps, future stamps, tombstone risk:**

```bash
SF="$(python3 -c "import json,os;p=os.path.expanduser('~/.locwarp/settings.json');print((json.load(open(p)) if os.path.exists(p) else {}).get('sync_folder') or os.path.expanduser('~/.locwarp'))")" \
python3 - <<'PY'
import json,os,re,collections,datetime
sf=os.environ["SF"]; p=os.path.join(sf,"bookmarks.json")
d=json.load(open(p))
b=d.get("bookmarks",[]); c=d.get("categories",[]); t=d.get("tombstones",[])
print("counts: bookmarks",len(b),"categories",len(c),"tombstones",len(t))
def shape(s):
    if not s: return "EMPTY"
    if s.endswith("Z"): return "Z-SUFFIX(!)"
    if s.endswith("+00:00"): return "utc-us" if "." in s else "utc-nofrac"
    return "OTHER(!)"
print("bookmark stamp shapes:",dict(collections.Counter(shape(x.get('updated_at','')) for x in b)))
print("category stamp shapes:",dict(collections.Counter(shape(x.get('updated_at','')) for x in c)))
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
print("FUTURE-dated bookmark stamps (clock-skew fingerprint, cause #7):",
      [x['id'] for x in b if (x.get('updated_at') or '')>now][:10])
tomb={x['id']:x.get('deleted_at','') for x in t}
print("alive items a tombstone will kill on the next merge:",
      [x['id'] for x in b if x['id'] in tomb and (x.get('updated_at') or '')<=tomb[x['id']]][:10])
PY
```

Fingerprints: `Z-SUFFIX(!)` / `OTHER(!)` would mean a foreign writer (none exists
today). Any **future-dated** stamp is direct evidence of cause #7 on the *other* Mac.

**D2 — catalog force-sync fingerprint (cause #4). Run from the repo root:**

```bash
cd /Users/raviwu/personal/locwarp
SF="$(python3 -c "import json,os;p=os.path.expanduser('~/.locwarp/settings.json');print((json.load(open(p)) if os.path.exists(p) else {}).get('sync_folder') or os.path.expanduser('~/.locwarp'))")" \
python3 - <<'PY'
import json,os,collections
live=json.load(open(os.path.join(os.environ["SF"],"bookmarks.json")))
cat=json.load(open("backend/static/catalog.json"))
cb={x["id"]:x for x in cat.get("bookmarks",[])}
seeds=[x for x in live.get("bookmarks",[]) if x["id"] in cb]
print("seed-* bookmarks present:",len(seeds),"of",len(cb))
cl=collections.Counter(x.get("updated_at","") for x in seeds).most_common(3)
print("batch-stamp clusters (a big cluster == a past catalog force-sync):",
      [(k[:26],v) for k,v in cl])
dn=[x["id"] for x in seeds if x.get("name")!=cb[x["id"]].get("name")]
da=[x["id"] for x in seeds if (x.get("address") or "")!=(cb[x["id"]].get("address") or "")]
dc=[x["id"] for x in seeds if x.get("category_id")!=cb[x["id"]].get("category_id")]
print("seed records a Refresh click WOULD revert -> name:",len(dn),dn[:5])
print("                                    address:",len(da),da[:5])
print("                                category_id:",len(dc),dc[:5])
existing={x["id"] for x in live.get("bookmarks",[])}
n=sum(1 for i in cb if i not in existing)
print("catalogNewCount =",n,"-> Refresh button is", "ENABLED (cause #4 is armed)" if n else "disabled")
PY
```

Measured on this Mac just now: 140/140 seeds present; **139 share the single stamp
`2026-05-24T02:53:56…`** (a past force-sync); `name` diverges on **1** record and
`category_id` on **23**; `catalogNewCount = 0`, so the button is disabled *here*.
**Run this on the second Mac too** — if its `catalogNewCount > 0`, cause #4 is armed there.

**D3 — look for an actual revert in the rotating backups (ids only, no names):**

```bash
python3 - <<'PY'
import json,glob,os,collections
fs=sorted(glob.glob(os.path.expanduser("~/.locwarp/backups/locwarp-backup-*.json")))
print("backups:",len(fs), os.path.basename(fs[0]) if fs else "-","->",os.path.basename(fs[-1]) if fs else "-")
hist=collections.defaultdict(list)
for f in fs:
    try: d=json.load(open(f))
    except Exception: continue
    src=d.get("bookmarks"); bms=src.get("bookmarks",[]) if isinstance(src,dict) else (src or [])
    for b in bms: hist[b["id"]].append((b.get("name",""),b.get("updated_at","")))
flip=[];back=[]
for i,seq in hist.items():
    ns=[n for n,_ in seq]; runs=[]
    for n in ns:
        if not runs or runs[-1]!=n: runs.append(n)
    if len(runs)>=3 and runs[0]==runs[2]: flip.append(i)
    ts=[t for _,t in seq]
    if any(ts[k+1]<ts[k] for k in range(len(ts)-1)): back.append(i)
print("ids whose NAME went A->B->A (a real revert):",len(flip),flip[:10])
print("ids whose updated_at moved BACKWARD (merge picked an older copy):",len(back),back[:10])
PY
```

Measured now: 69 backups spanning **2026-08-23 → 2026-08-26 only** (72 h retention),
**0 flips, 0 backward stamps** — i.e. no revert occurred inside the retained window.
This command is the one to re-run the moment Ravi notices the next revert; it will
name the offending id directly. Consider raising `BACKUP_RETENTION_HOURS` above 72
while hunting this.

**D4 — the one thing the store files cannot tell you: clock offset between the Macs.**
Run on **both** Macs and compare:

```bash
sntp -d time.apple.com 2>/dev/null | tail -3 ; date -u +%FT%T.%6NZ ; sudo systemsetup -getusingnetworktime 2>/dev/null
```

(The `sntp` line is read-only; `systemsetup -get…` is a read, but it prompts for sudo —
skip it if you'd rather not.) An offset above a few seconds promotes cause #7.

---

## Open questions / what remains UNVERIFIED

1. **Which field actually reverted.** "描述" maps to no schema field. If it is `name`,
   causes #1–#4 all apply. If it is `address`, note two extra facts: the Edit dialog has
   **no address input at all** (it always echoes the snapshot's address back —
   `EditBookmarkDialog.tsx:77-82`), and all 140 catalog entries carry `address: ""`
   (measured), so a catalog Refresh **blanks** it. If it is the geo subtitle
   (city/region/timezone), a different, weaker path applies: `enrich_bookmark`
   deliberately does not stamp `updated_at` (`bookmarks.py:66-67`), so enrichment is
   invisible to LWW and non-convergent between the two Macs.
   **Settles it:** ask Ravi which text he edited, and on which screen.
2. **Whether an open Edit dialog was involved.** Cause #1(a) requires only that the
   dialog was open across the remote change. **Settles it:** ask whether the revert
   followed a session where he had the edit dialog open for a while (lid closed,
   app left running).
3. **Whether iCloud materialization can produce a non-monotonic local mtime** (cause #5's
   sole premise). Nothing in the repo establishes it and I could not test it (read-only,
   app must not be run). **Settles it:** on Mac B, `stat -f '%m %N'` the iCloud
   `bookmarks.json` before and after a known Mac-A write lands, and compare with the
   `_last_loaded_mtime` the backend logged.
4. **Whether the two Macs run the same build** (cause #4's two-build variant).
   **Settles it:** compare `git rev-parse HEAD` and the `_meta.compiled_at` inside
   `backend/static/catalog.json` on both machines, plus D2's `catalogNewCount`.
5. **Actual clock offset between the two Macs** (cause #7). Unmeasurable from one
   machine. **Settles it:** D4 on both.
6. **Real-world width of the race windows.** Not measured — no app run, no test suite
   run, per constraints. All mechanisms above are verified in code; their *frequency* is
   inferred, not observed. The `sometimes` in the report is consistent with every one of
   causes #1–#5.
7. **The 5 bookmarks / 2 categories with `updated_at = ""`** are consistent with legacy
   pre-CRDT records (the field was added in `03acc56`, 2026-05-14) but I did not trace
   their provenance. They are a latent data-loss risk (any real-timestamp tombstone for
   those ids wins), not a revert vector. Currently 0 are tombstone-suppressed (measured).
