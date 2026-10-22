// Mass-property aggregation from backend-supplied per-part properties (protocol §E.3).
// The front end never integrates mesh buffers for physics; it only combines float64 per-part values the backend
// sent (COM in the canonical frame, inertia about the part COM) with poses. Results of this module are shown
// as "local recompute" until the backend confirms them (protocol §I.5).

import type { Limits, Mat3, Metrics, Part, Pose, Vec3 } from '../api/types';
import { eigSym3, matchPrincipalFrame, matMul, matVec, transpose, trace } from './math3';

export interface PartWorld {
  part_id: string;
  mass_kg: number;
  com_mm: Vec3;
  /** inertia about the part's own COM, world axes, kg·m² */
  inertia_kgm2: Mat3;
}

export interface Contribution {
  part_id: string;
  mass_kg: number;
  /** distance from part COM to assembly COM, mm */
  d_mm: number;
  /** tr of the part's own inertia, kg·m² */
  self_trace_kgm2: number;
  /** parallel-axis term 2·m·‖d‖², kg·m² */
  parallel_trace_kgm2: number;
  /** COM lever m_i / M (mm of assembly COM per mm of part move) */
  lever: number;
}

export interface Aggregate {
  mass_kg: number;
  com_mm: Vec3;
  inertia_kgm2: Mat3;
  principal_kgm2: Vec3;
  principal_axes: Mat3;
  lambda_max_kgm2: number;
  trace_kgm2: number;
  products_norm_kgm2: number;
  kappa: number;
  tilt_deg: number;
  axes_degenerate: boolean;
  contributions: Contribution[];
  included: string[];
  excluded: string[];
}

export function rotationFor(rotations: Mat3[], orient: number): Mat3 {
  const R = rotations[orient];
  if (!R) throw new Error(`orientation ${orient} is not in the rotation table (${rotations.length} entries)`);
  return R;
}

/** World COM and world-axes inertia for one part at a pose. c_w = R·c + t; I_w = R·I·Rᵀ. */
export function partWorld(part: Part, pose: Pose, rotations: Mat3[], massOverride?: number): PartWorld | null {
  if (part.mass_kg == null || part.com_canonical_mm == null || part.inertia_com_kgm2 == null) return null;
  const R = rotationFor(rotations, pose.orient);
  const t: Vec3 = [pose.t_um[0] / 1000, pose.t_um[1] / 1000, pose.t_um[2] / 1000];
  const c = matVec(R, part.com_canonical_mm);
  const mass = massOverride ?? part.mass_kg;
  // geometry never changes: I scales with m_new / m_old (protocol §E.2)
  const s = part.mass_kg > 0 ? mass / part.mass_kg : 0;
  const I = matMul(matMul(R, part.inertia_com_kgm2), transpose(R)).map((r) => r.map((v) => v * s)) as Mat3;
  return { part_id: part.id, mass_kg: mass, com_mm: [c[0] + t[0], c[1] + t[1], c[2] + t[2]], inertia_kgm2: I };
}

/** Assemble totals: M = Σm, C = Σm·c / M, I_C = Σ[I_w + m(‖d‖²E − d·dᵀ)], d = c − C (d in metres). */
export function aggregate(
  parts: Record<string, Part> | Part[],
  poses: Pose[],
  rotations: Mat3[],
  massOverrides: Record<string, number> = {},
): Aggregate {
  const byId: Record<string, Part> = Array.isArray(parts) ? Object.fromEntries(parts.map((p) => [p.id, p])) : parts;
  const worlds: PartWorld[] = [];
  const excluded: string[] = [];
  for (const pose of poses) {
    const part = byId[pose.part_id];
    const w = part ? partWorld(part, pose, rotations, massOverrides[pose.part_id]) : null;
    if (w) worlds.push(w);
    else excluded.push(pose.part_id);
  }
  const M = worlds.reduce((s, w) => s + w.mass_kg, 0);
  const C: Vec3 = [0, 0, 0];
  if (M > 0) for (const w of worlds) for (let k = 0; k < 3; k++) C[k] += (w.mass_kg * w.com_mm[k]) / M;
  const I: Mat3 = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  const contributions: Contribution[] = [];
  for (const w of worlds) {
    const d: Vec3 = [(w.com_mm[0] - C[0]) / 1000, (w.com_mm[1] - C[1]) / 1000, (w.com_mm[2] - C[2]) / 1000];
    const d2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2];
    for (let i = 0; i < 3; i++)
      for (let j = 0; j < 3; j++) I[i][j] += w.inertia_kgm2[i][j] + w.mass_kg * ((i === j ? d2 : 0) - d[i] * d[j]);
    contributions.push({
      part_id: w.part_id,
      mass_kg: w.mass_kg,
      d_mm: Math.sqrt(d2) * 1000,
      self_trace_kgm2: trace(w.inertia_kgm2),
      parallel_trace_kgm2: 2 * w.mass_kg * d2,
      lever: M > 0 ? w.mass_kg / M : 0,
    });
  }
  // symmetrise against round-off
  for (let i = 0; i < 3; i++)
    for (let j = i + 1; j < 3; j++) {
      const a = (I[i][j] + I[j][i]) / 2;
      I[i][j] = a;
      I[j][i] = a;
    }
  const { values, vectors } = eigSym3(I);
  const frame = matchPrincipalFrame(values, vectors);
  const products = Math.sqrt(I[0][1] ** 2 + I[0][2] ** 2 + I[1][2] ** 2);
  let kappa = 0;
  for (const [i, j] of [
    [0, 1],
    [0, 2],
    [1, 2],
  ] as const) {
    const den = Math.sqrt(Math.abs(I[i][i] * I[j][j]));
    if (den > 0) kappa = Math.max(kappa, Math.abs(I[i][j]) / den);
  }
  return {
    mass_kg: M,
    com_mm: C,
    inertia_kgm2: I,
    principal_kgm2: values,
    principal_axes: frame.axes,
    lambda_max_kgm2: values[2],
    trace_kgm2: values[0] + values[1] + values[2],
    products_norm_kgm2: products,
    kappa,
    tilt_deg: frame.tiltDeg,
    axes_degenerate: frame.degenerate,
    contributions,
    included: worlds.map((w) => w.part_id),
    excluded,
  };
}

/** Axis-aligned world bounds of a part at a pose (exact for the 24 axis-permutation rotations). */
export function partWorldAabb(part: Part, pose: Pose, rotations: Mat3[]): { min: Vec3; max: Vec3 } {
  const R = rotationFor(rotations, pose.orient);
  const e = part.extents_mm;
  const half = [0, 1, 2].map((r) => (Math.abs(R[r][0]) * e[0] + Math.abs(R[r][1]) * e[1] + Math.abs(R[r][2]) * e[2]) / 2);
  const c = pose.t_um.map((v) => v / 1000);
  return {
    min: [c[0] - half[0], c[1] - half[1], c[2] - half[2]],
    max: [c[0] + half[0], c[1] + half[1], c[2] + half[2]],
  };
}

export interface MetricsContext {
  rotations: Mat3[];
  limits: Limits;
  enclosureZ: [number, number];
  enclosureVolumeMm3: number;
  targetComMm: Vec3;
  compactness: 'one_end' | 'span';
}

/**
 * Full metric set for a layout, computed from part properties (used by the MOCK backend and for the
 * "local recompute" after a mass edit). Returns the contract's Metrics shape; fields this module cannot
 * compute (largest empty box, clearances, cable, cost, insertion order) are null.
 */
export function computeMetrics(
  parts: Record<string, Part>,
  poses: Pose[],
  ctx: MetricsContext,
  massOverrides: Record<string, number> = {},
): Metrics {
  const agg = aggregate(parts, poses, ctx.rotations, massOverrides);
  let top = -Infinity;
  let bottom = Infinity;
  let solid = 0;
  for (const pose of poses) {
    const p = parts[pose.part_id];
    if (!p) continue;
    const bb = partWorldAabb(p, pose, ctx.rotations);
    top = Math.max(top, bb.max[2]);
    bottom = Math.min(bottom, bb.min[2]);
    solid += p.volume_mm3 ?? 0;
  }
  const z0 = ctx.enclosureZ[0];
  const lengthUsed = Number.isFinite(top) ? top - z0 : null;
  const span = Number.isFinite(top) && Number.isFinite(bottom) ? top - bottom : null;
  const box = ctx.limits.com_box_mm ?? [20, 20, 70];
  const margin: Vec3 = [box[0] - Math.abs(agg.com_mm[0]), box[1] - Math.abs(agg.com_mm[1]), box[2] - Math.abs(agg.com_mm[2])];
  const dx = agg.com_mm.map((v, k) => v - ctx.targetComMm[k]);
  return {
    length_used_mm: lengthUsed,
    span_mm: span,
    space_used: ctx.enclosureVolumeMm3 > 0 ? solid / ctx.enclosureVolumeMm3 : null,
    largest_empty_box_mm: null,
    mass_kg: agg.mass_kg,
    com_mm: agg.com_mm,
    com_error_mm: Math.sqrt(dx[0] ** 2 + dx[1] ** 2 + dx[2] ** 2),
    com_box_ok: margin.every((m) => m >= 0),
    com_box_margin_mm: margin,
    inertia_kgm2: agg.inertia_kgm2,
    principal_kgm2: agg.principal_kgm2,
    principal_axes: agg.principal_axes,
    lambda_max_kgm2: agg.lambda_max_kgm2,
    trace_kgm2: agg.trace_kgm2,
    products_norm_kgm2: agg.products_norm_kgm2,
    kappa: agg.kappa,
    tilt_deg: agg.tilt_deg,
    min_clearance_mm: null,
    margin_objective: null,
    cable_blocked_fraction: null,
    hardware_cost_rel: null,
    insertion_order: null,
    interlocked: [],
  };
}

/** Products of inertia P_ij = +∫ x_i x_j dm = −I_ij (protocol §E.1), as a separate labelled table. */
export function productsOfInertia(I: Mat3): { Pxy: number; Pxz: number; Pyz: number } {
  return { Pxy: -I[0][1], Pxz: -I[0][2], Pyz: -I[1][2] };
}

/** Objective weights from slider values: w_k = (s_k + 1) / Σ(s_j + 1) over the active sliders (protocol §F.4). */
export function normalisedWeights<K extends string>(sliders: Record<K, number>, active: K[]): Record<K, number> {
  const total = active.reduce((s, k) => s + sliders[k] + 1, 0);
  const out = {} as Record<K, number>;
  for (const k of active) out[k] = total > 0 ? (sliders[k] + 1) / total : 0;
  return out;
}
