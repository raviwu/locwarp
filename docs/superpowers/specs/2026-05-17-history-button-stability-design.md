# History Button Stability — Design

**Date:** 2026-05-17
**Status:** Draft (pending user review)
**Author:** Ravi Wu
**Type:** Bugfix + UX stabilisation

---

## 1. Background

The "Recent destinations" history button at top-right of the map is gated by
`recentPlaces && recentPlaces.length > 0` (`MapView.tsx:2148`). When the
gate is `false` the entire button disappears from the UI.

`recentPlaces` is the React state in `App.tsx:606`, initialized to `[]` and
populated by a single call to `api.getRecent()` inside a `refreshRecent`
`useCallback`, triggered once on mount via
`useEffect(() => { void refreshRecent() }, [refreshRecent])`
(`App.tsx:610`). The `refreshRecent` body silently swallows errors:

```ts
const refreshRecent = useCallback(async () => {
  try { setRecentPlaces(await api.getRecent()) } catch { /* silent */ }
}, [])
```

`api.getRecent()` flows through `request()` → `fetchWithRetry()`
(`api.ts:5-17`), which retries on `fetch` rejections (connection refused
during backend startup) with backoff, **15 attempts capped at ~25 seconds
total**. HTTP 4xx/5xx responses are NOT retried — they propagate as the
`Response` object and the catch block silently absorbs them.

**Resulting failure mode**: if the backend takes longer than ~25 seconds to
start (cold disk, antivirus scan, transient port conflict) OR returns any
non-2xx response on first contact, the only mount-time fetch fails, the
state stays `[]`, and the button never appears for the rest of the session.
The user reproduced this today — after `./start.sh` the icon disappeared,
and reappeared only after a full app restart. There is no auto-recovery
path today.

The button-disappearance also conflates two distinct states the user
experiences identically:

| Underlying state | Today's UI |
|------------------|-----------|
| First-run, genuinely no history | No button |
| Backend hadn't reached us yet → fetch failed | No button |
| Backend returned 5xx on first contact | No button |

A user who sees no button cannot tell whether their history was lost,
whether they need to do something, or whether the app is broken.

## 2. Goals

- The history button is **always present** in its top-right slot whenever
  `MapView` is mounted, regardless of fetch state or list emptiness.
- When the initial `getRecent()` fetch fails, the app **auto-recovers**
  the next time the backend becomes reachable, without requiring a user
  action or app restart.
- Zero new UI elements, zero new i18n strings, no behavioural changes to
  fetch / retry plumbing beyond what is needed.

## 3. Non-goals

- Adding a manual "Reload" affordance inside the empty dropdown. The
  WS-triggered auto-refresh covers the common case; if it ever doesn't,
  that's a separate diagnostic and we'll add affordances then.
- Showing a "fetch failed" badge / spinner / error state on the button.
  Fetch failures are silent today and will remain silent — surfacing them
  is a separate UX decision.
- Changing `fetchWithRetry`'s 15-attempt / 25-second budget or its
  exponential backoff. The window is fine; the gap was only between
  "single mount-time attempt" and "self-healing on WS connect".
- Touching the backend `/api/recent` endpoint or `RecentPlacesManager`.
- Adding a manual retry timer (polling). The WS-triggered approach is
  more efficient and naturally aligned with "backend is reachable".

## 4. Design

### 4.1 Always-visible button (A)

In `frontend/src/components/MapView.tsx:2148`, the outer wrapper:

```tsx
{(recentPlaces && recentPlaces.length > 0) && (
  <div ...>... button + dropdown ...</div>
)}
```

becomes:

```tsx
{recentPlaces && (
  <div ...>... button + dropdown ...</div>
)}
```

This change has **no other side effects** because the inner UI already
defends against empty state:
- The badge count overlay at `MapView.tsx:2209` is gated on
  `recentPlaces.length > 0 && !recentOpen` — when empty, no `0` badge.
- The "Clear" button in the dropdown header at `MapView.tsx:2262` is
  gated on `onRecentClear && recentPlaces.length > 0` — when empty, no
  Clear button.
- The empty-state message at `MapView.tsx:2478` (`map.recent_empty`,
  `'還沒有任何紀錄'` / `'No history yet'`) is rendered when
  `recentPlaces.length === 0`.

The remaining `recentPlaces &&` truthy check is a type-narrowing
defence: the prop is declared optional (`recentPlaces?: Array<...>` at
`MapView.tsx:116`), so the truthy guard satisfies the compiler.
`App.tsx` always passes a non-null array (initialised to `[]`), so this
guard is effectively a no-op at runtime today.

### 4.2 WS-triggered auto-refresh (B)

In `frontend/src/App.tsx:610`, change:

```ts
useEffect(() => { void refreshRecent() }, [refreshRecent])
```

to:

```ts
useEffect(() => { void refreshRecent() }, [refreshRecent, ws.connected])
```

`ws` is the existing `useWebSocket()` hook (`App.tsx:82`). Its
`connected` boolean tracks the live WebSocket session to the backend on
port 8777. The same boolean is already used as a `useEffect` dep at
`App.tsx:380`, `404`, `498`, `502`, `510` for various "act when the
backend is reachable" flows — this change is the same pattern applied
to recent-list refresh.

**Behaviour:**
- Mount: `ws.connected` is `false`. Effect fires once. `refreshRecent`
  attempts fetch — usually succeeds (fetchWithRetry rides out the
  startup race) but may fail if backend is unusually slow.
- WS connects: `ws.connected` transitions `false → true`. Effect fires
  again. `refreshRecent` runs. If the mount fetch failed, this rescues
  the state. If the mount fetch succeeded, this is a redundant refresh
  (cheap, idempotent).
- WS reconnect after drop: `ws.connected` flips `true → false → true`.
  Effect fires on each transition. The intermediate `false` triggers an
  attempt that usually fails (silent — no harm). The subsequent `true`
  triggers a successful refresh, picking up any history entries pushed
  by other clients of the same backend during the drop window.

`refreshRecent` keeps its existing silent-catch — failures during
disconnected intervals don't surface as errors and don't perturb state.

### 4.3 What this design does NOT do

- Doesn't track "fetch failed" in a state variable. Failures stay silent;
  recovery is implicit via the WS retry hook.
- Doesn't add a retry-on-dropdown-open. The WS hook is sufficient and
  cleaner than per-click state checks.
- Doesn't change the initial empty UX. First-time users will see the
  history button (with no badge, dropdown opens to "還沒有任何紀錄") —
  this is the desired UX, matching common desktop app conventions
  (Spotify recently played, browser history, etc.).

## 5. Files touched

| File | What changes |
|------|--------------|
| `frontend/src/App.tsx` | Line 610: `useEffect` dep array gains `ws.connected` so the recent fetch self-heals on backend reachability. |
| `frontend/src/components/MapView.tsx` | Line 2148: outer wrapper gate drops the `length > 0` check; button now renders whenever `recentPlaces` is truthy (always, in practice). |

No new files, no i18n changes, no backend changes, no API changes.

## 6. Testing

Frontend has no automated test suite. Verification is manual against the
running app (dev or installed).

Automated gates: `cd frontend && npx tsc --noEmit` clean, `npm run build`
green.

Manual matrix:

1. Fresh-install / empty history: launch the app. The history button is
   visible at top-right. Click it — dropdown opens showing the
   "還沒有任何紀錄" empty state.
2. Populated history: with existing entries, launch the app. Button is
   visible with badge count. Dropdown shows entries normally.
3. Backend-startup race: kill the backend, launch the app cold. Button
   appears but dropdown opens empty initially. Once the WS connects
   (visible via the device-status indicator), open the dropdown again —
   entries appear.
4. Mid-session WS drop / reconnect: open the dropdown and confirm
   entries. Disable WiFi / restart backend / otherwise force a WS
   reconnect. After WS reconnects, entries are still there (re-fetched
   identically).
5. Clear all history via the dropdown's Clear button: button stays
   visible, dropdown opens to empty state. Confirm Clear button itself
   is now hidden (existing `onRecentClear && recentPlaces.length > 0`
   gate).
6. Existing flows (left-click re-fly, right-click + ⋮ context menu,
   matched-bookmark display, Add Bookmark / Already bookmarked menu
   item): no regressions.

## 7. Risks and rollback

- **Risk: WS reconnect storm causes excessive `/api/recent` calls.**
  Mitigation: `/api/recent` is a small GET that returns a capped
  20-entry list from in-memory state on the backend. Multiple calls
  per second would still be negligible. WS reconnect cadence is
  bounded by `useWebSocket`'s own backoff. Not a concern.
- **Risk: First-run users find the empty history button noisy.** Low
  risk — empty desktop-app history affordances are conventional. If
  the user dislikes it, we can add a "hide when empty until first
  push" override later (would need a new state flag).
- **Risk: The truthy guard `recentPlaces &&` resolves false in some
  unforeseen path, blanking the button again.** Today's App.tsx
  initialises the state to `[]` and never sets it to undefined, so the
  guard always passes. If a future refactor changes that, the guard
  fails closed (no button) — which is the original behaviour, no worse.
- **Rollback**: The change is two single-line edits across two files.
  Reverting restores prior behaviour.

## 8. Out of scope (revisit later)

- Surface a "fetch failed" state in the UI (red dot, retry button,
  toast).
- Replace the WS-triggered approach with a smarter retry policy (e.g.
  exponential backoff with cap, jitter).
- Persist `recentPlaces` to local storage as a fallback when the
  backend is unreachable across a full session.
- Extract `refreshRecent` and the recent-state machinery into a custom
  hook (`useRecentPlaces`).
