// V2 WS6 engineering drawings: what is drawn, taken from the same data as the 3D view — the layout's poses with the
// parts' display meshes (placed like PartObject: world = R[orient] · (part_scale · p) + t), its extra items (brackets
// and other hardware, meshes in world coordinates from extra_items[].mesh_url) and the PC/104 rods of the Stage 2 frame
// (boxes) — and the sheets of the set: the assembly, then one detail sheet per designed bracket.

import type { BracketDesign, Layout, Mat3, Part, ProjectSnapshot } from '../../api/types';
import { itemNumbers, type Bom, type BomRow } from '../../lib/bom';
import type { Box3, V3 } from './projection';

export type DrawSource = { kind: 'part'; part: Part } | { kind: 'mesh'; url: string } | { kind: 'box'; min: V3; max: V3 };

export interface DrawTransform {
  R: Mat3;
  s: number;
  t: V3;
}

export interface DrawItem {
  /** id in the 3D render: part id, extra item id or frame item id */
  id: string;
  /** BOM item number (balloons), null when the BOM does not list it */
  itemNo: number | null;
  name: string;
  /** part a click on its balloon selects in the 3D view */
  partId: string | null;
  source: DrawSource;
  transform: DrawTransform;
}

export const IDENTITY: Mat3 = [
  [1, 0, 0],
  [0, 1, 0],
  [0, 0, 1],
];

export interface SheetSpec {
  key: string;
  kind: 'assembly' | 'detail';
  /** items rendered on this sheet */
  items: DrawItem[];
  /** detail sheets: the bracket's BOM row and design record */
  row?: BomRow;
  design?: BracketDesign & Record<string, unknown>;
}

export interface DrawingModel {
  layout: Layout;
  bom: Bom | null;
  items: DrawItem[];
  /** CubeSat envelope (model mm) */
  envelope: Box3;
  /** length used from the −Z end (metrics.length_used_mm) */
  usedLength: number | null;
  formFactor: string;
  sheets: SheetSpec[];
  /** changes whenever anything drawn changes (re-render key) */
  signature: string;
}

export function drawable(p: Part | undefined): p is Part {
  return !!p && (p.status === 'VALID' || p.status === 'REPAIRED' || p.status === 'WITHHELD') && p.triangles > 0;
}

export function envelopeOf(project: ProjectSnapshot | null): Box3 {
  const e = project?.enclosure;
  const size = (e?.size_mm as V3 | undefined) ?? [100, 100, 340.5];
  const min = (e?.min_mm as V3 | undefined) ?? [-size[0] / 2, -size[1] / 2, -size[2] / 2];
  const max = (e?.max_mm as V3 | undefined) ?? [size[0] / 2, size[1] / 2, size[2] / 2];
  return { min, max };
}

function partKeyOf(p: Part): string {
  return `${p.id}:${p.sha256}:${p.units}:${p.units_confirmed}`;
}

export function buildDrawingModel(layout: Layout, bom: Bom | null, parts: Record<string, Part>, rotations: Mat3[], project: ProjectSnapshot | null): DrawingModel {
  const nums = itemNumbers(bom && bom.layout_id === layout.id ? bom.items : []);
  const scale = layout.part_scale ?? 1;
  const items: DrawItem[] = [];
  for (const pose of layout.poses) {
    const part = parts[pose.part_id];
    if (!drawable(part)) continue;
    items.push({
      id: part.id,
      itemNo: nums.get(part.id) ?? null,
      name: part.name,
      partId: part.id,
      source: { kind: 'part', part },
      transform: { R: rotations[pose.orient] ?? IDENTITY, s: scale, t: [pose.t_um[0] / 1000, pose.t_um[1] / 1000, pose.t_um[2] / 1000] },
    });
  }
  for (const it of layout.extra_items ?? []) {
    if (!it.mesh_url) continue;
    items.push({ id: it.id, itemNo: nums.get(it.id) ?? null, name: it.label ?? it.kind, partId: it.for_part ?? null, source: { kind: 'mesh', url: it.mesh_url }, transform: { R: IDENTITY, s: 1, t: [0, 0, 0] } });
  }
  for (const f of layout.stage2?.frame ?? []) {
    if (f.kind !== 'rod' || !f.id) continue;
    items.push({ id: f.id, itemNo: nums.get(f.id) ?? null, name: 'PC/104 stack rod', partId: null, source: { kind: 'box', min: f.min, max: f.max }, transform: { R: IDENTITY, s: 1, t: [0, 0, 0] } });
  }
  const sheets: SheetSpec[] = [{ key: 'assembly', kind: 'assembly', items }];
  const designs = (layout.stage2?.bracket_designs ?? {}) as Record<string, BracketDesign & Record<string, unknown>>;
  for (const r of bom && bom.layout_id === layout.id ? bom.items : []) {
    if (r.group !== 'brackets' || !r.designed) continue;
    const it = items.find((x) => x.id === r.item_ids[0]);
    if (!it) continue;
    sheets.push({ key: `detail:${it.id}`, kind: 'detail', items: [it], row: r, design: designs[r.part_id ?? ''] });
  }
  const enc = project?.enclosure as { form_factor?: string; form?: string } | undefined;
  const ff = enc?.form_factor ?? project?.settings?.form_factor ?? /^(\d+U)\b/.exec(enc?.form ?? '')?.[1] ?? '';
  const signature = JSON.stringify([
    layout.id,
    scale,
    items.map((i) => [i.id, i.itemNo, i.source.kind === 'part' ? partKeyOf(i.source.part) : i.source.kind === 'mesh' ? i.source.url : [i.source.min, i.source.max]]),
    sheets.map((s) => s.key),
  ]);
  return { layout, bom, items, envelope: envelopeOf(project), usedLength: layout.metrics?.length_used_mm ?? null, formFactor: ff, sheets, signature };
}
