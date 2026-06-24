# SH4 — a11y / i18n / Cosmetic / Dedup / Coordinate-Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the core surfaces to a baseline of keyboard/screen-reader accessibility, finish i18n, apply the existing design tokens, dedup the hand-rolled dialogs behind one `DialogShell`, fix a drag-listener leak, and resolve coordinate ownership (delete the dead backend parser + consolidate the two frontend decimal helpers). The FINAL stability-hardening batch.

**Architecture:** 16 bite-sized TDD tasks across 3 clusters: T1 modal/dialog a11y + `DialogShell` dedup (X13×3 build+migrate, U23, U20), T2 menu/row/chip keyboard a11y + toast aria-live (U19, U22×4, U21), T3 i18n + design tokens + drag-leak + coordinate ownership (U24, U27, U28, X10/A15, X11).

**Tech Stack:** React 18 + TypeScript + vitest + @testing-library/react (frontend); Python/pytest (the one backend coord-delete task).

## Global Constraints

- **Mostly ADDITIVE (behavior change is fine here):** a11y attributes/keyboard handlers, i18n strings, design-token usage. The EXCEPTION is the coordinate-ownership task — see below.
- **`@testing-library/user-event` is NOT installed** (only `@testing-library/{dom,react,jest-dom}`) and NO new dependency may be added. All keyboard/interaction tests use `fireEvent` ONLY (the house style).
- **Baselines:** frontend `npx vitest run` => **708 passed / 92 files**, `npx tsc --noEmit` => 0 errors, `npx depcruise src` => 0 errors; backend `pytest --collect-only -q` => **981 collected**, `lint-imports` => 7 kept/0 broken.
- **Full green after every commit.** After EACH commit: `npx tsc --noEmit` 0 + `npx vitest run` green; for the backend coord task `pytest -q` green + `lint-imports` 7/0.
- **Coordinate ownership (X10/A15 + X11) is BEHAVIOR-PRESERVING for what remains:** X10 DELETES the dead backend `CoordinateFormatter` parser (unreachable from the UI; its DMS negative-degree bug A15 disappears with it) and KEEPS the `.format` enum passthrough; this REMOVES the dead dialect tests, so the **backend collection DROPS** below 981 (expected — state the new count). X11 CONSOLIDATES the two divergent frontend decimal coord helpers WITHOUT changing what either dialog currently accepts (characterization test first). **DMS/DM paste support is OUT OF SCOPE** (adding it would be a feature, not hardening).
- **T1 ordering:** build `DialogShell` (Task 1) FIRST — every other T1 task imports it. Migrations keep each dialog's exact look/submit/cancel; they ADD only focus-trap/Escape/initial-focus.
- New user-facing strings get BOTH `zh` + `en` in `frontend/src/i18n/strings.ts`; tests use `localStorage.locwarp.lang='en'`.
- **Line numbers are audit/draft-time anchors** (SH1+SH2+SH3 already edited these files) — locate by CONTENT.
- **Personal repo:** direct commits; identity auto-set by `~/.gitconfig` — never pass `-c user.email=...`.

---


<!-- ===== T1 · Modal/dialog a11y + DialogShell dedup ===== -->

### Task 1: Build the shared DialogShell primitive (portal + backdrop + Escape + focus trap + initial focus + busy-lock)

**Files:**
- Create: `frontend/src/components/DialogShell.tsx`
- Test: `frontend/src/components/DialogShell.test.tsx`

**Interfaces:**
- Consumes: none
- Produces: `DialogShell` (default export) with props `{ open: boolean; onClose: () => void; busy?: boolean; labelledBy?: string; initialFocusRef?: React.RefObject<HTMLElement>; backdropStyle?: React.CSSProperties; panelStyle?: React.CSSProperties; panelClassName?: string; backdropClassName?: string; panelProps?: React.HTMLAttributes<HTMLDivElement>; children: React.ReactNode }`. Migrations in later tasks rely on these exact prop names. The panel renders with `role="dialog"` + `aria-modal="true"`.

This is the shared primitive every other T1 task migrates onto. It MUST exist and be green BEFORE any migration task starts.

**Dependency note:** `@testing-library/user-event` is NOT installed in this repo (only `@testing-library/{dom,react,jest-dom}`), and the HARD rule forbids adding a dependency. ALL tests below use `fireEvent` only — no `userEvent`. The neighboring tests confirm this is the house style (`render, screen, fireEvent` from `@testing-library/react`).

Behavior contract (matches the copy-pasted overlays seen across the existing dialogs — `position: fixed; inset 0; rgba(8,10,20,0.55) backdrop; blur(4px); zIndex; centered flex`):
- Renders `null` when `open === false`.
- Renders into `document.body` via `createPortal`.
- Outer backdrop `onClick` calls `onClose` UNLESS `busy` is true (the `showRepairConfirm` modal already gates backdrop-close on `repairState === 'running'`, and `BulkPasteDialog` gates on its `busy` prop; `busy` generalizes both).
- Inner panel stops click propagation (`onClick={(e) => e.stopPropagation()}`) so a click inside never closes.
- `Escape` keydown (document-level listener, capture phase) calls `onClose` UNLESS `busy` is true.
- On open, focus moves to `initialFocusRef.current` if provided, else the first focusable element inside the panel.
- Tab / Shift+Tab cycle stays trapped inside the panel (focus trap).
- Panel carries `role="dialog"`, `aria-modal="true"`, and `aria-labelledby={labelledBy}` when `labelledBy` is set.
- Caller-supplied `backdropStyle` / `panelStyle` merge OVER the defaults so each migrated dialog keeps its existing exact look (width/padding/border/boxShadow).

- [ ] **Step 1: Write the failing test** — create `frontend/src/components/DialogShell.test.tsx` (fireEvent-only, no userEvent):
```tsx
import React, { useRef } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import DialogShell from './DialogShell';

describe('DialogShell', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <DialogShell open={false} onClose={() => {}}><button>Inner</button></DialogShell>,
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('renders a role=dialog aria-modal panel into a portal when open', () => {
    render(
      <DialogShell open onClose={() => {}}><button>Inner</button></DialogShell>,
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByText('Inner')).toBeTruthy();
  });

  it('wires aria-labelledby when labelledBy is provided', () => {
    render(
      <DialogShell open onClose={() => {}} labelledBy="shell-title">
        <h2 id="shell-title">Title</h2>
      </DialogShell>,
    );
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-labelledby', 'shell-title');
  });

  it('closes on Escape', () => {
    const onClose = vi.fn();
    render(<DialogShell open onClose={onClose}><button>Inner</button></DialogShell>);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does NOT close on Escape when busy', () => {
    const onClose = vi.fn();
    render(<DialogShell open onClose={onClose} busy><button>Inner</button></DialogShell>);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on backdrop click but not on panel click', () => {
    const onClose = vi.fn();
    render(<DialogShell open onClose={onClose}><button>Inner</button></DialogShell>);
    // Panel click does not close.
    fireEvent.click(screen.getByRole('dialog'));
    expect(onClose).not.toHaveBeenCalled();
    // Backdrop is the dialog panel's parent.
    const backdrop = screen.getByRole('dialog').parentElement!;
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does NOT close on backdrop click when busy', () => {
    const onClose = vi.fn();
    render(<DialogShell open onClose={onClose} busy><button>Inner</button></DialogShell>);
    const backdrop = screen.getByRole('dialog').parentElement!;
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('focuses the initialFocusRef target on open', () => {
    const Harness = () => {
      const ref = useRef<HTMLInputElement>(null);
      return (
        <DialogShell open onClose={() => {}} initialFocusRef={ref}>
          <button>First</button>
          <input ref={ref} aria-label="target" />
        </DialogShell>
      );
    };
    render(<Harness />);
    expect(document.activeElement).toBe(screen.getByLabelText('target'));
  });

  it('focuses the first focusable element when no initialFocusRef given', () => {
    render(
      <DialogShell open onClose={() => {}}>
        <button>First</button>
        <button>Second</button>
      </DialogShell>,
    );
    expect(document.activeElement).toBe(screen.getByText('First'));
  });

  it('traps Tab focus inside the panel (wraps from last back to first)', () => {
    render(
      <DialogShell open onClose={() => {}}>
        <button>First</button>
        <button>Last</button>
      </DialogShell>,
    );
    const first = screen.getByText('First');
    const last = screen.getByText('Last');
    expect(document.activeElement).toBe(first);
    // Move focus to the last item, then Tab forward -> wraps to first.
    last.focus();
    fireEvent.keyDown(last, { key: 'Tab' });
    expect(document.activeElement).toBe(first);
  });

  it('traps Shift+Tab focus inside the panel (wraps from first back to last)', () => {
    render(
      <DialogShell open onClose={() => {}}>
        <button>First</button>
        <button>Last</button>
      </DialogShell>,
    );
    const first = screen.getByText('First');
    const last = screen.getByText('Last');
    // Focus starts on first; Shift+Tab backward -> wraps to last.
    fireEvent.keyDown(first, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
  });
});
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/DialogShell.test.tsx`. Expected failure: `Failed to resolve import "./DialogShell"` (the file does not exist yet).

- [ ] **Step 3: Implement** — create `frontend/src/components/DialogShell.tsx`. Default backdrop + panel styles lifted from the existing copy-pasted overlays (e.g. CustomBookmarkDialog lines ~80-97). The `onKeyDown` Tab-trap lives on the panel (React synthetic handler); a keydown on any inner focusable bubbles to it, so `fireEvent.keyDown(last, {key:'Tab'})` reaches it:
```tsx
import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

interface DialogShellProps {
  open: boolean;
  onClose: () => void;
  // When true, Escape and backdrop-click do NOT close (mirrors the
  // repairState === 'running' gate on the WiFi repair modal and the
  // BulkPasteDialog busy gate).
  busy?: boolean;
  // id of the heading element inside children, wired to aria-labelledby.
  labelledBy?: string;
  // Element to focus on open; falls back to the first focusable in the panel.
  initialFocusRef?: React.RefObject<HTMLElement>;
  backdropStyle?: React.CSSProperties;
  panelStyle?: React.CSSProperties;
  panelClassName?: string;
  backdropClassName?: string;
  panelProps?: React.HTMLAttributes<HTMLDivElement>;
  children: React.ReactNode;
}

const DEFAULT_BACKDROP: React.CSSProperties = {
  position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
  background: 'rgba(8, 10, 20, 0.55)',
  backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)',
  zIndex: 1000,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

const DialogShell: React.FC<DialogShellProps> = ({
  open, onClose, busy = false, labelledBy, initialFocusRef,
  backdropStyle, panelStyle, panelClassName, backdropClassName, panelProps, children,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);

  // Escape-to-close (capture phase so it fires before inner inputs swallow it).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onClose();
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [open, busy, onClose]);

  // Initial focus on open.
  useEffect(() => {
    if (!open) return;
    const target = initialFocusRef?.current
      ?? panelRef.current?.querySelector<HTMLElement>(FOCUSABLE)
      ?? null;
    target?.focus();
  }, [open, initialFocusRef]);

  if (!open) return null;

  const focusables = (): HTMLElement[] =>
    Array.from(panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);

  const onPanelKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'Tab') return;
    const items = focusables();
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div
      className={backdropClassName}
      onClick={() => { if (!busy) onClose(); }}
      style={{ ...DEFAULT_BACKDROP, ...backdropStyle }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        className={panelClassName}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onPanelKeyDown}
        style={panelStyle}
        {...panelProps}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
};

export default DialogShell;
```

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/DialogShell.test.tsx`. Expected: all DialogShell tests PASS.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) + `npx vitest run` (all green; baseline 708 passed / 92 files grows by the new DialogShell file, +11 tests). `npm run depcruise` must stay 0 errors (DialogShell imports only `react` + `react-dom`).

- [ ] **Step 6: Commit** — `git add frontend/src/components/DialogShell.tsx frontend/src/components/DialogShell.test.tsx` then `git commit -m "feat(fe): add shared DialogShell (portal + backdrop + Escape + focus trap + initial focus)"`


---

### Task 2: Migrate CustomBookmarkDialog + EditBookmarkDialog onto DialogShell

**Files:**
- Modify: `frontend/src/components/CustomBookmarkDialog.tsx` (the `return createPortal(...)` block — the outer `<div onClick={onClose} className="anim-fade-in" ...>` backdrop + inner panel `<div onClick={(e) => e.stopPropagation()} className="anim-scale-in" ...>`)
- Modify: `frontend/src/components/EditBookmarkDialog.tsx` (same `createPortal` overlay block; note its render guard is `if (!bookmark) return null;`, NOT an `open` prop)
- Test: `frontend/src/components/CustomBookmarkDialog.test.tsx` (extend), `frontend/src/components/EditBookmarkDialog.test.tsx` (extend)

**Interfaces:**
- Consumes: `DialogShell`
- Produces: none

**Prop mapping (verified):** `CustomBookmarkDialog` IS controlled by an `open: boolean` prop -> `open={open}`. `EditBookmarkDialog` is controlled by a `bookmark: DialogBookmark | null` prop (no `open`) -> `open={bookmark != null}`. Do NOT pass `open={open}` to EditBookmarkDialog — that prop does not exist there.

Both dialogs already have backdrop-click-close. CustomBookmarkDialog's name input has `onKeyDown` that runs both `if (isSubmitEnter(e)) handleSubmit();` AND `if (e.key === 'Escape') onClose();`. EditBookmarkDialog's name input `onKeyDown` only has `if (e.key === 'Escape') onClose();` (no submit-on-enter). Both inputs use `autoFocus`. Migrating to DialogShell makes Escape work from anywhere in the panel and adds the focus trap, WITHOUT changing what `onSubmit` / `onClose` emit. Keep each inline panel `style` object by passing it as `panelStyle`, and keep the `anim-fade-in` / `anim-scale-in` classes via `backdropClassName` / `panelClassName`.

- [ ] **Step 1: Write the failing test** — append to `frontend/src/components/CustomBookmarkDialog.test.tsx` (it already mocks `../i18n` and imports `render, screen, fireEvent, vi`; its `makeProps` spreads `over`, so `makeProps({ name, lat, lng, category, onSubmit })` works):
```tsx
  it('exposes the panel as a role=dialog (a11y)', () => {
    render(<CustomBookmarkDialog {...makeProps()} />);
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
  });

  it('closes on Escape pressed anywhere in the dialog', () => {
    const onClose = vi.fn();
    render(<CustomBookmarkDialog {...makeProps({ onClose })} />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('still submits the validated bookmark unchanged after migration', () => {
    const onSubmit = vi.fn();
    render(
      <CustomBookmarkDialog
        {...makeProps({ name: 'Pin', lat: '24.14', lng: '120.65', category: 'Work', onSubmit })}
      />,
    );
    fireEvent.click(screen.getByText('generic.add'));
    expect(onSubmit).toHaveBeenCalledWith({ name: 'Pin', lat: 24.14, lng: 120.65, category: 'Work' });
  });
```
Append the analogous block to `frontend/src/components/EditBookmarkDialog.test.tsx` (its `makeProps` uses the `ORIG` bookmark + `name/lat/lng` string props): a `role=dialog` + `aria-modal` assertion, an Escape-from-document-closes test, and a re-assertion that the existing Save path still emits `onSubmit('bm-1', { ...ORIG, name, lat, lng })` (mirror the existing "submits the merged shape" test).

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/CustomBookmarkDialog.test.tsx src/components/EditBookmarkDialog.test.tsx -t "role=dialog"`. Expected failure: `Unable to find an accessible element with the role "dialog"` (the hand-rolled overlay has no `role`).

- [ ] **Step 3: Implement** — in `CustomBookmarkDialog.tsx` add `import DialogShell from './DialogShell';` and replace the entire `return createPortal( <div onClick={onClose} className="anim-fade-in" ...> <div onClick={(e) => e.stopPropagation()} className="anim-scale-in" ...> {...} </div> </div>, document.body );` with a `DialogShell` wrapper that keeps the same panel look:
```tsx
  return (
    <DialogShell
      open={open}
      onClose={onClose}
      labelledBy="custom-bm-title"
      backdropClassName="anim-fade-in"
      panelClassName="anim-scale-in"
      panelStyle={{
        background: 'rgba(26, 29, 39, 0.96)',
        backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)',
        border: '1px solid rgba(108, 140, 255, 0.2)',
        borderRadius: 12, padding: 18, width: 320, color: '#e0e0e0',
        boxShadow: '0 20px 60px rgba(12, 18, 40, 0.65), 0 0 0 1px rgba(255, 255, 255, 0.05) inset',
      }}
    >
      <div id="custom-bm-title" style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
        {t('bm.add_custom')}
      </div>
      {/* ...the existing name input, lat/lng input, select, out-of-range error,
          and the Add/Cancel button row — UNCHANGED — go here... */}
    </DialogShell>
  );
```
Keep the name input's `autoFocus` (DialogShell's initial-focus picks the first focusable, which is the name input — both agree). On the name input's `onKeyDown`, KEEP `if (isSubmitEnter(e)) handleSubmit();` and REMOVE the now-redundant `if (e.key === 'Escape') onClose();` (DialogShell owns Escape). The `if (!open) return null;` guard at the top can stay (harmless) or be dropped since DialogShell renders null when closed; if kept, the existing "renders nothing when closed" test still passes.
Apply the same transformation to `EditBookmarkDialog.tsx`: `open={bookmark != null}`, `labelledBy="edit-bm-title"` with `<div id="edit-bm-title">{t('bm.edit')}</div>`, panel `style` (the object at lines ~98-104) passed as `panelStyle`, preserve the panel's `onContextMenu={(e) => e.stopPropagation()}` via `panelProps={{ onContextMenu: (e) => e.stopPropagation() }}`, and DROP the name input's `if (e.key === 'Escape') onClose();` (EditBookmarkDialog's input has no submit-on-enter line, so nothing else to keep there). Keep `if (!bookmark) return null;` at the top so the body can safely read `bookmark.id` etc.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/CustomBookmarkDialog.test.tsx src/components/EditBookmarkDialog.test.tsx`. Expected: all existing + new tests PASS (the original split/submit/out-of-range tests still pass because the inner markup is unchanged).

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0) + `npx vitest run` (green). `npm run depcruise` 0 errors.

- [ ] **Step 6: Commit** — `git add frontend/src/components/CustomBookmarkDialog.tsx frontend/src/components/EditBookmarkDialog.tsx frontend/src/components/CustomBookmarkDialog.test.tsx frontend/src/components/EditBookmarkDialog.test.tsx` then `git commit -m "refactor(fe): migrate Custom/EditBookmarkDialog onto DialogShell (focus trap + panel-wide Escape)"`


---

### Task 3: Migrate RoutePaste/RouteLoad/BulkPaste/WaypointFly dialogs onto DialogShell

**Files:**
- Modify: `frontend/src/components/RoutePasteDialog.tsx` (its `createPortal` backdrop/panel block; render guard `if (!open) return null;`, panel `width: 460`, backdrop `zIndex: 2000`)
- Modify: `frontend/src/components/RouteLoadDialog.tsx` (its `createPortal` block; render guard `if (!confirm) return null;`, panel `width: 380`, backdrop `zIndex: 2000`)
- Modify: `frontend/src/components/BulkPasteDialog.tsx` (its `createPortal` block; render guard `if (!open) return null;`, panel `width: 460`, backdrop `zIndex: 2000`; backdrop AND cancel/submit are gated on its `busy` prop today)
- Modify: `frontend/src/components/WaypointFlyDialog.tsx` (the `if (!confirm) return null; return createPortal(<div onClick={onClose} style={{ position:'fixed', inset:0, zIndex:2000, ... }}>` block; panel `width: 360`)
- Test: extend `frontend/src/components/RouteLoadDialog.test.tsx`, `frontend/src/components/WaypointFlyDialog.test.tsx` (RoutePasteDialog.test.tsx + BulkPasteDialog.test.tsx also exist — add a minimal `role=dialog` assertion to each).

**Interfaces:**
- Consumes: `DialogShell`
- Produces: none

All four are confirm/paste portal dialogs that currently hand-roll the `position: fixed; inset 0; rgba(8,10,20,0.55)` backdrop at `zIndex: 2000` and gate close on backdrop-click only (no Escape, no focus trap, no initial focus). Migrate each onto DialogShell, preserving the exact panel `style` via `panelStyle`, the `zIndex: 2000` via `backdropStyle={{ zIndex: 2000 }}` (all four differ from the 1000 default), and the exact `onConfirm` / `onSetAsStart` / `onSubmit` / `onClose` wiring. The `open` prop maps to each existing render guard: `confirm != null` for RouteLoad + WaypointFly; `open` for RoutePaste + BulkPaste.

**BulkPasteDialog busy gate (behavior-preserving — do NOT drop):** today its backdrop is `onClick={() => { if (!busy) onClose(); }}` and its cancel/submit buttons are `disabled={busy ...}`. Pass `busy={busy}` to DialogShell so backdrop-click AND the new Escape stay locked during the async createBookmark loop. Leave the inner button `disabled={busy ...}` logic exactly as-is.

- [ ] **Step 1: Write the failing test** — append to `frontend/src/components/WaypointFlyDialog.test.tsx` (already mocks `../i18n`, imports `render, screen, fireEvent, vi`; `makeProps` builds `confirm` via `makeTarget` defaulting to `{ lat: 25.047801, lng: 121.531902, index: 2 }`):
```tsx
  it('exposes the panel as a role=dialog (a11y)', () => {
    render(<WaypointFlyDialog {...makeProps()} />);
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
  });

  it('closes on Escape (added by DialogShell migration)', () => {
    const onClose = vi.fn();
    render(<WaypointFlyDialog {...makeProps({ onClose })} />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('still shows the target coord to 6 decimals after migration', () => {
    render(<WaypointFlyDialog {...makeProps()} />);
    expect(screen.getByText('25.047801, 121.531902')).toBeTruthy();
  });
```
Append the analogous `role=dialog` + Escape-closes block to `frontend/src/components/RouteLoadDialog.test.tsx` (re-assert its existing "show only"/"fly to start"/start-coord tests still pass). Add a single `role=dialog` assertion to `RoutePasteDialog.test.tsx` and `BulkPasteDialog.test.tsx` (open them via their existing `open: true` prop); for BulkPaste also add an Escape-while-busy test asserting `onClose` is NOT called when `busy` is true.

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/WaypointFlyDialog.test.tsx src/components/RouteLoadDialog.test.tsx -t "role=dialog"`. Expected failure: `Unable to find an accessible element with the role "dialog"`.

- [ ] **Step 3: Implement** — for `WaypointFlyDialog.tsx`: add `import DialogShell from './DialogShell';`, KEEP `if (!confirm) return null;` ABOVE the return (so the body can safely read `confirm.lat`), then replace the `return createPortal( <div onClick={onClose} style={{ position:'fixed', inset:0, zIndex:2000, ... }}> <div onClick={(e) => e.stopPropagation()} style={{ width:360, ... }}> {...} </div> </div>, document.body )` with:
```tsx
  return (
    <DialogShell
      open={confirm != null}
      onClose={onClose}
      labelledBy="wp-fly-title"
      backdropStyle={{ zIndex: 2000 }}
      panelStyle={{
        width: 360, maxWidth: '92vw',
        background: 'rgba(26, 29, 39, 0.96)',
        border: '1px solid rgba(108, 140, 255, 0.25)', borderRadius: 12,
        padding: 22, color: '#e8eaf0',
        boxShadow: '0 20px 60px rgba(12, 18, 40, 0.65)',
        fontSize: 13,
      }}
    >
      <div id="wp-fly-title" style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>
        {t('panel.wp_fly_title')}
      </div>
      {/* ...the hint, the monospace coord block (confirm.lat.toFixed(6), confirm.lng.toFixed(6)),
          keep-mode line, and the cancel / set-as-start / confirm button row UNCHANGED... */}
    </DialogShell>
  );
```
(Since `if (!confirm) return null;` runs first, `confirm` is non-null in the body — `confirm.lat.toFixed(6)` stays as-is, no non-null assertion needed.) Apply the same shell wrap to `RoutePasteDialog.tsx` (`open={open}`, `labelledBy="route-paste-title"`, panel style verbatim, `backdropStyle={{ zIndex: 2000 }}`, give `t('panel.route_paste_title')`'s `<div>` `id="route-paste-title"`), `RouteLoadDialog.tsx` (`open={confirm != null}`, `labelledBy="route-load-title"`, keep `if (!confirm) return null;` above the return, panel style verbatim, `backdropStyle={{ zIndex: 2000 }}`, give `t('panel.route_load_title')`'s `<div>` `id="route-load-title"`), and `BulkPasteDialog.tsx` (`open={open}`, `busy={busy}`, `labelledBy="bulk-paste-title"`, panel style verbatim, `backdropStyle={{ zIndex: 2000 }}`, give `t('bm.bulk_paste_title')`'s `<div>` `id="bulk-paste-title"`; remove the now-redundant `if (!busy)` wrapper on what was the backdrop onClick — DialogShell's `busy` owns it — but KEEP the inner cancel/submit `disabled={busy ...}` logic). Do NOT touch any `onConfirm` / `onSubmit` / `onSetAsStart` / button wiring.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/WaypointFlyDialog.test.tsx src/components/RouteLoadDialog.test.tsx src/components/RoutePasteDialog.test.tsx src/components/BulkPasteDialog.test.tsx`. Expected: all PASS.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0) + `npx vitest run` (green). `npm run depcruise` 0 errors.

- [ ] **Step 6: Commit** — `git add frontend/src/components/RoutePasteDialog.tsx frontend/src/components/RouteLoadDialog.tsx frontend/src/components/BulkPasteDialog.tsx frontend/src/components/WaypointFlyDialog.tsx frontend/src/components/WaypointFlyDialog.test.tsx frontend/src/components/RouteLoadDialog.test.tsx frontend/src/components/RoutePasteDialog.test.tsx frontend/src/components/BulkPasteDialog.test.tsx` then `git commit -m "refactor(fe): migrate route/bulk/waypoint dialogs onto DialogShell (Escape + focus trap + initial focus, preserve bulk busy-lock)"`


---

### Task 4: Add focus trap + autofocus + Escape to WiFi-warning / Repair / Phone-control / Forget modals (DialogShell, busy-lock on repair-running)

**Files:**
- Modify: `frontend/src/components/DeviceStatus.tsx` (the `showWifiWarning && createPortal(...)` block starting ~line 888 and the `showRepairConfirm && createPortal(...)` block starting ~line 941)
- Modify: `frontend/src/components/PhoneControl.tsx` (the `open && createPortal(( <div onClick={() => setOpen(false)} style={{ ...zIndex:2000... }}>` block ~line 139)
- Modify: `frontend/src/components/DeviceChip.tsx` (the `confirmForget && createPortal(...)` block ~line 149)
- Test: `frontend/src/components/DeviceChip.test.tsx` (ALREADY EXISTS — extend it; do not recreate)

**Interfaces:**
- Consumes: `DialogShell`
- Produces: none

**Grounding facts (verified against the real code):**
- `DeviceChip` is a NAMED export: `export function DeviceChip(...)` — import as `import { DeviceChip } from './DeviceChip'` (NOT default).
- `DeviceChip.test.tsx` already has a full "forget confirmation flow" describe block: it opens the menu via `fireEvent.contextMenu(screen.getByTitle('A · My iPhone'))`, clicks `device.chip_forget`, and already asserts OK fires `onForget` (`device.forget_ok`) and Cancel does not (`device.forget_cancel`). Only the NEW a11y + Escape assertions need adding.
- The forget backdrop is `rgba(0,0,0,0.5)` with NO blur, `zIndex: 10000`. Title key `device.forget_confirm_title`, body `device.forget_confirm_body`.
- The WiFi-warning + Repair modals BOTH sit at `zIndex: 1000` (the DialogShell default) with `anim-fade-in`/`anim-scale-in` classes — no `backdropStyle` zIndex override needed. WiFi-warning title is `t('wifi.warning_title')` inside a `<strong>`. The Repair confirm title is `t('wifi.repair_confirm_title')` inside a `<strong>` (NOT `wifi.repair_title`). The Repair backdrop already gates on `repairState !== 'running'` -> maps to DialogShell `busy={repairState === 'running'}`.
- PhoneControl modal is at `zIndex: 2000`, title `t('phone.modal_title')` in an `<h2>`.

- [ ] **Step 1: Write the failing test** — append a new describe block to the EXISTING `frontend/src/components/DeviceChip.test.tsx` (which imports `{ DeviceChip }`, has `makeDevice`, `noop`, and an `openMenu`/`getByTitle('A · My iPhone')` pattern). Reuse those exact helpers:
```tsx
describe('DeviceChip forget modal a11y (DialogShell)', () => {
  function openForget() {
    fireEvent.contextMenu(screen.getByTitle('A · My iPhone'))
    fireEvent.click(screen.getByText('device.chip_forget'))
  }

  it('exposes the forget confirm as a role=dialog when open', () => {
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    openForget()
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByText('device.forget_confirm_title')).toBeInTheDocument()
  })

  it('closes the forget modal on Escape without calling onForget', () => {
    const onForget = vi.fn()
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        onDisconnect={noop}
        onForget={onForget}
        onRestoreOne={noop}
      />,
    )
    openForget()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByText('device.forget_confirm_title')).not.toBeInTheDocument()
    expect(onForget).not.toHaveBeenCalled()
  })
})
```
(The existing block already covers OK-fires-`onForget` and Cancel-does-not, so no need to duplicate those.)

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/DeviceChip.test.tsx -t "role=dialog"`. Expected failure: `Unable to find an accessible element with the role "dialog"` (the hand-rolled forget overlay has no role; Escape currently does nothing).

- [ ] **Step 3: Implement** — `DeviceChip.tsx`: add `import DialogShell from './DialogShell';` and replace the `confirmForget && createPortal( <div onClick={() => setConfirmForget(false)} style={{ position:'fixed', inset:0, zIndex:10000, background:'rgba(0,0,0,0.5)', ... }}> <div onClick={e => e.stopPropagation()} style={{ background:'rgba(20,22,28,0.96)', ... }}> {...} </div> </div>, document.body )` with:
```tsx
      <DialogShell
        open={confirmForget}
        onClose={() => setConfirmForget(false)}
        labelledBy="forget-title"
        backdropStyle={{ zIndex: 10000, background: 'rgba(0,0,0,0.5)', backdropFilter: 'none', WebkitBackdropFilter: 'none' }}
        panelStyle={{
          background: 'rgba(20,22,28,0.96)',
          backdropFilter: 'blur(18px) saturate(160%)',
          border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: 10, padding: 16, maxWidth: 320,
          color: '#eaeaea', fontSize: 13,
        }}
      >
        <div id="forget-title" style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>
          {t('device.forget_confirm_title')}
        </div>
        {/* ...the body div + cancel/ok button row UNCHANGED (forget_cancel / forget_ok)... */}
      </DialogShell>
```
(The original backdrop has no blur; setting `backdropFilter: 'none'` overrides the DialogShell default `blur(4px)`.)
`DeviceStatus.tsx`: add `import DialogShell from './DialogShell';`. Wrap the WiFi-warning block with `<DialogShell open={showWifiWarning} onClose={() => setShowWifiWarning(false)} labelledBy="wifi-warning-title" backdropClassName="anim-fade-in" panelClassName="anim-scale-in" panelStyle={<the existing inner-panel style object verbatim>}>` and give the `<strong>{t('wifi.warning_title')}</strong>` an `id="wifi-warning-title"`. Wrap the Repair block with `<DialogShell open={showRepairConfirm} onClose={() => { setShowRepairConfirm(false); setRepairTargetUdid(null); }} busy={repairState === 'running'} labelledBy="wifi-repair-title" backdropClassName="anim-fade-in" panelClassName="anim-scale-in" panelStyle={<existing repair panel style verbatim>}>` and give the `<strong>{t('wifi.repair_confirm_title')}</strong>` an `id="wifi-repair-title"` — `busy` reproduces the existing `if (repairState !== 'running')` backdrop guard AND extends it to Escape. (Both modals are zIndex 1000 = DialogShell default, so no backdropStyle override.) `PhoneControl.tsx`: add the import and wrap with `<DialogShell open={open} onClose={() => setOpen(false)} labelledBy="phone-modal-title" backdropStyle={{ zIndex: 2000 }} panelStyle={<existing panel style verbatim>}>`; give the `<h2>{t('phone.modal_title')}</h2>` an `id="phone-modal-title"`. Keep every inner button / handler exactly as-is. For each migrated dialog, drop only the now-redundant backdrop `onClick` close logic (DialogShell owns it) and keep all inner content.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/DeviceChip.test.tsx`. Expected: all (existing + new) PASS. Also re-run `src/components/DeviceStatus.test.tsx` + any `PhoneControl.test.tsx` if present to confirm no regression.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0) + `npx vitest run` (green). `npm run depcruise` 0 errors.

- [ ] **Step 6: Commit** — `git add frontend/src/components/DeviceStatus.tsx frontend/src/components/PhoneControl.tsx frontend/src/components/DeviceChip.tsx frontend/src/components/DeviceChip.test.tsx` then `git commit -m "refactor(fe): give WiFi-warning/repair/phone-control/forget modals DialogShell a11y (focus trap + Escape + busy-lock)"`


---

### Task 5: Add Esc-close + initial focus to SettingsModal (DialogShell) and UserAvatarPicker (Esc + focus ref)

**Files:**
- Modify: `frontend/src/components/SettingsModal.tsx` (the `return createPortal(( <div onClick={onClose} style={{ ...zIndex:2000... }}> <div onClick={(e) => e.stopPropagation()} style={{ width:560, ... }}>` block ~lines 98-118)
- Modify: `frontend/src/components/UserAvatarPicker.tsx` (the top-level `return ( <div style={{ position:'absolute', ... zIndex:900 ... }}>` panel ~line 132 — NOT a portal, NOT a backdrop overlay; it's a draggable popover)
- Test: `frontend/src/components/SettingsModal.test.tsx` (extend + rewrite one existing test), `frontend/src/components/UserAvatarPicker.test.tsx` (ALREADY EXISTS — extend it)

**Interfaces:**
- Consumes: `DialogShell` (for SettingsModal only)
- Produces: none

SettingsModal is a true portal/backdrop modal at `zIndex: 2000` -> migrate to DialogShell (gains Escape + focus trap + initial focus; keeps its existing X button (`aria-label='generic.close'`), backdrop-close, and all toggle wiring). UserAvatarPicker is a draggable absolute-positioned popover (`position:absolute, zIndex:900`) with NO backdrop and document-level capture-phase drag listeners -> do NOT force it through DialogShell (that would add a backdrop + change layout). Instead add a self-contained `Escape`-to-`handleCancel` document listener + an `initialFocusRef` on the close (×) button. Both changes are purely additive.

**Pre-existing test that MUST be rewritten (not just appended):** `SettingsModal.test.tsx` lines 82-96 finds the backdrop by DOM-walk: `const panel = screen.getByText('settings.title').closest('div')!.parentElement!; const backdrop = panel.parentElement!;`. After migration the title `<div>` becomes a direct child of the `role="dialog"` panel, so rewrite that lookup to `const backdrop = screen.getByRole('dialog').parentElement!;` (keep the in-panel-click-does-not-close assertion identical, still clicking `screen.getByText('settings.title')`).

**UserAvatarPicker grounding facts (verified):** existing test uses default import `import UserAvatarPicker from './UserAvatarPicker'`, a `baseProps()` helper (`avatar/customPng/onSave/onClose/onShowToast`), and a `vi.mock('../userAvatars', ...)` stub with `PRESETS`/`DEFAULT_AVATAR_HTML`/`pngFileToDataUrl`. There is already a test "close (×) button calls onClose without saving" that finds the button via `screen.getByTitle('avatar.close_no_save')`. `handleCancel` is defined ~line 96; the × button (`onClick={handleCancel}`, `title={t('avatar.close_no_save')}`) is ~lines 163-172 and currently has NO ref. ADD the new assertions to the EXISTING test file using its existing `baseProps`/mock — do not create a second file or re-declare the mock.

- [ ] **Step 1: Write the failing test** — append to `frontend/src/components/SettingsModal.test.tsx` (imports `render, screen, fireEvent, vi`; mocks `../i18n`, `../services/alertSound`, `./CloudSyncSection`):
```tsx
  it('exposes the modal as role=dialog and closes on Escape', () => {
    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} />);
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
```
And REWRITE the existing backdrop test body (lines ~90-94) to `const backdrop = screen.getByRole('dialog').parentElement!;` (drop the `panel.closest('div').parentElement` walk; keep the rest of that test identical). For UserAvatarPicker, append to the EXISTING `frontend/src/components/UserAvatarPicker.test.tsx` (reuse its `baseProps`, default import, and `../userAvatars` mock):
```tsx
  it('closes (cancel) on Escape without saving', () => {
    const props = baseProps();
    render(<UserAvatarPicker {...props} />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(props.onClose).toHaveBeenCalledTimes(1);
    expect(props.onSave).not.toHaveBeenCalled();
  });

  it('focuses the close (×) button on mount', () => {
    render(<UserAvatarPicker {...baseProps()} />);
    expect(document.activeElement).toBe(screen.getByTitle('avatar.close_no_save'));
  });
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/SettingsModal.test.tsx src/components/UserAvatarPicker.test.tsx`. Expected failures: SettingsModal `Unable to find role="dialog"`; UserAvatarPicker Escape does not call `onClose`, and the × button is not the active element on mount.

- [ ] **Step 3: Implement** — `SettingsModal.tsx`: add `import DialogShell from './DialogShell';` and replace the `return createPortal(( <div onClick={onClose} style={{ position:'fixed', inset:0, zIndex:2000, ... }}> <div onClick={(e) => e.stopPropagation()} style={{ width:560, ... }}> {...} </div> </div> ), document.body)` with `<DialogShell open={open} onClose={onClose} labelledBy="settings-title" backdropStyle={{ zIndex: 2000 }} panelStyle={<the existing inner-panel style object, lines ~109-118, verbatim>}>` and give `t('settings.title')`'s `<div>` (line ~138) an `id="settings-title"`. Keep the X button, all rows, and `<CloudSyncSection />` unchanged. KEEP the `useEffect` that reads `window.electronAPI` (it already early-returns on `!open`). You may drop the explicit `if (!open) return null;` (line ~44) since DialogShell renders null when closed — the existing "renders nothing when open is false" test still passes either way.
For `UserAvatarPicker.tsx` (already imports `useEffect, useRef, useState`): add a close-button ref + two effects, placed AFTER `handleCancel`'s definition (~line 100) to avoid use-before-define:
```tsx
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { closeBtnRef.current?.focus(); }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') handleCancel(); };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [handleCancel]);
```
Add `ref={closeBtnRef}` to the existing × button (~lines 163-172, the one with `onClick={handleCancel}` and `title={t('avatar.close_no_save')}`). Do NOT add a backdrop and do NOT touch the `beginDrag` document capture-phase listeners.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/SettingsModal.test.tsx src/components/UserAvatarPicker.test.tsx`. Expected: all PASS, including the rewritten backdrop test.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0) + `npx vitest run` (green). `npm run depcruise` 0 errors.

- [ ] **Step 6: Commit** — `git add frontend/src/components/SettingsModal.tsx frontend/src/components/UserAvatarPicker.tsx frontend/src/components/SettingsModal.test.tsx frontend/src/components/UserAvatarPicker.test.tsx` then `git commit -m "feat(fe): add Esc-close + initial focus to SettingsModal (DialogShell) and UserAvatarPicker"`


---


<!-- ===== T2 · Menu/row/chip keyboard a11y + toast aria-live ===== -->

### Task 6: Toast container gets role=status + aria-live=polite (U19)

**Files:**
- Modify: `frontend/src/App.tsx` (the inline `{toastMsg && (<div key={toastMsg} className="anim-fade-slide-down" …>{toastMsg}</div>)}` block — currently ~L1610-1639; locate by the `className="anim-fade-slide-down"` toast div)
- Test: `frontend/src/App.toastAria.test.tsx` (create)

**Interfaces:**
- Consumes: none
- Produces: none

- [ ] **Step 1: Write the failing test** — Drive a real toast through the App.smoke harness (a bare `tunnel_recovered` WS frame fires `showToast(t('wifi.tunnel_recovered'))`; with no `primaryDevice` the `useSimulation` udid guard `if (primary && msgUdid && msgUdid !== primary) return` is skipped, so `onTunnelRecoveredRef.current?.()` fires unconditionally — verified at `useSimulation.ts:448-459` + `App.tsx:88-92`) and assert the rendered toast node carries the live-region attributes. The harness is copied verbatim from `src/App.smoke.test.tsx` (MapView stub + `services/api` importOriginal mock + real `createWsRouter()` injected via `ServicesProvider`, real `I18nProvider` so `t()` resolves real English strings). NOTE: this test does NOT use `@testing-library/user-event` (not a project dependency) — it only dispatches a WS frame and queries by role.

```tsx
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React from 'react'
import { render, act, screen } from '@testing-library/react'

// MapView pulls Leaflet/MapLibre — render nothing (same as App.smoke.test.tsx).
vi.mock('./components/MapView', () => ({
  default: React.forwardRef(function MapViewStub(_props: any, _ref: any) {
    return null
  }),
}))

vi.mock('./services/api', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const arrayReturning = new Set([
    'getSavedRoutes', 'getRecent', 'listRouteCategories', 'listBookmarks',
    'listCategories', 'listDevices', 'getBookmarks', 'getCategories',
  ])
  const nullReturning = new Set(['getCatalog'])
  const urlReturning = new Set(['bookmarksExportUrl', 'exportGpxUrl', 'routesExportUrl'])
  const out: Record<string, unknown> = {}
  for (const key of Object.keys(actual)) {
    if (typeof actual[key] !== 'function') { out[key] = actual[key]; continue }
    if (key === 'cloudSyncStatus') {
      out[key] = async () => ({ enabled: false, prompt_dismissed: true, detected_icloud_path: null })
    } else if (key === 'getCooldownStatus' || key === 'getStatus') {
      out[key] = async () => ({})
    } else if (arrayReturning.has(key)) {
      out[key] = async () => []
    } else if (nullReturning.has(key)) {
      out[key] = async () => null
    } else if (urlReturning.has(key)) {
      out[key] = () => ''
    } else {
      out[key] = async () => undefined
    }
  }
  return out
})

import App from './App'
import { I18nProvider } from './i18n'
import { ServicesProvider } from './contexts/ServicesContext'
import { createWsRouter, type WsRouterImpl } from './adapters/ws/router'
import * as api from './services/api'

function renderApp(router: WsRouterImpl, connected = true) {
  return render(
    <I18nProvider>
      <ServicesProvider value={{ api, ws: router, sendMessage: vi.fn(), connected }}>
        <App />
      </ServicesProvider>
    </I18nProvider>,
  )
}

beforeEach(() => { try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ } })
afterEach(() => { try { localStorage.clear() } catch { /* ignore */ } })

describe('App toast a11y (U19)', () => {
  it('renders the toast inside a polite live region (role=status, aria-live=polite)', async () => {
    const router = createWsRouter()
    await act(async () => { renderApp(router) })

    // No primaryDevice in this harness -> useSimulation's udid guard is skipped
    // and the positive 'WiFi tunnel restored' toast fires unconditionally.
    await act(async () => {
      router.dispatch({ type: 'tunnel_recovered' })
    })

    // 'wifi.tunnel_recovered' resolves to its English string via I18nProvider.
    const region = await screen.findByRole('status')
    expect(region).toHaveAttribute('aria-live', 'polite')
    // The toast message text lives inside the same live-region node.
    expect(region.textContent && region.textContent.length).toBeGreaterThan(0)
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/App.toastAria.test.tsx -t "polite live region"`. Expected failure: `Unable to find an accessible element with the role "status"` (the toast `<div>` currently has no `role`/`aria-live`).
- [ ] **Step 3: Implement** — Add the two attributes to the existing toast container div in `App.tsx`. Current code (L1610-1613):

```tsx
        {toastMsg && (
          <div
            key={toastMsg}
            className="anim-fade-slide-down"
            style={{
```

New code:

```tsx
        {toastMsg && (
          <div
            key={toastMsg}
            role="status"
            aria-live="polite"
            className="anim-fade-slide-down"
            style={{
```

Leave the `style`/`key`/text untouched. (`CloudSyncBusyOverlay.tsx:74` already uses `role="alert" aria-live="assertive"` for blocking sync; toasts are non-blocking status, so `polite` is the correct counterpart, and `status`/`alert` do not collide in `findByRole`.)
- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/App.toastAria.test.tsx -t "polite live region"`. Expected: 1 passed.
- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) + `npx vitest run` (green; baseline 708 passed/92 files grows by 1 file + 1 test) + depcruise (0 errors) if depcruise is wired into the FE lint step.
- [ ] **Step 6: Commit** — `git add frontend/src/App.tsx frontend/src/App.toastAria.test.tsx` then `git commit -m "feat(a11y): announce toasts via role=status aria-live=polite (U19)"`.


---

### Task 7: BookmarkContextMenu becomes a role=menu with role=menuitem buttons (U22)

**Files:**
- Modify: `frontend/src/components/BookmarkContextMenu.tsx` (the portal `<div data-bookmark-context-menu …>` container ~L153-173 + the action rows currently `<div style={ctxItemStyle} onClick={…}>` — Teleport/Navigate/GoldDitto/Waypoint/Edit/Copy/Delete/Move-to; locate each by its `t(...)` label) + the two module-level helpers `ctxHighlight`/`ctxUnhighlight` (~L55-60)
- Test: `frontend/src/components/BookmarkContextMenu.test.tsx` (extend; do not delete the existing describe blocks)

**Interfaces:**
- Consumes: none
- Produces: pattern reused by the RouteList + MapContextMenu + CategoryManagerPanel + DeviceChip tasks — `role="menu"` container + `role="menuitem"` `<button>` action rows + native button activation

- [ ] **Step 1: Write the failing test** — Append to the existing `BookmarkContextMenu.test.tsx` (which already mocks `../i18n` to identity and defines module-level `bm` + `makeProps`; `render`, `screen`, `fireEvent`, `vi` are already imported). DO NOT add `@testing-library/user-event` — it is NOT a project dependency. jsdom does NOT auto-fire `onClick` on Enter/Space for a native `<button>` (verified empirically), so we assert (a) the container is `role="menu"`, (b) each row is a `role="menuitem"` that is a real `<button>` element (hence natively keyboard-focusable + Enter/Space-operable by the browser — the actual a11y win), and (c) `fireEvent.click` on the menuitem still fires its callback + closes (proving the `<div>`→`<button>` conversion preserved activation). Use the existing `makeProps`/`bm`.

```tsx
describe('BookmarkContextMenu keyboard a11y (U22)', () => {
  it('exposes a role=menu container with role=menuitem button action rows', () => {
    render(<BookmarkContextMenu {...makeProps()} />);
    expect(screen.getByRole('menu')).toBeTruthy();
    // Teleport / Delete are menuitems; their text label is the accessible name
    // (the leading <svg> contributes no name).
    const teleport = screen.getByRole('menuitem', { name: /map\.teleport_here/ });
    expect(teleport.tagName).toBe('BUTTON'); // native = keyboard-operable
    expect(screen.getByRole('menuitem', { name: /generic\.delete/ })).toBeTruthy();
  });

  it('activating the Teleport menuitem fires its callback and closes', () => {
    const onTeleport = vi.fn();
    const onClose = vi.fn();
    render(<BookmarkContextMenu {...makeProps({ onTeleport, onClose })} />);
    fireEvent.click(screen.getByRole('menuitem', { name: /map\.teleport_here/ }));
    expect(onTeleport).toHaveBeenCalledWith(bm.lat, bm.lng);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/BookmarkContextMenu.test.tsx -t "keyboard a11y"`. Expected failure: `Unable to find an accessible element with the role "menu"` (container is a plain styled `<div>`; rows are `<div onClick>` with no role).
- [ ] **Step 3: Implement** — (a) Add `role="menu"` + `aria-label={t('bm.menu_label')}` to the container `<div data-bookmark-context-menu …>`. (b) Convert each action row from `<div style={ctxItemStyle} onClick={…}>…</div>` to a `<button type="button" role="menuitem" style={{ ...ctxItemStyle, width: '100%', textAlign: 'left', background: 'transparent', border: 'none', font: 'inherit' }} onClick={…}>`. A native `<button>` is keyboard-focusable and the browser fires its `onClick` on Enter/Space, so no manual `onKeyDown` is needed. Keep `onMouseEnter={ctxHighlight}`/`onMouseLeave={ctxUnhighlight}`. Example — current Teleport row (L245-262):

```tsx
            <div
              style={ctxItemStyle}
              onMouseEnter={ctxHighlight}
              onMouseLeave={ctxUnhighlight}
              onClick={() => {
                onTeleport(bm.lat, bm.lng);
                onClose();
              }}
            >
              <svg …/>
              {t('map.teleport_here')}
            </div>
```

becomes:

```tsx
            <button
              type="button"
              role="menuitem"
              style={{ ...ctxItemStyle, width: '100%', textAlign: 'left', background: 'transparent', border: 'none', font: 'inherit' }}
              onMouseEnter={ctxHighlight}
              onMouseLeave={ctxUnhighlight}
              onClick={() => {
                onTeleport(bm.lat, bm.lng);
                onClose();
              }}
            >
              <svg …/>
              {t('map.teleport_here')}
            </button>
```

Apply the same conversion to Navigate, Set-as-Gold-Ditto-A, Add-Waypoint, Edit, Copy, Delete, and each Move-to-category row. Because the buttons now pass `e: React.MouseEvent<HTMLButtonElement>` to the helpers, widen the two module-level helpers (L55-60) from `HTMLDivElement` to `HTMLElement`:

```tsx
function ctxHighlight(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e';
}
function ctxUnhighlight(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = 'transparent';
}
```

to:

```tsx
function ctxHighlight(e: React.MouseEvent<HTMLElement>) {
  (e.currentTarget as HTMLElement).style.background = '#3a3a3e';
}
function ctxUnhighlight(e: React.MouseEvent<HTMLElement>) {
  (e.currentTarget as HTMLElement).style.background = 'transparent';
}
```

Leave the coords-header row (L175-221, a click-to-geocode affordance, keeps `ctxHighlight`/`ctxUnhighlight` — still type-checks under the widened helper) and the reverse-geocode result row (L225) as `<div>`s, and leave the device-disconnected non-interactive notice (L279) as a `<div>`. Add the i18n key `'bm.menu_label'` to `frontend/src/i18n/strings.ts` (zh: `書籤選單`, en: `Bookmark actions`). Do NOT change the Delete row's `window.confirm` gating.
- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/BookmarkContextMenu.test.tsx`. Expected: all existing tests + the 2 new ones pass (the existing `getByText('map.teleport_here')` / `getByText('generic.delete')` assertions still match because the label text stays inside the button; the existing reverse-geocode + delete-confirm tests are unaffected — those rows are untouched).
- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) + `npx vitest run` (green).
- [ ] **Step 6: Commit** — `git add frontend/src/components/BookmarkContextMenu.tsx frontend/src/components/BookmarkContextMenu.test.tsx frontend/src/i18n/strings.ts` then `git commit -m "feat(a11y): role=menu + role=menuitem buttons for BookmarkContextMenu (U22)"`.


---

### Task 8: MapContextMenu becomes a role=menu with role=menuitem buttons (U22)

**Files:**
- Modify: `frontend/src/components/MapContextMenu.tsx` (the root `<div ref={contextMenuElRef} className="context-menu …">` ~L134-161 + each `<div className="context-menu-item" style={contextMenuItemStyle} onClick={…}>` action row — Teleport/Navigate/GoldDitto/Copy/AddBookmark/AddWaypoint; locate each by its `t(...)` label)
- Modify: `frontend/src/utils/contextMenuStyle.ts` (widen `highlightItem`/`unhighlightItem` param types from `HTMLDivElement` to `HTMLElement` so `<button>` rows type-check — L17-23)
- Test: `frontend/src/components/MapContextMenu.test.tsx` (extend; keep the existing describe blocks)

**Interfaces:**
- Consumes: pattern from the BookmarkContextMenu task — `role="menu"` container + `role="menuitem"` `<button>` rows
- Produces: none

- [ ] **Step 1: Write the failing test** — Append to the existing `MapContextMenu.test.tsx` (already mocks `../i18n` identity + defines `makeProps`, `COORD`; `render`, `screen`, `fireEvent`, `vi` already imported). DO NOT add `@testing-library/user-event` (not a project dependency); jsdom does not fire button onClick on Enter, so assert role + native-button + `fireEvent.click` activation.

```tsx
describe('MapContextMenu keyboard a11y (U22)', () => {
  it('exposes a role=menu container with role=menuitem button action rows', () => {
    render(<MapContextMenu {...makeProps()} />);
    expect(screen.getByRole('menu')).toBeTruthy();
    const copy = screen.getByRole('menuitem', { name: /map\.copy_coords/ });
    expect(copy.tagName).toBe('BUTTON'); // native = keyboard-operable
    expect(screen.getByRole('menuitem', { name: /map\.add_bookmark/ })).toBeTruthy();
  });

  it('activating the Copy menuitem fires onCopy and closes', () => {
    const onCopy = vi.fn();
    const onClose = vi.fn();
    render(<MapContextMenu {...makeProps({ onCopy, onClose })} />);
    fireEvent.click(screen.getByRole('menuitem', { name: /map\.copy_coords/ }));
    expect(onCopy).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/MapContextMenu.test.tsx -t "keyboard a11y"`. Expected failure: `Unable to find an accessible element with the role "menu"`.
- [ ] **Step 3: Implement** — (a) Add `role="menu"` + `aria-label={t('map.menu_label')}` to the root `<div ref={contextMenuElRef} className="context-menu anim-scale-in-tl" …>`. Keep ALL existing inline-style logic (the `contextMenuPos` clamp + `visibility` + `onClick={(e) => e.stopPropagation()}`) — the layout-effect dep-list (`[x, y]`, DELIBERATELY excluding `contextMenuPos`) and the visibility-clamp are load-bearing (see the component's doc comment, L51-64) and MUST NOT change. (b) Convert each `<div className="context-menu-item" style={contextMenuItemStyle} onClick={…}>` action row to `<button type="button" role="menuitem" className="context-menu-item" style={{ ...contextMenuItemStyle, width: '100%', textAlign: 'left', background: 'transparent', border: 'none', font: 'inherit' }} onClick={…}>`. Native `<button>` gives Enter/Space activation, so no manual `onKeyDown`. Example — current Copy row (L303-318):

```tsx
      <div
        className="context-menu-item"
        style={contextMenuItemStyle}
        onMouseEnter={highlightItem}
        onMouseLeave={unhighlightItem}
        onClick={() => {
          onCopy();
          onClose();
        }}
      >
        <svg …/>
        {t('map.copy_coords')}
      </div>
```

becomes:

```tsx
      <button
        type="button"
        role="menuitem"
        className="context-menu-item"
        style={{ ...contextMenuItemStyle, width: '100%', textAlign: 'left', background: 'transparent', border: 'none', font: 'inherit' }}
        onMouseEnter={highlightItem}
        onMouseLeave={unhighlightItem}
        onClick={() => {
          onCopy();
          onClose();
        }}
      >
        <svg …/>
        {t('map.copy_coords')}
      </button>
```

Apply to Teleport, Navigate, Set-as-Gold-Ditto-A, Add-Bookmark, and Add-Waypoint. Leave the disabled rows (`device_disconnected` L291, `already_bookmarked` L324) as `<div>`s — they are non-interactive notices, not actions. Leave the coords-header click-to-geocode `<div>` (L165) as-is (it keeps `highlightItem`/`unhighlightItem`, still type-checks under the widened helper). (c) Widen the helpers in `contextMenuStyle.ts` (L17-23):

```ts
export function highlightItem(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e';
}

export function unhighlightItem(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = 'transparent';
}
```

to:

```ts
export function highlightItem(e: React.MouseEvent<HTMLElement>) {
  (e.currentTarget as HTMLElement).style.background = '#3a3a3e';
}

export function unhighlightItem(e: React.MouseEvent<HTMLElement>) {
  (e.currentTarget as HTMLElement).style.background = 'transparent';
}
```

Add i18n key `'map.menu_label'` to `strings.ts` (zh: `地圖選單`, en: `Map actions`).
- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/MapContextMenu.test.tsx`. Expected: existing tests (incl. the reverse-geocode + stale-guard tests, which touch the untouched header row) + 2 new pass.
- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) + `npx vitest run` (green). Note: `WaypointMenu` and any other consumer of `highlightItem`/`unhighlightItem` keeps type-checking because `HTMLDivElement` is assignable to the widened `HTMLElement` param.
- [ ] **Step 6: Commit** — `git add frontend/src/components/MapContextMenu.tsx frontend/src/utils/contextMenuStyle.ts frontend/src/components/MapContextMenu.test.tsx frontend/src/i18n/strings.ts` then `git commit -m "feat(a11y): role=menu + role=menuitem buttons for MapContextMenu (U22)"`.


---

### Task 9: RouteList context menu + rows get menu roles and keyboard activation (U22)

**Files:**
- Modify: `frontend/src/components/RouteList.tsx` (the portal `<div data-route-context-menu …>` ~L834-845 + its `<div style={ctxItemStyle} onClick={…}>` rows Load/Edit/Export-GPX/Delete/Move-to ~L846-928; AND the `renderRouteRow` row `<div className="bookmark-item" … onClick onContextMenu>` ~L1026-1053; AND the two file-local helpers `ctxHighlight`/`ctxUnhighlight` ~L1116-1121; locate by content)
- Test: `frontend/src/components/RouteList.test.tsx` (extend; keep existing describe blocks)

**Interfaces:**
- Consumes: pattern from the BookmarkContextMenu task
- Produces: none

- [ ] **Step 1: Write the failing test** — Append to `RouteList.test.tsx` (already mocks `../i18n` identity, defines `makeProps`, `makeRoute`, `categories`; `render`, `screen`, `fireEvent`, `vi` already imported; default `makeRoute` name is `'Morning Loop'`). DO NOT add `@testing-library/user-event` (not a project dependency). The list ROW is a `<div role="button">` with an EXPLICIT `onKeyDown` handler in the component, so `fireEvent.keyDown(row, { key: 'Enter' })` genuinely fires `onRouteLoad` (verified: a div with an own onKeyDown handler responds to fireEvent.keyDown in jsdom). The context-menu rows are native `<button>`s — assert role + `fireEvent.click` (jsdom does not auto-activate native buttons on Enter).

```tsx
describe('RouteList keyboard a11y (U22)', () => {
  it('list rows are role=button and Enter (via onKeyDown) loads the route', () => {
    const onRouteLoad = vi.fn();
    render(<RouteList {...(makeProps({ onRouteLoad }) as any)} />);
    const row = screen.getByRole('button', { name: /Morning Loop/ });
    row.focus();
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(onRouteLoad).toHaveBeenCalledWith('r1');
  });

  it('right-click opens a role=menu with role=menuitem button actions', () => {
    render(<RouteList {...(makeProps() as any)} />);
    const row = screen.getByRole('button', { name: /Morning Loop/ });
    fireEvent.contextMenu(row);
    expect(screen.getByRole('menu')).toBeTruthy();
    const load = screen.getByRole('menuitem', { name: /route\.load/ });
    expect(load.tagName).toBe('BUTTON');
    expect(screen.getByRole('menuitem', { name: /generic\.delete/ })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/RouteList.test.tsx -t "keyboard a11y"`. Expected failure: `Unable to find an accessible element with the role "button"` matching the route name (the row is a bare `<div onClick>` with no role).
- [ ] **Step 3: Implement** — (a) On the `renderRouteRow` row `<div className="bookmark-item" …>` (L1026-1053), add `role="button"`, `tabIndex={isEditing ? -1 : 0}`, `aria-label={route.name}`, and an `onKeyDown` mirroring the existing `onClick` (load/toggle-select) for Enter/Space without breaking the inline-edit input. Current opening of the row div:

```tsx
      <div
        key={route.id}
        className="bookmark-item"
        style={{ … }}
        onClick={() => {
          if (multiSelect) toggleSelected(route.id);
          else if (!isEditing) onRouteLoad(route.id);
        }}
        onContextMenu={(e) => { … }}
```

becomes:

```tsx
      <div
        key={route.id}
        className="bookmark-item"
        role="button"
        tabIndex={isEditing ? -1 : 0}
        aria-label={route.name}
        style={{ … }}
        onClick={() => {
          if (multiSelect) toggleSelected(route.id);
          else if (!isEditing) onRouteLoad(route.id);
        }}
        onKeyDown={(e) => {
          if (isEditing) return;
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            if (multiSelect) toggleSelected(route.id);
            else onRouteLoad(route.id);
          }
        }}
        onContextMenu={(e) => { … }}
```

(Keep the existing `style`, `onContextMenu`, `onMouseEnter`, `onMouseLeave` exactly.) (b) On the portal context-menu container `<div data-route-context-menu …>` (L834), add `role="menu"` + `aria-label={t('route.menu_label')}`. (c) Convert the menu's action rows (Load L846, Edit L856, Export-GPX L872, Delete L885, each Move-to-category row L909) from `<div style={ctxItemStyle} onClick={…}>` to `<button type="button" role="menuitem" style={{ ...ctxItemStyle, width: '100%', textAlign: 'left', background: 'transparent', border: 'none', font: 'inherit' }} onClick={…}>`, keeping `onMouseEnter={ctxHighlight}`/`onMouseLeave={ctxUnhighlight}`. Widen the two file-local helpers (L1116-1121) from `React.MouseEvent<HTMLDivElement>` to `React.MouseEvent<HTMLElement>` (mirror the BookmarkContextMenu helper change):

```tsx
function ctxHighlight(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = '#3a3a3e';
}
function ctxUnhighlight(e: React.MouseEvent<HTMLDivElement>) {
  (e.currentTarget as HTMLDivElement).style.background = 'transparent';
}
```

to:

```tsx
function ctxHighlight(e: React.MouseEvent<HTMLElement>) {
  (e.currentTarget as HTMLElement).style.background = '#3a3a3e';
}
function ctxUnhighlight(e: React.MouseEvent<HTMLElement>) {
  (e.currentTarget as HTMLElement).style.background = 'transparent';
}
```

Leave the `'bm.move_to'` section header `<div>` (L905) as-is. Add i18n key `'route.menu_label'` to `strings.ts` (zh: `路線選單`, en: `Route actions`). Do NOT change the Delete row's `window.confirm` gating or the right-click open behavior. NOTE: the existing U13 single-delete tests open the menu via `fireEvent.contextMenu(screen.getByText('Morning Loop'))` then click the Delete label — they still pass because the label text stays inside the converted `<button>` and `fireEvent.click` fires it.
- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/RouteList.test.tsx`. Expected: existing tests (incl. the `getByText('Morning Loop')` row-render + `fireEvent.click(getByText('Morning Loop'))` row-click tests — text is still inside the row div, and click on the inner text still bubbles to the row's `onClick`) + 2 new pass.
- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) + `npx vitest run` (green).
- [ ] **Step 6: Commit** — `git add frontend/src/components/RouteList.tsx frontend/src/components/RouteList.test.tsx frontend/src/i18n/strings.ts` then `git commit -m "feat(a11y): keyboard-activatable route rows + role=menu route context menu (U22)"`.


---

### Task 10: CategoryManagerPanel delete-dropdown gets menu roles + icon-button aria-labels (U22)

**Files:**
- Modify: `frontend/src/components/CategoryManagerPanel.tsx` (the edit-pencil `<button>` ~L82-98 has only a `title`, no `aria-label`; the `CategoryDeleteDropdown` trigger `<button>` ~L186-198 is icon-only with no accessible name; the open dropdown `<div>` ~L200-211 and its two `<div onClick>` choice rows ~L212-232 have no roles/keyboard)
- Test: `frontend/src/components/CategoryManagerPanel.test.tsx` (extend; keep existing describe blocks)

**Interfaces:**
- Consumes: pattern from the BookmarkContextMenu task
- Produces: none

- [ ] **Step 1: Write the failing test** — Append to `CategoryManagerPanel.test.tsx` (already mocks `../i18n` identity, defines `makeProps` with categories `['Default','Work','Trips']`; `render`, `screen`, `fireEvent`, `vi` already imported). DO NOT add `@testing-library/user-event` (not a project dependency) — open the dropdown with `fireEvent.click` and activate the choice with `fireEvent.click` (jsdom does not auto-fire button onClick on Enter; the soft-delete choice is a native `<button role="menuitem">`, so its real keyboard operability is native + we prove activation with click).

```tsx
describe('CategoryManagerPanel delete-dropdown a11y (U22)', () => {
  it('the delete trigger exposes an accessible name', () => {
    render(<CategoryManagerPanel {...makeProps()} />)
    // One trigger per non-default category (Work, Trips).
    expect(screen.getAllByRole('button', { name: /bm\.cat\.delete_title/ }).length).toBe(2)
  })

  it('opens a role=menu of role=menuitem choices; clicking soft-delete triggers it', () => {
    const onCategoryDelete = vi.fn()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<CategoryManagerPanel {...makeProps({ onCategoryDelete })} />)
    const trigger = screen.getAllByRole('button', { name: /bm\.cat\.delete_title/ })[0]
    fireEvent.click(trigger)
    expect(screen.getByRole('menu')).toBeTruthy()
    const soft = screen.getByRole('menuitem', { name: /bm\.delete\.softdelete_label/ })
    expect(soft.tagName).toBe('BUTTON')
    fireEvent.click(soft)
    expect(onCategoryDelete).toHaveBeenCalledWith('Work')
    confirmSpy.mockRestore()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/CategoryManagerPanel.test.tsx -t "delete-dropdown a11y"`. Expected failure: `Unable to find ... role "button" ... name /bm.cat.delete_title/` (the trigger has no accessible name) and no `role="menu"`.
- [ ] **Step 3: Implement** — (a) On the edit-pencil button (L82-98, already has `title={t('bm.cat.edit_title')}`), add `type="button"` + `aria-label={t('bm.cat.edit_title')}` to give the icon button an accessible name. (b) On the `CategoryDeleteDropdown` trigger `<button>` (L186-198), add `type="button"` + `title={t('bm.cat.delete_title')}` + `aria-label={t('bm.cat.delete_title')}` + `aria-haspopup="menu"` + `aria-expanded={open}`. Current trigger:

```tsx
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          background: 'none', border: 'none',
          color: '#f44336', cursor: 'pointer',
          padding: '2px 4px', fontSize: 11,
        }}
      >
```

becomes:

```tsx
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={t('bm.cat.delete_title')}
        aria-label={t('bm.cat.delete_title')}
        aria-haspopup="menu"
        aria-expanded={open}
        style={{
          background: 'none', border: 'none',
          color: '#f44336', cursor: 'pointer',
          padding: '2px 4px', fontSize: 11,
        }}
      >
```

(c) On the open dropdown container `<div>` (L200) add `role="menu"`. Convert its two choice rows (soft-delete L212, cascade L221) from `<div onClick={…}>` to `<button type="button" role="menuitem" onClick={…}>`, keeping the inline `padding`/`fontSize`/`cursor` (and the cascade row's `color: '#ff6b6b'`) styles plus adding `width: '100%', textAlign: 'left', background: 'transparent', border: 'none', font: 'inherit'`, and keeping the `onMouseEnter`/`onMouseLeave` background toggles — change their inline `e.currentTarget as HTMLDivElement` casts to `HTMLButtonElement`. Native `<button>` gives Enter/Space activation. Add i18n key `'bm.cat.delete_title'` to `strings.ts` (zh: `刪除分類`, en: `Delete category`) — VERIFIED ABSENT today (only `bm.cat.edit_title` exists at strings.ts:605). Do NOT change the `confirmSoft`/`confirmCascade` `window.confirm` gating, and keep the outside-click `pointerdown` close-effect (the trigger lives inside `ref`, so clicking it does not self-close).
- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/CategoryManagerPanel.test.tsx`. Expected: existing tests (the `getAllByTitle('bm.cat.edit_title')` count test still passes — `title` is retained on the pencil) + 2 new pass.
- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) + `npx vitest run` (green).
- [ ] **Step 6: Commit** — `git add frontend/src/components/CategoryManagerPanel.tsx frontend/src/components/CategoryManagerPanel.test.tsx frontend/src/i18n/strings.ts` then `git commit -m "feat(a11y): accessible-name + role=menu for CategoryManagerPanel delete dropdown (U22)"`.


---

### Task 11: DeviceChip gets a keyboard-reachable actions button + role=menu (U21)

**Files:**
- Modify: `frontend/src/components/DeviceChip.tsx` (the chip `<div ref={ref} onContextMenu={…}>` ~L76-122 is keyboard-unreachable; the portal menu `<div onClick={(e)=>e.stopPropagation()}>` ~L124-148 + its `MenuItem` rows have no menu roles; the `MenuItem` helper ~L194-211 is a `<div onClick>`)
- Test: `frontend/src/components/DeviceChip.test.tsx` (extend; keep existing describe blocks — they use `fireEvent.contextMenu` which MUST keep working)

**Interfaces:**
- Consumes: none
- Produces: none

- [ ] **Step 1: Write the failing test** — Append to `DeviceChip.test.tsx` (already defines `makeDevice`, `baseProps`, `noop`; `render`, `screen`, `fireEvent`, `vi` already imported; mocks `../i18n` identity). DO NOT add `@testing-library/user-event` (not a project dependency) — open the menu with `fireEvent.click` on the actions button and activate the menuitem with `fireEvent.click` (jsdom does not auto-fire button onClick on Enter; native `<button>` is the real keyboard-operability win, asserted via `tagName === 'BUTTON'`). The existing right-click tests stay untouched.

```tsx
describe('DeviceChip discoverable + keyboard-reachable actions (U21)', () => {
  it('exposes a keyboard-reachable actions button that opens a role=menu of menuitem buttons', () => {
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        onDisconnect={noop}
        onForget={noop}
        onRestoreOne={noop}
      />,
    )
    const actions = screen.getByRole('button', { name: /device\.chip_actions/ })
    expect(actions.tagName).toBe('BUTTON') // natively focusable + Enter/Space-operable
    fireEvent.click(actions)
    expect(screen.getByRole('menu')).toBeTruthy()
    const disc = screen.getByRole('menuitem', { name: /device\.chip_disconnect/ })
    expect(disc.tagName).toBe('BUTTON')
  })

  it('fires onDisconnect when the menuitem is activated', () => {
    const props = baseProps()
    render(
      <DeviceChip
        letter="A"
        device={makeDevice()}
        onDisconnect={props.onDisconnect}
        onForget={props.onForget}
        onRestoreOne={props.onRestoreOne}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /device\.chip_actions/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: /device\.chip_disconnect/ }))
    expect(props.onDisconnect).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/DeviceChip.test.tsx -t "discoverable + keyboard-reachable actions"`. Expected failure: `Unable to find ... role "button" ... name /device.chip_actions/` (actions are right-click only; the chip is a `<div>`).
- [ ] **Step 3: Implement** — (a) Add a visible `⋯` actions `<button>` inside the chip that left-click-opens the same `menu` state the right-click sets; native `<button>` makes it keyboard-focusable + Enter/Space-activatable. Add `const actionsBtnRef = useRef<HTMLButtonElement | null>(null)` beside the existing `ref`. Place the button as the last child of the chip `<div>` (after the trailing label `<span>`), anchoring the menu via `getBoundingClientRect()`:

```tsx
        <button
          ref={actionsBtnRef}
          type="button"
          aria-label={t('device.chip_actions')}
          aria-haspopup="menu"
          aria-expanded={!!menu}
          onClick={(e) => {
            e.stopPropagation()
            const r = (e.currentTarget as HTMLButtonElement).getBoundingClientRect()
            setMenu({ x: r.left, y: r.bottom })
          }}
          style={{
            marginLeft: 2, padding: '0 2px',
            background: 'none', border: 'none',
            color: 'inherit', cursor: 'pointer',
            fontSize: 13, lineHeight: 1,
          }}
        >⋯</button>
```

The chip `<div>` keeps its `onContextMenu` exactly (right-click parity preserved). The button's `onClick` calls `e.stopPropagation()` so the window-`click` close-listener (registered while `menu` is set) does not immediately re-close the just-opened menu. (b) On the portal menu `<div onClick={(e) => e.stopPropagation()}>` (L124), add `role="menu"` + `aria-label={t('device.chip_actions')}`. (c) Convert the local `MenuItem` helper from a `<div onClick>` to a `<button type="button" role="menuitem">` so it is focusable + Enter/Space-activatable. Current helper (L194-211):

```tsx
function MenuItem({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  const [hover, setHover] = useState(false)
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: '6px 10px',
        borderRadius: 6,
        cursor: 'pointer',
        background: hover ? 'rgba(108,140,255,0.18)' : 'transparent',
      }}
    >
      {children}
    </div>
  )
}
```

becomes:

```tsx
function MenuItem({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  const [hover, setHover] = useState(false)
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'block', width: '100%', textAlign: 'left',
        padding: '6px 10px',
        borderRadius: 6,
        border: 'none', font: 'inherit', color: 'inherit',
        cursor: 'pointer',
        background: hover ? 'rgba(108,140,255,0.18)' : 'transparent',
      }}
    >
      {children}
    </button>
  )
}
```

Add i18n key `'device.chip_actions'` to `strings.ts` (zh: `裝置操作`, en: `Device actions`) — VERIFIED ABSENT today. Do NOT change the existing `useEffect` window-click/scroll close listener, the forget-confirm modal flow, or the right-click `onContextMenu` handler — the existing tests depend on all three.
- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/DeviceChip.test.tsx`. Expected: all existing tests (right-click open via `fireEvent.contextMenu` then `getByText(...)` / restore / disconnect / forget-confirm flows — the labels still render inside the converted `<button>`s and `fireEvent.click` still fires them) + 2 new pass. NOTE: existing tests that match a menu item by `getByText('device.chip_disconnect')` still find one node; the new `getByRole('menuitem', …)` queries do not affect them.
- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors) + `npx vitest run` (green). `DeviceChipRow.tsx` needs no change (it only passes callback props).
- [ ] **Step 6: Commit** — `git add frontend/src/components/DeviceChip.tsx frontend/src/components/DeviceChip.test.tsx frontend/src/i18n/strings.ts` then `git commit -m "feat(a11y): discoverable + keyboard-reachable DeviceChip actions menu (U21)"`.


---


<!-- ===== T3 · i18n strings + design tokens + drag-leak + coordinate ownership ===== -->

### Task 12: i18n the two hardcoded DeviceStatus strings ("No device" + "{n} devices found")

**Files:**
- Modify: `frontend/src/i18n/strings.ts` (Device status block — add `device.devices_found` next to existing `device.scan_found`, locate by the `'device.scan_found'` line, NOT by line number)
- Modify: `frontend/src/components/DeviceStatus.tsx` (the `No device` placeholder in the `device ? (...) : (...)` ternary; and the `{devices.length} devices found` summary inside the device-dropdown toggle button — locate by content)
- Test: `frontend/src/components/DeviceStatus.test.tsx`

**Interfaces:**
- Consumes: none
- Produces: i18n key `device.devices_found` (with `{n}`)

> NOTE (verified at audit): this is NOT a no-op. `device.no_device` ALREADY EXISTS in strings.ts (line ~239) but DeviceStatus.tsx still renders the literal `No device` (line ~242). `device.devices_found` does NOT exist and the count is rendered as the literal `{devices.length} devices found` (line ~347). So: add ONE new key + swap BOTH literals to `t()`. The existing tests assert the literals (`'No device'` + `'2 devices found'` + two `'1 devices found'`) and MUST be updated in this same commit. `const t = useT();` is already in scope (line ~55).

- [ ] **Step 1: Write the failing test** — The test file mocks `useT` as a key-passthrough (`useT: () => (key: string) => key`) AND the mock IGNORES interpolation vars, so under the mock `t('device.devices_found', {n})` renders the bare key `device.devices_found` (NOT `2 devices found`). Update the four existing literal lookups to the keys, and add one explicit count-key test:
  - `it('shows "No device" placeholder when device is null', ...)` → change `screen.getByText('No device')` to `screen.getByText('device.no_device')`.
  - `it('opens the device dropdown and lists every device on toggle', ...)` → change `screen.getByText('2 devices found')` to `screen.getByText('device.devices_found')`.
  - `it('fires onSelect with the device id when a dropdown row is clicked', ...)` → change `screen.getByText('1 devices found')` to `screen.getByText('device.devices_found')`.
  - `it('does NOT auto-expand when all devices are healthy', ...)` → change `screen.getByText('1 devices found')` to `screen.getByText('device.devices_found')`.
  Then add a dedicated test proving `t()` is wired (the bare key proves it is NOT the hardcoded English string):
```tsx
  it('renders the devices_found count via t() (key, since the i18n mock ignores vars)', () => {
    const a = makeDevice({ id: 'a', udid: 'ua', name: 'iPhone A' })
    const b = makeDevice({ id: 'b', udid: 'ub', name: 'iPhone B' })
    render(<DeviceStatus {...baseProps} devices={[a, b]} />)
    expect(screen.getByText('device.devices_found')).toBeInTheDocument()
    // The hardcoded English summary must be gone.
    expect(screen.queryByText('2 devices found')).not.toBeInTheDocument()
  })
```
Keep the rest of each existing test body unchanged.

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/DeviceStatus.test.tsx`. Expected FAIL: the swapped lookups (`device.no_device`, `device.devices_found`) throw `Unable to find an element with the text` because the component still renders the literals `No device` / `2 devices found` / `1 devices found`.

- [ ] **Step 3: Implement** — (a) In `strings.ts`, after the existing line
```ts
  'device.scan_found': { zh: '找到 {n} 台裝置', en: 'Found {n} device(s)' },
```
add:
```ts
  'device.devices_found': { zh: '找到 {n} 台裝置', en: '{n} device(s) found' },
```
(b) In `DeviceStatus.tsx`, change the placeholder ternary branch from:
```tsx
            <div style={{ fontSize: 13, opacity: 0.6 }}>No device</div>
```
to:
```tsx
            <div style={{ fontSize: 13, opacity: 0.6 }}>{t('device.no_device')}</div>
```
and change the dropdown summary from:
```tsx
              {devices.length} devices found
```
to:
```tsx
              {t('device.devices_found', { n: devices.length })}
```

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/DeviceStatus.test.tsx`. Expected PASS for all DeviceStatus tests.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0 errors — `device.devices_found` is auto-typed via `StringKey = keyof typeof STRINGS`) + `cd frontend && npx vitest run` (green) + `cd frontend && npx depcruise --config .dependency-cruiser.cjs src` (0 errors).

- [ ] **Step 6: Commit** — `git add frontend/src/i18n/strings.ts frontend/src/components/DeviceStatus.tsx frontend/src/components/DeviceStatus.test.tsx` then `git commit -m "i18n(device): t() the No device + devices-found strings (add device.devices_found)"`


---

### Task 13: Switch CloudSyncBusyOverlay + LangToggle inline styles to design tokens (var(--accent-*) / var(--z-*))

**Files:**
- Modify: `frontend/src/components/CloudSyncBusyOverlay.tsx` (the `backdrop.zIndex = 9999` literal and the `spinner.borderTopColor = '#6c8cff'` literal — locate by content)
- Modify: `frontend/src/components/LangToggle.tsx` (the `btnStyle` `color` + `borderBottom` `#6c8cff` literals — locate by content)
- Test: `frontend/src/components/CloudSyncBusyOverlay.test.tsx` (Create)

**Interfaces:**
- Consumes: none (CSS vars already defined in `styles.css :root`: `--accent-blue: #6c8cff` line 24, `--z-modal: 1000` line 70, `--z-toast: 1500` line 71, `--z-tooltip: 2000` line 72)
- Produces: none

> NOTE (verified at audit): `CloudSyncBusyOverlay` uses `zIndex: 9999`, which is ABOVE the entire `--z-*` scale (max `--z-tooltip: 2000`). It is a full-screen blocking modal, so it should sit at `--z-modal` (1000). Its spinner `borderTopColor` hardcodes the accent blue. The component already renders `role="alert" aria-live="assertive"` on the backdrop and reads `busy/tookTooLong/cancel` from `useCloudSyncBusy()`. LangToggle hardcodes the accent blue in active-button color + underline.

- [ ] **Step 1: Write the failing test** — jsdom does not resolve CSS vars to hex, but it DOES preserve the literal `var(...)` string in `element.style`, so asserting the computed inline style string proves the token swap. The overlay returns `null` unless `busy` is true, so mock `useCloudSyncBusy` to force the visible state. Mirror the import/mock style of `UserAvatarPicker.test.tsx`:
```tsx
import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

vi.mock('../contexts/CloudSyncBusyContext', () => ({
  useCloudSyncBusy: () => ({ busy: true, tookTooLong: false, cancel: vi.fn() }),
}))

import { CloudSyncBusyOverlay } from './CloudSyncBusyOverlay'

describe('CloudSyncBusyOverlay', () => {
  it('renders as an assertive alert region', () => {
    render(<CloudSyncBusyOverlay />)
    const region = screen.getByRole('alert')
    expect(region).toHaveAttribute('aria-live', 'assertive')
  })

  it('reads its z-index from the --z-modal token, not an off-scale literal', () => {
    render(<CloudSyncBusyOverlay />)
    const region = screen.getByRole('alert')
    // jsdom preserves the literal var() string in the inline style.
    expect(region.style.zIndex).toBe('var(--z-modal)')
    expect(region.style.zIndex).not.toBe('9999')
  })
})
```
(Note: `CloudSyncBusyOverlay` is a NAMED export — `export function CloudSyncBusyOverlay()` — so use `import { CloudSyncBusyOverlay }`, not a default import.)

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/CloudSyncBusyOverlay.test.tsx`. Expected: the alert-role test PASSES (already correct in the component); the z-index test FAILS with `expected '9999' to be 'var(--z-modal)'`.

- [ ] **Step 3: Implement** — (a) In `CloudSyncBusyOverlay.tsx`, in the `backdrop` style object change:
```tsx
    zIndex: 9999,
```
to:
```tsx
    zIndex: 'var(--z-modal)',
```
and in the `spinner` style object change:
```tsx
    borderTopColor: '#6c8cff',
```
to:
```tsx
    borderTopColor: 'var(--accent-blue)',
```
(b) In `LangToggle.tsx`, in `btnStyle` change:
```tsx
    color: active ? '#6c8cff' : 'rgba(255,255,255,0.45)',
    fontWeight: active ? 600 : 400,
    cursor: 'pointer',
    borderBottom: active ? '1px solid #6c8cff' : '1px solid transparent',
```
to:
```tsx
    color: active ? 'var(--accent-blue)' : 'rgba(255,255,255,0.45)',
    fontWeight: active ? 600 : 400,
    cursor: 'pointer',
    borderBottom: active ? '1px solid var(--accent-blue)' : '1px solid transparent',
```
Note: `React.CSSProperties` accepts `string` for `zIndex` (it is `number | string`), so `'var(--z-modal)'` type-checks.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/CloudSyncBusyOverlay.test.tsx`. Expected PASS on both tests.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0) + `cd frontend && npx vitest run` (green) + `cd frontend && npx depcruise --config .dependency-cruiser.cjs src` (0 errors).

- [ ] **Step 6: Commit** — `git add frontend/src/components/CloudSyncBusyOverlay.tsx frontend/src/components/LangToggle.tsx frontend/src/components/CloudSyncBusyOverlay.test.tsx` then `git commit -m "style(tokens): read accent + z-index from CSS vars in CloudSyncBusyOverlay + LangToggle"`


---

### Task 14: Fix UserAvatarPicker drag listener leak + setState-after-unmount on mid-drag close

**Files:**
- Modify: `frontend/src/components/UserAvatarPicker.tsx` (the `beginDrag` mousedown handler that adds `mousemove`/`mouseup` document listeners removed ONLY in `onUp` — locate by the `document.addEventListener('mousemove', onMove, true)` content)
- Test: `frontend/src/components/UserAvatarPicker.test.tsx`

**Interfaces:**
- Consumes: none
- Produces: none

> NOTE (verified at audit): `beginDrag` registers capture-phase `mousemove`/`mouseup` document listeners and removes them ONLY inside `onUp`. If the panel unmounts mid-drag (onClose fires while a drag is in flight, before `mouseup`), the listeners are never removed → leaked listener + `setDragOffset` after unmount. Fix: track the active detach via a ref and run it from a `useEffect` unmount cleanup. The test file currently has 10 existing `it()` tests (not 11).

- [ ] **Step 1: Write the failing test** — Append to the existing `describe('UserAvatarPicker', ...)` block (this file already imports `render, screen, fireEvent, waitFor` and mocks `../i18n` + `../userAvatars`). Start a drag on the title bar, unmount mid-drag, and assert both capture-phase listeners were torn down:
```tsx
  it('removes the document drag listeners when unmounted mid-drag', () => {
    const removeSpy = vi.spyOn(document, 'removeEventListener')
    const props = baseProps()
    const { unmount } = render(<UserAvatarPicker {...props} />)
    // Title bar is the drag handle (cursor: move); start a drag on it.
    const title = screen.getByText('avatar.title')
    const handle = title.parentElement as HTMLElement
    fireEvent.mouseDown(handle, { clientX: 10, clientY: 10 })
    // Unmount while the drag is still in flight (no mouseup yet).
    unmount()
    // Both capture-phase listeners must have been torn down on unmount.
    expect(removeSpy).toHaveBeenCalledWith('mousemove', expect.any(Function), true)
    expect(removeSpy).toHaveBeenCalledWith('mouseup', expect.any(Function), true)
    removeSpy.mockRestore()
  })
```
(The title `<div>{t('avatar.title')}</div>` is wrapped by the drag `<div onMouseDown={beginDrag}>`, so `title.parentElement` is the drag handle. The i18n mock returns the key, so the title text is `avatar.title`.)

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/components/UserAvatarPicker.test.tsx -t "removes the document drag listeners when unmounted mid-drag"`. Expected FAIL: `removeEventListener` was never called with `'mousemove'/'mouseup'` because the current code only removes listeners inside `onUp` (which never fires when unmounting before mouseup).

- [ ] **Step 3: Implement** — In `UserAvatarPicker.tsx`, replace the current drag block:
```tsx
  const [dragOffset, setDragOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const beginDrag = (e: React.MouseEvent) => {
    const t = e.target as HTMLElement;
    if (t.closest('button')) return;
    e.preventDefault();
    e.stopPropagation();
    const baseX = dragOffset.x;
    const baseY = dragOffset.y;
    const startX = e.clientX;
    const startY = e.clientY;
    const onMove = (ev: MouseEvent) => {
      ev.preventDefault();
      setDragOffset({
        x: baseX + (ev.clientX - startX),
        y: baseY + (ev.clientY - startY),
      });
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove, true);
      document.removeEventListener('mouseup', onUp, true);
    };
    document.addEventListener('mousemove', onMove, true);
    document.addEventListener('mouseup', onUp, true);
  };
```
with a ref-tracked + unmount-cleaned version:
```tsx
  const [dragOffset, setDragOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  // Track the in-flight drag listeners so an unmount mid-drag (panel closed
  // before mouseup) tears them down — otherwise the document listeners leak
  // and setDragOffset fires after unmount. detach() is idempotent.
  const dragHandlersRef = useRef<(() => void) | null>(null);
  const beginDrag = (e: React.MouseEvent) => {
    const t = e.target as HTMLElement;
    if (t.closest('button')) return;
    e.preventDefault();
    e.stopPropagation();
    const baseX = dragOffset.x;
    const baseY = dragOffset.y;
    const startX = e.clientX;
    const startY = e.clientY;
    const onMove = (ev: MouseEvent) => {
      ev.preventDefault();
      setDragOffset({
        x: baseX + (ev.clientX - startX),
        y: baseY + (ev.clientY - startY),
      });
    };
    const detach = () => {
      document.removeEventListener('mousemove', onMove, true);
      document.removeEventListener('mouseup', onUp, true);
      dragHandlersRef.current = null;
    };
    const onUp = () => detach();
    document.addEventListener('mousemove', onMove, true);
    document.addEventListener('mouseup', onUp, true);
    dragHandlersRef.current = detach;
  };
  // On unmount, tear down any drag that is still in flight.
  useEffect(() => () => { dragHandlersRef.current?.(); }, []);
```
`useEffect` and `useRef` are already imported at the top (`import React, { useEffect, useRef, useState } from 'react';`).

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/components/UserAvatarPicker.test.tsx -t "removes the document drag listeners when unmounted mid-drag"`. Expected PASS. Then run the whole file `cd frontend && npx vitest run src/components/UserAvatarPicker.test.tsx` to confirm the existing 10 tests still pass (11 total with the new one).

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0) + `cd frontend && npx vitest run` (green) + `cd frontend && npx depcruise --config .dependency-cruiser.cjs src` (0 errors).

- [ ] **Step 6: Commit** — `git add frontend/src/components/UserAvatarPicker.tsx frontend/src/components/UserAvatarPicker.test.tsx` then `git commit -m "fix(avatar): tear down drag listeners on unmount to stop leak + setState-after-unmount"`


---

### Task 15: Delete the dead backend CoordinateFormatter parser; keep only the .format enum passthrough (kills A15 DMS negative-degree bug)

**Files:**
- Modify: `backend/services/coord_format.py` (delete every method except `__init__` + the `self.format` attribute; drop now-unused imports — locate by content)
- Test: `backend/tests/test_coord_format_cov.py` (replace the file: the 43 dialect/format/conversion tests reference deleted methods and must go; keep ONE characterization pair for the surviving `.format` default)

**Interfaces:**
- Consumes: none
- Produces: none (the production surface — `CoordinateFormatter().format`, GET/PUT `/api/settings/coord-format`, the WS settings `coord_format` field — is UNCHANGED)

> NOTE (verified at audit): `CoordinateFormatter`'s parse/format/conversion methods are DEAD — a grep across backend (excluding tests + .venv) finds the methods defined ONLY in coord_format.py; the only callers live in test_coord_format_cov.py. Production only ever (1) constructs `CoordinateFormatter()` (main.py:138), (2) sets `.format` from persisted settings (main.py:223, `CoordinateFormat(fmt)`), (3) reads `.format.value` into the WS settings payload (main.py:301) and the REST GET/PUT in api/location.py:424/430, (4) injects it through bootstrap/container.py:33+50 + api/deps.py:29-30. The A15 DMS negative-degree bug lives entirely inside `_try_parse_dms`/`_try_parse_dm`/`_format_value`, so deleting the dead body REMOVES the bug — no separate fix. BEHAVIOR-PRESERVING for the live surface.

- [ ] **Step 1: Write the failing test** — Replace `backend/tests/test_coord_format_cov.py` entirely with a characterization test that pins ONLY the surviving behavior. Mirror the existing pytest style (plain module-level `def test_*`, import from `services.coord_format` + `models.schemas`):
```python
"""Characterization test for services.coord_format.CoordinateFormatter.

The DD/DMS/DM parser + formatter + conversion helpers were deleted as dead
code (only this test exercised them; production reads ONLY `.format`). What
remains is a thin holder for the persisted UI coord-format preference, wired
through the DI container and echoed in the WS settings payload + the REST
GET/PUT /settings/coord-format endpoints. This test freezes that surface.
"""

from __future__ import annotations

from models.schemas import CoordinateFormat
from services.coord_format import CoordinateFormatter


def test_default_format_is_dd():
    assert CoordinateFormatter().format == CoordinateFormat.DD


def test_format_attribute_is_assignable():
    # main.py load_state assigns `.format = CoordinateFormat(fmt)` from the
    # persisted settings; api/location.py PUT assigns `.format = req.format`.
    f = CoordinateFormatter()
    f.format = CoordinateFormat.DMS
    assert f.format.value == "dms"
```

- [ ] **Step 2: Run test, verify it fails** — This is a dead-code deletion, so there is no single failing assertion; the RED→GREEN safety net is the full-suite + lint-imports. BEFORE deletion, confirm the kept tests already pass and the whole suite is green: `cd backend && .venv/bin/python -m pytest tests/test_coord_format_cov.py -q` (2 new tests PASS — they touch only `.format`) and `cd backend && .venv/bin/python -m pytest -q` (green, baseline 981 collected). The structural red signal is captured in Step 4/5: after deletion, re-running proves no production import broke and the collection dropped exactly as expected.

- [ ] **Step 3: Implement** — Replace the entire body of `backend/services/coord_format.py` with the reduced holder. Current file opens:
```python
"""Coordinate format switching: DD, DMS, DM."""

from __future__ import annotations

import math
import re

from models.schemas import Coordinate, CoordinateFormat


class CoordinateFormatter:
    """Formats and parses geographic coordinates in multiple notations."""

    def __init__(self) -> None:
        self.format: CoordinateFormat = CoordinateFormat.DD
```
...followed by `format_coord`, `format_lat`, `format_lng`, `_format_value`, `parse_coord`, `_try_parse_dms`, `_try_parse_dm`, `_try_parse_dd`, `_dd_to_dms`, `_dd_to_dm`. Delete ALL of those methods and the now-unused imports (`math`, `re`, and `Coordinate` — `Coordinate` is no longer referenced; `CoordinateFormat` stays). New full file:
```python
"""Persisted coordinate-format preference (DD / DMS / DM).

The DD/DMS/DM parser + formatter once lived here but was dead code: production
only ever reads/writes `.format`. The parser is gone; this is now a thin
holder for the user's persisted coord-format choice, wired through the DI
container (bootstrap/container.py) and surfaced via the WS settings payload
and the REST GET/PUT /api/settings/coord-format endpoints.
"""

from __future__ import annotations

from models.schemas import CoordinateFormat


class CoordinateFormatter:
    """Holds the persisted coordinate-format preference."""

    def __init__(self) -> None:
        self.format: CoordinateFormat = CoordinateFormat.DD
```
Do NOT touch main.py, api/location.py, api/deps.py, or bootstrap/container.py — they only use `__init__` + `.format`, which are preserved.

- [ ] **Step 4: Run test, verify it passes** — `cd backend && .venv/bin/python -m pytest tests/test_coord_format_cov.py -q`. Expected PASS (2 tests). The collection count for this file drops from 44 → 2.

- [ ] **Step 5: tsc + broader suite** — backend: `cd backend && .venv/bin/python -m pytest -q` — expected GREEN with collection dropped from baseline 981 to 939 (981 − 44 + 2 = 939; STATE the exact collected number printed). This drop is EXPECTED for dead-code deletion. Then `cd backend && .venv/bin/lint-imports` — expected `7 kept, 0 broken` (`services/coord_format.py` still imports only `models.schemas`).

- [ ] **Step 6: Commit** — `git add backend/services/coord_format.py backend/tests/test_coord_format_cov.py` then `git commit -m "refactor(coord): delete dead CoordinateFormatter parser, keep .format enum passthrough"`


---

### Task 16: Consolidate the two frontend decimal-coord helpers into one module (behavior-preserving)

**Files:**
- Modify: `frontend/src/utils/coords.ts` (becomes the single coord-parsing home — add `trySplitLatLng` here alongside `parseCoord`, keeping the regex distinct)
- Modify: `frontend/src/utils/latlng.ts` (re-export `trySplitLatLng` from `./coords` so the two dialog imports keep working unchanged)
- Test: `frontend/src/utils/coords.test.ts` and `frontend/src/utils/latlng.test.ts` (extend FIRST with a characterization block pinning current acceptance of BOTH helpers; both files keep their existing cases)

**Interfaces:**
- Consumes: none
- Produces: none (`parseCoord` and `trySplitLatLng` keep their EXACT signatures + return contracts — `parseCoord(raw): {lat,lng}|null`, `trySplitLatLng(s): [string,string]|null`)

> NOTE (verified at audit): the two helpers have DIFFERENT return contracts and serve DIFFERENT dialogs and MUST both be preserved verbatim. `parseCoord` (coords.ts line 34) scrapes the first valid range-checked decimal pair out of arbitrary text and returns parsed NUMBERS — used by App.tsx (lines 425/556) + CoordInputStrip.tsx (81/95). `trySplitLatLng` (latlng.ts line 7) matches a STRICT whole-input pair and returns RAW STRING halves (so the dialogs keep partial text while typing) with NO range check — used by CustomBookmarkDialog.tsx (128) + EditBookmarkDialog.tsx (135). Their inner regexes are NOT identical: `trySplitLatLng` uses separator class `[,\t ]` (exactly one comma/tab/space); `parseCoord`'s integer fallback `COORD_INTEGER_RE` (coords.ts line 24) uses `[,;\s]+` (also accepts `;` and runs of whitespace). Merging them would CHANGE acceptance — DO NOT. The consolidation = single MODULE home (both helpers in coords.ts, latlng.ts becomes a re-export shim), NOT a single regex. DMS/DM paste is OUT OF SCOPE.

- [ ] **Step 1: Write the failing test (characterization first)** — Add a consolidation-import block to `coords.test.ts` proving `trySplitLatLng` is now importable from `./coords` with its current behavior intact, and add a shim-check to `latlng.test.ts` proving the old import path still resolves. Keep ALL existing cases in both files unchanged. Append to `coords.test.ts`:
```ts
import { trySplitLatLng } from './coords'

describe('trySplitLatLng (consolidated into coords.ts)', () => {
  // Pin the EXACT current acceptance — these mirror latlng.test.ts so a
  // regression in either dialog's accepted input is caught immediately.
  it('splits a comma-separated pair into raw string halves', () => {
    expect(trySplitLatLng('24.14, 120.65')).toEqual(['24.14', '120.65'])
  })
  it('splits a pair with no space after the comma', () => {
    expect(trySplitLatLng('24.14,120.65')).toEqual(['24.14', '120.65'])
  })
  it('splits a whitespace-separated pair', () => {
    expect(trySplitLatLng('24.14 120.65')).toEqual(['24.14', '120.65'])
  })
  it('splits a tab-separated pair', () => {
    expect(trySplitLatLng('24.14\t120.65')).toEqual(['24.14', '120.65'])
  })
  it('handles negative coordinates', () => {
    expect(trySplitLatLng('-33.86, -151.20')).toEqual(['-33.86', '-151.20'])
  })
  it('splits integer (no-decimal) pairs', () => {
    expect(trySplitLatLng('25, 121')).toEqual(['25', '121'])
  })
  it('does NOT range-check (returns raw out-of-range halves)', () => {
    // Distinguishes trySplitLatLng from parseCoord, which WOULD reject this.
    expect(trySplitLatLng('95, 200')).toEqual(['95', '200'])
  })
  it('returns null while still typing the first number', () => {
    expect(trySplitLatLng('24.1')).toBeNull()
  })
  it('returns null for a single trailing comma', () => {
    expect(trySplitLatLng('24.14,')).toBeNull()
  })
  it('returns null for non-numeric input', () => {
    expect(trySplitLatLng('Taipei 101')).toBeNull()
  })
})
```
Also append to `latlng.test.ts` a shim-resolution assertion (keeps the old import path covered; `trySplitLatLng` is already imported at the top of that file):
```ts
it('still exports trySplitLatLng from the latlng module (shim)', () => {
  expect(typeof trySplitLatLng).toBe('function')
  expect(trySplitLatLng('1.0, 2.0')).toEqual(['1.0', '2.0'])
})
```

- [ ] **Step 2: Run test, verify it fails** — `cd frontend && npx vitest run src/utils/coords.test.ts`. Expected FAIL: `import { trySplitLatLng } from './coords'` resolves to `undefined` (not yet exported from coords.ts) → the new `describe` block's cases throw / fail.

- [ ] **Step 3: Implement** — (a) Append `trySplitLatLng` to `frontend/src/utils/coords.ts`, moving it from latlng.ts VERBATIM (its strict regex stays distinct from `COORD_INTEGER_RE` — do not merge):
```ts
// Strict whole-input pair splitter. Unlike parseCoord (which scrapes the
// first valid pair out of arbitrary text and range-checks it), this returns
// the RAW string halves with NO range check, so the bookmark dialogs can keep
// partial text while the user is still typing. Separator class is exactly one
// comma / tab / space — intentionally narrower than parseCoord's fallback.
export function trySplitLatLng(s: string): [string, string] | null {
  const m = s.trim().match(/^(-?\d+(?:\.\d+)?)\s*[,\t ]\s*(-?\d+(?:\.\d+)?)\s*$/);
  return m ? [m[1], m[2]] : null;
}
```
(b) Replace the body of `frontend/src/utils/latlng.ts` with a re-export shim so the two dialog imports (`CustomBookmarkDialog.tsx`, `EditBookmarkDialog.tsx`) keep resolving without edits:
```ts
/**
 * trySplitLatLng moved into utils/coords.ts (single coord-parsing home).
 * Re-exported here so existing `../utils/latlng` imports keep working.
 */
export { trySplitLatLng } from './coords';
```
Do NOT edit `CustomBookmarkDialog.tsx` / `EditBookmarkDialog.tsx` — their `import { trySplitLatLng } from '../utils/latlng'` resolves through the shim.

- [ ] **Step 4: Run test, verify it passes** — `cd frontend && npx vitest run src/utils/coords.test.ts src/utils/latlng.test.ts`. Expected PASS: all existing `parseCoord` (9) + `trySplitLatLng` (10) cases plus the new consolidation block + shim check are green, proving acceptance is unchanged for both dialogs.

- [ ] **Step 5: tsc + broader suite** — `cd frontend && npx tsc --noEmit` (0) + `cd frontend && npx vitest run` (green) + `cd frontend && npx depcruise --config .dependency-cruiser.cjs src` (0 errors — latlng.ts re-exporting coords.ts adds an intra-utils edge, which depcruise allows).

- [ ] **Step 6: Commit** — `git add frontend/src/utils/coords.ts frontend/src/utils/latlng.ts frontend/src/utils/coords.test.ts frontend/src/utils/latlng.test.ts` then `git commit -m "refactor(coords): consolidate trySplitLatLng into coords.ts behind a latlng shim"`


---

<!-- ===== Acceptance + manual smoke ===== -->

### Task 17: SH4 acceptance — full gate + a11y/i18n/coord manual smoke

**Files:** none (verification only).

**Interfaces:**
- Consumes: Tasks 1-16
- Produces: none

- [ ] **Step 1: Full gate**

```bash
cd /Users/raviwu/personal/locwarp/frontend
npx tsc --noEmit && npx vitest run && npx depcruise src
cd /Users/raviwu/personal/locwarp/backend
.venv/bin/python -m pytest -q && .venv/bin/lint-imports
```
Expected: frontend tsc 0 / vitest green (708 + new a11y/i18n tests) / depcruise 0 errors; backend pytest green / lint 7-0. NOTE: backend collection is LOWER than 981 by the removed dead coord-dialect tests (X10) — that drop is expected; confirm the number and that no LIVE test was removed.

- [ ] **Step 2: Manual smoke — keyboard-only a11y (U20/U21/U22/U23/X13)**

Run `cd frontend && npm run start`. WITHOUT a mouse: Tab to a bookmark/route row, open its menu, arrow through items, activate with Enter, close with Esc; reach a device-chip's actions (Disconnect/Forget/Re-trust) by keyboard; open a dialog (Settings / a bookmark dialog / WiFi-warning / Repair) and confirm Esc closes it, focus is trapped inside, and focus lands inside on open.
- Expected: full keyboard reachability; visible focus ring; Esc closes every modal; focus trapped.

- [ ] **Step 3: Manual smoke — screen reader (U19)**

With VoiceOver on, trigger any async action.
- Expected: the toast is announced (role="status" / aria-live).

- [ ] **Step 4: Manual smoke — i18n (U24)**

Switch language to zh-TW with no device, then while scanning.
- Expected: NO stray English in the device panel ("No device" / "N devices found" are translated).

- [ ] **Step 5: Manual smoke — visual consistency + coord (X13/U27/X11)**

Open several dialogs.
- Expected: consistent overlay/spacing/accent via `DialogShell` + design tokens; no off-scale layering. Paste a decimal coordinate into a bookmark dialog → it parses exactly as before (X11 consolidation behavior-preserving). The dead backend coord parser is gone (test count dropped accordingly).

**SH4 acceptance:** full gate green (Step 1); keyboard + screen-reader + i18n + visual/coord smoke (Steps 2-5) observed and evidenced. All single-device / no-device verifiable.
