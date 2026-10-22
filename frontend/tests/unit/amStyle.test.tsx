import { describe, expect, it } from 'vitest';
import { render, within } from '@testing-library/react';
import * as THREE from 'three';
import { EXTRA_ITEM_STYLES, extraItemStyle, isMetalAm, SUBSYSTEM_COLORS } from '../../src/lib/colors';
import { createHatchMaterial, extraItemMaterial } from '../../src/components/viewport/materials';
import { groupHardware, HardwareTable } from '../../src/tabs/Manufacturable';
import type { MfgItem } from '../../src/api/types';

describe('metal-AM brackets are visually distinct (Addendum 1.5)', () => {
  const am = extraItemStyle('metal_am');
  const others = Object.entries(EXTRA_ITEM_STYLES).filter(([k]) => k !== 'metal_am');

  it('has its own colour, a hatch pattern and an AM badge that no other process has', () => {
    expect(am.hatch).toBe(true);
    expect(am.badge).toBe('AM');
    expect(am.section).toBe('METAL 3D-PRINTED');
    for (const [, st] of others) {
      expect(st.color.toLowerCase()).not.toBe(am.color.toLowerCase());
      expect(st.hatch).toBe(false);
      expect(st.badge).toBeNull();
      expect(st.section).toBe('OTHER HARDWARE');
    }
    for (const c of Object.values(SUBSYSTEM_COLORS)) expect(c.toLowerCase()).not.toBe(am.color.toLowerCase());
    expect(isMetalAm('metal_am')).toBe(true);
    expect(isMetalAm('sheet')).toBe(false);
    expect(isMetalAm('unknown_process')).toBe(false);
  });

  it('the 3D material for AM carries the diagonal hatch shader; others do not', () => {
    const m = extraItemMaterial('metal_am');
    expect(m.userData.hatch).toBe(true);
    expect(m.customProgramCacheKey()).toBe('hatch-diagonal-v1');
    const shader = { fragmentShader: 'void main(){\n#include <dithering_fragment>\n}', vertexShader: '', uniforms: {} };
    m.onBeforeCompile(shader as unknown as THREE.WebGLProgramParametersWithUniforms, undefined as unknown as THREE.WebGLRenderer);
    expect(shader.fragmentShader).toContain('hatchBand');
    expect(new THREE.Color(m.color).getHexString()).toBe(am.color.slice(1).toLowerCase());
    const sheet = extraItemMaterial('sheet');
    expect(sheet.userData.hatch).toBeUndefined();
    expect(createHatchMaterial('#ffffff').userData.hatch).toBe(true);
  });

  it('the hardware list puts metal 3D-printed brackets in their own section', () => {
    const items: MfgItem[] = [
      { id: 'b1', for_part: 'p01', part_name: 'battery_pack', mount_type: 'direct', process: 'direct', material: 'A2-70', mass_kg: 0.004, cost_rel: 0.4 },
      { id: 'b2', for_part: 'p17', part_name: 'magnetometer_ring_torus', mount_type: 'conformal saddle', process: 'metal_am', material: 'AlSi10Mg', mass_kg: 0.012, cost_rel: 14.2 },
      { id: 'b3', for_part: 'p05', part_name: 'reaction_wheel', mount_type: 'L bracket', process: 'sheet', material: 'Al 5052', mass_kg: 0.008, cost_rel: 3.5 },
    ];
    const groups = groupHardware(items);
    expect(groups.map((g) => g.section)).toEqual(['METAL 3D-PRINTED', 'OTHER HARDWARE']);
    expect(groups[0].items.map((i) => i.id)).toEqual(['b2']);
    const { getByTestId } = render(<HardwareTable items={items} />);
    const table = getByTestId('hardware-list');
    const amBody = table.querySelector('tbody[data-section="METAL 3D-PRINTED"]')!;
    expect(within(amBody as HTMLElement).getByText('magnetometer_ring_torus')).toBeTruthy();
    expect(within(amBody as HTMLElement).queryByText('battery_pack')).toBeNull();
    expect(amBody.querySelector('.swatch.hatch')).not.toBeNull();
    expect(within(amBody as HTMLElement).getAllByText('AM').length).toBeGreaterThan(0);
  });
});
