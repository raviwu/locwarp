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
