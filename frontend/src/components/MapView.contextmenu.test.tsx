import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, act } from '@testing-library/react';

// MapView drags in maplibre-gl + leaflet, which touch WebGL / createObjectURL
// at module-init time and are unavailable in jsdom. Stub the same dependency
// chain MapView.test.tsx stubs, so the component itself can be mounted.
vi.mock('maplibre-gl', () => ({ default: {} }));
vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}));
vi.mock('@maplibre/maplibre-gl-leaflet', () => ({}));
vi.mock('leaflet', () => ({ default: {} }));
vi.mock('../hooks/useBaseLayers', () => ({ useBaseLayers: () => {} }));
vi.mock('../hooks/useRoutePolylineLayer', () => ({ useRoutePolylineLayer: () => {} }));
vi.mock('../hooks/useCurrentPositionLayer', () => ({ useCurrentPositionLayer: () => {} }));
vi.mock('../hooks/useDestinationLayer', () => ({ useDestinationLayer: () => {} }));
vi.mock('../hooks/useRandomWalkCircleLayer', () => ({ useRandomWalkCircleLayer: () => {} }));
vi.mock('../hooks/usePreviewPinLayer', () => ({ usePreviewPinLayer: () => {} }));
vi.mock('../hooks/useWaypointMarkersLayer', () => ({ useWaypointMarkersLayer: () => {} }));
vi.mock('../hooks/useBookmarkMarkersLayer', () => ({ useBookmarkMarkersLayer: () => {} }));
vi.mock('../hooks/useS2Grid', () => ({
  useS2Grid: () => ({
    s2Enabled: false,
    setS2Enabled: () => {},
    s2Level: 17,
    setS2Level: () => {},
    s2Suppressed: false,
  }),
}));
vi.mock('./LeafletBarButton', () => ({ useLeafletBarButton: () => {} }));
vi.mock('../contexts/ServicesContext', () => ({
  useServices: () => ({
    api: {
      getInitialPosition: () => Promise.resolve({ position: null }),
      reverseGeocode: () => Promise.resolve(null),
      nearbyPois: () => Promise.resolve([]),
    },
  }),
}));
vi.mock('../i18n', () => ({ useT: () => (k: string) => k }));
// Owns a ResizeObserver over `.status-bar`, which jsdom does not provide.
vi.mock('./CoordInputStrip', () => ({ CoordInputStrip: () => null }));

// Capture the options MapView hands the map hook, so the real onContextMenu
// callback can be invoked with a synthetic right-click.
let capturedOpts: any = null;
vi.mock('../hooks/useMapInstance', () => ({
  useMapInstance: (_container: any, opts: any) => {
    capturedOpts = opts;
    return { mapRef: { current: fakeMap } };
  },
}));

// Capture what the context menu is opened with.
let ctxProps: any = null;
vi.mock('./MapContextMenu', () => ({
  default: (p: any) => { ctxProps = p; return null; },
}));

// Minimal Leaflet map stand-in. The projection is the part under test's
// CONTRACT, not its implementation: a right-click at clientX/Y must be
// measured against where the current position is painted.
const POSITION_PIXEL = { x: 508, y: 297 };
const fakeMap = {
  // The three calls the snap actually depends on.
  mouseEventToContainerPoint: (e: MouseEvent) => ({ x: e.clientX, y: e.clientY }),
  latLngToContainerPoint: () => POSITION_PIXEL,
  getZoom: () => 8,
  // Incidental calls made elsewhere in MapView's render path.
  getCenter: () => ({ lat: 47.32825, lng: 11.845251 }),
  getBounds: () => ({
    getSouthWest: () => ({ lat: 46, lng: 10 }),
    getNorthEast: () => ({ lat: 48, lng: 13 }),
    getCenter: () => ({ lat: 47, lng: 11.5 }),
  }),
  setView: () => {},
  panTo: () => {},
  invalidateSize: () => {},
  on: () => {},
  off: () => {},
};

import MapView from './MapView';

// The 2026-09-17 pankrazberg numbers: Leaflet handed back a zoom-8 pixel 3.6 km
// from where the device actually was.
const CLICK_LAT = 47.3388227;
const CLICK_LNG = 11.7993164;
const DEVICE = { lat: 47.32825, lng: 11.845251 };

function renderMap(over: Record<string, any> = {}) {
  const props: any = {
    currentPosition: DEVICE,
    destination: null,
    waypoints: [],
    routePath: [],
    randomWalkRadius: null,
    onMapClick: vi.fn(),
    onTeleport: vi.fn(),
    onNavigate: vi.fn(),
    onAddBookmark: vi.fn(),
    bookmarks: [],
    ...over,
  };
  render(<MapView {...props} />);
  return props;
}

function rightClickAt(x: number, y: number) {
  act(() => {
    capturedOpts.onContextMenu(CLICK_LAT, CLICK_LNG, { clientX: x, clientY: y } as MouseEvent);
  });
}

describe('MapView right-click coordinate', () => {
  beforeEach(() => {
    capturedOpts = null;
    ctxProps = null;
  });

  it('snaps a click inside the position marker to the device coordinate', () => {
    renderMap();
    rightClickAt(500, 300); // 8.5px from POSITION_PIXEL — inside the 22px avatar

    expect(ctxProps.lat).toBe(DEVICE.lat);
    expect(ctxProps.lng).toBe(DEVICE.lng);
  });

  it('keeps a deliberate far click as-is', () => {
    renderMap();
    rightClickAt(700, 300); // ~192px away

    expect(ctxProps.lat).toBe(CLICK_LAT);
    expect(ctxProps.lng).toBe(CLICK_LNG);
  });

  it('falls back to the raw click when there is no device position', () => {
    renderMap({ currentPosition: null });
    rightClickAt(500, 300);

    expect(ctxProps.lat).toBe(CLICK_LAT);
    expect(ctxProps.lng).toBe(CLICK_LNG);
  });

  it('forwards the snap flag and the zoom precision to the add-bookmark handler', () => {
    const props = renderMap();
    rightClickAt(500, 300);

    act(() => { ctxProps.onAddBookmark(ctxProps.lat, ctxProps.lng, 'some name'); });

    expect(props.onAddBookmark).toHaveBeenCalledWith(
      DEVICE.lat,
      DEVICE.lng,
      'some name',
      { snapped: true, metersPerPixel: expect.any(Number) },
    );
    // zoom 8 at 47N is ~417 m per pixel — comfortably over the hint threshold.
    const meta = props.onAddBookmark.mock.calls[0][3];
    expect(meta.metersPerPixel).toBeGreaterThan(400);
    expect(meta.metersPerPixel).toBeLessThan(430);
  });

  it('reports snapped=false for a far click so the precision hint can show', () => {
    const props = renderMap();
    rightClickAt(700, 300);

    act(() => { ctxProps.onAddBookmark(ctxProps.lat, ctxProps.lng, undefined); });

    expect(props.onAddBookmark).toHaveBeenCalledWith(
      CLICK_LAT, CLICK_LNG, undefined,
      { snapped: false, metersPerPixel: expect.any(Number) },
    );
  });
});
