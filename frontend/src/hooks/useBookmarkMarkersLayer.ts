import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { clusterByPixelDistance } from '../utils/pinCluster'
import {
  buildBookmarkPinHtml,
  buildBookmarkClusterHtml,
  buildBookmarkClusterPopupHtml,
} from '../utils/mapIconHtml'

// ─────────────────────────────────────────────────────────────────────────────
// useBookmarkMarkersLayer — the small clickable bookmark pins rendered on the
// map when the user toggles 'show all bookmarks on map', carved VERBATIM out of
// MapView's bookmark-pins rebuild effect (Phase 4b, task p4b2bi). Owns the ONE
// layer's marker ref:
//   - bookmarkMarkersRef — the live L.marker[] (single-pin `.bookmark-pin`
//     divIcons + cluster `.bookmark-cluster-pin` divIcons), fully torn down +
//     rebuilt on every effect run AND on every `zoomend`.
//
// The clustering is screen-pixel based: bookmarks within ~40px of each other at
// the CURRENT zoom collapse into a single polaroid-stack cluster pin. Because
// "what overlaps at world-scale is not overlapping at street-scale", the whole
// pin set is re-clustered + rebuilt on every `zoomend`. The pure pixel math
// lives in `clusterByPixelDistance` (unit-tested in utils/pinCluster.ts); this
// hook hands it Leaflet's `map.latLngToLayerPoint` as the projector EXACTLY as
// the original effect did. The single-pin / cluster-pin / cluster-popup HTML
// builders are the pure `buildBookmark*Html` helpers (unit-tested in
// utils/mapIconHtml.ts).
//
// CRITICAL listener lifecycle — the `zoomend` rebuild listener (`onZoom`) is
// added with `map.on('zoomend', onZoom)` and removed in the effect cleanup with
// `map.off('zoomend', onZoom)`. A leaked `zoomend` listener (or an orphaned
// marker layer) is the main risk of this carve-out, so the add + the matching
// off are kept together, byte-for-byte, inside this single effect — every
// re-run / unmount removes the prior listener before (re)adding.
//
// The cluster popup's clickable rows wire `onTeleport(lat, lng)` through the
// same `popupopen` → `document.querySelectorAll('.bm-cluster-row')` DOM-query
// click handler as the original (reading `data-lat`/`data-lng`, closing the
// popup, then teleporting). Verbatim.
//
// Runs as a mapRef-dependent effect AFTER useMapInstance has created the map,
// guarding `if (!map) return` — preserving the documented map-init ORDER. The
// effect body is the original VERBATIM; the dep array stays
// `[bookmarkPins, showBookmarkPins, onTeleport]`.
//
// This overlay is prop-driven and has NO e2e net — it was moved byte-for-byte;
// the clustering + icon algorithms ARE unit-tested.
// ─────────────────────────────────────────────────────────────────────────────

/** One bookmark to render as a small clickable pin. Mirrors MapView's prop shape. */
interface BookmarkPin {
  id?: string
  name: string
  lat: number
  lng: number
  country_code?: string
  city?: string
  timezone?: string
}

export interface UseBookmarkMarkersLayerOptions {
  // The bookmark list to render as small clickable markers. When `showBookmarkPins`
  // is on and this is non-empty, each pin (or polaroid-stack cluster) is clickable;
  // clicking teleports to that bookmark's coordinate via `onTeleport`.
  bookmarkPins?: BookmarkPin[]
  // Master toggle for the overlay. When false (or absent) the layer is torn down
  // and nothing is drawn — matching the original early-return.
  showBookmarkPins?: boolean
  // Teleport callback fired on a single-pin click and on a cluster-popup row
  // click. Same `(lat, lng)` signature the original inline handlers passed.
  onTeleport: (lat: number, lng: number) => void
}

/**
 * Draws / rebuilds the small bookmark pins (with screen-pixel clustering),
 * owning its marker ref and the `zoomend` rebuild listener. The single-pin
 * click and the cluster-popup row click both teleport via `onTeleport`.
 *
 * @param mapRef the live map ref owned by useMapInstance
 * @param opts the bookmark list + the show toggle + the teleport callback
 */
export function useBookmarkMarkersLayer(
  mapRef: React.RefObject<L.Map | null>,
  { bookmarkPins, showBookmarkPins, onTeleport }: UseBookmarkMarkersLayerOptions,
) {
  const bookmarkMarkersRef = useRef<L.Marker[]>([])

  // Render/clear small bookmark pins on the map when the user toggles
  // 'show all bookmarks on map'. Each pin is clickable and teleports to
  // that bookmark's position.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    bookmarkMarkersRef.current.forEach((m) => m.remove());
    bookmarkMarkersRef.current = [];
    if (!showBookmarkPins || !bookmarkPins || bookmarkPins.length === 0) return;

    // Cluster bookmarks that fall within ~40 px of each other at the current
    // zoom. One teardrop pin represents the group; clicking a cluster opens a
    // popup list the user can tap to choose which exact bookmark to jump to.
    // This stops a dozen pins stacking into what looks like a single dot when
    // the user zooms out to see all of Taiwan.
    const rebuild = () => {
      bookmarkMarkersRef.current.forEach((m) => m.remove());
      bookmarkMarkersRef.current = [];
      const THRESHOLD_PX = 40;
      const clusters = clusterByPixelDistance(
        bookmarkPins!,
        (item) => map.latLngToLayerPoint([item.lat, item.lng]),
        THRESHOLD_PX,
      );

      clusters.forEach((c) => {
        if (c.members.length === 1) {
          const bm = c.members[0];
          // Design 5 — Neon glass bubble. Frosted capsule with purple glow,
          // flag + name inside, tiny pointing nub underneath pinning the
          // coordinate. Max width 180px, name truncates with ellipsis.
          const icon = L.divIcon({
            className: 'bookmark-pin',
            // Outer div fills the Leaflet divIcon container, flex column
            // bottom-center so the glowing dot at the bottom sits exactly
            // on the (lat, lng) coordinate (matches iconAnchor below).
            html: buildBookmarkPinHtml(bm.name, bm.country_code),
            iconSize: [200, 56],
            // Anchor = bottom-center of the icon = the glowing dot = exact
            // (lat, lng) coordinate. Previously the flex-inline column was
            // sitting at top-left so the whole pin rendered above-left of
            // the real point.
            iconAnchor: [100, 56],
          });
          const marker = L.marker([bm.lat, bm.lng], {
            icon,
            pane: 'markerPane',
            // Sit above the blue person marker (zIndexOffset 1000) so the
            // pin stays clickable when the user is standing on it.
            zIndexOffset: 2000,
          });
          marker.on('click', () => onTeleport(bm.lat, bm.lng));
          marker.addTo(map);
          bookmarkMarkersRef.current.push(marker);
        } else {
          // Design 4 — Polaroid stack cluster. Three overlapping mini cards
          // with rotation, top one shows the count. Click = open list popup.
          const count = c.members.length;
          const icon = L.divIcon({
            className: 'bookmark-cluster-pin',
            html: buildBookmarkClusterHtml(count),
            iconSize: [52, 46],
            iconAnchor: [26, 23],
          });
          const clusterLat = c.members.reduce((s, m) => s + m.lat, 0) / count;
          const clusterLng = c.members.reduce((s, m) => s + m.lng, 0) / count;
          const marker = L.marker([clusterLat, clusterLng], {
            icon,
            pane: 'markerPane',
            // Above blue person so the cluster card is always clickable.
            zIndexOffset: 2000,
          });
          // Click on a cluster opens a popup with a clickable list so the
          // user can pick which specific bookmark to teleport to. Solves the
          // 'zoom out to see whole country, markers overlap into one dot'
          // usability issue.
          const popup = L.popup({
            className: 'bookmark-cluster-popup',
            maxWidth: 240,
            offset: [0, -12],
          }).setContent(buildBookmarkClusterPopupHtml(c.members));
          marker.bindPopup(popup);
          marker.on('popupopen', () => {
            document.querySelectorAll('.bm-cluster-row').forEach((el) => {
              el.addEventListener('click', () => {
                const lat = parseFloat((el as HTMLElement).dataset.lat || '');
                const lng = parseFloat((el as HTMLElement).dataset.lng || '');
                if (Number.isFinite(lat) && Number.isFinite(lng)) {
                  map.closePopup();
                  onTeleport(lat, lng);
                }
              });
            });
          });
          marker.addTo(map);
          bookmarkMarkersRef.current.push(marker);
        }
      });
    };
    rebuild();

    // Rebuild clusters when the zoom level changes — what's 'overlapping'
    // at world-scale is not overlapping at street-scale.
    const onZoom = () => rebuild();
    map.on('zoomend', onZoom);
    return () => { map.off('zoomend', onZoom); };
  }, [bookmarkPins, showBookmarkPins, onTeleport]);
}
