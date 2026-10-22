import { describe, expect, it } from 'vitest';
import type { Part, Pose } from '../../src/api/types';
import { aggregate, computeMetrics, normalisedWeights, partWorld, productsOfInertia } from '../../src/lib/physics';
import { normaliseRotations, det3, eigSym3, matchPrincipalFrame } from '../../src/lib/math3';
import { loadFixtures } from './helpers';

const fx = loadFixtures();
const rotations = normaliseRotations(fx.project.rotations);
const parts = Object.fromEntries(fx.project.parts.map((p) => [p.id, p])) as Record<string, Part>;
const battery = fx.project.parts.find((p) => p.name === 'battery_pack')!;

describe('rotation table from the project snapshot', () => {
  it('has 24 proper rotations with identity first', () => {
    expect(rotations).toHaveLength(24);
    expect(rotations[0]).toEqual([
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 1],
    ]);
    for (const R of rotations) expect(det3(R)).toBe(1);
  });
});

describe('mass / COM aggregation from part data (T-UI2)', () => {
  it('battery alone: COM at its pose, I_xx = 2.181e-4 kg·m², mass 0.380 kg', () => {
    const pose: Pose = { part_id: battery.id, orient: 0, t_um: [40000, 40000, 11000] };
    const a = aggregate([battery], [pose], rotations);
    expect(a.mass_kg).toBeCloseTo(0.38016, 6);
    expect(a.com_mm[0]).toBeCloseTo(40, 9);
    expect(a.com_mm[1]).toBeCloseTo(40, 9);
    expect(a.com_mm[2]).toBeCloseTo(11, 9);
    expect(a.inertia_kgm2[0][0]).toBeCloseTo(2.1808e-4, 7);
    expect(Number(a.inertia_kgm2[0][0].toPrecision(4))).toBe(2.181e-4);
    expect(a.inertia_kgm2[2][2]).toBeCloseTo(4.0550e-4, 7);
    expect(Math.abs(a.inertia_kgm2[0][1])).toBeLessThan(1e-18);
  });

  it('total mass of the 19 parts is 2.916 kg (ASSUMED 2,700 kg/m³)', () => {
    const poses = fx.layouts[0].poses;
    const a = aggregate(parts, poses, rotations);
    expect(a.included).toHaveLength(19);
    expect(a.mass_kg).toBeCloseTo(2.916, 3);
    // COM = Σ m c / M
    let M = 0;
    const S = [0, 0, 0];
    for (const pose of poses) {
      const w = partWorld(parts[pose.part_id], pose, rotations)!;
      M += w.mass_kg;
      for (let k = 0; k < 3; k++) S[k] += w.mass_kg * w.com_mm[k];
    }
    for (let k = 0; k < 3; k++) expect(a.com_mm[k]).toBeCloseTo(S[k] / M, 9);
  });

  it('rotating a part maps its inertia as R·I·Rᵀ', () => {
    // find an orientation that maps canonical z to world x
    const o = rotations.findIndex((R) => R[0][2] !== 0);
    const a = aggregate([battery], [{ part_id: battery.id, orient: o, t_um: [0, 0, 0] }], rotations);
    expect(a.inertia_kgm2[0][0]).toBeCloseTo(battery.inertia_com_kgm2![2][2], 12);
  });

  it('parallel-axis theorem: two batteries ±50 mm along x', () => {
    const a = aggregate(
      [battery],
      [
        { part_id: battery.id, orient: 0, t_um: [-50000, 0, 0] },
        { part_id: battery.id, orient: 0, t_um: [50000, 0, 0] },
      ],
      rotations,
    );
    const m = battery.mass_kg!;
    const I = battery.inertia_com_kgm2!;
    expect(a.com_mm[0]).toBeCloseTo(0, 9);
    expect(a.inertia_kgm2[0][0]).toBeCloseTo(2 * I[0][0], 12);
    expect(a.inertia_kgm2[1][1]).toBeCloseTo(2 * I[1][1] + 2 * m * 0.05 ** 2, 12);
    expect(a.inertia_kgm2[2][2]).toBeCloseTo(2 * I[2][2] + 2 * m * 0.05 ** 2, 12);
    // trace identity tr(I_C) = Σ tr(I_i) + 2 Σ m_i ‖d_i‖²
    const tr = a.contributions.reduce((s, c) => s + c.self_trace_kgm2 + c.parallel_trace_kgm2, 0);
    expect(a.trace_kgm2).toBeCloseTo(tr, 12);
  });

  it('a mass edit scales the part inertia by m_new / m_old and never moves the part COM', () => {
    const pose: Pose = { part_id: battery.id, orient: 0, t_um: [1000, 2000, 3000] };
    const a = aggregate([battery], [pose], rotations, { [battery.id]: 2 * battery.mass_kg! });
    expect(a.mass_kg).toBeCloseTo(2 * battery.mass_kg!, 12);
    expect(a.inertia_kgm2[0][0]).toBeCloseTo(2 * battery.inertia_com_kgm2![0][0], 12);
    [1, 2, 3].forEach((v, k) => expect(a.com_mm[k]).toBeCloseTo(v, 12));
  });

  it('products of inertia table is P = −I off-diagonal', () => {
    const P = productsOfInertia([
      [1, -2, 3],
      [-2, 4, -5],
      [3, -5, 6],
    ]);
    expect(P).toEqual({ Pxy: 2, Pxz: -3, Pyz: 5 });
  });

  it('principal frame: eigenvalues ascending, tilt 0 for a diagonal tensor', () => {
    const { values, vectors } = eigSym3([
      [3, 0, 0],
      [0, 1, 0],
      [0, 0, 2],
    ]);
    expect(values).toEqual([1, 2, 3]);
    const f = matchPrincipalFrame(values, vectors);
    expect(f.tiltDeg).toBeCloseTo(0, 9);
    expect(f.moments).toEqual([3, 1, 2]);
  });

  it('metrics for the fixture placeholder layout: length used and CDS box margins', () => {
    const m = computeMetrics(parts, fx.layouts[0].poses, {
      rotations,
      limits: fx.project.limits,
      enclosureZ: [-170.25, 170.25],
      enclosureVolumeMm3: 100 * 100 * 340.5,
      targetComMm: [0, 0, 0],
      compactness: 'one_end',
    });
    expect(m.length_used_mm!).toBeGreaterThan(108); // above the solid-volume lower bound
    expect(m.length_used_mm!).toBeLessThanOrEqual(340.5);
    expect(m.space_used!).toBeCloseTo(1080000 / 3405000, 3);
    expect(m.com_box_margin_mm![2]).toBeCloseTo(70 - Math.abs(m.com_mm![2]), 9);
  });

  it('weights w_k = (s_k + 1) / Σ(s_j + 1) are always positive', () => {
    const w = normalisedWeights({ space: 0, balance: 0, inertia: 100 }, ['space', 'balance', 'inertia']);
    expect(w.space).toBeCloseTo(1 / 103, 12);
    expect(w.inertia).toBeCloseTo(101 / 103, 12);
  });
});
