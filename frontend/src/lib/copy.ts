// Plain-language copy. Tooltips follow a fixed order: plain sentence → "Technically:" → "Why it matters".
import type { SliderKey } from '../api/types';

export interface Explainer {
  plain: string;
  technical: string;
  why: string;
}

export interface SliderDef extends Explainer {
  key: SliderKey;
  label: string;
  /** only meaningful in Stage 2 */
  stage2Only?: boolean;
  /** greyed out in Stage 1 with this explanation */
  stage1Disabled?: string;
  expertOnly?: boolean;
  /** not listed in the Goals panel (shown in its own tab) */
  notInGoals?: boolean;
  /** what the ends of the slider mean, instead of "priority" */
  ends?: [string, string];
  /** only listed when at least one part is marked optional */
  needsOptional?: boolean;
}

export const SLIDERS: SliderDef[] = [
  {
    key: 'space',
    label: 'Use Space Efficiently',
    plain: 'Packs the parts closer together so less of the spacecraft’s length is used.',
    technical: 'weight of L, the length used from the −Z end face: max over parts of (top z) − z₀, in mm.',
    why: 'free length leaves room for more payload or margin.',
  },
  {
    key: 'balance',
    label: 'Balance the Spacecraft',
    plain: 'Moves heavy parts so the spacecraft’s balance point sits near the middle.',
    technical: 'minimises the distance between the assembly centre of mass and the target point (mm).',
    why: 'launch rules require the balance point within ±20 mm sideways and ±70 mm lengthwise.',
  },
  {
    key: 'inertia',
    label: 'Reduce Rotational Inertia',
    plain: 'Keeps heavy parts close together so the spacecraft is easier to turn.',
    technical: 'weight of I = α·T̂ + (1 − α)·P̂, with T = tr(I_C) and P = √(I_xy² + I_xz² + I_yz²), in kg·m².',
    why: 'lower inertia means faster turns (slews) with the same reaction wheels.',
  },
  {
    key: 'feasibility',
    label: 'Improve Physical Feasibility',
    plain: 'Leaves more room than the minimum gaps between parts and walls.',
    technical: 'weight of G = 1 − min(1, s_min / 5 mm), the slack beyond the hard clearances (Stage 2 only).',
    why: 'extra slack makes assembly and manufacturing tolerances easier.',
    stage1Disabled: 'Stage 1 is idealized; switch to Stage 2 to work on physical feasibility.',
  },
  {
    key: 'cable',
    label: 'Keep cable path clear',
    plain: 'Keeps a channel free along one wall for the wiring harness.',
    technical: 'H = blocked fraction of the chosen 10 mm corridor’s length. At 70 or more the corridor becomes a hard full-length keep-out (continuous-cable mode).',
    why: 'a clear harness path avoids routing cables around parts; it can cost packing.',
    stage2Only: true,
  },
  {
    key: 'cost',
    label: 'Keep hardware cost low',
    plain: 'Prefers placing parts flat against walls and rails so cheap mounts can be used.',
    technical: 'weight of C, the relative hardware cost (ASSUMED cost model, relative units).',
    why: 'custom and metal 3D-printed brackets cost more than direct mounts.',
    stage2Only: true,
    notInGoals: true,
  },
  {
    key: 'bracket_budget',
    label: 'Bracket budget',
    plain: '0 holds every part with simple brackets (machined, sheet metal, clamps). The higher the budget, the more parts get a metal 3D-printed bracket instead; at 100 every bracket that can be 3D-printed is (parts bolted straight to a wall keep their bolts).',
    technical: 'Steps: 0 simple only · 1–33 metal AM only where no simple bracket fits · 34–66 metal AM where it costs ≤ 2× the cheapest simple bracket that fits (replaces cradles) · 67–99 ≤ 10× (also blocks, sheet brackets, clamps) · 100 wherever it fits. Crossing a step restarts the search; the hardware cost C is weighted by (100 − budget) / 100.',
    why: '3D-printed brackets are thinner and follow the part, so parts fit more closely, but they cost more.',
    stage2Only: true,
    ends: ['simple brackets', 'metal 3D-printed'],
  },
  {
    key: 'optional_parts',
    label: 'Include optional parts',
    plain: 'How hard the search tries to fit the parts you marked optional. Optional parts that do not fit are left out instead of making the layout fail.',
    technical: 'weight of O, the share of optional parts left out of a layout (0 = all included).',
    why: 'a nice-to-have part should not block a layout that fits everything essential.',
    needsOptional: true,
  },
  {
    key: 'mass_symmetry',
    label: 'Mass-distribution symmetry',
    plain: 'How much it matters that mass sits symmetrically about the body axes.',
    technical: 'α, the split between the trace T and the products of inertia P inside the inertia objective.',
    why: 'products of inertia couple the axes and tilt the principal frame.',
    expertOnly: true,
  },
  {
    // V2: no longer shown. Its only effect was how long the search waited without improvement before it stopped
    // itself; the search now runs until Pause (the status bar shows a recommended minimum run time instead).
    key: 'speed_quality',
    label: 'Computation: speed ↔ quality',
    plain: 'No effect: the search runs until you press Pause.',
    technical: 'it used to set how long the search waited without improvement before it stopped itself (15 + 6 × value s); the backend’s algorithm selector and search never read it.',
    why: 'the status bar shows a recommended minimum run time instead.',
    expertOnly: true,
    notInGoals: true,
  },
];

export const METRIC_TIPS: Record<string, Explainer> = {
  space: {
    plain: 'Share of the box filled by solid parts.',
    technical: 'Σ part volumes ÷ enclosure volume. It is the same for every layout, because neither the parts nor the box change; compactness is measured by length used instead.',
    why: 'it shows how full the spacecraft is, but it cannot tell two arrangements apart.',
  },
  mass: {
    plain: 'Total mass of all parts.',
    technical: 'M = Σ mᵢ (kg). The CubeSat Design Specification gives 6.00 kg as a typical maximum for 3U (a note, not a limit used by the optimiser).',
    why: 'heavier spacecraft can exceed launcher limits.',
  },
  balance: {
    plain: 'How far the balance point is from the target (the middle by default).',
    technical: '‖C − C*‖₂ in mm. The CDS box is ±20 / ±20 / ±70 mm (displayed in Stage 1, enforced in Stage 2).',
    why: 'launch rules require the balance point inside that box.',
  },
  inertia: {
    plain: 'How hard the spacecraft is to turn about its hardest axis.',
    technical: 'λ_max, the largest principal moment of the assembly inertia tensor about its centre of mass (kg·m²).',
    why: 'the worst axis limits how fast the spacecraft can slew.',
  },
  validity: {
    plain: 'Whether the layout respects engineering rules (walls, rails, clearances, assembly order).',
    technical: 'Stage 2 checks: clearances 2.2 mm part–part and 1.2 mm part–wall, CDS COM box, ±Z insertion order (ASSUMED frame).',
    why: 'an idealized layout in an empty box may not be buildable.',
  },
};

export const PHYSICAL_CAPTION = 'changes the physics';
export const GOALS_CAPTION = 'never changes the parts';
export const TWEEN_LABEL = 'visual interpolation — not a validated motion path';
export const NOT_OPTIMAL = 'Best found so far — not proven optimal';
export const DISCLAIMER_STAGE2 = 'Successful geometric packaging does not demonstrate mechanical or flight qualification.';
export const MFG_LABEL = 'manufacturing concept — assumed cost model, not a quote; brackets not stress-analysed';
