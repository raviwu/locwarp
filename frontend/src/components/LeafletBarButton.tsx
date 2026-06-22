import { useEffect, useRef } from 'react'
import L from 'leaflet'

// ─────────────────────────────────────────────────────────────────────────────
// useLeafletBarButton — the shared shape behind MapView's 4 near-identical
// custom leaflet-bar buttons (recenter → follow → library → S2-grid), carved
// out into ONE reusable raw-DOM primitive (Phase 4b, task p4b2a).
//
// These buttons are NOT React-rendered: they're built with `L.DomUtil.create`
// + `innerHTML` SVG + `L.DomEvent`, appended to Leaflet's top-left control
// corner so Leaflet's own `.leaflet-top .leaflet-left` layout pins them to the
// same x as the zoom +/- bar with the standard 10px gap. A hook (not a JSX
// component) is therefore the right primitive — it owns the two effects every
// call site already hand-rolled:
//
//   1. wire-once  — build the button ONCE per mount (deps: []), append it to
//      the control corner in call-site order, and route its click through a
//      `handlerRef` mirror so the once-bound listener always reads the FRESH
//      `onClick` (prop/state changes mid-session never rebuild the button).
//   2. React→DOM active-sync — on every relevant render, update the
//      `handlerRef`, repaint the active background, refresh the title, toggle
//      `aria-pressed`, and reflect the disabled state. This is the effect that
//      keeps follow / S2 `aria-pressed` (+ recenter's disabled) in lock-step
//      with React state WITHOUT re-creating the DOM node.
//
// Behavior is FROZEN: the e2e net (mapview-controls.spec.ts) asserts the exact
// title attrs (recenter / follow), the custom classNames (`.locwarp-library-btn`,
// `.locwarp-s2-btn`), the `aria-pressed` toggles (follow / S2), the stack order
// (recenter → follow → library → S2), and the 5-`.leaflet-bar` count.
// ─────────────────────────────────────────────────────────────────────────────

export interface LeafletBarButtonOptions {
  /** The live map ref owned by useMapInstance. The button mounts once it exists. */
  mapRef: React.RefObject<L.Map | null>
  /** Inner SVG markup painted into the button via innerHTML. */
  iconHtml: string
  /** Tooltip / accessible title. Read fresh on every active-sync render. */
  title: string
  /** Optional custom className on the <button> (e.g. `locwarp-library-btn`). */
  className?: string
  /**
   * Optional foreground colour for the icon. Defaults to '#fff'. Library uses
   * gold (#ffd95b) for its star; the rest stay white.
   */
  color?: string
  /**
   * Paints the active (blue) background when true, neutral surface when false.
   * Drives BOTH the toggle buttons (follow / S2 on) and recenter's
   * blue-when-enabled look. Purely visual — does NOT touch `aria-pressed`
   * (see `ariaPressed` below), so recenter stays free of the attribute.
   */
  active?: boolean
  /**
   * The `aria-pressed` toggle attribute. Provided ONLY by the real toggles
   * (follow / S2) so recenter never grows an unexpected attribute. Kept
   * separate from `active` because recenter is blue-when-enabled but is not a
   * pressed-state toggle.
   */
  ariaPressed?: boolean
  /**
   * Disabled state. When true the button is `disabled`, dimmed, and shows a
   * not-allowed cursor. Recenter uses this (no current position → disabled).
   */
  disabled?: boolean
  /** Click handler. Routed through a ref so the once-bound listener stays fresh. */
  onClick: () => void
  /** Optional right-click / long-press handler (S2 opens its level picker). */
  onContextMenu?: () => void
}

// The active (toggled-on / enabled-recenter) blue, and the neutral surface
// fallback — lifted VERBATIM from the 4 inline builders so the visual is
// byte-identical to before.
const ACTIVE_BG = '#6c8cff'
const SURFACE_BG = 'var(--bg-surface, #2a2f3a)'

/**
 * Builds ONE custom leaflet-bar button and keeps it in sync with React state.
 *
 * Must be called unconditionally (Rules of Hooks). To preserve the documented
 * stack order, call the hook for each button in the desired order — the
 * wire-once effects run in call order, appending each wrapper to the control
 * corner in turn (recenter → follow → library → S2).
 */
export function useLeafletBarButton(opts: LeafletBarButtonOptions): void {
  const { mapRef, iconHtml, title, className, color, active, ariaPressed, disabled, onClick, onContextMenu } = opts

  // The DOM button node — set once the wire-once effect runs.
  const btnRef = useRef<HTMLButtonElement | null>(null)
  // Handler mirrors so the once-bound L.DomEvent listeners always read the
  // freshest callback without re-creating the button.
  const onClickRef = useRef(onClick)
  const onContextMenuRef = useRef(onContextMenu)

  // ── wire-once: build the button + append to the top-left control corner ──
  // Runs once per mount AFTER useMapInstance has created the map + nudged the
  // control corners. Deps [] so the node is never rebuilt; click/contextmenu
  // route through the refs above for freshness.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const topLeftEl = (map as any)._controlCorners?.topleft as HTMLElement | undefined
    if (!topLeftEl) return

    const wrapper = L.DomUtil.create('div', 'leaflet-bar leaflet-control')
    const btn = L.DomUtil.create('button', className ?? '', wrapper) as HTMLButtonElement
    btn.type = 'button'
    btn.setAttribute('role', 'button')
    btn.style.cssText = [
      'width: 30px', 'height: 30px', 'display: flex',
      'align-items: center', 'justify-content: center',
      'padding: 0', 'margin: 0', 'cursor: pointer',
      `background: ${SURFACE_BG}`,
      `color: ${color ?? '#fff'}`, 'border: none', 'border-radius: 0',
    ].join(';')
    // Seed the toggle attribute at build time (matches the original builders,
    // which set aria-pressed="false" before the sync effect first runs).
    if (ariaPressed !== undefined) {
      btn.setAttribute('aria-pressed', ariaPressed ? 'true' : 'false')
    }
    btn.innerHTML = iconHtml
    L.DomEvent.disableClickPropagation(wrapper)
    L.DomEvent.on(btn, 'click', (e: Event) => {
      e.preventDefault()
      if (btn.disabled) return
      onClickRef.current()
    })
    if (onContextMenu) {
      L.DomEvent.on(btn, 'contextmenu', (e: Event) => {
        e.preventDefault()
        onContextMenuRef.current?.()
      })
    }
    topLeftEl.appendChild(wrapper)
    btnRef.current = btn
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── React→DOM active-sync: keep handler + visual state in lock-step ──────
  // Repaints background, title, aria-pressed, and disabled WITHOUT rebuilding
  // the node. Mirrors the per-button sync effects MapView used to hand-roll.
  useEffect(() => {
    onClickRef.current = onClick
    onContextMenuRef.current = onContextMenu
    const btn = btnRef.current
    if (!btn) return

    // Disabled wins (recenter): dim + not-allowed, neutral surface.
    if (disabled) {
      btn.disabled = true
      btn.style.background = SURFACE_BG
      btn.style.cursor = 'not-allowed'
      btn.style.opacity = '0.55'
    } else {
      btn.disabled = false
      btn.style.background = active ? ACTIVE_BG : SURFACE_BG
      btn.style.cursor = 'pointer'
      btn.style.opacity = '1'
    }

    btn.title = title
    if (ariaPressed !== undefined) {
      btn.setAttribute('aria-pressed', ariaPressed ? 'true' : 'false')
    }
  }, [onClick, onContextMenu, title, active, ariaPressed, disabled])
}
