import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import type { DesignProgress } from '../../src/api/types';
import { designRunView, ProgressBar, secondsText } from '../../src/components/DesignProgress';

const run = (over: Partial<DesignProgress>): DesignProgress => ({
  status: 'RUNNING', layout_id: 'L-0001', brackets: [], n_total: 4, n_done: 0, workers: 2, seconds: 0, eta_s: null, ...over,
});

describe('V2 bracket design progress bars', () => {
  it('writes times as seconds, then minutes and seconds', () => {
    expect(secondsText(41.4)).toBe('41 s');
    expect(secondsText(101)).toBe('1 min 41 s');
    expect(secondsText(null)).toBe('—');
  });

  it('moves the last update on to now: time so far, time left and how full the bar is', () => {
    const r = run({
      seconds: 50, n_done: 1, eta_s: 60,
      brackets: [
        { k: 0, pid: 'a', kind: 'metal_am', status: 'done', started_s: 0, seconds: 40, solid: true, passed: true, mass_g: 13 },
        { k: 1, pid: 'b', kind: 'metal_am', status: 'running', started_s: 0 },
        { k: 2, pid: 'c', kind: 'clamp', status: 'running', started_s: 40 },
        { k: 3, pid: 'd', kind: 'cradle', status: 'queued' },
      ],
    });
    const at = '2026-10-24T06:00:00.000Z';
    const v = designRunView(r, at, Date.parse(at) + 10_000)!;   // 10 s after the update arrived
    expect(v.active).toBe(true);
    expect(v.elapsed).toBeCloseTo(60);
    expect(v.eta).toBeCloseTo(50);
    expect(v.mean).toBe(40);
    // 1 done + b at most 90 % of the mean + c 20 s of 40 s, of 4 brackets
    expect(v.fraction).toBeCloseTo((1 + 0.9 + 0.5) / 4);
  });

  it('a finished run is a full bar with no time left; before any bracket is done there is no estimate', () => {
    const done = designRunView(run({ status: 'DONE', seconds: 101, n_done: 4, eta_s: 0 }), undefined, 0)!;
    expect([done.active, done.fraction, done.eta, done.elapsed]).toEqual([false, 1, 0, 101]);
    const early = designRunView(run({ seconds: 5, brackets: [{ k: 0, pid: 'a', kind: 'metal_am', status: 'running', started_s: 0 }] }), undefined, 0)!;
    expect(early.eta).toBeNull();
    expect(early.fraction).toBe(0);
    expect(designRunView(null, undefined, 0)).toBeNull();
  });

  it('the bar is an accessible progress bar, striped while running', () => {
    const { getByRole } = render(<ProgressBar value={0.42} running label="Bracket design run" />);
    const bar = getByRole('progressbar', { name: 'Bracket design run' });
    expect(bar.getAttribute('aria-valuenow')).toBe('42');
    expect(bar.className).toContain('running');
    expect((bar.firstElementChild as HTMLElement).style.width).toBe('42%');
  });
});
