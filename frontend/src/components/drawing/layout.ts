// V2 WS6 engineering drawings: arranging the views on a sheet. The front, top and side views keep their projection
// relationship (first angle: top view below the front view, the view from the left to its right; third angle: top
// view above, the view from the right to its right) at the largest ISO 5455 scale that fits the space left of the
// title-block column; the isometric view goes where the largest scale fits (the free quadrant of the group, the space
// beside it, or the column above the parts list), and is labelled with its own scale when that differs.

import { chooseScale, placeView, sideView, VIEWS, type Box3, type PlacedView, type ViewId } from './projection';
import { frameRect, partsList, revisionBlock, titleBlock, TITLE_W, type PartsListGeometry, type Rect, type SheetTemplate } from './sheet';

/** Space kept around a view (sheet mm): dimensions, balloons, the view label. */
export interface Margins {
  l: number;
  r: number;
  t: number;
  b: number;
}

export interface ViewSlot extends PlacedView {
  view: ViewId;
  label: string;
  margins: Margins;
  /** the view's scale differs from the sheet's main scale (labelled) */
  ownScale: boolean;
}

export interface SheetLayout {
  views: ViewSlot[];
  scale: number;
  title: Rect;
  revisions: Rect;
  parts: PartsListGeometry | null;
  notes: Rect | null;
  /** the area left of the title-block column */
  main: Rect;
  /** the column above the parts list / notes */
  column: Rect;
}

export const GAP = 4;
export const PAD = 4;

const fits = (w: number, h: number, r: Rect) => w <= r.w + 1e-9 && h <= r.h + 1e-9;

export interface ArrangeInput {
  template: SheetTemplate;
  box: Box3;
  /** parts list rows (assembly) — or null for none */
  partsRows: number | null;
  /** height of a notes block above the title block (detail sheets) */
  notesH?: number;
  revRows: number;
  margins: (v: ViewId) => Margins;
  /** largest scale to try (detail parts may be enlarged) */
  maxScale?: number;
}

/** The three orthographic views as a group at scale s: sizes and the offsets of each view's box inside the group. */
function orthoGroup(box: Box3, s: number, p: SheetTemplate['projection'], m: (v: ViewId) => Margins) {
  const side = sideView(p);
  const F = placeView(VIEWS.front, box, s, 0, 0);
  const T = placeView(VIEWS.top, box, s, 0, 0);
  const S = placeView(VIEWS[side], box, s, 0, 0);
  const mf = m('front');
  const mt = m('top');
  const ms = m(side);
  const left = Math.max(mf.l, mt.l);
  const col1 = left + Math.max(F.w, T.w) + Math.max(mf.r, mt.r);
  const col2 = ms.l + S.w + ms.r;
  const rowFS = { top: Math.max(mf.t, ms.t), h: Math.max(F.h, S.h), bottom: Math.max(mf.b, ms.b) };
  const rowT = { top: mt.t, h: T.h, bottom: mt.b };
  const hFS = rowFS.top + rowFS.h + rowFS.bottom;
  const hT = rowT.top + rowT.h + rowT.bottom;
  const w = col1 + GAP + col2;
  const h = hFS + GAP + hT;
  // offsets of each view's box (top-left) inside the group
  const fsY = p === 'first' ? rowFS.top : hT + GAP + rowFS.top;
  const tY = p === 'first' ? hFS + GAP + rowT.top : rowT.top;
  const pos: Record<string, [number, number]> = {
    front: [left, fsY],
    top: [left, tY],
    [side]: [col1 + GAP + ms.l, fsY],
  };
  // the free quadrant: below the side view (first angle) or above it (third angle)
  const quad: Rect = { x: col1 + GAP, y: p === 'first' ? hFS + GAP : 0, w: col2, h: hT };
  return { w, h, pos, side, quad, margins: { front: mf, top: mt, [side]: ms } as Record<string, Margins>, sizes: { F, T, S } };
}

export function arrangeViews(inp: ArrangeInput): SheetLayout | null {
  const t = inp.template;
  const f = frameRect(t);
  const title = titleBlock(t).rect;
  const revisions = revisionBlock(t, inp.revRows);
  const columnX = f.x + f.w - TITLE_W;
  const parts = inp.partsRows != null ? partsList(inp.partsRows, title, revisions.y + revisions.h + PAD) : null;
  const notes = inp.notesH ? { x: columnX, y: title.y - inp.notesH, w: TITLE_W, h: inp.notesH } : null;
  const columnBottom = parts ? parts.rect.y : notes ? notes.y : title.y;
  const main: Rect = { x: f.x + PAD, y: f.y + PAD, w: columnX - f.x - 2 * PAD, h: f.h - 2 * PAD };
  const column: Rect = { x: columnX + PAD, y: revisions.y + revisions.h + PAD, w: TITLE_W - 2 * PAD, h: columnBottom - revisions.y - revisions.h - 2 * PAD };
  const s = chooseScale((sc) => {
    const g = orthoGroup(inp.box, sc, t.projection, inp.margins);
    return fits(g.w, g.h, main);
  }, inp.maxScale ?? 50);
  if (s == null) return null;
  const g = orthoGroup(inp.box, s, t.projection, inp.margins);
  const gx = main.x + (main.w - g.w) / 2;
  const gy = main.y + (main.h - g.h) / 2;
  const views: ViewSlot[] = [];
  for (const id of ['front', 'top', g.side] as ViewId[]) {
    const [ox, oy] = g.pos[id];
    const v = placeView(VIEWS[id], inp.box, s, gx + ox, gy + oy);
    views.push({ ...v, view: id, label: VIEWS[id].label, margins: g.margins[id], ownScale: false });
  }
  // isometric view: the largest scale ≤ the main scale over the candidate places
  const mi = inp.margins('iso');
  const slots: Rect[] = [
    { x: gx + g.quad.x, y: gy + g.quad.y, w: g.quad.w, h: g.quad.h },
    { x: gx + g.w + GAP, y: main.y, w: main.x + main.w - (gx + g.w + GAP), h: main.h },
    { x: main.x, y: main.y, w: gx - GAP - main.x, h: main.h },
    column,
  ].filter((r) => r.w > 10 && r.h > 10);
  let best: { s: number; slot: Rect } | null = null;
  for (const slot of slots) {
    const si = chooseScale((sc) => {
      const v = placeView(VIEWS.iso, inp.box, sc, 0, 0);
      return fits(mi.l + v.w + mi.r, mi.t + v.h + mi.b, slot);
    }, s);
    if (si != null && (!best || si > best.s + 1e-12)) best = { s: si, slot };
  }
  if (best) {
    const v = placeView(VIEWS.iso, inp.box, best.s, 0, 0);
    const x = best.slot.x + (best.slot.w - (mi.l + v.w + mi.r)) / 2 + mi.l;
    const y = best.slot.y + (best.slot.h - (mi.t + v.h + mi.b)) / 2 + mi.t;
    views.push({ ...placeView(VIEWS.iso, inp.box, best.s, x, y), view: 'iso', label: VIEWS.iso.label, margins: mi, ownScale: Math.abs(best.s - s) > 1e-12 });
  }
  return { views, scale: s, title, revisions, parts, notes, main, column };
}
