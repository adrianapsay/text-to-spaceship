import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import type { BracketLayouts, DesignOptions, OnePieceEstimate } from '../../src/api/types';
import { BracketLayoutTable, columnCells, LayoutRunForm, sizeText } from '../../src/components/BracketLayouts';
import { designRunView, headline } from '../../src/components/DesignProgress';

const summary = (over: Record<string, unknown> = {}) => ({
  mode: 'per_part' as const,
  bracket_mass_kg: 0.1234,
  estimates: 0,
  worst: { case: 'static', axis: 'y', check: 'flange bearing yield', ms: 6.3, part: 'bolt', bracket: 'bracket:p12' },
  f1: { f_hz: 9312.4, bracket: 'bracket:p17' },
  prints: 9,
  largest_print_mm: [43.2, 7.0, 41.0],
  largest_fits: true,
  build_volume_mm: [250, 250, 325],
  pieces: 17,
  ...over,
});

const data = (over: Partial<BracketLayouts> = {}): BracketLayouts => ({
  layout_id: 'L-2002',
  chosen: 'per_part',
  active: 'per_part',
  modes: {
    per_part: { mode: 'per_part', name: 'one bracket per part', status: 'designed', summary: summary() },
    combined: {
      mode: 'combined',
      name: 'combined per wall',
      status: 'designed',
      summary: summary({ mode: 'combined', bracket_mass_kg: 0.1301, prints: 5, largest_print_mm: [75.6, 12.7, 88.6], passed: true, failed: [] }),
      result: {
        status: 'designed',
        designs: { 'p06+p07+p10+p12+p17': { name: 'combined:1', kind: 'combined', parts: ['p06', 'p07', 'p10', 'p12', 'p17'], passed: true, mass_kg: 0.06 } },
      },
    },
    one_piece: { mode: 'one_piece', name: 'one piece', status: 'not run', summary: null, result: null },
  },
  combined_plan: [{ name: 'combined:1', pids: ['p06', 'p07', 'p10', 'p12', 'p17'], target: '+y wall', bridges: [] }],
  build_volume_mm: [250, 250, 325],
  build_volume_note: 'ASSUMED: 250 × 250 × 325 mm, a typical metal L-PBF machine',
  running: null,
  budget_range_s: [60, 7200],
  exploratory: { one_piece: true },
  ...over,
});

describe('M4 bracket layout comparison', () => {
  it('each column gives the mass, the worst margin with its check, f1, the prints and the largest print', () => {
    const d = data();
    const pp = columnCells(d.modes.per_part);
    expect(pp.mass).toBe('123.4 g');
    expect(pp.worst).toBe('MS +6.30 — static, y, bolt flange bearing yield (bracket:p12)');
    expect(pp.f1).toBe('9312 Hz (bracket:p17)');
    expect(pp.prints).toBe('9');
    expect(pp.largest).toBe('43 × 7 × 41 mm');
    expect(columnCells(d.modes.one_piece)).toEqual({ mass: '—', worst: '—', f1: '—', prints: '—', largest: '—' });
    const big = columnCells({ ...d.modes.per_part, summary: summary({ largest_print_mm: [96, 96, 330], largest_fits: false, estimates: 2 }) });
    expect(big.largest).toContain('larger than the build volume');
    expect(big.mass).toContain('2 ESTIMATEs');
    expect(sizeText(null)).toBe('—');
  });

  it('three columns; the chosen one marked; the one piece labelled exploratory; Use is offered only for designed layouts', () => {
    const onUse = vi.fn();
    const onRun = vi.fn();
    const { getByTestId } = render(<BracketLayoutTable data={data()} running={false} onUse={onUse} onRun={onRun} names={{ p06: 'tank' }} />);
    expect(getByTestId('layout-col-per_part').textContent).toContain('chosen');
    expect(getByTestId('layout-col-one_piece').textContent).toContain('exploratory');
    expect(getByTestId('cell-prints-combined').textContent).toBe('5');
    expect(getByTestId('cell-parts-combined').textContent).toContain('tank');
    expect((getByTestId('use-per_part') as HTMLButtonElement).disabled).toBe(true);        // already chosen
    expect((getByTestId('use-one_piece') as HTMLButtonElement).disabled).toBe(true);       // nothing designed
    fireEvent.click(getByTestId('use-combined'));
    expect(onUse).toHaveBeenCalledWith('combined');
    fireEvent.click(getByTestId('run-one_piece'));
    expect(onRun).toHaveBeenCalledWith('one_piece');
  });

  it('a combined bracket without a solid is marked, and its parts keep their own brackets in the numbers', () => {
    const d = data();
    d.modes.combined = {
      ...d.modes.combined,
      summary: summary({ mode: 'combined', passed: false, failed: ['p06+p07+p10+p12+p17'] }),
      result: {
        status: 'designed',
        designs: {
          'p06+p07+p10+p12+p17': { name: 'combined:1', kind: 'combined', parts: ['p06', 'p07'], passed: false, mass_kg: null, reason: 'not solved: memory' },
        },
      },
    };
    const { getByTestId } = render(<BracketLayoutTable data={d} running={false} onUse={vi.fn()} onRun={vi.fn()} />);
    expect(getByTestId('layout-col-combined').textContent).toContain('1 without a solid');
    expect(getByTestId('cell-parts-combined').textContent).toContain('no solid (not solved: memory): these parts keep their own brackets');
    expect((getByTestId('use-combined') as HTMLButtonElement).disabled).toBe(true);
  });

  it('nothing can start or be chosen while a design run is under way; nothing to combine means no combined run', () => {
    const { getByTestId } = render(<BracketLayoutTable data={data({ combined_plan: [] })} running onUse={vi.fn()} onRun={vi.fn()} />);
    for (const id of ['run-combined', 'run-one_piece', 'use-combined']) expect((getByTestId(id) as HTMLButtonElement).disabled).toBe(true);
  });

  it('the one piece is estimated before it can start; the run gets the settings and the time budget', () => {
    const options = {
      materials: [{ id: 'AlSi10Mg', name: 'AlSi10Mg', process: 'metal_am', E_mpa: 65000, yield_mpa: 170, ultimate_mpa: 280, density_g_cm3: 2.68, source: '' }],
      vol_frac: { range: [0.02, 0.8], ladder: [0.03, 0.05] },
      min_member_mm: { range: [1, 12], am_min_wall_mm: 2, generator_sets_member_size: true },
      bracket_material: 'AlSi10Mg',
    } as unknown as DesignOptions;
    const onStart = vi.fn();
    const onEstimate = vi.fn();
    const props = { mode: 'one_piece' as const, options, settings: null, budgetRange: [60, 7200] as [number, number], running: false, onStart, onEstimate };
    const { getByTestId, rerender } = render(<LayoutRunForm {...props} estimate={null} />);
    expect((getByTestId('start-one_piece') as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(getByTestId('estimate-one-piece'));
    expect(onEstimate).toHaveBeenCalled();
    const est: OnePieceEstimate = {
      grid: [36, 36, 85], h_mm: [2.667, 2.667, 3.959], free_voxels: 61234, held_parts: 17, kept_brackets: [], dofs_fine: 211000, dofs_coarse: 26000,
      fe_dofs_estimate: 150000, seconds_estimate: 845, simp_seconds_estimate: 600, fe_seconds_estimate: 225, memory_mb_estimate: 1350, available_mb: 4096,
      budget_s: 900, notes: [], model: 'ASSUMED cost model',
    };
    rerender(<LayoutRunForm {...props} estimate={est} />);
    expect(getByTestId('one-piece-estimate').textContent).toContain('14 min 05 s');
    fireEvent.change(getByTestId('layout-budget'), { target: { value: '20' } });
    fireEvent.click(getByTestId('start-one_piece'));
    expect(onStart).toHaveBeenCalledWith({ material: null, vol_frac: 'auto', min_member_mm: 'auto', budget_s: 1200 });
  });

  it('the progress headline names the layout being designed', () => {
    const run = { status: 'RUNNING', layout_id: 'L-2002', mode: 'combined' as const, brackets: [{ k: 0, pid: 'combined:1', kind: 'combined', status: 'running' as const, started_s: 0 }], n_total: 1, n_done: 0, workers: 1, seconds: 10, eta_s: null };
    const v = designRunView(run, undefined, Date.now());
    expect(v && headline(v)).toContain('Designing the combined brackets of L-2002: 0 of 1 done');
    const done = designRunView({ ...run, status: 'DONE', mode: 'one_piece' as const }, undefined, Date.now());
    expect(done && headline(done)).toContain('One piece of L-2002 designed');
  });
});
