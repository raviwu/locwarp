import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// ─────────────────────────────────────────────────────────────────────────────
// PAINT-CONTAINMENT GATE — whole-window flicker regression (2026-08-24).
//
// Symptom: on the packaged macOS build the ENTIRE window flashed near-black
// (#0f1117, the shared blank-surface colour of index.html, .leaflet-container
// and the BrowserWindow backgroundColor) while a route simulation ran, worst on
// a >500m teleport.
//
// Root cause was a compositing chain, not a React re-render:
//   1. `.route-flow-dash` animates `stroke-dashoffset` infinitely; that
//      property is NOT compositor-accelerated, so the route polyline's bbox is
//      CPU-rastered every frame. It exists only while `routePath.length > 1`
//      (useRoutePolylineLayer.ts), i.e. only while a sim runs — which is why an
//      idle app never flickered.
//   2. `.noise-overlay` was `position: fixed; inset: 0; mix-blend-mode: overlay`
//      painting above the map. A non-normal blend mode pulls its whole backdrop
//      — the entire viewport, map included — into ONE render surface, so the
//      map-local repaint from (1) escalated into a whole-window re-composite
//      every frame. THIS was the escalation link.
//   3. A >500m delta takes the non-animated `map.setView()` branch
//      (useCurrentPositionLayer.ts), which falls through Leaflet's animated-pan
//      test into `_resetView` and rebuilds the entire tile grid inside that
//      already-per-frame whole-window surface — hence "worst on teleport".
//
// The fix removes link (2): the noise texture keeps its position and opacity
// but loses `mix-blend-mode`, so it is an ordinary alpha layer with no backdrop
// dependency. Paint containment is a belt on top of that, and it lives on
// `.leaflet-container`, NOT on `.map-container` — see the map-container test
// below for the regression that placement caused.
//
// The blend was deliberately NOT relocated into `.sidebar`: the sidebar runs a
// continuous `chip-pulse` animation on connected-device chips, so a blend group
// there would forbid compositing that animation and reproduce the same defect
// at sidebar scale.
//
// These assertions are structural. jsdom implements neither compositing nor
// containment, so the invariants are pinned at the source level — a green
// suite is NOT evidence about either.
// ─────────────────────────────────────────────────────────────────────────────

const here = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(join(here, 'styles.css'), 'utf8')

/**
 * Return the DECLARATIONS of the first top-level `selector { ... }` rule.
 * Comments are stripped so that prose explaining a banned property (e.g. the
 * note on `.map-container` saying why it must not be paint-contained) cannot
 * satisfy or trip an assertion about the declarations themselves.
 */
function ruleBody(selector: string): string {
  const start = css.indexOf(`\n${selector} {`)
  if (start === -1) throw new Error(`rule not found: ${selector}`)
  const open = css.indexOf('{', start)
  const close = css.indexOf('}', open)
  if (close === -1) throw new Error(`unterminated rule: ${selector}`)
  return css.slice(open + 1, close).replace(/\/\*[\s\S]*?\*\//g, '')
}

/** Every first-party .ts/.tsx source file, tests excluded. */
function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) sourceFiles(full, out)
    else if (/\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$/.test(entry.name)) out.push(full)
  }
  return out
}

describe('paint containment (whole-window flicker gate)', () => {
  it('the noise overlay is not a blend group', () => {
    expect(ruleBody('.noise-overlay')).not.toMatch(/mix-blend-mode/)
  })

  it('no first-party rule reintroduces blending over the map', () => {
    // Any `mix-blend-mode` on an element overlapping the map re-creates the
    // viewport-wide render surface. Comments are stripped first so the prose
    // explaining the ban does not trip the ban.
    //
    // SCOPE: first-party CSS only. Leaflet 1.9.4 ships its own
    // `.leaflet-container img.leaflet-tile { mix-blend-mode: plus-lighter }`
    // (leaflet.css, a workaround for Chromium bug 600120) which this gate
    // cannot see. That one is bounded twice over: LocWarp's own
    // `.leaflet-tile-pane { filter: ... }` (styles.css, a cosmetic tone-down —
    // first-party and ungated, so do not rely on it alone) makes a stacking
    // context, and `contain: paint` on `.leaflet-container` now adds a second
    // isolation boundary. It remains a map-local cost amplifier and is the
    // first suspect if in-map shimmer survives this fix.
    const declarations = css.replace(/\/\*[\s\S]*?\*\//g, '')
    expect(declarations.match(/mix-blend-mode/g) ?? []).toHaveLength(0)
  })

  it('no component sets a blend mode inline, evading the stylesheet gate', () => {
    // Both spellings: the React style-object `mixBlendMode` and the raw
    // property name reachable via `el.style.setProperty('mix-blend-mode', …)`.
    const offenders = sourceFiles(here).filter((f) =>
      /mixBlendMode|mix-blend-mode/.test(readFileSync(f, 'utf8')),
    )
    expect(offenders).toEqual([])
  })

  it('the leaflet control corners stay clear of the EtaBar', () => {
    // `contain: paint` on .leaflet-container traps Leaflet's control corners
    // (leaflet.css z-index 800/1000) in a new stacking context, so they now
    // paint BELOW .map-container siblings like .eta-bar (z-index 900). The
    // 56px nudge is what keeps the zoom buttons visible; without it they are
    // silently covered. Verified on Electron 30 / Chromium 124.
    const hook = readFileSync(join(here, 'hooks', 'useMapInstance.ts'), 'utf8')
    expect(hook).toMatch(/topLeftEl\.style\.marginTop\s*=\s*'56px'/)
    expect(hook).toMatch(/topRightEl\.style\.marginTop\s*=\s*'56px'/)
  })

  it('map repaints are bounded at the leaflet container', () => {
    expect(ruleBody('.leaflet-container')).toMatch(/contain:\s*paint/)
  })

  it('the map container is NOT paint-contained', () => {
    // REGRESSION GUARD. `contain: paint` makes an element the containing block
    // for `position: fixed` descendants and clips them to its box — unlike
    // `overflow: hidden`, which does not clip fixed descendants at all.
    // `.map-container` holds MapContextMenu and WaypointMenu, both
    // `position: fixed` and NOT portaled, both clamping themselves against
    // window.innerWidth/innerHeight. Containing them shifts the menus right by
    // the sidebar width and clips them away near the right edge — measured on
    // Electron 30 / Chromium 124. If containment is ever wanted here, portal
    // those menus to document.body FIRST.
    expect(ruleBody('.map-container')).not.toMatch(/contain:/)
  })
})
