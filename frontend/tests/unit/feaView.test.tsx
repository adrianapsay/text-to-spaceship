import { describe, expect, it } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import * as THREE from 'three';
import type { BracketDesign, FeaField, Layout } from '../../src/api/types';
import { BLUE_RAMP, CRITICAL, checkBars, fieldValueText, rampRgb, rampSteps, scaleFor, vertexColors } from '../../src/lib/feaColors';
import { FeaLegend, UtilisationChart, governingField } from '../../src/components/FeaView';
import { designedRows } from '../../src/tabs/Components';

const util: FeaField = { id: 'util_body', label: 'Utilisation', unit: '', kind: 'utilisation', case: null, axis: null, max: 0.6, max_all: 0.7 };
const stress: FeaField = { id: 'vm_static_x', label: 'von Mises, static x', unit: 'MPa', kind: 'stress', case: 'static', axis: 'x', max: 40, max_all: 50 };
const hex = (c: [number, number, number]) => '#' + c.map((x) => Math.round(x * 255).toString(16).padStart(2, '0')).join('');

describe('FEA colour maps', () => {
  it('one blue ramp, light to dark; on the dark 3D background low values are dark and high ones light', () => {
    expect(hex(rampRgb(0, false))).toBe(BLUE_RAMP[0]);
    expect(hex(rampRgb(1, false))).toBe(BLUE_RAMP[BLUE_RAMP.length - 1]);
    expect(hex(rampRgb(0, true))).toBe(BLUE_RAMP[BLUE_RAMP.length - 1]);
    expect(hex(rampRgb(1, true))).toBe(BLUE_RAMP[0]);
    expect(rampSteps(true)[0]).toBe('#0d366b');
    expect(hex(rampRgb(-3, true))).toBe(hex(rampRgb(0, true))); // clamped
  });

  it('utilisation is scaled 0…1 and a value of 1 or more (zero or negative margin) takes the critical colour', () => {
    expect(scaleFor(util)).toEqual({ min: 0, max: 1, threshold: 1 });
    expect(scaleFor(stress)).toEqual({ min: 0, max: 50, threshold: null }); // the top of the legend = the margins' stress
    const c = vertexColors([0.2, 1.0, 1.4], scaleFor(util), true);
    const crit = new THREE.Color().setStyle(CRITICAL, THREE.SRGBColorSpace);
    const isCrit = (i: number) => [0, 1, 2].every((k) => Math.abs(c[3 * i + k] - [crit.r, crit.g, crit.b][k]) < 1e-6);
    expect([isCrit(0), isCrit(1), isCrit(2)]).toEqual([false, true, true]);
    expect(fieldValueText(12.345, stress)).toBe('12.3 MPa');
    expect(fieldValueText(0, stress)).toBe('0 MPa');
    expect(fieldValueText(0.0004, stress)).toBe('4.0e-4 MPa');
    expect(fieldValueText(0.456, util)).toBe('0.46');
  });

  it('the legend names the failing colour with an icon and a label', () => {
    const a = render(<FeaLegend field={util} />).container.textContent ?? '';
    expect(a).toContain('⚠ ≥ 1.00: fails (negative margin)');
    const b = render(<FeaLegend field={stress} />).container.textContent ?? '';
    expect(b).not.toContain('fails');
    expect(b).toContain('50.0 MPa (largest, as in the margins)');
  });
});

const design = (over: Partial<BracketDesign> = {}): BracketDesign => ({
  pid: 'p1', generator: 'pytopo3d SIMP', mass_kg: 0.02, cost_rel: 3, label: '', passed: true, reason: '', sigma_mpa: 40, ms_yield: 0.4, ms_ult: 0.9, f1_hz: 900,
  checks: [
    { case: 'static', axis: 'x', sigma_mpa: 20, factor_yield: 1.25, factor_ult: 1.4, ms_yield: 3, ms_ult: 4, gates: true },
    { case: 'random limit', axis: 'y', sigma_mpa: 60, factor_yield: 1.6, factor_ult: 1.8, ms_yield: 0.25, ms_ult: 0.5, gates: true },
    { case: 'shock limit (ESTIMATE)', axis: 'z', sigma_mpa: 300, factor_yield: 1.25, factor_ult: 1.4, ms_yield: -0.2, ms_ult: -0.1, gates: false },
  ],
  bolt_checks: [{ case: 'static', axis: 'z', check: 'bolt tension yield', ms: 1, bolt: 0, gates: true }],
  ...over,
});

describe('utilisation per check', () => {
  it('opens on the stress of the body check with the smallest margin (estimates and bolts aside)', () => {
    expect(governingField(design())).toBe('vm_random_limit_y');
    expect(governingField({ checks: [] })).toBe('util_body');
  });

  it('turns every margin into 1 / (1 + MS), largest first', () => {
    const bars = checkBars(design().checks, design().bolt_checks);
    expect(bars.map((b) => b.label)).toEqual(['shock limit (ESTIMATE), z', 'random limit, y', 'bolts: static, z', 'static, x']);
    expect(bars[1].u).toBeCloseTo(1 / 1.25);
    expect(bars[2].u).toBeCloseTo(0.5);
    expect(bars[0].gates).toBe(false);
  });

  it('labels only the largest bar and failures; an estimate is marked and never "fails"', () => {
    const { getByTestId, getAllByRole } = render(<UtilisationChart design={design()} />);
    const text = getByTestId('utilisation-chart').textContent ?? '';
    expect(text).toContain('(estimate)');
    expect(text).not.toContain('fails');
    const rows = getAllByRole('generic').filter((e) => e.className.includes('ubar-row') && !e.className.includes('axis'));
    expect(rows).toHaveLength(4);
    fireEvent.mouseEnter(rows[1]); // hover shows the detail of a bar
    expect(getByTestId('utilisation-chart').textContent).toContain('MS yield +0.25');
    const failing = design({ checks: [{ case: 'static', axis: 'x', sigma_mpa: 300, factor_yield: 1.25, factor_ult: 1.4, ms_yield: -0.2, ms_ult: -0.1, gates: true }], bolt_checks: [] });
    expect(render(<UtilisationChart design={failing} />).container.textContent).toContain('✗ 1.25 fails');
  });
});

describe('designed brackets in the Components tab', () => {
  it('lists the metal-AM, cradle and clamp brackets with their designs and mesh URLs', () => {
    const layout = {
      id: 'L-5',
      stage2: {
        brackets: [
          { pid: 'p1', kind: 'metal_am', target: '+x wall' },
          { pid: 'p2', kind: 'direct', target: '-y wall' },
          { pid: 'p3', kind: 'cradle', target: '-x wall' },
        ],
        bracket_designs: { p1: design(), p3: { ...design(), pid: 'p3', mass_kg: null as unknown as number } },
      },
      extra_items: [
        { id: 'L-5-br0', mesh_url: '/api/items/L-5-br0/mesh?v=d1' },
        { id: 'L-5-br2', mesh_url: '/api/items/L-5-br2/mesh' },
      ],
    } as unknown as Layout;
    const rows = designedRows(layout);
    expect(rows.map((r) => [r.itemId, r.pid, r.meshUrl, !!r.design])).toEqual([
      ['L-5-br0', 'p1', '/api/items/L-5-br0/mesh?v=d1', true],
      ['L-5-br2', 'p3', '/api/items/L-5-br2/mesh', false], // a failed design (no solid) counts as not designed
    ]);
    expect(designedRows(null)).toEqual([]);
  });
});
