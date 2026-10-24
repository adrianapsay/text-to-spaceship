// V2 WS6 engineering drawings: the raster views. Each orthographic / isometric view is rendered off screen with
// three.js from the same meshes as the 3D view, in a technical style: white faces, black feature edges (creases above
// 30° and the silhouette for this view direction, as thick lines), optionally the hidden edges dashed and thin. A
// second pass renders every item in a flat id colour; its visible pixels give each item's visible area and a point
// well inside it, for the balloons. The image covers exactly the view's sheet rectangle (plus a small pad), using the
// same projection as the vectors on the sheet.

import * as THREE from 'three';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { session } from '../../api/session';
import { buildGeometry, loadPartGeometry } from '../viewport/geometry';
import type { Visibility } from './balloons';
import type { DrawItem, DrawSource, DrawTransform } from './model';
import { boxCentre, type PlacedView, type V3, type ViewId } from './projection';

// ------------------------------------------------------------------------------------------------ meshes
const itemCache = new Map<string, Promise<THREE.BufferGeometry>>();

/** An extra item's mesh (world coordinates), cached by URL like the 3D view (a designed bracket gets a new URL). */
export function loadItemGeometry(url: string): Promise<THREE.BufferGeometry> {
  let p = itemCache.get(url);
  if (!p) {
    p = session()
      .api.itemMesh(url)
      .then((m) => buildGeometry(m).geometry);
    p.catch(() => itemCache.delete(url));
    itemCache.set(url, p);
  }
  return p;
}

const boxCache = new Map<string, THREE.BufferGeometry>();

export async function loadSource(src: DrawSource): Promise<THREE.BufferGeometry | null> {
  try {
    if (src.kind === 'part') return (await loadPartGeometry(src.part)).geometry;
    if (src.kind === 'mesh') return await loadItemGeometry(src.url);
    const key = `${src.min.join(',')}|${src.max.join(',')}`;
    let g = boxCache.get(key);
    if (!g) {
      const d = [0, 1, 2].map((k) => src.max[k] - src.min[k]);
      g = new THREE.BoxGeometry(d[0], d[1], d[2]).translate((src.min[0] + src.max[0]) / 2, (src.min[1] + src.max[1]) / 2, (src.min[2] + src.max[2]) / 2);
      boxCache.set(key, g);
    }
    return g;
  } catch {
    return null;
  }
}

export function matrixOf(t: DrawTransform): THREE.Matrix4 {
  const R = t.R;
  const s = t.s;
  return new THREE.Matrix4().set(R[0][0] * s, R[0][1] * s, R[0][2] * s, t.t[0], R[1][0] * s, R[1][1] * s, R[1][2] * s, t.t[1], R[2][0] * s, R[2][1] * s, R[2][2] * s, t.t[2], 0, 0, 0, 1);
}

// ------------------------------------------------------------------------------------------------ feature edges
/** Unique edges of a triangle mesh with the normals of the faces on both sides (vertices welded at 0.1 µm). */
export interface EdgeTable {
  count: number;
  a: Float32Array;
  b: Float32Array;
  n1: Float32Array;
  /** NaN for a boundary edge (one face) */
  n2: Float32Array;
  /** drawn in every view: crease above the angle, boundary or non-manifold */
  crease: Uint8Array;
}

export function buildEdgeTable(pos: ArrayLike<number>, index: ArrayLike<number> | null, creaseDeg = 30): EdgeTable {
  const nv = pos.length / 3;
  const weld = new Int32Array(nv);
  const keys = new Map<string, number>();
  const wp: number[] = [];
  for (let i = 0; i < nv; i++) {
    const x = pos[3 * i];
    const y = pos[3 * i + 1];
    const z = pos[3 * i + 2];
    const k = `${Math.round(x * 1e4)},${Math.round(y * 1e4)},${Math.round(z * 1e4)}`;
    let id = keys.get(k);
    if (id === undefined) {
      id = wp.length / 3;
      keys.set(k, id);
      wp.push(x, y, z);
    }
    weld[i] = id;
  }
  const nw = wp.length / 3;
  const nt = (index ? index.length : nv) / 3;
  const fn = new Float32Array(nt * 3);
  const emap = new Map<number, number>();
  const ea: number[] = [];
  const eb: number[] = [];
  const f1: number[] = [];
  const f2: number[] = [];
  const cnt: number[] = [];
  for (let t = 0; t < nt; t++) {
    const v = [0, 1, 2].map((j) => weld[index ? index[3 * t + j] : 3 * t + j]);
    const p0 = 3 * v[0];
    const p1 = 3 * v[1];
    const p2 = 3 * v[2];
    const ux = wp[p1] - wp[p0];
    const uy = wp[p1 + 1] - wp[p0 + 1];
    const uz = wp[p1 + 2] - wp[p0 + 2];
    const vx = wp[p2] - wp[p0];
    const vy = wp[p2 + 1] - wp[p0 + 1];
    const vz = wp[p2 + 2] - wp[p0 + 2];
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    const l = Math.hypot(nx, ny, nz);
    if (!(l > 1e-12)) continue; // degenerate: no edges from it
    nx /= l;
    ny /= l;
    nz /= l;
    fn[3 * t] = nx;
    fn[3 * t + 1] = ny;
    fn[3 * t + 2] = nz;
    for (let j = 0; j < 3; j++) {
      const p = v[j];
      const q = v[(j + 1) % 3];
      if (p === q) continue;
      const lo = Math.min(p, q);
      const hi = Math.max(p, q);
      const key = lo * nw + hi;
      const e = emap.get(key);
      if (e === undefined) {
        emap.set(key, ea.length);
        ea.push(lo);
        eb.push(hi);
        f1.push(t);
        f2.push(-1);
        cnt.push(1);
      } else {
        if (cnt[e] === 1) f2[e] = t;
        cnt[e] += 1;
      }
    }
  }
  const n = ea.length;
  const out: EdgeTable = { count: n, a: new Float32Array(3 * n), b: new Float32Array(3 * n), n1: new Float32Array(3 * n), n2: new Float32Array(3 * n), crease: new Uint8Array(n) };
  const cosC = Math.cos((creaseDeg * Math.PI) / 180);
  for (let e = 0; e < n; e++) {
    for (let k = 0; k < 3; k++) {
      out.a[3 * e + k] = wp[3 * ea[e] + k];
      out.b[3 * e + k] = wp[3 * eb[e] + k];
      out.n1[3 * e + k] = fn[3 * f1[e] + k];
      out.n2[3 * e + k] = f2[e] >= 0 ? fn[3 * f2[e] + k] : NaN;
    }
    const d = f2[e] >= 0 ? fn[3 * f1[e]] * fn[3 * f2[e]] + fn[3 * f1[e] + 1] * fn[3 * f2[e] + 1] + fn[3 * f1[e] + 2] * fn[3 * f2[e] + 2] : -1;
    out.crease[e] = cnt[e] !== 2 || d < cosC ? 1 : 0;
  }
  return out;
}

const tables = new WeakMap<THREE.BufferGeometry, EdgeTable>();

export function edgeTableOf(g: THREE.BufferGeometry): EdgeTable {
  let t = tables.get(g);
  if (!t) {
    const pos = g.getAttribute('position').array as ArrayLike<number>;
    const idx = g.getIndex();
    t = buildEdgeTable(pos, idx ? (idx.array as ArrayLike<number>) : null);
    tables.set(g, t);
  }
  return t;
}

/** The edge table in world coordinates: p = R · (s · p) + t, n = R · n. */
export function edgesToWorld(e: EdgeTable, tr: DrawTransform): EdgeTable {
  const R = tr.R;
  const s = tr.s;
  const out: EdgeTable = { count: e.count, a: new Float32Array(e.a.length), b: new Float32Array(e.b.length), n1: new Float32Array(e.n1.length), n2: new Float32Array(e.n2.length), crease: e.crease };
  const tp = (src: Float32Array, dst: Float32Array, point: boolean) => {
    for (let i = 0; i < src.length; i += 3) {
      const x = src[i];
      const y = src[i + 1];
      const z = src[i + 2];
      for (let k = 0; k < 3; k++) dst[i + k] = point ? s * (R[k][0] * x + R[k][1] * y + R[k][2] * z) + tr.t[k] : R[k][0] * x + R[k][1] * y + R[k][2] * z;
    }
  };
  tp(e.a, out.a, true);
  tp(e.b, out.b, true);
  tp(e.n1, out.n1, false);
  tp(e.n2, out.n2, false);
  return out;
}

/** Segments drawn for a view direction: creases and boundaries always, smooth edges where the surface turns away
 * (one face toward the viewer, the other not: the silhouette). Returns xyz pairs. */
export function featureSegments(e: EdgeTable, dir: V3, out: number[] = []): number[] {
  const eps = 1e-6;
  for (let i = 0; i < e.count; i++) {
    let draw = e.crease[i] === 1;
    if (!draw) {
      const d1 = e.n1[3 * i] * dir[0] + e.n1[3 * i + 1] * dir[1] + e.n1[3 * i + 2] * dir[2];
      const d2 = e.n2[3 * i] * dir[0] + e.n2[3 * i + 1] * dir[1] + e.n2[3 * i + 2] * dir[2];
      draw = d1 < -eps !== d2 < -eps;
    }
    if (draw) out.push(e.a[3 * i], e.a[3 * i + 1], e.a[3 * i + 2], e.b[3 * i], e.b[3 * i + 1], e.b[3 * i + 2]);
  }
  return out;
}

// ------------------------------------------------------------------------------------------------ id raster
/**
 * Visible area and an inside point per id from an id raster (`labels`: −1 background, else 0…n−1; row 0 = first row
 * of `labels`): pixel counts and, per id, the pixel farthest from the region's border (two-pass 3-4 chamfer
 * distance), a stable point for a leader to end on.
 */
export function analyseLabels(labels: Int32Array, w: number, h: number, n: number): { count: Int32Array; anchor: Int32Array; depth: Int32Array } {
  const BIG = 1 << 29;
  const d = new Int32Array(w * h);
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const l = labels[i];
      const edge = x === 0 || y === 0 || x === w - 1 || y === h - 1 || labels[i - 1] !== l || labels[i + 1] !== l || labels[i - w] !== l || labels[i + w] !== l;
      d[i] = edge ? 0 : BIG;
    }
  for (let y = 1; y < h; y++)
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      if (d[i] === 0) continue;
      d[i] = Math.min(d[i], d[i - 1] + 3, d[i - w] + 3, d[i - w - 1] + 4, d[i - w + 1] + 4);
    }
  for (let y = h - 2; y >= 0; y--)
    for (let x = w - 2; x > 0; x--) {
      const i = y * w + x;
      if (d[i] === 0) continue;
      d[i] = Math.min(d[i], d[i + 1] + 3, d[i + w] + 3, d[i + w + 1] + 4, d[i + w - 1] + 4);
    }
  const count = new Int32Array(n);
  const anchor = new Int32Array(n).fill(-1);
  const depth = new Int32Array(n).fill(-1);
  for (let i = 0; i < w * h; i++) {
    const l = labels[i];
    if (l < 0 || l >= n) continue;
    count[l] += 1;
    if (d[i] > depth[l]) {
      depth[l] = d[i];
      anchor[l] = i;
    }
  }
  return { count, anchor, depth };
}

/** RGBA id raster (WebGL readPixels: bottom row first) → labels with the top row first. */
export function decodeIds(buf: Uint8Array, w: number, h: number): Int32Array {
  const out = new Int32Array(w * h);
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) {
      const s = 4 * ((h - 1 - y) * w + x);
      out[y * w + x] = buf[s + 2] > 127 ? -1 : buf[s] + 256 * buf[s + 1] - 1;
    }
  return out;
}

// ------------------------------------------------------------------------------------------------ renderer
let renderer: THREE.WebGLRenderer | null = null;

function getRenderer(): THREE.WebGLRenderer {
  if (!renderer) {
    const canvas = document.createElement('canvas');
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true, alpha: false, powerPreference: 'high-performance' });
    renderer.setPixelRatio(1);
    renderer.setClearColor(0xffffff, 1);
  }
  return renderer;
}

/** Free the off-screen WebGL context (when the Drawings tab closes). */
export function releaseRenderer(): void {
  if (!renderer) return;
  renderer.dispose();
  renderer.forceContextLoss();
  renderer = null;
}

export interface LoadedItem {
  item: DrawItem;
  geometry: THREE.BufferGeometry;
  edges: EdgeTable;
}

export async function loadItems(items: DrawItem[]): Promise<LoadedItem[]> {
  const geos = await Promise.all(items.map((i) => loadSource(i.source)));
  const out: LoadedItem[] = [];
  items.forEach((item, k) => {
    const g = geos[k];
    if (g) out.push({ item, geometry: g, edges: edgesToWorld(edgeTableOf(g), item.transform) });
  });
  return out;
}

/** World bounding box of loaded items. */
export function worldBox(items: LoadedItem[]): { min: V3; max: V3 } | null {
  const b = new THREE.Box3();
  for (const it of items) {
    if (!it.geometry.boundingBox) it.geometry.computeBoundingBox();
    const bb = it.geometry.boundingBox!.clone().applyMatrix4(matrixOf(it.item.transform));
    b.union(bb);
  }
  return b.isEmpty() ? null : { min: [b.min.x, b.min.y, b.min.z], max: [b.max.x, b.max.y, b.max.z] };
}

export interface ViewRender {
  view: ViewId;
  href: string;
  /** image rectangle on the sheet (the view rectangle grown by the pad) */
  x: number;
  y: number;
  w: number;
  h: number;
  vis: Visibility[];
}

export interface RenderOptions {
  /** pixels per sheet millimetre of the image (8 ≈ 200 dpi) */
  pxPerMm: number;
  /** pixels per sheet millimetre of the id raster */
  idPxPerMm: number;
  hidden: boolean;
  /** sheet mm around the view rectangle */
  pad: number;
  /** visible / hidden edge widths (sheet mm, ISO 128 line group 0.35) */
  wide: number;
  narrow: number;
}

export const RENDER_DEFAULTS: RenderOptions = { pxPerMm: 8, idPxPerMm: 2, hidden: false, pad: 1.5, wide: 0.35, narrow: 0.18 };

const ID_VERT = 'void main() { gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }';
const ID_FRAG = 'uniform vec3 idc; void main() { gl_FragColor = vec4(idc, 1.0); }';

function viewCamera(v: PlacedView, pad: number): THREE.OrthographicCamera {
  const hw = (v.w / 2 + pad) / v.scale;
  const hh = (v.h / 2 + pad) / v.scale;
  const c = boxCentre(v.box);
  const ext = [0, 1, 2].map((k) => v.box.max[k] - v.box.min[k]);
  const r = Math.hypot(ext[0], ext[1], ext[2]) / 2 + 10;
  const cam = new THREE.OrthographicCamera(-hw, hw, hh, -hh, 0.1, 4 * r + 20);
  cam.position.set(c[0] - v.basis.dir[0] * 2 * r, c[1] - v.basis.dir[1] * 2 * r, c[2] - v.basis.dir[2] * 2 * r);
  cam.up.set(v.basis.up[0], v.basis.up[1], v.basis.up[2]);
  cam.lookAt(c[0], c[1], c[2]);
  cam.updateProjectionMatrix();
  cam.updateMatrixWorld(true);
  return cam;
}

const nextTick = () => new Promise<void>((r) => setTimeout(r, 0));

/** Render the views of one sheet. Throws when WebGL is not available. */
export async function renderViews(items: LoadedItem[], views: (PlacedView & { view: ViewId })[], opts: RenderOptions = RENDER_DEFAULTS, alive: () => boolean = () => true): Promise<ViewRender[]> {
  const r = getRenderer();
  const faceMat = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
  const scene = new THREE.Scene();
  const idScene = new THREE.Scene();
  const idMats: THREE.ShaderMaterial[] = [];
  items.forEach((it, i) => {
    const m = matrixOf(it.item.transform);
    const mesh = new THREE.Mesh(it.geometry, faceMat);
    mesh.matrixAutoUpdate = false;
    mesh.matrix.copy(m);
    mesh.updateMatrixWorld(true);
    scene.add(mesh);
    const id = i + 1;
    const mat = new THREE.ShaderMaterial({ uniforms: { idc: { value: new THREE.Vector3((id & 255) / 255, ((id >> 8) & 255) / 255, 0) } }, vertexShader: ID_VERT, fragmentShader: ID_FRAG, side: THREE.DoubleSide });
    idMats.push(mat);
    const im = new THREE.Mesh(it.geometry, mat);
    im.matrixAutoUpdate = false;
    im.matrix.copy(m);
    im.updateMatrixWorld(true);
    idScene.add(im);
  });
  const out: ViewRender[] = [];
  try {
    for (const v of views) {
      if (!alive()) break;
      const wMm = v.w + 2 * opts.pad;
      const hMm = v.h + 2 * opts.pad;
      let px = opts.pxPerMm;
      const maxSide = Math.min(4096, r.capabilities.maxTextureSize || 4096);
      if (Math.max(wMm, hMm) * px > maxSide) px = maxSide / Math.max(wMm, hMm);
      const W = Math.max(2, Math.round(wMm * px));
      const H = Math.max(2, Math.round(hMm * px));
      const cam = viewCamera(v, opts.pad);
      const segs: number[] = [];
      for (const it of items) featureSegments(it.edges, v.basis.dir, segs);
      const lineGeo = new LineSegmentsGeometry();
      lineGeo.setPositions(segs.length ? segs : [0, 0, 0, 0, 0, 0]);
      const visMat = new LineMaterial({ color: 0x000000, linewidth: Math.max(1, opts.wide * px), worldUnits: false, depthTest: true, depthWrite: false });
      visMat.resolution.set(W, H);
      const visLines = new LineSegments2(lineGeo, visMat);
      visLines.renderOrder = 2;
      const added: THREE.Object3D[] = [visLines];
      let hidMat: LineMaterial | null = null;
      if (opts.hidden) {
        hidMat = new LineMaterial({ color: 0x3c3c3c, linewidth: Math.max(1, opts.narrow * px), worldUnits: false, dashed: true, dashSize: 2.4 / v.scale, gapSize: 1.2 / v.scale, depthTest: true, depthWrite: false });
        hidMat.depthFunc = THREE.GreaterDepth;
        hidMat.resolution.set(W, H);
        const hid = new LineSegments2(lineGeo, hidMat);
        hid.computeLineDistances();
        hid.renderOrder = 1;
        added.push(hid);
      }
      for (const o of added) scene.add(o);
      r.setRenderTarget(null);
      r.setSize(W, H, false);
      r.clear();
      r.render(scene, cam);
      const href = r.domElement.toDataURL('image/png');
      for (const o of added) scene.remove(o);
      lineGeo.dispose();
      visMat.dispose();
      hidMat?.dispose();
      // id pass: visible area and an inside point per item
      const Wi = Math.max(2, Math.round(wMm * opts.idPxPerMm));
      const Hi = Math.max(2, Math.round(hMm * opts.idPxPerMm));
      const rt = new THREE.WebGLRenderTarget(Wi, Hi, { depthBuffer: true });
      r.setRenderTarget(rt);
      r.clear();
      r.render(idScene, cam);
      const buf = new Uint8Array(Wi * Hi * 4);
      r.readRenderTargetPixels(rt, 0, 0, Wi, Hi, buf);
      r.setRenderTarget(null);
      rt.dispose();
      const labels = decodeIds(buf, Wi, Hi);
      const a = analyseLabels(labels, Wi, Hi, items.length);
      const x0 = v.x - opts.pad;
      const y0 = v.y - opts.pad;
      const vis: Visibility[] = [];
      items.forEach((it, i) => {
        if (!a.count[i] || it.item.itemNo == null) return;
        const p = a.anchor[i];
        vis.push({ view: v.view, id: it.item.id, itemNo: it.item.itemNo, area: a.count[i] / (opts.idPxPerMm * opts.idPxPerMm), anchor: [x0 + ((p % Wi) + 0.5) / opts.idPxPerMm, y0 + (Math.floor(p / Wi) + 0.5) / opts.idPxPerMm] });
      });
      out.push({ view: v.view, href, x: x0, y: y0, w: wMm, h: hMm, vis });
      await nextTick();
    }
  } finally {
    faceMat.dispose();
    for (const m of idMats) m.dispose();
  }
  return out;
}
