import * as THREE from 'three';
import { acceleratedRaycast, computeBoundsTree, disposeBoundsTree } from 'three-mesh-bvh';
import { useEffect, useState } from 'react';
import type { Mat3, Part, Pose } from '../../api/types';
import { hasSession, session } from '../../api/session';
import type { MeshData } from '../../api/rest';

// three-mesh-bvh picking (firstHitOnly is set on the raycaster in the canvas)
const proto = THREE.BufferGeometry.prototype as unknown as { computeBoundsTree: unknown; disposeBoundsTree: unknown };
proto.computeBoundsTree = computeBoundsTree;
proto.disposeBoundsTree = disposeBoundsTree;
THREE.Mesh.prototype.raycast = acceleratedRaycast;

export interface PartGeometry {
  geometry: THREE.BufferGeometry;
  edges: THREE.BufferGeometry;
  triangles: number;
}

const cache = new Map<string, Promise<PartGeometry>>();

export function buildGeometry(m: MeshData, edgeAngleDeg = 30): PartGeometry {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(m.positions, 3));
  g.setIndex(new THREE.BufferAttribute(m.indices, 1));
  g.computeVertexNormals();
  g.computeBoundingBox();
  g.computeBoundingSphere();
  try {
    (g as unknown as { computeBoundsTree: () => void }).computeBoundsTree();
  } catch {
    /* BVH is an optimisation only */
  }
  const edges = new THREE.EdgesGeometry(g, edgeAngleDeg);
  return { geometry: g, edges, triangles: m.indices.length / 3 };
}

export function partKey(p: Pick<Part, 'id' | 'sha256' | 'units' | 'units_confirmed'>): string {
  return `${p.id}:${p.sha256}:${p.units}:${p.units_confirmed}`;
}

export function loadPartGeometry(p: Part): Promise<PartGeometry> {
  const key = partKey(p);
  let pr = cache.get(key);
  if (!pr) {
    pr = session()
      .api.mesh(p.id, 'display')
      .then((m) => buildGeometry(m));
    pr.catch(() => cache.delete(key));
    cache.set(key, pr);
  }
  return pr;
}

export function usePartGeometry(p: Part | undefined | null): PartGeometry | null {
  const [g, setG] = useState<PartGeometry | null>(null);
  const key = p ? partKey(p) : '';
  useEffect(() => {
    if (!p || p.status === 'NEEDS_UNITS' || p.status === 'ANALYSING' || !hasSession()) {
      setG(null);
      return;
    }
    let alive = true;
    loadPartGeometry(p).then(
      (r) => alive && setG(r),
      () => alive && setG(null),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return g;
}

// Extra items' meshes (brackets, standoffs, PC/104 rods), cached by URL. Every new best layout brings new URLs (its own
// bracket boxes), so during a long search the cache would grow without end: an entry no view shows any more is kept
// among the ITEM_KEEP most recently used and freed after that (GPU buffers, edges, BVH). An entry a view still shows
// is never freed.
export const ITEM_KEEP = 120;
interface ItemEntry {
  promise: Promise<PartGeometry>;
  /** views showing it now */
  refs: number;
  /** when it was last taken or given back (a counter) */
  used: number;
}
const itemCache = new Map<string, ItemEntry>();
let itemClock = 0;

export function disposeGeometry(g: PartGeometry): void {
  (g.geometry as unknown as { disposeBoundsTree?: () => void }).disposeBoundsTree?.();
  g.geometry.dispose();
  g.edges.dispose();
}

/** Take an item's mesh for a view (loaded once per URL); give it back with releaseItemGeometry. */
export function acquireItemGeometry(url: string, load: (url: string) => Promise<MeshData> = (u) => session().api.itemMesh(u)): Promise<PartGeometry> {
  let e = itemCache.get(url);
  if (!e) {
    const entry: ItemEntry = { promise: load(url).then((m) => buildGeometry(m)), refs: 0, used: 0 };
    entry.promise.catch(() => {
      if (itemCache.get(url) === entry) itemCache.delete(url);
    });
    itemCache.set(url, entry);
    e = entry;
  }
  e.refs += 1;
  e.used = ++itemClock;
  return e.promise;
}

export function releaseItemGeometry(url: string): void {
  const e = itemCache.get(url);
  if (!e) return;
  e.refs = Math.max(0, e.refs - 1);
  e.used = ++itemClock;
  if (e.refs === 0) trimItemCache();
}

/** Free the least recently used item meshes that no view shows, beyond `keep`; returns how many were freed. */
export function trimItemCache(keep = ITEM_KEEP): number {
  const idle = [...itemCache.entries()].filter(([, e]) => e.refs === 0).sort((a, b) => a[1].used - b[1].used);
  const drop = idle.slice(0, Math.max(0, idle.length - keep));
  for (const [url, e] of drop) {
    itemCache.delete(url);
    e.promise.then(disposeGeometry, () => undefined);
  }
  return drop.length;
}

/** Test helper: the item cache's size and how many entries a view shows. */
export function itemCacheStats(): { entries: number; inUse: number } {
  return { entries: itemCache.size, inUse: [...itemCache.values()].filter((e) => e.refs > 0).length };
}

export function useItemGeometry(url: string | null | undefined): PartGeometry | null {
  const [g, setG] = useState<PartGeometry | null>(null);
  useEffect(() => {
    if (!url || !hasSession()) return;
    let alive = true;
    acquireItemGeometry(url).then(
      (r) => alive && setG(r),
      () => alive && setG(null),
    );
    return () => {
      alive = false;
      releaseItemGeometry(url);
    };
  }, [url]);
  return g;
}

/** Pose → world matrix: world = R[orient] · p_canonical + t_um / 1000 (contract §1). */
export function poseMatrix(pose: Pose, rotations: Mat3[]): THREE.Matrix4 {
  const R = rotations[pose.orient] ?? [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
  ];
  const t = pose.t_um.map((v) => v / 1000);
  return new THREE.Matrix4().set(R[0][0], R[0][1], R[0][2], t[0], R[1][0], R[1][1], R[1][2], t[1], R[2][0], R[2][1], R[2][2], t[2], 0, 0, 0, 1);
}

export function poseTRS(pose: Pose, rotations: Mat3[]): { position: THREE.Vector3; quaternion: THREE.Quaternion } {
  const m = poseMatrix(pose, rotations);
  const position = new THREE.Vector3();
  const quaternion = new THREE.Quaternion();
  const scl = new THREE.Vector3();
  m.decompose(position, quaternion, scl);
  return { position, quaternion };
}

/** Test helper: clear caches between projects. */
export function clearGeometryCache(): void {
  cache.clear();
  for (const e of itemCache.values()) e.promise.then(disposeGeometry, () => undefined);
  itemCache.clear();
}
