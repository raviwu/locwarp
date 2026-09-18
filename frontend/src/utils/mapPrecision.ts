// Map-pixel <-> ground-precision policy. Pure arithmetic, zero imports, so it
// stays trivially testable and usable from any ring.
//
// Why this module exists: Leaflet turns a right-click's SCREEN PIXEL into a
// lat/lng at the map's current zoom. At zoom 8 one pixel is 220-610 m of
// ground, so a click that looks perfectly on-target can store a bookmark
// kilometres away. On 2026-09-17, 22 bookmarks were saved 0.67-8.7 km off this
// way; every one of them landed on an exact integer-pixel grid at zoom 6-8.

export interface PixelPoint {
  x: number
  y: number
}

// The current-position marker is a 44x44 divIcon anchored at its centre
// (`iconAnchor: [22, 22]` in hooks/useCurrentPositionLayer.ts) and is
// `interactive: false`, so a right-click anywhere on the avatar passes THROUGH
// to the map and arrives up to 22 px from the true anchor. Keep this in step
// with that icon's size: radius = iconSize / 2.
export const MARKER_SNAP_RADIUS_PX = 22

// Show the add-bookmark precision hint once a single pixel is worth this many
// metres (~zoom 12 at mid latitudes). A live-store scan found every one of the
// 35 historically-imprecise bookmarks was created at zoom <= 12.
export const PRECISION_HINT_M_PER_PX = 25

/**
 * The coordinate a map right-click should act on.
 *
 * When the click landed inside the position marker's on-screen footprint the
 * user was pointing AT the device, not at a pixel near it — so return the
 * device's exact position instead of the click's own (zoom-quantised)
 * coordinate. Otherwise the click stands, unchanged.
 *
 * Both points are container pixels from the same map, so the comparison is
 * zoom-independent: it always means "within the avatar graphic".
 */
export function snapContextCoord(
  click: { lat: number; lng: number; point: PixelPoint },
  current: { lat: number; lng: number; point: PixelPoint } | null,
  radiusPx: number = MARKER_SNAP_RADIUS_PX,
): { lat: number; lng: number; snapped: boolean } {
  if (current) {
    const dx = click.point.x - current.point.x
    const dy = click.point.y - current.point.y
    if (Math.sqrt(dx * dx + dy * dy) <= radiusPx) {
      return { lat: current.lat, lng: current.lng, snapped: true }
    }
  }
  return { lat: click.lat, lng: click.lng, snapped: false }
}

// Ground resolution of one screen pixel, web-mercator, 256 px tiles.
// 156543.03392 = earth equatorial circumference / 256.
export function metersPerPixel(lat: number, zoom: number): number {
  return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, zoom)
}
