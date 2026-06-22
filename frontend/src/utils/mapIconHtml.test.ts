import { describe, it, expect } from 'vitest';
import {
  buildCurrentPositionHtml,
  buildDestinationHtml,
  buildPreviewHtml,
  buildWaypointHtml,
  buildBookmarkPinHtml,
  buildBookmarkClusterHtml,
  buildBookmarkClusterRowHtml,
  buildBookmarkClusterPopupHtml,
} from './mapIconHtml';

describe('buildCurrentPositionHtml', () => {
  it('emits the two pulse rings the live-position marker reads as', () => {
    const html = buildCurrentPositionHtml(null);
    expect(html).toContain('class="pos-pulse-ring"');
    expect(html).toContain('pos-pulse-ring-2');
  });

  it('falls back to the default blue-person SVG when no avatar HTML', () => {
    expect(buildCurrentPositionHtml(undefined)).toContain('class="pos-icon"');
    expect(buildCurrentPositionHtml('')).toContain('class="pos-icon"');
  });

  it('uses the provided avatar HTML verbatim (trusted markup, not escaped)', () => {
    const html = buildCurrentPositionHtml('<img src="me.png">');
    expect(html).toContain('<img src="me.png">');
    expect(html).not.toContain('class="pos-icon"');
  });
});

describe('buildDestinationHtml', () => {
  it('builds the red teardrop SVG with its gradient + shadow ids', () => {
    const html = buildDestinationHtml();
    expect(html).toContain('id="destGrad"');
    expect(html).toContain('id="destShadow"');
    expect(html).toContain('viewBox="0 0 36 50"');
  });
});

describe('buildPreviewHtml', () => {
  it('builds the amber teardrop SVG with its gradient + shadow ids', () => {
    const html = buildPreviewHtml();
    expect(html).toContain('id="previewGrad"');
    expect(html).toContain('id="previewShadow"');
  });
});

describe('buildWaypointHtml', () => {
  it('renders index 0 as the green start "S"', () => {
    const html = buildWaypointHtml(0);
    expect(html).toContain('>S</div>');
    expect(html).toContain('#43a047'); // start green ring
  });

  it('renders a non-zero index as its number in orange', () => {
    const html = buildWaypointHtml(3);
    expect(html).toContain('>3</div>');
    expect(html).toContain('#ff9800'); // orange ring
  });
});

describe('buildBookmarkPinHtml', () => {
  it('escapes the bookmark name to block HTML injection', () => {
    const html = buildBookmarkPinHtml('<script>alert(1)</script>');
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(html).not.toContain('<script>alert(1)</script>');
  });

  it('renders a flag img when a country code is given, none otherwise', () => {
    expect(buildBookmarkPinHtml('Taipei', 'tw')).toContain(
      'https://flagcdn.com/w20/tw.png',
    );
    expect(buildBookmarkPinHtml('Taipei')).not.toContain('flagcdn.com');
  });
});

describe('buildBookmarkClusterHtml', () => {
  it('shows the member count', () => {
    expect(buildBookmarkClusterHtml(7)).toContain('>7</div>');
  });
});

describe('buildBookmarkClusterRowHtml', () => {
  it('carries the bm-cluster-row class + data-lat/lng for the popup click wiring', () => {
    const html = buildBookmarkClusterRowHtml({ name: 'A', lat: 25.1, lng: 121.5 });
    expect(html).toContain('class="bm-cluster-row"');
    expect(html).toContain('data-lat="25.1"');
    expect(html).toContain('data-lng="121.5"');
  });

  it('escapes the row name', () => {
    const html = buildBookmarkClusterRowHtml({ name: 'a & b', lat: 0, lng: 0 });
    expect(html).toContain('a &amp; b');
  });
});

describe('buildBookmarkClusterPopupHtml', () => {
  const members = [
    { name: 'Alpha', lat: 1, lng: 2 },
    { name: 'Beta', lat: 3, lng: 4 },
  ];

  it('renders one bm-cluster-row per member', () => {
    const html = buildBookmarkClusterPopupHtml(members);
    expect((html.match(/bm-cluster-row/g) || [])).toHaveLength(2);
    expect(html).toContain('Alpha');
    expect(html).toContain('Beta');
  });

  it('pluralizes the header by member count', () => {
    expect(buildBookmarkClusterPopupHtml(members)).toContain('2 bookmarks');
    expect(buildBookmarkClusterPopupHtml([{ name: 'Solo', lat: 0, lng: 0 }])).toContain(
      '1 bookmark',
    );
  });
});
