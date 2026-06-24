import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import { useRef } from 'react';

// MapView.tsx drags in maplibre-gl + leaflet which have side-effects at module
// init time (WebGL / URL.createObjectURL) — not available in jsdom. Stub the
// whole dependency chain so TransportButtons (a pure component) can be tested.
vi.mock('maplibre-gl', () => ({ default: {} }));
vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}));
vi.mock('@maplibre/maplibre-gl-leaflet', () => ({}));
vi.mock('leaflet', () => ({ default: {} }));
vi.mock('../hooks/useMapInstance', () => ({ useMapInstance: () => null }));
vi.mock('../hooks/useBaseLayers', () => ({ useBaseLayers: () => {} }));
vi.mock('../hooks/useRoutePolylineLayer', () => ({ useRoutePolylineLayer: () => {} }));
vi.mock('../hooks/useCurrentPositionLayer', () => ({ useCurrentPositionLayer: () => {} }));
vi.mock('../hooks/useDestinationLayer', () => ({ useDestinationLayer: () => {} }));
vi.mock('../hooks/useRandomWalkCircleLayer', () => ({ useRandomWalkCircleLayer: () => {} }));
vi.mock('../hooks/usePreviewPinLayer', () => ({ usePreviewPinLayer: () => {} }));
vi.mock('../hooks/useWaypointMarkersLayer', () => ({ useWaypointMarkersLayer: () => {} }));
vi.mock('../hooks/useBookmarkMarkersLayer', () => ({ useBookmarkMarkersLayer: () => {} }));
vi.mock('../hooks/useS2Grid', () => ({ useS2Grid: () => {} }));
vi.mock('./LeafletBarButton', () => ({ useLeafletBarButton: () => {} }));
vi.mock('../contexts/ServicesContext', () => ({ useServices: () => ({}) }));
vi.mock('../i18n', () => ({ useT: () => (k: string) => k }));

import { TransportButtons } from './MapView';
import { SimMode } from '../hooks/useSimulation';

function Harness(props: any) {
  const t = useRef((k: string) => k);
  return <TransportButtons t={t} {...props} />;
}

describe('TransportButtons — Teleport-mode Start suppression', () => {
  it('hides the Start button when simMode is Teleport (dead no-op)', () => {
    render(<Harness simMode={SimMode.Teleport} isRunning={false} isPaused={false}
      onStart={vi.fn()} onStop={vi.fn()} onPause={vi.fn()} onResume={vi.fn()} />);
    expect(document.querySelector('.lw-transport-start')).toBeNull();
  });
  it('shows the Start button in a non-Teleport idle mode (e.g. Joystick)', () => {
    render(<Harness simMode={SimMode.Joystick} isRunning={false} isPaused={false}
      onStart={vi.fn()} onStop={vi.fn()} onPause={vi.fn()} onResume={vi.fn()} />);
    expect(document.querySelector('.lw-transport-start')).not.toBeNull();
  });
});
