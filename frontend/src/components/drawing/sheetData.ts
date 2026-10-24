// V2 WS6 engineering drawings: one sheet of the set, ready to draw — the arranged views with their rendered images,
// and every vector computed from the same projection: the envelope / reserved-box outlines (phantom lines), centre
// lines, overall dimensions, balloons, the title block values, the revision block and the parts list or notes.

import { STATUS_LINE, type Bom, type BomRow } from '../../lib/bom';
import { BALLOON_R, chooseBalloonViews, LANE_W, placeBalloons, type Balloon, type Visibility } from './balloons';
import { arrangeViews, type Margins, type SheetLayout, type ViewSlot } from './layout';
import type { DrawingModel, SheetSpec } from './model';
import { boxCentre, boxEdges, dimText, linearDim, project, scaleLabel, type Box3, type LinearDim, type P2, type V3, type ViewId } from './projection';
import { loadItems, renderViews, RENDER_DEFAULTS, worldBox, type ViewRender } from './render';
import type { Revision, SheetTemplate, TitleValues } from './sheet';

export interface PartsListRow {
  item: number;
  qty: number;
  name: string;
  material: string;
  mass: string;
  source: string;
  partId: string | null;
}

export interface SheetData {
  key: string;
  index: number;
  count: number;
  kind: 'assembly' | 'detail';
  template: SheetTemplate;
  layout: SheetLayout;
  renders: ViewRender[];
  /** phantom lines (ISO 128 05.1): the CubeSat envelope, or a bracket's reserved box */
  phantom: [P2, P2][];
  centre: [P2, P2][];
  dims: LinearDim[];
  balloons: Balloon[];
  /** bolt / hole centres from the design record (sheet points per view), when it has them */
  holes: { c: P2; r: number }[];
  title: TitleValues;
  revisions: Revision[];
  parts: PartsListRow[] | null;
  notes: string[] | null;
  /** BOM items with geometry that no view shows (no balloon) */
  unballooned: number[];
  /** rendering failed (no WebGL): the vectors only */
  renderError: string | null;
  partSelection: Record<number, string | null>;
}

const today = () => new Date().toISOString().slice(0, 10);
const dateOf = (iso: string | null | undefined) => (iso && /^\d{4}-\d{2}-\d{2}/.test(iso) ? iso.slice(0, 10) : '—');
const pad3 = (n: number) => String(n).padStart(3, '0');

/** Space around each view (sheet mm): assembly views get balloon lanes; the front view the height dimensions. */
export function viewMargins(kind: 'assembly' | 'detail'): (v: ViewId) => Margins {
  const lane = kind === 'assembly' ? LANE_W : 6;
  return (v) => {
    if (v === 'front') return { l: 22 + lane, r: lane, t: 3, b: 8 };
    if (v === 'iso') return { l: lane, r: lane, t: 3, b: 8 };
    return { l: lane, r: lane, t: 3, b: 16 };
  };
}

/** Overall dimensions: the front view's height (and the used length as a reference dimension), the plan's width
 * (x) and the side view's width (y) — each once. */
export function overallDims(views: ViewSlot[], box: Box3, usedLength: number | null): LinearDim[] {
  const out: LinearDim[] = [];
  const front = views.find((v) => v.view === 'front');
  const top = views.find((v) => v.view === 'top');
  const side = views.find((v) => v.view === 'left' || v.view === 'right');
  const [x0, y0, z0] = box.min;
  const [x1, y1, z1] = box.max;
  if (front) {
    const a = project(front, [x0, y0, z0]);
    const b = project(front, [x0, y0, z1]);
    if (usedLength != null && usedLength > 0 && usedLength < z1 - z0 - 1e-6) {
      out.push(linearDim(a, project(front, [x0, y0, z0 + usedLength]), 'y', -1, 8, dimText(usedLength, true)));
      out.push(linearDim(a, b, 'y', -1, 16, dimText(z1 - z0)));
    } else out.push(linearDim(a, b, 'y', -1, 8, dimText(z1 - z0)));
  }
  if (top) out.push(linearDim(project(top, [x0, y0, z0]), project(top, [x1, y0, z0]), 'x', 1, 8, dimText(x1 - x0)));
  if (side) {
    const ends: [V3, V3] = [
      [x0, y0, z0],
      [x0, y1, z0],
    ];
    const p = ends.map((q) => project(side, q)).sort((m, n) => m[0] - n[0]) as [P2, P2];
    out.push(linearDim(p[0], p[1], 'x', 1, 8, dimText(y1 - y0)));
  }
  return out;
}

/** Centre lines of the envelope's axes in the orthographic views, 3 mm beyond the outline. */
export function centreLines(views: ViewSlot[], box: Box3): [P2, P2][] {
  const c = boxCentre(box);
  const out: [P2, P2][] = [];
  for (const v of views) {
    if (v.view === 'iso') continue;
    const p = project(v, c);
    if (v.view !== 'top') out.push([[p[0], v.y - 3], [p[0], v.y + v.h + 3]]);
    else {
      out.push([[p[0], v.y - 3], [p[0], v.y + v.h + 3]]);
      out.push([[v.x - 3, p[1]], [v.x + v.w + 3, p[1]]]);
    }
  }
  return out;
}

/** Balloons per view, each item once (largest visible area), in lanes at the outer edge of the side margins. */
export function sheetBalloons(views: ViewSlot[], renders: ViewRender[]): { balloons: Balloon[]; shown: Set<number> } {
  const vis: Visibility[] = renders.flatMap((r) => r.vis);
  const chosen = chooseBalloonViews(vis);
  const balloons: Balloon[] = [];
  for (const v of views) {
    const refs = [...chosen.values()].filter((c) => c.view === v.view);
    if (!refs.length) continue;
    const lanes = { left: v.x - v.margins.l + BALLOON_R + 0.5, right: v.x + v.w + v.margins.r - BALLOON_R - 0.5 };
    balloons.push(...placeBalloons(v, lanes, [v.y - v.margins.t, v.y + v.h], refs));
  }
  return { balloons, shown: new Set(chosen.keys()) };
}

function partsRows(bom: Bom): PartsListRow[] {
  return bom.items.map((r) => ({
    item: r.item_no,
    qty: r.qty,
    name: r.name,
    material: r.material,
    mass: r.unit_mass_kg == null ? '—' : (r.unit_mass_kg * 1000).toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
    source: r.mass_source === 'USER_MASS' || r.mass_source === 'USER_DENSITY' ? 'USER' : r.mass_source,
    partId: r.part_id ?? (r.for_parts.length === 1 ? r.for_parts[0] : null),
  }));
}

export interface SheetContext {
  model: DrawingModel;
  template: SheetTemplate;
  hidden: boolean;
  /** "BEST VALIDATED" … for the subtitle */
  badge: string;
  /** when the layout's brackets were designed, if this session saw it */
  designedAt: string | null;
}

function titleFor(spec: SheetSpec, ctx: SheetContext, index: number, count: number, scale: number): TitleValues {
  const L = ctx.model.layout;
  const bom = ctx.model.bom && ctx.model.bom.layout_id === L.id ? ctx.model.bom : null;
  const s2 = L.stage === 2;
  const base: TitleValues = {
    title: '',
    subtitle: '',
    drawingNo: '',
    rev: 'A',
    date: today(),
    sheet: `${index + 1}/${count}`,
    scale: scaleLabel(scale),
    size: ctx.template.size,
    units: 'mm',
    mass: '—',
    material: '—',
    process: '—',
    tolerances: 'ISO 2768-m (ASSUMED)',
    drawnBy: 'TEXT-TO-SPACESHIP (generated)',
    approved: 'not reviewed',
    reference: `layout ${L.id} · Stage ${L.stage}`,
    docType: spec.kind === 'assembly' ? 'Assembly drawing' : 'Detail drawing',
    status: s2 ? STATUS_LINE : 'IDEALIZED (Stage 1) — not flight-qualified; not for manufacture',
    lang: 'en',
  };
  if (spec.kind === 'assembly') {
    const designed = (bom?.items ?? []).filter((r) => r.designed).length;
    const mass = bom ? bom.totals.assembly_kg : L.metrics?.mass_kg ?? null;
    return {
      ...base,
      title: `CubeSat ${ctx.model.formFactor || ''} assembly`.replace('  ', ' '),
      subtitle: `${L.id} · ${ctx.badge}`,
      drawingNo: `T2S-${L.id}-000`,
      rev: designed ? 'B' : 'A',
      mass: mass == null ? '—' : `${mass.toFixed(3)} kg${bom ? ' (parts + hardware)' : ' (layout metrics)'}`,
      material: 'see parts list',
      process: 'assembly',
    };
  }
  const r = spec.row as BomRow;
  return {
    ...base,
    title: r.name,
    subtitle: `item ${r.item_no} of ${L.id}`,
    drawingNo: `T2S-${L.id}-${pad3(r.item_no)}`,
    mass: r.unit_mass_kg == null ? '—' : `${(r.unit_mass_kg * 1000).toFixed(1)} g (${r.mass_source}, without fasteners)`,
    material: r.material,
    process: r.process,
  };
}

function revisionsFor(spec: SheetSpec, ctx: SheetContext): Revision[] {
  const L = ctx.model.layout;
  const bom = ctx.model.bom && ctx.model.bom.layout_id === L.id ? ctx.model.bom : null;
  const designed = (bom?.items ?? []).filter((r) => r.designed).length;
  const estimates = (bom?.items ?? []).filter((r) => r.mass_source === 'ESTIMATE').length;
  if (spec.kind === 'detail') {
    return [{ rev: 'A', description: `Designed bracket of ${L.id}: ${spec.design?.generator ?? 'generated'} solid`, date: dateOf(ctx.designedAt), approved: '—' }];
  }
  const out: Revision[] = [{ rev: 'A', description: `Generated from layout ${L.id}${estimates && !designed ? `; ${estimates} bracket mass(es) are ESTIMATES` : ''}`, date: dateOf(L.created), approved: '—' }];
  if (designed) out.push({ rev: 'B', description: `${designed} bracket(s) designed: the solids replace the reserved-box estimates`, date: dateOf(ctx.designedAt), approved: '—' });
  return out;
}

function detailNotes(spec: SheetSpec): string[] {
  const d = spec.design;
  const r = spec.row as BomRow;
  const n: string[] = [];
  if (d) {
    const solvers = Object.values((d.solvers ?? {}) as Record<string, { solver?: string }>).map((s) => s.solver).filter(Boolean);
    n.push(`Designed by ${d.generator}${typeof d.vol_frac === 'number' ? ` (volume fraction ${d.vol_frac})` : ''}; ${d.passed ? 'passed' : `did not pass: ${d.reason || 'see Mounting Hardware'}`}${solvers.length ? ` (checked with ${solvers.join(' and ')})` : ''}.`);
    const ms = [d.ms_yield != null ? `MS yield ${d.ms_yield >= 0 ? '+' : ''}${d.ms_yield.toFixed(2)}` : null, d.ms_ult != null ? `MS ultimate ${d.ms_ult >= 0 ? '+' : ''}${d.ms_ult.toFixed(2)}` : null, d.f1_hz != null ? `first natural frequency ${Math.round(d.f1_hz)} Hz with the part` : null].filter(Boolean);
    if (ms.length) n.push(`${ms.join(', ')} (design record).`);
    if (typeof d.overhang_fraction === 'number') n.push(`Overhang beyond 45°: ${(100 * d.overhang_fraction).toFixed(1)} % of the surface (supports).`);
    if (typeof d.voxel_mm === 'number') n.push(`Generated on ${d.voxel_mm} mm voxels: surfaces are faceted.`);
  }
  if (!holesOf(spec).length) n.push('Fastener holes are not modelled in the concept mesh (M3 clearance 3.4 mm, mfg rule); no bolt positions in the design record.');
  n.push(`Mass ${r.unit_mass_kg != null ? `${(r.unit_mass_kg * 1000).toFixed(1)} g` : '—'} is the solid alone; its fasteners are a separate BOM item.`);
  n.push('Phantom outline: the reserved box the bracket was designed in. General tolerances ISO 2768-m (ASSUMED).');
  return n;
}

/** Bolt / hole centres of a design record, when it has any (world mm). Absent in today's records. */
export function holesOf(spec: SheetSpec): V3[] {
  const d = (spec.design ?? {}) as Record<string, unknown>;
  const raw = (d.bolts ?? d.bolt_positions_mm ?? d.holes) as unknown;
  if (!Array.isArray(raw)) return [];
  const out: V3[] = [];
  for (const b of raw) {
    const o = (b ?? {}) as Record<string, unknown>;
    const p = Array.isArray(b) ? b : (o.p ?? o.pos ?? o.xyz ?? o.centre_mm);
    if (Array.isArray(p) && p.length === 3 && p.every((x) => typeof x === 'number')) out.push(p as V3);
  }
  return out;
}

/** Rendered views of a sheet, kept while the geometry and the arrangement stay the same (a mass edit only changes
 * the parts list and the title block). */
export type RenderCache = Map<string, { renders: ViewRender[]; renderError: string | null }>;

/** Build one sheet: arrange, render (async, cached), then the vectors and the balloons. */
export async function buildSheet(spec: SheetSpec, index: number, ctx: SheetContext, alive: () => boolean, cache?: RenderCache): Promise<SheetData | null> {
  const loaded = await loadItems(spec.items);
  if (!alive()) return null;
  const model = ctx.model;
  let box: Box3 = model.envelope;
  let reserve: Box3 | null = null;
  if (spec.kind === 'detail') {
    const wb = worldBox(loaded);
    if (!wb) return null;
    box = wb;
    const it = model.layout.extra_items.find((x) => x.id === spec.items[0]?.id);
    if (it?.box_mm?.length === 6) reserve = { min: it.box_mm.slice(0, 3) as V3, max: it.box_mm.slice(3) as V3 };
    if (reserve) box = { min: box.min.map((v, k) => Math.min(v, reserve!.min[k])) as V3, max: box.max.map((v, k) => Math.max(v, reserve!.max[k])) as V3 };
  }
  const bom = model.bom && model.bom.layout_id === model.layout.id ? model.bom : null;
  const revisions = revisionsFor(spec, ctx);
  const layout = arrangeViews({
    template: ctx.template,
    box,
    partsRows: spec.kind === 'assembly' ? (bom?.items.length ?? 0) : null,
    notesH: spec.kind === 'detail' ? 46 : undefined,
    revRows: revisions.length,
    margins: viewMargins(spec.kind),
    maxScale: spec.kind === 'detail' ? 10 : 2,
  });
  if (!layout) return null;
  const key = JSON.stringify([model.signature, ctx.template.id, ctx.hidden, spec.key, layout.views.map((v) => [v.view, v.x, v.y, v.scale])]);
  let hit = cache?.get(key);
  if (!hit) {
    let renders: ViewRender[] = [];
    let renderError: string | null = null;
    try {
      renders = await renderViews(loaded, layout.views, { ...RENDER_DEFAULTS, hidden: ctx.hidden }, alive);
    } catch (e) {
      renderError = `The views could not be rendered (${(e as Error).message}); outlines and dimensions only.`;
    }
    if (!alive()) return null;
    hit = { renders, renderError };
    if (cache) {
      if (cache.size > 24) cache.delete(cache.keys().next().value as string);
      cache.set(key, hit);
    }
  }
  const { renders, renderError } = hit;
  const phantom = layout.views.flatMap((v) => boxEdges(v, spec.kind === 'assembly' ? model.envelope : (reserve ?? box)));
  const dims = overallDims(layout.views, spec.kind === 'assembly' ? model.envelope : box, spec.kind === 'assembly' ? model.usedLength : null);
  const centre = spec.kind === 'assembly' ? centreLines(layout.views, model.envelope) : [];
  const { balloons, shown } = spec.kind === 'assembly' ? sheetBalloons(layout.views, renders) : { balloons: [], shown: new Set<number>() };
  const drawnNos = new Set(spec.items.map((i) => i.itemNo).filter((n): n is number => n != null));
  const unballooned = spec.kind === 'assembly' && !renderError ? [...drawnNos].filter((n) => !shown.has(n)).sort((a, b) => a - b) : [];
  const holes = holesOf(spec).flatMap((p) => layout.views.filter((v) => v.view !== 'iso').map((v) => ({ c: project(v, p), r: 1.7 * v.scale })));
  const partSelection: Record<number, string | null> = {};
  for (const r of bom?.items ?? []) partSelection[r.item_no] = r.part_id ?? (r.for_parts.length === 1 ? r.for_parts[0] : null);
  const count = model.sheets.length;
  return {
    key: spec.key,
    index,
    count,
    kind: spec.kind,
    template: ctx.template,
    layout,
    renders,
    phantom,
    centre,
    dims,
    balloons,
    holes,
    title: titleFor(spec, ctx, index, count, layout.scale),
    revisions,
    parts: spec.kind === 'assembly' && bom ? partsRows(bom) : null,
    notes: spec.kind === 'detail' ? detailNotes(spec) : null,
    unballooned,
    renderError,
    partSelection,
  };
}
