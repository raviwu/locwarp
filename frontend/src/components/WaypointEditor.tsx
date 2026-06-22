import React from 'react';
import { useT } from '../i18n';
import PauseControl from './PauseControl';
import { SimMode } from '../hooks/useSimulation';
import type { MoveMode } from '../hooks/useSimulation';

interface PauseSetting {
  enabled: boolean;
  min: number;
  max: number;
}

interface Waypoint {
  lat: number;
  lng: number;
}

/**
 * Result shape of `api.routeOptimize`. Passed in via `onOptimize` so this
 * component never imports `services/api` directly (hexagon-lite: view reaches
 * the backend only through an injected port).
 */
export interface RouteOptimizeResult {
  waypoints: { lat: number; lng: number }[];
  used_estimate?: boolean;
}

export interface WaypointEditorProps {
  /** Loop or MultiStop — selects PauseControl label/value and lap-count UI. */
  mode: SimMode;
  waypoints: Waypoint[];
  waypointProgress: { current: number; next: number; total: number } | null;
  /** Whether a run is in progress — drives the per-button disabled guards. */
  statusRunning: boolean | undefined;

  // Pause settings (Loop vs MultiStop chosen by the caller's mode wiring).
  pauseLoop: PauseSetting;
  pauseMultiStop: PauseSetting;
  setPauseLoop: (next: PauseSetting) => void;
  setPauseMultiStop: (next: PauseSetting) => void;

  // Loop lap count.
  loopLapCount: number | null;
  setLoopLapCount: (v: number | null) => void;
  lapProgress: { current: number; total: number | null } | null;

  // Random-waypoint generator inputs.
  wpGenRadius: number;
  wpGenCount: number;
  setWpGenRadius: (v: number) => void;
  setWpGenCount: (v: number) => void;

  // Move mode + route engine — forwarded to onOptimize.
  moveMode: MoveMode;
  routeEngine: string;

  // Handlers (defined in App).
  onGenerateRandomWaypoints: () => void;
  onGenerateAllRandom: () => void;
  onMoveWaypoint: (index: number, direction: -1 | 1) => void;
  onRemoveWaypoint: (index: number) => void;
  onClearWaypoints: () => void;
  setWaypoints: (wps: Waypoint[]) => void;
  onFlyToWaypoint: (target: { lat: number; lng: number; index: number }) => void;
  onOpenBulkPaste: () => void;
  showToast: (msg: string) => void;
  /**
   * Injected route-optimize port (App routes `api.routeOptimize` through this)
   * so WaypointEditor stays free of any `services/api` import.
   */
  onOptimize: (
    waypoints: { lat: number; lng: number }[],
    profile: MoveMode,
    keepFirst: boolean,
    engine: string,
  ) => Promise<RouteOptimizeResult>;
}

const WaypointEditor: React.FC<WaypointEditorProps> = ({
  mode,
  waypoints,
  waypointProgress,
  statusRunning,
  pauseLoop,
  pauseMultiStop,
  setPauseLoop,
  setPauseMultiStop,
  loopLapCount,
  setLoopLapCount,
  lapProgress,
  wpGenRadius,
  wpGenCount,
  setWpGenRadius,
  setWpGenCount,
  moveMode,
  routeEngine,
  onGenerateRandomWaypoints,
  onGenerateAllRandom,
  onMoveWaypoint,
  onRemoveWaypoint,
  onClearWaypoints,
  setWaypoints,
  onFlyToWaypoint,
  onOpenBulkPaste,
  showToast,
  onOptimize,
}) => {
  const t = useT();

  return (
          <div className="section" style={{ margin: '0 0 8px 0' }}>
            <div className="section-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="3" />
                <line x1="12" y1="5" x2="12" y2="1" />
                <line x1="12" y1="23" x2="12" y2="19" />
              </svg>
              {t('panel.waypoints')} ({waypoints.length})
              <span style={{ fontSize: 10, opacity: 0.5, marginLeft: 4 }}>{t('panel.waypoints_hint')}</span>
            </div>
            <div className="section-content">
              <PauseControl
                labelKey={mode === SimMode.Loop ? 'pause.loop' : 'pause.multi_stop'}
                value={mode === SimMode.Loop ? pauseLoop : pauseMultiStop}
                onChange={mode === SimMode.Loop ? setPauseLoop : setPauseMultiStop}
              />
              {mode === SimMode.Loop && (
                <div style={{
                  marginBottom: 6, fontSize: 11,
                  display: 'flex', alignItems: 'center', gap: 6,
                }}>
                  <span style={{ opacity: 0.7, whiteSpace: 'nowrap' }}>{t('loop.lap_count_label')}</span>
                  <input
                    type="number"
                    className="lw-input"
                    min={0}
                    placeholder={t('loop.lap_count_placeholder')}
                    value={loopLapCount ?? ''}
                    onChange={(e) => {
                      const raw = e.target.value.trim()
                      if (raw === '') { setLoopLapCount(null); return }
                      const n = parseInt(raw, 10)
                      setLoopLapCount(Number.isFinite(n) && n > 0 ? n : null)
                    }}
                    style={{ width: 70 }}
                    title={t('loop.lap_count_tooltip')}
                  />
                  {lapProgress && (
                    <span style={{ opacity: 0.6, fontSize: 10, marginLeft: 'auto' }}>
                      {t('loop.lap_progress', {
                        current: lapProgress.current,
                        total: lapProgress.total ?? '∞',
                      })}
                    </span>
                  )}
                </div>
              )}
              <div style={{ marginBottom: 6, fontSize: 11 }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ opacity: 0.7, width: 36 }}>{t('panel.waypoints_radius')}</span>
                  <input
                    type="number"
                    className="lw-input"
                    min={10}
                    value={wpGenRadius}
                    onChange={(e) => setWpGenRadius(Math.max(1, parseInt(e.target.value) || 0))}
                    style={{ flex: 1 }}
                  />
                  <span style={{ opacity: 0.5, width: 16 }}>m</span>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6 }}>
                  <span style={{ opacity: 0.7, width: 36 }}>{t('panel.waypoints_count')}</span>
                  <input
                    type="number"
                    className="lw-input"
                    min={1}
                    max={50}
                    value={wpGenCount}
                    onChange={(e) => setWpGenCount(Math.max(1, parseInt(e.target.value) || 0))}
                    style={{ flex: 1 }}
                  />
                  <span style={{ opacity: 0.5, width: 16 }}>{t('panel.points')}</span>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    className="action-btn"
                    style={{ flex: 1, padding: '3px 8px', fontSize: 11 }}
                    onClick={onGenerateRandomWaypoints}
                    title={t('panel.waypoints_gen_tooltip')}
                  >{t('panel.waypoints_generate')}</button>
                  <button
                    className="action-btn"
                    style={{ flex: 1, padding: '3px 8px', fontSize: 11 }}
                    onClick={onGenerateAllRandom}
                    title={t('panel.waypoints_gen_all_tooltip')}
                  >{t('panel.waypoints_generate_all')}</button>
                </div>
                {/* Bulk paste button — Variant D from the mockup: gradient pill
                    with an animated shimmer that hints "this is the eye-catcher". */}
                <button
                  className="route-paste-shimmer"
                  onClick={onOpenBulkPaste}
                  title={t('panel.route_paste_tooltip')}
                  style={{ width: '100%', marginTop: 8 }}
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="9" y="2" width="6" height="4" rx="1"/>
                    <path d="M9 4H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-3"/>
                  </svg>
                  {t('panel.route_paste_button')}
                </button>
              </div>
              {waypoints.length === 0 && (
                <div style={{ fontSize: 12, opacity: 0.5, padding: '4px 0' }}>
                  {t('panel.waypoints_empty')}
                </div>
              )}
              {waypoints.map((wp: any, i: number) => {
                // UI waypoints[0] = the implicit start position (current
                // device location at add-time). Backend seg_idx N = traveling
                // from waypoints[N] toward waypoints[N+1]; the *target* of
                // that segment is waypoints[N+1], so highlight i == seg+1.
                const seg = waypointProgress?.current
                const approaching = seg != null && i === seg + 1
                const passed = seg != null && i <= seg
                const isStart = i === 0;
                return (
                  <div
                    key={i}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6, padding: '3px 6px', fontSize: 12,
                      borderRadius: 4, marginBottom: 2,
                      background: approaching ? 'rgba(255, 152, 0, 0.18)' : 'transparent',
                      border: approaching ? '1px solid rgba(255, 152, 0, 0.6)' : '1px solid transparent',
                      opacity: passed ? 0.4 : 1,
                      transition: 'background 0.25s, border-color 0.25s',
                      animation: approaching ? 'wp-pulse 1.4s ease-in-out infinite' : undefined,
                    }}
                  >
                    <span style={{ color: approaching ? '#ff9800' : passed ? '#666' : isStart ? '#4caf50' : '#ff9800', fontWeight: 600, width: 24, fontSize: isStart ? 10 : undefined }}>
                      {approaching ? '>' : passed ? 'OK' : isStart ? t('panel.waypoint_start') : `#${i}`}
                    </span>
                    <button
                      onClick={() => onFlyToWaypoint({ lat: wp.lat, lng: wp.lng, index: i })}
                      title={t('panel.waypoints_click_to_fly')}
                      style={{
                        flex: 1, background: 'transparent', border: 'none',
                        color: 'inherit', opacity: 0.85, textAlign: 'left',
                        padding: 0, cursor: 'pointer',
                        font: 'inherit', letterSpacing: 0,
                      }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.textDecoration = 'underline'; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.textDecoration = 'none'; }}
                    >{wp.lat.toFixed(5)}, {wp.lng.toFixed(5)}</button>
                    {!isStart && (
                      <>
                        <button
                          className="action-btn"
                          style={{ padding: '2px 5px', fontSize: 10, opacity: i <= 1 ? 0.3 : 1 }}
                          onClick={() => onMoveWaypoint(i, -1)}
                          disabled={i <= 1 || statusRunning}
                          title={t('panel.waypoints_move_up')}
                        >↑</button>
                        <button
                          className="action-btn"
                          style={{ padding: '2px 5px', fontSize: 10, opacity: i >= waypoints.length - 1 ? 0.3 : 1 }}
                          onClick={() => onMoveWaypoint(i, 1)}
                          disabled={i >= waypoints.length - 1 || statusRunning}
                          title={t('panel.waypoints_move_down')}
                        >↓</button>
                      </>
                    )}
                    <button
                      className="action-btn"
                      style={{ padding: '2px 6px', fontSize: 10 }}
                      onClick={() => onRemoveWaypoint(i)}
                      title={t('panel.waypoints_remove')}
                    >X</button>
                  </div>
                );
              })}
              {waypoints.length > 0 && (
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  <button
                    className="action-btn"
                    style={{ flex: 1 }}
                    onClick={onClearWaypoints}
                    disabled={statusRunning}
                  >{t('generic.clear')}</button>
                  {waypoints.length >= 3 && (
                    <button
                      className="action-btn"
                      style={{ flex: 1 }}
                      onClick={async () => {
                        try {
                          const res = await onOptimize(
                            waypoints.map((w: any) => ({ lat: w.lat, lng: w.lng })),
                            moveMode, true, routeEngine,
                          )
                          if (res?.waypoints?.length) {
                            setWaypoints(res.waypoints)
                            const baseMsg = t('toast.route_optimized')
                            // When the duration matrix fell back to
                            // haversine (all road-aware engines down),
                            // tag the toast so the user knows the order
                            // is from a straight-line estimate.
                            showToast(res.used_estimate
                              ? `${baseMsg} (${t('toast.route_optimize_estimate')})`
                              : baseMsg)
                          }
                        } catch (err: any) {
                          showToast(err?.message || t('toast.route_optimize_failed'))
                        }
                      }}
                      disabled={statusRunning}
                      title={t('panel.waypoints_optimize_tooltip')}
                    >{t('panel.waypoints_optimize')}</button>
                  )}
                </div>
              )}
            </div>
          </div>
  );
};

export default WaypointEditor;
