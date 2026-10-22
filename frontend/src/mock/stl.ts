// In-browser STL reader for MOCK mode only (the real pipeline is the backend's, protocol §B).
// Parses binary and ASCII STL, welds exactly-equal float32 vertices, finds open edges / boundary loops,
// and computes float64 mass properties with the covariance (divergence-theorem) method of protocol §E.2.

import type { Mat3, Vec3 } from '../api/types';

export interface ParsedMesh {
  positions: Float64Array; // welded, in file units
  indices: Uint32Array;
  format: 'binary' | 'ascii';
}

export function parseStl(buf: ArrayBuffer): ParsedMesh {
  const bytes = new Uint8Array(buf);
  const head = new TextDecoder('latin1').decode(bytes.subarray(0, Math.min(bytes.length, 512)));
  if (buf.byteLength >= 84) {
    const nt = new DataView(buf).getUint32(80, true);
    if (84 + nt * 50 === buf.byteLength) return weld(readBinary(buf, nt), 'binary');
  }
  if (/^\s*solid/i.test(head)) {
    const tris = readAscii(new TextDecoder('latin1').decode(bytes));
    if (tris.length >= 9) return weld(tris, 'ascii');
  }
  throw new Error('not a readable STL file (neither binary with a consistent triangle count nor ASCII)');
}

function readBinary(buf: ArrayBuffer, nt: number): Float32Array {
  const dv = new DataView(buf);
  const out = new Float32Array(nt * 9);
  for (let i = 0; i < nt; i++) {
    const o = 84 + i * 50 + 12;
    for (let k = 0; k < 9; k++) out[i * 9 + k] = dv.getFloat32(o + k * 4, true);
  }
  return out;
}

function readAscii(txt: string): Float32Array {
  const re = /vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)/g;
  const v: number[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(txt))) v.push(+m[1], +m[2], +m[3]);
  return Float32Array.from(v.slice(0, v.length - (v.length % 9)));
}

function weld(tris: Float32Array, format: ParsedMesh['format']): ParsedMesh {
  const map = new Map<string, number>();
  const pos: number[] = [];
  const idx = new Uint32Array(tris.length / 3);
  for (let i = 0; i < tris.length / 3; i++) {
    const x = tris[i * 3];
    const y = tris[i * 3 + 1];
    const z = tris[i * 3 + 2];
    const key = `${x},${y},${z}`;
    let id = map.get(key);
    if (id === undefined) {
      id = pos.length / 3;
      map.set(key, id);
      pos.push(x, y, z);
    }
    idx[i] = id;
  }
  return { positions: Float64Array.from(pos), indices: idx, format };
}

export interface MeshCheck {
  boundaryEdges: number;
  nonManifoldEdges: number;
  boundaryLoops: number;
  degenerate: number;
}

export function checkMesh(m: ParsedMesh): MeshCheck {
  const count = new Map<string, number>();
  let degenerate = 0;
  const idx = m.indices;
  for (let t = 0; t < idx.length; t += 3) {
    const a = idx[t];
    const b = idx[t + 1];
    const c = idx[t + 2];
    if (a === b || b === c || a === c) degenerate++;
    for (const [u, v] of [
      [a, b],
      [b, c],
      [c, a],
    ]) {
      const key = u < v ? `${u}_${v}` : `${v}_${u}`;
      count.set(key, (count.get(key) ?? 0) + 1);
    }
  }
  let boundaryEdges = 0;
  let nonManifoldEdges = 0;
  const parent = new Map<number, number>();
  const find = (x: number): number => {
    let r = x;
    while (parent.get(r) !== undefined && parent.get(r) !== r) r = parent.get(r)!;
    parent.set(x, r);
    return r;
  };
  for (const [key, c] of count) {
    if (c === 1) {
      boundaryEdges++;
      const [u, v] = key.split('_').map(Number);
      if (!parent.has(u)) parent.set(u, u);
      if (!parent.has(v)) parent.set(v, v);
      const ru = find(u);
      const rv = find(v);
      if (ru !== rv) parent.set(ru, rv);
    } else if (c > 2) nonManifoldEdges++;
  }
  const roots = new Set<number>();
  for (const k of parent.keys()) roots.add(find(k));
  return { boundaryEdges, nonManifoldEdges, boundaryLoops: roots.size, degenerate };
}

export interface MassPropsMm {
  volume_mm3: number;
  com_mm: Vec3;
  /** unit-density inertia about the COM, mm^5 */
  J_mm5: Mat3;
}

/** Covariance method about the origin of the given positions (callers centre the mesh first). */
export function massProps(positions: Float64Array, indices: Uint32Array): MassPropsMm {
  let V = 0;
  const S = [0, 0, 0];
  const C = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  for (let t = 0; t < indices.length; t += 3) {
    const ia = indices[t] * 3;
    const ib = indices[t + 1] * 3;
    const ic = indices[t + 2] * 3;
    const a = [positions[ia], positions[ia + 1], positions[ia + 2]];
    const b = [positions[ib], positions[ib + 1], positions[ib + 2]];
    const c = [positions[ic], positions[ic + 1], positions[ic + 2]];
    const d = a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0]);
    V += d / 6;
    const s = [a[0] + b[0] + c[0], a[1] + b[1] + c[1], a[2] + b[2] + c[2]];
    for (let i = 0; i < 3; i++) S[i] += (d * s[i]) / 24;
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) C[i][j] += (d / 120) * (s[i] * s[j] + a[i] * a[j] + b[i] * b[j] + c[i] * c[j]);
  }
  const com = (V !== 0 ? S.map((v) => v / V) : [0, 0, 0]) as Vec3;
  const Cc = C.map((row, i) => row.map((v, j) => v - V * com[i] * com[j]));
  const tr = Cc[0][0] + Cc[1][1] + Cc[2][2];
  const J = Cc.map((row, i) => row.map((v, j) => (i === j ? tr : 0) - v)) as Mat3;
  return { volume_mm3: V, com_mm: com, J_mm5: J };
}

export interface Canonical {
  positions: Float32Array;
  positions64: Float64Array;
  indices: Uint32Array;
  extents: Vec3;
  centre: Vec3;
}

/** Scale to millimetres and translate so the AABB centre is at the origin (canonical frame, orient 0 = identity). */
export function canonicalise(m: ParsedMesh, unitScale: number): Canonical {
  const lo = [Infinity, Infinity, Infinity];
  const hi = [-Infinity, -Infinity, -Infinity];
  const p = m.positions;
  for (let i = 0; i < p.length; i += 3)
    for (let k = 0; k < 3; k++) {
      const v = p[i + k] * unitScale;
      if (v < lo[k]) lo[k] = v;
      if (v > hi[k]) hi[k] = v;
    }
  const centre = [0, 1, 2].map((k) => (lo[k] + hi[k]) / 2) as Vec3;
  const positions64 = new Float64Array(p.length);
  for (let i = 0; i < p.length; i += 3) for (let k = 0; k < 3; k++) positions64[i + k] = p[i + k] * unitScale - centre[k];
  return {
    positions: Float32Array.from(positions64),
    positions64,
    indices: m.indices,
    extents: [0, 1, 2].map((k) => (p.length ? hi[k] - lo[k] : 0)) as Vec3,
    centre,
  };
}

export const UNIT_SCALE: Record<string, number> = { mm: 1, cm: 10, m: 1000, in: 25.4 };

/** Build a binary STL (used by tests to generate unseen files). */
export function buildBinaryStl(tris: number[][][]): ArrayBuffer {
  const buf = new ArrayBuffer(84 + tris.length * 50);
  const dv = new DataView(buf);
  dv.setUint32(80, tris.length, true);
  tris.forEach((t, i) => {
    const o = 84 + i * 50 + 12;
    for (let v = 0; v < 3; v++) for (let k = 0; k < 3; k++) dv.setFloat32(o + (v * 3 + k) * 4, t[v][k], true);
  });
  return buf;
}

/** Closed axis-aligned box as 12 outward-wound triangles. */
export function boxTriangles(min: Vec3, max: Vec3): number[][][] {
  const [x0, y0, z0] = min;
  const [x1, y1, z1] = max;
  const v = [
    [x0, y0, z0],
    [x1, y0, z0],
    [x1, y1, z0],
    [x0, y1, z0],
    [x0, y0, z1],
    [x1, y0, z1],
    [x1, y1, z1],
    [x0, y1, z1],
  ];
  const f = [
    [0, 2, 1],
    [0, 3, 2],
    [4, 5, 6],
    [4, 6, 7],
    [0, 1, 5],
    [0, 5, 4],
    [1, 2, 6],
    [1, 6, 5],
    [2, 3, 7],
    [2, 7, 6],
    [3, 0, 4],
    [3, 4, 7],
  ];
  return f.map((tri) => tri.map((i) => v[i]));
}
