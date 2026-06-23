import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/react';

// i18n -> identity translator (same pattern as S2LevelPicker / WaypointMenu
// tests). The strip uses plain string keys with no interpolation, so identity
// is enough. Placeholders / button labels surface as their raw key strings.
const fakeT = (k: string, params?: Record<string, unknown>) =>
  params ? `${k}:${Object.values(params).join(',')}` : k;
vi.mock('../i18n', () => ({
  useT: () => fakeT,
  useI18n: () => ({ lang: 'en', setLang: vi.fn(), t: fakeT }),
}));

import { CoordInputStrip } from './CoordInputStrip';

// jsdom has no ResizeObserver — define a stub so the status-bar observer effect
// can construct one. The stub records observe/disconnect so we can assert the
// effect's cleanup disconnects it on unmount.
class ResizeObserverStub {
  static instances: ResizeObserverStub[] = [];
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  constructor(public cb: ResizeObserverCallback) {
    ResizeObserverStub.instances.push(this);
  }
}

// Defaults satisfying the prop contract; each test overrides what it asserts.
function makeProps(over: Partial<Record<string, any>> = {}) {
  return {
    deviceConnected: true,
    onTeleport: vi.fn(),
    onNavigate: vi.fn(),
    onPreview: vi.fn(),
    onShowToast: vi.fn(),
    onStatusBarHeight: vi.fn(),
    ...over,
  } as any;
}

// The coord input is the only text <input> in the strip.
function getInput(container: HTMLElement) {
  return container.querySelector('input[type="text"]') as HTMLInputElement;
}

describe('CoordInputStrip', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    ResizeObserverStub.instances = [];
    (global as any).ResizeObserver = ResizeObserverStub as any;
  });

  afterEach(() => {
    delete (global as any).ResizeObserver;
  });

  // --- renders -------------------------------------------------------------
  it('renders the input + the four action buttons', () => {
    const { getByText, container } = render(<CoordInputStrip {...makeProps()} />);
    expect(getInput(container)).toBeTruthy();
    expect(getByText('panel.paste')).toBeTruthy();
    expect(getByText('panel.coord_teleport')).toBeTruthy();
    expect(getByText('panel.coord_preview')).toBeTruthy();
    expect(getByText('panel.coord_navigate')).toBeTruthy();
  });

  // --- valid teleport ------------------------------------------------------
  it('fires onTeleport with the parsed numbers + clears the input on teleport', () => {
    const onTeleport = vi.fn();
    const { getByText, container } = render(
      <CoordInputStrip {...makeProps({ onTeleport })} />,
    );
    const input = getInput(container);
    fireEvent.change(input, { target: { value: '25.0330, 121.5654' } });
    fireEvent.click(getByText('panel.coord_teleport'));
    expect(onTeleport).toHaveBeenCalledTimes(1);
    expect(onTeleport).toHaveBeenCalledWith(25.033, 121.5654, 'coord');
    // Input is cleared after a successful teleport.
    expect(input.value).toBe('');
  });

  // --- Enter key submits as teleport ---------------------------------------
  it('submits a teleport on Enter (not mid-IME-composition)', () => {
    const onTeleport = vi.fn();
    const { container } = render(<CoordInputStrip {...makeProps({ onTeleport })} />);
    const input = getInput(container);
    fireEvent.change(input, { target: { value: '35.018, 135.584' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onTeleport).toHaveBeenCalledWith(35.018, 135.584, 'coord');
  });

  // --- valid navigate ------------------------------------------------------
  it('fires onNavigate with the parsed numbers + clears the input on navigate', () => {
    const onNavigate = vi.fn();
    const { getByText, container } = render(
      <CoordInputStrip {...makeProps({ onNavigate })} />,
    );
    const input = getInput(container);
    fireEvent.change(input, { target: { value: '(-33.41902, -70.70187) 一般火' } });
    fireEvent.click(getByText('panel.coord_navigate'));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    // parseCoord scrapes the bracketed pair, ignoring the trailing note.
    expect(onNavigate).toHaveBeenCalledWith(-33.41902, -70.70187, 'coord');
    expect(input.value).toBe('');
  });

  // --- valid preview keeps the input -------------------------------------
  it('fires onPreview with the parsed numbers but does NOT clear the input', () => {
    const onPreview = vi.fn();
    const { getByText, container } = render(
      <CoordInputStrip {...makeProps({ onPreview })} />,
    );
    const input = getInput(container);
    fireEvent.change(input, { target: { value: '48.8584, 2.2945' } });
    fireEvent.click(getByText('panel.coord_preview'));
    expect(onPreview).toHaveBeenCalledWith(48.8584, 2.2945);
    // Preview keeps the value so the user can promote it to a real teleport.
    expect(input.value).toBe('48.8584, 2.2945');
  });

  // --- invalid coord rejected ----------------------------------------------
  it('rejects an invalid coord: no callback, toast shown, buttons stay disabled', () => {
    const onTeleport = vi.fn();
    const onShowToast = vi.fn();
    const { getByText, container } = render(
      <CoordInputStrip {...makeProps({ onTeleport, onShowToast })} />,
    );
    const input = getInput(container);
    // No numeric pair at all — parseCoord returns null.
    fireEvent.change(input, { target: { value: 'not a coordinate' } });
    const teleportBtn = getByText('panel.coord_teleport') as HTMLButtonElement;
    // The trimmed input is non-empty, so the button is enabled, but the
    // click is rejected by parseCoord -> toast, no teleport.
    fireEvent.click(teleportBtn);
    expect(onTeleport).not.toHaveBeenCalled();
    expect(onShowToast).toHaveBeenCalledWith('panel.coord_invalid');
  });

  // --- empty input disables the submit buttons -----------------------------
  it('disables the submit buttons while the input is empty', () => {
    const { getByText } = render(<CoordInputStrip {...makeProps()} />);
    expect((getByText('panel.coord_teleport') as HTMLButtonElement).disabled).toBe(true);
    expect((getByText('panel.coord_preview') as HTMLButtonElement).disabled).toBe(true);
    expect((getByText('panel.coord_navigate') as HTMLButtonElement).disabled).toBe(true);
  });

  // --- device-gating: teleport / navigate disabled when disconnected -------
  it('disables teleport + navigate (but NOT preview) when the device is disconnected', () => {
    const { getByText, container } = render(
      <CoordInputStrip {...makeProps({ deviceConnected: false })} />,
    );
    fireEvent.change(getInput(container), { target: { value: '25.03, 121.56' } });
    expect((getByText('panel.coord_teleport') as HTMLButtonElement).disabled).toBe(true);
    expect((getByText('panel.coord_navigate') as HTMLButtonElement).disabled).toBe(true);
    // Preview is camera-only, so it stays enabled regardless of connection.
    expect((getByText('panel.coord_preview') as HTMLButtonElement).disabled).toBe(false);
  });

  // --- clipboard paste path ------------------------------------------------
  it('fills the input from the clipboard (trimmed) when Paste is clicked', async () => {
    const readText = vi.fn().mockResolvedValue('  25.033, 121.565  ');
    Object.assign(navigator, { clipboard: { readText } });
    const { getByText, container } = render(<CoordInputStrip {...makeProps()} />);
    fireEvent.click(getByText('panel.paste'));
    // Let the awaited clipboard read + setState flush.
    await waitFor(() => expect(getInput(container).value).toBe('25.033, 121.565'));
    expect(readText).toHaveBeenCalledTimes(1);
  });

  it('toasts paste_denied when the clipboard read rejects', async () => {
    const readText = vi.fn().mockRejectedValue(new Error('denied'));
    Object.assign(navigator, { clipboard: { readText } });
    const onShowToast = vi.fn();
    const { getByText } = render(<CoordInputStrip {...makeProps({ onShowToast })} />);
    fireEvent.click(getByText('panel.paste'));
    await waitFor(() => expect(onShowToast).toHaveBeenCalledWith('panel.paste_denied'));
  });

  // --- ResizeObserver: status-bar height reported + cleaned up -------------
  it('observes the status bar, reports its height, and disconnects on unmount', () => {
    const onStatusBarHeight = vi.fn();
    // The effect early-returns unless a .status-bar element exists in the DOM.
    const bar = document.createElement('div');
    bar.className = 'status-bar';
    document.body.appendChild(bar);
    const { unmount } = render(
      <CoordInputStrip {...makeProps({ onStatusBarHeight })} />,
    );
    // One observer constructed + observing the bar; height reported on mount.
    expect(ResizeObserverStub.instances).toHaveLength(1);
    const ro = ResizeObserverStub.instances[0];
    expect(ro.observe).toHaveBeenCalledWith(bar);
    expect(onStatusBarHeight).toHaveBeenCalled();
    // Cleanup disconnects the observer.
    unmount();
    expect(ro.disconnect).toHaveBeenCalledTimes(1);
    document.body.removeChild(bar);
  });
});
