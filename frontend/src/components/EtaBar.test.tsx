import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import EtaBar from './EtaBar';
import type { RuntimesMap, DeviceRuntime } from '../hooks/useSimulation';

// Passthrough i18n: t(key) → key, so we can assert on raw label keys.
vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}));

function runtime(overrides: Partial<DeviceRuntime> & { udid: string }): DeviceRuntime {
  return {
    state: 'idle',
    currentPos: null,
    destination: null,
    routePath: [],
    progress: 0,
    eta: 0,
    distanceRemaining: 0,
    distanceTraveled: 0,
    waypointIndex: null,
    currentSpeedKmh: 0,
    error: null,
    lapCount: 0,
    cooldown: 0,
    ...overrides,
  };
}

const baseProps = {
  state: 'navigating',
  progress: 0.5,
  remainingDistance: 1500,
  traveledDistance: 250,
  eta: 90,
};

describe('EtaBar — visibility gating', () => {
  it('renders nothing when state is not an active state and no group', () => {
    const { container } = render(<EtaBar {...baseProps} state="idle" />);
    expect(container.firstChild).toBeNull();
  });

  it('renders for each active single-device state', () => {
    for (const state of ['navigating', 'looping', 'multi_stop', 'random_walk']) {
      const { container, unmount } = render(<EtaBar {...baseProps} state={state} />);
      expect(container.querySelector('.eta-bar')).not.toBeNull();
      unmount();
    }
  });
});

describe('EtaBar — single-device formatting', () => {
  it('formats percent, distances (km/m) and ETA from props', () => {
    render(<EtaBar {...baseProps} />);
    // progress 0.5 → 50%
    expect(screen.getByText('50%')).toBeInTheDocument();
    // remaining 1500m → 1.50 km
    expect(screen.getByText('eta.remaining 1.50 km')).toBeInTheDocument();
    // traveled 250m → 250 m
    expect(screen.getByText('eta.traveled 250 m')).toBeInTheDocument();
    // eta 90s → 1m 30s
    expect(screen.getByText('eta.eta 1m 30s')).toBeInTheDocument();
  });

  it('formats ETA with hours when >= 3600s', () => {
    render(<EtaBar {...baseProps} eta={3725} />);
    // 3725s → 1h 2m
    expect(screen.getByText('eta.eta 1h 2m')).toBeInTheDocument();
  });

  it('formats ETA of 0 (or negative) as 0s', () => {
    render(<EtaBar {...baseProps} eta={0} />);
    expect(screen.getByText('eta.eta 0s')).toBeInTheDocument();
  });

  it('rounds sub-1000m distances to whole meters', () => {
    render(<EtaBar {...baseProps} remainingDistance={123.7} />);
    expect(screen.getByText('eta.remaining 124 m')).toBeInTheDocument();
  });

  it('clamps progress to 100% when progress exceeds 1', () => {
    render(<EtaBar {...baseProps} progress={1.5} />);
    expect(screen.getByText('100%')).toBeInTheDocument();
  });

  it('clamps progress to 0% when progress is negative', () => {
    render(<EtaBar {...baseProps} progress={-0.3} state="navigating" />);
    expect(screen.getByText('0%')).toBeInTheDocument();
  });

  it('does not render the group-progress section in single-device mode', () => {
    render(<EtaBar {...baseProps} />);
    expect(screen.queryByText('eta.group_progress')).not.toBeInTheDocument();
  });
});

describe('EtaBar — paused state', () => {
  it('shows a paused chip when isPaused=true', () => {
    render(<EtaBar {...baseProps} isPaused={true} />);
    expect(screen.getByTestId('eta-paused-chip')).toBeInTheDocument();
  });

  it('does not show the paused chip when isPaused=false', () => {
    render(<EtaBar {...baseProps} isPaused={false} />);
    expect(screen.queryByTestId('eta-paused-chip')).not.toBeInTheDocument();
  });

  it('progress fill is dimmed (opacity<1) when isPaused=true', () => {
    const { container } = render(<EtaBar {...baseProps} isPaused={true} />);
    const fill = container.querySelector('.eta-progress-fill') as HTMLElement;
    expect(fill).not.toBeNull();
    const opacity = parseFloat(fill.style.opacity);
    expect(opacity).toBeLessThan(1);
  });

  it('progress fill has full opacity when isPaused=false', () => {
    const { container } = render(<EtaBar {...baseProps} isPaused={false} />);
    const fill = container.querySelector('.eta-progress-fill') as HTMLElement;
    expect(fill).not.toBeNull();
    const opacity = fill.style.opacity === '' ? 1 : parseFloat(fill.style.opacity);
    expect(opacity).toBe(1);
  });
});

describe('EtaBar — group-mode aggregation (2+ active runtimes)', () => {
  const runtimes: RuntimesMap = {
    A: runtime({
      udid: 'A',
      state: 'navigating',
      progress: 0.4,
      eta: 60,
      distanceRemaining: 800,
      distanceTraveled: 200,
    }),
    B: runtime({
      udid: 'B',
      state: 'looping',
      progress: 0.8,
      eta: 120,
      distanceRemaining: 2000,
      distanceTraveled: 600,
    }),
    // an idle device must be excluded from aggregation
    C: runtime({ udid: 'C', state: 'idle', progress: 1, eta: 9999 }),
  };

  it('uses average progress across active runtimes', () => {
    // (0.4 + 0.8) / 2 = 0.6 → 60%
    render(<EtaBar {...baseProps} progress={0.1} runtimes={runtimes} />);
    expect(screen.getByText('60%')).toBeInTheDocument();
  });

  it('uses max ETA and max remaining distance across active runtimes', () => {
    render(<EtaBar {...baseProps} runtimes={runtimes} />);
    // max eta = 120s → 2m 0s
    expect(screen.getByText('eta.eta 2m 0s')).toBeInTheDocument();
    // max remaining = 2000m → 2.00 km
    expect(screen.getByText('eta.remaining 2.00 km')).toBeInTheDocument();
  });

  it('sums traveled distance across active runtimes', () => {
    render(<EtaBar {...baseProps} runtimes={runtimes} />);
    // 200 + 600 = 800 m
    expect(screen.getByText('eta.traveled 800 m')).toBeInTheDocument();
  });

  it('renders the group-progress section with per-device A/B ETAs', () => {
    render(<EtaBar {...baseProps} runtimes={runtimes} />);
    expect(screen.getByText('eta.group_progress')).toBeInTheDocument();
    expect(screen.getByText('A 1m 0s')).toBeInTheDocument();
    expect(screen.getByText('B 2m 0s')).toBeInTheDocument();
  });

  it('renders even when single-device state is idle, because group is active', () => {
    const { container } = render(<EtaBar {...baseProps} state="idle" runtimes={runtimes} />);
    expect(container.querySelector('.eta-bar')).not.toBeNull();
  });

  it('treats a single active runtime as non-group (falls back to props)', () => {
    const oneActive: RuntimesMap = {
      A: runtime({ udid: 'A', state: 'navigating', progress: 0.9, eta: 30 }),
      C: runtime({ udid: 'C', state: 'idle' }),
    };
    render(<EtaBar {...baseProps} progress={0.5} runtimes={oneActive} />);
    // not a group → uses prop progress 0.5 → 50%, no group section
    expect(screen.getByText('50%')).toBeInTheDocument();
    expect(screen.queryByText('eta.group_progress')).not.toBeInTheDocument();
  });
});
