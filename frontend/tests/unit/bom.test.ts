import { describe, expect, it } from 'vitest';
import type { ExtraItem, Layout, Part } from '../../src/api/types';
import { bomCsv, buildBomClient, CSV_COLUMNS, gramText, groupRows, itemNumbers, partForRow, rowsForPart, sumRows } from '../../src/lib/bom';
import { makeMockBackend } from './helpers';

const F = 0.0012;

function part(id: string, mass: number | null, over: Partial<Part> = {}): Part {
  return {
    id, name: `part_${id}`, file: `${id}.stl`, sha256: id, units: 'mm', units_confirmed: true, status: 'VALID', status_detail: '', repairs: [], triangles: 12,
    display_triangles: 12, subsystem: 'power', labels: [], extents_mm: [10, 20, 30], volume_mm3: 6000, density_kg_m3: 2700, mass_kg: mass,
    mass_source: mass == null ? 'WITHHELD' : 'ASSUMED', com_canonical_mm: [0, 0, 0], inertia_com_kgm2: null, principal_kgm2: null, solidity: null, obb_fill: null,
    allowed_orients: [0], locked: false, lock_pose: null, tags: [], ...over,
  };
}

function bracket(k: number, pid: string, kind: string, nf: number, mass: number, over: Partial<ExtraItem> & { designed?: boolean } = {}) {
  return {
    item: { id: `L-9-br${k}`, kind: 'bracket', bracket_kind: kind, process: kind === 'metal_am' ? 'metal_am' : kind === 'clamp' ? 'catalogue' : kind, for_part: pid, mesh_url: `/api/items/L-9-br${k}/mesh`, mass_kg: mass, cost_rel: 1, material: 'AlSi10Mg (ASSUMED)', label: `${kind} bracket`, exact: kind !== 'metal_am', ...over } as ExtraItem,
    info: { name: `bracket:${pid}`, pid, kind, mount_type: kind, process: kind, fasteners: nf, gap_mm: 3, target: 'wall +x', reserve: [0, 0, 0, 1, 1, 1], depth_mm: 0, mass_kg: mass, cost_rel: 1, material: 'x', label: 'x', exact: true },
  };
}

/** A V2 Stage 2 layout: 4 parts (one withheld), a direct mount, a designed metal-AM bracket, an estimate and a clamp. */
function stage2(): { layout: Layout; parts: Record<string, Part> } {
  const parts = { a: part('a', 0.38), b: part('b', 0.19), c: part('c', 0.1), d: part('d', null) };
  const bs = [
    bracket(0, 'a', 'direct', 4, 0.0046 + 4 * F),
    bracket(1, 'b', 'metal_am', 3, 0.0068 + 3 * F, { designed: true, exact: true }),
    bracket(2, 'c', 'metal_am', 3, 0.0092 + 3 * F),
    bracket(3, 'd', 'clamp', 2, 0.015 + 2 * F),
  ];
  const extra = bs.map((b) => b.item);
  const massOfItems = extra.reduce((s, i) => s + (i.mass_kg ?? 0), 0);
  const layout = {
    id: 'L-9', hash: 'h', stage: 2, mode: 'default', status: 'VALIDATED', parts_rev: 1, constraint_rev: 1, mass_rev: 1, weights_rev: 1,
    poses: ['a', 'b', 'c', 'd'].map((id) => ({ part_id: id, orient: 0, t_um: [0, 0, 0] })), extra_items: extra,
    metrics: { mass_kg: 0.38 + 0.19 + 0.1 + massOfItems }, scores: null, algorithm: null, validation: null, origin: 'search', created: '2026-10-24T00:00:00Z',
    stage2: {
      mode: 'default', corridor: null, stack_span_mm: null, overflow_mm: 0, unmounted: [], mounts: {}, cable_blocked_fraction: null, frame: [], insertion_order: null, assumed: [],
      brackets: bs.map((b) => b.info),
      bracket_designs: { b: { pid: 'b', generator: 'TEST', mass_kg: 0.0068 + 3 * F, solid_mass_kg: 0.0068, fastener_mass_kg: 3 * F, cost_rel: 12, label: 'designed', passed: true, reason: '', sigma_mpa: 10, ms_yield: 1, ms_ult: 2, f1_hz: 900 } },
    },
  } as unknown as Layout;
  return { layout, parts };
}

describe('V2 WS6 bill of materials helpers', () => {
  it('splits every bracket into its solid and one aggregated fastener row, so nothing is counted twice', () => {
    const { layout, parts } = stage2();
    const bom = buildBomClient(layout, parts, ['d', 'c', 'b', 'a'], 0.97);
    expect(bom.items.filter((r) => r.group === 'parts').map((r) => r.part_id)).toEqual(['d', 'c', 'b', 'a']);
    const fast = bom.items.filter((r) => r.kind === 'fastener');
    expect(fast).toHaveLength(1);
    expect(fast[0].qty).toBe(4 + 3 + 3 + 2);
    expect(fast[0].unit_mass_kg).toBe(F);
    expect(fast[0].total_mass_kg).toBeCloseTo(12 * F, 12);
    const am = bom.items.find((r) => r.group === 'brackets' && r.part_id === 'b')!;
    expect(am.mass_source).toBe('designed');
    expect(am.unit_mass_kg).toBeCloseTo(0.0068, 12);
    expect(bom.items.find((r) => r.part_id === 'c' && r.group === 'brackets')!.mass_source).toBe('ESTIMATE');
    expect(bom.items.find((r) => r.part_id === 'd' && r.group === 'brackets')!.mass_source).toBe('catalogue');
    // the direct mount is not a bracket: its spacer washers are hardware
    expect(bom.items.some((r) => r.group === 'brackets' && r.part_id === 'a')).toBe(false);
    expect(bom.items.find((r) => r.kind === 'washer_set')!.unit_mass_kg).toBeCloseTo(0.0046, 12);
    // totals: parts with a mass + every item's mass as the layout gives it (fasteners included there)
    const s = sumRows(bom.items);
    expect(s.parts).toBeCloseTo(0.38 + 0.19 + 0.1, 12);
    expect(s.hardware).toBeCloseTo(layout.extra_items.reduce((a, i) => a + (i.mass_kg ?? 0), 0), 12);
    expect(bom.totals.matches_metrics).toBe(true);
    expect(bom.totals.frame_kg).toBe(0.97);
    expect(bom.totals.with_frame_kg).toBeCloseTo(s.assembly + 0.97, 12);
    expect(bom.totals.withheld).toEqual(['part_d']);
    for (const r of bom.items) if (r.unit_mass_kg != null) expect(r.total_mass_kg).toBeCloseTo(r.unit_mass_kg * r.qty, 12);
    expect(bom.items.map((r) => r.item_no)).toEqual(bom.items.map((_, i) => i + 1));
  });

  it('links rows and 3D ids both ways: a part, its bracket, the shared hardware', () => {
    const { layout, parts } = stage2();
    const bom = buildBomClient(layout, parts, ['a', 'b', 'c', 'd']);
    const nums = itemNumbers(bom.items);
    for (const it of layout.extra_items) expect(nums.has(it.id)).toBe(true);
    const owners = bom.items.flatMap((r) => r.item_ids);
    expect(new Set(owners).size).toBe(owners.length); // every 3D object belongs to one row (one balloon number)
    for (const p of ['a', 'b', 'c', 'd']) expect(bom.items[nums.get(p)! - 1].part_id).toBe(p);
    const sel = rowsForPart(bom.items, 'b');
    const own = [...sel.own].map((n) => bom.items[n - 1]);
    expect(own.map((r) => r.group).sort()).toEqual(['brackets', 'parts']);
    expect([...sel.related].map((n) => bom.items[n - 1].kind)).toEqual(['fastener']);
    expect(rowsForPart(bom.items, null).own.size).toBe(0);
    const fast = bom.items.find((r) => r.kind === 'fastener')!;
    expect(partForRow(fast)).toBeNull(); // shared by several parts: no single part to select
    expect(partForRow(bom.items.find((r) => r.kind === 'washer_set')!)).toBe('a');
    expect(partForRow(bom.items.find((r) => r.group === 'brackets' && r.part_id === 'c')!)).toBe('c');
    expect(groupRows(bom).map((g) => g.id)).toEqual(['parts', 'brackets', 'hardware']);
  });

  it('writes the same CSV columns as the backend, with totals', () => {
    const { layout, parts } = stage2();
    const csv = bomCsv(buildBomClient(layout, parts, [], 0.5));
    expect(csv.startsWith('﻿"# Bill of materials, layout L-9')).toBe(true); // quoted like Python's csv module
    const lines = csv.slice(1).trim().split('\r\n');
    expect(lines[2]).toBe(CSV_COLUMNS.join(','));
    expect(CSV_COLUMNS).toEqual(['item', 'group', 'name', 'qty', 'material', 'process', 'unit_mass_kg', 'total_mass_kg', 'mass_source', 'in_total', 'part_id', 'description', 'item_ids']);
    expect(lines.filter((l) => /^\d+,/.test(l))).toHaveLength(4 + 3 + 2 + 1);
    expect(lines.some((l) => l.startsWith(',TOTAL,parts + hardware'))).toBe(true);
    expect(lines.some((l) => l.startsWith(',TOTAL,"frame (listed, not included)",'))).toBe(true);
    expect(gramText(0.0012)).toBe('1.2');
    expect(gramText(2.9159)).toBe('2,915.9');
    expect(gramText(null)).toBe('—');
  });

  it('the MOCK backend serves a BOM of its placeholder layout, tagged mock, equal to the layout mass', async () => {
    const mb = makeMockBackend();
    const r = await mb.handle('/api/layouts/L-MOCK-0001/bom');
    expect(r.status).toBe(200);
    const bom = await r.json();
    expect(bom.mock).toBe(true);
    expect(bom.items).toHaveLength(19);
    expect(bom.items.every((x: { group: string }) => x.group === 'parts')).toBe(true);
    expect(bom.totals.matches_metrics).toBe(true);
    expect(bom.totals.assembly_kg).toBeCloseTo(2.916, 3);
    const c = await mb.handle('/api/layouts/L-MOCK-0001/bom?format=csv');
    expect(c.headers.get('content-type')).toContain('text/csv');
    expect((await mb.handle('/api/layouts/L-NOPE/bom')).status).toBe(404);
  });
});
