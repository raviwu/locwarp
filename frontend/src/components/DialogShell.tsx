import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

// Module-level open-shell stack so Escape closes only the TOPMOST dialog.
// Each open DialogShell pushes a stable token (object identity) on mount and
// pops it on unmount. The Escape handler fires onClose only when this shell's
// token is at the top of the stack.
const _openShells: object[] = [];

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
  // Stable token representing this shell instance in the open-shell stack.
  const tokenRef = useRef<object>({});

  // Maintain the open-shell stack: push when open, pop on close/unmount.
  useEffect(() => {
    if (!open) return;
    const token = tokenRef.current;
    _openShells.push(token);
    return () => {
      const idx = _openShells.lastIndexOf(token);
      if (idx !== -1) _openShells.splice(idx, 1);
    };
  }, [open]);

  // Escape-to-close (capture phase so it fires before inner inputs swallow it).
  // Only fires when this shell is the topmost open dialog.
  useEffect(() => {
    if (!open) return;
    const token = tokenRef.current;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy && _openShells[_openShells.length - 1] === token) {
        onClose();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [open, busy, onClose]);

  // Initial focus on open. initialFocusRef is a stable RefObject (the object
  // reference never changes, only .current does), so [open] is the correct
  // dep — re-running when initialFocusRef itself changes would be spurious.
  useEffect(() => {
    if (!open) return;
    const target = initialFocusRef?.current
      ?? panelRef.current?.querySelector<HTMLElement>(FOCUSABLE)
      ?? null;
    target?.focus();
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

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
