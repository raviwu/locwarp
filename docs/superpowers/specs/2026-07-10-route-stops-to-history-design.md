# Route stops → Recent history

**Date:** 2026-07-10
**Status:** Design — awaiting approval
**Baseline to hold green:** backend `1118` pytest collected; frontend vitest; import-linter `7 kept, 0 broken`; dependency-cruiser `0 errors`

---

## 1. Problem

LocWarp's history feature (the map's "Recent" popover, backed by `recent_places.json`) records only
**user-initiated fly-to intents**: right-click teleport, right-click navigate, address search, and the
two coord-input buttons. It is written exclusively by the frontend — the backend has zero internal
writers of the recent store.

When a simulated route runs, the places it actually passes through are never recorded. The user wants
those stops in history too, so an individual stop can be re-flown with one click.

## 2. Ground truth (verified)

| Fact | Receipt |
|---|---|
| History = FIFO 20-entry store, 5 manual kinds | `backend/services/recent.py:19, 22-29` |
| Dedup compares **only** `entries[0]`, within 10 m, and preserves the original `kind` | `backend/services/recent.py:20, 90-103` |
| All writes originate in the frontend; backend has no internal caller | `frontend/src/hooks/useRecentPlaces.ts:27-48`; `backend/api/recent.py` is the only importer of `services.recent` |
| Frontend double-pushes (unnamed, then reverse-geocoded) and relies on top-entry dedup to backfill `name` | `frontend/src/hooks/useRecentPlaces.ts:36-45` |
| `multi_stop` **routed** emits `stop_reached {index,total,lat,lng}` for `waypoints[1..N-1]` — never the origin | `backend/core/multi_stop.py:187, 243` |
| `multi_stop` **jump** emits `stop_reached` for **every** waypoint incl. `waypoints[0]` | `backend/core/multi_stop.py:352, 375` |
| `route_loop` **routed** has **no** coordinate-bearing arrival event; its leg walk explicitly "mirrors multi_stop" | `backend/core/route_loop.py:213-215, 237-277` |
| `route_loop` **jump** emits `user_waypoint_advance` only (no lat/lng) | `backend/core/route_loop.py:383` |
| `route_loop` **GPX timed replay** returns before the leg walk — emits no per-stop event at all | `backend/core/route_loop.py:75-117` |
| `_emit` wraps `event_callback` in `try/except` + `logger.exception` | `backend/core/simulation_engine.py:584-588` |
| `event_callback` already carries a non-WS side effect, and broadcasts **before** it | `backend/main.py:482-488` |
| `_primary_udid` is promoted to a surviving engine when the primary disconnects | `backend/main.py:531-532, 734-736` |
| Every start path fans out to **all** connected devices, so the primary is always among them | `frontend/src/hooks/useSimActions.ts:240`; `useSimulation.ts:1005-1009` |
| `Coordinate` is lat/lng only — waypoints carry no id/name anywhere | `backend/models/schemas.py:9-11` |
| Popover already resolves a bookmark name by coordinate, for display | `frontend/src/components/RecentPlacesPopover.tsx:356-382` |
| `badgeByKind` has a grey fallback for unknown kinds — degrade-safe | `frontend/src/components/RecentPlacesPopover.tsx:280` |
| `WS_EVENT_TYPES` already lists `stop_reached`; `WsEvent` is an open `Record<string, unknown>` | `frontend/src/contract/wsEvents.ts:5, 21` |
| `GET /api/recent` has **no** `response_model` — extra fields pass through | `backend/api/recent.py:25-27` |
| `main.py` is the composition root; `backend/.importlinter`'s 7 contracts do not forbid `core → services`, but CLAUDE.md doctrine does | `backend/.importlinter`; `CLAUDE.md` |
| The recent store participates in **no** backup, cloud-sync, or CRDT merge | grep across `domain/backup.py`, `services/backup_service.py`, `services/cloud_sync*.py`, `services/sync_merge.py` |

## 3. Decisions

1. **Granularity** — one entry per stop, with **global coordinate dedup** (10 m) across route stops.
   A revisit refreshes `ts` and increments `visit_count`. A 3-lap, 8-stop loop yields 8 rows, not 24.
2. **Write side** — the **backend**, in `main.py`'s engine `event_callback`.
3. **Modes covered** — `multi_stop` (routed + jump) and `route_loop` (routed + jump).
4. **Storage** — the same recent store and the same popover, with a new `route_stop` kind and
   **split FIFO budgets** so manual and route entries never evict each other.
5. **Origin** — `waypoints[0]` (the device's position when Start was pressed, auto-injected at index 0)
   is **never** recorded, on any of the four paths.
6. **Re-fly** — teleports immediately; if a simulation was running, a toast reports that it was stopped.
   Re-flying a recent row no longer creates a duplicate manual entry.
7. **GPX timed replay** — records nothing; documented as a known limitation.
8. **Backup** — the recent store joins the existing rotating backup.

## 4. Non-goals

- `random_walk` arrivals and navigate-arrivals are out of scope. (`navigate` already records its
  destination at departure; recording arrival too would be swallowed by the 10 m dedup.)
- No reverse-geocoding of route stops on the backend.
- No new HTTP endpoints. No change to the `stop_reached` event's existing keys.
- No per-row delete, and no scoped "clear only route stops".

---

## 5. Architecture

### 5.1 The store — `backend/services/recent.py`

The draft that preceded this spec kept `push()` and `_load()` unchanged. That is not implementable:
`recent.py:53` and `recent.py:105-106` both slice `entries[:MAX_ENTRIES]` **by position**, over a list
that would now hold both classes. Thirty freshly-written route stops plus one manual teleport would
truncate to twenty and `_save()` the loss. And `push()`'s dedup compares `entries[0]` **without
checking `kind`**, so a manual teleport landing within 10 m of a leading route stop would be swallowed
into that row — taking the frontend's name-backfill re-push with it.

Both defects share one root cause: two classes of entry sharing one list. So the store keeps them in
**two internal lists** and merges only on read.

```python
MANUAL_KINDS = frozenset({"teleport", "navigate", "search", "coord_teleport", "coord_navigate"})
ROUTE_KIND   = "route_stop"
_VALID_KINDS = MANUAL_KINDS | {ROUTE_KIND}

MAX_MANUAL_ENTRIES     = 20   # was MAX_ENTRIES
MAX_ROUTE_STOP_ENTRIES = 30
DEDUPE_DIST_M          = 10.0
```

State becomes `self._manual: list[dict]` and `self._route_stops: list[dict]`, each held ts-descending.

- `list()` returns `sorted(self._manual + self._route_stops, key=ts, reverse=True)`. Python's sort is
  stable, so ties are deterministic.
- `_load()` reads the flat array, validates, buckets by kind, sorts each bucket ts-desc, and caps each
  bucket **independently**. Legacy files hold only manual kinds, so `_route_stops` starts empty —
  backward compatible with no migration.
- `_save()` writes `self.list()` — still a flat, ts-desc JSON array. An older LocWarp reading this file
  drops `route_stop` rows via `_valid()` and keeps working.
- `push(lat, lng, kind, name=None)` accepts **manual kinds only**. It dedups against `self._manual[0]`,
  not `entries[0]`. When no route stops exist the two are identical, so **existing behavior is preserved
  exactly** — including the frontend's reverse-geocode name-backfill.
- `push_route_stop(lat, lng, name=None)` scans **all** of `self._route_stops` and picks the **nearest**
  entry within `DEDUPE_DIST_M` (nearest, not first, so overlapping stops resolve deterministically).
  On a hit it sets `ts = now`, increments `visit_count`, backfills an empty `name`, and moves the row to
  the front (`ts = now` makes it the newest route stop). On a miss it inserts a new row at the front and
  trims the tail to `MAX_ROUTE_STOP_ENTRIES`.
- `clear()` empties both lists (unchanged user-facing behavior).
- `snapshot_export()` returns `list(self.list())` for the backup service.
- `record_route_stop(lat, lng)` — a module-level function that calls `push_route_stop` inside
  `try/except` and **never raises**.

The two classes never dedup against each other and never evict each other.

### 5.2 Origin marking — `backend/core/multi_stop.py`, `backend/core/route_loop.py`

`stop_reached` gains one **additive** key, `origin: bool`. No existing key changes and no existing emit
is removed, so the WS surface stays compatible; `WsEvent` is an open record, so no frontend type changes.

| Path | Change |
|---|---|
| `multi_stop.py:243` (routed) | add `"origin": False` (routed never reaches `waypoints[0]`) |
| `multi_stop.py:375` (jump) | add `"origin": i == 0` |
| `route_loop.py` routed, after the stop-event check at `:269` | **new** `stop_reached` emit; hoist `is_last_leg` (today computed at `:274`) above it and pass `"origin": is_last_leg` — the closing leg's `wp_b` is `closed_waypoints[num_legs] == waypoints[0]` |
| `route_loop.py` jump, after `user_waypoint_advance` at `:383` | **new** `stop_reached` emit with `"origin": i == 0` |

The recorder skips any event with `origin` truthy. The result: all four paths record exactly
`waypoints[1..N-1]`, matching what `multi_stop` routed does today.

### 5.3 Wiring — `backend/main.py`

```python
async def event_callback(event_type: str, data: dict):
    if isinstance(data, dict) and "udid" not in data:
        data = {**data, "udid": udid}
    if (
        event_type == "stop_reached"
        and not data.get("origin")
        and udid == self._primary_udid
        and "lat" in data and "lng" in data
    ):
        record_route_stop(data["lat"], data["lng"])   # sync; never raises
    await broadcast(event_type, data)
    if event_type == "position_update" and "lat" in data:
        self.update_last_position(data["lat"], data["lng"])
```

Three deliberate choices:

**Record before broadcast.** The frontend refetches on the `stop_reached` broadcast. Recording first
means the refetch cannot observe a store that predates the write.

**Record synchronously on the event loop.** `_save()` performs an atomic tmp-write-and-replace of a
≤50-entry JSON, at most once per stop (stops are seconds apart). Moving it to `asyncio.to_thread`
would be the first cross-thread mutation of a store that has **no lock**, introducing a race that does
not exist today. Every other writer — the three HTTP handlers — already runs on this loop.

**Gate on the primary device.** A `multiStopAll` fan-out runs the same route on N engines, each with
its own `event_callback`. Without the gate, one physical stop would increment `visit_count` by N. The
gate is safe because every start path fans out to all connected devices (so the primary is always
running the route) and `main.py:531-532` promotes a survivor when the primary disconnects.

`_emit` already swallows callback exceptions (`simulation_engine.py:584-588`), so a recorder failure
cannot abandon a route; `record_route_stop` is defensive anyway, to avoid log spam.

This lives in `main.py`, the composition root — no ring is crossed. `core/` never learns that a recent
store exists.

### 5.4 API — `backend/api/recent.py`

No new endpoints.

- `RecentPushRequest.kind` keeps its five-member Literal, so **the frontend physically cannot forge a
  `route_stop`**. The backend is the sole writer of that kind — an invariant worth a test.
- `GET /api/recent` has no `response_model`, so `visit_count` passes through untouched. A regression
  test pins this, because adding a `response_model` later would silently strip the field.
- `DELETE /api/recent` clears both classes.

### 5.5 Frontend

| File | Change |
|---|---|
| `services/api.ts:417-418` | `RecentKind` += `'route_stop'`; `RecentEntry` += `visit_count?: number` |
| `components/RecentPlacesPopover.tsx:6-12` | widen the local `RecentPlaceEntry.kind` union; add `visit_count?` |
| `components/RecentPlacesPopover.tsx:273-279` | `badgeByKind` += `route_stop` → label `路線` / `Route`, purple `#b085f5` |
| `components/RecentPlacesPopover.tsx` row | render `×N` beside the badge when `visit_count > 1` |
| `hooks/useRecentPlaces.ts:16` | signature becomes `useRecentPlaces(api, connected, ws?)`; subscribe to `stop_reached` → **coalesced** `refreshRecent()` (trailing debounce, ~500 ms) so a multi-device fan-out's N broadcasts collapse into one GET. Read-path only — the hook never POSTs a route stop. |
| `App.tsx:345` | pass the ws router (sole production call site; `ws` is optional, so the five existing test call sites compile unchanged) |
| `App.tsx:1147-1151` | `onRecentReFly`: `route_stop` takes the teleport branch, with `{ record: false }` |
| `hooks/useSimActions.ts:195` | `handleTeleport` gains a `record` option (default `true`); when a sim is running, show the stopped-simulation toast |
| `adapters/ws/eventWiring.test.tsx:88, 120-133` | remove `stop_reached` from `UI_IGNORED_BY_DESIGN` **and** mount `useRecentPlaces` in `collectSubscribedTypes()` |
| `i18n/strings.ts:379-383` | `recent.kind_route_stop`, `recent.visit_count_tooltip`, `toast.sim_stopped_by_refly` (zh-TW + en) |

The `eventWiring` gate matters: promoting `stop_reached` to "surfaced" without adding `useRecentPlaces`
to the collector turns test 1 red, because the collector mounts only four hooks today.

Re-fly currently calls `pushRecent` unconditionally (`useSimActions.ts:195`), so clicking a route stop
would mint a duplicate manual `teleport` row. It also calls `engine.stop()` (`core/teleport.py:29`),
silently killing a running route. Both are fixed here: `record: false` suppresses the duplicate, and the
toast makes the abort visible. The toast applies to **every** re-fly kind — the abort was never
route-stop-specific, only far less likely to be hit before route stops began appearing mid-run.

### 5.6 Backup

The recent store joins the existing rotating backup (`docs/superpowers/specs/2026-06-22-bookmark-route-rotating-backup-design.md`).

- `RecentPlacesManager.snapshot_export()` supplies a consistent read (single-loop; no lock needed).
- `domain/backup.py`: include `recent` in the payload and in the change fingerprint. The first tick
  after upgrade will archive one timestamped file because the fingerprint changes — expected.
- `services/backup_service.py`: the skip-on-empty guard stays keyed on `bookmarks == 0 AND routes == 0`.
- `domain/recent_merge.py` (new, pure): `merge_recent(a, b)` unions the two snapshots **within each
  class** (a manual row never merges with a route row), matching rows whose coordinates fall within
  `DEDUPE_DIST_M`. A matched pair keeps `max(ts)`, the non-empty `name`, and — for `route_stop` rows
  only — `max(visit_count)`; manual rows carry no `visit_count` and gain none. The result is sorted
  ts-desc and each class is capped, so the output satisfies the same invariants the live store does.
  Commutative and idempotent, mirroring `merge_stores`'s contract without needing tombstones.
  `merge_backup.py` / `restore_combined_snapshot` fold the `recent` sub-store through it.
- `conftest._isolate_real_data_paths` already redirects both `RECENT_PLACES_FILE` and `BACKUP_DIR`.

---

## 6. Data model

```jsonc
// ~/.locwarp/recent_places.json — flat array, ts-descending
[
  { "lat": 25.0478, "lng": 121.5170, "kind": "route_stop",
    "name": "", "ts": 1783..., "visit_count": 3 },
  { "lat": 25.0340, "lng": 121.5645, "kind": "teleport",
    "name": "台北 101", "ts": 1783... }          // manual: no visit_count
]
```

`visit_count` is optional; absent means 1. It appears only on `route_stop` rows. `_valid()` tolerates
its absence, so existing files load unchanged.

## 7. Invariants

1. Manual and route entries never dedup against each other.
2. Manual and route entries never evict each other; caps are 20 and 30 respectively.
3. `list()` is ts-descending.
4. `route_stop` rows are written **only** by the backend recorder. `POST /api/recent` cannot create one.
5. `waypoints[0]` is never recorded, on any path.
6. One physical stop increments `visit_count` by exactly 1, regardless of how many devices ran the route.
7. A recorder failure never aborts a running route.

## 8. Testing — test-first

`simulation_engine.py`, the movers, and `device_manager` recovery are the repo's danger zone. Write the
characterization tests **before** touching any of them, and assert ordered exact tuples.

**Backend**

1. `test_route_loop_cov.py` — routed loop, 3 waypoints, 1 lap: assert the exact ordered `stop_reached`
   sequence `(wp1, origin=False), (wp2, origin=False), (wp0, origin=True)`.
2. `test_route_loop_cov.py` — jump loop: one `stop_reached` per waypoint, `origin == (i == 0)`.
3. `test_multi_stop_cov.py` — add `origin` assertions (routed: all `False`; jump: `i == 0` is `True`).
   Existing ordered-tuple assertions must be updated in the same commit.
4. Store, new tests:
   - global dedup: push A, B, A → two route rows; A's `visit_count == 2`
   - **B1 regression**: 30 route stops, then one manual `push()` → still 30 route stops
   - **B2 regression**: a route stop at the front, then a manual teleport within 10 m → a new manual row;
     the route stop's `kind`, `ts`, and `visit_count` untouched
   - name-backfill still works with a route stop present at the front of the merged list
   - split-budget eviction in both directions
   - `_load()` on a legacy flat file (manual kinds, no `visit_count`)
   - `_load()` caps each class independently
   - `list()` is ts-desc
5. `POST /api/recent` with `kind=route_stop` → 422.
6. `GET /api/recent` returns `visit_count` (pins the no-`response_model` behavior).
7. Recorder: `origin=True` is skipped; a non-primary udid is skipped; an exception is swallowed.
8. Backup: `recent` present in the snapshot; `merge_recent` commutative + idempotent; restore round-trip.

**Frontend**

9. `useRecentPlaces` subscribes `stop_reached` and coalesces N events into one GET.
10. Popover renders the `route_stop` badge; `×N` shows only when `visit_count > 1`.
11. `onRecentReFly(route_stop)` teleports **without** calling `pushRecent`.
12. Re-fly during a running sim raises the toast.
13. `eventWiring.test.tsx` — updated collector and allowlist, still green.
14. `npx tsc --noEmit` clean (both type copies widened).

**Gates:** full backend pytest (baseline 1118 collected), full vitest, `import-linter` `7 kept, 0 broken`,
`depcruise` `0 errors`.

## 9. Commit plan

Every commit carries its own tests, so the suite is never red at a commit boundary.

| # | Scope |
|---|---|
| C1 | `domain/recent.py` (pure policy) + `services/recent.py` two-list restructure + `push_route_stop` / `record_route_stop` / `should_record_stop`, with their tests |
| C2 | `/api/recent` contract tests (no production change) |
| C3 | Engine: `origin` key on `multi_stop`'s two emits + tests |
| C4 | Engine: new `route_loop` emits (routed + jump) + characterization tests |
| C5 | `main.py` recorder wiring + tests |
| C6 | Frontend: types, route badge, `×N` chip, i18n |
| C7 | Frontend: `useRecentPlaces` ws subscribe + `eventWiring` gate |
| C8 | Frontend: re-fly `record:false` + interrupted-simulation toast |
| C9 | Backup: `merge_recent`, fingerprint + payload, `snapshot_export`, restore path + tests |

## 10. Known limitations

- **GPX timed-replay loops record nothing.** `route_loop.py:75-117` returns before the leg walk. Fixable
  later by emitting coordinates from `waypoint_progress` (the engine already holds `_user_waypoints`).
- **Non-bookmark stops show raw coordinates.** The backend writes `name: ""`; the popover resolves names
  only through `bookmarkByCoord`. A route built from raw map clicks yields raw-coordinate rows, exactly
  as an unnamed manual teleport does today. Follow-up: enrich via `services/geo_offline.py`.
- **Resume mid-leg can re-emit a stop already recorded**, inflating `visit_count` by 1.
- **`visit_count` counts arrivals across all runs and sessions**, not laps within one run.
- **`DELETE /api/recent` clears both classes.** Route stops regenerate on the next run (with
  `visit_count` reset); curated manual history does not.
- `random_walk` and navigate-arrivals are not recorded.
- **`make restore-backup` must be run with LocWarp stopped** for the recent
  store. Bookmarks and routes have file watchers that pick up an external write;
  the recent store does not, so a restore into a running app would be overwritten
  by the next push.
