import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SettingsModal from './SettingsModal';

// i18n passthrough: rendered text === key, so assertions target stable keys.
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}));

// alertSound service — drive the persisted-state seam + the test button.
const isAlertSoundEnabled = vi.fn(() => true);
const setAlertSoundEnabled = vi.fn();
const playCompletionAlert = vi.fn();
vi.mock('../services/alertSound', () => ({
  isAlertSoundEnabled: () => isAlertSoundEnabled(),
  setAlertSoundEnabled: (v: boolean) => setAlertSoundEnabled(v),
  playCompletionAlert: (f?: boolean) => playCompletionAlert(f),
}));

// CloudSyncSection pulls in services/api + contexts; stub it to a marker so we
// can assert it's mounted without wiring its dependency tree.
vi.mock('./CloudSyncSection', () => ({
  CloudSyncSection: () => <div data-testid="cloud-sync-section" />,
}));

describe('SettingsModal', () => {
  beforeEach(() => {
    isAlertSoundEnabled.mockReturnValue(true);
  });
  afterEach(() => {
    vi.clearAllMocks();
    // Reset any electronAPI stub between tests.
    delete (window as any).electronAPI;
  });

  it('renders nothing when open is false', () => {
    const { container } = render(<SettingsModal open={false} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText('settings.title')).not.toBeInTheDocument();
  });

  it('renders the title, alert-sound row, and the CloudSync section when open', () => {
    render(<SettingsModal open onClose={() => {}} />);
    expect(screen.getByText('settings.title')).toBeInTheDocument();
    expect(screen.getByText('settings.alert_sound_label')).toBeInTheDocument();
    expect(screen.getByTestId('cloud-sync-section')).toBeInTheDocument();
  });

  it('seeds the alert-sound checkbox from the persisted value', () => {
    isAlertSoundEnabled.mockReturnValue(false);
    render(<SettingsModal open onClose={() => {}} />);
    const checkbox = screen.getByRole('checkbox') as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
  });

  it('toggling the alert-sound checkbox persists via setAlertSoundEnabled and flips the UI', () => {
    isAlertSoundEnabled.mockReturnValue(true);
    render(<SettingsModal open onClose={() => {}} />);
    const checkbox = screen.getByRole('checkbox') as HTMLInputElement;
    expect(checkbox.checked).toBe(true);

    fireEvent.click(checkbox);

    expect(setAlertSoundEnabled).toHaveBeenCalledWith(false);
    expect(checkbox.checked).toBe(false);
  });

  it('clicking the test button plays the completion alert with force=true', () => {
    render(<SettingsModal open onClose={() => {}} />);
    fireEvent.click(screen.getByText('settings.alert_sound_test'));
    expect(playCompletionAlert).toHaveBeenCalledWith(true);
  });

  it('invokes onClose when the close (X) button is clicked', () => {
    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} />);
    // The X button is labelled via aria-label = 'generic.close'.
    fireEvent.click(screen.getByLabelText('generic.close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('invokes onClose when the backdrop is clicked but not when the panel body is clicked', () => {
    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} />);

    // Clicking inside the panel (on the title) must NOT close (stopPropagation).
    fireEvent.click(screen.getByText('settings.title'));
    expect(onClose).not.toHaveBeenCalled();

    // Clicking the backdrop closes. After DialogShell migration, the panel is
    // the role=dialog element; its parent is the backdrop.
    const backdrop = screen.getByRole('dialog').parentElement!;
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('exposes the modal as role=dialog and closes on Escape', () => {
    const onClose = vi.fn();
    render(<SettingsModal open onClose={onClose} />);
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not render the render-mode row in a non-Electron context', async () => {
    render(<SettingsModal open onClose={() => {}} />);
    // No electronAPI -> getRenderMode never called -> renderInfo stays null.
    await waitFor(() => {
      expect(screen.queryByText('settings.render_mode_label')).not.toBeInTheDocument();
    });
  });

  it('loads and renders the render-mode toggle from electronAPI.getRenderMode', async () => {
    (window as any).electronAPI = {
      getRenderMode: vi.fn().mockResolvedValue({ mode: 'software', saved: 'software' }),
      setRenderMode: vi.fn().mockResolvedValue(undefined),
      relaunchApp: vi.fn(),
    };
    render(<SettingsModal open onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('settings.render_mode_label')).toBeInTheDocument();
    });
    // software mode -> the hardware checkbox is unchecked, status shows the sw label.
    expect(screen.getByText('settings.render_mode_sw')).toBeInTheDocument();
    const checkboxes = screen.getAllByRole('checkbox') as HTMLInputElement[];
    // Second checkbox is the render-mode (hardware) toggle.
    expect(checkboxes[1].checked).toBe(false);
  });

  it('toggling render mode calls setRenderMode and surfaces the restart hint', async () => {
    const setRenderMode = vi.fn().mockResolvedValue(undefined);
    const relaunchApp = vi.fn();
    (window as any).electronAPI = {
      getRenderMode: vi.fn().mockResolvedValue({ mode: 'software', saved: 'software' }),
      setRenderMode,
      relaunchApp,
    };
    render(<SettingsModal open onClose={() => {}} />);

    const hwToggle = await waitFor(() => {
      const cbs = screen.getAllByRole('checkbox') as HTMLInputElement[];
      expect(cbs.length).toBeGreaterThan(1);
      return cbs[1];
    });

    fireEvent.click(hwToggle);

    await waitFor(() => {
      expect(setRenderMode).toHaveBeenCalledWith('hardware');
    });
    // Dirty -> restart hint + restart-now button appear.
    await waitFor(() => {
      expect(screen.getByText('settings.render_mode_restart_hint')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('settings.render_mode_restart_now'));
    expect(relaunchApp).toHaveBeenCalledTimes(1);
  });
});
