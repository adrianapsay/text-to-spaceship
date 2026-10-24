// V2 WS6: the bill of materials of the shown layout. The backend (report/bom.py, GET /api/layouts/{id}/bom) is the
// single source; this module holds its wire types, the helpers the Bill of Materials tab and the drawings share
// (groups, 3D id ↔ row, totals check, CSV, mass text), the hooks that keep it in step with the 3D view, and a
// client-side builder that only the MOCK backend uses (its BOM is tagged mock).

import { useMemo } from 'react';
import type { Layout, Part, ProjectSnapshot } from '../api/types';
import { ApiError } from '../api/rest';
import { session } from '../api/session';
import { renderPlan, type RenderItem } from '../api/protocol';
import { useApp } from '../store/store';
import { useAsync, type AsyncState } from '../hooks';

export type BomGroupId = 'parts' | 'brackets' | 'hardware' | 'structure';

export interface BomRow {
  item_no: number;
  group: BomGroupId;
  kind: string;
  name: string;
  /** the part this row selects in the 3D view (a part, or the part a bracket holds) */
  part_id: string | null;
  /** parts the item belongs to / holds */
  for_parts: string[];
  qty: number;
  material: string;
  process: string;
  unit_mass_kg: number | null;
  total_mass_kg: number | null;
  /** ASSUMED | USER_MASS | USER_DENSITY | WITHHELD | designed | exact | ESTIMATE | catalogue | not modelled */
  mass_source: string;
  /** counted in the layout's total mass (parts + hardware) */
  in_total: boolean;
  description: string;
  /** ids of the objects in the 3D render: part ids, extra item ids, frame item ids */
  item_ids: string[];
  bracket_kind?: string | null;
  designed?: boolean;
  passed?: boolean | null;
  target?: string | null;
}

export interface BomTotals {
  parts_kg: number;
  hardware_kg: number;
  assembly_kg: number;
  frame_kg: number | null;
  with_frame_kg: number | null;
  estimate_kg: number;
  metrics_mass_kg: number | null;
  matches_metrics: boolean | null;
  difference_kg: number | null;
  rows: number;
  pieces: number;
  withheld: string[];
  not_modelled: number[];
  included: string;
}

export interface Bom {
  layout_id: string;
  stage: number;
  mode: string | null;
  part_scale: number;
  label: string;
  status_line: string;
  groups: { id: BomGroupId; label: string }[];
  items: BomRow[];
  totals: BomTotals;
  notes: string[];
  units?: { mass: string; length: string };
  /** built by the in-browser MOCK backend */
  mock?: boolean;
}

export const BOM_GROUPS: { id: BomGroupId; label: string }[] = [
  { id: 'parts', label: 'Parts' },
  { id: 'brackets', label: 'Brackets' },
  { id: 'hardware', label: 'Fasteners & hardware' },
  { id: 'structure', label: 'Structure (frame)' },
];

export const STATUS_LINE = 'ENGINEERING-CONSTRAINED — not flight-qualified; not for manufacture without review';

// ------------------------------------------------------------------------------------------------ helpers
/** Rows by group, in the backend's group order (empty groups left out). */
export function groupRows(bom: Pick<Bom, 'items' | 'groups'>): { id: BomGroupId; label: string; rows: BomRow[] }[] {
  const groups = bom.groups?.length ? bom.groups : BOM_GROUPS;
  return groups.map((g) => ({ ...g, rows: bom.items.filter((r) => r.group === g.id) })).filter((g) => g.rows.length);
}

/** The part a click on this row selects in the 3D view: its own part, the part a bracket holds, or the single part
 * an item of hardware belongs to (none for hardware shared by several parts). */
export function partForRow(row: BomRow): string | null {
  if (row.part_id) return row.part_id;
  return row.for_parts.length === 1 ? row.for_parts[0] : null;
}

/** For a part selected in 3D: its own rows (the part and the brackets holding it) and the related rows (shared
 * hardware used on it). */
export function rowsForPart(items: BomRow[], partId: string | null): { own: Set<number>; related: Set<number> } {
  const own = new Set<number>();
  const related = new Set<number>();
  if (!partId) return { own, related };
  for (const r of items) {
    if (r.part_id === partId && (r.group === 'parts' || r.group === 'brackets')) own.add(r.item_no);
    else if (r.for_parts.includes(partId) || r.part_id === partId) related.add(r.item_no);
  }
  return { own, related };
}

/** 3D render id (part id, extra item id) → BOM item number. */
export function itemNumbers(items: BomRow[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const r of items) for (const id of r.item_ids) if (!m.has(id)) m.set(id, r.item_no);
  return m;
}

/** Sums of the rows counted in the total: parts, hardware (brackets + fasteners & hardware), and the frame. */
export function sumRows(items: BomRow[]): { parts: number; hardware: number; assembly: number; frame: number | null } {
  let parts = 0;
  let hardware = 0;
  let frame: number | null = null;
  for (const r of items) {
    if (r.group === 'structure') {
      if (r.total_mass_kg != null) frame = (frame ?? 0) + r.total_mass_kg;
      continue;
    }
    if (!r.in_total || r.total_mass_kg == null) continue;
    if (r.group === 'parts') parts += r.total_mass_kg;
    else hardware += r.total_mass_kg;
  }
  return { parts, hardware, assembly: parts + hardware, frame };
}

/** Mass in grams for tables (one unit per column), "—" when not known. */
export function gramText(kg: number | null | undefined, decimals = 1): string {
  if (kg == null || !Number.isFinite(kg)) return '—';
  return (kg * 1000).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export const CSV_COLUMNS = ['item', 'group', 'name', 'qty', 'material', 'process', 'unit_mass_kg', 'total_mass_kg', 'mass_source', 'in_total', 'part_id', 'description', 'item_ids'];

function csvCell(v: unknown): string {
  const s = v == null ? '' : String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
const num = (v: number | null | undefined) => (v == null ? '' : v.toFixed(6));

/** The same CSV layout as the backend's (report/bom.py bom_csv). */
export function bomCsv(bom: Bom): string {
  const labels = Object.fromEntries((bom.groups?.length ? bom.groups : BOM_GROUPS).map((g) => [g.id, g.label]));
  const lines: string[][] = [
    [`# Bill of materials, layout ${bom.layout_id}: ${bom.label}${bom.mock ? ' (MOCK)' : ''}`],
    [`# Masses in kg as the layout data gives them (source per row). ${bom.totals.included}`],
    CSV_COLUMNS,
  ];
  for (const r of bom.items)
    lines.push([String(r.item_no), labels[r.group] ?? r.group, r.name, String(r.qty), r.material, r.process, num(r.unit_mass_kg), num(r.total_mass_kg), r.mass_source, r.in_total ? 'yes' : 'no', r.part_id ?? '', r.description, r.item_ids.join(';')]);
  const t = bom.totals;
  lines.push([]);
  for (const [label, v] of [
    ['parts', t.parts_kg],
    ['hardware', t.hardware_kg],
    ["parts + hardware (the layout's total mass)", t.assembly_kg],
    ['frame (listed, not included)', t.frame_kg],
    ['total with the frame', t.with_frame_kg],
  ] as [string, number | null][])
    if (v != null) lines.push(['', 'TOTAL', label, '', '', '', '', num(v), '', '', '', '', '']);
  return '﻿' + lines.map((l) => l.map(csvCell).join(',')).join('\r\n') + '\r\n';
}

// ------------------------------------------------------------------------------------------------ MOCK builder
const FASTENER_MASS_KG = 0.0012; // backend mfg.rules.FASTENER_MASS_KG (ASSUMED); used by the MOCK builder only
const SUBSYSTEM: Record<string, string> = { power: 'Power', electronics: 'Electronics', adcs: 'ADCS', tanks: 'Tanks', payload: 'Payload / sensors', structure: 'Structure', unknown: 'Unknown' };
const KIND_NAME: Record<string, string> = { machined: 'Machined spacer block', sheet: 'Sheet-metal Z-bracket', clamp: 'Tube clamp', cradle: 'Machined cradle', metal_am: 'Metal 3D-printed bracket' };
const mmText = (v: number) => String(Number(v.toFixed(1)));

function row(p: Partial<BomRow> & Pick<BomRow, 'group' | 'kind' | 'name'>): BomRow {
  const r: BomRow = { item_no: 0, part_id: null, for_parts: [], qty: 1, material: '—', process: '—', unit_mass_kg: null, total_mass_kg: null, mass_source: 'not modelled', in_total: false, description: '', item_ids: [], ...p };
  if (r.unit_mass_kg != null && p.total_mass_kg == null) r.total_mass_kg = r.unit_mass_kg * r.qty;
  return r;
}

/**
 * Client-side BOM of a layout (used by the MOCK backend; the live app uses the backend's): parts in the project's
 * order, V2 brackets as their solid with the fasteners split out into one aggregated row, other items aggregated by
 * kind, label and mass, and the ASSUMED frame (Stage 2) listed but not included — the backend's rules, simplified
 * (a direct mount's spacer washers are one row per mount mass instead of one per stack envelope).
 */
export function buildBomClient(layout: Layout, parts: Record<string, Part>, order: string[], frameMassKg: number | null = null): Bom {
  const scale = layout.part_scale ?? 1;
  const placed = new Set(layout.poses.map((p) => p.part_id));
  const ids = [...new Set([...order.filter((id) => placed.has(id)), ...layout.poses.map((p) => p.part_id)])];
  const names = Object.fromEntries(ids.map((id) => [id, parts[id]?.name ?? id]));
  const excluded = new Set((layout.metrics as { mass_excluded_parts?: string[] } | null)?.mass_excluded_parts ?? []);
  const rows: BomRow[] = ids.map((id) => {
    const p = parts[id];
    const m = p?.mass_kg != null ? (p.mass_source === 'USER_MASS' ? p.mass_kg : p.mass_kg * scale ** 3) : null;
    const src = m == null ? 'WITHHELD' : p.mass_source;
    // the material of a supplied part is not known: what is known is the density its mass comes from
    const material =
      m == null ? 'unknown (mass withheld)' : src === 'USER_MASS' ? 'not specified (mass entered)' : `density ${(p.density_kg_m3 ?? 2700).toLocaleString('en-US', { maximumFractionDigits: 0 })} kg/m³ (${src === 'USER_DENSITY' ? 'entered' : 'ASSUMED'})`;
    const desc = [SUBSYSTEM[p?.subsystem ?? 'unknown'] ?? p?.subsystem ?? 'Unknown'];
    if (p?.extents_mm) desc.push(`bounding box ${p.extents_mm.map((v) => mmText(v * scale)).join(' × ')} mm${scale !== 1 ? ` at ${Math.round(scale * 100)} % size` : ''}`);
    return row({ group: 'parts', kind: 'part', name: names[id], part_id: id, for_parts: [id], material, process: 'as supplied', unit_mass_kg: m, mass_source: src, in_total: m != null && !excluded.has(id), description: desc.join('; '), item_ids: [id] });
  });
  const brackets: BomRow[] = [];
  const hardware: BomRow[] = [];
  const designs = layout.stage2?.bracket_designs ?? {};
  const info = layout.stage2?.brackets ?? [];
  const fasteners: { id: string; pid: string; n: number }[] = [];
  const groups = new Map<string, BomRow>();
  for (const it of layout.extra_items ?? []) {
    const m = it.mass_kg;
    if (it.kind === 'bracket' && it.bracket_kind) {
      const k = /-br(\d+)$/.exec(it.id);
      const b = (k ? info[Number(k[1])] : undefined) ?? info.find((x) => x.pid === it.for_part);
      const nf = b?.fasteners ?? 0;
      const d = (it as { designed?: boolean }).designed ? designs[it.for_part] : undefined;
      const dd = d as (typeof d & { solid_mass_kg?: number; fastener_mass_kg?: number }) | undefined;
      const fast = dd?.fastener_mass_kg ?? nf * FASTENER_MASS_KG;
      let solid = dd?.solid_mass_kg ?? (m != null ? m - fast : null);
      const split = solid != null && solid > 0 && nf > 0;
      if (!split) solid = m;
      const source = dd ? 'designed' : it.exact === false ? 'ESTIMATE' : it.bracket_kind === 'clamp' ? 'catalogue' : 'exact';
      if (it.bracket_kind === 'direct') {
        const key = `washers:${solid?.toFixed(9)}`;
        const g = groups.get(key) ?? row({ group: 'hardware', kind: 'washer_set', name: 'M3 spacer washers (one direct mount)', qty: 0, material: 'steel (ASSUMED)', process: 'catalogue', unit_mass_kg: solid, mass_source: 'ASSUMED', in_total: solid != null, description: 'washer stacks of one direct mount' });
        g.qty += 1;
        g.total_mass_kg = solid != null ? solid * g.qty : null;
        g.item_ids.push(it.id);
        if (!g.for_parts.includes(it.for_part)) g.for_parts.push(it.for_part);
        groups.set(key, g);
      } else {
        brackets.push(row({ group: 'brackets', kind: 'bracket', name: `${KIND_NAME[it.bracket_kind] ?? it.bracket_kind} for ${names[it.for_part] ?? it.for_part}`, part_id: it.for_part, for_parts: [it.for_part], material: it.material ?? b?.material ?? '—', process: it.bracket_kind === 'metal_am' ? 'L-PBF metal AM' : it.bracket_kind === 'sheet' ? 'sheet metal, 2 bends' : it.bracket_kind === 'clamp' && !dd ? 'catalogue' : 'CNC machined', unit_mass_kg: solid, mass_source: source, in_total: solid != null, description: it.label ?? '', item_ids: [it.id], bracket_kind: it.bracket_kind, designed: !!dd, passed: dd ? dd.passed : null, target: it.target ?? null }));
      }
      if (split) fasteners.push({ id: it.id, pid: it.for_part, n: nf });
    } else {
      const key = `${it.kind}|${it.label ?? ''}|${it.material ?? ''}|${m?.toFixed(9)}`;
      const g = groups.get(key) ?? row({ group: 'hardware', kind: it.kind || 'item', name: it.label ?? it.kind, qty: 0, material: it.material ?? '—', process: String(it.process ?? '—'), unit_mass_kg: m, mass_source: m != null ? 'ASSUMED' : 'not modelled', in_total: m != null });
      g.qty += 1;
      g.total_mass_kg = m != null ? m * g.qty : null;
      g.item_ids.push(it.id);
      if (it.for_part && !g.for_parts.includes(it.for_part)) g.for_parts.push(it.for_part);
      groups.set(key, g);
    }
  }
  const pos = new Map(ids.map((id, i) => [id, i]));
  brackets.sort((a, b) => (pos.get(a.part_id ?? '') ?? 1e9) - (pos.get(b.part_id ?? '') ?? 1e9));
  if (fasteners.length) {
    const n = fasteners.reduce((s, f) => s + f.n, 0);
    // no 3D id of their own: the fasteners are not modelled as solids
    hardware.push(row({ group: 'hardware', kind: 'fastener', name: 'M3 × 8 screw with washer', qty: n, material: 'steel (ASSUMED)', process: 'catalogue', unit_mass_kg: FASTENER_MASS_KG, mass_source: 'ASSUMED', in_total: true, for_parts: [...new Set(fasteners.map((f) => f.pid))], description: `${n} on ${fasteners.length} bracket(s) and direct mounts; ${FASTENER_MASS_KG * 1000} g each (ASSUMED); not drawn` }));
  }
  hardware.push(...groups.values());
  const structure: BomRow[] = [];
  if (layout.stage === 2 && frameMassKg != null)
    structure.push(row({ group: 'structure', kind: 'frame', name: 'CubeSat frame: walls and 4 corner rails', material: 'aluminium, 2,700 kg/m³ (ASSUMED)', unit_mass_kg: frameMassKg, mass_source: 'ASSUMED', in_total: false, description: "ASSUMED geometry; not in the layout's total mass (as in the metrics); drawn as an outline" }));
  const items = [...rows, ...brackets, ...hardware, ...structure].map((r, i) => ({ ...r, item_no: i + 1 }));
  const s = sumRows(items);
  const mm = layout.metrics?.mass_kg ?? null;
  const notes: string[] = [];
  if (layout.stage !== 2) notes.push('Stage 1 (IDEALIZED): parts only; no brackets, fasteners or frame are modelled.');
  if (scale !== 1) notes.push(`Parts at ${Math.round(scale * 100)} % of full size (part-size slider).`);
  return {
    layout_id: layout.id,
    stage: layout.stage,
    mode: layout.mode ?? null,
    part_scale: scale,
    label: layout.label ?? (layout.stage === 2 ? STATUS_LINE : 'IDEALIZED (Stage 1)'),
    status_line: STATUS_LINE,
    groups: BOM_GROUPS,
    items,
    notes,
    totals: {
      parts_kg: s.parts,
      hardware_kg: s.hardware,
      assembly_kg: s.assembly,
      frame_kg: s.frame,
      with_frame_kg: s.frame != null ? s.assembly + s.frame : null,
      estimate_kg: items.filter((r) => r.mass_source === 'ESTIMATE').reduce((a, r) => a + (r.total_mass_kg ?? 0), 0),
      metrics_mass_kg: mm,
      matches_metrics: mm == null ? null : Math.abs(s.assembly - mm) <= 1e-6,
      difference_kg: mm == null ? null : s.assembly - mm,
      rows: items.length,
      pieces: items.reduce((a, r) => a + r.qty, 0),
      withheld: items.filter((r) => r.group === 'parts' && r.total_mass_kg == null).map((r) => r.name),
      not_modelled: items.filter((r) => r.group !== 'parts' && r.total_mass_kg == null).map((r) => r.item_no),
      included: 'Parts and hardware (brackets, fasteners, washers, standoffs): the layout\'s total mass. The frame and rows without a mass model are listed, not included.',
    },
  };
}

/** MOCK backend route: the client-side BOM tagged mock. */
export function mockBom(layout: Layout, project: ProjectSnapshot): Bom {
  const parts = Object.fromEntries(project.parts.map((p) => [p.id, p]));
  const fm = (project.stage2_frame as { frame_mass_kg?: number } | null)?.frame_mass_kg ?? null;
  return { ...buildBomClient(layout, parts, project.parts.map((p) => p.id), fm), mock: true };
}

// ------------------------------------------------------------------------------------------------ fetching
export function bomPath(layoutId: string, format: 'json' | 'csv' = 'json'): string {
  return `/api/layouts/${encodeURIComponent(layoutId)}/bom${format === 'csv' ? '?format=csv' : ''}`;
}

export async function fetchBom(layoutId: string): Promise<Bom> {
  const api = session().api;
  const path = bomPath(layoutId);
  let r: Response;
  try {
    r = await api.t.fetch(path, { headers: { accept: 'application/json' } });
  } catch (e) {
    throw new ApiError(0, path, `network error: ${(e as Error).message}`);
  }
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = (await r.json()) as { detail?: unknown };
      if (j?.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, path, msg);
  }
  return (await r.json()) as Bom;
}

export async function downloadBomCsv(layoutId: string): Promise<void> {
  await session().api.download(bomPath(layoutId, 'csv'), `bom_${layoutId}.csv`);
}

/** What changes when a layout's brackets are designed (layout.updated): item ids, masses and mesh URLs. */
export function itemsSignature(l: Pick<Layout, 'id' | 'extra_items'> | null): string {
  if (!l) return '';
  return `${l.id}|${(l.extra_items ?? []).map((i) => `${i.id}:${i.mass_kg ?? ''}:${i.mesh_url}`).join('|')}`;
}

/**
 * The layout the Overview shows (best validated, or the least-violating Stage 2 candidate), fetched in full, and
 * fetched again when its brackets are designed (the design run finishes, or layout.updated replaces it in the store).
 */
export function useShownLayout(): { item: RenderItem | null; layout: Layout | null; state: AsyncState<Layout> } {
  const best = useApp((s) => s.solver.best);
  const infeasible = useApp((s) => s.solver.infeasible);
  const newest = useApp((s) => s.conn.newest);
  const designedAt = useApp((s) => {
    const st = s.solver.studies['bracket_design'];
    return (st?.partial as { status?: string } | undefined)?.status === 'DONE' ? (st?.at ?? null) : null;
  });
  const item = useMemo(() => renderPlan({ best, infeasible, candidate: null }, newest, { expert: false, showGhost: false })[0] ?? null, [best, infeasible, newest]);
  const id = item?.layout.id ?? null;
  const sig = itemsSignature(item?.layout ?? null);
  const state = useAsync(id ? () => session().api.layout(id) : null, [id, designedAt, sig]);
  const layout = state.data && state.data.id === id ? state.data : item?.layout ?? null;
  return { item, layout, state };
}

/** The BOM of a layout, fetched again when its items change (designed brackets) or the part masses / parts change. */
export function useBom(layout: Layout | null): AsyncState<Bom> {
  const massRev = useApp((s) => s.conn.newest.mass_rev);
  const partsRev = useApp((s) => s.conn.newest.parts_rev);
  const id = layout?.id ?? null;
  const sig = itemsSignature(layout);
  return useAsync(id ? () => fetchBom(id) : null, [id, sig, massRev, partsRev]);
}
