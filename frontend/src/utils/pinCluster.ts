/**
 * Bookmark-pin clustering — the pure screen-pixel grouping math lifted out
 * of MapView's bookmark-pins rebuild effect.
 *
 * Pure: takes a `project(latlng) -> {x, y}` callback (the caller passes
 * Leaflet's `map.latLngToLayerPoint`) so this module has NO Leaflet / DOM
 * dependency. Returns the cluster groups; the caller decides single-pin vs
 * cluster rendering from `members.length`.
 */

export interface PixelPoint {
  x: number;
  y: number;
}

/** Minimal shape the clusterer needs from each item: a lat/lng to project. */
export interface LatLngItem {
  lat: number;
  lng: number;
}

export interface PinCluster<T extends LatLngItem> {
  /** Running-average screen-x of the cluster's members (px). */
  x: number;
  /** Running-average screen-y of the cluster's members (px). */
  y: number;
  members: T[];
}

/**
 * Greedily group items whose projected screen points fall within
 * `thresholdPx` of an existing cluster's running-average centre. First
 * item seeds a cluster; each subsequent item joins the first cluster it is
 * within-threshold of (squared-distance compare, boundary inclusive:
 * d <= threshold clusters), else seeds a new one. The cluster centre is
 * updated as a running average on each join — same cheap approximation the
 * original effect used.
 *
 * Matches the original loop exactly, including the `<=` boundary and the
 * single-pass "first match wins" behaviour.
 */
export function clusterByPixelDistance<T extends LatLngItem>(
  items: readonly T[],
  project: (item: LatLngItem) => PixelPoint,
  thresholdPx: number,
): PinCluster<T>[] {
  const clusters: PinCluster<T>[] = [];
  const thr2 = thresholdPx * thresholdPx;
  for (const item of items) {
    const pt = project(item);
    let matched = false;
    for (const c of clusters) {
      const dx = c.x - pt.x;
      const dy = c.y - pt.y;
      if (dx * dx + dy * dy <= thr2) {
        c.members.push(item);
        // Update cluster centre as running average (cheap approximation).
        c.x = (c.x * (c.members.length - 1) + pt.x) / c.members.length;
        c.y = (c.y * (c.members.length - 1) + pt.y) / c.members.length;
        matched = true;
        break;
      }
    }
    if (!matched) {
      clusters.push({ x: pt.x, y: pt.y, members: [item] });
    }
  }
  return clusters;
}
