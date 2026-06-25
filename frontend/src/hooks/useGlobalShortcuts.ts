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
