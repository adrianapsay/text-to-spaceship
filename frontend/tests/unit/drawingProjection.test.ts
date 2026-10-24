import { describe, expect, it } from 'vitest';
import { arrangeViews, type ViewSlot } from '../../src/components/drawing/layout';
import { boxEdges, chooseScale, cross, dimText, dot, linearDim, placeView, project, scaleLabel, sideView, STANDARD_SCALES, VIEWS, viewExtent, type Box3, type V3 } from '../../src/components/drawing/projection';
import { frameRect, TEMPLATES, titleBlock, type Rect } from '../../src/components/drawing/sheet';
import { centreLines, overallDims, viewMargins } from '../../src/components/drawing/sheetData';

const U3: Box3 = { min: [-50, -50, -170.25], max: [50, 50, 170.25] };
const near = (a: number[], b: number[], eps = 1e-9) => a.every((v, i) => Math.abs(v - b[i]) <= eps);
const overlap = (a: Rect, b: Rect) => Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
const outer = (v: ViewSlot): Rect => ({ x: v.x - v.margins.l, y: v.y - v.margins.t, w: v.w + v.margins.l + v.margins.r, h: v.h + v.margins.t + v.margins.b });

describe('V2 WS6 drawing projection, scales and dimensions', () => {
  it('views like the 3D view: front from −Y with Z up, plan from +Z with Y up, side views, a true isometric', () => {
    expect(near(VIEWS.front.right, [1, 0, 0]) && near(VIEWS.front.up, [0, 0, 1])).toBe(true);
    expect(near(VIEWS.top.right, [1, 0, 0]) && near(VIEWS.top.up, [0, 1, 0])).toBe(true);
    expect(near(VIEWS.left.right, [0, -1, 0]) && near(VIEWS.left.up, [0, 0, 1])).toBe(true);
    expect(near(VIEWS.right.right, [0, 1, 0]) && near(VIEWS.right.up, [0, 0, 1])).toBe(true);
    const s2 = Math.SQRT1_2;
    expect(near(VIEWS.iso.right, [s2, s2, 0])).toBe(true);
    expect(near(VIEWS.iso.up, [-1 / Math.sqrt(6), 1 / Math.sqrt(6), 2 / Math.sqrt(6)])).toBe(true);
    for (const v of Object.values(VIEWS)) {
      expect(dot(v.right, v.up)).toBeCloseTo(0, 12);
      expect(near(cross(v.right, v.up), v.dir.map((x) => -x) as V3, 1e-12)).toBe(true); // right-handed, looking along dir
    }
    // the isometric axes make 30° with the horizontal (true isometric)
    const x = [dot([1, 0, 0], VIEWS.iso.right), dot([1, 0, 0], VIEWS.iso.up)];
    expect((Math.atan2(-x[1], x[0]) * 180) / Math.PI).toBeCloseTo(30, 9);
    expect(sideView('first')).toBe('left');
    expect(sideView('third')).toBe('right');
  });

  it('a known box projects to the right size at a given scale, and back onto its corners', () => {
    const f = placeView(VIEWS.front, U3, 1 / 2, 40, 20);
    expect([f.w, f.h]).toEqual([50, 170.25]);
    expect(project(f, [-50, -50, 170.25])).toEqual([40, 20]); // top-left corner
    expect(project(f, [50, 50, -170.25])).toEqual([90, 190.25]);
    expect(project(f, [0, 0, 0])).toEqual([65, 105.125]); // the centre is the rectangle's centre
    const t = placeView(VIEWS.top, U3, 1 / 2, 0, 0);
    expect([t.w, t.h]).toEqual([50, 50]);
    expect(project(t, [-50, 50, 0])).toEqual([0, 0]); // back-left at the top of the plan
    const e = viewExtent(VIEWS.iso, U3);
    expect(e.w).toBeCloseTo(200 * Math.SQRT1_2, 9);
    expect(e.h).toBeCloseTo((2 * 340.5 + 2 * 100) / Math.sqrt(6), 9);
    // the 12 projected edges of the box in the front view stay on its rectangle
    for (const [a, b] of boxEdges(f, U3)) for (const p of [a, b]) expect(p[0] >= 40 - 1e-9 && p[0] <= 90 + 1e-9 && p[1] >= 20 - 1e-9 && p[1] <= 190.25 + 1e-9).toBe(true);
  });

  it('dimensions: the dimension line spans the projected feature and carries the model value', () => {
    const t = placeView(VIEWS.top, U3, 1 / 2, 100, 50);
    const a = project(t, [-50, -50, 0]);
    const b = project(t, [50, -50, 0]);
    const d = linearDim(a, b, 'x', 1, 8, dimText(100));
    expect(d.length).toBeCloseTo(50, 9); // 100 mm at 1:2
    expect(d.line).toEqual([[100, 108], [150, 108]]);
    expect(d.ext[0]).toEqual([[100, 101], [100, 110]]); // 1 mm gap from the outline, 2 mm beyond the line
    expect(d.text).toEqual({ x: 125, y: 107, rotate: 0, value: '100' });
    expect(d.arrows[0][0]).toEqual([100, 108]);
    expect(d.arrows[0][1][0]).toBeGreaterThan(100); // tips at the ends, pointing outward
    expect(d.arrows[1][1][0]).toBeLessThan(150);
    const f = placeView(VIEWS.front, U3, 1 / 2, 40, 20);
    const v = linearDim(project(f, [-50, -50, -170.25]), project(f, [-50, -50, 170.25]), 'y', -1, 16, dimText(340.5));
    expect(v.line[0][0]).toBe(24);
    expect(v.length).toBeCloseTo(170.25, 9);
    expect(v.text.rotate).toBe(-90); // read from the right
    expect(v.text.x).toBeLessThan(24);
    expect([dimText(340.5), dimText(100), dimText(147.64, true)]).toEqual(['340.5', '100', '(147.6)']);
  });

  it('standard ISO 5455 scales: the largest that fits is chosen', () => {
    expect(STANDARD_SCALES).toContain(1);
    expect([scaleLabel(1), scaleLabel(0.5), scaleLabel(2), scaleLabel(1 / 5), scaleLabel(10)]).toEqual(['1:1', '1:2', '2:1', '1:5', '10:1']);
    // 340.5 mm in 270 mm of paper: 1:2; a 30 mm bracket in 120 mm: 2:1 (5:1 would be 150 mm)
    expect(chooseScale((s) => 340.5 * s <= 270)).toBe(1 / 2);
    expect(chooseScale((s) => 30 * s <= 120)).toBe(2);
    expect(chooseScale((s) => 30 * s <= 120, 1)).toBe(1);
    expect(chooseScale(() => false)).toBeNull();
  });

  it('first-angle A3: front above the plan, the view from the left to its right, all aligned, nothing overlapping', () => {
    const t = TEMPLATES['iso-a3'];
    const L = arrangeViews({ template: t, box: U3, partsRows: 19, revRows: 1, margins: viewMargins('assembly') })!;
    expect(L.scale).toBe(1 / 2);
    const by = Object.fromEntries(L.views.map((v) => [v.view, v]));
    expect(Object.keys(by).sort()).toEqual(['front', 'iso', 'left', 'top']);
    expect(by.top.y).toBeGreaterThan(by.front.y + by.front.h); // plan below
    expect(by.top.x).toBeCloseTo(by.front.x, 9); // projection lines vertical
    expect(by.left.x).toBeGreaterThan(by.front.x + by.front.w); // side view to the right
    expect(by.left.y).toBeCloseTo(by.front.y, 9);
    const f = frameRect(t);
    const title = titleBlock(t).rect;
    const blocks = [title, L.revisions, L.parts!.rect];
    for (const v of L.views) {
      expect(outer(v).x).toBeGreaterThanOrEqual(f.x);
      expect(outer(v).x + outer(v).w).toBeLessThanOrEqual(f.x + f.w);
      expect(outer(v).y + outer(v).h).toBeLessThanOrEqual(f.y + f.h);
      for (const b of blocks) expect(overlap(outer(v), b)).toBe(0);
    }
    for (let i = 0; i < L.views.length; i++) for (let j = i + 1; j < L.views.length; j++) expect(overlap(outer(L.views[i]), outer(L.views[j]))).toBe(0);
    // dimensions from the same projection: overall height, used length (reference), widths
    const dims = overallDims(L.views, U3, 147.6);
    expect(dims.map((d) => d.text.value)).toEqual(['(147.6)', '340.5', '100', '100']);
    expect(dims[1].length).toBeCloseTo(340.5 * L.scale, 9);
    expect(dims[0].length).toBeCloseTo(147.6 * L.scale, 9);
    expect(centreLines(L.views, U3).length).toBe(4); // front, side, and the plan's cross
  });

  it('third-angle ANSI B: the plan above the front view, the view from the right to its right', () => {
    const L = arrangeViews({ template: TEMPLATES['ansi-b'], box: U3, partsRows: 19, revRows: 1, margins: viewMargins('assembly') })!;
    const by = Object.fromEntries(L.views.map((v) => [v.view, v]));
    expect(by.right).toBeDefined();
    expect(by.left).toBeUndefined();
    expect(by.top.y + by.top.h).toBeLessThan(by.front.y);
    expect(by.right.x).toBeGreaterThan(by.front.x + by.front.w);
    expect(by.right.y).toBeCloseTo(by.front.y, 9);
  });

  it('a small part is enlarged on its detail sheet', () => {
    const br: Box3 = { min: [10, -5, 20], max: [42, 13, 31] };
    const L = arrangeViews({ template: TEMPLATES['iso-a3'], box: br, partsRows: null, notesH: 46, revRows: 1, margins: viewMargins('detail'), maxScale: 10 })!;
    expect(L.scale).toBeGreaterThan(1);
    expect(STANDARD_SCALES).toContain(L.scale);
    expect(L.parts).toBeNull();
    expect(L.notes).not.toBeNull();
  });
});
