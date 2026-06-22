import { describe, it, expect } from 'vitest';
import { clusterByPixelDistance, type LatLngItem, type PixelPoint } from './pinCluster';

// Each test item carries an explicit projected point so we can drive the
// pure math without Leaflet. We tag items with a `px`/`py` so the injected
// `project` fn just reads them back.
interface TestItem extends LatLngItem {
  name: string;
  px: number;
  py: number;
}

function item(name: string, px: number, py: number): TestItem {
  // lat/lng are irrelevant to clustering math (only `project` output matters),
  // but the running-average centre uses the projected px/py, not lat/lng.
  return { name, px, py, lat: 0, lng: 0 };
}

const project = (it: LatLngItem): PixelPoint => ({ x: (it as TestItem).px, y: (it as TestItem).py });

describe('clusterByPixelDistance', () => {
  it('returns no clusters for empty input', () => {
    expect(clusterByPixelDistance([], project, 40)).toEqual([]);
  });

  it('clusters two points within the threshold into one group', () => {
    const items = [item('a', 0, 0), item('b', 30, 0)]; // 30px apart, threshold 40
    const clusters = clusterByPixelDistance(items, project, 40);
    expect(clusters).toHaveLength(1);
    expect(clusters[0].members.map((m) => (m as TestItem).name)).toEqual(['a', 'b']);
  });

  it('keeps two points beyond the threshold as separate groups', () => {
    const items = [item('a', 0, 0), item('b', 50, 0)]; // 50px apart, threshold 40
    const clusters = clusterByPixelDistance(items, project, 40);
    expect(clusters).toHaveLength(2);
    expect(clusters[0].members).toHaveLength(1);
    expect(clusters[1].members).toHaveLength(1);
  });

  it('clusters at the exact threshold boundary (d == threshold is inclusive)', () => {
    const items = [item('a', 0, 0), item('b', 40, 0)]; // exactly 40px apart
    const clusters = clusterByPixelDistance(items, project, 40);
    expect(clusters).toHaveLength(1);
    expect(clusters[0].members).toHaveLength(2);
  });

  it('separates points one pixel beyond the boundary', () => {
    const items = [item('a', 0, 0), item('b', 41, 0)]; // 41px > 40
    const clusters = clusterByPixelDistance(items, project, 40);
    expect(clusters).toHaveLength(2);
  });

  it('uses squared euclidean distance (diagonal is the hypotenuse, not axis sum)', () => {
    // (30,30) is sqrt(1800)=~42.4 from origin > 40 → separate, even though
    // each axis delta (30) is under threshold. Guards against a Manhattan bug.
    const items = [item('a', 0, 0), item('b', 30, 30)];
    const clusters = clusterByPixelDistance(items, project, 40);
    expect(clusters).toHaveLength(2);
  });

  it('updates the cluster centre as a running average', () => {
    // a at 0, b at 40 → centre after 2 members = 20; c at 35 is within 40 of
    // centre 20 (|35-20|=15) so it joins; centre becomes (0+40+35)/3 = 25.
    const items = [item('a', 0, 0), item('b', 40, 0), item('c', 35, 0)];
    const clusters = clusterByPixelDistance(items, project, 40);
    expect(clusters).toHaveLength(1);
    expect(clusters[0].members).toHaveLength(3);
    expect(clusters[0].x).toBeCloseTo(25, 6);
    expect(clusters[0].y).toBeCloseTo(0, 6);
  });

  it('first-match-wins: an item joins the first cluster it is within range of', () => {
    // Two seeds far apart; a third point near the FIRST seed joins it even
    // though it could conceivably be measured against later clusters.
    const items = [item('a', 0, 0), item('b', 200, 0), item('c', 10, 0)];
    const clusters = clusterByPixelDistance(items, project, 40);
    expect(clusters).toHaveLength(2);
    expect(clusters[0].members.map((m) => (m as TestItem).name)).toEqual(['a', 'c']);
    expect(clusters[1].members.map((m) => (m as TestItem).name)).toEqual(['b']);
  });
});
