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
