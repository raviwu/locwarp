import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';

// i18n mock: `t` is a passthrough returning the key (with the count appended
// for the lap-progress call so we can still assert) — lets us key on the
// stable string keys rather than the real string table.
vi.mock('../i18n', () => ({
  useT: () => (k: string) => k,
}));

import WaypointEditor from './WaypointEditor';
import type { WaypointEditorProps } from './WaypointEditor';
import { SimMode, MoveMode } from '../hooks/useSimulation';

const noop = () => {};

function makeProps(overrides: Partial<WaypointEditorProps> = {}): WaypointEditorProps {
  return {
    mode: SimMode.Loop,
    waypoints: [
      { lat: 25.04, lng: 121.53 },
      { lat: 24.14, lng: 120.68 },
      { lat: 22.99, lng: 120.21 },
    ],
    waypointProgress: null,
    statusRunning: false,
    pauseLoop: { enabled: false, min: 1, max: 5 },
    pauseMultiStop: { enabled: false, min: 1, max: 5 },
    setPauseLoop: vi.fn(),
    setPauseMultiStop: vi.fn(),
    loopLapCount: null,
    setLoopLapCount: vi.fn(),
    lapProgress: null,
    wpGenRadius: 300,
    wpGenCount: 5,
    setWpGenRadius: vi.fn(),
    setWpGenCount: vi.fn(),
    moveMode: MoveMode.Walking,
    routeEngine: 'osrm',
    onGenerateRandomWaypoints: vi.fn(),
    onGenerateAllRandom: vi.fn(),
    onMoveWaypoint: vi.fn(),
    onRemoveWaypoint: vi.fn(),
    onClearWaypoints: vi.fn(),
    setWaypoints: vi.fn(),
    onFlyToWaypoint: vi.fn(),
    onOpenBulkPaste: vi.fn(),
    showToast: vi.fn(),
    onOptimize: vi.fn().mockResolvedValue({ waypoints: [], used_estimate: false }),
    ...overrides,
  };
}

describe('WaypointEditor', () => {
  it('renders a row for every waypoint (start marker + numbered stops)', () => {
    render(<WaypointEditor {...makeProps()} />);
    // The start row shows the start label; the other two show the coords.
    expect(screen.getByText('panel.waypoint_start')).toBeInTheDocument();
    expect(screen.getByText('25.04000, 121.53000')).toBeInTheDocument();
    expect(screen.getByText('24.14000, 120.68000')).toBeInTheDocument();
    expect(screen.getByText('22.99000, 120.21000')).toBeInTheDocument();
  });

  it('shows the empty hint when there are no waypoints', () => {
    render(<WaypointEditor {...makeProps({ waypoints: [] })} />);
    expect(screen.getByText('panel.waypoints_empty')).toBeInTheDocument();
  });

  it('fires onGenerateRandomWaypoints when the generate button is clicked', () => {
    const onGenerateRandomWaypoints = vi.fn();
    render(<WaypointEditor {...makeProps({ onGenerateRandomWaypoints })} />);
    fireEvent.click(screen.getByText('panel.waypoints_generate'));
    expect(onGenerateRandomWaypoints).toHaveBeenCalledTimes(1);
  });

  it('fires onGenerateAllRandom when the generate-all button is clicked', () => {
    const onGenerateAllRandom = vi.fn();
    render(<WaypointEditor {...makeProps({ onGenerateAllRandom })} />);
    fireEvent.click(screen.getByText('panel.waypoints_generate_all'));
    expect(onGenerateAllRandom).toHaveBeenCalledTimes(1);
  });

  it('fires onRemoveWaypoint with the row index when its X button is clicked', () => {
    const onRemoveWaypoint = vi.fn();
    render(<WaypointEditor {...makeProps({ onRemoveWaypoint })} />);
    // Each row has a remove button titled panel.waypoints_remove.
    const removeButtons = screen.getAllByTitle('panel.waypoints_remove');
    expect(removeButtons).toHaveLength(3);
    fireEvent.click(removeButtons[1]); // remove the second waypoint (index 1)
    expect(onRemoveWaypoint).toHaveBeenCalledWith(1);
  });

  it('fires onFlyToWaypoint with the clicked coords + index', () => {
    const onFlyToWaypoint = vi.fn();
    render(<WaypointEditor {...makeProps({ onFlyToWaypoint })} />);
    fireEvent.click(screen.getByText('24.14000, 120.68000'));
    expect(onFlyToWaypoint).toHaveBeenCalledWith({ lat: 24.14, lng: 120.68, index: 1 });
  });

  it('fires onOpenBulkPaste from the bulk-paste shimmer button', () => {
    const onOpenBulkPaste = vi.fn();
    render(<WaypointEditor {...makeProps({ onOpenBulkPaste })} />);
    fireEvent.click(screen.getByText('panel.route_paste_button'));
    expect(onOpenBulkPaste).toHaveBeenCalledTimes(1);
  });

  it('routes optimize through onOptimize (never a direct services/api import) and applies the result', async () => {
    const onOptimize = vi.fn().mockResolvedValue({
      waypoints: [{ lat: 1, lng: 2 }, { lat: 3, lng: 4 }],
      used_estimate: false,
    });
    const setWaypoints = vi.fn();
    render(<WaypointEditor {...makeProps({ onOptimize, setWaypoints })} />);
    fireEvent.click(screen.getByText('panel.waypoints_optimize'));
    expect(onOptimize).toHaveBeenCalledWith(
      [
        { lat: 25.04, lng: 121.53 },
        { lat: 24.14, lng: 120.68 },
        { lat: 22.99, lng: 120.21 },
      ],
      MoveMode.Walking,
      true,
      'osrm',
    );
    // Flush the awaited promise so setWaypoints fires.
    await Promise.resolve();
    expect(setWaypoints).toHaveBeenCalledWith([{ lat: 1, lng: 2 }, { lat: 3, lng: 4 }]);
  });

  it('disables the Clear / move / optimize buttons while a run is in progress', () => {
    render(<WaypointEditor {...makeProps({ statusRunning: true })} />);
    const clearBtn = screen.getByText('generic.clear') as HTMLButtonElement;
    expect(clearBtn.disabled).toBe(true);
    const optimizeBtn = screen.getByText('panel.waypoints_optimize') as HTMLButtonElement;
    expect(optimizeBtn.disabled).toBe(true);
    // Move buttons (↑ / ↓) on non-start rows are disabled too.
    const moveDown = screen.getAllByTitle('panel.waypoints_move_down') as HTMLButtonElement[];
    expect(moveDown.every((b) => b.disabled)).toBe(true);
  });

  it('does not disable Clear when no run is in progress', () => {
    render(<WaypointEditor {...makeProps({ statusRunning: false })} />);
    const clearBtn = screen.getByText('generic.clear') as HTMLButtonElement;
    expect(clearBtn.disabled).toBe(false);
  });

  it('hides the optimize button when there are fewer than 3 waypoints', () => {
    render(<WaypointEditor {...makeProps({ waypoints: [{ lat: 1, lng: 1 }, { lat: 2, lng: 2 }] })} />);
    expect(screen.queryByText('panel.waypoints_optimize')).not.toBeInTheDocument();
  });

  it('shows the lap-count input only in Loop mode', () => {
    const { rerender } = render(<WaypointEditor {...makeProps({ mode: SimMode.Loop })} />);
    expect(screen.getByText('loop.lap_count_label')).toBeInTheDocument();
    rerender(<WaypointEditor {...makeProps({ mode: SimMode.MultiStop })} />);
    expect(screen.queryByText('loop.lap_count_label')).not.toBeInTheDocument();
  });

  it('does not render move buttons on the start (index 0) row', () => {
    render(<WaypointEditor {...makeProps()} />);
    // 3 waypoints, start row has no move buttons → 2 down buttons.
    expect(screen.getAllByTitle('panel.waypoints_move_down')).toHaveLength(2);
    // The start row still has a remove (X) button — verify it exists alongside the start label.
    const startSpan = screen.getByText('panel.waypoint_start');
    const startRow = startSpan.parentElement as HTMLElement;
    expect(within(startRow).getByTitle('panel.waypoints_remove')).toBeInTheDocument();
    expect(within(startRow).queryByTitle('panel.waypoints_move_down')).not.toBeInTheDocument();
  });
});
