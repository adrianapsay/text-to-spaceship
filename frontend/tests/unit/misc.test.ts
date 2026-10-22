import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { contrastRatio } from '../../src/lib/colors';
import { layoutIdeaMap, navigate, tabFromName } from '../../src/lib/ideamapLayout';
import type { IdeaMap } from '../../src/api/types';

const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../src/styles/tokens.css'), 'utf8');
function tokens(block: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of block.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)) out[m[1]] = m[2];
  return out;
}

describe('design-token contrast (T-UI11, WCAG 2.2 AA)', () => {
  const light = tokens(css.slice(0, css.indexOf('@media')));
  const darkStart = css.indexOf(":root[data-theme='dark']");
  const dark = tokens(css.slice(darkStart));
  for (const [name, t] of [
    ['light', light],
    ['dark', dark],
  ] as const) {
    it(`${name}: text ≥ 4.5:1 on panels and app background; controls / accent ≥ 3:1`, () => {
      for (const bg of ['bg-panel', 'bg-app', 'bg-sunken']) {
        expect(contrastRatio(t.text, t[bg])).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(t['text-muted'], t[bg])).toBeGreaterThanOrEqual(4.5);
        for (const k of ['ok', 'warn', 'err', 'accent']) expect(contrastRatio(t[k], t[bg])).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(t.border, t[bg])).toBeGreaterThanOrEqual(3);
      }
      expect(contrastRatio(t['accent-text'], t.accent)).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(t['mock-text'], t['mock-bg'])).toBeGreaterThanOrEqual(4.5);
    });
  }
  it('viewport labels and subsystem colours are readable on the dark viewport', () => {
    expect(contrastRatio(light['vp-label'], light.viewport)).toBeGreaterThanOrEqual(4.5);
    for (const k of ['c-power', 'c-electronics', 'c-adcs', 'c-tanks', 'c-payload', 'c-structure', 'c-unknown', 'c-am']) expect(contrastRatio(light[k], light.viewport)).toBeGreaterThanOrEqual(3);
  });
});

describe('idea map layout', () => {
  const map: IdeaMap = {
    nodes: [
      { id: 'layout', label: 'L-1', kind: 'layout', tab: 'overview', detail: null },
      { id: 'g1', label: 'Box-like', kind: 'parts', tab: 'components', detail: null },
      { id: 'x1', label: 'Box proxy', kind: 'proxy', tab: 'Components', detail: null },
      { id: 'a1', label: 'Hybrid', kind: 'algorithm', tab: 'Algorithm Comparison', detail: null },
      { id: 'w', label: 'Weights', kind: 'weights', tab: 'optimisation', detail: null },
      { id: 'sel', label: 'Chosen', kind: 'selected', tab: 'explain', detail: null },
    ],
    edges: [
      { from: 'g1', to: 'x1', label: 'volume share 31 %' },
      { from: 'x1', to: 'a1', label: null },
      { from: 'a1', to: 'sel', label: null },
      { from: 'w', to: 'sel', label: 'weight 0.70' },
      { from: 'sel', to: 'layout', label: 'L = 214.0 mm' },
      { from: 'layout', to: 'g1', label: 'cycle edge is ignored for layering' },
    ],
  };
  it('is deterministic and layered by longest path', () => {
    const a = layoutIdeaMap(map);
    const b = layoutIdeaMap({ nodes: [...map.nodes].reverse(), edges: [...map.edges].reverse() });
    expect(a.nodes.map((n) => [n.id, n.x, n.y])).toEqual(b.nodes.map((n) => [n.id, n.x, n.y]).sort((p, q) => a.nodes.findIndex((n) => n.id === p[0]) - a.nodes.findIndex((n) => n.id === q[0])));
    const col = Object.fromEntries(a.nodes.map((n) => [n.id, n.col]));
    expect(col.g1).toBeLessThan(col.x1);
    expect(col.x1).toBeLessThan(col.a1);
    expect(col.a1).toBeLessThan(col.sel);
    expect(col.sel).toBeLessThan(col.layout);
  });
  it('keyboard navigation follows links and columns', () => {
    const a = layoutIdeaMap(map);
    expect(navigate(a, 'g1', 'ArrowRight')).toBe('x1');
    expect(navigate(a, 'sel', 'ArrowLeft')).toBe('a1');
    expect(navigate(a, 'sel', 'ArrowRight')).toBe('layout');
  });
  it('maps backend tab names to tabs', () => {
    expect(tabFromName('Algorithm Comparison')).toBe('comparison');
    expect(tabFromName('optimisation')).toBe('optimization');
    expect(tabFromName('nope')).toBeNull();
  });
});
