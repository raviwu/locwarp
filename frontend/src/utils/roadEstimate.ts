// Client-side road-distance estimate: straight-line meters × a per-profile
// detour factor. Shown as "≈" while the exact routed value is pending or
// unavailable, so the road badge is never blank and never shows a spinner.
const DETOUR_FACTORS: Record<string, number> = {
  driving: 1.4, car: 1.4,
  walking: 1.3, foot: 1.3, running: 1.3,
  cycling: 1.35, bike: 1.35,
};
const DEFAULT_FACTOR = 1.4;

export function roadEstimateM(straightM: number, profile?: string): number {
  const factor = (profile && DETOUR_FACTORS[profile]) || DEFAULT_FACTOR;
  return straightM * factor;
}
