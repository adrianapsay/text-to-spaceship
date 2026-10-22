import type { SliderKey, Sliders } from '../api/types';

export type PresetId = 'max_packing' | 'com_priority' | 'min_inertia' | 'balanced' | 'custom';

export const PRESETS: { id: PresetId; label: string; favoured?: SliderKey }[] = [
  { id: 'max_packing', label: 'Maximum Packing Efficiency', favoured: 'space' },
  { id: 'com_priority', label: 'Center-of-Mass Priority', favoured: 'balance' },
  { id: 'min_inertia', label: 'Minimum Rotational Inertia', favoured: 'inertia' },
  { id: 'balanced', label: 'Balanced' },
  { id: 'custom', label: 'Custom' },
];

/** Beginner goal sliders that are active in a stage (protocol §F.4: three in Stage 1, four in Stage 2). */
export function activeGoalSliders(stage: 1 | 2): SliderKey[] {
  return stage === 2 ? ['space', 'balance', 'inertia', 'feasibility'] : ['space', 'balance', 'inertia'];
}

/** Apply a preset to the beginner sliders: favoured 70, others 10; Balanced = all active equal. */
export function applyPreset(sliders: Sliders, preset: PresetId, stage: 1 | 2): Sliders {
  if (preset === 'custom') return sliders;
  const active = activeGoalSliders(stage);
  const out = { ...sliders };
  const def = PRESETS.find((p) => p.id === preset);
  for (const k of active) out[k] = preset === 'balanced' ? 25 : k === def?.favoured ? 70 : 10;
  return out;
}

export function detectPreset(sliders: Sliders, stage: 1 | 2): PresetId {
  for (const p of PRESETS) {
    if (p.id === 'custom') continue;
    const target = applyPreset(sliders, p.id, stage);
    if (activeGoalSliders(stage).every((k) => target[k] === sliders[k])) return p.id;
  }
  return 'custom';
}
