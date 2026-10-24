import { describe, expect, it, vi } from 'vitest';
import type { MeshData } from '../../src/api/rest';
import { acquireItemGeometry, clearGeometryCache, ITEM_KEEP, itemCacheStats, releaseItemGeometry, trimItemCache } from '../../src/components/viewport/geometry';
import { remember } from '../../src/components/drawing/render';

const tri = (): MeshData => ({ positions: new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]), indices: new Uint32Array([0, 1, 2]) });
const settle = () => new Promise((r) => setTimeout(r, 0));

describe('3D view item meshes (brackets, standoffs, rods)', () => {
  it('loads a URL once, never frees a mesh a view shows, and keeps only ITEM_KEEP idle meshes', async () => {
    clearGeometryCache();
    const load = vi.fn(async () => tri());
    const shown = await acquireItemGeometry('/api/items/L-1-br0/mesh', load);
    expect(await acquireItemGeometry('/api/items/L-1-br0/mesh', load)).toBe(shown); // a second view of it
    expect(load).toHaveBeenCalledTimes(1);
    const dispose = vi.spyOn(shown.geometry, 'dispose');
    for (let k = 0; k < ITEM_KEEP + 50; k++) {
      // a long search: every new best layout's brackets are shown, then replaced
      const url = `/api/items/L-${k + 2}-br0/mesh`;
      await acquireItemGeometry(url, load);
      releaseItemGeometry(url);
    }
    expect(itemCacheStats()).toEqual({ entries: ITEM_KEEP + 1, inUse: 1 });
    await settle();
    expect(dispose).not.toHaveBeenCalled();
    releaseItemGeometry('/api/items/L-1-br0/mesh');
    releaseItemGeometry('/api/items/L-1-br0/mesh'); // both views gave it back: idle, the most recent
    expect(itemCacheStats()).toEqual({ entries: ITEM_KEEP, inUse: 0 });
    expect(trimItemCache(0)).toBe(ITEM_KEEP);
    await settle();
    expect(dispose).toHaveBeenCalled(); // GPU buffers freed
    expect(itemCacheStats().entries).toBe(0);
  });

  it('does not keep a mesh that failed to load', async () => {
    clearGeometryCache();
    const bad = vi.fn(async (): Promise<MeshData> => {
      throw new Error('404');
    });
    await expect(acquireItemGeometry('/api/items/L-9-br0/mesh', bad)).rejects.toThrow('404');
    await settle();
    expect(itemCacheStats().entries).toBe(0);
    releaseItemGeometry('/api/items/L-9-br0/mesh'); // the view giving it back is harmless
  });
});

describe('drawings mesh cache', () => {
  it('keeps the most recently used entries and frees the oldest', () => {
    const m = new Map<string, number>();
    const freed: number[] = [];
    for (let i = 0; i < 5; i++) remember(m, `k${i}`, i, 3, (v) => freed.push(v));
    expect([...m.keys()]).toEqual(['k2', 'k3', 'k4']);
    expect(freed).toEqual([0, 1]);
    remember(m, 'k2', 2, 3, (v) => freed.push(v)); // used again: now the most recent
    remember(m, 'k5', 5, 3, (v) => freed.push(v));
    expect([...m.keys()]).toEqual(['k4', 'k2', 'k5']);
    expect(freed).toEqual([0, 1, 3]);
  });
});
