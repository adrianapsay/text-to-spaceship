import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { SweepStrip, sweepBands, switchPoints, SelectorHeatmap, normaliseMap } from '../../src/components/SelectorViews';
import { mockSweep, partStats, mockSelect } from '../../src/mock/content';
import { loadFixtures } from './helpers';

describe('selector sweep rendering (Addendum 3.2 c)', () => {
  const values = Array.from({ length: 101 }, (_, i) => i);
  const choices = values.map((v) => (v < 30 ? 'hybrid_box' : v < 71 ? 'hybrid_box_com' : 'hybrid_voxel'));

  it('run-length encodes choices into bands with switch points', () => {
    const bands = sweepBands(values, choices);
    expect(bands).toEqual([
      { id: 'hybrid_box', start: 0, end: 29 },
      { id: 'hybrid_box_com', start: 30, end: 70 },
      { id: 'hybrid_voxel', start: 71, end: 100 },
    ]);
    expect(switchPoints(bands)).toEqual([30, 71]);
    expect(sweepBands(values, values.map(() => 'a'))).toHaveLength(1);
  });

  it('draws one coloured band per run, a line per switch point and marks the current value', () => {
    const sweep = { slider: 'space', values, choices, legend: { hybrid_box: 'Hybrid box', hybrid_box_com: 'Hybrid box + COM', hybrid_voxel: 'Hybrid voxel' } };
    const { container, getByRole } = render(<SweepStrip sweep={sweep} label="Use Space Efficiently" current={42} allIds={Object.keys(sweep.legend)} />);
    const rects = container.querySelectorAll('rect[data-band]');
    expect(rects).toHaveLength(3);
    expect([...rects].map((r) => r.getAttribute('data-band'))).toEqual(['hybrid_box', 'hybrid_box_com', 'hybrid_voxel']);
    const fills = new Set([...rects].map((r) => r.getAttribute('fill')));
    expect(fills.size).toBe(3);
    expect(container.querySelectorAll('line[data-switch]')).toHaveLength(2);
    expect(container.querySelector('path[data-current="42"]')).not.toBeNull();
    const img = getByRole('img');
    expect(img.getAttribute('aria-label')).toContain('Switch points at 30, 71');
    expect(img.getAttribute('aria-label')).toContain('Current value 42');
    expect(container.textContent).toContain('Hybrid box + COM 30–70');
  });

  it('the mock sweep is deterministic and consistent with the rule at every point', () => {
    const fx = loadFixtures();
    const stats = partStats(fx.project.parts);
    const s1 = mockSweep(fx.project.settings, stats, 'balance');
    const s2 = mockSweep(fx.project.settings, stats, 'balance');
    expect(s1.choices).toEqual(s2.choices);
    expect(s1.values).toHaveLength(101);
    for (const v of [0, 37, 100]) expect(s1.choices[v]).toBe(mockSelect({ ...fx.project.settings, sliders: { ...fx.project.settings.sliders, balance: v } }, stats).id);
  });

  it('renders the 2-slider heat map grid with the current point', () => {
    const grid = Array.from({ length: 5 }, (_, j) => Array.from({ length: 5 }, (_, i) => (i + j > 4 ? 'b' : 'a')));
    const map = normaliseMap(grid, 'space', 'balance')!;
    const { container } = render(<SelectorHeatmap map={map} xLabel="space" yLabel="balance" xVal={25} yVal={25} allIds={['a', 'b']} legend={{ a: 'A', b: 'B' }} />);
    expect(container.querySelectorAll('rect').length).toBe(25 + 1);
    expect(container.querySelector('circle')).not.toBeNull();
  });
});
