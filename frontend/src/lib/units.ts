import type { Units, Vec3 } from '../api/types';

export const UNIT_FACTORS: Record<Units, number> = { mm: 1, cm: 10, m: 1000, in: 25.4 };
export const UNIT_LABELS: Record<Units, string> = { mm: 'millimetres (mm)', cm: 'centimetres (cm)', m: 'metres (m)', in: 'inches (in)' };

export interface UnitAdvice {
  /** unit the extents suggest, if not millimetres */
  suggest: Units | null;
  warnings: string[];
}

/**
 * Units advice for a freshly added STL (Addendum 2.1 step 4). The default stays millimetres; a warning is shown
 * when the extents suggest inches (25.4×) or metres (1000×), or when the part would not fit the 3U length.
 * `extents` are the raw file numbers (what the part measures if read as millimetres).
 */
export function unitAdvice(extents: Vec3, chosen: Units, enclosureLengthMm = 340.5, enclosureWidthMm = 100): UnitAdvice {
  const L = Math.max(...extents.map((v) => (Number.isFinite(v) ? Math.abs(v) : 0)));
  const warnings: string[] = [];
  let suggest: Units | null = null;
  const n = (v: number) => (v >= 100 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toPrecision(2));
  if (L <= 0) {
    warnings.push('The mesh has no size (all vertices coincide).');
    return { suggest, warnings };
  }
  if (L < 0.5) {
    suggest = 'm';
    warnings.push(`Read as millimetres the largest size is only ${n(L)} mm. If the file is in metres it is ${n(L * 1000)} mm.`);
  } else if (L < 15) {
    suggest = 'in';
    warnings.push(`Read as millimetres the largest size is only ${n(L)} mm. If the file is in inches it is ${n(L * 25.4)} mm.`);
  }
  const scaled = extents.map((v) => Math.abs(v) * UNIT_FACTORS[chosen]);
  const sorted = [...scaled].sort((a, b) => a - b);
  if (sorted[2] > enclosureLengthMm) warnings.push(`In ${chosen} the part is ${n(sorted[2])} mm long — longer than the ${enclosureLengthMm} mm 3U enclosure.`);
  else if (sorted[1] > enclosureWidthMm) warnings.push(`In ${chosen} the part's second-largest size is ${n(sorted[1])} mm — wider than the ${enclosureWidthMm} mm cross-section in every orientation.`);
  return { suggest, warnings };
}
