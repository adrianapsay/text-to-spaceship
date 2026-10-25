import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { initialSolver } from '../../src/api/protocol';
import type { BracketLayouts, DesignOptions, OnePieceEstimate, Settings } from '../../src/api/types';
import { BracketLayoutTable, columnCells, frameCells, LayoutRunForm, MODES, sizeText } from '../../src/components/BracketLayouts';
import { DesignProgressPanel, designRunView, headline } from '../../src/components/DesignProgress';
import { appStore, initialState } from '../../src/store/store';

afterEach(() => appStore.setState(initialState()));

const frameCellsOf = (d: BracketLayouts) => Object.fromEntries(MODES.map((m) => [m, frameCells(d.modes[m])]));

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

  it('the whole satellite with each layout: f1 against the guidance, deflection, frame margin, mass; a check button per column', () => {
    const d = data();
    d.modes.one_piece = {
      ...d.modes.one_piece,
      status: 'designed',
      brace_frame: true,
      summary: summary({ mode: 'one_piece', passed: true, failed: [] }),
      frame_check: {
        f1_hz: 87.6, f1_guidance_hz: 100, static_g: 54.1, max_deflection_mm: 0.1234, max_deflection_axis: 'y', total_mass_kg: 3.456,
        groups: { frame: { ms_yield: 11.29, ms_ult: 12.2, governing: 'random limit', checks: [], mass_kg: 0.97, elements: 100 } }, estimated: [],
      },
    };
    d.modes.per_part = { ...d.modes.per_part, frame_check: { error: 'not solved: memory' } };
    const fc = frameCellsOf(d);
    expect(fc.one_piece.sat_f1).toBe('88 Hz — below 100 Hz');
    expect(fc.one_piece.sat_defl).toBe('0.123 mm (54 g along y)');
    expect(fc.one_piece.sat_frame).toBe('MS +11.29 — random limit');
    expect(fc.one_piece.sat_mass).toBe('3.456 kg');
    expect(fc.per_part.sat_f1).toBe('not checked: not solved: memory');
    expect(fc.combined.sat_f1).toBe('—');
    const onCheck = vi.fn();
    const { getByTestId } = render(<BracketLayoutTable data={d} running={false} onUse={vi.fn()} onRun={vi.fn()} onCheck={onCheck} />);
    expect(getByTestId('layout-col-one_piece').textContent).toContain('braces the frame');
    expect(getByTestId('check-one_piece').textContent).toBe('Check the whole satellite again');
    fireEvent.click(getByTestId('check-per_part'));
    expect(onCheck).toHaveBeenCalledWith('per_part');
  });

  it('bracing the frame needs the Bracket budget at 100 and goes with the run settings', () => {
    const onStart = vi.fn();
    const base = { mode: 'one_piece' as const, options: null, budgetRange: [60, 7200] as [number, number], running: false, onStart, onEstimate: vi.fn() };
    const settings = (budget: number) => ({ stage: 2, sliders: { bracket_budget: budget } }) as unknown as Settings;
    const est = { grid: [36, 36, 86], h_mm: [2.667, 2.667, 3.913], free_voxels: 1, held_parts: 1, kept_brackets: [], dofs_fine: 1, dofs_coarse: 1, fe_dofs_estimate: 1, seconds_estimate: 60, simp_seconds_estimate: 30, fe_seconds_estimate: 30, memory_mb_estimate: 100, available_mb: 4096, budget_s: 900, notes: [], model: '' } as OnePieceEstimate;
    const { getByTestId, rerender } = render(<LayoutRunForm {...base} settings={settings(50)} estimate={est} />);
    const box = getByTestId('brace-frame') as HTMLInputElement;
    expect(box.disabled).toBe(true);
    rerender(<LayoutRunForm {...base} settings={settings(100)} estimate={est} />);
    fireEvent.click(getByTestId('brace-frame'));
    fireEvent.click(getByTestId('start-one_piece'));
    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ brace_frame: true }));
  });

  it('a whole-satellite check that did not fit in memory is "not checked", not failed', () => {
    const reason = 'not solved: whole satellite with 110829 dofs needs about 451 MB; 2300 MB available, 2000 MB must stay free';
    const row = { k: 0, pid: 'whole satellite', kind: 'frame_check', label: 'whole satellite (per part)', status: 'done' as const, started_s: 0, seconds: 25, passed: false, solid: false, reason };
    const run = { status: 'DONE', layout_id: 'L-2163', mode: 'frame_check' as const, brackets: [row], n_total: 1, n_done: 1, workers: 1, seconds: 25, eta_s: null };
    appStore.setState({ solver: { ...initialSolver(), studies: { bracket_design: { progress: 1, partial: run, at: new Date().toISOString() } } } });
    const { getByTestId } = render(<DesignProgressPanel />);
    const text = getByTestId('design-progress').textContent ?? '';
    expect(text).toContain('Whole satellite of L-2163 not checked (25 s)');
    expect(text).toContain('not checked 25 s');                                 // the row's badge and time
    expect(text).not.toContain('failed');
    expect(text).not.toContain('passed');
    const ok = { ...run, brackets: [{ ...row, solid: true, passed: true, reason: '' }] };
    appStore.setState({ solver: { ...initialSolver(), studies: { bracket_design: { progress: 1, partial: ok, at: new Date().toISOString() } } } });
    const again = render(<DesignProgressPanel />).getAllByTestId('design-progress').at(-1)?.textContent ?? '';
    expect(again).toContain('Whole satellite of L-2163 checked in 25 s');
    expect(again).toContain('passed');
  });

  it('the progress headline names the layout being designed', () => {
    const run = { status: 'RUNNING', layout_id: 'L-2002', mode: 'combined' as const, brackets: [{ k: 0, pid: 'combined:1', kind: 'combined', status: 'running' as const, started_s: 0 }], n_total: 1, n_done: 0, workers: 1, seconds: 10, eta_s: null };
    const v = designRunView(run, undefined, Date.now());
    expect(v && headline(v)).toContain('Designing the combined brackets of L-2002: 0 of 1 done');
    const done = designRunView({ ...run, status: 'DONE', mode: 'one_piece' as const }, undefined, Date.now());
    expect(done && headline(done)).toContain('One piece of L-2002 designed');
  });
});
