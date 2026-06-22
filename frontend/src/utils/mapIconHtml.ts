/**
 * Icon-HTML builders — the PURE string-building helpers that produce the
 * raw `html` payloads handed to `L.divIcon({ html })` / `L.popup().setContent()`
 * in MapView's Leaflet effects.
 *
 * Pure: inputs -> HTML string. No Leaflet, no DOM. The Leaflet effects in
 * MapView keep owning `L.divIcon`, `className`, `iconSize`, `iconAnchor`,
 * marker creation and event wiring — only the html-string math lives here.
 *
 * NOTE: the load-bearing `className` props the e2e suite asserts on
 * (`current-pos-marker`, `dest-marker`, ...) stay on the `L.divIcon` call in
 * MapView, NOT in these strings (Leaflet applies them to the wrapper div).
 */

import { escapeHtml } from './escapeHtml';

/** Default blue-person SVG used when the user has no custom avatar HTML. */
const DEFAULT_AVATAR_SVG = `<svg width="44" height="44" viewBox="0 0 44 44" class="pos-icon">
            <defs>
              <radialGradient id="posGlow" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stop-color="#4285f4" stop-opacity="0.3"/>
                <stop offset="100%" stop-color="#4285f4" stop-opacity="0"/>
              </radialGradient>
              <filter id="posShadow" x="-30%" y="-30%" width="160%" height="160%">
                <feDropShadow dx="0" dy="1" stdDeviation="2" flood-color="#4285f4" flood-opacity="0.6"/>
              </filter>
            </defs>
            <circle cx="22" cy="22" r="20" fill="url(#posGlow)"/>
            <circle cx="22" cy="22" r="11" fill="#4285f4" filter="url(#posShadow)"/>
            <circle cx="22" cy="22" r="9" fill="#2b6ff2"/>
            <circle cx="22" cy="18" r="3.5" fill="#ffffff" opacity="0.95"/>
            <path d="M15.5 28.5c0-3.6 2.9-6.5 6.5-6.5s6.5 2.9 6.5 6.5" fill="#ffffff" opacity="0.95" stroke="none"/>
            <circle cx="22" cy="22" r="11" fill="none" stroke="#ffffff" stroke-width="2" opacity="0.8"/>
          </svg>`;

/**
 * HTML for the current-position (blue person) divIcon body: two pulse rings
 * plus either the user's custom avatar HTML or the default blue-person SVG.
 * `userAvatarHtml` is trusted markup supplied by the app shell, so it is NOT
 * escaped (matches the original effect).
 */
export function buildCurrentPositionHtml(userAvatarHtml?: string | null): string {
  const avatarInner = userAvatarHtml && userAvatarHtml.length > 0
    ? userAvatarHtml
    : DEFAULT_AVATAR_SVG;
  return `<div class="pos-pulse-ring"></div>
          <div class="pos-pulse-ring pos-pulse-ring-2"></div>
          ${avatarInner}`;
}

/** HTML for the destination (red teardrop) divIcon body. */
export function buildDestinationHtml(): string {
  return `<svg width="36" height="50" viewBox="0 0 36 50">
          <defs>
            <filter id="destShadow" x="-20%" y="-10%" width="140%" height="130%">
              <feDropShadow dx="0" dy="2" stdDeviation="2.5" flood-color="#000" flood-opacity="0.4"/>
            </filter>
            <linearGradient id="destGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#ff6b6b"/>
              <stop offset="100%" stop-color="#e53935"/>
            </linearGradient>
          </defs>
          <ellipse cx="18" cy="47" rx="6" ry="2" fill="#000" opacity="0.2"/>
          <path d="M18 2C9.7 2 3 8.7 3 17c0 12 15 30 15 30s15-18 15-30C33 8.7 26.3 2 18 2z"
                fill="url(#destGrad)" filter="url(#destShadow)"/>
          <circle cx="18" cy="17" r="7" fill="#ffffff" opacity="0.95"/>
          <svg x="11" y="10" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#e53935" stroke-width="2.5">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/>
            <circle cx="12" cy="10" r="3"/>
          </svg>
        </svg>`;
}

/** HTML for the preview (amber teardrop, eye icon) divIcon body. */
export function buildPreviewHtml(): string {
  return `<svg width="36" height="50" viewBox="0 0 36 50">
          <defs>
            <filter id="previewShadow" x="-20%" y="-10%" width="140%" height="130%">
              <feDropShadow dx="0" dy="2" stdDeviation="2.5" flood-color="#000" flood-opacity="0.4"/>
            </filter>
            <linearGradient id="previewGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#fbbf24"/>
              <stop offset="100%" stop-color="#d97706"/>
            </linearGradient>
          </defs>
          <ellipse cx="18" cy="47" rx="6" ry="2" fill="#000" opacity="0.2"/>
          <path d="M18 2C9.7 2 3 8.7 3 17c0 12 15 30 15 30s15-18 15-30C33 8.7 26.3 2 18 2z"
                fill="url(#previewGrad)" filter="url(#previewShadow)"
                stroke="rgba(255,255,255,0.7)" stroke-width="1.2"/>
          <circle cx="18" cy="17" r="7" fill="#ffffff" opacity="0.95"/>
          <svg x="11" y="10" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2.2">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
        </svg>`;
}

/**
 * HTML for a waypoint (subway-station ring + stem + ground shadow) divIcon
 * body. `index === 0` is the implicit start point (green "S"); others are
 * numbered orange. `label` is derived numeric/literal text, not user input.
 */
export function buildWaypointHtml(index: number): string {
  const isStart = index === 0;
  const label = isStart ? 'S' : String(index);
  const ringColor = isStart ? '#43a047' : '#ff9800';
  const ringGlow = isStart ? 'rgba(67,160,71,0.32)' : 'rgba(255,152,0,0.3)';
  const textColor = isStart ? '#1b5e20' : '#e65100';
  const stemStart = isStart ? '#43a047' : '#ff9800';
  const stemEnd = isStart ? 'rgba(67,160,71,0)' : 'rgba(255,152,0,0)';
  return `<div style="
          position:relative;width:100%;height:100%;
          display:flex;flex-direction:column;align-items:center;justify-content:flex-end;
          pointer-events:auto;cursor:pointer;">
          <div style="
            width:28px;height:28px;border-radius:50%;
            border:4px solid ${ringColor};background:#fff;
            display:flex;align-items:center;justify-content:center;
            color:${textColor};font-weight:800;font-size:13px;
            font-family:system-ui,-apple-system,'Segoe UI',sans-serif;
            box-shadow:0 0 0 2px ${ringGlow}, 0 3px 8px rgba(0,0,0,0.4);
          ">${label}</div>
          <div style="
            width:2px;height:10px;margin-top:-1px;
            background:linear-gradient(180deg, ${stemStart}, ${stemEnd});
          "></div>
          <div style="
            width:12px;height:3px;margin-top:-1px;
            background:rgba(0,0,0,0.5);border-radius:50%;filter:blur(1px);
          "></div>
        </div>`;
}

/** Flag `<img>` for a country code, or '' when absent. `w` is the flagcdn width key. */
function flagImg(countryCode: string | undefined, style: string): string {
  return countryCode
    ? `<img src="https://flagcdn.com/w20/${countryCode}.png" style="${style}" alt="" />`
    : '';
}

/**
 * HTML for a single bookmark pin (neon glass bubble). `name` is escaped via
 * escapeHtml; the flag image is built from the (trusted) country code.
 */
export function buildBookmarkPinHtml(name: string, countryCode?: string): string {
  const flagHtml = flagImg(
    countryCode,
    'width:18px;height:12px;border-radius:2px;flex-shrink:0;display:inline-block;vertical-align:middle;',
  );
  return `<div style="width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;pointer-events:none;">
              <div style="
                padding:5px 12px 5px 6px;
                border-radius:100px;
                background:linear-gradient(135deg, rgba(255,255,255,0.88), rgba(255,255,255,0.68));
                color:#0e0f10;
                font-size:12px;font-weight:600;line-height:1.2;
                box-shadow:
                  0 0 0 1px rgba(99,102,241,0.45),
                  0 0 14px rgba(99,102,241,0.4),
                  0 3px 8px rgba(0,0,0,0.15);
                display:inline-flex;align-items:center;gap:6px;
                max-width:180px;white-space:nowrap;overflow:hidden;
                backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
                pointer-events:auto;cursor:pointer;
              ">${flagHtml}<span style="overflow:hidden;text-overflow:ellipsis;max-width:140px;">${escapeHtml(name)}</span></div>
              <div style="
                width:10px;height:10px;margin-top:-5px;
                background:linear-gradient(135deg, rgba(255,255,255,0.88), rgba(255,255,255,0.68));
                transform:rotate(45deg);
                box-shadow:2px 2px 6px rgba(99,102,241,0.3);
                border-right:1px solid rgba(99,102,241,0.45);
                border-bottom:1px solid rgba(99,102,241,0.45);
              "></div>
              <div style="width:5px;height:5px;border-radius:50%;background:rgba(99,102,241,0.7);margin-top:-3px;box-shadow:0 0 8px rgba(99,102,241,0.9);"></div>
            </div>`;
}

/** HTML for a bookmark cluster pin (polaroid stack showing the count). */
export function buildBookmarkClusterHtml(count: number): string {
  return `<div style="position:relative;width:52px;height:46px;pointer-events:none;">
              <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%) rotate(-8deg) translate(-4px, 3px);width:38px;height:32px;background:#fff;border:1px solid #c8ccd4;box-shadow:0 2px 6px rgba(0,0,0,0.3);"></div>
              <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%) rotate(6deg) translate(4px, -2px);width:38px;height:32px;background:#fff;border:1px solid #c8ccd4;box-shadow:0 2px 6px rgba(0,0,0,0.3);"></div>
              <div style="
                position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
                width:38px;height:32px;background:#fff;border:1px solid #c8ccd4;
                box-shadow:0 2px 8px rgba(0,0,0,0.35);
                display:flex;align-items:center;justify-content:center;
                font-weight:700;font-size:15px;color:#2d3748;
                pointer-events:auto;cursor:pointer;
              ">${count}</div>
              <div style="
                position:absolute;top:50%;left:50%;transform:translate(-50%,-50%) translate(0, -14px);
                width:14px;height:3px;background:rgba(253,216,53,0.85);border-radius:1px;
                box-shadow:0 1px 2px rgba(0,0,0,0.2);
                z-index:3;
              "></div>
            </div>`;
}

/** One clickable row in the bookmark-cluster popup list. `name` is escaped. */
export function buildBookmarkClusterRowHtml(
  bm: { name: string; lat: number; lng: number; country_code?: string },
): string {
  const flag = flagImg(
    bm.country_code,
    'width:14px;height:10px;border-radius:1px;vertical-align:middle;margin-right:6px;',
  );
  return `<div
              class="bm-cluster-row"
              data-lat="${bm.lat}" data-lng="${bm.lng}"
              style="display:flex;align-items:center;gap:4px;padding:6px 8px;cursor:pointer;border-radius:4px;color:#e8e8ea;font-size:12px;transition:background 0.1s;"
              onmouseenter="this.style.background='rgba(255,255,255,0.08)'"
              onmouseleave="this.style.background='transparent'"
            >${flag}<span style="flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(bm.name)}</span></div>`;
}

/**
 * Full popup content for a bookmark cluster: a header with the count plus the
 * concatenated row list. `members` rows are escaped per-row; the header label
 * pluralizes via escapeHtml on the literal 'bookmark'/'bookmarks'.
 */
export function buildBookmarkClusterPopupHtml(
  members: ReadonlyArray<{ name: string; lat: number; lng: number; country_code?: string }>,
): string {
  const count = members.length;
  const listHtml = members.map((bm) => buildBookmarkClusterRowHtml(bm)).join('');
  return `
            <div style="background:rgba(26,29,39,0.96);backdrop-filter:blur(12px);border:1px solid rgba(108,140,255,0.25);border-radius:8px;padding:6px;min-width:180px;max-height:280px;overflow-y:auto;">
              <div style="padding:4px 8px;font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#9ac0ff;">${count} ${escapeHtml(count === 1 ? 'bookmark' : 'bookmarks')}</div>
              ${listHtml}
            </div>
          `;
}
