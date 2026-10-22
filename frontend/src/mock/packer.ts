// MOCK placeholder "search": a seeded randomised layer packer over AABB footprints (same idea as
// scripts/build-mock-fixtures.mjs). It produces AABB-disjoint layouts, which is a valid (if very loose) proof of
// non-overlap for the Stage 1 box. It is NOT an optimiser and its layouts are labelled MOCK everywhere.

import type { Mat3, Part, Pose, Vec3 } from '../api/types';

const GAP = 0.005;

export function rotExtents(R: Mat3, e: Vec3): Vec3 {
  return [0, 1, 2].map((r) => Math.abs(R[r][0]) * e[0] + Math.abs(R[r][1]) * e[1] + Math.abs(R[r][2]) * e[2]) as Vec3;
}

export function lcg(seed: number): () => number {
  let s = seed >>> 0 || 1;
  return () => (s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296;
}

interface FreeRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

function tryInsert(free: FreeRect[], w: number, h: number): { x: number; y: number } | null {
  let best: { x: number; y: number; s: number } | null = null;
  for (const r of free) {
    if (w + GAP <= r.w + 1e-9 && h + GAP <= r.h + 1e-9) {
      const s = Math.min(r.w - w, r.h - h);
      if (!best || s < best.s) best = { x: r.x, y: r.y, s };
    }
  }
  return best;
}

function place(free: FreeRect[], x: number, y: number, w: number, h: number): FreeRect[] {
  const W = w + GAP;
  const H = h + GAP;
  const out: FreeRect[] = [];
  for (const r of free) {
    if (x >= r.x + r.w || x + W <= r.x || y >= r.y + r.h || y + H <= r.y) {
      out.push(r);
      continue;
    }
    if (x > r.x) out.push({ x: r.x, y: r.y, w: x - r.x, h: r.h });
    if (x + W < r.x + r.w) out.push({ x: x + W, y: r.y, w: r.x + r.w - x - W, h: r.h });
    if (y > r.y) out.push({ x: r.x, y: r.y, w: r.w, h: y - r.y });
    if (y + H < r.y + r.h) out.push({ x: r.x, y: y + H, w: r.w, h: r.y + r.h - y - H });
  }
  return out.filter(
    (a, i) =>
      !out.some(
        (b, j) =>
          j !== i &&
          a.x >= b.x &&
          a.y >= b.y &&
          a.x + a.w <= b.x + b.w &&
          a.y + a.h <= b.y + b.h &&
          (j < i || a.x !== b.x || a.y !== b.y || a.w !== b.w || a.h !== b.h),
      ),
  );
}

export interface PackResult {
  poses: Pose[];
  length_mm: number;
  fits: boolean;
}

/**
 * One randomised attempt. `bias` in [0,1] mixes "deepest first" ordering with random order. `flip` mirrors the
 * stack so heavy layers end up at the other end (gives the mock some COM variety).
 */
export function packOnce(
  parts: Part[],
  rotations: Mat3[],
  enclosure: { x: number; y: number; z: number },
  seed: number,
  opts: { flip?: boolean; centreXY?: boolean } = {},
): PackResult {
  const rnd = lcg(seed);
  const items = parts.map((p) => {
    const opts2 = rotations
      .map((R, o) => ({ o, e: rotExtents(R, p.extents_mm) }))
      .filter((c) => c.e[0] <= enclosure.x && c.e[1] <= enclosure.y && (p.allowed_orients.length === 0 || p.allowed_orients.includes(c.o)));
    const minZ = opts2.reduce((b, c) => (!b || c.e[2] < b.e[2] ? c : b), null as null | { o: number; e: Vec3 });
    return { p, opts: opts2, minZ };
  });
  const usable = items.filter((it) => it.minZ);
  const order = usable.map((it) => ({ it, r: rnd() })).sort((a, b) => a.r - b.r).map((x) => x.it);
  type Placed = { id: string; o: number; e: Vec3; x: number; y: number };
  const layers: { h: number; free: FreeRect[]; items: Placed[] }[] = [];
  for (const it of order) {
    let done = false;
    for (const L of layers) {
      const fit = it.opts.filter((c) => c.e[2] <= L.h + 1e-9).sort((a, b) => a.e[0] * a.e[1] - b.e[0] * b.e[1]);
      for (const c of fit) {
        const pos = tryInsert(L.free, c.e[0], c.e[1]);
        if (pos) {
          L.free = place(L.free, pos.x, pos.y, c.e[0], c.e[1]);
          L.items.push({ id: it.p.id, o: c.o, e: c.e, x: pos.x + GAP, y: pos.y + GAP });
          done = true;
          break;
        }
      }
      if (done) break;
    }
    if (!done) {
      const c = rnd() < 0.5 ? it.minZ! : it.opts[Math.floor(rnd() * it.opts.length)];
      const L = { h: c.e[2], free: [{ x: 0, y: 0, w: enclosure.x, h: enclosure.y }], items: [] as Placed[] };
      const pos = tryInsert(L.free, c.e[0], c.e[1]);
      if (!pos) continue;
      L.free = place(L.free, pos.x, pos.y, c.e[0], c.e[1]);
      L.items.push({ id: it.p.id, o: c.o, e: c.e, x: pos.x + GAP, y: pos.y + GAP });
      layers.push(L);
    }
  }
  if (opts.flip) layers.reverse();
  const z0 = -enclosure.z / 2;
  let z = z0;
  const poses: Pose[] = [];
  for (const L of layers) {
    // optionally centre the layer's occupied footprint in XY
    let ox = 0;
    let oy = 0;
    if (opts.centreXY && L.items.length) {
      const maxX = Math.max(...L.items.map((i) => i.x + i.e[0]));
      const maxY = Math.max(...L.items.map((i) => i.y + i.e[1]));
      ox = (enclosure.x - maxX) / 2;
      oy = (enclosure.y - maxY) / 2;
    }
    for (const it of L.items) {
      const cx = -enclosure.x / 2 + ox + it.x + it.e[0] / 2;
      const cy = -enclosure.y / 2 + oy + it.y + it.e[1] / 2;
      const cz = z + GAP + it.e[2] / 2;
      poses.push({ part_id: it.id, orient: it.o, t_um: [Math.round(cx * 1000), Math.round(cy * 1000), Math.round(cz * 1000)] });
    }
    z += GAP + L.h;
  }
  poses.sort((a, b) => (a.part_id < b.part_id ? -1 : a.part_id > b.part_id ? 1 : 0));
  return { poses, length_mm: z - z0, fits: z - z0 <= enclosure.z + 1e-9 && usable.length === parts.length };
}

export interface AabbCheck {
  ok: boolean;
  pairs: number;
  containment: { part_id: string; min: Vec3; max: Vec3; margin_mm: Vec3 }[];
  separations: { a: string; b: string; axis: 0 | 1 | 2; gap_mm: number }[];
  failure?: string;
}

/** The MOCK validator: AABBs inside the box and pairwise disjoint (gap ≥ 0 on at least one axis). */
export function aabbCheck(parts: Record<string, Part>, poses: Pose[], rotations: Mat3[], half: Vec3): AabbCheck {
  const boxes = poses.map((ps) => {
    const p = parts[ps.part_id];
    const e = rotExtents(rotations[ps.orient], p.extents_mm);
    const c = ps.t_um.map((v) => v / 1000) as Vec3;
    return { id: ps.part_id, min: c.map((v, k) => v - e[k] / 2) as Vec3, max: c.map((v, k) => v + e[k] / 2) as Vec3 };
  });
  const containment = boxes.map((b) => ({
    part_id: b.id,
    min: b.min,
    max: b.max,
    margin_mm: [0, 1, 2].map((k) => Math.min(b.min[k] + half[k], half[k] - b.max[k])) as Vec3,
  }));
  for (const c of containment)
    if (c.margin_mm.some((m) => m < -1e-9)) return { ok: false, pairs: 0, containment, separations: [], failure: `${c.part_id} outside the enclosure` };
  const separations: AabbCheck['separations'] = [];
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i];
      const b = boxes[j];
      let best: { axis: 0 | 1 | 2; gap: number } | null = null;
      for (const k of [0, 1, 2] as const) {
        const gap = Math.max(b.min[k] - a.max[k], a.min[k] - b.max[k]);
        if (!best || gap > best.gap) best = { axis: k, gap };
      }
      if (!best || best.gap < 0) return { ok: false, pairs: separations.length, containment, separations, failure: `AABB overlap ${a.id} / ${b.id}` };
      separations.push({ a: a.id, b: b.id, axis: best.axis, gap_mm: best.gap });
    }
  return { ok: true, pairs: separations.length, containment, separations };
}
