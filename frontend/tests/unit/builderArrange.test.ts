import { describe, expect, it } from 'vitest';
import type { Analysis, Pick, PickItem } from '../../src/builder/analysisTypes';
import { arrange, OUTER_MM } from '../../src/builder/arrange';

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

  it('uses lanes across a 6U so small parts sit side by side', () => {
    const a = design(6, [pk('obc', 'internal', [item('a', [90, 90, 20]), item('b', [90, 90, 20])])]);
    const { boxes } = arrange(a);
    expect(boxes[0].center[0]).not.toBeCloseTo(boxes[1].center[0]);
    expect(boxes[0].center[2]).toBeCloseTo(boxes[1].center[2]);
  });
});
