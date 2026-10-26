import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, within } from '@testing-library/react';
import type { Analysis, Calc, CatalogList, Pick } from '../../src/builder/analysisTypes';
import { num, verdict, withUnit } from '../../src/builder/analysisTypes';
import { AnalysisSection, CalcCard } from '../../src/builder/AnalysisView';
import { ArchitectureSection, ChecksPanel, orbitText } from '../../src/builder/ArchitectureView';
import { TradeSection } from '../../src/builder/TradeView';
import { CatalogSection, GeometryCell } from '../../src/builder/CatalogView';
import { assumptions, summaryMarkdown } from '../../src/builder/summary';
import type { BuilderResponse } from '../../src/builder/types';

const calc = (over: Partial<Calc>): Calc => ({
  id: 'power.margin',
  label: 'Energy margin (worst day)',
  value: 31.9,
  unit: '%',
  equation: 'margin = E_generated / E_needed − 1',
  inputs: { E_generated: { value: 11.84, unit: 'Wh', source: 'power.generation' } },
  assumptions: ['design margin target 20 % (ASSUMED, as for mass)'],
  refs: ['tsi'],
  fidelity: 'conceptual',
  explain: 'The panels cover the loads with the design margin.',
  missing: null,
  ok: true,
  ...over,
});

const REFS = { tsi: { key: 'tsi', title: 'SORCE total solar irradiance', publisher: 'NASA GSFC', url: 'https://example.org/tsi', accessed: '2026-10-25' } };

const pick = (over: Partial<Pick>): Pick => ({
  slot: 'gnss',
  label: 'GNSS receiver',
  items: [
    {
      id: 'spacemanic-celeste', name: 'Spacemanic Celeste', qty: 1, category: 'gnss', mass_kg: 0.025, dims_mm: [67, 42, 7.5],
      power_w: { typical: 0.25, peak: null }, price: { value: 5200, currency: 'EUR', kind: 'listed', note: '' }, cad: 'public',
      url: 'https://example.org/celeste',
    },
  ],
  status: 'recommended',
  why: 'Locates the images on the ground.',
  need: '',
  alternatives: [{ id: 'skyfox-labs-pinav-ng-fm', name: 'SkyFox piNAV', score: 0.5, reason: 'ranked lower' }],
  flags: [],
  place: 'internal',
  ...over,
});

const analysis = (over: Partial<Analysis> = {}): Analysis => ({
  engine: 'test', computed_at: '2026-10-26T00:00:00', design_id: 'D-20261026-abcdef', design_version: 3, inputs_hash: 'h1', cached: false,
  fidelity: 'conceptual', mission_years: 2, prefs: { cost_performance: 0.5 }, size_u: 6, size_label: '6U',
  size_why: 'The smallest size that passes every hard check.', size_user: false,
  orbit: { choice: 'recommend', alt_km: 540, inc_deg: 97.55, ltdn_h: 10.5, sso: true, why: 'Sun-synchronous.', flags: [] },
  picks: {
    gnss: pick({}),
    solar: pick({ slot: 'solar', label: 'Solar panels', place: 'external', items: [{ ...pick({}).items[0], id: 'photon', name: 'PHOTON-SIDE', qty: 5 }], alternatives: [] }),
  },
  slots: [{ id: 'gnss', label: 'GNSS receiver', place: 'internal' }, { id: 'solar', label: 'Solar panels', place: 'external' }],
  calcs: { 'power.margin': calc({}) },
  groups: [{ id: 'power', label: 'Power', calcs: ['power.margin'] }],
  checks: [
    { rule: 'voltage', status: 'compatible', status_text: 'Compatible', title: 'Celeste: supply voltage', detail: 'needs 3.3 V', items: [], fix: '', source: '' },
    { rule: 'packing_model', status: 'incompatible', status_text: 'Incompatible', title: 'Camera: optimiser packing model', detail: 'too wide', items: [], fix: 'send a simplified shape', source: '' },
    { rule: 'power', status: 'unknown', status_text: 'Insufficient information to verify', title: 'Power', detail: 'XACT-15 power not published', items: [], fix: '', source: '' },
  ],
  check_summary: { counts: { compatible: 1, assumptions: 0, incompatible: 1, unknown: 1 }, overall: 'incompatible' },
  trade: [
    { size_u: 3, label: '3U', failures: ['the parts fill too much of the volume'], feasible: false, alt_km: 510, mass_kg: 4.3, mass_limit_kg: 6, margin_pct: 190, data_pct: 225, fill_pct: 96, cost: {}, quotes: 9, payload: ['MultiScape100'], gsd_m: 4.9, checks: { compatible: 1, assumptions: 0, incompatible: 0, unknown: 0 } },
    { size_u: 6, label: '6U', failures: [], feasible: true, alt_km: 540, mass_kg: 4.8, mass_limit_kg: 12, margin_pct: 31.9, data_pct: 255, fill_pct: 38, cost: {}, quotes: 9, payload: ['MultiScape100'], gsd_m: 5.1, checks: { compatible: 1, assumptions: 0, incompatible: 0, unknown: 0 } },
  ],
  failures: [], missing_hardware: ['a GNSS antenna'], flags: ['XACT-15 does not publish its power'],
  sliders: { cost_performance: { label: 'Cost ↔ performance', low: 'Lowest cost', high: 'Best performance', default: 0.5 } },
  refs: REFS, disclaimer: 'A conceptual design. It is not flight-ready.', open_questions: [],
  ...over,
});

afterEach(() => vi.useRealTimers());

describe('V3 Builder: Engineering Analysis', () => {
  it('writes numbers for people and reads a verdict from ok / meets / feasible', () => {
    expect(num(0.006944)).toBe('0.00694');
    expect(num(5423.4)).toBe('5,423');
    expect(num(31.91)).toBe('31.9');
    expect(withUnit(97.55, 'deg')).toBe('97.5°');
    expect(withUnit(31.9, '%')).toBe('31.9 %');
    expect(verdict(calc({}))).toBe(true);
    expect(verdict(calc({ ok: undefined, meets: false }))).toBe(false);
    expect(verdict(calc({ value: null, ok: null, missing: 'not published' }))).toBeNull();
  });

  it('a calculation shows its value, verdict and sentence, with the working one click away', () => {
    const { getByTestId, getByText } = render(<CalcCard c={calc({})} refs={REFS} expert={false} />);
    const card = getByTestId('calc-power.margin');
    expect(card.textContent).toContain('31.9 %');
    expect(card.textContent).toContain('meets');
    expect(getByText('Show the working')).toBeTruthy();
    const link = within(getByTestId('working-power.margin')).getByRole('link', { name: 'SORCE total solar irradiance' });
    expect(link.getAttribute('href')).toBe('https://example.org/tsi');
  });

  it('a value that cannot be computed says what it needs', () => {
    const { getByTestId } = render(<CalcCard c={calc({ id: 'adcs.knowledge', value: null, ok: null, missing: 'XACT-15 does not publish its attitude knowledge' })} refs={REFS} expert />);
    const card = getByTestId('calc-adcs.knowledge');
    expect(card.textContent).toContain('not computed');
    expect(card.textContent).toContain('cannot compute');
    expect(card.textContent).toContain('Needs: XACT-15 does not publish its attitude knowledge');
  });

  it('stale results are labelled as not current while the analysis recomputes', () => {
    const { getByTestId, getByRole } = render(<AnalysisSection a={analysis()} stale expert={false} />);
    expect(getByTestId('analysis').getAttribute('aria-busy')).toBe('true');
    expect(getByRole('status').textContent).toContain('not current');
  });
});

describe('V3 Builder: architecture, checks, trade study and catalog', () => {
  it('lists checks worst first and keeps the compatible ones folded', () => {
    const { getByTestId } = render(<ChecksPanel checks={analysis().checks} />);
    const inc = getByTestId('checks-incompatible') as HTMLDetailsElement;
    const ok = getByTestId('checks-compatible') as HTMLDetailsElement;
    expect(inc.open).toBe(true);
    expect(ok.open).toBe(false);
    expect(inc.compareDocumentPosition(ok) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('says the orbit in words', () => {
    expect(orbitText(analysis().orbit)).toBe('540 km, sun-synchronous 97.5° inclination, equator southbound at 10:30 local time');
  });

  it('changing a slot offers the alternatives and the way back to the recommendation', () => {
    const onSelect = vi.fn();
    const onUnselect = vi.fn();
    const a = analysis({ picks: { ...analysis().picks, gnss: pick({ status: 'user', recommended: { items: [{ id: 'x', name: 'X', qty: 1 }], status: 'recommended', why: '' } }) } });
    const catalog: CatalogList = { categories: { gnss: 'GNSS receiver' }, components: [], refs: {} };
    const { getByTestId } = render(
      <ArchitectureSection a={a} stale={false} busy={false} catalog={catalog} slots={[{ id: 'gnss', label: 'GNSS receiver', categories: ['gnss'], place: 'internal' }]} onSelect={onSelect} onUnselect={onUnselect} />,
    );
    expect(getByTestId('slot-solar').textContent).toContain('not packed');
    fireEvent.click(getByTestId('change-gnss'));
    fireEvent.click(getByTestId('use-gnss-skyfox-labs-pinav-ng-fm'));
    expect(onSelect).toHaveBeenCalledWith('gnss', 'skyfox-labs-pinav-ng-fm', 1);
    fireEvent.click(getByTestId('change-gnss'));
    fireEvent.click(getByTestId('reset-gnss'));
    expect(onUnselect).toHaveBeenCalledWith('gnss');
  });

  it('a slider is sent once the hand stops; a size is sent at once', () => {
    vi.useFakeTimers();
    const onPrefs = vi.fn();
    const { getByTestId } = render(<TradeSection a={analysis()} stale={false} busy={false} onPrefs={onPrefs} />);
    fireEvent.change(getByTestId('slider-cost_performance'), { target: { value: '0.2' } });
    fireEvent.change(getByTestId('slider-cost_performance'), { target: { value: '0.1' } });
    expect(onPrefs).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(onPrefs).toHaveBeenCalledTimes(1);
    expect(onPrefs).toHaveBeenLastCalledWith({ cost_performance: 0.1 });
    fireEvent.change(getByTestId('size-select'), { target: { value: '3' } });
    expect(onPrefs).toHaveBeenLastCalledWith({ size_u: 3 });
    expect(getByTestId('trade-table').textContent).toContain('1 failing');
  });

  it('the design summary carries the disclaimer, where each value came from, the parts with sources, checks and assumptions', () => {
    const r = {
      design: { id: 'D-20261026-abcdef', name: 'California imager', version: 3, statement: 'photograph California' },
      view: {
        requirements: [{ key: 'imaging.gsd_m', qid: 'imaging.gsd_m', prompt: 'Pixel size', value: 10, unit: 'm', source: 'default', note: '10 m suits land imaging (ASSUMED)', display: '10 m' }],
      },
    } as unknown as BuilderResponse;
    const md = summaryMarkdown(r, analysis());
    expect(md).toContain('# California imager');
    expect(md).toContain('It is not flight-ready.');
    expect(md).toContain('| Pixel size | 10 m | default (ASSUMED) |');
    expect(md).toContain('https://example.org/celeste');
    expect(md).toContain('### Incompatible (1)');
    expect(md).toContain('SORCE total solar irradiance — NASA GSFC. https://example.org/tsi (accessed 2026-10-25)');
    expect(assumptions(r, analysis())).toEqual(['Pixel size: 10 m — 10 m suits land imaging (ASSUMED)', 'design margin target 20 % (ASSUMED, as for mass)']);
  });

  it('a part\'s geometry says where it came from and imports the file the user picks', () => {
    const onImport = vi.fn();
    const onSimplified = vi.fn();
    const part = pick({}).items[0];
    const entry = {
      component: part.id, origin: 'bbox' as const, origin_text: 'Simplified bounding box', file: 'x/x.stl', source_name: null, source_url: null, sha256: null,
      imported: '2026-10-26T00:00:00', units: 'mm', scale: 1, extents_mm: [67, 42, 7.5], shift_mm: [0, 0, 0], volume_mm3: 21105, solids: 1, faces: 12,
      checks: [{ name: 'size', ok: true, detail: "the catalog's published size" }], ok: true, licence: null,
    };
    const { getByTestId, getByText } = render(
      <GeometryCell c={part} entry={entry} offerUrl="https://example.org/cad.zip" busy={false} onImport={onImport} onSimplified={onSimplified} onDelete={() => undefined} />,
    );
    expect(getByText('Simplified bounding box')).toBeTruthy();
    expect(getByText('maker offers a public file').getAttribute('href')).toBe('https://example.org/cad.zip');
    expect(getByTestId(`geometry-${part.id}`).textContent).toContain("size: the catalog's published size");
    const file = new File(['ISO-10303-21;'], 'part.step', { type: 'application/step' });
    fireEvent.change(getByTestId(`cad-file-${part.id}`), { target: { files: [file] } });
    expect(onImport).toHaveBeenCalledWith(file);
    fireEvent.click(getByTestId(`cad-simple-${part.id}`));
    expect(onSimplified).toHaveBeenCalledTimes(1);
  });

  it('the catalog filters by kind, says what is not published, and puts a part in a slot', () => {
    const onUse = vi.fn();
    const catalog: CatalogList = {
      categories: { gnss: 'GNSS receiver', camera: 'Camera / optical payload' },
      components: [
        { ...pick({}).items[0] },
        { id: 'cam', category: 'camera', manufacturer: 'M', product: 'Cam', mass_kg: null, dims_mm: null, power_w: { typical: null, peak: null }, price: { value: null, currency: null, kind: 'quote', note: '' }, cad: 'unknown' },
      ],
      refs: {},
    };
    const { getByTestId, queryByTestId } = render(
      <CatalogSection catalog={catalog} busy={false} slots={[{ id: 'payload', label: 'Payload', categories: ['camera'], place: 'internal' }]} onUse={onUse} />,
    );
    expect(getByTestId('part-cam').textContent).toContain('not published');
    expect(getByTestId('part-cam').textContent).toContain('quote required');
    fireEvent.change(getByTestId('catalog-category'), { target: { value: 'camera' } });
    expect(queryByTestId('part-spacemanic-celeste')).toBeNull();
    fireEvent.change(getByTestId('use-in-cam'), { target: { value: 'payload' } });
    expect(onUse).toHaveBeenCalledWith('payload', 'cam');
  });
});
