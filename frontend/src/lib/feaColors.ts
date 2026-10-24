// FEA colour maps of the designed brackets (Components tab). Magnitude is one hue, light <-> dark: the documented blue
// sequential ramp, steps 100 -> 700 (dataviz skill: sequential = one hue, never a rainbow), flipped on a dark surface
// so that low values recede into it and high values stand out. A utilisation of 1 or more (a negative margin) shows in
// the critical status colour, and the legend always names it with an icon and a label, never by colour alone.
import * as THREE from 'three';
import type { FeaField } from '../api/types';

/** Documented blue ramp, step 100 (lightest) to step 700 (darkest). */
export const BLUE_RAMP = ['#cde2fb', '#b7d3f6', '#9ec5f4', '#86b6ef', '#6da7ec', '#5598e7', '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b'];
/** Status: critical (fixed, never a series colour). */
export const CRITICAL = '#d03b3b';
/** The 3D views' background (always dark): the colour maps are drawn on it. */
export const VIEWPORT_BG = '#26282C';

function rgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

/** Ramp steps from low to high: on a dark surface the darkest step is low, on a light one the lightest. */
export function rampSteps(darkSurface: boolean): string[] {
  return darkSurface ? [...BLUE_RAMP].reverse() : BLUE_RAMP;
}

/** sRGB colour (0…1 each) of t in [0, 1] along the ramp (linear between the documented steps). */
export function rampRgb(t: number, darkSurface: boolean): [number, number, number] {
  const steps = rampSteps(darkSurface);
  const x = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0)) * (steps.length - 1);
  const i = Math.min(steps.length - 2, Math.floor(x));
  const f = x - i;
  const a = rgb(steps[i]);
  const b = rgb(steps[i + 1]);
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

export interface FieldScale {
  min: number;
  max: number;
  /** values at or above it (a utilisation of 1: zero margin) take the critical colour */
  threshold: number | null;
}

/** Colour scale of a field: utilisation 0…1 with the threshold at 1; stress and displacement 0 … their largest value
 * over every voxel (the number the margins use), so the top of the legend is that number. */
export function scaleFor(f: FeaField): FieldScale {
  if (f.kind === 'utilisation') return { min: 0, max: 1, threshold: 1 };
  return { min: 0, max: f.max_all > 0 ? f.max_all : 1, threshold: null };
}

/** Per-vertex colours for a three.js colour attribute (linear RGB, as three.js expects of vertex colours). */
export function vertexColors(values: ArrayLike<number>, scale: FieldScale, darkSurface: boolean): Float32Array {
  const out = new Float32Array(values.length * 3);
  const c = new THREE.Color();
  const crit = new THREE.Color().setStyle(CRITICAL, THREE.SRGBColorSpace);
  const span = scale.max - scale.min || 1;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (scale.threshold != null && v >= scale.threshold) c.copy(crit);
    else {
      const [r, g, b] = rampRgb((v - scale.min) / span, darkSurface);
      c.setRGB(r, g, b, THREE.SRGBColorSpace);
    }
    out[3 * i] = c.r;
    out[3 * i + 1] = c.g;
    out[3 * i + 2] = c.b;
  }
  return out;
}

/** CSS gradient of the ramp, low (left) to high (right). */
export function rampGradient(darkSurface: boolean): string {
  const s = rampSteps(darkSurface);
  return `linear-gradient(to right, ${s.map((h, i) => `${h} ${((100 * i) / (s.length - 1)).toFixed(1)}%`).join(', ')})`;
}

/** A value as the legend and the tooltips write it. */
export function fieldValueText(v: number, f: Pick<FeaField, 'unit' | 'kind'>): string {
  if (!Number.isFinite(v)) return '—';
  if (f.kind === 'utilisation') return v.toFixed(2);
  const a = Math.abs(v);
  const s = a === 0 ? '0' : a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : a >= 1 ? v.toFixed(2) : a >= 0.01 ? v.toFixed(3) : v.toExponential(1);
  return `${s} ${f.unit}`.trim();
}

export interface CheckBar {
  key: string;
  label: string;
  /** factor × stress / allowable: 1 = zero margin */
  u: number;
  ms: number;
  gates: boolean;
  detail: string;
}

/** Every check of a design as a utilisation bar (1 / (1 + MS)), largest first: the bracket body per load case and axis
 * (the smaller of the yield and ultimate margins) and the worst bolt per load case and axis. */
export function checkBars(
  checks: { case: string; axis: string; sigma_mpa: number; factor_yield: number; factor_ult: number; ms_yield: number; ms_ult: number; gates: boolean }[] | undefined,
  bolts: { case: string; axis: string; check: string; ms: number; bolt?: number; gates: boolean }[] | undefined,
): CheckBar[] {
  const out: CheckBar[] = [];
  for (const r of checks ?? []) {
    const ms = Math.min(r.ms_yield, r.ms_ult);
    out.push({
      key: `body:${r.case}:${r.axis}`,
      label: `${r.case}, ${r.axis}`,
      u: 1 / (1 + ms),
      ms,
      gates: r.gates,
      detail: `bracket: ${r.sigma_mpa.toFixed(1)} MPa × factors ${r.factor_yield} / ${r.factor_ult}; MS yield ${r.ms_yield >= 0 ? '+' : ''}${r.ms_yield.toFixed(2)}, ultimate ${r.ms_ult >= 0 ? '+' : ''}${r.ms_ult.toFixed(2)}`,
    });
  }
  for (const r of bolts ?? []) {
    out.push({
      key: `bolt:${r.case}:${r.axis}:${r.check}`,
      label: `bolts: ${r.case}, ${r.axis}`,
      u: 1 / (1 + r.ms),
      ms: r.ms,
      gates: r.gates,
      detail: `${r.check}${r.bolt != null ? `, bolt ${r.bolt + 1}` : ''}; MS ${r.ms >= 0 ? '+' : ''}${r.ms.toFixed(2)}`,
    });
  }
  return out.filter((b) => Number.isFinite(b.u)).sort((a, b) => b.u - a.u);
}
