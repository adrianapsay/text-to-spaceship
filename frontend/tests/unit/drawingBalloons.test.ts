import { describe, expect, it } from 'vitest';
import { BALLOON_GAP, BALLOON_R, chooseBalloonViews, placeBalloons, spread, type Visibility } from '../../src/components/drawing/balloons';
import { analyseLabels, buildEdgeTable, decodeIds, edgesToWorld, featureSegments } from '../../src/components/drawing/render';
import type { Rect } from '../../src/components/drawing/sheet';
import { buildBomClient, itemNumbers } from '../../src/lib/bom';
import type { Layout, Part } from '../../src/api/types';

const vis = (itemNo: number, view: Visibility['view'], area: number, x: number, y: number, id = `p${itemNo}`): Visibility => ({ itemNo, view, area, anchor: [x, y], id });

describe('V2 WS6 balloons: every BOM item once, numbered like the BOM', () => {
  it('each item in the view where most of it shows; slivers are not ballooned', () => {
    const best = chooseBalloonViews([vis(1, 'front', 40, 0, 0), vis(1, 'iso', 55, 0, 0), vis(2, 'top', 3, 0, 0), vis(2, 'front', 2, 0, 0), vis(3, 'left', 0.1, 0, 0)]);
    expect(best.get(1)!.view).toBe('iso');
    expect(best.get(2)!.view).toBe('top');
    expect(best.has(3)).toBe(false);
  });

  it('balloon numbers match the BOM rows of the items drawn, each number once', () => {
    const parts: Record<string, Part> = {};
    const ids = ['a', 'b', 'c', 'd', 'e'];
    for (const id of ids) parts[id] = { id, name: id, mass_kg: 0.1, mass_source: 'ASSUMED', density_kg_m3: 2700, subsystem: 'power', extents_mm: [1, 1, 1] } as Part;
    const layout = { id: 'L-1', stage: 1, poses: ids.map((id) => ({ part_id: id, orient: 0, t_um: [0, 0, 0] })), extra_items: [], metrics: null } as unknown as Layout;
    const bom = buildBomClient(layout, parts, ids);
    const nums = itemNumbers(bom.items);
    // what the id rasters report: item c in two views, e hidden everywhere
    const seen = [vis(nums.get('a')!, 'front', 30, 10, 20, 'a'), vis(nums.get('b')!, 'front', 20, 40, 60, 'b'), vis(nums.get('c')!, 'front', 5, 30, 80, 'c'), vis(nums.get('c')!, 'top', 25, 30, 150, 'c'), vis(nums.get('d')!, 'top', 12, 20, 160, 'd')];
    const chosen = chooseBalloonViews(seen);
    const view: Rect = { x: 0, y: 0, w: 50, h: 100 };
    const balloons = [
      ...placeBalloons(view, { left: -8, right: 58 }, [0, 100], [...chosen.values()].filter((v) => v.view === 'front')),
      ...placeBalloons({ x: 0, y: 120, w: 50, h: 50 }, { left: -8, right: 58 }, [120, 170], [...chosen.values()].filter((v) => v.view === 'top')),
    ];
    const numbers = balloons.map((b) => b.itemNo).sort((x, y) => x - y);
    expect(numbers).toEqual([1, 2, 3, 4]); // a, b, c, d in the parts order; e (item 5) is not visible
    expect(new Set(numbers).size).toBe(numbers.length);
    for (const b of balloons) expect(bom.items[b.itemNo - 1].item_ids).toContain(b.id);
  });

  it('balloons in a lane keep their order and spacing, so their leaders do not cross; leaders end on the item', () => {
    const view: Rect = { x: 100, y: 50, w: 50, h: 170 };
    const refs = [vis(1, 'front', 9, 110, 60), vis(2, 'front', 9, 112, 61), vis(3, 'front', 9, 115, 62), vis(4, 'front', 9, 140, 200), vis(5, 'front', 9, 145, 120)];
    const out = placeBalloons(view, { left: 90, right: 160 }, [50, 220], refs);
    expect(out).toHaveLength(5);
    for (const side of ['left', 'right'] as const) {
      const lane = out.filter((b) => b.side === side).sort((p, q) => p.centre[1] - q.centre[1]);
      for (let i = 1; i < lane.length; i++) {
        expect(lane[i].centre[1] - lane[i - 1].centre[1]).toBeGreaterThanOrEqual(2 * BALLOON_R + BALLOON_GAP - 1e-9);
        expect(lane[i].anchor[1]).toBeGreaterThanOrEqual(lane[i - 1].anchor[1]); // same order as their anchors
      }
    }
    for (const b of out) {
      expect(b.side === 'left' ? b.anchor[0] < 125 : b.anchor[0] >= 125).toBe(true);
      expect(b.centre[0]).toBe(b.side === 'left' ? 90 : 160);
      expect(b.leader[1]).toEqual(b.anchor);
      expect(Math.hypot(b.leader[0][0] - b.centre[0], b.leader[0][1] - b.centre[1])).toBeCloseTo(BALLOON_R, 9);
      expect(b.centre[1] - BALLOON_R).toBeGreaterThanOrEqual(50 - 1e-9);
      expect(b.centre[1] + BALLOON_R).toBeLessThanOrEqual(220 + 1e-9);
    }
  });

  it('a full lane hands balloons to the other one; an overfull lane is spread evenly', () => {
    const view: Rect = { x: 0, y: 0, w: 40, h: 40 };
    const refs = Array.from({ length: 8 }, (_, i) => vis(i + 1, 'top', 5, 5 + i * 0.1, 5 + i * 4));
    const out = placeBalloons(view, { left: -8, right: 48 }, [0, 40], refs);
    const cap = Math.floor((40 - 2 * BALLOON_R) / (2 * BALLOON_R + BALLOON_GAP)) + 1;
    expect(out.filter((b) => b.side === 'left')).toHaveLength(cap);
    expect(out.filter((b) => b.side === 'right')).toHaveLength(8 - cap);
    expect(spread([5, 5, 5], 10, 0, 10)).toEqual([0, 5, 10]);
    expect(spread([1, 2], 3, 0, 100)).toEqual([1, 4]);
  });
});

describe('V2 WS6 drawing edges and the id raster', () => {
  // a unit cube as three.js BoxGeometry stores it: 24 vertices (4 per face), 12 triangles
  function cube(): { pos: number[]; idx: number[] } {
    const pos: number[] = [];
    const idx: number[] = [];
    const faces: [number, number, number][] = [[0, 1, 2], [0, 2, 1], [1, 2, 0], [1, 0, 2], [2, 0, 1], [2, 1, 0]];
    faces.forEach(([a, b, c], f) => {
      const s = f % 2 === 0 ? 1 : 0;
      const base = pos.length / 3;
      for (const [u, v] of [[0, 0], [1, 0], [1, 1], [0, 1]]) {
        const p = [0, 0, 0];
        p[a] = s;
        p[b] = u;
        p[c] = v;
        pos.push(...p);
      }
      idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    });
    return { pos, idx };
  }

  it('welds a split-vertex box into 18 edges: 12 creases and 6 flat diagonals', () => {
    const { pos, idx } = cube();
    const t = buildEdgeTable(pos, idx);
    expect(t.count).toBe(18);
    expect([...t.crease].filter((c) => c).length).toBe(12);
    // all 12 box edges in every view; the diagonals never (flat)
    expect(featureSegments(t, [0, 1, 0]).length / 6).toBe(12);
  });

  it('a smooth cylinder shows its two silhouette lines and its rims, not its facets', () => {
    const n = 48;
    const pos: number[] = [];
    const idx: number[] = [];
    for (let i = 0; i < n; i++) {
      const a = (2 * Math.PI * (i + 0.5)) / n;
      pos.push(Math.cos(a), Math.sin(a), 0, Math.cos(a), Math.sin(a), 2);
    }
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n;
      idx.push(2 * i, 2 * j, 2 * j + 1, 2 * i, 2 * j + 1, 2 * i + 1);
    }
    pos.push(0, 0, 0, 0, 0, 2);
    const c0 = 2 * n;
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n;
      idx.push(c0, 2 * j, 2 * i, c0 + 1, 2 * i + 1, 2 * j + 1);
    }
    const t = buildEdgeTable(pos, idx);
    const side = featureSegments(t, [0, 1, 0]).length / 6;
    expect(side).toBe(2 * n + 2); // two rims (creases) + the two silhouette generators
    const top = featureSegments(t, [0, 0, -1]).length / 6;
    expect(top).toBe(2 * n); // seen along its axis: only the rims
    // placed in the world (rotated about x by 90°, scaled 2×, moved): the silhouette follows the view
    const w = edgesToWorld(t, { R: [[1, 0, 0], [0, 0, -1], [0, 1, 0]], s: 2, t: [5, 0, 0] });
    expect(featureSegments(w, [0, 0, -1]).length / 6).toBe(2 * n + 2);
    expect(Math.max(...Array.from(w.a).filter((_, i) => i % 3 === 0))).toBeCloseTo(5 + 2 * Math.cos(Math.PI / n), 5);
  });

  it('the id raster gives each item its visible area and a point well inside it', () => {
    const w = 20;
    const h = 10;
    const labels = new Int32Array(w * h).fill(-1);
    for (let y = 1; y < 9; y++) for (let x = 1; x < 9; x++) labels[y * w + x] = 0; // 8 × 8 square
    for (let y = 2; y < 5; y++) for (let x = 12; x < 19; x++) labels[y * w + x] = 1; // 7 × 3 bar
    const a = analyseLabels(labels, w, h, 3);
    expect([...a.count]).toEqual([64, 21, 0]);
    const ax = a.anchor[0] % w;
    const ay = Math.floor(a.anchor[0] / w);
    expect(Math.abs(ax - 4.5)).toBeLessThanOrEqual(1);
    expect(Math.abs(ay - 4.5)).toBeLessThanOrEqual(1);
    expect(Math.floor(a.anchor[1] / w)).toBe(3);
    expect(a.anchor[2]).toBe(-1);
    // WebGL rows come bottom first; white is background, ids are 1-based in red/green
    const buf = new Uint8Array([255, 255, 255, 255, 2, 0, 0, 255, 1, 1, 0, 255, 255, 255, 255, 255]);
    expect([...decodeIds(buf, 2, 2)]).toEqual([256, -1, -1, 1]);
  });
});
