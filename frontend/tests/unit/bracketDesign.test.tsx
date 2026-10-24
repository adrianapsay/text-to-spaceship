import { describe, expect, it } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import type { BracketDesign, BracketInfo, DesignOptions } from '../../src/api/types';
import { BracketSettings, feaMinimumText, governingText, MEMBER_STOPS, outdatedText, stopIndex, vfStops } from '../../src/components/BracketDesign';

const options: DesignOptions = {
  environments: [],
  materials: [
    { id: 'AlSi10Mg', name: 'AlSi10Mg', process: 'metal_am', E_mpa: 65000, yield_mpa: 170, ultimate_mpa: 280, density_g_cm3: 2.68, source: '' },
    { id: 'Ti-6Al-4V', name: 'Ti-6Al-4V', process: 'metal_am', E_mpa: 110000, yield_mpa: 860, ultimate_mpa: 930, density_g_cm3: 4.41, source: '' },
    { id: '6061-T6', name: '6061-T6', process: 'machined', E_mpa: 68300, yield_mpa: 240, ultimate_mpa: 290, density_g_cm3: 2.71, source: '' },
  ],
  allowables: 'vendor minimum values',
  machined: '6061-T6',
  vol_frac: { range: [0.02, 0.8], ladder: [0.03, 0.05, 0.08, 0.12, 0.2, 0.3, 0.45] },
  min_member_mm: { range: [1, 12], am_min_wall_mm: 2, generator_sets_member_size: true },
  generator: 'pytopo3d',
  launch_environment: 'gevs',
  bracket_material: 'AlSi10Mg',
};

const am: BracketInfo = {
  name: 'b1', pid: 'p1', kind: 'metal_am', mount_type: 'metal_am', process: 'metal_am', fasteners: 3, gap_mm: 20, target: '+x wall',
  reserve: [0, 0, 0, 20, 30, 30], depth_mm: 20, mass_kg: 0.05, cost_rel: 3, material: 'AlSi10Mg', label: '', exact: false,
};
const cradle: BracketInfo = { ...am, name: 'b2', pid: 'p2', kind: 'cradle', process: 'machined' };

const design = (over: Partial<BracketDesign> = {}): BracketDesign => ({
  pid: 'p1', generator: 'pytopo3d SIMP', mass_kg: 0.02, cost_rel: 3, label: '', passed: true, reason: '', sigma_mpa: 40, ms_yield: 0.4,
  ms_ult: 0.9, f1_hz: 900, environment: 'gevs', environment_name: 'GEVS', material: 'AlSi10Mg', min_vol_frac: 0.08,
  settings: { material: 'AlSi10Mg', vol_frac: 'auto', min_member_mm: 'auto' },
  ladder: [{ vol_frac: 0.03, passed: false }, { vol_frac: 0.05, passed: false }, { vol_frac: 0.08, passed: true, mass_g: 20 }],
  governing: { case: 'random qualification', axis: 'y', check: 'yield', ms: 0.4, part: 'bracket' },
  margins: { static: { ms_yield: 2, ms_ult: 2.5, axis: 'x', gates: true }, 'bolt: static': { ms: 1.2, check: 'bolt tension yield', bolt: 0, axis: 'z', gates: true } },
  member_mm: 3, plate_mm: 1.5, skin_mm: 1.5,
  ...over,
});

describe('WS4 per-bracket design settings', () => {
  it('slider stops: automatic, the automatic run’s ladder and 60 %; stored values land on their stop', () => {
    const s = vfStops(options);
    expect(s).toEqual(['auto', 0.03, 0.05, 0.08, 0.12, 0.2, 0.3, 0.45, 0.6]);
    expect(stopIndex(s, 'auto')).toBe(0);
    expect(stopIndex(s, undefined)).toBe(0);
    expect(stopIndex(s, 0.12)).toBe(4);
    expect(stopIndex(MEMBER_STOPS, 2.6)).toBe(MEMBER_STOPS.indexOf(2.5));
  });

  it('a design for another launch environment or material is outdated', () => {
    expect(outdatedText(am, design(), undefined, 'gevs', 'AlSi10Mg')).toBeNull();
    expect(outdatedText(am, design(), undefined, 'spacex', 'AlSi10Mg', 'SpaceX Rideshare')).toBe('designed for GEVS, not SpaceX Rideshare');
    expect(outdatedText(am, design(), undefined, 'gevs', 'Ti-6Al-4V')).toBe('designed in AlSi10Mg, not Ti-6Al-4V');
    expect(outdatedText(am, design(), { material: 'AlSi10Mg' }, 'gevs', 'Ti-6Al-4V')).toBeNull();   // its own material
    expect(outdatedText(cradle, design({ material: '6061-T6' }), undefined, 'gevs', 'Ti-6Al-4V')).toBeNull();
    expect(outdatedText(am, design({ environment: undefined }), undefined, 'gevs', 'AlSi10Mg')).toContain('before the launch environments');
    expect(outdatedText(am, undefined, undefined, 'gevs', 'AlSi10Mg')).toBeNull();
  });

  it('names the governing check and the FEA minimum', () => {
    expect(governingText(design().governing)).toBe('random qualification, y, yield');
    expect(governingText({ case: 'static', axis: 'x', check: 'tension yield', ms: 1, part: 'bolt' })).toBe('static, x, bolt tension yield');
    const s = vfStops(options);
    expect(feaMinimumText(0.08, s, false)).toBe('FEA minimum 8 %: the lightest material use that passed every check');
    expect(feaMinimumText(0.03, s, true)).toContain('3 % or less');
  });

  it('a metal-AM bracket: material, material used with its FEA minimum, member thickness with the AM minimum', () => {
    const { getByTestId, getByLabelText, queryByText, getByText } = render(
      <BracketSettings layoutId="L-1" b={am} d={design()} options={options} settings={null} running={false} />,
    );
    const mat = getByTestId('material-p1') as HTMLSelectElement;
    expect([...mat.options].map((o) => o.value)).toEqual(['', 'AlSi10Mg', 'Ti-6Al-4V']);   // AM materials only
    expect(getByText(/FEA minimum 8 %/)).toBeTruthy();
    expect(getByText(/AM minimum wall 2 mm/)).toBeTruthy();
    expect(queryByText(/Below the FEA minimum/)).toBeNull();
    fireEvent.change(getByLabelText('Material used (share of the reserved box)'), { target: { value: '2' } });   // 5 %
    expect(getByText(/Below the FEA minimum/)).toBeTruthy();
    fireEvent.change(getByLabelText('Minimum member thickness'), { target: { value: '1' } });   // 1.5 mm
    expect(getByText(/Thinner than the 2 mm AM minimum wall/)).toBeTruthy();
    expect(getByTestId('margins-table').textContent).toContain('bolt tension yield');
    expect((getByTestId('redesign-p1') as HTMLButtonElement).disabled).toBe(false);
  });

  it('a cradle is machined: no material choice and no material-used slider; nothing can start during a run', () => {
    const { queryByTestId, getByText, getByTestId } = render(
      <BracketSettings layoutId="L-1" b={cradle} d={undefined} options={options} settings={null} running />,
    );
    expect(queryByTestId('material-p2')).toBeNull();
    expect(queryByTestId('vf-p2')).toBeNull();
    expect(getByText(/machined 6061-T6/)).toBeTruthy();
    expect((getByTestId('redesign-p2') as HTMLButtonElement).disabled).toBe(true);
  });
});
