# Keyboard Reflexes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan — each task is dispatched to a fresh implementer subagent + an adversarial reviewer, gated independently. Steps use checkbox (- [ ]) syntax; tick each as you complete it. Do NOT batch tasks; one task = one reviewable, independently-mergeable deliverable ending in a commit. The whole branch gets a final whole-branch review before ff-merge.

**Goal:** Remove the highest-frequency daily-use keyboard friction in LocWarp's renderer with three pure-frontend capabilities: (1) keyboard navigation of the address-search results list, (2) app-window-scoped keyboard shortcuts mapped to existing simulation handlers, and (3) single-level Undo of the last teleport. No backend surface, no Electron `globalShortcut`, no external HTTP/WS/IPC change.

**Architecture:** Pure frontend, fits the existing hexagon-lite `view (App) → hooks → utils`. Reuses the already-extracted `useSimActions` handlers (`handleStop`/`handleRestore`/`handlePause`/`handleResume`/`handleTeleport`); adds a `lastPosition` snapshot inside `handleTeleport` (so Undo has a universal source on both single- and dual-device paths); adds an `isTypingTarget` guard to `utils/keyboard.ts`; introduces one new hook `useGlobalShortcuts.ts` that mounts a single `document` `keydown` listener. No new subsystem, no new adapter, no backend file touched.

**Tech stack:** React 18 + TypeScript + Electron renderer; Vitest + `@testing-library/react` (`fireEvent` ONLY — `@testing-library/user-event` is NOT installed); injected fake `api` via `vi.mock('../contexts/ServicesContext')` for component tests, `renderHook` for hook tests (mirror the existing `AddressSearch.test.tsx` and `useSimActions.test.tsx` harnesses verbatim); `tsc --noEmit`; import-linter (backend, untouched here) + dependency-cruiser (frontend) CI gates.

## Global Constraints

Copied verbatim from the master spec's Global Constraints; every task's requirements implicitly include this section.

- **Green after every commit.** Backend `pytest` + frontend `vitest` + 7 import-linter contracts (`7 kept, 0 broken`) + dependency-cruiser (`0 errors, 0 warnings`) all pass after EVERY commit. Pin the exact baselines before starting:
  - Backend: `cd backend && .venv/bin/python -m pytest --collect-only -q` (expected ≈949 collected).
  - Frontend: `cd frontend && npx vitest run` (expected ≈773) + `npx tsc --noEmit` (0 errors) + `npm run depcruise` (0/0).
- **Danger-zone-test-first.** `simulation_engine.py`, all movers, `api/location.py`, `device_manager` recovery, `phone_control.py` have NO direct tests. Write characterization tests (injected `ClockPort` + stepped `asyncio.sleep`, ordered exact-tuple assertions, REAL collaborators — never stub the method under test) BEFORE touching them. (Not applicable to this cluster — pure frontend — but the discipline of test-first applies to every task here.)
- **WS payload discipline.** New/changed WS payloads are compared deep-equal JSON, serialized `exclude_unset`/`exclude_none` so absent keys stay absent. Adding keys to an existing event must be backward-compatible (existing consumers must not break). (Not applicable to this cluster — no WS change.)
- **One documented behavior change.** Speed jitter (Cluster 3) changes the per-tick speed of all existing modes. It is gated behind a settings toggle that defaults ON. This is the ONLY intentional behavior change in the program; characterization tests run with jitter OFF to keep exact-tuple assertions stable. (Not applicable to this cluster — Cluster 1 introduces no behavior change to existing flows; new shortcuts only invoke existing handlers.)
- **Hexagon boundaries hold.** `domain/` stays pure; `services/` raise domain errors not `HTTPException`; view never imports `adapters/api` / `services/api` directly; the `device_manager → EventPublisher` inversion stays **awaited, in-line, order-preserving** — NEVER acquire the WS connection-manager lock while `device_manager._lock` is held.
- **Survey before adding surface.** Each new endpoint/event below states reuse-vs-new with its justification (done in the master spec: this cluster adds NO backend surface — pure frontend, reuses existing `useSimActions` handlers, adds `isTypingTarget` to `utils/keyboard.ts`, adds a universal teleport snapshot).
- **Personal-repo conventions.** Direct commits to `main`; git identity auto-set by includeIf (never pass `-c user.email=`); no PR ceremony.

---

### Task 1: `isTypingTarget` guard in `utils/keyboard.ts`

Adds a pure helper so the (later) global-shortcut listener never fires while the user is typing in an INPUT / TEXTAREA / contentEditable element. `keyboard.ts` today holds only the IME-safe Enter guard (`isImeComposing` / `isSubmitEnter`) and has NO typing-target guard. This is a leaf utility with no consumers yet, so it lands first and independently.

**Files:**
- Modify: `frontend/src/utils/keyboard.ts` (append a new exported function after `isSubmitEnter`, currently ends at line 21).
- Modify: `frontend/src/utils/keyboard.test.ts` (APPEND a new `describe('isTypingTarget', ...)` block — do NOT overwrite; the file already has 7 passing tests for `isImeComposing`/`isSubmitEnter`).

**Interfaces:**
- Produces: `export function isTypingTarget(target: EventTarget | null): boolean` — returns `true` when `target` is an `HTMLInputElement`, `HTMLTextAreaElement`, or any element whose `isContentEditable` is `true`; `false` otherwise (including `null`).
- Consumes: nothing (pure DOM type checks; takes the raw `EventTarget` so it works with a native `KeyboardEvent` whose `e.target` type is `EventTarget | null`).

- [ ] **Step 1: Write the failing test for `isTypingTarget`.** Append to the existing `frontend/src/utils/keyboard.test.ts` (7 tests today — do NOT overwrite). Add `isTypingTarget` to the existing `import { isImeComposing, isSubmitEnter } from './keyboard'` line; do NOT duplicate the `import { describe, it, expect } from 'vitest'` line. Append this `describe` block at the end of the file:
  ```ts

  describe('isTypingTarget', () => {
    it('returns true for an INPUT element', () => {
      const el = document.createElement('input');
      expect(isTypingTarget(el)).toBe(true);
    });

    it('returns true for a TEXTAREA element', () => {
      const el = document.createElement('textarea');
      expect(isTypingTarget(el)).toBe(true);
    });

    it('returns true for a contentEditable element', () => {
      const el = document.createElement('div');
      // jsdom does not derive isContentEditable from the attribute, so set it
      // explicitly via the property to model the runtime DOM behaviour.
      Object.defineProperty(el, 'isContentEditable', { value: true, configurable: true });
      expect(isTypingTarget(el)).toBe(true);
    });

    it('returns false for a plain DIV (not editable)', () => {
      const el = document.createElement('div');
      expect(isTypingTarget(el)).toBe(false);
    });

    it('returns false for a BUTTON element', () => {
      const el = document.createElement('button');
      expect(isTypingTarget(el)).toBe(false);
    });

    it('returns false for null', () => {
      expect(isTypingTarget(null)).toBe(false);
    });
  });
  ```

- [ ] **Step 2: Run the test and watch it fail.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/utils/keyboard.test.ts
  ```
  Expected: the 6 new `isTypingTarget` tests fail because the export does not exist yet (`isTypingTarget is not a function`); the 7 existing tests still pass. Confirm the failure is the missing export, not a typo in the test.

- [ ] **Step 3: Implement `isTypingTarget`.** In `frontend/src/utils/keyboard.ts`, append after the closing brace of `isSubmitEnter` (current line 21):
  ```ts

  /**
   * True when the event target is a text-entry element — an INPUT, a TEXTAREA,
   * or any contentEditable host. The app-level global keydown listener uses
   * this to BAIL OUT so single-key shortcuts (Space / R / P / B) never fire
   * while the user is typing into the address search, a coordinate field, or
   * any dialog input. Takes the raw `EventTarget` (native `KeyboardEvent.target`
   * is `EventTarget | null`) so it works outside React's synthetic events.
   */
  export function isTypingTarget(target: EventTarget | null): boolean {
    if (target === null) return false;
    const el = target as HTMLElement;
    const tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return true;
    return el.isContentEditable === true;
  }
  ```

- [ ] **Step 4: Run the test and watch it pass.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/utils/keyboard.test.ts
  ```
  Expected: `6 passed`.

- [ ] **Step 5: Verify the full gate is green.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run && npm run depcruise
  ```
  Expected: `tsc` prints nothing (0 errors); `vitest` total rises by 6 to ≈779 passed (existing 7 tests retained, not replaced, + 6 new `isTypingTarget` tests); `npm run depcruise` prints `no dependency violations found` (0 errors, 0 warnings).

- [ ] **Step 6: Commit.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add frontend/src/utils/keyboard.ts frontend/src/utils/keyboard.test.ts && git commit -m "$(cat <<'EOF'
feat(aip-c1): add isTypingTarget guard to utils/keyboard

App-level shortcuts must never fire while the user is typing in an
INPUT/TEXTAREA/contentEditable host. Pure leaf helper, no consumers yet
(wired by the global-shortcut listener in a later task).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
  ```

---

### Task 2: Universal `lastPosition` snapshot in `handleTeleport` + exposed Undo handler

`handleTeleport` (in `hooks/useSimActions.ts`) currently snapshots `prevPos = sim.currentPosition` ONLY inside the `udids.length >= 2` dual-device branch (for the total-failure revert). The single-device path does NOT snapshot. Undo needs a universal pre-teleport snapshot on BOTH paths plus a handler that flies back to it. This task adds:
1. A module-internal `lastPositionRef` updated on every teleport (before the optimistic move), capturing the position the device was at BEFORE the teleport.
2. A new `handleUndo` callback that teleports back to the snapshot (single level only — last position, no stack), and clears the snapshot after use so a second Undo is a no-op until the next teleport.

Single level by design (YAGNI — no stack). Undo with no snapshot is a silent no-op (never throws).

**Files:**
- Modify: `frontend/src/hooks/useSimActions.ts` — add `lastPositionRef` (near the other refs, ~lines 97-114), capture inside `handleTeleport` (currently lines 151-184), add `handleUndo` (new `useCallback`, before the `return`), and add `handleUndo` to the returned object (currently lines 351-361).
- Modify: `frontend/src/hooks/useSimActions.test.tsx` — add a new `describe('useSimActions — undo')` block (existing file ends at line 320).

**Interfaces:**
- Produces (added to `useSimActions`'s return object): `handleUndo: () => Promise<void>` — flies back to the snapshotted coordinate via the SAME single-vs-dual fan-out path as a teleport (so dual-device co-locates both phones), then clears the snapshot; no-op (no `sim` call) when no snapshot exists.
- Consumes: existing `simRef`, `deviceRef`, `showToastRef`, `tRef`, `pushRecentRef` already declared in `useSimActions` (lines 97-106); the existing `Position` shape `{ lat: number; lng: number }` used by `sim.currentPosition` / `sim.setCurrentPosition`.
- Note: the snapshot captures `sim.currentPosition` (the position BEFORE the optimistic move). On the single-device path `handleTeleport` does not call `sim.setCurrentPosition` (the engine does), so capturing `simRef.current.currentPosition` at the top of the handler is the pre-move value on both paths.

- [ ] **Step 1: Write failing tests for the universal snapshot + Undo.** Append to `frontend/src/hooks/useSimActions.test.tsx` (after the final `describe` block closes at line 319, before EOF):
  ```ts

  describe('useSimActions — undo (single-level last-position snapshot)', () => {
    it('single device: handleUndo teleports back to the pre-teleport position', async () => {
      // Device starts at { lat: 1, lng: 2 } (makeSim default currentPosition).
      const sim = makeSim({ currentPosition: { lat: 1, lng: 2 } })
      const { result } = setup({ udids: ['A'], sim })
      // Teleport to a new spot — snapshot should capture the prior {1,2}.
      await act(async () => { await result.current.handleTeleport(10, 20) })
      expect(sim.teleport).toHaveBeenCalledWith(10, 20)
      sim.teleport.mockClear()
      // Undo flies back to the snapshot.
      await act(async () => { await result.current.handleUndo() })
      expect(sim.teleport).toHaveBeenCalledWith(1, 2)
    })

    it('handleUndo is a silent no-op when nothing has been teleported yet', async () => {
      const sim = makeSim({ currentPosition: { lat: 1, lng: 2 } })
      const { result } = setup({ udids: ['A'], sim })
      await act(async () => { await result.current.handleUndo() })
      expect(sim.teleport).not.toHaveBeenCalled()
      expect(sim.teleportAll).not.toHaveBeenCalled()
    })

    it('single level: a second consecutive Undo is a no-op (snapshot cleared after use)', async () => {
      const sim = makeSim({ currentPosition: { lat: 1, lng: 2 } })
      const { result } = setup({ udids: ['A'], sim })
      await act(async () => { await result.current.handleTeleport(10, 20) })
      sim.teleport.mockClear()
      await act(async () => { await result.current.handleUndo() })
      expect(sim.teleport).toHaveBeenCalledTimes(1) // first undo flew back
      sim.teleport.mockClear()
      await act(async () => { await result.current.handleUndo() })
      expect(sim.teleport).not.toHaveBeenCalled() // second undo: snapshot consumed
    })

    it('no-op when the pre-teleport position was null (nothing to snapshot)', async () => {
      const sim = makeSim({ currentPosition: null })
      const { result } = setup({ udids: ['A'], sim })
      await act(async () => { await result.current.handleTeleport(10, 20) })
      sim.teleport.mockClear()
      await act(async () => { await result.current.handleUndo() })
      expect(sim.teleport).not.toHaveBeenCalled()
    })

    it('dual device: handleUndo fans out teleportAll back to the snapshot', async () => {
      const sim = makeSim({ currentPosition: { lat: 1, lng: 2 } })
      const { result } = setup({ udids: ['A', 'B'], sim })
      await act(async () => { await result.current.handleTeleport(10, 20) })
      sim.teleportAll.mockClear()
      await act(async () => { await result.current.handleUndo() })
      expect(sim.teleportAll).toHaveBeenCalledWith(['A', 'B'], 1, 2)
    })
  })
  ```

- [ ] **Step 2: Run the new tests and watch them fail.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useSimActions.test.tsx
  ```
  Expected: the 5 new `undo` tests fail with `result.current.handleUndo is not a function` (the handler does not exist yet). The 38 pre-existing tests in this file still pass.

- [ ] **Step 3: Add the `lastPositionRef` declaration.** In `frontend/src/hooks/useSimActions.ts`, immediately AFTER the `setPreviewPinRef` block (currently lines 113-114, ending `setPreviewPinRef.current = args.setPreviewPin`), add:
  ```ts

  // ── Undo snapshot (single level) ─────────────────────────────────────────
  // Captures the position the device was at BEFORE the most recent teleport so
  // handleUndo can fly back to it. Populated on EVERY teleport (single AND dual
  // device) — unlike the dual-only `prevPos` revert below, this is universal.
  // Cleared after an Undo consumes it (single level, no stack — YAGNI).
  const lastPositionRef = useRef<{ lat: number; lng: number } | null>(null)
  ```

- [ ] **Step 4: Capture the snapshot inside `handleTeleport`.** In `handleTeleport` (currently starting line 151), insert the snapshot capture right after the `const lng = normalizeLngRef.current(lngIn)` line (currently line 158) and BEFORE `setPreviewPinRef.current(null)` (currently line 159). The block becomes:
  ```ts
    const lat = clampLatRef.current(latIn)
    const lng = normalizeLngRef.current(lngIn)
    // Snapshot the pre-teleport position for single-level Undo. Read from the
    // ref so it is the position BEFORE this teleport's optimistic move (the
    // dual path calls setCurrentPosition below; the single path lets the engine
    // update it). Captured on BOTH paths so Undo is universal.
    lastPositionRef.current = sim.currentPosition ?? null
    setPreviewPinRef.current(null)
  ```
  (Note: `sim` is the local `const sim = simRef.current` already destructured at the top of `handleTeleport`, line 152.)

- [ ] **Step 5: Add the `handleUndo` callback.** In `frontend/src/hooks/useSimActions.ts`, add this `useCallback` immediately BEFORE the `return {` statement (currently line 351):
  ```ts
  const handleUndo = useCallback(async () => {
    const snapshot = lastPositionRef.current
    if (!snapshot) return // nothing to undo — silent no-op
    // Consume the snapshot up front so a double-fire (key repeat / toast click)
    // does not undo twice, and so a second Undo is a no-op (single level).
    lastPositionRef.current = null
    const sim = simRef.current
    const device = deviceRef.current
    const showToast = showToastRef.current
    const t = tRef.current
    const pushRecent = pushRecentRef.current
    const { lat, lng } = snapshot
    const udids = device.connectedDevices.map((d) => d.udid)
    if (udids.length >= 2) {
      sim.setCurrentPosition({ lat, lng })
      const outcome = await sim.teleportAll(udids, lat, lng)
      if (outcome.ok.length === 0 && outcome.failed.length > 0) {
        sim.setCurrentPosition(snapshot)
      }
      showToast(toastForFanout(t, t('mode.teleport'), outcome, device.connectedDevices))
    } else {
      try {
        await sim.teleport(lat, lng)
      } catch {
        showToast(t('toast.teleport_failed'))
        return
      }
    }
    void pushRecent(lat, lng, 'teleport')
  }, [])
  ```

- [ ] **Step 6: Export `handleUndo` from the hook.** In the `return { ... }` object (currently lines 351-361), add `handleUndo,` after `handleResume,`:
  ```ts
  return {
    handleRestore,
    handleTeleport,
    handleNavigate,
    handleStartWaypointRoute,
    handleStart,
    handleStop,
    handleApplySpeed,
    handlePause,
    handleResume,
    handleUndo,
  }
  ```

- [ ] **Step 7: Run the tests and watch them pass.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useSimActions.test.tsx
  ```
  Expected: `43 passed` (38 pre-existing + 5 new undo tests).

- [ ] **Step 8: Verify the full gate is green.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run && npm run depcruise
  ```
  Expected: `tsc` 0 errors; `vitest` total ≈784 passed; `npm run depcruise` prints `no dependency violations found`.

- [ ] **Step 9: Commit.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add frontend/src/hooks/useSimActions.ts frontend/src/hooks/useSimActions.test.tsx && git commit -m "$(cat <<'EOF'
feat(aip-c1): universal teleport snapshot + handleUndo in useSimActions

handleTeleport only snapshotted prevPos on the dual-device revert path;
Undo needs a universal pre-teleport snapshot. Add lastPositionRef captured
on every teleport (single + dual) and a handleUndo that flies back to it via
the same fan-out path, then clears the snapshot (single level, no stack).
No-op when no snapshot or when the prior position was null.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
  ```

---

### Task 3: `useGlobalShortcuts` hook (the single app-window keydown listener)

A new hook that mounts ONE `document` `keydown` listener on the app window (scope = renderer window only; NO Electron `globalShortcut`). It dispatches to the existing handlers per key, bailing out via `isTypingTarget` (Task 1) so shortcuts never fire while typing. Preconditions-absent → no-op (never throws). Built and fully unit-tested in isolation BEFORE wiring into `App.tsx` (Task 4) so each commit stays green.

Key map (from the spec):
- `Space` → stop
- `R` → restore
- `P` → pause/resume toggle (caller supplies a single `onPauseToggle`)
- `B` → bookmark-here
- `Cmd/Ctrl+K` → focus address search
- `Cmd/Ctrl+Z` → undo

**Files:**
- Create: `frontend/src/hooks/useGlobalShortcuts.ts`.
- Create: `frontend/src/hooks/useGlobalShortcuts.test.tsx`.

**Interfaces:**
- Produces:
  ```ts
  export interface GlobalShortcutHandlers {
    onStop: () => void;
    onRestore: () => void;
    onPauseToggle: () => void;
    onBookmarkHere: () => void;
    onFocusSearch: () => void;
    onUndo: () => void;
  }
  export function useGlobalShortcuts(handlers: GlobalShortcutHandlers): void;
  ```
  Mounts a `document` `keydown` listener for the component's lifetime; calls the matching handler. Each handler is OPTIONAL in effect: callers pass no-op-safe callbacks (the underlying `useSimActions` handlers are already precondition-guarded no-ops — e.g. `handleStop` with no movement, `handleUndo` with no snapshot). The hook itself only adds the typing-target + IME guards and key dispatch; it does NOT inspect app state.
- Consumes: `isTypingTarget` from `../utils/keyboard` (Task 1); the caller (`App.tsx`, Task 4) supplies the six callbacks — `onStop=handleStop`, `onRestore=handleRestore`, `onPauseToggle` (a small App-local toggle reading `sim.status`), `onBookmarkHere` (App-local `handleAddBookmark` bound to `sim.currentPosition`), `onFocusSearch` (focus the `.search-input`), `onUndo=handleUndo`.

Dispatch rules (exact, so Task 4 wires the right callbacks):
- The hook stores `handlers` in a ref updated each render (same ref-mirror technique as `useSimActions`) so the listener is mounted once (`[]` effect deps) yet always calls the latest callbacks — no stale closures, no re-subscribe churn.
- For the plain single-key shortcuts (`Space`/`R`/`P`/`B`): bail if `isTypingTarget(e.target)` OR `e.metaKey` OR `e.ctrlKey` OR `e.altKey` (a bare key with no modifier). Match on `e.code` for `Space` (`e.code === 'Space'`) and `e.key.toLowerCase()` for the letters (so `R`/`r` both match, layout-independent for letters). On match: `e.preventDefault()` then call the handler.
- For the modifier shortcuts (`Cmd/Ctrl+K`, `Cmd/Ctrl+Z`): require `(e.metaKey || e.ctrlKey)` AND NOT `e.shiftKey` AND NOT `e.altKey`; match `e.key.toLowerCase() === 'k'` / `=== 'z'`. These fire EVEN when `isTypingTarget` is true for `Cmd+K` (focus-search is useful while another field has focus) — but `Cmd+Z` bails when `isTypingTarget` so it does not hijack native text-undo in an input. On match: `e.preventDefault()` then call the handler.

- [ ] **Step 1: Write the failing tests for `useGlobalShortcuts`.** Create `frontend/src/hooks/useGlobalShortcuts.test.tsx` with this complete content:
  ```tsx
  import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
  import { renderHook } from '@testing-library/react';
  import { useGlobalShortcuts, type GlobalShortcutHandlers } from './useGlobalShortcuts';

  // Dispatch a native keydown on `document` with the given init, optionally
  // overriding the event target (jsdom KeyboardEvent.target defaults to the
  // dispatch node, i.e. document). We set `target` so we can model focus inside
  // an input without an actual focused element.
  function fireKey(init: KeyboardEventInit & { target?: EventTarget }) {
    const { target, ...rest } = init;
    const ev = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...rest });
    if (target) Object.defineProperty(ev, 'target', { value: target, configurable: true });
    document.dispatchEvent(ev);
    return ev;
  }

  function makeHandlers(): GlobalShortcutHandlers {
    return {
      onStop: vi.fn(),
      onRestore: vi.fn(),
      onPauseToggle: vi.fn(),
      onBookmarkHere: vi.fn(),
      onFocusSearch: vi.fn(),
      onUndo: vi.fn(),
    };
  }

  describe('useGlobalShortcuts', () => {
    let handlers: GlobalShortcutHandlers;

    beforeEach(() => {
      handlers = makeHandlers();
      renderHook(() => useGlobalShortcuts(handlers));
    });

    afterEach(() => {
      vi.clearAllMocks();
    });

    it('Space → onStop', () => {
      fireKey({ code: 'Space', key: ' ' });
      expect(handlers.onStop).toHaveBeenCalledTimes(1);
    });

    it('R → onRestore (case-insensitive)', () => {
      fireKey({ key: 'r' });
      fireKey({ key: 'R' });
      expect(handlers.onRestore).toHaveBeenCalledTimes(2);
    });

    it('P → onPauseToggle', () => {
      fireKey({ key: 'p' });
      expect(handlers.onPauseToggle).toHaveBeenCalledTimes(1);
    });

    it('B → onBookmarkHere', () => {
      fireKey({ key: 'b' });
      expect(handlers.onBookmarkHere).toHaveBeenCalledTimes(1);
    });

    it('Cmd+K → onFocusSearch', () => {
      fireKey({ key: 'k', metaKey: true });
      expect(handlers.onFocusSearch).toHaveBeenCalledTimes(1);
    });

    it('Ctrl+K → onFocusSearch', () => {
      fireKey({ key: 'k', ctrlKey: true });
      expect(handlers.onFocusSearch).toHaveBeenCalledTimes(1);
    });

    it('Cmd+Z → onUndo', () => {
      fireKey({ key: 'z', metaKey: true });
      expect(handlers.onUndo).toHaveBeenCalledTimes(1);
    });

    it('does NOT fire single-key Space when focus is in an INPUT', () => {
      const input = document.createElement('input');
      fireKey({ code: 'Space', key: ' ', target: input });
      expect(handlers.onStop).not.toHaveBeenCalled();
    });

    it('does NOT fire single-key R when focus is in a TEXTAREA', () => {
      const ta = document.createElement('textarea');
      fireKey({ key: 'r', target: ta });
      expect(handlers.onRestore).not.toHaveBeenCalled();
    });

    it('does NOT fire Space when a modifier is held (e.g. Cmd+Space)', () => {
      fireKey({ code: 'Space', key: ' ', metaKey: true });
      expect(handlers.onStop).not.toHaveBeenCalled();
    });

    it('Cmd+K still fires while focus is in an INPUT (focus-search is global)', () => {
      const input = document.createElement('input');
      fireKey({ key: 'k', metaKey: true, target: input });
      expect(handlers.onFocusSearch).toHaveBeenCalledTimes(1);
    });

    it('Cmd+Z does NOT fire while focus is in an INPUT (native text-undo wins)', () => {
      const input = document.createElement('input');
      fireKey({ key: 'z', metaKey: true, target: input });
      expect(handlers.onUndo).not.toHaveBeenCalled();
    });

    it('Cmd+Shift+Z does NOT fire onUndo (reserved for redo / not bound)', () => {
      fireKey({ key: 'z', metaKey: true, shiftKey: true });
      expect(handlers.onUndo).not.toHaveBeenCalled();
    });

    it('an unmapped key (e.g. X) fires nothing', () => {
      fireKey({ key: 'x' });
      expect(handlers.onStop).not.toHaveBeenCalled();
      expect(handlers.onRestore).not.toHaveBeenCalled();
      expect(handlers.onPauseToggle).not.toHaveBeenCalled();
      expect(handlers.onBookmarkHere).not.toHaveBeenCalled();
      expect(handlers.onFocusSearch).not.toHaveBeenCalled();
      expect(handlers.onUndo).not.toHaveBeenCalled();
    });

    it('calls preventDefault on a matched shortcut', () => {
      const ev = fireKey({ key: 'r' });
      expect(ev.defaultPrevented).toBe(true);
    });

    it('removes the listener on unmount (no fire after cleanup)', () => {
      const localHandlers = makeHandlers();
      const { unmount } = renderHook(() => useGlobalShortcuts(localHandlers));
      unmount();
      fireKey({ key: 'r' });
      // Only the beforeEach-mounted hook's onRestore could fire; the unmounted
      // one's must not. Assert the locally-scoped handler stayed untouched.
      expect(localHandlers.onRestore).not.toHaveBeenCalled();
    });
  });
  ```

- [ ] **Step 2: Run the tests and watch them fail.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useGlobalShortcuts.test.tsx
  ```
  Expected: the run fails to resolve `./useGlobalShortcuts` (module does not exist). Confirm it is the missing module, not a test typo.

- [ ] **Step 3: Implement `useGlobalShortcuts`.** Create `frontend/src/hooks/useGlobalShortcuts.ts` with this complete content:
  ```ts
  import { useEffect, useRef } from 'react';
  import { isTypingTarget } from '../utils/keyboard';

  export interface GlobalShortcutHandlers {
    /** Space — stop the active movement (keep simulated location). */
    onStop: () => void;
    /** R — restore real GPS. */
    onRestore: () => void;
    /** P — pause/resume toggle (caller decides which based on sim state). */
    onPauseToggle: () => void;
    /** B — bookmark the current position. */
    onBookmarkHere: () => void;
    /** Cmd/Ctrl+K — focus the address search input. */
    onFocusSearch: () => void;
    /** Cmd/Ctrl+Z — undo the last teleport. */
    onUndo: () => void;
  }

  /**
   * One app-window-scoped `document` keydown listener mapping keys to the
   * supplied handlers. Scope is the renderer window ONLY — NO Electron
   * globalShortcut (a system-wide Mac hotkey adds collision/enable complexity
   * for a case the phone-side controls already cover; deferred, see the
   * App Improvement Program design spec).
   *
   * Guards:
   *  - Single-key shortcuts (Space/R/P/B) bail when focus is in a typing target
   *    or any modifier is held, so they never fire mid-typing.
   *  - Cmd/Ctrl+K fires even inside an input (focus-search is globally useful).
   *  - Cmd/Ctrl+Z bails inside a typing target so native text-undo still works.
   *
   * Every handler is precondition-safe at the caller (the useSimActions handlers
   * are already no-ops when their precondition is absent), so the hook never
   * needs to inspect app state — it only dispatches.
   *
   * Handlers are mirrored into a ref updated each render so the listener mounts
   * ONCE (stable `[]` deps) yet always calls the latest callbacks — no stale
   * closures, no re-subscribe churn (same technique as useSimActions).
   */
  export function useGlobalShortcuts(handlers: GlobalShortcutHandlers): void {
    const handlersRef = useRef(handlers);
    handlersRef.current = handlers;

    useEffect(() => {
      const onKeyDown = (e: KeyboardEvent) => {
        const h = handlersRef.current;
        const hasMod = e.metaKey || e.ctrlKey;
        const typing = isTypingTarget(e.target);

        // ── Modifier shortcuts ──────────────────────────────────────────────
        if (hasMod && !e.shiftKey && !e.altKey) {
          const key = e.key.toLowerCase();
          if (key === 'k') {
            // Focus search works even while another field has focus.
            e.preventDefault();
            h.onFocusSearch();
            return;
          }
          if (key === 'z') {
            // Don't hijack native text-undo inside an input.
            if (typing) return;
            e.preventDefault();
            h.onUndo();
            return;
          }
          return; // other modifier combos are not ours
        }

        // ── Single-key shortcuts ────────────────────────────────────────────
        // Bail if typing or ANY modifier is held (bare keys only).
        if (typing || e.metaKey || e.ctrlKey || e.altKey) return;

        if (e.code === 'Space') {
          e.preventDefault();
          h.onStop();
          return;
        }
        const key = e.key.toLowerCase();
        if (key === 'r') {
          e.preventDefault();
          h.onRestore();
        } else if (key === 'p') {
          e.preventDefault();
          h.onPauseToggle();
        } else if (key === 'b') {
          e.preventDefault();
          h.onBookmarkHere();
        }
      };

      document.addEventListener('keydown', onKeyDown);
      return () => document.removeEventListener('keydown', onKeyDown);
    }, []);
  }
  ```

- [ ] **Step 4: Run the tests and watch them pass.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useGlobalShortcuts.test.tsx
  ```
  Expected: `17 passed`.

- [ ] **Step 5: Verify the full gate is green.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run && npm run depcruise
  ```
  Expected: `tsc` 0 errors; `vitest` total ≈801 passed; `npm run depcruise` prints `no dependency violations found`.

- [ ] **Step 6: Commit.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add frontend/src/hooks/useGlobalShortcuts.ts frontend/src/hooks/useGlobalShortcuts.test.tsx && git commit -m "$(cat <<'EOF'
feat(aip-c1): add useGlobalShortcuts hook (app-window keydown listener)

One document keydown listener mapping Space→stop, R→restore, P→pause toggle,
B→bookmark, Cmd/Ctrl+K→focus search, Cmd/Ctrl+Z→undo. Single-key shortcuts
bail via isTypingTarget + modifier check; Cmd+K fires even in inputs; Cmd+Z
yields to native text-undo inside inputs. Ref-mirrored handlers → mounted once.
Built + unit-tested in isolation; wired into App in the next task.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
  ```

---

### Task 4: Wire `useGlobalShortcuts` into `App.tsx`

Mount the listener at app level and supply the six callbacks from existing App state/handlers. `handleStop`/`handleRestore`/`handlePause`/`handleResume`/`handleUndo` come from `useSimActions` (destructured at `App.tsx:337-340` — add `handleUndo` to that destructure). `onPauseToggle` reads `sim.status` to choose pause vs resume. `onBookmarkHere` calls the App-local `handleAddBookmark` (defined at `App.tsx:355`) with `sim.currentPosition`. `onFocusSearch` focuses the address input via `document.querySelector('.search-input')` (the `AddressSearch` input carries `className="search-input"`, `AddressSearch.tsx:144`).

**Files:**
- Modify: `frontend/src/App.tsx` — add the import, add `handleUndo` to the `useSimActions` destructure (lines 337-340), define the four App-local callbacks, call `useGlobalShortcuts(...)`.
- Create: `frontend/src/App.globalShortcuts.test.tsx` — a rendered App-level characterization test mirroring the existing `App.dangerzone.test.tsx` harness.

**Interfaces:**
- Consumes: `useGlobalShortcuts` + `GlobalShortcutHandlers` from `./hooks/useGlobalShortcuts` (Task 3); `handleUndo` from `simActions` (Task 2); existing `handleStop`/`handleRestore`/`handlePause`/`handleResume` (already destructured); `sim.status?.paused` (stored boolean — used to decide pause vs resume, matches existing `App.tsx` style); `sim.currentPosition` (`{ lat, lng } | null`); `handleAddBookmark` (`(lat, lng, suggestedName?) => void`, `App.tsx:355`); `showToast`/`t` (already in scope).
- Produces: no new exported interface; wires the listener as a side effect.
- Note on `sim.status` shape: `useSimulation` exposes `sim.status?.paused` (a stored boolean, matches existing `App.tsx` style). The pause/resume toggle treats the simulation as paused when `sim.status?.paused === true` and resumes; otherwise pauses. If `sim.status` is absent, default to pause (matches the "P pauses an active run" intuition).

- [ ] **Step 1: Inspect the live `sim.status` shape BEFORE writing the toggle test.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "paused\|status?" src/hooks/useSimulation.ts | head -20; grep -rn "status?.paused\|\.paused" src/ | head
  ```
  Expected: confirms that `sim.status?.paused` is a stored boolean (matches existing `App.tsx` style). If the actual field name differs, substitute the real field everywhere it appears in Steps 2-3. Record the confirmed field before proceeding.

- [ ] **Step 2: Write the failing App-level characterization test.** First open the existing harness to mirror it exactly:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && sed -n '1,80p' src/App.dangerzone.test.tsx
  ```
  Then create `frontend/src/App.globalShortcuts.test.tsx` mirroring that file's imports, `renderApp` helper, fake-api injection via `ServicesProvider`, and `fireEvent` usage. The test body asserts the wiring end-to-end:
  ```tsx
  // MIRROR App.dangerzone.test.tsx EXACTLY for imports + the render harness
  // (ServicesProvider with a fake api, i18n, the same renderApp() helper and
  // any beforeEach/afterEach it uses). Then add this describe block. Replace
  // `renderApp` / fake-api builders with whatever names that file uses; do NOT
  // invent a new harness.
  import { describe, it, expect, vi, beforeEach } from 'vitest';
  // (import render/fireEvent/act + ServicesProvider + makeFakeApi + renderApp
  //  exactly as App.dangerzone.test.tsx does)

  describe('App — global keyboard shortcuts wiring', () => {
    it('Space dispatched on document calls api.stop (single device)', async () => {
      // Render App with a single connected device + an active simulation, using
      // the SAME fake-api builder App.dangerzone.test.tsx uses. Then:
      //   fireEvent.keyDown(document, { code: 'Space', key: ' ' })
      // Assert the fake api's stop endpoint was called (the same spied endpoint
      // App.dangerzone.test.tsx reads to detect a stop, WITHOUT a udid for the
      // single-device path).
    });

    it('a Space dispatched while an INPUT is focused does NOT call api.stop', async () => {
      // Render App, focus the address-search input (className "search-input"),
      // dispatch the same Space keydown WITH the input as the event target via
      //   fireEvent.keyDown(inputEl, { code: 'Space', key: ' ' })
      // (keyDown bubbles to document; e.target is the input → isTypingTarget true)
      // Assert api.stop was NOT called.
    });

    it('Cmd+K focuses the address-search input', async () => {
      // Render App. The .search-input must exist. Dispatch
      //   fireEvent.keyDown(document, { key: 'k', metaKey: true })
      // Assert document.activeElement is the .search-input element.
    });
  });
  ```
  IMPORTANT for the implementer: do NOT guess the dangerzone harness — read it first (the `sed` above) and copy its exact `render`/`ServicesProvider`/fake-api/`renderApp` shape. Use `fireEvent.keyDown(target, init)` (fireEvent is the only API installed — `@testing-library/user-event` is NOT available). For the Space-while-typing case, dispatch the keyDown on the focused input element so it bubbles to the `document` listener with `e.target` = the input. If wiring App to a fully-active single-device simulation is heavier than the dangerzone harness supports, narrow the first assertion to "Space triggers the same `onStop` path the ControlPanel Stop button triggers" by spying the same fake-api endpoint that file already spies; keep the typing-guard + Cmd+K assertions as the load-bearing ones.

- [ ] **Step 3: Run the new test and watch it fail.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/App.globalShortcuts.test.tsx
  ```
  Expected: failures because `useGlobalShortcuts` is not wired into App yet (Space does nothing; Cmd+K does not focus the input). Confirm the failures are the missing wiring, not harness errors.

- [ ] **Step 4: Add the import to App.tsx.** In `frontend/src/App.tsx`, after the existing `import { useSimActions } from './hooks/useSimActions'` line (line 14), add:
  ```ts
  import { useGlobalShortcuts } from './hooks/useGlobalShortcuts'
  ```

- [ ] **Step 5: Destructure `handleUndo` from `simActions`.** Change the destructure block at `App.tsx:337-340` from:
  ```ts
  const {
    handleRestore, handleTeleport, handleNavigate,
    handleStart, handleStop, handleApplySpeed, handlePause, handleResume,
  } = simActions
  ```
  to:
  ```ts
  const {
    handleRestore, handleTeleport, handleNavigate,
    handleStart, handleStop, handleApplySpeed, handlePause, handleResume,
    handleUndo,
  } = simActions
  ```

- [ ] **Step 6: Define the four App-local shortcut callbacks + mount the hook.** In `App.tsx`, AFTER the `handleAddBookmark` definition completes (it ends with its `useCallback` closing — find the `}, [...])` that closes the `useCallback` started at line 355) and AFTER the `simActions` destructure, add this block (place it after both are in scope; if `handleAddBookmark` is defined below the destructure, place this block after `handleAddBookmark`):
  ```ts
  // ── App-window keyboard shortcuts (Cluster 1) ────────────────────────────
  // Scope = renderer window only (NO Electron globalShortcut). Maps keys to the
  // existing precondition-guarded handlers, so each is a safe no-op when its
  // precondition is absent.
  const onPauseToggle = useCallback(() => {
    // Resume if currently paused, otherwise pause. sim.status?.paused is read
    // through the latest sim object captured by this callback's render.
    if (sim.status?.paused) {
      void handleResume()
    } else {
      void handlePause()
    }
  }, [sim.status?.paused, handlePause, handleResume])

  const onBookmarkHere = useCallback(() => {
    if (!sim.currentPosition) {
      showToast(t('toast.no_position_random'))
      return
    }
    handleAddBookmark(sim.currentPosition.lat, sim.currentPosition.lng)
  }, [sim.currentPosition, handleAddBookmark, showToast, t])

  const onFocusSearch = useCallback(() => {
    const input = document.querySelector<HTMLInputElement>('.search-input')
    input?.focus()
  }, [])

  useGlobalShortcuts({
    onStop: handleStop,
    onRestore: handleRestore,
    onPauseToggle,
    onBookmarkHere,
    onFocusSearch,
    onUndo: handleUndo,
  })
  ```
  IMPORTANT: confirm the `sim.status?.paused` field matches what Step 1 found; substitute the real field name if different. If `handleAddBookmark` is declared AFTER the `simActions` destructure (it is — line 355 vs 337), this block MUST be placed after line ~430 (after `handleAddBookmark`'s `useCallback` closes) so all referenced handlers are in scope. The handler identities are all stable (`useCallback`), so the hook's ref-mirror keeps the listener mounted once.

- [ ] **Step 7: Run the test and watch it pass.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/App.globalShortcuts.test.tsx
  ```
  Expected: all assertions in the new file pass (Space stops single-device; Space-in-input no-ops; Cmd+K focuses the search input).

- [ ] **Step 8: Verify the full gate is green.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run && npm run depcruise
  ```
  Expected: `tsc` 0 errors; `vitest` total ≈804 passed (no regressions in `App.dangerzone.test.tsx` / `App.renderCount.test.tsx` — the listener is mounted once, no extra re-renders); `npm run depcruise` prints `no dependency violations found`.

- [ ] **Step 9: Commit.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add frontend/src/App.tsx frontend/src/App.globalShortcuts.test.tsx && git commit -m "$(cat <<'EOF'
feat(aip-c1): wire app-window keyboard shortcuts into App

Mount useGlobalShortcuts at app level: Space→stop, R→restore, P→pause/resume
toggle (reads sim.status), B→bookmark current position, Cmd/Ctrl+K→focus the
address search, Cmd/Ctrl+Z→undo. Reuses the stable useSimActions handlers; new
App-local callbacks are precondition-safe no-ops. App-level only, no globalShortcut.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
  ```

---

### Task 5: Address-search keyboard navigation (ArrowUp/Down + Enter, IME-safe)

Add `selectedIndex` state to `AddressSearch.tsx`'s results list. ArrowDown/ArrowUp move the highlight (CLAMP at the ends — simpler than wrap, per spec); row 0 is highlighted by default so a bare Enter flies to the top result. Enter commits the highlighted row through the existing `isSubmitEnter` IME guard (so a candidate-confirming Enter mid-composition does NOT submit). The highlight is reset to 0 whenever a fresh result set arrives.

**Files:**
- Modify: `frontend/src/components/AddressSearch.tsx` — add `selectedIndex` state (near the other `useState`s, ~lines 23-27), reset it when results change (in `doSearch`, lines 73-102), add an `onKeyDown` on the search `<input>` (the input at lines 142-150), highlight the row whose index matches `selectedIndex` in the results `.map` (lines 447-481).
- Modify: `frontend/src/components/AddressSearch.test.tsx` — add keyboard-nav tests (existing file ends at line 152).

**Interfaces:**
- Consumes: existing `isSubmitEnter` from `../utils/keyboard` (already imported, line 2); existing `results` state (`SearchResult[]`), `handleSelect(result)` (line 111), `showResults` state.
- Produces: no new export; internal `selectedIndex: number` state + an input `onKeyDown` handler.

Behaviour spec (exact):
- `selectedIndex` initial `0`.
- On a successful search that sets results (`setResults(mapped)`), reset `selectedIndex` to `0`.
- Input `onKeyDown`:
  - `ArrowDown`: `e.preventDefault()`; `setSelectedIndex(i => Math.min(i + 1, results.length - 1))` (clamp at last). No-op effect when `results.length === 0`.
  - `ArrowUp`: `e.preventDefault()`; `setSelectedIndex(i => Math.max(i - 1, 0))` (clamp at first).
  - Enter: if `isSubmitEnter(e)` AND `showResults` AND `results.length > 0` AND `results[selectedIndex]` exists: `e.preventDefault()`; `handleSelect(results[selectedIndex])`. Mid-IME-composition Enter is NOT a submit (guarded by `isSubmitEnter`), so it does nothing.
- The highlighted row's background is `#3a3a3e` (the same hover color already used) when `idx === selectedIndex`; otherwise transparent. Keep the existing `onMouseEnter`/`onMouseLeave` hover behavior, but make `onMouseEnter` also `setSelectedIndex(idx)` so mouse and keyboard share one highlight source of truth.

- [ ] **Step 1: Write the failing keyboard-nav tests.** Append to `frontend/src/components/AddressSearch.test.tsx` (after the final test, before the `});` that closes the `describe` at line 152 — insert the new `it` blocks inside the existing `describe('AddressSearch', ...)`):
  ```tsx

    it('highlights the first result by default; bare Enter commits the top result', async () => {
      mockedSearch.mockResolvedValue([
        { display_name: 'Kyoto Station', lat: 34.9858, lng: 135.7588 },
        { display_name: 'Kyoto Tower', lat: 34.9875, lng: 135.7591 },
      ]);
      const onSelect = vi.fn();
      render(<AddressSearch onSelect={onSelect} />);
      const input = screen.getByPlaceholderText('search.placeholder');
      fireEvent.change(input, { target: { value: 'kyoto' } });
      await flushDebounce();

      fireEvent.keyDown(input, { key: 'Enter' });
      // Default highlight is row 0 → top result committed.
      expect(onSelect).toHaveBeenCalledWith(34.9858, 135.7588, 'Kyoto Station');
    });

    it('ArrowDown then Enter commits the SECOND result, not the first', async () => {
      mockedSearch.mockResolvedValue([
        { display_name: 'Kyoto Station', lat: 34.9858, lng: 135.7588 },
        { display_name: 'Kyoto Tower', lat: 34.9875, lng: 135.7591 },
      ]);
      const onSelect = vi.fn();
      render(<AddressSearch onSelect={onSelect} />);
      const input = screen.getByPlaceholderText('search.placeholder');
      fireEvent.change(input, { target: { value: 'kyoto' } });
      await flushDebounce();

      fireEvent.keyDown(input, { key: 'ArrowDown' });
      fireEvent.keyDown(input, { key: 'Enter' });
      expect(onSelect).toHaveBeenCalledWith(34.9875, 135.7591, 'Kyoto Tower');
    });

    it('ArrowDown clamps at the last result (does not wrap past the end)', async () => {
      mockedSearch.mockResolvedValue([
        { display_name: 'A', lat: 1, lng: 1 },
        { display_name: 'B', lat: 2, lng: 2 },
      ]);
      const onSelect = vi.fn();
      render(<AddressSearch onSelect={onSelect} />);
      const input = screen.getByPlaceholderText('search.placeholder');
      fireEvent.change(input, { target: { value: 'ab' } });
      await flushDebounce();

      fireEvent.keyDown(input, { key: 'ArrowDown' });
      fireEvent.keyDown(input, { key: 'ArrowDown' });
      fireEvent.keyDown(input, { key: 'ArrowDown' }); // clamped at index 1
      fireEvent.keyDown(input, { key: 'Enter' });
      expect(onSelect).toHaveBeenCalledWith(2, 2, 'B');
    });

    it('ArrowUp clamps at the first result', async () => {
      mockedSearch.mockResolvedValue([
        { display_name: 'A', lat: 1, lng: 1 },
        { display_name: 'B', lat: 2, lng: 2 },
      ]);
      const onSelect = vi.fn();
      render(<AddressSearch onSelect={onSelect} />);
      const input = screen.getByPlaceholderText('search.placeholder');
      fireEvent.change(input, { target: { value: 'ab' } });
      await flushDebounce();

      fireEvent.keyDown(input, { key: 'ArrowDown' });
      fireEvent.keyDown(input, { key: 'ArrowUp' });
      fireEvent.keyDown(input, { key: 'ArrowUp' }); // clamped at index 0
      fireEvent.keyDown(input, { key: 'Enter' });
      expect(onSelect).toHaveBeenCalledWith(1, 1, 'A');
    });

    it('Enter mid-IME-composition does NOT commit (isImeComposing guard)', async () => {
      mockedSearch.mockResolvedValue([
        { display_name: 'Kyoto Station', lat: 34.9858, lng: 135.7588 },
      ]);
      const onSelect = vi.fn();
      render(<AddressSearch onSelect={onSelect} />);
      const input = screen.getByPlaceholderText('search.placeholder');
      fireEvent.change(input, { target: { value: 'kyoto' } });
      await flushDebounce();

      // isComposing true → not a submit Enter.
      fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
      expect(onSelect).not.toHaveBeenCalled();
    });

    it('Enter with no results does nothing', () => {
      const onSelect = vi.fn();
      render(<AddressSearch onSelect={onSelect} />);
      const input = screen.getByPlaceholderText('search.placeholder');
      fireEvent.keyDown(input, { key: 'Enter' });
      expect(onSelect).not.toHaveBeenCalled();
    });
  ```

- [ ] **Step 2: Run the new tests and watch them fail.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/AddressSearch.test.tsx
  ```
  Expected: the 6 new tests fail (`onSelect` not called on Enter / ArrowDown — no keyboard nav yet). The 10 pre-existing tests still pass.

- [ ] **Step 3: Add the `selectedIndex` state.** In `frontend/src/components/AddressSearch.tsx`, after the `const [showResults, setShowResults] = useState(false);` line (line 26), add:
  ```ts
  const [selectedIndex, setSelectedIndex] = useState(0);
  ```

- [ ] **Step 4: Reset the highlight when fresh results arrive.** In `doSearch` (line 73), immediately after `setResults(mapped);` (line 91), add:
  ```ts
        setSelectedIndex(0);
  ```

- [ ] **Step 5: Add the keyboard handler to the input.** In the search `<input>` element (lines 142-150), add an `onKeyDown` prop after the existing `onFocus` prop (line 148):
  ```tsx
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setSelectedIndex((i) => Math.min(i + 1, results.length - 1));
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setSelectedIndex((i) => Math.max(i - 1, 0));
              } else if (isSubmitEnter(e)) {
                if (showResults && results.length > 0) {
                  const chosen = results[selectedIndex];
                  if (chosen) {
                    e.preventDefault();
                    handleSelect(chosen);
                  }
                }
              }
            }}
  ```

- [ ] **Step 6: Highlight the selected row in the results map.** In the results `.map` (lines 447-481), change the result row `<div>`'s inline `style` `background`/hover so the selected index is highlighted, and make `onMouseEnter` sync `selectedIndex`. Change the row's opening `<div>` block from:
  ```tsx
            <div
              key={idx}
              className="search-result-item"
              style={{
                padding: '8px 12px', cursor: 'pointer',
                borderBottom: idx < results.length - 1 ? '1px solid #333' : 'none',
                fontSize: 13, transition: 'background 0.15s',
              }}
              onClick={() => handleSelect(result)}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = 'transparent'; }}
            >
  ```
  to:
  ```tsx
            <div
              key={idx}
              className="search-result-item"
              style={{
                padding: '8px 12px', cursor: 'pointer',
                borderBottom: idx < results.length - 1 ? '1px solid #333' : 'none',
                fontSize: 13, transition: 'background 0.15s',
                background: idx === selectedIndex ? '#3a3a3e' : 'transparent',
              }}
              onClick={() => handleSelect(result)}
              onMouseEnter={() => setSelectedIndex(idx)}
              onMouseLeave={() => { /* keyboard/selectedIndex owns the highlight */ }}
            >
  ```

- [ ] **Step 7: Run the tests and watch them pass.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/components/AddressSearch.test.tsx
  ```
  Expected: `16 passed` (10 pre-existing + 6 new). Confirm the pre-existing "fires onSelect when a result is clicked" test still passes (the `onClick` path is unchanged).

- [ ] **Step 8: Verify the full gate is green.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run && npm run depcruise
  ```
  Expected: `tsc` 0 errors; `vitest` total ≈810 passed; `npm run depcruise` prints `no dependency violations found`.

- [ ] **Step 9: Commit.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add frontend/src/components/AddressSearch.tsx frontend/src/components/AddressSearch.test.tsx && git commit -m "$(cat <<'EOF'
feat(aip-c1): keyboard navigation for address-search results

ArrowUp/ArrowDown move a highlight (clamped at the ends), row 0 highlighted by
default so a bare Enter flies to the top result. Enter commits the highlighted
row through the existing isSubmitEnter IME guard (candidate-confirming Enter
mid-composition does not submit). Mouse hover shares the same selectedIndex.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
  ```

---

### Task 6: Undo affordance on the teleport toast (optional surface) + cluster verification

The spec calls for "an Undo affordance on the teleport toast + the keybinding." The keybinding ships in Task 4. This task adds a lightweight Undo hint to the teleport success toast so the affordance is discoverable, then runs the whole-cluster verification. The toast surface (`useToast` → `toastMsg` string) is plain-string today, so the discoverable affordance is a textual hint appended to the teleport toast ("Undo: ⌘Z"), keeping the change minimal and within the existing single-string toast model (no new toast component, no behavior change to other toasts).

**Files:**
- Modify: `frontend/src/i18n/strings.ts` — add a single flat `'toast.teleport_undo_hint': { zh: ..., en: ... }` entry for the hint text. (Survey the file first to confirm the flat-map shape.)
- Modify: `frontend/src/hooks/useSimActions.ts` — on the SINGLE-device successful teleport path (after `await sim.teleport(lat, lng)` succeeds, currently inside the `else` branch ~lines 172-178), show a brief toast with the undo hint. Do NOT change the dual-device path (it already toasts a fan-out summary). Guard: only show the hint when a `lastPositionRef` snapshot exists (i.e. there is something to undo).
- Modify: `frontend/src/hooks/useSimActions.test.tsx` — add a test that the single-device teleport shows the undo-hint toast.

**Interfaces:**
- Consumes: `lastPositionRef` (Task 2), `showToastRef`, `tRef`; the new i18n key `toast.teleport_undo_hint`.
- Produces: no new export.

- [ ] **Step 1: Survey the i18n strings shape.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && grep -n "teleport_failed\|'toast\.\|toast:" src/i18n/strings.ts | head -20
  ```
  Expected: shows the flat-map structure — entries like `'toast.teleport_failed': { zh: '瞬移失敗', en: 'Teleport failed' }`. Note the exact quoting/comma style to mirror.

- [ ] **Step 2: Write the failing test.** Append inside the `describe('useSimActions — teleport', ...)` block in `frontend/src/hooks/useSimActions.test.tsx` (before that describe's closing `})` at line 157) — note the stub `t` returns the key for unmapped keys, so `toast.teleport_undo_hint` echoes verbatim:
  ```ts

    it('single device: shows the undo-hint toast after a successful teleport (snapshot present)', async () => {
      const sim = makeSim({ currentPosition: { lat: 1, lng: 2 } })
      const { result, showToast } = setup({ udids: ['A'], sim })
      await act(async () => { await result.current.handleTeleport(10, 20) })
      // teleport succeeded and there was a prior position to snapshot → hint shown.
      expect(showToast).toHaveBeenCalledWith('toast.teleport_undo_hint')
    })

    it('single device: NO undo-hint toast when there was no prior position', async () => {
      const sim = makeSim({ currentPosition: null })
      const { result, showToast } = setup({ udids: ['A'], sim })
      await act(async () => { await result.current.handleTeleport(10, 20) })
      expect(showToast).not.toHaveBeenCalledWith('toast.teleport_undo_hint')
    })
  ```

- [ ] **Step 3: Run the new tests and watch them fail.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useSimActions.test.tsx
  ```
  Expected: the 2 new tests fail (no `toast.teleport_undo_hint` toast yet). All others (43 from Task 2 + the existing) still pass.

- [ ] **Step 4: Add the i18n key.** In `frontend/src/i18n/strings.ts`, add a SINGLE flat entry next to the existing `'toast.teleport_failed'` line (the file is a flat map of `'key': { zh, en }` entries — there are no separate per-locale objects):
  ```ts
  'toast.teleport_undo_hint': { zh: '已傳送 — 按 ⌘Z / Ctrl+Z 復原', en: 'Teleported — press ⌘Z / Ctrl+Z to undo' },
  ```

- [ ] **Step 5: Show the hint on the single-device success path.** In `handleTeleport` (`frontend/src/hooks/useSimActions.ts`), the single-device `else` branch currently is:
  ```ts
      try {
        await sim.teleport(lat, lng)
      } catch {
        showToast(t('toast.teleport_failed'))
        return
      }
  ```
  Change it to show the undo hint on success when a snapshot exists:
  ```ts
      try {
        await sim.teleport(lat, lng)
        if (lastPositionRef.current) {
          showToast(t('toast.teleport_undo_hint'))
        }
      } catch {
        showToast(t('toast.teleport_failed'))
        return
      }
  ```
  (`showToast` and `t` are the locals already destructured at the top of `handleTeleport`, lines 154-155; `lastPositionRef` was added in Task 2.)

- [ ] **Step 6: Run the tests and watch them pass.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx vitest run src/hooks/useSimActions.test.tsx
  ```
  Expected: `45 passed`. Re-check that the pre-existing "single device: calls sim.teleport WITHOUT a udid; never the *All variant" test (which asserted `expect(showToast).not.toHaveBeenCalled()`) — it uses `currentPosition: { lat: 1, lng: 2 }`, so the hint WOULD now fire. UPDATE that one pre-existing assertion: change its final line from `expect(showToast).not.toHaveBeenCalled()` to `expect(showToast).toHaveBeenCalledWith('toast.teleport_undo_hint')` (it is the documented new behavior; the test at lines 109-116). Re-run until green.

- [ ] **Step 7: Run the FULL frontend gate.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/frontend && npx tsc --noEmit && npx vitest run && npm run depcruise
  ```
  Expected: `tsc` 0 errors; `vitest` total ≈812 passed, 0 failed; `npm run depcruise` prints `no dependency violations found` (0/0).

- [ ] **Step 8: Run the backend gate (must stay untouched/green).** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m lint_imports
  ```
  Expected: pytest all pass (≈949 collected, unchanged — this cluster touched no backend file); import-linter `7 kept, 0 broken`. (If `lint_imports` is invoked differently in this repo, run the same command the CI gate uses — confirm `7 kept, 0 broken`.)

- [ ] **Step 9: Commit.** Run:
  ```bash
  cd /Users/raviwu/personal/locwarp && git add frontend/src/i18n/strings.ts frontend/src/hooks/useSimActions.ts frontend/src/hooks/useSimActions.test.tsx && git commit -m "$(cat <<'EOF'
feat(aip-c1): discoverable Undo hint on single-device teleport toast

After a successful single-device teleport (when a prior position was
snapshotted), toast a hint that ⌘Z / Ctrl+Z undoes it — making the new Undo
keybinding discoverable. Dual-device path unchanged (already toasts a summary).
Concludes Cluster 1 (Keyboard Reflexes): address-search nav, app-window
shortcuts, single-level Undo.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017KcNYhNQFqMDYmzkh7dhJw
EOF
)"
  ```
