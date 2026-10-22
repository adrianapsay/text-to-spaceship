// MOCK content generators: selector rule, detail-ladder (fidelity) data, idea map and fit proof.
// Every object produced here carries `mock: true`; the UI labels it MOCK. The selector rule and the fidelity
// numbers are ILLUSTRATIVE (they are not the backend's rule and not measurements). The proof is a genuine
// AABB-interval argument for the mock's own placeholder layouts, but it is not produced by the backend validator.

import type { FidelityLevel, FidelityResult, IdeaMap, Layout, Part, Settings, SliderKey, Vec3 } from '../api/types';
import { normalisedWeights } from '../lib/physics';
import { activeGoalSliders } from '../store/presets';
import type { AabbCheck } from './packer';
import { lcg } from './packer';

// ------------------------------------------------------------------------------------------------ selector
export const MOCK_ALGOS: Record<string, string> = {
  box_decoder: 'Constructive box decoder (V1)',
  hybrid_box: 'Hybrid BRKGA + box decoder',
  hybrid_box_com: 'Hybrid BRKGA + box decoder, COM-seeking placement',
  hybrid_voxel: 'Hybrid BRKGA + voxel decoder',
  hybrid_voxel_cable: 'Hybrid + voxel decoder, continuous-cable mode',
};

export interface PartStats {
  n: number;
  concaveShare: number;
  boxShare: number;
}

export function partStats(parts: Part[]): PartStats {
  const usable = parts.filter((p) => (p.status === 'VALID' || p.status === 'REPAIRED') && (p.volume_mm3 ?? 0) > 0);
  const total = usable.reduce((s, p) => s + (p.volume_mm3 ?? 0), 0) || 1;
  const share = (pred: (p: Part) => boolean) => usable.filter(pred).reduce((s, p) => s + (p.volume_mm3 ?? 0), 0) / total;
  return {
    n: usable.length,
    concaveShare: share((p) => p.labels.some((l) => l.startsWith('concave'))),
    boxShare: share((p) => p.labels.includes('box-like') || p.labels.includes('near-box')),
  };
}

const pct = (v: number) => `${(v * 100).toFixed(0)} %`;

/** ILLUSTRATIVE default rule for the mock (labelled). Deterministic, so it can be swept. */
export function mockSelect(settings: Settings, stats: PartStats): { id: string; reasons: string[] } {
  const s = settings.sliders;
  const w = normalisedWeights(s, activeGoalSliders(settings.stage));
  const cableThreshold = 70;
  if (settings.stage === 2 && s.cable >= cableThreshold)
    return { id: 'hybrid_voxel_cable', reasons: [`cable-routing slider ${s.cable} ≥ ${cableThreshold} → continuous-cable mode`, 'MOCK default rule (no benchmark evidence)'] };
  if (s.speed_quality <= 20)
    return { id: 'box_decoder', reasons: [`speed ↔ quality ${s.speed_quality} ≤ 20 → constructive decoder only`, 'MOCK default rule (no benchmark evidence)'] };
  if ((w.space ?? 0) >= 0.5 && stats.concaveShare >= 0.3)
    return {
      id: 'hybrid_voxel',
      reasons: [`weight on compactness ${(w.space ?? 0).toFixed(2)} ≥ 0.50`, `concave volume share ${pct(stats.concaveShare)} ≥ 30 %`, 'MOCK default rule (no benchmark evidence)'],
    };
  if ((w.balance ?? 0) >= 0.4 || (w.inertia ?? 0) >= 0.45)
    return {
      id: 'hybrid_box_com',
      reasons: [`weight on balance ${(w.balance ?? 0).toFixed(2)}, on inertia ${(w.inertia ?? 0).toFixed(2)} → COM-seeking placement`, 'MOCK default rule (no benchmark evidence)'],
    };
  return { id: 'hybrid_box', reasons: [`no goal weight dominates (max ${Math.max(...Object.values(w)).toFixed(2)})`, 'MOCK default rule (no benchmark evidence)'] };
}

export function mockSweep(settings: Settings, stats: PartStats, slider: SliderKey) {
  const values = Array.from({ length: 101 }, (_, i) => i);
  const choices = values.map((v) => mockSelect({ ...settings, sliders: { ...settings.sliders, [slider]: v } }, stats).id);
  return { slider, values, choices, legend: MOCK_ALGOS, mock: true };
}

export function mockMap(settings: Settings, stats: PartStats, x: SliderKey, y: SliderKey, n: number) {
  const vals = Array.from({ length: n }, (_, i) => Math.round((i * 100) / (n - 1)));
  const grid = vals.map((vy) => vals.map((vx) => mockSelect({ ...settings, sliders: { ...settings.sliders, [x]: vx, [y]: vy } }, stats).id));
  return { x, y, n, values: vals, grid, legend: MOCK_ALGOS, mock: true };
}

// ------------------------------------------------------------------------------------------------ fidelity
const LADDER: { level: string; family: string; label: string; params: Record<string, unknown> }[] = [
  { level: 'F0', family: 'F0', label: 'Bounding box (OBB)', params: {} },
  { level: 'F1-2', family: 'F1', label: 'Compound boxes, k = 2', params: { k: 2 } },
  { level: 'F1-4', family: 'F1', label: 'Compound boxes, k = 4', params: { k: 4 } },
  { level: 'F1-6', family: 'F1', label: 'Compound boxes, k = 6', params: { k: 6 } },
  { level: 'F2-26', family: 'F2', label: 'Support polytope, 26 directions', params: { directions: 26 } },
  { level: 'F2-64', family: 'F2', label: 'Support polytope, 64 directions', params: { directions: 64 } },
  { level: 'F2-hull', family: 'F2', label: 'Exact convex hull', params: {} },
  { level: 'F3-2', family: 'F3', label: 'Convex cover, 2 pieces', params: { pieces: 2 } },
  { level: 'F3-4', family: 'F3', label: 'Convex cover, 4 pieces', params: { pieces: 4 } },
  { level: 'F3-8', family: 'F3', label: 'Convex cover, 8 pieces', params: { pieces: 8 } },
  { level: 'F3-16', family: 'F3', label: 'Convex cover, 16 pieces', params: { pieces: 16 } },
  { level: 'F4-1', family: 'F4', label: 'Conservative voxels, 1 mm', params: { voxel_mm: 1 } },
  { level: 'F5-5k', family: 'F5', label: 'Decimated mesh, 5k triangles (inflated)', params: { triangles: 5000 } },
  { level: 'F6', family: 'F6', label: 'Full mesh', params: {} },
];
const FIDELITY_ALGOS = ['box_decoder', 'hybrid_box', 'hybrid_voxel'];

function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** ILLUSTRATIVE MOCK detail-ladder result. Only F0 and F6 proxy volumes are real (AABB volume, mesh volume). */
export function mockFidelity(part: Part, status: FidelityResult['status'] = 'DONE', upTo?: number): FidelityResult {
  const rnd = lcg(hashStr(part.sha256 || part.id));
  const trueV = Math.max(1, part.volume_mm3 ?? 1);
  const aabbV = part.extents_mm[0] * part.extents_mm[1] * part.extents_mm[2];
  const concave = part.labels.some((l) => l.startsWith('concave'));
  const boxy = part.labels.includes('box-like') || part.labels.includes('near-box');
  const stopAt = boxy ? 2 : concave ? 10 : 6; // index in LADDER where the mock ladder "converges"
  const last = Math.min(upTo ?? stopAt + 1, LADDER.length - 1);
  const levels: FidelityLevel[] = [];
  const baseL = 300 + rnd() * 20;
  for (let i = 0; i <= last; i++) {
    const def = LADDER[i];
    const tight = 1 - Math.exp(-(i + 0.5) / (stopAt + 0.5) * 2.5);
    const vol = def.level === 'F0' ? aabbV : def.level === 'F6' ? trueV : trueV + (aabbV - trueV) * (1 - tight);
    const evalUs = 0.4 * 1.9 ** i * (1 + rnd() * 0.2);
    const results: FidelityLevel['results'] = {};
    for (const [k, a] of FIDELITY_ALGOS.entries()) {
      const gain = (aabbV - trueV) / 1e4;
      results[a] = {
        length_used_mm: Number((baseL - k * 4 - Math.min(gain, 25) * tight + rnd() * 0.3).toFixed(1)),
        com_error_mm: Number((30 + rnd() * 10).toFixed(1)),
        score_g: Number((0.5 - 0.2 * tight + rnd() * 0.01).toFixed(3)),
        first_valid_s: Number((0.05 * 1.6 ** i).toFixed(2)),
        false_reject_rate: Number(Math.max(0, (1 - tight) * (0.6 - k * 0.1) + rnd() * 0.01).toFixed(3)),
      };
    }
    levels.push({ level: def.level, family: def.family, label: def.label, params: def.params, proxy_volume_mm3: vol, overhead: vol / trueV - 1, build_s: Number((0.01 * 2 ** i).toFixed(3)), eval_us_median: Number(evalUs.toFixed(2)), results });
  }
  const chosen: Record<string, string> = {};
  const reasons: Record<string, string> = {};
  if (status === 'DONE') {
    for (const a of FIDELITY_ALGOS) {
      const top = levels[levels.length - 1];
      let pick = top;
      for (const lv of levels) {
        const r = lv.results[a];
        const t = top.results[a];
        if (
          r.length_used_mm !== null && t.length_used_mm !== null &&
          Math.abs(r.length_used_mm - t.length_used_mm) < 0.5 &&
          Math.abs((r.false_reject_rate ?? 0) - (t.false_reject_rate ?? 0)) < 0.01
        ) {
          pick = lv;
          break;
        }
      }
      chosen[a] = pick.level;
      const next = levels[levels.indexOf(pick) + 1];
      reasons[a] = next
        ? `MOCK: more detail than "${pick.label}" changed the result by only ${Math.abs((next.results[a].length_used_mm ?? 0) - (pick.results[a].length_used_mm ?? 0)).toFixed(1)} mm but took ${((next.eval_us_median ?? 1) / (pick.eval_us_median ?? 1)).toFixed(1)}× longer`
        : `MOCK: most detailed level tested`;
    }
  }
  return {
    status,
    levels,
    chosen,
    reasons,
    stop_reason: status === 'DONE' ? 'converged' : null,
    mock: true,
    mock_note: 'ILLUSTRATIVE MOCK VALUES — not measured. The detail-ladder study runs only in the backend.',
  };
}
export { FIDELITY_ALGOS };

// ------------------------------------------------------------------------------------------------ idea map
export function mockIdeaMap(parts: Part[], settings: Settings, best: Layout | null, selected: { id: string; reasons: string[] }): IdeaMap {
  const stats = partStats(parts);
  const usable = parts.filter((p) => p.status === 'VALID' || p.status === 'REPAIRED');
  const groupOf = (p: Part) =>
    p.labels.includes('box-like') || p.labels.includes('near-box') ? 'box' : p.labels.some((l) => l.startsWith('concave')) ? 'concave' : 'convex';
  const groups: Record<string, Part[]> = { box: [], convex: [], concave: [] };
  for (const p of usable) groups[groupOf(p)].push(p);
  const total = usable.reduce((s, p) => s + (p.volume_mm3 ?? 0), 0) || 1;
  const vshare = (g: Part[]) => g.reduce((s, p) => s + (p.volume_mm3 ?? 0), 0) / total;
  const w = normalisedWeights(settings.sliders, activeGoalSliders(settings.stage));
  const nodes: IdeaMap['nodes'] = [
    { id: 'g_box', label: `Box-like parts (${groups.box.length})`, kind: 'parts', tab: 'components', detail: groups.box.map((p) => p.name).join(', ') },
    { id: 'g_convex', label: `Convex / curved parts (${groups.convex.length})`, kind: 'parts', tab: 'components', detail: groups.convex.map((p) => p.name).join(', ') },
    { id: 'g_concave', label: `Concave parts (${groups.concave.length})`, kind: 'parts', tab: 'components', detail: groups.concave.map((p) => p.name).join(', ') },
    { id: 'x_box', label: 'Box proxy (G1)', kind: 'proxy', tab: 'components', detail: 'MOCK: simplified shape used by the search' },
    { id: 'x_hull', label: 'Convex hull (G2)', kind: 'proxy', tab: 'components', detail: 'MOCK: simplified shape used by the search' },
    { id: 'x_cover', label: 'Convex cover (G3)', kind: 'proxy', tab: 'components', detail: 'MOCK: simplified shape used by the search' },
    ...Object.entries(MOCK_ALGOS).map(([id, label]) => ({ id: `a_${id}`, label, kind: 'algorithm', tab: 'comparison', detail: 'candidate algorithm' })),
    {
      id: 'weights',
      label: `Your priorities`,
      kind: 'weights',
      tab: 'optimization',
      detail: Object.entries(w).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(' · '),
    },
    {
      id: 'constraints',
      label: settings.stage === 2 ? 'Stage 2 ENGINEERING-CONSTRAINED' : 'Stage 1 IDEALIZED',
      kind: 'constraints',
      tab: 'engineering',
      detail: settings.stage === 2 ? 'walls, rails, clearances (ASSUMED)' : 'empty 100 × 100 × 340.5 mm box',
    },
    { id: 'selected', label: `Chosen: ${MOCK_ALGOS[selected.id] ?? selected.id}`, kind: 'selected', tab: 'explain', detail: selected.reasons.join('; ') },
    {
      id: 'layout',
      label: best ? `${best.id}` : 'No validated layout',
      kind: 'layout',
      tab: 'overview',
      detail: best?.metrics?.length_used_mm != null ? `length used ${best.metrics.length_used_mm.toFixed(1)} mm (MOCK placeholder)` : null,
    },
  ];
  const edges: IdeaMap['edges'] = [
    { from: 'g_box', to: 'x_box', label: `volume share ${pct(vshare(groups.box))}` },
    { from: 'g_convex', to: 'x_hull', label: `volume share ${pct(vshare(groups.convex))}` },
    { from: 'g_concave', to: 'x_cover', label: `concave volume share ${pct(stats.concaveShare)}` },
    { from: 'x_box', to: 'a_box_decoder', label: null },
    { from: 'x_box', to: 'a_hybrid_box', label: null },
    { from: 'x_box', to: 'a_hybrid_box_com', label: null },
    { from: 'x_hull', to: 'a_hybrid_box', label: null },
    { from: 'x_cover', to: 'a_hybrid_voxel', label: null },
    { from: 'x_cover', to: 'a_hybrid_voxel_cable', label: null },
    { from: 'weights', to: 'selected', label: `weight on compactness ${(w.space ?? 0).toFixed(2)}` },
    { from: 'constraints', to: 'selected', label: settings.stage === 2 ? `cable slider ${settings.sliders.cable}` : 'no hard COM box' },
    { from: `a_${selected.id}`, to: 'selected', label: 'MOCK default rule' },
    { from: 'selected', to: 'layout', label: best?.metrics?.length_used_mm != null ? `L = ${best.metrics.length_used_mm.toFixed(1)} mm` : null },
  ];
  return { nodes, edges, mock: true };
}

// ------------------------------------------------------------------------------------------------ fit proof
const AX = ['x', 'y', 'z'];
const f2 = (v: number) => v.toFixed(3).replace(/^-/, '−');

export function mockProof(layout: Layout, parts: Record<string, Part>, check: AabbCheck, half: Vec3, com: Vec3 | null) {
  const lines: string[] = [];
  lines.push(`# MOCK fit proof for ${layout.id}`);
  lines.push('');
  lines.push('> **MOCK.** Generated in the browser from axis-aligned bounding boxes of the placeholder layout. The argument is valid for this layout, but it is not produced by the backend validator and does not use convex pieces or separating planes.');
  lines.push('');
  lines.push(`**Theorem.** The ${layout.poses.length} parts occupy pairwise-disjoint regions inside the enclosure [−${half[0]}, ${half[0]}] × [−${half[1]}, ${half[1]}] × [−${half[2]}, ${half[2]}] mm.`);
  lines.push('');
  lines.push('## Lemma 1 (containment)');
  lines.push('The enclosure is convex and each part lies inside its axis-aligned bounding box (the box of its vertices). With the 24 axis-permutation orientations the world box is exact. So if every box satisfies the enclosure bounds, every part is inside.');
  lines.push('');
  lines.push('| Part | min x | max x | min y | max y | min z | max z | tightest margin |');
  lines.push('|---|---:|---:|---:|---:|---:|---:|---:|');
  for (const c of check.containment) {
    const p = parts[c.part_id];
    const k = c.margin_mm.indexOf(Math.min(...c.margin_mm));
    lines.push(`| ${p?.name ?? c.part_id} | ${f2(c.min[0])} | ${f2(c.max[0])} | ${f2(c.min[1])} | ${f2(c.max[1])} | ${f2(c.min[2])} | ${f2(c.max[2])} | ${f2(c.margin_mm[k])} mm (${AX[k]}) |`);
  }
  lines.push('');
  lines.push('## Lemma 2 (separation, AABB-gap interval argument)');
  lines.push('For each pair there is an axis on which the two boxes\' intervals do not overlap; the gap is shown. Disjoint boxes contain disjoint parts.');
  lines.push('');
  lines.push('| Pair | axis | gap |');
  lines.push('|---|---|---:|');
  for (const s of check.separations) lines.push(`| ${parts[s.a]?.name ?? s.a} / ${parts[s.b]?.name ?? s.b} | ${AX[s.axis]} | ${f2(s.gap_mm)} mm |`);
  lines.push('');
  lines.push('## Balance (Stage 1: displayed, not enforced)');
  if (com) {
    lines.push(`COM = (${f2(com[0])}, ${f2(com[1])}, ${f2(com[2])}) mm. CDS box: |x| ≤ 20, |y| ≤ 20, |z| ≤ 70 mm →`);
    lines.push(`|x| = ${f2(Math.abs(com[0]))} ${Math.abs(com[0]) <= 20 ? '≤' : '>'} 20, |y| = ${f2(Math.abs(com[1]))} ${Math.abs(com[1]) <= 20 ? '≤' : '>'} 20, |z| = ${f2(Math.abs(com[2]))} ${Math.abs(com[2]) <= 70 ? '≤' : '>'} 70.`);
  } else lines.push('COM not available.');
  lines.push('');
  lines.push('## Lower bound');
  const solid = Object.values(parts).filter((p) => layout.poses.some((q) => q.part_id === p.id)).reduce((s, p) => s + (p.volume_mm3 ?? 0), 0);
  lines.push(`Solid volume ${f2(solid / 1000)} cm³ divided by the 100 × 100 mm cross-section gives L ≥ ${f2(solid / 10000)} mm (rigorous for the true shapes).`);
  const certificate = {
    mock: true,
    layout_id: layout.id,
    method: 'aabb-interval',
    containment: check.containment,
    separations: check.separations,
  };
  return { markdown: lines.join('\n'), certificate, mock: true };
}
