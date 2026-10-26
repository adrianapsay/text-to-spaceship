// V3 CubeSat Builder — an illustrative arrangement of a design's parts for the 3D preview (not the optimiser's
// packing). Internal parts are bounding boxes stacked along the long axis (Z) in lanes across the width; external
// parts sit on the faces: body solar panels on the long faces, deployable wings beside them, antennas and sensors on
// the end faces. Parts whose size is not published are drawn as small dashed cubes and listed.
import type { Analysis, PickItem } from './analysisTypes';

export interface PlacedBox {
  id: string;
  name: string;
  slot: string;
  /** centre (mm), satellite frame: Z along the long axis, −Z the nadir (camera) end */
  center: [number, number, number];
  size: [number, number, number];
  external: boolean;
  /** drawn without a published size (a 20 mm stand-in) */
  unsized: boolean;
  overflow: boolean;
}

export const OUTER_MM: Record<number, [number, number, number]> = {
  1: [100, 100, 113.5],
  1.5: [100, 100, 170.2],
  2: [100, 100, 227],
  3: [100, 100, 340.5],
  6: [226.3, 100, 366],
  12: [226.3, 226.3, 366],
};
const WALL = 2;
const GAP = 2;
const STANDIN = 20;

/** Orient a box so it fits the cross-section with its largest face across, if it can. */
function orient(d: number[], w: number, h: number): [number, number, number] {
  const perms: [number, number, number][] = [
    [d[0], d[1], d[2]], [d[0], d[2], d[1]], [d[1], d[0], d[2]], [d[1], d[2], d[0]], [d[2], d[0], d[1]], [d[2], d[1], d[0]],
  ];
  const fit = perms.filter((p) => p[0] <= w + 1e-6 && p[1] <= h + 1e-6);
  if (!fit.length) return perms.sort((a, b) => a[2] - b[2])[0];
  return fit.sort((a, b) => a[2] - b[2])[0];              // shortest along Z: thin parts lie flat
}

/** The catalog id of a placed box (boxes of one part are `<id>#<n>`). */
export const componentOf = (b: PlacedBox) => b.id.split('#')[0];

/** A model with more triangles than this stays a box in the preview (the browser would stall on it). */
export const MESH_MAX_FACES = 400_000;

type Geometry = NonNullable<Analysis['geometry']>[string];

/**
 * How each placed part is drawn: with its imported model (the maker's CAD or a reconstruction) when it has one light
 * enough for the browser, else as its box. Body solar panels are drawn as panels whatever their geometry.
 */
export function drawPlan(boxes: PlacedBox[], geometry: Analysis['geometry']): { box: PlacedBox; cid: string; model: Geometry | null; heavy: boolean }[] {
  return boxes.map((b) => {
    const cid = componentOf(b);
    const g = geometry?.[cid];
    const imported = !!g && (g.origin === 'manufacturer' || g.origin === 'reconstructed') && b.slot !== 'solar' && !b.unsized;
    const heavy = imported && (g.faces ?? 0) > MESH_MAX_FACES;
    return { box: b, cid, model: imported && !heavy ? g : null, heavy };
  });
}

/**
 * The rotation (3×3, rows = world axes) that turns a part's mesh so its longest side lies along the box's longest side,
 * and so on: the maker's model drawn where the arrangement put the part's box. Always a turn, never a mirror (when the
 * axis swap alone would mirror the part, the shortest axis is reversed).
 */
export function axisTurn(extents: number[], size: number[]): number[][] {
  const byE = [0, 1, 2].sort((i, j) => extents[j] - extents[i]);
  const byS = [0, 1, 2].sort((i, j) => size[j] - size[i]);
  const m = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  for (let k = 0; k < 3; k++) m[byS[k]][byE[k]] = 1;
  const det =
    m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
  if (det < 0) m[byS[2]] = m[byS[2]].map((v) => (v ? -v : 0));
  return m;
}

export function arrange(a: Analysis): { outer: [number, number, number]; boxes: PlacedBox[] } {
  const outer = OUTER_MM[a.size_u] ?? OUTER_MM[3];
  const inner: [number, number, number] = [outer[0] - 2 * WALL, outer[1] - 2 * WALL, outer[2] - 2 * WALL];
  const internal: { it: PickItem; slot: string }[] = [];
  const external: { it: PickItem; slot: string }[] = [];
  for (const s of a.slots) {
    const p = a.picks[s.id];
    if (!p || p.place === 'frame') continue;
    for (const it of p.items) {
      for (let k = 0; k < Math.min(it.qty, 12); k++) (p.place === 'external' ? external : internal).push({ it: { ...it, id: `${it.id}#${k}` }, slot: s.id });
    }
  }
  const vol = (it: PickItem) => (it.dims_mm ? it.dims_mm[0] * it.dims_mm[1] * it.dims_mm[2] : 0);
  internal.sort((x, y) => vol(y.it) - vol(x.it));
  // lanes across X: one per ~100 mm of width
  const lanes = Math.max(1, Math.floor(inner[0] / 100));
  const laneW = inner[0] / lanes;
  const z = new Array(lanes).fill(-inner[2] / 2);
  const boxes: PlacedBox[] = [];
  for (const { it, slot } of internal) {
    const unsized = !it.dims_mm;
    const d = it.dims_mm ?? [STANDIN, STANDIN, STANDIN];
    let size = orient(d, laneW, inner[1]);
    let x = 0;
    let z0: number;
    if (lanes > 1 && size[0] <= laneW + 1e-6 && size[1] <= inner[1] + 1e-6) {
      const lane = z.indexOf(Math.min(...z));             // the lowest lane takes the next part
      x = -inner[0] / 2 + laneW * (lane + 0.5);
      z0 = z[lane];
      z[lane] = z0 + size[2] + GAP;
    } else {
      size = orient(d, inner[0], inner[1]);               // across the full width, above every lane
      z0 = Math.max(...z);
      for (let i = 0; i < lanes; i++) z[i] = z0 + size[2] + GAP;
    }
    const overflow = z0 + size[2] > inner[2] / 2 + 1e-6 || size[0] > inner[0] + 1e-6 || size[1] > inner[1] + 1e-6;
    boxes.push({ id: it.id, name: it.name, slot, center: [x, 0, z0 + size[2] / 2], size, external: false, unsized, overflow });
  }
  // external parts
  const faces: [number, number][] = [[1, 0], [-1, 0], [0, 1], [0, -1]];
  let bodyPanel = 0;
  let wing = 0;
  let endTop = 0;
  let endBottom = 0;
  for (const { it, slot } of external) {
    const unsized = !it.dims_mm;
    const deployable = slot === 'solar' && /deploy/i.test(`${it.name} ${it.fits ?? ''}`);
    if (slot === 'solar' && !deployable) {
      const [fx, fy] = faces[bodyPanel % 4];
      const sideW = fx ? outer[1] : outer[0];
      const per = sideW > 200 ? 2 : 1;
      const k = Math.floor(bodyPanel / 4) % per;
      const w = Math.min(sideW / per - 4, 96);
      const off = per === 2 ? (k === 0 ? -sideW / 4 : sideW / 4) : 0;
      const t = 2;
      const center: [number, number, number] = fx ? [fx * (outer[0] / 2 + t / 2), off, 0] : [off, fy * (outer[1] / 2 + t / 2), 0];
      const size: [number, number, number] = fx ? [t, w, outer[2] - 20] : [w, t, outer[2] - 20];
      boxes.push({ id: it.id, name: it.name, slot, center, size, external: true, unsized: false, overflow: false });
      bodyPanel++;
      continue;
    }
    if (deployable) {
      const side = wing % 2 === 0 ? 1 : -1;
      const d = it.dims_mm ? [...it.dims_mm].sort((p, q) => p - q) : [2, 200, 300];
      const span = d[1];
      const center: [number, number, number] = [side * (outer[0] / 2 + 10 + span / 2), 0, 0];
      boxes.push({ id: it.id, name: it.name, slot, center, size: [span, 2, Math.min(d[2], outer[2])], external: true, unsized, overflow: false });
      wing++;
      continue;
    }
    // antennas and sensors on the end faces: data antennas and sensors at the nadir end, others at the zenith end
    const d = it.dims_mm ? [...it.dims_mm].sort((p, q) => q - p) : [STANDIN, STANDIN, STANDIN];
    const nadir = slot === 'antenna_data' || slot === 'sun_sensor';
    const used = nadir ? endBottom : endTop;
    const x = -outer[0] / 2 + d[0] / 2 + 4 + used;
    const zc = nadir ? -(outer[2] / 2 + d[2] / 2) : outer[2] / 2 + d[2] / 2;
    boxes.push({ id: it.id, name: it.name, slot, center: [Math.min(x, outer[0] / 2 - d[0] / 2), 0, zc], size: [d[0], d[1], d[2]], external: true, unsized, overflow: false });
    if (nadir) endBottom += d[0] + 4;
    else endTop += d[0] + 4;
  }
  return { outer, boxes };
}
