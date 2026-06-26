/**
 * App.profiler.bench.test.tsx
 *
 * React 18 <Profiler> harness — measures per-tick commit cost and per-component
 * wasted-render counts for the App tree during position_update ticks.
 *
 * Two scenarios:
 *   MOVING — 100 ticks, lat/lng advance by 0.0001° per tick (realistic GPS drift)
 *   STATIC  — 100 ticks, same lat/lng every time (memoization should block commits)
 *
 * NOTE: jsdom measures React reconcile/commit time, NOT real browser layout/paint.
 * Numbers are useful for relative comparisons and catching memoization regressions,
 * but do NOT predict real FPS. A Playwright CPU-profile step is needed for
 * paint-inclusive measurements.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React, { Profiler } from 'react'
import { render, act } from '@testing-library/react'

// ── Render counters — mutated from inside stub render bodies ──────────────────
// These track commit count per component (same pattern as renderCount.test.tsx).
const renderCounts = {
  control: 0,
  map: 0,
  etaBar: 0,
  statusBar: 0,
  deviceStatus: 0,
  deviceChipRow: 0,
}

// ── Stubs (mirror renderCount.test.tsx exactly) ───────────────────────────────
// MapView pulls Leaflet/MapLibre (WebGL — not in jsdom). Stub to render-nothing
// + commit counter, wrapped in React.memo to mirror the real component's memo.
vi.mock('./components/MapView', () => {
  const MapViewStub = React.memo(
    React.forwardRef(function MapViewStub(_props: any, _ref: any) {
      renderCounts.map++
      return null
    }),
  )
  ;(MapViewStub as any).displayName = 'MapViewStub'
  return { default: MapViewStub }
})

// ControlPanel is heavy. Stub to memo'd counter.
vi.mock('./components/ControlPanel', () => {
  const ControlPanelStub = React.memo(function ControlPanelStub(_props: any) {
    renderCounts.control++
    return null
  })
  ;(ControlPanelStub as any).displayName = 'ControlPanelStub'
  return { default: ControlPanelStub }
})

// EtaBar — NOT memoized in production — measure as-is to detect wasted commits.
vi.mock('./components/EtaBar', () => {
  const EtaBarStub = function EtaBarStub(_props: any) {
    renderCounts.etaBar++
    return null
  }
  EtaBarStub.displayName = 'EtaBarStub'
  return { default: EtaBarStub }
})

// StatusBar — NOT memoized in production.
vi.mock('./components/StatusBar', () => {
  const StatusBarStub = function StatusBarStub(_props: any) {
    renderCounts.statusBar++
    return null
  }
  StatusBarStub.displayName = 'StatusBarStub'
  return { default: StatusBarStub }
})

// DeviceStatus — NOT memoized in production.
vi.mock('./components/DeviceStatus', () => {
  const DeviceStatusStub = function DeviceStatusStub(_props: any) {
    renderCounts.deviceStatus++
    return null
  }
  DeviceStatusStub.displayName = 'DeviceStatusStub'
  return { default: DeviceStatusStub }
})

// DeviceChipRow — check if memoized or not.
vi.mock('./components/DeviceChipRow', () => {
  const DeviceChipRowStub = function DeviceChipRowStub(_props: any) {
    renderCounts.deviceChipRow++
    return null
  }
  DeviceChipRowStub.displayName = 'DeviceChipRowStub'
  return {
    default: DeviceChipRowStub,
    DeviceChipRow: DeviceChipRowStub,
    MAX_DEVICES: 2,
  }
})

// Same inert services/api mock as renderCount.test.tsx.
vi.mock('./services/api', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const arrayReturning = new Set([
    'getSavedRoutes', 'getRecent', 'listRouteCategories', 'listBookmarks',
    'listCategories', 'listDevices', 'getBookmarks', 'getCategories',
  ])
  const nullReturning = new Set(['getCatalog'])
  const urlReturning = new Set(['bookmarksExportUrl', 'exportGpxUrl', 'routesExportUrl'])
  const out: Record<string, unknown> = {}
  for (const key of Object.keys(actual)) {
    if (typeof actual[key] !== 'function') { out[key] = actual[key]; continue }
    if (key === 'cloudSyncStatus') {
      out[key] = async () => ({ enabled: false, prompt_dismissed: true, detected_icloud_path: null })
    } else if (key === 'getCooldownStatus' || key === 'getStatus') {
      out[key] = async () => ({})
    } else if (arrayReturning.has(key)) { out[key] = async () => [] }
    else if (nullReturning.has(key)) { out[key] = async () => null }
    else if (urlReturning.has(key)) { out[key] = () => '' }
    else { out[key] = async () => undefined }
  }
  return out
})

import App from './App'
import { I18nProvider } from './i18n'
import { ServicesProvider } from './contexts/ServicesContext'
import { createWsRouter, type WsRouterImpl } from './adapters/ws/router'
import * as api from './services/api'

// ── Profiler record type (mirrors React.ProfilerProps onRender signature) ─────
interface CommitRecord {
  id: string
  phase: 'mount' | 'update' | 'nested-update'
  actualDuration: number
  baseDuration: number
  startTime: number
  commitTime: number
}

// ── renderApp: wraps App in a top-level <Profiler> for whole-tree measurement ─
function renderApp(
  router: WsRouterImpl,
  onRender: (rec: CommitRecord) => void,
  connected = true,
) {
  const handleRender = (
    id: string,
    phase: 'mount' | 'update' | 'nested-update',
    actualDuration: number,
    baseDuration: number,
    startTime: number,
    commitTime: number,
  ) => {
    onRender({ id, phase, actualDuration, baseDuration, startTime, commitTime })
  }

  return render(
    <I18nProvider>
      <ServicesProvider value={{ api, ws: router, sendMessage: vi.fn(), connected }}>
        <Profiler id="app" onRender={handleRender}>
          <App />
        </Profiler>
      </ServicesProvider>
    </I18nProvider>,
  )
}

// ── stat helpers ───────────────────────────────────────────────────────────────
function median(vals: number[]): number {
  if (vals.length === 0) return 0
  const sorted = [...vals].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid]
}

function p95(vals: number[]): number {
  if (vals.length === 0) return 0
  const sorted = [...vals].sort((a, b) => a - b)
  const idx = Math.ceil(sorted.length * 0.95) - 1
  return sorted[Math.max(0, idx)]
}

// ── Reset between tests ───────────────────────────────────────────────────────
function resetCounts() {
  renderCounts.control = 0
  renderCounts.map = 0
  renderCounts.etaBar = 0
  renderCounts.statusBar = 0
  renderCounts.deviceStatus = 0
  renderCounts.deviceChipRow = 0
}

beforeEach(() => {
  resetCounts()
  try { localStorage.setItem('locwarp.lang', 'en') } catch { /* ignore */ }
})
afterEach(() => { try { localStorage.clear() } catch { /* ignore */ } })

// ── Main test ─────────────────────────────────────────────────────────────────
describe('App per-tick Profiler bench (position_update commit cost)', () => {
  it('measures moving + static commit durations and per-component wasted renders', async () => {
    const N = 100

    // ── MOVING SCENARIO ──────────────────────────────────────────────────────
    // lat/lng advance by 0.0001° per tick (~11 m) — coordinates genuinely change
    // so map marker + ETA + position-dependent UI legitimately update.
    const movingCommits: CommitRecord[] = []
    const routerMoving = createWsRouter()
    const { unmount: unmountMoving } = renderApp(routerMoving, (rec) => movingCommits.push(rec))

    // Warm-up: mount + effects settle (discard mount commits)
    await act(async () => {})
    movingCommits.length = 0
    resetCounts()

    // Fire the first frame (null → position) — records initial position commit
    const BASE_LAT = 25.0330
    const BASE_LNG = 121.5654
    await act(async () => {
      routerMoving.dispatch({
        type: 'position_update',
        lat: BASE_LAT,
        lng: BASE_LNG,
        progress: 0,
        distance_remaining: 1000,
        distance_traveled: 0,
      })
    })
    movingCommits.length = 0
    resetCounts()

    // Capture steady-state MOVING ticks
    const movingRenderCountsPerComponent = {
      control: 0, map: 0, etaBar: 0, statusBar: 0, deviceStatus: 0, deviceChipRow: 0,
    }
    for (let i = 1; i <= N; i++) {
      const tickCounts = { ...renderCounts }
      await act(async () => {
        routerMoving.dispatch({
          type: 'position_update',
          lat: BASE_LAT + i * 0.0001,
          lng: BASE_LNG + i * 0.0001,
          progress: i / N,
          distance_remaining: 1000 - i * 10,
          distance_traveled: i * 10,
        })
      })
      movingRenderCountsPerComponent.control += renderCounts.control - tickCounts.control
      movingRenderCountsPerComponent.map += renderCounts.map - tickCounts.map
      movingRenderCountsPerComponent.etaBar += renderCounts.etaBar - tickCounts.etaBar
      movingRenderCountsPerComponent.statusBar += renderCounts.statusBar - tickCounts.statusBar
      movingRenderCountsPerComponent.deviceStatus += renderCounts.deviceStatus - tickCounts.deviceStatus
      movingRenderCountsPerComponent.deviceChipRow += renderCounts.deviceChipRow - tickCounts.deviceChipRow
    }

    // Filter to UPDATE commits only (skip stray nested-update artifacts from effects)
    const movingUpdateCommits = movingCommits.filter((r) => r.phase === 'update' || r.phase === 'nested-update')
    const movingDurations = movingUpdateCommits.map((r) => r.actualDuration)

    unmountMoving()

    // ── STATIC SCENARIO ───────────────────────────────────────────────────────
    // Same coords every tick. Memoization (N1 fix) should block ControlPanel +
    // MapView commits; unmemoized components (EtaBar, StatusBar, DeviceStatus)
    // will still commit because App re-renders and passes new prop objects.
    const staticCommits: CommitRecord[] = []
    resetCounts()
    const routerStatic = createWsRouter()
    const { unmount: unmountStatic } = renderApp(routerStatic, (rec) => staticCommits.push(rec))

    await act(async () => {})
    staticCommits.length = 0
    resetCounts()

    // First frame to establish position
    await act(async () => {
      routerStatic.dispatch({
        type: 'position_update',
        lat: BASE_LAT,
        lng: BASE_LNG,
        progress: 0,
        distance_remaining: 1000,
        distance_traveled: 0,
      })
    })
    staticCommits.length = 0
    resetCounts()

    // Steady-state STATIC ticks
    const staticRenderCountsPerComponent = {
      control: 0, map: 0, etaBar: 0, statusBar: 0, deviceStatus: 0, deviceChipRow: 0,
    }
    for (let i = 1; i <= N; i++) {
      const tickCounts = { ...renderCounts }
      await act(async () => {
        routerStatic.dispatch({
          type: 'position_update',
          lat: BASE_LAT,
          lng: BASE_LNG,
          progress: 0,
          distance_remaining: 1000,
          distance_traveled: 0,
        })
      })
      staticRenderCountsPerComponent.control += renderCounts.control - tickCounts.control
      staticRenderCountsPerComponent.map += renderCounts.map - tickCounts.map
      staticRenderCountsPerComponent.etaBar += renderCounts.etaBar - tickCounts.etaBar
      staticRenderCountsPerComponent.statusBar += renderCounts.statusBar - tickCounts.statusBar
      staticRenderCountsPerComponent.deviceStatus += renderCounts.deviceStatus - tickCounts.deviceStatus
      staticRenderCountsPerComponent.deviceChipRow += renderCounts.deviceChipRow - tickCounts.deviceChipRow
    }

    const staticUpdateCommits = staticCommits.filter((r) => r.phase === 'update' || r.phase === 'nested-update')
    const staticDurations = staticUpdateCommits.map((r) => r.actualDuration)

    unmountStatic()

    // ── Compute stats ────────────────────────────────────────────────────────
    const movingMedian = median(movingDurations)
    const movingP95 = p95(movingDurations)
    const movingCommitsPerTick = movingUpdateCommits.length / N

    const staticMedian = median(staticDurations)
    const staticP95 = p95(staticDurations)
    const staticCommitsPerTick = staticUpdateCommits.length / N

    // ── Wasted-render analysis ────────────────────────────────────────────────
    // A component is "wasted" if it commits on a static-coord tick (same position,
    // memoization should suppress it). We flag components committing > N*0.1 times
    // on static ticks as wasted (>10% of ticks = real problem, not noise).
    const wastedThreshold = N * 0.1
    const wastedComponents: string[] = []
    for (const [name, count] of Object.entries(staticRenderCountsPerComponent)) {
      if (count > wastedThreshold) wastedComponents.push(`${name}:${count}`)
    }

    // ── Print report ─────────────────────────────────────────────────────────
    console.log('\n=== App per-tick Profiler bench results ===')
    console.log(`\n[MOVING — ${N} ticks, lat/lng+0.0001° each tick]`)
    console.log(`  Profiler commits recorded : ${movingUpdateCommits.length}`)
    console.log(`  Commits per tick          : ${movingCommitsPerTick.toFixed(2)}`)
    console.log(`  actualDuration median     : ${movingMedian.toFixed(3)} ms`)
    console.log(`  actualDuration p95        : ${movingP95.toFixed(3)} ms`)
    console.log(`  Component commit counts   :`)
    console.log(`    ControlPanel  : ${movingRenderCountsPerComponent.control}`)
    console.log(`    MapView       : ${movingRenderCountsPerComponent.map}`)
    console.log(`    EtaBar        : ${movingRenderCountsPerComponent.etaBar}`)
    console.log(`    StatusBar     : ${movingRenderCountsPerComponent.statusBar}`)
    console.log(`    DeviceStatus  : ${movingRenderCountsPerComponent.deviceStatus}`)
    console.log(`    DeviceChipRow : ${movingRenderCountsPerComponent.deviceChipRow}`)

    console.log(`\n[STATIC — ${N} ticks, same lat/lng every tick]`)
    console.log(`  Profiler commits recorded : ${staticUpdateCommits.length}`)
    console.log(`  Commits per tick          : ${staticCommitsPerTick.toFixed(2)}`)
    console.log(`  actualDuration median     : ${staticMedian.toFixed(3)} ms`)
    console.log(`  actualDuration p95        : ${staticP95.toFixed(3)} ms`)
    console.log(`  Component commit counts   :`)
    console.log(`    ControlPanel  : ${staticRenderCountsPerComponent.control}   (memo'd — expect 0)`)
    console.log(`    MapView       : ${staticRenderCountsPerComponent.map}   (memo'd — expect 0)`)
    console.log(`    EtaBar        : ${staticRenderCountsPerComponent.etaBar}   (NOT memo'd — will commit)`)
    console.log(`    StatusBar     : ${staticRenderCountsPerComponent.statusBar}   (NOT memo'd — will commit)`)
    console.log(`    DeviceStatus  : ${staticRenderCountsPerComponent.deviceStatus}   (NOT memo'd — will commit)`)
    console.log(`    DeviceChipRow : ${staticRenderCountsPerComponent.deviceChipRow}   (check)`)

    console.log(`\n[WASTED RENDER SUMMARY]`)
    if (wastedComponents.length === 0) {
      console.log('  No unexpected wasted renders detected.')
    } else {
      console.log(`  Components committing >10% of static ticks (wasted): ${wastedComponents.join(', ')}`)
    }
    console.log(`\n[NOTE] jsdom timing: React reconcile cost only. Browser paint/layout NOT measured.`)
    console.log('=== end bench ===\n')

    // ── Assertions (loose sanity bounds — not performance gates) ─────────────
    // The median actualDuration per tick must be under 200 ms (jsdom, no paint).
    // This is a canary for catastrophic regressions, not a real-time budget.
    expect(movingMedian).toBeLessThan(200)
    expect(staticMedian).toBeLessThan(200)

    // Memoized components (ControlPanel + MapView) must NOT commit on static ticks.
    // This is the key correctness guarantee (N1 memoization guard).
    expect(staticRenderCountsPerComponent.control).toBe(0)
    expect(staticRenderCountsPerComponent.map).toBe(0)

    // At least some profiler update commits must be recorded for MOVING ticks
    // (sanity: proves the Profiler is wired correctly).
    expect(movingUpdateCommits.length).toBeGreaterThan(0)
  }, 60_000) // allow up to 60s for 200 ticks + renders
})
