# History Button Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the "Recent destinations" history button always visible (no length-based gate) and have `refreshRecent` re-run whenever the backend WebSocket becomes reachable, so a slow / racing / disconnected backend can no longer hide the button forever.

**Architecture:** Two surgical edits, no new components, no new state. Change one JSX gate in `MapView.tsx` and one `useEffect` dependency array in `App.tsx`. The button always renders; the existing empty-state UI handles "no entries yet". The `useWebSocket` hook (already used by 5+ other effects in `App.tsx`) provides the `ws.connected` boolean that triggers re-fetch on initial connect and every reconnect.

**Tech Stack:** React 18 + TypeScript + Vite (`frontend/`). No automated test suite — gates are `tsc --noEmit` + `npm run build` + manual smoke test.

**Spec:** `docs/superpowers/specs/2026-05-17-history-button-stability-design.md` (commit `70134dc`).

---

## File Structure

All changes in `frontend/`. No new files.

| File | Why it changes |
|------|----------------|
| `frontend/src/components/MapView.tsx` | Line 2148: gate around the history button drops the `length > 0` clause so the button is visible even when `recentPlaces` is empty. |
| `frontend/src/App.tsx` | Line 610: the `useEffect` that fires `refreshRecent` gains `ws.connected` as a dependency, so re-fetch happens on initial backend WS connect and every subsequent reconnect. |

---

## Task 1: Make the history button always visible

**Files:**
- Modify: `frontend/src/components/MapView.tsx:2148`

Remove the `recentPlaces.length > 0` half of the wrapper gate. Other empty-state handling already exists deeper in the dropdown.

- [ ] **Step 1: Locate the gate**

In `frontend/src/components/MapView.tsx`, find line 2148:

```tsx
      {(recentPlaces && recentPlaces.length > 0) && (
        <div
          onContextMenu={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
```

- [ ] **Step 2: Replace the gate**

Replace the single line `2148` with:

```tsx
      {recentPlaces && (
```

Nothing else on that line — surrounding `<div>` and its props unchanged.

Why this is safe (already verified — do not touch):
- `MapView.tsx:2209` badge-count overlay is gated `recentPlaces.length > 0 && !recentOpen`, so an empty list won't display a `0`.
- `MapView.tsx:2262` Clear-button is gated `onRecentClear && recentPlaces.length > 0`, so an empty list won't show a Clear control.
- `MapView.tsx:2478` empty-state message (`map.recent_empty` → `還沒有任何紀錄` / `No history yet`) renders when `recentPlaces.length === 0`.
- The remaining `recentPlaces &&` truthy check is a TS narrowing guard against the optional prop type at `MapView.tsx:116`.

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output (clean exit).

- [ ] **Step 4: Production build (sanity)**

```bash
cd frontend && npm run build
```

Expected: `✓ built in <time>s`. Pre-existing dynamic-import warning unchanged.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MapView.tsx
git commit -m "fix(map): keep history button visible when recent list is empty"
```

---

## Task 2: Re-fetch recent list on WS connect / reconnect

**Files:**
- Modify: `frontend/src/App.tsx:610`

Add `ws.connected` to the `useEffect` dependency array so `refreshRecent` re-runs when the backend WebSocket transitions reachable. Existing `useWebSocket()` hook already exposes `ws.connected`; the same boolean is already used as a `useEffect` dep at `App.tsx:380`, `404`, `498`, `502`, `510` — so this is the same pattern, applied to recent-list refresh.

- [ ] **Step 1: Locate the effect**

In `frontend/src/App.tsx`, find line 610:

```ts
  const [recentPlaces, setRecentPlaces] = useState<api.RecentEntry[]>([])
  const refreshRecent = useCallback(async () => {
    try { setRecentPlaces(await api.getRecent()) } catch { /* silent */ }
  }, [])
  useEffect(() => { void refreshRecent() }, [refreshRecent])
```

- [ ] **Step 2: Add `ws.connected` to the dependency array**

Replace line 610:

```ts
  useEffect(() => { void refreshRecent() }, [refreshRecent])
```

with:

```ts
  // Re-fetch on initial mount AND whenever the backend WebSocket becomes
  // reachable. Without the ws.connected dep, a slow/racing backend boot
  // could blow the only fetch attempt and the recent list would stay empty
  // for the rest of the session (silent catch in refreshRecent above).
  useEffect(() => { void refreshRecent() }, [refreshRecent, ws.connected])
```

`refreshRecent` is stable (deps `[]`), so adding `ws.connected` is the only behavioural change. Other effects in `App.tsx` already use this exact `[..., ws.connected]` pattern (search `ws.connected` to confirm).

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no output.

- [ ] **Step 4: Production build**

```bash
cd frontend && npm run build
```

Expected: `✓ built in <time>s`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "fix(app): re-fetch recent list on backend WS connect"
```

---

## Task 3: Manual smoke test verification matrix

**Files:** none

Frontend has no automated test suite — verification is manual against the dev server. Spec §6 matrix below.

- [ ] **Step 1: Start the dev environment**

```bash
cd /Users/raviwu/personal/locwarp
./start.sh
```

(Do **not** prefix with `sudo` — root ownership of `frontend/node_modules/.vite/deps` breaks subsequent runs.)

If `./start.sh` is unavailable or you prefer Vite-only:

```bash
cd frontend && npm run dev
```

Then open `http://localhost:5173` (or whichever Electron window pops up).

- [ ] **Step 2: Walk through the verification matrix**

| # | Action | Expected |
|---|--------|----------|
| 1 | Empty history: clear all entries via the dropdown's Clear button, then close + re-open the app. | History button is **visible** at top-right. Clicking it opens the dropdown showing `還沒有任何紀錄` / `No history yet`. Badge count is hidden. Clear button is hidden inside the dropdown. |
| 2 | Populated history: with at least one entry, restart the app. | Button visible with badge count. Dropdown lists entries normally. |
| 3 | Backend-startup race: kill the LocWarp backend process (or wait for the bundled backend to come up slowly), launch the app cold. | Button visible immediately (even before backend is reachable). Dropdown initially opens empty. **Within ~1–2 seconds of the WS connecting** (the device-status indicator turns connected), close + re-open the dropdown — entries appear. No app restart needed. |
| 4 | Mid-session WS reconnect: restart the backend while the app is running, or briefly disable network so WS drops + reconnects. | Button stays visible. After WS reconnects, dropdown shows the current entries (re-fetched silently). |
| 5 | Existing flows still work: left-click row → re-fly; right-click / ⋮ → context menu; matched-bookmark rows show bookmark name + GeoLine; "Add to bookmarks" disables to "已加入書籤" for matched coords; map-only right-click works. | No regressions. |

- [ ] **Step 3: Stop the dev environment**

`Ctrl-C` the foreground process (start.sh prints the pids if it spawned the backend separately).

- [ ] **Step 4: (no commit — manual-test task)**

If smoke test surfaces a defect, fix in a follow-up task with its own commit.

---

## Out of scope (do not implement here)

Per spec §3 / §8 — do **not** sneak these in:

- Manual "Reload" button inside the empty dropdown.
- Visible "fetch failed" badge / spinner / error toast.
- Changes to `fetchWithRetry`'s 25-second retry window or its backoff.
- Persisting `recentPlaces` to local storage.
- Extracting `refreshRecent` + recent-list state into a `useRecentPlaces` hook.
- Backend / `/api/recent` changes.
