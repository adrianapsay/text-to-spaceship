// V2 WS6 engineering drawings: the sheet templates, like the default templates of CAD programs. Pure geometry in sheet
// millimetres (origin top-left, y down):
//  * ISO A3 landscape (ISO 5457): 420 × 297 mm, 20 mm filing margin on the left and 10 mm elsewhere, 0.7 mm frame,
//    centring marks, a grid reference of 50 mm fields counted from the centring marks (numbers 1–8 left to right,
//    letters A–F top to bottom), first-angle projection;
//  * ANSI B (ASME Y14.1) 17 × 11 in, third-angle projection; its margins (0.5 in) and zones (4 × 2: numbers right to
//    left, letters bottom to top) follow common CAD templates (ASSUMED, not checked against the standard text);
//  * an ISO 7200-style title block (180 mm wide) at the bottom right, a revision block at the top right and the parts
//    list directly above the title block (ISO 7573: headings next to the title block, items numbered upward).

import type { Projection } from './projection';

export type TemplateId = 'iso-a3' | 'ansi-b';

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface SheetTemplate {
  id: TemplateId;
  label: string;
  /** sheet size name for the title block */
  size: string;
  width: number;
  height: number;
  /** drawing frame inset from the trimmed sheet edge */
  margins: { left: number; right: number; top: number; bottom: number };
  projection: Projection;
  zones: { cols: number; rows: number; colsRightToLeft: boolean; rowsBottomToTop: boolean; fieldFromCentre: number | null };
  /** @page size for printing at true scale */
  page: string;
}

export const TEMPLATES: Record<TemplateId, SheetTemplate> = {
  'iso-a3': {
    id: 'iso-a3',
    label: 'ISO A3 (420 × 297 mm), first-angle projection',
    size: 'A3',
    width: 420,
    height: 297,
    margins: { left: 20, right: 10, top: 10, bottom: 10 },
    projection: 'first',
    zones: { cols: 8, rows: 6, colsRightToLeft: false, rowsBottomToTop: false, fieldFromCentre: 50 },
    page: '420mm 297mm',
  },
  'ansi-b': {
    id: 'ansi-b',
    label: 'ANSI B (17 × 11 in), third-angle projection',
    size: 'B',
    width: 431.8,
    height: 279.4,
    margins: { left: 12.7, right: 12.7, top: 12.7, bottom: 12.7 },
    projection: 'third',
    zones: { cols: 4, rows: 2, colsRightToLeft: true, rowsBottomToTop: true, fieldFromCentre: null },
    page: '17in 11in',
  },
};

export const LINE = { frame: 0.7, wide: 0.35, narrow: 0.18, zone: 0.35, mark: 0.7 } as const;
export const TITLE_W = 180;
export const TITLE_H = 56;
export const ZONE_STRIP = 5; // grid reference marks reach this far from the frame line toward the sheet edge

export function frameRect(t: SheetTemplate): Rect {
  return { x: t.margins.left, y: t.margins.top, w: t.width - t.margins.left - t.margins.right, h: t.height - t.margins.top - t.margins.bottom };
}

export interface Field {
  label: string;
  from: number;
  to: number;
}

/** Boundaries of fields of `step` mm counted from `centre` inside [lo, hi] (ISO 5457), or `n` equal fields. */
export function divisions(lo: number, hi: number, centre: number | null, step: number | null, n: number): number[] {
  if (centre == null || step == null) return Array.from({ length: n + 1 }, (_, i) => lo + ((hi - lo) * i) / n);
  const out = [lo];
  const k0 = Math.ceil((lo - centre) / step + 1e-9);
  for (let k = k0; centre + k * step < hi - 1e-9; k++) if (centre + k * step > lo + 1e-9) out.push(centre + k * step);
  out.push(hi);
  return out;
}

const LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ'; // I and O are not used for zones

/** The grid reference fields along the top / bottom (numbers) and the sides (letters). */
export function zones(t: SheetTemplate): { cols: Field[]; rows: Field[] } {
  const f = frameRect(t);
  const z = t.zones;
  const xs = divisions(f.x, f.x + f.w, z.fieldFromCentre ? t.width / 2 : null, z.fieldFromCentre, z.cols);
  const ys = divisions(f.y, f.y + f.h, z.fieldFromCentre ? t.height / 2 : null, z.fieldFromCentre, z.rows);
  const nc = xs.length - 1;
  const nr = ys.length - 1;
  const cols = xs.slice(0, -1).map((x, i) => ({ label: String(z.colsRightToLeft ? nc - i : i + 1), from: x, to: xs[i + 1] }));
  const rows = ys.slice(0, -1).map((y, i) => ({ label: LETTERS[z.rowsBottomToTop ? nr - 1 - i : i], from: y, to: ys[i + 1] }));
  return { cols, rows };
}

/** Centring marks: from the trimmed edge to 5 mm inside the frame, on the sheet's axes of symmetry. */
export function centringMarks(t: SheetTemplate): [number, number, number, number][] {
  const f = frameRect(t);
  const cx = t.width / 2;
  const cy = t.height / 2;
  return [
    [cx, 0, cx, f.y + 5],
    [cx, t.height, cx, f.y + f.h - 5],
    [0, cy, f.x + 5, cy],
    [t.width, cy, f.x + f.w - 5, cy],
  ];
}

// ------------------------------------------------------------------------------------------------ title block
export interface TitleValues {
  title: string;
  subtitle: string;
  drawingNo: string;
  rev: string;
  date: string;
  sheet: string;
  scale: string;
  size: string;
  units: string;
  mass: string;
  material: string;
  process: string;
  tolerances: string;
  drawnBy: string;
  approved: string;
  reference: string;
  docType: string;
  status: string;
  lang: string;
}

export interface TitleField {
  key: keyof TitleValues | 'projection';
  label: string;
  /** cell rectangle (sheet mm) */
  x: number;
  y: number;
  w: number;
  h: number;
  /** value text height */
  size: number;
  lines?: number;
}

/** ISO 7200-style title block: 180 × 56 mm at the bottom right of the frame, identification zone along the bottom. */
export function titleBlock(t: SheetTemplate): { rect: Rect; fields: TitleField[] } {
  const f = frameRect(t);
  const x = f.x + f.w - TITLE_W;
  const y = f.y + f.h - TITLE_H;
  const c = (key: TitleField['key'], label: string, x0: number, y0: number, w: number, h: number, size: number, lines?: number): TitleField => ({
    key, label, x: x + x0, y: y + y0, w, h, size, lines,
  });
  const fields: TitleField[] = [
    c('drawnBy', 'DRAWN BY', 0, 0, 45, 9, 2.2),
    c('approved', 'CHECKED / APPROVED', 45, 0, 45, 9, 2.2),
    c('reference', 'TECHNICAL REFERENCE', 90, 0, 45, 9, 2.2),
    c('docType', 'DOCUMENT TYPE', 135, 0, 45, 9, 2.5),
    c('scale', 'SCALE', 0, 9, 22, 10, 3.5),
    c('size', 'SIZE', 22, 9, 14, 10, 3.5),
    c('units', 'UNITS', 36, 9, 14, 10, 3.5),
    c('projection', 'PROJECTION', 50, 9, 22, 10, 2.5),
    c('mass', 'MASS', 72, 9, 40, 10, 2.5),
    c('tolerances', 'GENERAL TOLERANCES', 112, 9, 68, 10, 2.5),
    c('material', 'MATERIAL', 0, 19, 112, 9, 2.2),
    c('process', 'PROCESS', 112, 19, 68, 9, 2.2),
    c('status', 'DOCUMENT STATUS', 0, 28, 180, 7, 2.2),
    c('title', 'TITLE', 0, 35, 100, 21, 3.5, 2),
    c('drawingNo', 'DRAWING NO.', 100, 35, 50, 11, 3.5),
    c('date', 'DATE OF ISSUE', 100, 46, 50, 10, 2.5),
    c('rev', 'REV', 150, 35, 15, 11, 3.5),
    c('lang', 'LANG', 150, 46, 15, 10, 2.5),
    c('sheet', 'SHEET', 165, 35, 15, 21, 3.5),
  ];
  return { rect: { x, y, w: TITLE_W, h: TITLE_H }, fields };
}

// ------------------------------------------------------------------------------------------------ revision block
export interface Revision {
  rev: string;
  description: string;
  date: string;
  approved: string;
}

export const REV_COLS = [
  { key: 'rev', label: 'REV', w: 12 },
  { key: 'description', label: 'DESCRIPTION', w: 108 },
  { key: 'date', label: 'DATE', w: 30 },
  { key: 'approved', label: 'APPROVED', w: 30 },
] as const;
export const REV_ROW = 5;

export function revisionBlock(t: SheetTemplate, rows: number): Rect {
  const f = frameRect(t);
  return { x: f.x + f.w - TITLE_W, y: f.y, w: TITLE_W, h: REV_ROW * (rows + 1) };
}

// ------------------------------------------------------------------------------------------------ parts list
export const PL_COLS = [
  { key: 'item', label: 'ITEM', w: 11, align: 'middle' },
  { key: 'qty', label: 'QTY', w: 10, align: 'middle' },
  { key: 'name', label: 'NAME', w: 66, align: 'start' },
  { key: 'material', label: 'MATERIAL', w: 55, align: 'start' },
  { key: 'mass', label: 'MASS g', w: 18, align: 'end' },
  { key: 'source', label: 'SOURCE', w: 20, align: 'start' },
] as const;
export const PL_HEAD = 5;

export interface PartsListGeometry {
  rect: Rect;
  rowH: number;
  /** rows shown (the rest: one "… more" line) */
  shown: number;
  overflow: number;
  /** y of the top of the header row */
  headY: number;
}

/** Parts list directly above the title block: header next to the title block, item 1 just above it, upward. Rows
 * are 4 mm high, squeezed to at least 3 mm when the list is long; beyond that the rest is summarised in one line. */
export function partsList(rows: number, above: Rect, minTop: number): PartsListGeometry {
  const avail = above.y - minTop - PL_HEAD;
  let rowH = 4;
  if (rows * rowH > avail) rowH = Math.max(3, avail / Math.max(rows, 1));
  let shown = rows;
  let overflow = 0;
  if (rows * rowH > avail) {
    shown = Math.max(0, Math.floor(avail / rowH) - 1);
    overflow = rows - shown;
  }
  const lines = shown + (overflow ? 1 : 0);
  const h = PL_HEAD + lines * rowH;
  return { rect: { x: above.x, y: above.y - h, w: TITLE_W, h }, rowH, shown, overflow, headY: above.y - PL_HEAD };
}

// ------------------------------------------------------------------------------------------------ projection symbol
export interface ProjectionSymbol {
  /** the truncated cone seen from the side: a trapezoid, narrow end to the left */
  cone: [number, number][];
  /** its end view: two concentric circles */
  circles: { cx: number; cy: number; r: number }[];
  /** centre lines */
  centre: [number, number, number, number][];
}

/**
 * ISO 5456-2 projection symbol inside a w × h box at (x, y). First angle: the end view (two circles) to the right of
 * the cone; third angle: to its left. The cone's narrow end points to the circles in third angle and away from them
 * in first angle, so the circles are the view of its narrow end in both (two visible circles).
 */
export function projectionSymbol(p: Projection, x: number, y: number, w: number, h: number): ProjectionSymbol {
  const d = Math.min(h * 0.6, w / 3.2); // large diameter
  const cy = y + h / 2;
  const coneW = d;
  const gap = d * 0.35;
  const total = coneW + gap + d;
  const x0 = x + (w - total) / 2;
  const coneX = p === 'first' ? x0 : x0 + d + gap;
  const circX = p === 'first' ? x0 + coneW + gap + d / 2 : x0 + d / 2;
  const cone: [number, number][] = [
    [coneX, cy - d / 4],
    [coneX + coneW, cy - d / 2],
    [coneX + coneW, cy + d / 2],
    [coneX, cy + d / 4],
  ];
  const circles = [
    { cx: circX, cy, r: d / 2 },
    { cx: circX, cy, r: d / 4 },
  ];
  const o = d * 0.15;
  const centre: [number, number, number, number][] = [
    [x0 - o, cy, x0 + total + o, cy],
    [circX, cy - d / 2 - o, circX, cy + d / 2 + o],
  ];
  return { cone, circles, centre };
}

/** Approximate width of a text in a sans-serif font (sheet mm): for fitting values into title block cells. */
export function textWidth(s: string, size: number): number {
  let w = 0;
  for (const ch of s) w += /[ilI.,:;'|!()[\]]/.test(ch) ? 0.3 : /[mwMW@%]/.test(ch) ? 0.85 : /[A-Z0-9]/.test(ch) ? 0.66 : 0.53;
  return w * size;
}

/** The text size that fits `s` in `width` (down to `min`), and whether it still overflows (then squeeze it). */
export function fitText(s: string, width: number, size: number, min = 1.6): { size: number; squeeze: boolean } {
  let z = size;
  while (z > min && textWidth(s, z) > width) z = Math.max(min, z - 0.1);
  return { size: Math.round(z * 100) / 100, squeeze: textWidth(s, z) > width };
}
