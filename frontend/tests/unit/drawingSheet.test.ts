import { describe, expect, it } from 'vitest';
import { centringMarks, divisions, fitText, frameRect, partsList, PL_HEAD, projectionSymbol, revisionBlock, TEMPLATES, TITLE_H, TITLE_W, titleBlock, zones, type Rect } from '../../src/components/drawing/sheet';

const overlap = (a: Rect, b: Rect) => Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
const inside = (a: Rect, b: Rect) => a.x >= b.x - 1e-9 && a.y >= b.y - 1e-9 && a.x + a.w <= b.x + b.w + 1e-9 && a.y + a.h <= b.y + b.h + 1e-9;

describe('V2 WS6 drawing sheet templates', () => {
  it('ISO A3: 420 × 297 mm, 20 mm filing margin, 10 mm elsewhere', () => {
    const t = TEMPLATES['iso-a3'];
    expect([t.width, t.height, t.size, t.projection]).toEqual([420, 297, 'A3', 'first']);
    expect(frameRect(t)).toEqual({ x: 20, y: 10, w: 390, h: 277 });
  });

  it('ISO 5457 grid reference: 50 mm fields from the centring marks, 1–8 across, A–F down', () => {
    const t = TEMPLATES['iso-a3'];
    const z = zones(t);
    expect(z.cols.map((c) => c.label)).toEqual(['1', '2', '3', '4', '5', '6', '7', '8']);
    expect(z.rows.map((r) => r.label)).toEqual(['A', 'B', 'C', 'D', 'E', 'F']);
    expect(z.cols.map((c) => c.from)).toEqual([20, 60, 110, 160, 210, 260, 310, 360]);
    expect(z.cols[7].to).toBe(410);
    expect(z.rows.map((r) => r.from)).toEqual([10, 48.5, 98.5, 148.5, 198.5, 248.5]);
    expect(z.rows[5].to).toBe(287);
    // every inner field is 50 mm; the edge fields take the rest
    for (const c of z.cols.slice(1, -1)) expect(c.to - c.from).toBe(50);
    expect(divisions(0, 100, null, null, 4)).toEqual([0, 25, 50, 75, 100]);
  });

  it('centring marks on the axes of symmetry, from the trimmed edge to 5 mm inside the frame', () => {
    const t = TEMPLATES['iso-a3'];
    const m = centringMarks(t);
    expect(m).toContainEqual([210, 0, 210, 15]);
    expect(m).toContainEqual([210, 297, 210, 282]);
    expect(m).toContainEqual([0, 148.5, 25, 148.5]);
    expect(m).toContainEqual([420, 148.5, 405, 148.5]);
  });

  it('ANSI B: 17 × 11 in, third angle, zones numbered right to left and lettered bottom to top', () => {
    const t = TEMPLATES['ansi-b'];
    expect([t.width, t.height, t.projection]).toEqual([431.8, 279.4, 'third']);
    const z = zones(t);
    expect(z.cols.map((c) => c.label)).toEqual(['4', '3', '2', '1']);
    expect(z.rows.map((r) => r.label)).toEqual(['B', 'A']);
    const f = frameRect(t);
    expect(z.cols[0].to - z.cols[0].from).toBeCloseTo(f.w / 4, 9);
  });

  it('ISO 7200 title block: 180 mm wide at the bottom right, every field inside, none overlapping', () => {
    for (const t of Object.values(TEMPLATES)) {
      const f = frameRect(t);
      const tb = titleBlock(t);
      expect(tb.rect).toEqual({ x: f.x + f.w - TITLE_W, y: f.y + f.h - TITLE_H, w: 180, h: 56 });
      const keys = tb.fields.map((x) => x.key);
      for (const k of ['title', 'drawingNo', 'rev', 'sheet', 'scale', 'size', 'units', 'projection', 'material', 'mass', 'drawnBy', 'date', 'status', 'tolerances', 'approved'])
        expect(keys).toContain(k);
      for (const a of tb.fields) expect(inside(a, tb.rect)).toBe(true);
      for (let i = 0; i < tb.fields.length; i++) for (let j = i + 1; j < tb.fields.length; j++) expect(overlap(tb.fields[i], tb.fields[j])).toBeCloseTo(0, 9);
      // the fields tile the block completely
      expect(tb.fields.reduce((s, x) => s + x.w * x.h, 0)).toBeCloseTo(TITLE_W * TITLE_H, 6);
      // identification zone along the bottom edge: drawing number, revision and sheet
      for (const k of ['drawingNo', 'sheet', 'title']) expect(tb.fields.find((x) => x.key === k)!.y).toBeGreaterThanOrEqual(tb.rect.y + 30);
    }
  });

  it('revision block at the top right, parts list directly above the title block (headings next to it, items upward)', () => {
    const t = TEMPLATES['iso-a3'];
    expect(revisionBlock(t, 2)).toEqual({ x: 230, y: 10, w: 180, h: 15 });
    const tb = titleBlock(t).rect;
    const pl = partsList(20, tb, 30);
    expect(pl.rect.y + pl.rect.h).toBeCloseTo(tb.y, 9);
    expect(pl.headY).toBeCloseTo(tb.y - PL_HEAD, 9);
    expect([pl.rowH, pl.shown, pl.overflow]).toEqual([4, 20, 0]);
    expect(pl.rect.h).toBeCloseTo(PL_HEAD + 20 * 4, 9);
    // a long list is squeezed (down to 3 mm rows), then the rest is summarised in one line
    const mid = partsList(60, tb, 30);
    expect(mid.rowH).toBeCloseTo((tb.y - 30 - PL_HEAD) / 60, 9);
    expect([mid.shown, mid.overflow]).toEqual([60, 0]);
    const long = partsList(80, tb, 30);
    expect(long.rowH).toBe(3);
    expect(long.shown + long.overflow).toBe(80);
    expect(long.overflow).toBeGreaterThan(0);
    expect(long.rect.y).toBeGreaterThanOrEqual(30 - 1e-9);
  });

  it('projection symbol: the cone keeps its narrow end left; the circles go right (first angle) or left (third)', () => {
    for (const p of ['first', 'third'] as const) {
      const s = projectionSymbol(p, 0, 0, 22, 10);
      const xs = s.cone.map((q) => q[0]);
      const halfLeft = Math.abs(s.cone[3][1] - s.cone[0][1]) / 2;
      const halfRight = Math.abs(s.cone[2][1] - s.cone[1][1]) / 2;
      expect(halfLeft).toBeLessThan(halfRight);
      expect(s.circles).toHaveLength(2);
      expect(s.circles[0].r).toBeCloseTo(halfRight, 9); // end view of the large end
      expect(s.circles[1].r).toBeCloseTo(halfLeft, 9);
      if (p === 'first') expect(s.circles[0].cx).toBeGreaterThan(Math.max(...xs));
      else expect(s.circles[0].cx).toBeLessThan(Math.min(...xs));
    }
  });

  it('long values are set smaller, then squeezed to fit their field', () => {
    expect(fitText('1:2', 20, 3.5)).toEqual({ size: 3.5, squeeze: false });
    const f = fitText('ENGINEERING-CONSTRAINED — not flight-qualified; not for manufacture without review', 60, 2.2, 1.6);
    expect(f.size).toBe(1.6);
    expect(f.squeeze).toBe(true);
  });
});
