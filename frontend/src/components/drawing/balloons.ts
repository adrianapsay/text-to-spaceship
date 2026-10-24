// V2 WS6 engineering drawings: item references (ISO 6433 balloons). Every BOM item that can be seen is referenced
// once, in the view where it shows the largest visible area (measured on the view's item-id raster, render.ts); the
// balloons stand in lanes left and right of the view, ordered by the heights of the points they refer to so that
// their leaders do not cross; a leader ends in a dot on the item (ISO 128-22: a leader ending inside an outline).

import type { P2, ViewId } from './projection';
import type { Rect } from './sheet';

export interface Visibility {
  view: ViewId;
  /** 3D render id (part id or extra item id) */
  id: string;
  itemNo: number;
  /** visible area in the view (sheet mm²) */
  area: number;
  /** a point well inside the visible region (sheet mm) */
  anchor: P2;
}

export interface Balloon {
  itemNo: number;
  view: ViewId;
  id: string;
  anchor: P2;
  centre: P2;
  r: number;
  /** leader: from the circle toward the anchor */
  leader: [P2, P2];
  side: 'left' | 'right';
}

export const BALLOON_R = 3.5;
export const BALLOON_GAP = 1.2;
/** distance from the view's edge to the near side of a balloon */
export const LANE_GAP = 5;
export const LANE_W = LANE_GAP + 2 * BALLOON_R;

/** Each item once: the visible instance (any view, any of its 3D ids) with the largest area (≥ minArea mm²). */
export function chooseBalloonViews(vis: Visibility[], minArea = 0.25): Map<number, Visibility> {
  const best = new Map<number, Visibility>();
  for (const v of vis) {
    if (!(v.area >= minArea)) continue;
    const b = best.get(v.itemNo);
    if (!b || v.area > b.area + 1e-9 || (Math.abs(v.area - b.area) <= 1e-9 && v.view < b.view)) best.set(v.itemNo, v);
  }
  return best;
}

/** Spread lane positions (desired y, sorted) at least `d` apart inside [lo, hi]; compressed evenly if they do not fit. */
export function spread(desired: number[], d: number, lo: number, hi: number): number[] {
  const n = desired.length;
  if (!n) return [];
  if ((n - 1) * d > hi - lo) return desired.map((_, i) => (n === 1 ? (lo + hi) / 2 : lo + ((hi - lo) * i) / (n - 1)));
  const y = desired.map((v) => Math.min(hi, Math.max(lo, v)));
  for (let i = 1; i < n; i++) y[i] = Math.max(y[i], y[i - 1] + d);
  if (y[n - 1] > hi) {
    y[n - 1] = hi;
    for (let i = n - 2; i >= 0; i--) y[i] = Math.min(y[i], y[i + 1] - d);
  }
  return y;
}

/**
 * Balloons of one view: `view` is the view's rectangle, `lanes` the x of the lane centres (null: no lane on that
 * side), [top, bottom] the vertical range the lanes may use. A point left of `split` (share of the view's width)
 * goes to the left lane: a view with dimensions on its left sends most of its balloons right (split < 0.5), so that
 * fewer leaders cross the dimensions.
 */
export function placeBalloons(
  view: Rect,
  lanes: { left: number | null; right: number | null },
  range: [number, number],
  refs: Visibility[],
  r = BALLOON_R,
  gap = BALLOON_GAP,
  split = 0.5,
): Balloon[] {
  const d = 2 * r + gap;
  const lo = range[0] + r;
  const hi = range[1] - r;
  const cap = Math.max(1, Math.floor((hi - lo) / d) + 1);
  const cx = view.x + view.w * split;
  const side = { left: [] as Visibility[], right: [] as Visibility[] };
  for (const v of refs) {
    const want = lanes.left == null ? 'right' : lanes.right == null ? 'left' : v.anchor[0] < cx ? 'left' : 'right';
    side[want].push(v);
  }
  // a full lane hands the references nearest the middle to the other lane
  for (const [a, b] of [
    ['left', 'right'],
    ['right', 'left'],
  ] as const) {
    if (lanes[b] == null) continue;
    while (side[a].length > cap && side[b].length < cap) {
      side[a].sort((p, q) => Math.abs(p.anchor[0] - cx) - Math.abs(q.anchor[0] - cx));
      side[b].push(side[a].shift()!);
    }
  }
  const out: Balloon[] = [];
  for (const s of ['left', 'right'] as const) {
    const x = lanes[s];
    if (x == null) continue;
    const list = side[s].sort((p, q) => p.anchor[1] - q.anchor[1] || p.itemNo - q.itemNo);
    const ys = spread(
      list.map((v) => v.anchor[1]),
      d,
      lo,
      hi,
    );
    list.forEach((v, i) => {
      const centre: P2 = [x, ys[i]];
      const dx = v.anchor[0] - centre[0];
      const dy = v.anchor[1] - centre[1];
      const l = Math.hypot(dx, dy) || 1;
      out.push({ itemNo: v.itemNo, view: v.view, id: v.id, anchor: v.anchor, centre, r, leader: [[centre[0] + (dx / l) * r, centre[1] + (dy / l) * r], v.anchor], side: s });
    });
  }
  return out;
}
