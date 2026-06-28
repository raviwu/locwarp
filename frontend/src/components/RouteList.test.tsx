import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

import RouteList, { SavedRoute, RouteCategory } from './RouteList'

const categories: RouteCategory[] = [
  { id: 'default', name: '預設', color: '#6c8cff', sort_order: 0 },
]

function makeRoute(over: Partial<SavedRoute> = {}): SavedRoute {
  return {
    id: 'r1',
    name: 'Morning Loop',
    waypoints: [
      { lat: 25.03, lng: 121.56 },
      { lat: 25.04, lng: 121.57 },
    ],
    category_id: 'default',
    ...over,
  }
}

function makeProps(over: Record<string, any> = {}) {
  return {
    routes: [makeRoute()],
    categories,
    currentWaypointsCount: 0,
    onRouteLoad: vi.fn(),
    onRouteSave: vi.fn(),
    onRouteRename: vi.fn(),
    onRouteDelete: vi.fn(),
    ...over,
  }
}

describe('RouteList', () => {
  it('renders a saved-route row with its name and waypoint count', () => {
    render(<RouteList {...(makeProps() as any)} />)
    expect(screen.getByText('Morning Loop')).toBeInTheDocument()
    // The sub-line renders "{count} route.points_unit".
    expect(screen.getByText(/2\s+route\.points_unit/)).toBeInTheDocument()
  })

  it('shows the empty-state message when there are no routes', () => {
    render(<RouteList {...(makeProps({ routes: [] }) as any)} />)
    expect(screen.getByText('panel.route_empty')).toBeInTheDocument()
  })

  it('fires onRouteLoad with the route id when a route row is clicked', () => {
    const onRouteLoad = vi.fn()
    render(<RouteList {...(makeProps({ onRouteLoad }) as any)} />)
    fireEvent.click(screen.getByText('Morning Loop'))
    expect(onRouteLoad).toHaveBeenCalledWith('r1')
  })

  it('groups routes under their category header with the category count', () => {
    const routes = [
      makeRoute({ id: 'r1', name: 'Route One' }),
      makeRoute({ id: 'r2', name: 'Route Two' }),
    ]
    render(<RouteList {...(makeProps({ routes }) as any)} />)
    // Category "預設" maps to bm.default via t() (appears in the header and
    // the save-target dropdown), and both rows are present.
    expect(screen.getAllByText('bm.default').length).toBeGreaterThan(0)
    expect(screen.getByText('Route One')).toBeInTheDocument()
    expect(screen.getByText('Route Two')).toBeInTheDocument()
  })
})

describe('RouteList single-delete confirmation (U13)', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it('does NOT call onRouteDelete when the confirm is dismissed', () => {
    const onRouteDelete = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<RouteList {...(makeProps({ onRouteDelete }) as any)} />);
    // Open the row's right-click context menu, then click Delete.
    fireEvent.contextMenu(screen.getByText('Morning Loop'));
    fireEvent.click(screen.getByText('generic.delete'));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onRouteDelete).not.toHaveBeenCalled();
  });

  it('calls onRouteDelete(id) when the confirm is accepted', () => {
    const onRouteDelete = vi.fn();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<RouteList {...(makeProps({ onRouteDelete }) as any)} />);
    fireEvent.contextMenu(screen.getByText('Morning Loop'));
    fireEvent.click(screen.getByText('generic.delete'));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onRouteDelete).toHaveBeenCalledWith('r1');
  });
})

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

describe('RouteList distance badges', () => {
  function routeWith(over: Partial<SavedRoute>) {
    return makeRoute({
      id: 'r1', name: 'Route 1',
      waypoints: [{ lat: 25, lng: 121 }, { lat: 26, lng: 122 }],
      profile: 'walking', category_id: 'default',
      ...over,
    });
  }

  it('shows the exact 沿路 value when status is ok', () => {
    render(<RouteList {...(makeProps({ routes: [routeWith({
      straight_distance_m: 10000, road_distance_m: 12000, road_distance_status: 'ok',
    })] }) as any)} />);
    expect(screen.getByText(/直線 10\.00 km/)).toBeInTheDocument();
    expect(screen.getByText(/沿路 12\.00 km/)).toBeInTheDocument();
    expect(screen.queryByText(/計算中/)).toBeNull();
    expect(screen.queryByText(/≈/)).toBeNull();
  });

  it('shows a ≈ estimate (never 計算中) while road is pending', () => {
    render(<RouteList {...(makeProps({ routes: [routeWith({
      straight_distance_m: 10000, road_distance_m: null, road_distance_status: 'pending',
    })] }) as any)} />);
    // walking factor 1.3 -> 13.00 km
    expect(screen.getByText(/沿路 ≈ 13\.00 km/)).toBeInTheDocument();
    expect(screen.queryByText(/計算中/)).toBeNull();
  });

  it('shows a ≈ estimate when road is unavailable', () => {
    render(<RouteList {...(makeProps({ routes: [routeWith({
      straight_distance_m: 10000, road_distance_m: null, road_distance_status: 'unavailable',
    })] }) as any)} />);
    expect(screen.getByText(/沿路 ≈ 13\.00 km/)).toBeInTheDocument();
    expect(screen.queryByText(/計算中/)).toBeNull();
  });
});
