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
