#!/usr/bin/env node
// Builds the MOCK-mode fixtures for the front end from the real synthetic dataset.
//
//   node scripts/build-mock-fixtures.mjs [--data <dir>] [--out <dir>]
//
// Reads  <data>/manifest.json and <data>/*.stl          (default data dir: ../data/synthetic, read-only)
// Writes <out>/project.json, <out>/layouts.json and <out>/meshes/<part_id>.bin   (default out: public/mock-fixtures)
//
// Everything written here is MOCK data for exercising the UI while the backend is being built:
//  * canonical frame = mesh translated so that its AABB centre is at the origin; orient 0 = identity;
//  * mass properties are computed here in float64 (divergence theorem) at an ASSUMED 2,700 kg/m^3;
//  * subsystem / labels come from the dataset manifest's *intended* labels, not from a classifier;
//  * the layout is a PLACEHOLDER: parts are stacked along Z by their AABB extents so that no two AABBs
//    overlap. It is not an optimisation result.
// The mesh binary format follows docs/api-contract.md: uint32 nv, uint32 nt, float32[3nv], uint32[3nt] (LE).

import { readFileSync, writeFileSync, mkdirSync, readdirSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const argVal = (flag, dflt) => {
  const i = args.indexOf(flag);
  return i >= 0 && args[i + 1] ? resolve(args[i + 1]) : dflt;
};
const DATA = argVal('--data', resolve(here, '../../data/synthetic'));
const OUT = argVal('--out', resolve(here, '../public/mock-fixtures'));
const DENSITY = 2700; // kg/m^3, ASSUMED (protocol default)
const ENCL = { x: 100, y: 100, z: 340.5 };
const Z0 = -ENCL.z / 2; // -170.25
const GAP_MM = 0.005; // +5 um placement gap (protocol F.2 contact policy, rule 1)

// ---------------------------------------------------------------- STL parsing
function parseStl(buf) {
  const isAsciiCandidate = buf.slice(0, 5).toString('latin1').toLowerCase() === 'solid';
  if (buf.length >= 84) {
    const nt = buf.readUInt32LE(80);
    if (84 + nt * 50 === buf.length) return parseBinary(buf, nt);
  }
  if (isAsciiCandidate) return parseAscii(buf.toString('latin1'));
  throw new Error('not a valid STL file');
}
function parseBinary(buf, nt) {
  const tris = new Float32Array(nt * 9);
  for (let i = 0; i < nt; i++) {
    const o = 84 + i * 50 + 12;
    for (let k = 0; k < 9; k++) tris[i * 9 + k] = buf.readFloatLE(o + k * 4);
  }
  return tris;
}
function parseAscii(txt) {
  const re = /vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)/g;
  const v = [];
  let m;
  while ((m = re.exec(txt))) v.push(Math.fround(+m[1]), Math.fround(+m[2]), Math.fround(+m[3]));
  return Float32Array.from(v);
}

// Weld exactly-equal float32 vertices.
function weld(tris) {
  const map = new Map();
  const pos = [];
  const idx = new Uint32Array(tris.length / 3);
  for (let i = 0; i < tris.length / 3; i++) {
    const x = tris[i * 3], y = tris[i * 3 + 1], z = tris[i * 3 + 2];
    const key = `${x},${y},${z}`;
    let id = map.get(key);
    if (id === undefined) {
      id = pos.length / 3;
      map.set(key, id);
      pos.push(x, y, z);
    }
    idx[i] = id;
  }
  return { pos: Float64Array.from(pos), idx };
}

function boundaryEdgeCount(idx) {
  const count = new Map();
  for (let t = 0; t < idx.length; t += 3) {
    for (let e = 0; e < 3; e++) {
      const a = idx[t + e], b = idx[t + ((e + 1) % 3)];
      const key = a < b ? `${a}_${b}` : `${b}_${a}`;
      count.set(key, (count.get(key) || 0) + 1);
    }
  }
  let boundary = 0;
  for (const c of count.values()) if (c !== 2) boundary++;
  return boundary;
}

// Covariance-method mass properties about the origin p0 (float64). Returns volume, first moment, second moment.
function massProps(pos, idx) {
  let V = 0;
  const S = [0, 0, 0];
  const C = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let t = 0; t < idx.length; t += 3) {
    const a = [pos[idx[t] * 3], pos[idx[t] * 3 + 1], pos[idx[t] * 3 + 2]];
    const b = [pos[idx[t + 1] * 3], pos[idx[t + 1] * 3 + 1], pos[idx[t + 1] * 3 + 2]];
    const c = [pos[idx[t + 2] * 3], pos[idx[t + 2] * 3 + 1], pos[idx[t + 2] * 3 + 2]];
    const d = a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0]);
    V += d / 6;
    const s = [a[0] + b[0] + c[0], a[1] + b[1] + c[1], a[2] + b[2] + c[2]];
    for (let i = 0; i < 3; i++) S[i] += (d * s[i]) / 24;
    for (let i = 0; i < 3; i++)
      for (let j = 0; j < 3; j++) C[i][j] += (d / 120) * (s[i] * s[j] + a[i] * a[j] + b[i] * b[j] + c[i] * c[j]);
  }
  const com = S.map((v) => v / V);
  const Cc = C.map((row, i) => row.map((v, j) => v - V * com[i] * com[j]));
  const tr = Cc[0][0] + Cc[1][1] + Cc[2][2];
  const J = Cc.map((row, i) => row.map((v, j) => (i === j ? tr : 0) - v)); // unit-density inertia about COM (mm^5)
  return { V, com, J };
}

// Jacobi eigenvalues of a symmetric 3x3 matrix (ascending).
function eigSym3(Ain) {
  const A = Ain.map((r) => r.slice());
  for (let sweep = 0; sweep < 50; sweep++) {
    let off = 0;
    for (let i = 0; i < 3; i++) for (let j = i + 1; j < 3; j++) off += A[i][j] * A[i][j];
    if (off < 1e-30) break;
    for (let p = 0; p < 3; p++)
      for (let q = p + 1; q < 3; q++) {
        if (Math.abs(A[p][q]) < 1e-300) continue;
        const theta = (A[q][q] - A[p][p]) / (2 * A[p][q]);
        const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1), s = t * c;
        for (let k = 0; k < 3; k++) {
          const akp = A[k][p], akq = A[k][q];
          A[k][p] = c * akp - s * akq;
          A[k][q] = s * akp + c * akq;
        }
        for (let k = 0; k < 3; k++) {
          const apk = A[p][k], aqk = A[q][k];
          A[p][k] = c * apk - s * aqk;
          A[q][k] = s * apk + c * aqk;
        }
      }
  }
  return [A[0][0], A[1][1], A[2][2]].sort((a, b) => a - b);
}

// ---------------------------------------------------------------- rotations
// All 24 proper rotations of the cube as integer row-major matrices; identity first, then lexicographic.
function rotationTable() {
  const perms = [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]];
  const out = [];
  for (const p of perms)
    for (let sx = -1; sx <= 1; sx += 2)
      for (let sy = -1; sy <= 1; sy += 2)
        for (let sz = -1; sz <= 1; sz += 2) {
          const s = [sx, sy, sz];
          const M = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
          for (let r = 0; r < 3; r++) M[r][p[r]] = s[r];
          const det =
            M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1]) -
            M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0]) +
            M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0]);
          if (det === 1) out.push(M.flat());
        }
  const isId = (m) => m.join(',') === '1,0,0,0,1,0,0,0,1';
  out.sort((a, b) => (isId(a) ? -1 : isId(b) ? 1 : a.join(',') < b.join(',') ? 1 : -1));
  return out.map((m) => [m.slice(0, 3), m.slice(3, 6), m.slice(6, 9)]);
}
const rotExtents = (R, e) => R.map((row) => Math.abs(row[0]) * e[0] + Math.abs(row[1]) * e[1] + Math.abs(row[2]) * e[2]);

// ---------------------------------------------------------------- subsystem mapping (MOCK)
const SUBSYSTEM = {
  battery: 'power', pcb: 'electronics', electronics: 'electronics', 'reaction wheel': 'adcs',
  magnetorquer: 'adcs', magnetometer: 'adcs', tank: 'tanks', sensor: 'payload', camera: 'payload',
  optics: 'payload', bracket: 'structure', 'connector hub': 'electronics', mechanism: 'structure',
  module: 'unknown', unknown: 'unknown',
};

// ---------------------------------------------------------------- main
const manifest = JSON.parse(readFileSync(join(DATA, 'manifest.json'), 'utf8'));
const stlFiles = new Set(readdirSync(DATA).filter((f) => f.toLowerCase().endsWith('.stl')));
const ROT = rotationTable();
mkdirSync(join(OUT, 'meshes'), { recursive: true });

const parts = [];
let n = 0;
for (const entry of manifest.parts) {
  if (entry.role !== 'packable' || !stlFiles.has(entry.file)) continue;
  n++;
  const id = `p${String(n).padStart(2, '0')}`;
  const raw = readFileSync(join(DATA, entry.file));
  const sha = createHash('sha256').update(raw).digest('hex');
  const tris = parseStl(raw);
  const { pos, idx } = weld(tris);
  // canonical frame: AABB centre at origin
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < pos.length; i += 3)
    for (let k = 0; k < 3; k++) {
      lo[k] = Math.min(lo[k], pos[i + k]);
      hi[k] = Math.max(hi[k], pos[i + k]);
    }
  const ctr = [0, 1, 2].map((k) => (lo[k] + hi[k]) / 2);
  const canon = new Float64Array(pos.length);
  for (let i = 0; i < pos.length; i += 3) for (let k = 0; k < 3; k++) canon[i + k] = pos[i + k] - ctr[k];
  const extents = [0, 1, 2].map((k) => hi[k] - lo[k]);
  const boundary = boundaryEdgeCount(idx);
  const mp = massProps(canon, idx);
  const closed = boundary === 0 && mp.V > 0;
  const mass = closed ? DENSITY * mp.V * 1e-9 : null;
  const inertia = closed ? mp.J.map((r) => r.map((v) => DENSITY * v * 1e-15)) : null;
  const principal = inertia ? eigSym3(inertia) : null;
  const aabbVol = extents[0] * extents[1] * extents[2];

  // binary mesh (canonical frame, float32 positions)
  const nv = canon.length / 3, nt = idx.length / 3;
  const bin = Buffer.alloc(8 + nv * 12 + nt * 12);
  bin.writeUInt32LE(nv, 0);
  bin.writeUInt32LE(nt, 4);
  for (let i = 0; i < canon.length; i++) bin.writeFloatLE(canon[i], 8 + i * 4);
  for (let i = 0; i < idx.length; i++) bin.writeUInt32LE(idx[i], 8 + nv * 12 + i * 4);
  writeFileSync(join(OUT, 'meshes', `${id}.bin`), bin);

  const round = (v, d = 6) => Math.round(v * 10 ** d) / 10 ** d;
  parts.push({
    id, name: entry.name, file: entry.file, sha256: sha,
    units: 'mm', units_confirmed: true,
    status: closed ? 'VALID' : 'WITHHELD',
    status_detail: closed ? 'closed mesh' : `open mesh — ${boundary} boundary edges`,
    repairs: [],
    triangles: nt, display_triangles: nt,
    subsystem: SUBSYSTEM[entry.suggested_type] || 'unknown',
    labels: entry.intended_labels || [],
    extents_mm: extents.map((v) => round(v, 4)),
    volume_mm3: round(mp.V, 3),
    density_kg_m3: DENSITY,
    mass_kg: mass,
    mass_source: closed ? 'ASSUMED' : 'WITHHELD',
    com_canonical_mm: mp.com.map((v) => round(v, 9)),
    inertia_com_kgm2: inertia,
    principal_kgm2: principal,
    solidity: null,
    obb_fill: null,
    aabb_fill: round(mp.V / aabbVol, 4),
    allowed_orients: ROT.map((_, i) => i),
    locked: false, lock_pose: null,
    tags: entry.suggested_type === 'pcb' ? ['pcb'] : [],
    welded_vertices_check: { ours: nv, manifest: entry.welded_vertices ?? null },
    canonical_offset_mm: ctr.map((v) => round(v, 6)),
  });
}

// ---------------------------------------------------------------- placeholder layout (MOCK)
// Each part takes the orientation with the smallest Z extent whose XY footprint fits 100 x 100.
// Parts are stacked along Z from the -Z end face in manifest order, each centred in XY, with a 5 um gap.
// If the plain stack would exceed the enclosure, shelves are formed: parts are put side by side in XY
// within a layer (simple row packing of AABB footprints), so AABBs still never overlap.
function chooseOrient(ext) {
  let best = null;
  ROT.forEach((R, o) => {
    const e = rotExtents(R, ext);
    if (e[0] > ENCL.x || e[1] > ENCL.y) return;
    if (!best || e[2] < best.e[2] - 1e-9 || (Math.abs(e[2] - best.e[2]) < 1e-9 && e[0] > best.e[0] + 1e-9)) best = { o, e };
  });
  return best;
}
const items = parts.map((p) => ({ p, ...chooseOrient(p.extents_mm) }));
const plainStack = items.reduce((s, it) => s + it.e[2] + GAP_MM, 0);
const poses = [];
let strategy;
if (plainStack <= ENCL.z) {
  strategy = 'single stack along Z';
  let z = Z0;
  for (const it of items) {
    const cz = z + GAP_MM + it.e[2] / 2;
    poses.push({ part_id: it.p.id, orient: it.o, t_um: [0, 0, Math.round(cz * 1000)] });
    z = cz + it.e[2] / 2;
  }
} else {
  strategy = 'layers along Z; AABB footprints packed side by side in each layer (max-rects)';
  // Max-rects 2-D packer for one 100 x 100 layer footprint. Returns {x, y} of the lower-left corner or null.
  const newFree = () => [{ x: 0, y: 0, w: ENCL.x, h: ENCL.y }];
  const tryInsert = (free, w, h) => {
    let best = null;
    for (const r of free) {
      if (w + GAP_MM <= r.w + 1e-9 && h + GAP_MM <= r.h + 1e-9) {
        const s = Math.min(r.w - w, r.h - h);
        if (!best || s < best.s) best = { x: r.x, y: r.y, s };
      }
    }
    return best;
  };
  const place = (free, x, y, w, h) => {
    const W = w + GAP_MM, H = h + GAP_MM;
    const out = [];
    for (const r of free) {
      if (x >= r.x + r.w || x + W <= r.x || y >= r.y + r.h || y + H <= r.y) { out.push(r); continue; }
      if (x > r.x) out.push({ x: r.x, y: r.y, w: x - r.x, h: r.h });
      if (x + W < r.x + r.w) out.push({ x: x + W, y: r.y, w: r.x + r.w - x - W, h: r.h });
      if (y > r.y) out.push({ x: r.x, y: r.y, w: r.w, h: y - r.y });
      if (y + H < r.y + r.h) out.push({ x: r.x, y: y + H, w: r.w, h: r.y + r.h - y - H });
    }
    return out.filter((a, i) => !out.some((b, j) => j !== i && a.x >= b.x && a.y >= b.y && a.x + a.w <= b.x + b.w && a.y + a.h <= b.y + b.h && (j < i || a.x !== b.x || a.y !== b.y || a.w !== b.w || a.h !== b.h)));
  };
  // Deterministic randomised greedy (seeded), keeping the shortest attempt. A placeholder, not an optimiser.
  let seed = 20261022;
  const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
  const orientOpts = (it) =>
    ROT.map((R, o) => ({ o, e: rotExtents(R, it.p.extents_mm) })).filter((c) => c.e[0] <= ENCL.x && c.e[1] <= ENCL.y);
  const attempt = (order, randomNewLayer) => {
    const layers = [];
    for (const it of order) {
      let done = false;
      const opts = orientOpts(it);
      for (const L of layers) {
        // orientations that fit under the layer height, smallest footprint first (stands the part up)
        const fit = opts.filter((c) => c.e[2] <= L.h + 1e-9).sort((a, b) => a.e[0] * a.e[1] - b.e[0] * b.e[1]);
        for (const c of fit) {
          const pos = tryInsert(L.free, c.e[0], c.e[1]);
          if (pos) {
            L.free = place(L.free, pos.x, pos.y, c.e[0], c.e[1]);
            L.items.push({ id: it.p.id, o: c.o, e: c.e, x: pos.x + GAP_MM, y: pos.y + GAP_MM });
            done = true;
            break;
          }
        }
        if (done) break;
      }
      if (!done) {
        const c = randomNewLayer ? opts[Math.floor(rnd() * opts.length)] : { o: it.o, e: it.e };
        const L = { h: c.e[2], free: newFree(), items: [] };
        const pos = tryInsert(L.free, c.e[0], c.e[1]);
        L.free = place(L.free, pos.x, pos.y, c.e[0], c.e[1]);
        L.items.push({ id: it.p.id, o: c.o, e: c.e, x: pos.x + GAP_MM, y: pos.y + GAP_MM });
        layers.push(L);
      }
    }
    return { layers, length: layers.reduce((s, L) => s + L.h + GAP_MM, 0) };
  };
  let bestAttempt = attempt([...items].sort((a, b) => b.e[2] - a.e[2] || b.e[0] * b.e[1] - a.e[0] * a.e[1]), false);
  for (let k = 0; k < 4000; k++) {
    const order = items.map((it) => ({ it, r: rnd() })).sort((a, b) => a.r - b.r).map((x) => x.it);
    const a = attempt(order, k % 2 === 1);
    if (a.length < bestAttempt.length) bestAttempt = a;
  }
  const layers = bestAttempt.layers;
  let z = Z0;
  for (const L of layers) {
    for (const { id, o, e, x, y } of L.items) {
      const cx = -ENCL.x / 2 + x + e[0] / 2;
      const cy = -ENCL.y / 2 + y + e[1] / 2;
      const cz = z + GAP_MM + e[2] / 2;
      poses.push({ part_id: id, orient: o, t_um: [Math.round(cx * 1000), Math.round(cy * 1000), Math.round(cz * 1000)] });
    }
    z += GAP_MM + L.h;
  }
  poses.sort((a, b) => (a.part_id < b.part_id ? -1 : 1));
}

// AABB self-check of the placeholder (proves AABB-disjointness + containment; used as the MOCK "validator").
const boxes = poses.map((ps) => {
  const p = parts.find((q) => q.id === ps.part_id);
  const e = rotExtents(ROT[ps.orient], p.extents_mm);
  const c = ps.t_um.map((v) => v / 1000);
  return { id: p.id, lo: c.map((v, k) => v - e[k] / 2), hi: c.map((v, k) => v + e[k] / 2) };
});
const half = [ENCL.x / 2, ENCL.y / 2, ENCL.z / 2];
if (process.env.T2S_FIXTURE_DEBUG) {
  console.log(`plain stack ${plainStack.toFixed(2)} mm`);
  for (const it of items) console.log(it.p.id, it.p.name, it.o, it.e.map((v) => v.toFixed(2)).join(' x '));
  for (const b of boxes) console.log(b.id, b.lo.map((v) => v.toFixed(2)).join(','), '->', b.hi.map((v) => v.toFixed(2)).join(','));
}
for (const b of boxes)
  for (let k = 0; k < 3; k++)
    if (b.lo[k] < -half[k] - 1e-9 || b.hi[k] > half[k] + 1e-9) throw new Error(`placeholder: ${b.id} outside enclosure on axis ${k}`);
for (let i = 0; i < boxes.length; i++)
  for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    const sep = [0, 1, 2].some((k) => a.hi[k] <= b.lo[k] || b.hi[k] <= a.lo[k]);
    if (!sep) throw new Error(`placeholder: AABB overlap ${a.id}/${b.id}`);
  }
const topZ = Math.max(...boxes.map((b) => b.hi[2]));

const project = {
  mock: true,
  mock_note: 'MOCK fixtures generated by frontend/scripts/build-mock-fixtures.mjs from data/synthetic. Not backend output.',
  name: 'Synthetic 3U (MOCK)',
  dataset_sha256: manifest.dataset_sha256,
  enclosure: { size_mm: [ENCL.x, ENCL.y, ENCL.z], form: '3U', min_mm: [-50, -50, Z0], max_mm: [50, 50, -Z0] },
  rotations: ROT,
  parts,
  settings: {
    stage: 1,
    sliders: { space: 25, balance: 25, inertia: 25, feasibility: 25, mass_symmetry: 50, cable: 0, cost: 0, speed_quality: 50 },
    target_com_mm: [0, 0, 0],
    compactness_definition: 'one_end',
    show_frame_mass_in_com: false,
  },
  stage2_frame: {
    status: 'ASSUMED',
    wall_mm: 2.0,
    inner_box_mm: [96, 96, 336.5],
    rail_mm: [8.5, 8.5],
    boxes: [
      ...[[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy], i) => ({
        kind: 'rail', id: `rail${i + 1}`,
        min: [sx < 0 ? -50 : 41.5, sy < 0 ? -50 : 41.5, Z0],
        max: [sx < 0 ? -41.5 : 50, sy < 0 ? -41.5 : 50, -Z0],
      })),
    ],
    walls: { inner_min: [-48, -48, -168.25], inner_max: [48, 48, 168.25] },
  },
  limits: {
    com_box_mm: [20, 20, 70],
    cds_mass_note_kg: 6.0,
    clearance_part_mm: 2.2,
    clearance_wall_mm: 1.2,
    length_mm: ENCL.z,
    lower_bounds_mm: [],
  },
  revs: { epoch: 1, parts_rev: 1, constraint_rev: 1, mass_rev: 1, weights_rev: 1 },
};

const layout = {
  id: 'L-MOCK-0001',
  hash: createHash('sha256').update(JSON.stringify(poses)).digest('hex').slice(0, 16),
  stage: 1,
  mode: 'default',
  status: 'VALIDATED',
  parts_rev: 1, constraint_rev: 1, mass_rev: 1, weights_rev: 1,
  poses,
  extra_items: [],
  metrics: null, // computed at runtime by the mock with the same aggregation code as the UI
  scores: null,
  algorithm: { id: 'mock_stack', label: 'MOCK placeholder stack', reason: `MOCK placeholder (${strategy}); not an optimisation result` },
  validation: { certified: true, validator_version: 'mock-aabb-1', tolerance_mm: 0, pairs: (boxes.length * (boxes.length - 1)) / 2, checked_at: new Date(0).toISOString() },
  origin: 'archive',
  created: new Date(0).toISOString(),
  mock: true,
};

writeFileSync(join(OUT, 'project.json'), JSON.stringify(project, null, 1));
writeFileSync(join(OUT, 'layouts.json'), JSON.stringify({ mock: true, layouts: [layout] }, null, 1));

const totalMass = parts.reduce((s, p) => s + (p.mass_kg || 0), 0);
const totalVol = parts.reduce((s, p) => s + p.volume_mm3, 0);
console.log(`parts: ${parts.length}; total volume ${(totalVol / 1000).toFixed(1)} cm^3; total mass ${totalMass.toFixed(4)} kg (ASSUMED ${DENSITY} kg/m^3)`);
console.log(`placeholder layout: ${strategy}; plain stack would be ${plainStack.toFixed(1)} mm; top z ${topZ.toFixed(2)} mm (length used ${(topZ - Z0).toFixed(1)} mm)`);
for (const p of parts)
  if (p.welded_vertices_check.manifest !== null && p.welded_vertices_check.ours !== p.welded_vertices_check.manifest)
    console.log(`note: ${p.name} welded vertices ${p.welded_vertices_check.ours} vs manifest ${p.welded_vertices_check.manifest}`);
console.log(`written to ${OUT}`);
if (!existsSync(join(OUT, 'project.json'))) process.exit(1);
