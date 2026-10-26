import { describe, expect, it } from 'vitest';
import type { Analysis, Pick, PickItem } from '../../src/builder/analysisTypes';
import { arrange, axisTurn, drawPlan, MESH_MAX_FACES, OUTER_MM } from '../../src/builder/arrange';

const apply = (m: number[][], v: number[]) => m.map((row) => row.reduce((s, x, j) => s + x * v[j], 0));
const det = (m: number[][]) =>
  m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);

const item = (id: string, dims: number[] | null, qty = 1, name = id): PickItem => ({
  id, name, qty, category: 'x', mass_kg: 0.1, dims_mm: dims, power_w: { typical: null }, price: { value: null, currency: null, kind: 'quote', note: '' }, cad: 'unknown',
});
const pk = (slot: string, place: Pick['place'], items: PickItem[]): Pick => ({ slot, label: slot, items, status: 'recommended', why: '', need: '', alternatives: [], flags: [], place });

function design(size: number, picks: Pick[]): Analysis {
  return {
    size_u: size,
    slots: picks.map((p) => ({ id: p.slot, label: p.slot, place: p.place })),
    picks: Object.fromEntries(picks.map((p) => [p.slot, p])),
  } as unknown as Analysis;
}

describe('V3 Builder: the preview arrangement', () => {
  it('stacks internal parts along the long axis inside the walls', () => {
    const a = design(3, [pk('payload', 'internal', [item('cam', [95, 90, 120])]), pk('obc', 'internal', [item('obc', [96, 90, 6])]), pk('structure', 'frame', [item('frame', [100, 100, 340.5])])]);
    const { outer, boxes } = arrange(a);
    expect(outer).toEqual(OUTER_MM[3]);
    expect(boxes.map((b) => b.id.split('#')[0])).toEqual(['cam', 'obc']);       // largest first; the frame is not a box
    const [cam, obc] = boxes;
    expect(cam.center[2] - cam.size[2] / 2).toBeCloseTo(-outer[2] / 2 + 2);       // starts at the inner end wall
    expect(obc.center[2] - obc.size[2] / 2).toBeCloseTo(cam.center[2] + cam.size[2] / 2 + 2);
    expect(boxes.every((b) => !b.overflow && !b.external)).toBe(true);
  });

  it('marks what does not fit, stands in for unpublished sizes, and puts external parts outside', () => {
    const a = design(3, [
      pk('payload', 'internal', [item('long', [90, 90, 400])]),
      pk('gnss', 'internal', [item('mystery', null)]),
      pk('solar', 'external', [item('panel', null, 4, 'PHOTON-SIDE')]),
      pk('antenna_ttc', 'external', [item('uhf', [98, 98, 7])]),
    ]);
    const { outer, boxes } = arrange(a);
    expect(boxes.find((b) => b.id.startsWith('long'))!.overflow).toBe(true);
    expect(boxes.find((b) => b.id.startsWith('mystery'))!.unsized).toBe(true);
    const panels = boxes.filter((b) => b.slot === 'solar');
    expect(panels).toHaveLength(4);
    for (const p of panels) expect(Math.max(Math.abs(p.center[0]), Math.abs(p.center[1]))).toBeGreaterThan(outer[0] / 2 - 1e-9);
    const ant = boxes.find((b) => b.slot === 'antenna_ttc')!;
    expect(ant.center[2]).toBeGreaterThan(outer[2] / 2);                          // on the zenith end
    expect(ant.external).toBe(true);
  });

  it('turns an imported model so its sides lie as its box does, never mirrored', () => {
    for (const [extents, size] of [
      [[10, 30, 20], [30, 20, 10]],
      [[95.4, 95.9, 67.3], [95.9, 95.4, 67.3]],          // a swap of two sides alone would mirror the part
      [[5, 90, 96], [96, 90, 5]],
    ]) {
      const m = axisTurn(extents, size);
      expect(apply(m, extents).map(Math.abs)).toEqual(size);
      expect(det(m)).toBe(1);
    }
  });

  it('draws parts with imported CAD as models, unless too detailed, and everything else as boxes', () => {
    const a = design(3, [
      pk('obc', 'internal', [item('kryten', [96, 90, 6])]),
      pk('radio_ttc', 'internal', [item('utrx', [96, 90, 16])]),
      pk('gnss', 'internal', [item('celeste', [67, 42, 7.5])]),
      pk('solar', 'external', [item('panel', [83, 98, 2], 2)]),
    ]);
    const geometry = {
      kryten: { origin: 'manufacturer' as const, origin_text: 'Manufacturer CAD', ok: true, extents_mm: [95.9, 90.2, 5.5], faces: 80_000, imported: 't1' },
      utrx: { origin: 'manufacturer' as const, origin_text: 'Manufacturer CAD', ok: true, extents_mm: [96, 90, 16], faces: MESH_MAX_FACES + 1, imported: 't2' },
      celeste: { origin: 'bbox' as const, origin_text: 'Simplified bounding box', ok: true, extents_mm: [67, 42, 7.5], faces: 12 },
      panel: { origin: 'manufacturer' as const, origin_text: 'Manufacturer CAD', ok: true, extents_mm: [83, 98, 2], faces: 1000, imported: 't3' },
    };
    const plan = drawPlan(arrange(a).boxes, geometry);
    const by = (cid: string) => plan.filter((p) => p.cid === cid);
    expect(by('kryten')[0].model?.imported).toBe('t1');
    expect(by('utrx')[0]).toMatchObject({ model: null, heavy: true });
    expect(by('celeste')[0].model).toBeNull();                 // a simplified box stays a box
    expect(by('panel').every((p) => p.model === null)).toBe(true); // body panels are drawn as panels
  });

  it('uses lanes across a 6U so small parts sit side by side', () => {
    const a = design(6, [pk('obc', 'internal', [item('a', [90, 90, 20]), item('b', [90, 90, 20])])]);
    const { boxes } = arrange(a);
    expect(boxes[0].center[0]).not.toBeCloseTo(boxes[1].center[0]);
    expect(boxes[0].center[2]).toBeCloseTo(boxes[1].center[2]);
  });
});
