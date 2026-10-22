import { describe, expect, it } from 'vitest';
import { DASH, fmt, fmtColumn, fmtDelta, fmtVec, MINUS, NNBSP } from '../../src/lib/fmt';

describe('fmt (T-UI1 number formatting)', () => {
  it('lengths to 0.1 mm with a narrow no-break space before the unit', () => {
    expect(fmt(214.04, 'mm')).toBe(`214.0${NNBSP}mm`);
    expect(fmt(340.5, 'mm')).toBe(`340.5${NNBSP}mm`);
  });
  it('clearances to 0.01 mm', () => {
    expect(fmt(1.6049, 'clearance')).toBe(`1.60${NNBSP}mm`);
    expect(fmt(2.2, 'clearance')).toBe(`2.20${NNBSP}mm`);
  });
  it('mass to 0.001 kg', () => {
    expect(fmt(2.91604, 'kg')).toBe(`2.916${NNBSP}kg`);
    expect(fmt(0.38016, 'kg')).toBe(`0.380${NNBSP}kg`);
  });
  it('inertia with 3 significant figures and a proper minus in the exponent', () => {
    expect(fmt(0.0103, 'kgm2')).toBe(`1.03e${MINUS}2${NNBSP}kg·m²`);
    expect(fmt(2.1808e-4, 'kgm2')).toBe(`2.18e${MINUS}4${NNBSP}kg·m²`);
    expect(fmt(0.009996, 'kgm2')).toBe(`1.00e${MINUS}2${NNBSP}kg·m²`);
    expect(fmt(-1.2e-5, 'kgm2')).toBe(`${MINUS}1.20e${MINUS}5${NNBSP}kg·m²`);
  });
  it('angles to 0.1° and percentages to 0.1 %', () => {
    expect(fmt(1.234, 'deg')).toBe('1.2°');
    expect(fmt(0.317, 'pct')).toBe(`31.7${NNBSP}%`);
    expect(fmt(31.66, 'pct100')).toBe(`31.7${NNBSP}%`);
  });
  it('uses U+2212 for negative numbers and never shows −0.0', () => {
    expect(fmt(-55.12, 'mm')).toBe(`${MINUS}55.1${NNBSP}mm`);
    expect(fmt(-0.01, 'mm')).toBe(`0.0${NNBSP}mm`);
    expect(fmt(-55.12, 'mm')).not.toContain('-');
  });
  it('shows unknown values as an em dash', () => {
    expect(fmt(null, 'mm')).toBe(DASH);
    expect(fmt(undefined, 'kg')).toBe(DASH);
    expect(fmt(Number.NaN, 'kgm2')).toBe(DASH);
    expect(fmt(Number.POSITIVE_INFINITY, 'deg')).toBe(DASH);
    expect(fmtVec(null)).toBe(DASH);
  });
  it('density with thousands separators; unit can be omitted', () => {
    expect(fmt(2700, 'density')).toBe(`2,700${NNBSP}kg/m³`);
    expect(fmt(2700, 'density', { unit: false })).toBe('2,700');
  });
  it('vectors', () => {
    expect(fmtVec([0.4, -0.2, -55.1])).toBe(`(0.4, ${MINUS}0.2, ${MINUS}55.1)${NNBSP}mm`);
  });
  it('shared column exponent for inertia tables', () => {
    const c = fmtColumn([0.0103, 0.00218, 0.000218, null]);
    expect(c.exponent).toBe(-2);
    expect(c.header).toBe(`(10⁻²${NNBSP}kg·m²)`);
    expect(c.cells).toEqual(['1.03', '0.218', '0.0218', DASH]);
  });
  it('signed deltas with the words better / worse', () => {
    expect(fmtDelta(-1.3, 'mm').text).toBe(`${MINUS}1.3${NNBSP}mm better`);
    expect(fmtDelta(2.04, 'mm').text).toBe(`+2.0${NNBSP}mm worse`);
    expect(fmtDelta(0.5, 'clearance', 'higher').verdict).toBe('better');
    expect(fmtDelta(0.01, 'mm').verdict).toBe('unchanged');
    expect(fmtDelta(null, 'mm').text).toBe(DASH);
  });
});
