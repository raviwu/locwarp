# Bookmark Edit Durability — G (per-field merge in the synced store)

Status: **DRAFT — awaiting Ravi's approval.** No code written.
Predecessor: `docs/superpowers/plans/2026-08-26-bookmark-edit-durability-e1-f.md` (E1 + F, shipped `e991b1c..bf4d606`).
Root cause report: `docs/superpowers/specs/2026-08-26-bookmark-revert-root-cause.md`.

---

## 1. Problem Statement

E1 and F closed both *confirmed* revert triggers, but both work **upstream** of the
merge. The merge itself is unchanged, and it is the design root cause:

| Location | Behaviour |
|---|---|
| `backend/domain/store_merge.py:41-52` (`_union_by_id`) | On an id collision, keeps the record with the newer `updated_at` **string** and discards the other **whole**. No field-level merge exists. |
| `backend/services/bookmarks.py:487` (`update_bookmark`) | Re-stamps `bm.updated_at = _now_iso()` for the whole record whenever *any* field changes. |

Together these produce the residual hazard recorded in the E1/F plan §11.1 and
pinned by `test_bookmark_revert_hazards.py::test_stale_whole_record_update_outranks_fresher_remote_copy`:

> Mac 1 renames a bookmark. Mac 2, which has not yet seen that rename, changes
> the same bookmark's address. Whichever save lands second replaces the record
> whole, and the other machine's field is silently lost.

Neither E1 (catalog-sync only) nor F (stale request *body* only) can reach this:
each machine legitimately edited its own field, and the staleness lives in the
peer's **in-memory record**, not in a request body.

### 1.1 Which write paths actually arm this

Surveyed every `updated_at` writer under `services/`. The ones that re-stamp a
whole record on a partial edit — i.e. the live triggers:

| Path | Fields it really changes | Armed? |
|---|---|---|
| `update_bookmark` (`:464-490`) | any subset of `name, lat, lng, address, category_id, last_used_at, country_code` | **yes** |
| `update_category` (`:344`) | any subset of `name, color, start_date, end_date` | **yes** |
| `move_bookmarks` (`:533-548`) | `category_id` (+ coordinate rounding) | **yes** — drag-to-category re-stamps the whole record |
| `import_catalog` resolver (`:659-670`) | only fields taken from theirs | **yes**, but narrowed by E1 |
| `RouteManager.update_category` (`route_store.py:224`) | any subset | **yes**, and still unconditional (no F-style no-op guard) |
| `enrich_all` (`:552-579`) | geo fields | **no** — deliberately does not stamp; values are deterministic from `(lat, lng)` so every device converges |
| `create_bookmark` (`:427`) | whole record is new | n/a |

Two things worth stating because they bound the scope:

- **`last_used_at` is not a live trigger.** It is in `update_bookmark`'s allowed
  set, but no frontend caller sends it (`grep last_used_at frontend/src` — read
  only, for sorting). It is written once at create. So "teleporting to a
  bookmark reverts a peer's rename" does **not** happen today. It would the
  moment a caller starts sending it, which is an argument for including it in
  the design rather than excluding it.
- **`enrich_all` is already the model answer** for a field that must not
  manufacture conflicts: deterministic value, no stamp. G must not regress it.

---

## 2. Scope

**In:** `BookmarkStore` — `Bookmark` and `BookmarkCategory` field-level merge.
**In:** `RouteManager.update_category`'s missing no-op guard (a prerequisite, see §7 Task 0).
**Decision pending (Q1):** `RouteStore` — same bug class, larger surface.

**Out:** any change to tombstone semantics, the CRDT's commutativity/idempotence
contract, the HTTP/WS surface, or the catalog three-way merge (E1 stays exactly
as shipped and keeps its own local baseline).

### 2.1 Hard constraints carried over from E1/F

1. **No external HTTP / WS / IPC change.** `exclude_unset` / `exclude_none`
   serialization stays.
2. **Backward- AND forward-compatible on disk.** A build that predates G must be
   able to read a G-written file, and its write-back must degrade to *today's*
   behaviour — never to something worse.
3. **The merge stays commutative and idempotent.** `merge_stores(a, b) ==
   merge_stores(b, a)` and `merge_stores(a, a) == a`. This property is what makes
   "it does not matter which device wrote the file last" true, and half the
   store design leans on it.
4. Full backend pytest green after every commit. Baseline to pin before starting:
   `cd backend && .venv/bin/python -m pytest --collect-only -q` (**1266** as of `df29ba6`).

---

## 3. Approaches surveyed

### 3.1 Per-field LWW-Register (an LWW-Map) — **recommended**

Each record carries a map of `field -> ISO timestamp`. The merge resolves each
field independently, taking the side whose stamp for that field is newer.

This is the standard CRDT map: Riak's `map` type composes LWW-registers exactly
this way, Redis Enterprise CRDBs do the same for hash fields, and it is what
most mobile last-write-wins sync layers (Firebase RTDB per-path, Couchbase
Mobile per-attribute plugins) reduce to.

- **+** Preserves commutativity/idempotence exactly — the merge stays a pure
  function of the two files, with no hidden machine-local state.
- **+** Converges regardless of sync order, missing local files, a wiped Mac, or
  a restore from backup. Nothing to bootstrap.
- **+** Degrades to today's behaviour, precisely, when the map is absent.
- **−** Changes the on-disk shape of `bookmarks.json` (additively).
- **−** File growth: see §5.4.

### 3.2 Machine-local base snapshot + three-way merge (git's model)

Extend E1's `catalog_baseline.json` idea to *all* edits: each machine keeps a
local snapshot of "the store as I last saw it", and on merge computes
ours-diff vs theirs-diff against it, taking disjoint changes from both sides.

- **+** **Zero on-disk format change** — the exact reason G was originally
  deferred would evaporate.
- **+** The codebase already proved the pattern in E1, and
  `domain/catalog_merge.resolve_record` is reusable nearly as-is.
- **−** **Breaks constraint 3.** The merge stops being a pure function of the two
  files: each machine resolves against a *different* base, so on a same-field
  conflict the two can pick differently and the stores permanently diverge.
  Repairing that needs a deterministic cross-machine tiebreak — i.e. re-inventing
  half of §3.1 anyway.
- **−** A missing/stale base has no safe default here. E1's `base := theirs`
  bootstrap is safe because "keep the local value" is the conservative choice
  against a *bundled catalog*. Against a *peer*, "keep ours for every diverged
  field" resurrects our stale values over their newer ones — strictly worse than
  today.
- **−** Adds a second write to every save, on the hot path.

### 3.3 Op-log / append-only journal (Automerge, Yjs)

Persist field-level operations rather than state; merge is a union of ops
ordered by `(timestamp, actor)`.

- **+** Strongest correctness story; gives edit history for free.
- **−** Replaces the persistence format wholesale, not additively. Every reader
  (`merge_backup.py`, `scripts/desktop_backup.py`, the restore path, the
  frontend import/export) changes.
- **−** Automerge/Yjs are new dependencies — `AGENTS.md`: "No new dependencies
  without discussion." Hand-rolling an op log is a large amount of new
  load-bearing code for a two-device, single-user store.
- **−** Unbounded growth without compaction, which is its own subsystem.

### 3.4 Recommendation

**§3.1.** It is the only option that keeps the CRDT contract the store already
depends on, and its single real cost — an additive on-disk field — is exactly
the cost §5.3 shows how to make safe. §3.2 is seductive because it looks
migration-free, but it trades a *visible, controllable* format change for an
*invisible* divergence risk, which is the worse trade for a store that syncs
through iCloud with no coordination channel.

---

## 4. Design

### 4.1 Schema (additive)

```python
class Bookmark(BaseModel):
    ...
    updated_at: str = ""
    # Per-field last-write stamps, ISO 8601, for the fields the cross-device
    # merge resolves independently (domain/store_merge.py::MERGEABLE_FIELDS).
    # Absent / missing key => fall back to this record's `updated_at`, which
    # reproduces pre-G whole-record LWW exactly. Written only by mutation
    # paths, never by enrichment.
    field_updated_at: dict[str, str] = {}
```

Same field on `BookmarkCategory` (and `Route` / `RouteCategory` if Q1 says yes).

Pydantic v2 defaults to `extra='ignore'`, so an older build reading this file
drops the key and writes it back without it. That is the documented, already-relied-on
cross-version behaviour — `enrich_all`'s docstring records the same cycle for the
geo fields.

### 4.2 Merge units, not raw fields

`lat` and `lng` **must move together.** Taking a latitude from one machine and a
longitude from the other synthesises a coordinate that never existed on either —
a bookmark in the sea. So the merge operates on named *units*:

| Unit | Fields | Applies to |
|---|---|---|
| `name` | `name` | bookmark, category |
| `coords` | `lat`, `lng` | bookmark |
| `address` | `address` | bookmark |
| `category_id` | `category_id` | bookmark |
| `last_used_at` | `last_used_at` | bookmark |
| `color` | `color` | category |
| `sort_order` | `sort_order` | category |
| `dates` | `start_date`, `end_date` | category |

**Deliberately excluded:**

- `country_code`, `timezone`, `city`, `region` — deterministic from `coords`,
  authored solely by `enrich_bookmark`, never stamped. They follow whichever
  side wins `coords`, which is what keeps them consistent with the coordinate.
- `created_at` — immutable.
- `id` — the merge key.

### 4.3 The resolution rule

For each unit `u`, with `stamp(record, u) = record.field_updated_at.get(u) or record.updated_at`:

1. Newer `stamp` wins the unit.
2. **Tie:** the side with the newer record-level `updated_at` wins.
3. **Still tied:** the side whose serialized unit value sorts greater wins.

Rule 3 is ugly and load-bearing. It exists purely so the merge stays
**commutative** — an arbitrary-but-symmetric tiebreak means `merge(a, b)` and
`merge(b, a)` agree. A "prefer left" rule would be simpler and would silently
break convergence. The alternative is a per-machine actor id in the file, which
is more state to manage and to keep out of the synced folder; rule 3 buys the
same determinism for free.

The merged record's `updated_at` becomes `max` over the surviving unit stamps and
both input `updated_at` values, so **tombstone semantics are untouched**:
`_alive()` keeps comparing `deleted_at` against a record-level `updated_at` that
is still "the last time anything about this record changed".

### 4.4 Degradation matrix — the safety argument

| Left record | Right record | Result |
|---|---|---|
| no map | no map | every unit falls back to `updated_at` → **identical to today's whole-record LWW** |
| has map | no map | right's units all resolve at its `updated_at`; a left unit stamped later than that survives. Strictly better than today, never worse |
| has map | has map | full per-field merge |

An old build that strips the map therefore rolls the pair back to row 1 for that
record — today's behaviour — and the next write from a G build re-populates it.
**No migration step, no coordinated upgrade, no half-migrated hazard.** This is
the direct answer to the reason G was deferred in the E1/F plan §2 table.

### 4.5 Writers

Every mutation stamps only what it changed. F's no-op guard already computes
exactly that set:

- `update_bookmark` — has `pending: dict[field, value]` (`:465-479`). Map each
  changed field to its unit, stamp those units, stamp `updated_at`. The existing
  early return on an empty `pending` means a no-op still writes nothing.
- `update_category` — same, via the `pending` dict added in `bf4d606`.
- `move_bookmarks` — stamps `category_id`, and `coords` **only if** the rounding
  actually changed a value (today it re-rounds unconditionally).
- `import_catalog` — the resolver already knows which fields came from theirs
  (`res.values`); stamp those units only.
- `create_bookmark` / `force_seed` / `import_json` — a new record; stamp all
  units at `updated_at`, or equivalently leave the map empty. Prefer **empty**:
  smaller, and the fallback makes it exactly equivalent.
- `enrich_bookmark` — **must not stamp.** Unchanged.

### 4.6 Ring placement

No new rings and no new import-linter contract.

- `domain/store_merge.py` — `MERGE_UNITS`, `unit_stamp()`, `merge_records()`,
  and `_union_by_id` rewritten to call it. Pure; stdlib + pydantic only.
- `models/schemas.py` — the additive field.
- `services/bookmarks.py`, `services/route_store.py` — writers stamp units.
- Nothing in `api/`, `infra/`, or `bootstrap/` changes.

The 7 contracts stay 7.

---

## 5. Consequences to check before coding

### 5.1 Everything that already goes through `merge_stores` gets G for free

`_save()`, `_watcher_tick`, `sync_merge.py`'s enable/disable migration, and
`merge_backup.py` (`make restore-backup` / `merge-bookmarks` / `merge-routes`)
all call the one primitive. Restore-from-backup therefore also becomes
field-aware — note this **still does not let a backup undo a revert**, because
the reverted record's fields carry the newer stamps. That operational fact from
the E1/F work is unchanged and should stay documented.

### 5.2 Tests that must change

- `test_bookmark_revert_hazards.py::test_stale_whole_record_update_outranks_fresher_remote_copy`
  — **inverts.** It currently asserts the loss. Under G both fields survive. Its
  module docstring (which walks the reader through why F cannot reach it) needs
  rewriting, and the file stops having a "residual hazard" entry.
- Any test asserting `_union_by_id` returns one input object identically. Needs a
  survey pass; `test_store_merge*.py` and `test_bookmark_concurrency.py` are the
  likely sites.

### 5.3 A property test is mandatory here, not optional

The tiebreak in §4.3 rule 3 is exactly the kind of rule that is "obviously fine"
and then is not. Plan a randomized commutativity/idempotence property test over
generated record pairs (fixed seed, no new dependency — a loop over a seeded
`random.Random` is enough) asserting `merge(a,b) == merge(b,a)` and
`merge(a,a) == a`, including records with partial, absent, and conflicting maps.

### 5.4 File size

Measured on the live store: 531 bookmarks / 19 categories, `bookmarks.json` =
**273 KB**. Six ISO stamps per bookmark plus five per category adds roughly
**+157 KB (+57%)**, to ~430 KB.

That is tolerable for an iCloud file rewritten on each save, but it is a real
regression in sync volume and in how readable the file is when debugging by eye.
Two mitigations, either deferrable:

- Store stamps as **epoch milliseconds integers** rather than ISO strings:
  ~+65 KB (+24%) instead. Cost: a second time format in one file.
- Omit a unit whose stamp equals the record's `updated_at` (the fallback makes it
  redundant). Saves a lot right after a write and little once records diverge.

Recommendation: ship ISO strings (consistent, greppable), revisit only if the
file becomes a problem. Flagged as **Q2**.

---

## 6. Test Plan

| # | Test | Asserts |
|---|---|---|
| 1 | `merge_records` unit matrix | each unit resolves independently; newer stamp wins |
| 2 | tie → record `updated_at`; tie → value sort | rule 2 and rule 3 fire in order |
| 3 | property: commutativity + idempotence, seeded random | §5.3 |
| 4 | `lat`/`lng` never split | a coords conflict takes one side's pair whole |
| 5 | degradation matrix §4.4, all three rows | no-map pairs behave exactly as pre-G |
| 6 | old-build round-trip | strip the map, re-merge → pre-G result, no crash |
| 7 | two-manager disjoint edit (the inverted hazard test) | both fields survive |
| 8 | two-manager same-field conflict | one side wins, both machines agree |
| 9 | `enrich_all` still stamps nothing | geo fields do not enter the merge |
| 10 | tombstone still beats an older record | `_alive` unaffected by the new `updated_at` derivation |
| 11 | `move_bookmarks` stamps `category_id` only | dragging does not clobber a peer's rename |
| 12 | `import_catalog` stamps only fields taken from theirs | E1 behaviour preserved end-to-end |
| 13 | `make restore-backup` path | `merge_backup.py` is field-aware, and a revert is still not undoable by restore |

Frontend: no change expected. Confirm by running `npx tsc --noEmit`, vitest, and
depcruise; if any of them move, that is a signal the API surface shifted, which
constraint 2.1.1 forbids.

---

## 7. Tasks

- **Task 0 — prerequisite.** Give `RouteManager.update_category` the same
  diff-before-mutate no-op guard `BookmarkManager.update_category` got in
  `bf4d606`, plus its `PUT` partial-update model. This is the last known
  unconditional re-stamp; leaving it in place would let a route-category save
  keep reverting under G.
- **Task 1.** `MERGE_UNITS` + `unit_stamp` + `merge_records` in
  `domain/store_merge.py`, with tests 1–5 written first (danger-zone-test-first:
  this is the single most load-bearing pure function in the store).
- **Task 2.** Property test (test 3) before wiring anything up.
- **Task 3.** Additive schema field on `Bookmark` / `BookmarkCategory`.
- **Task 4.** `_union_by_id` calls `merge_records`. Tests 6, 10.
- **Task 5.** Writers stamp units: `update_bookmark`, `update_category`,
  `move_bookmarks`. Tests 7, 8, 11.
- **Task 6.** `import_catalog` resolver stamps only taken fields. Test 12.
- **Task 7.** Invert the hazard test and rewrite the module docstring. Test 7.
- **Task 8.** `merge_backup.py` verification pass. Test 13.
- **Task 9.** Routes, if Q1 = yes.
- **Task 10.** Update `CLAUDE.md` / `AGENTS.md` — the "Bookmark / Route store:
  CRDT merge semantics" section currently states "whole-record LWW" as an
  invariant in three places, and the E1/F "two rules that work UPSTREAM of the
  merge" framing stops being accurate once the merge itself changes.

---

## 8. Rollout

Unlike E1, G needs no per-machine bootstrap and no ordering discipline: the
degradation matrix means a G machine and a pre-G machine can share the store
indefinitely. Both Macs are already on the post-E1/F build (verified on Mac 1
today via `/openapi.json`).

Recommended anyway: `make backup` **before** `make build-install` on each Mac —
`build-install` pkills the app, and `make backup` needs it running.

---

## 9. Risks

1. **The tiebreak is the whole ballgame.** If rule 3 is wrong or is quietly
   dropped in review, the two stores diverge permanently and silently — a strictly
   worse failure than today's revert, because there is no single correct value to
   restore. Mitigated by test 3 and by making it impossible to omit (the property
   test fails without it).
2. **A field added later without a unit** silently falls back to whole-record LWW
   for that field. That is safe but invisible. Mitigate with a test that asserts
   every mutable field on `Bookmark` is covered by exactly one unit or is on an
   explicit exclusion list.
3. **Sync volume +57%** (§5.4).
4. **`_union_by_id` becomes materially more complex** on the hottest merge path,
   called on every `_save()` and every watcher tick over ~550 records. Worth one
   timing check against the current implementation; a per-record dict build is
   cheap, but this runs under `_store_lock`.
5. **Task 0 widens the diff** into the route store before G's core lands. It could
   be split into its own commit ahead of the rest — recommended.

---

## 10. Open questions for Ravi

| # | Question | Options | Recommendation |
|---|---|---|---|
| **Q1** | Include `RouteStore` (routes + route categories) in G, or bookmarks only? | (a) bookmarks only, routes later; (b) both in one pass | **(b) both** — same primitive, same merge function; doing routes later means writing the unit table twice and living with a known-broken half. Task 0 already opens that file. |
| **Q2** | Stamp encoding — ISO strings (+57% file size) or epoch-ms integers (+24%)? | (a) ISO; (b) epoch-ms | **(a) ISO** — consistent with every other timestamp in the file and greppable when debugging by eye. Revisit if sync volume bites. |
| **Q3** | Same-field conflict resolution: silently pick a winner (§4.3), or surface it? | (a) silent; (b) also log + expose a count the UI could toast | **(a) silent for now** — but I'd add the log line, since a silent same-field loss is precisely the class of bug that started this. |
