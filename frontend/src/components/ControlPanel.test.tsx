import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('../i18n', () => ({
  useT: () => (key: string) => key,
}))

// Heavy children — stub each to a trivial marker so ControlPanel can mount
// without dragging in maps, address search, export popovers, etc.
vi.mock('./RouteEngineSelector', () => ({ default: () => <div data-testid="route-engine" /> }))
vi.mock('./PauseControl', () => ({ default: () => <div data-testid="pause-control" /> }))
vi.mock('./AddressSearch', () => ({ default: () => <div data-testid="address-search" /> }))
vi.mock('./BookmarkList', () => ({ default: () => <div data-testid="bookmark-list" /> }))
vi.mock('./GoldDittoPanel', () => ({ default: () => <div data-testid="gold-ditto" /> }))
vi.mock('./ExportPopover', () => ({ default: () => <div data-testid="export-popover" /> }))
vi.mock('./RouteList', () => ({ default: () => <div data-testid="route-list" /> }))
vi.mock('./StartPositionPicker', () => ({ default: () => <div data-testid="start-pos" /> }))

import ControlPanel from './ControlPanel'
import { SimMode, MoveMode } from '../hooks/useSimulation'

function makeProps(over: Record<string, any> = {}) {
  return {
    simMode: SimMode.Teleport,
    moveMode: MoveMode.Walking,
    speed: 5,
    isRunning: false,
    isPaused: false,
    currentPosition: null,
    onModeChange: vi.fn(),
    onSpeedChange: vi.fn(),
    onMoveModeChange: vi.fn(),
    customSpeedKmh: null,
    onCustomSpeedChange: vi.fn(),
    speedMinKmh: null,
    onSpeedMinChange: vi.fn(),
    speedMaxKmh: null,
    onSpeedMaxChange: vi.fn(),
    onStart: vi.fn(),
    onStop: vi.fn(),
    onPause: vi.fn(),
    onResume: vi.fn(),
    onRestore: vi.fn(),
    onTeleport: vi.fn(),
    onNavigate: vi.fn(),
    bookmarks: [],
    bookmarkCategories: [],
    onBookmarkClick: vi.fn(),
    deviceConnected: false,
    showWaypointOption: false,
    onBookmarkAdd: vi.fn(),
    onBookmarkDelete: vi.fn(),
    onBookmarkEdit: vi.fn(),
    onCategoryAdd: vi.fn(),
    onCategoryDelete: vi.fn(),
    savedRoutes: [],
    routeCategories: [],
    onRouteLoad: vi.fn(),
    onRouteSave: vi.fn(),
    randomWalkRadius: 100,
    onRandomWalkRadiusChange: vi.fn(),
    ...over,
  }
}

describe('ControlPanel', () => {
  it('renders one mode button per SimMode value', () => {
    render(<ControlPanel {...(makeProps() as any)} />)
    // Mode buttons carry the .mode-btn class; one per SimMode enum value.
    const modeButtons = document.querySelectorAll('button.mode-btn')
    expect(modeButtons.length).toBe(Object.values(SimMode).length)
    // The label keys are passed through by the mocked t().
    expect(screen.getAllByText('mode.teleport').length).toBeGreaterThan(0)
    expect(screen.getAllByText('mode.navigate').length).toBeGreaterThan(0)
  })

  it('marks the active mode button and fires onModeChange on a different mode click', () => {
    const onModeChange = vi.fn()
    render(<ControlPanel {...(makeProps({ simMode: SimMode.Teleport, onModeChange }) as any)} />)

    const buttons = Array.from(document.querySelectorAll('button.mode-btn')) as HTMLButtonElement[]
    // The active mode (Teleport) button has the .active class.
    const active = buttons.filter((b) => b.classList.contains('active'))
    expect(active.length).toBe(1)
    expect(active[0].textContent).toContain('mode.teleport')

    // Click the Navigate button -> onModeChange(SimMode.Navigate).
    const navBtn = buttons.find((b) => b.textContent?.includes('mode.navigate'))!
    fireEvent.click(navBtn)
    expect(onModeChange).toHaveBeenCalledWith(SimMode.Navigate)
  })

  it('collapses the mode section when its title is clicked', () => {
    render(<ControlPanel {...(makeProps() as any)} />)
    // Section starts expanded -> mode buttons present.
    expect(document.querySelectorAll('button.mode-btn').length).toBeGreaterThan(0)
    // Click the "panel.mode" section title to collapse.
    fireEvent.click(screen.getByText('panel.mode'))
    expect(document.querySelectorAll('button.mode-btn').length).toBe(0)
  })
})
