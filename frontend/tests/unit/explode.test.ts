import { describe, expect, it } from 'vitest';
import { EXPLODE_GAIN, explodeOffsets } from '../../src/lib/explode';
import { createAppStore } from '../../src/store/store';

const layout = {
  poses: [
    { part_id: 'a', orient: 0, t_um: [0, 0, -100000] as [number, number, number] },
    { part_id: 'b', orient: 0, t_um: [20000, 0, 0] as [number, number, number] },
    { part_id: 'c', orient: 0, t_um: [-20000, 0, 100000] as [number, number, number] },
  ],
};

describe('exploded view (V2)', () => {
  it('is the assembled layout at 0 and for no layout', () => {
    expect(explodeOffsets(layout, 0)).toEqual({});
    expect(explodeOffsets(null, 1)).toEqual({});
    expect(explodeOffsets({ poses: [] }, 1)).toEqual({});
  });

  it('pushes every part away from the layout centre in proportion to its distance', () => {
    const o = explodeOffsets(layout, 1);
    // centre of the part origins is (0, 0, 0) mm
    expect(o.a).toEqual([0, 0, -100 * EXPLODE_GAIN]);
    expect(o.b[0]).toBeCloseTo(20 * EXPLODE_GAIN);
    expect(o.c[2]).toBeCloseTo(100 * EXPLODE_GAIN);
    const half = explodeOffsets(layout, 0.5);
    expect(half.c[2]).toBeCloseTo(o.c[2] / 2);
  });

  it('keeps the slider within 0…100 in the store', () => {
    const store = createAppStore();
    store.getState().setExplode(140);
    expect(store.getState().view.explode).toBe(100);
    store.getState().setExplode(-5);
    expect(store.getState().view.explode).toBe(0);
  });
});
