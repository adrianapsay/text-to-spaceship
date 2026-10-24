import { describe, expect, it } from 'vitest';
import type { Sliders } from '../../src/api/types';
import { comFirstOn } from '../../src/store/presets';

const base: Sliders = {
  space: 87,
  balance: 29,
  inertia: 10,
  feasibility: 25,
  mass_symmetry: 50,
  cable: 0,
  cost: 0,
  speed_quality: 50,
  bracket_budget: 100,
  optional_parts: 75,
};

describe('centre-of-mass-first mode (backend stage2_model.com_first_mode)', () => {
  it('is on only in Stage 2 with Balance and the Bracket budget both at 100', () => {
    expect(comFirstOn({ ...base, balance: 100 }, 2)).toBe(true);
    expect(comFirstOn(base, 2)).toBe(false);
    expect(comFirstOn({ ...base, balance: 100, bracket_budget: 99 }, 2)).toBe(false);
    expect(comFirstOn({ ...base, balance: 100 }, 1)).toBe(false);
  });
});
