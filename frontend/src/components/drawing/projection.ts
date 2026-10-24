// V2 WS6 engineering drawings: orthographic / isometric view definitions, the projection from model millimetres to
// sheet millimetres, standard drawing scales (ISO 5455) and linear dimensions (ISO 129-1 style). Pure functions: the
// raster views (render.ts) and every vector on the sheet (outlines, dimensions, centre lines, balloons) use the same
// projection, so they line up.

export type V3 = [number, number, number];
export type P2 = [number, number];
export type Projection = 'first' | 'third';
export type ViewId = 'front' | 'top' | 'right' | 'left' | 'iso';

export interface ViewBasis {
  id: ViewId;
  label: string;
  /** looking direction (from the eye into the scene), unit */
  dir: V3;
  /** sheet x axis (to the right) in model coordinates, unit */
  right: V3;
  /** sheet up axis in model coordinates, unit (sheet y grows downward) */
  up: V3;
}

export const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export const norm = (a: V3): V3 => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};
const neg = (a: V3): V3 => [-a[0], -a[1], -a[2]];

/** The basis a three.js camera looking along `dir` with `up` gets (Object3D.lookAt): right = up × (−dir). */
export function basis(id: ViewId, label: string, dir: V3, up: V3): ViewBasis {
  const d = norm(dir);
  const right = norm(cross(up, neg(d)));
  return { id, label, dir: d, right, up: cross(neg(d), right) };
}

// The app's 3D views are Z-up with the front seen from −Y (viewport key 1): the same here.
export const VIEWS: Record<ViewId, ViewBasis> = {
  front: basis('front', 'FRONT VIEW', [0, 1, 0], [0, 0, 1]),
  top: basis('top', 'TOP VIEW', [0, 0, -1], [0, 1, 0]),
  right: basis('right', 'RIGHT VIEW', [-1, 0, 0], [0, 0, 1]),
  left: basis('left', 'LEFT VIEW', [1, 0, 0], [0, 0, 1]),
  // true isometric seen from the right-front-top corner (like the 3D view's start): Z up, X right-down and Y right-up
  // at 30° to the horizontal; the front (−Y), right (+X) and top (+Z) faces are seen
  iso: basis('iso', 'ISOMETRIC VIEW', [-1, 1, -1], [0, 0, 1]),
};

/** The side view drawn to the right of the front view: seen from the left in first-angle projection (ISO E), from the
 * right in third-angle projection. The top view is the plan seen from above in both; first angle places it below the
 * front view, third angle above. */
export function sideView(p: Projection): ViewId {
  return p === 'first' ? 'left' : 'right';
}

/** Model point → (u, v) along the view's right / up axes, relative to `centre` (model mm). */
export function toUV(b: ViewBasis, p: V3, centre: V3): P2 {
  const d: V3 = [p[0] - centre[0], p[1] - centre[1], p[2] - centre[2]];
  return [dot(d, b.right), dot(d, b.up)];
}

export interface Box3 {
  min: V3;
  max: V3;
}

export function boxCorners(b: Box3): V3[] {
  const out: V3[] = [];
  for (const x of [b.min[0], b.max[0]]) for (const y of [b.min[1], b.max[1]]) for (const z of [b.min[2], b.max[2]]) out.push([x, y, z]);
  return out;
}

export function boxCentre(b: Box3): V3 {
  return [(b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2];
}

/** Extent of a model box in a view (model mm): u range and v range about the box centre. */
export function viewExtent(b: ViewBasis, box: Box3): { u0: number; u1: number; v0: number; v1: number; w: number; h: number } {
  const c = boxCentre(box);
  let u0 = Infinity;
  let u1 = -Infinity;
  let v0 = Infinity;
  let v1 = -Infinity;
  for (const p of boxCorners(box)) {
    const [u, v] = toUV(b, p, c);
    u0 = Math.min(u0, u);
    u1 = Math.max(u1, u);
    v0 = Math.min(v0, v);
    v1 = Math.max(v1, v);
  }
  return { u0, u1, v0, v1, w: u1 - u0, h: v1 - v0 };
}

/** A view placed on the sheet: model box `box` seen in `basis`, drawn at `scale` (sheet mm per model mm) with the
 * projected box occupying the sheet rectangle (x, y, w, h). */
export interface PlacedView {
  basis: ViewBasis;
  box: Box3;
  scale: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export function placeView(b: ViewBasis, box: Box3, scale: number, x: number, y: number): PlacedView {
  const e = viewExtent(b, box);
  return { basis: b, box, scale, x, y, w: e.w * scale, h: e.h * scale };
}

/** Model point → sheet point (mm, y down) for a placed view. */
export function project(v: PlacedView, p: V3): P2 {
  const e = viewExtent(v.basis, v.box);
  const [u, uv] = toUV(v.basis, p, boxCentre(v.box));
  return [v.x + (u - e.u0) * v.scale, v.y + (e.v1 - uv) * v.scale];
}

/** Sheet point → the model ray's (u, v) in the view (inverse of project for the in-plane part). */
export function unproject(v: PlacedView, q: P2): P2 {
  const e = viewExtent(v.basis, v.box);
  return [e.u0 + (q[0] - v.x) / v.scale, e.v1 - (q[1] - v.y) / v.scale];
}

/** The 12 edges of a box projected into a view (sheet segments). */
export function boxEdges(v: PlacedView, box: Box3): [P2, P2][] {
  const c = boxCorners(box); // index bits: x (4), y (2), z (1)
  const out: [P2, P2][] = [];
  for (let i = 0; i < 8; i++)
    for (const bit of [4, 2, 1]) {
      const j = i | bit;
      if (j !== i) out.push([project(v, c[i]), project(v, c[j])]);
    }
  return out;
}

// --------------------------------------------------------------------------------------------- scales (ISO 5455)
/** Recommended scales of ISO 5455 (sheet length / true length), largest first. */
export const STANDARD_SCALES = [50, 20, 10, 5, 2, 1, 1 / 2, 1 / 5, 1 / 10, 1 / 20, 1 / 50, 1 / 100, 1 / 200];

export function scaleLabel(s: number): string {
  if (s >= 1) return `${Math.round(s)}:1`;
  return `1:${Math.round(1 / s)}`;
}

/** The largest standard scale ≤ `max` for which `fits(scale)` holds (null if none does). */
export function chooseScale(fits: (s: number) => boolean, max = 50): number | null {
  for (const s of STANDARD_SCALES) if (s <= max + 1e-12 && fits(s)) return s;
  return null;
}

// --------------------------------------------------------------------------------------------- dimensions (ISO 129-1)
export interface DimStyle {
  /** gap between the feature and the extension line */
  gap: number;
  /** extension line beyond the dimension line */
  overshoot: number;
  /** arrowhead length and half-width */
  arrow: number;
  arrowHalf: number;
  /** text height and its distance from the dimension line */
  text: number;
  textGap: number;
}

export const DIM_STYLE: DimStyle = { gap: 1, overshoot: 2, arrow: 3, arrowHalf: 0.5, text: 3.5, textGap: 1 };

export interface LinearDim {
  /** extension lines (sheet segments) */
  ext: [P2, P2][];
  /** the dimension line */
  line: [P2, P2];
  /** filled arrowheads: tip, and the two back corners */
  arrows: [P2, P2, P2][];
  /** value text: anchor (middle), rotation in degrees (−90 for vertical dimensions: read from the right) */
  text: { x: number; y: number; rotate: number; value: string };
  /** sheet length of the dimension line */
  length: number;
}

/** Format a dimension value: millimetres, at most one decimal, no trailing zero ("100", "340.5"). Reference
 * dimensions (not toleranced, e.g. the used length) go in parentheses. */
export function dimText(value: number, reference = false): string {
  const t = String(Number(value.toFixed(1)));
  return reference ? `(${t})` : t;
}

/**
 * Linear dimension between feature points `a` and `b` (sheet mm) measured along `axis` ('x' horizontal, 'y'
 * vertical), with the dimension line `offset` mm from the features toward `side` (+1: right / down, −1: left / up).
 * The value is the model length (given), not the sheet length.
 */
export function linearDim(a: P2, b: P2, axis: 'x' | 'y', side: 1 | -1, offset: number, value: string, st: DimStyle = DIM_STYLE): LinearDim {
  const k = axis === 'x' ? 1 : 0; // the coordinate perpendicular to the measured direction: y for 'x' dims
  const base = side > 0 ? Math.max(a[k], b[k]) : Math.min(a[k], b[k]);
  const at = base + side * offset;
  const pt = (p: P2, c: number): P2 => (axis === 'x' ? [p[0], c] : [c, p[1]]);
  const q1 = pt(a, at);
  const q2 = pt(b, at);
  const ext: [P2, P2][] = [a, b].map((p) => [pt(p, p[k] + side * st.gap), pt(p, at + side * st.overshoot)] as [P2, P2]);
  const arrows: [P2, P2, P2][] = [];
  const along = axis === 'x' ? 0 : 1;
  const lo = q1[along] <= q2[along] ? q1 : q2;
  const hi = lo === q1 ? q2 : q1;
  for (const [tip, dirn] of [
    [lo, 1],
    [hi, -1],
  ] as [P2, number][]) {
    const back = tip[along] + dirn * st.arrow;
    if (axis === 'x') arrows.push([tip, [back, tip[1] - st.arrowHalf], [back, tip[1] + st.arrowHalf]]);
    else arrows.push([tip, [tip[0] - st.arrowHalf, back], [tip[0] + st.arrowHalf, back]]);
  }
  const mid: P2 = [(q1[0] + q2[0]) / 2, (q1[1] + q2[1]) / 2];
  const text =
    axis === 'x'
      ? { x: mid[0], y: mid[1] - st.textGap, rotate: 0, value }
      : { x: mid[0] - st.textGap, y: mid[1], rotate: -90, value };
  return { ext, line: [q1, q2], arrows, text, length: Math.hypot(q2[0] - q1[0], q2[1] - q1[1]) };
}
