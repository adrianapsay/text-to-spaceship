import { afterEach, describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import type { Envelope, ProgressPayload } from '../../src/api/types';
import { initialConn, initialSolver, reduceEnvelope } from '../../src/api/protocol';
import { Session } from '../../src/api/session';
import { StatusBar } from '../../src/components/Shell';
import { minutesText, runTime } from '../../src/lib/runTime';
import { appStore, createAppStore, initialState } from '../../src/store/store';
import { makeMockBackend, waitFor } from './helpers';

const NOTE = 'Search-based and provisional, from one 7.5 h run at 3U 54 % on this PC; to be replaced by a measured distribution.';
const progress = (over: Partial<ProgressPayload> = {}): ProgressPayload => ({
  status: 'SEARCHING', evaluations: 1234, best_g: 0.4, elapsed_s: 12 * 60 + 41, recommended_min_s: 5930, recommended_note: NOTE, ...over,
});

afterEach(() => appStore.setState(initialState()));

describe('V2: the search runs until Pause — running time and recommended minimum', () => {
  it('writes the running time in whole minutes and the recommendation rounded up', () => {
    expect(minutesText(41)).toBe('less than 1 min');
    expect(minutesText(60)).toBe('1 min');
    expect(minutesText(452 * 60 + 59)).toBe('452 min');
    const rt = runTime(progress(), 'SEARCHING')!;
    expect(rt.text).toBe('recommended minimum 99 min · running 12 min');        // 5930 s = 98.8 min
    expect(rt.title).toContain('Search-based and provisional');
    expect(rt.title).toContain('until you press Pause');
    expect(runTime(progress(), 'PAUSED')!.text).toBe('recommended minimum 99 min · running 12 min (paused)');
  });

  it('shows only the running time where nothing was measured (6U, 12U, mock) and nothing without progress', () => {
    const none = runTime(progress({ recommended_min_s: null, recommended_note: 'No recommended minimum has been measured for 6U yet.' }), 'SEARCHING')!;
    expect(none.text).toBe('running 12 min');
    expect(none.title).toBe('No recommended minimum has been measured for 6U yet.');
    expect(runTime(null)).toBeNull();
    expect(runTime(progress({ elapsed_s: null }))).toBeNull();
    expect(runTime(progress(), 'IDLE')).toBeNull();                         // no search yet, or no packable parts
  });

  it('the status bar shows it with the tooltip', () => {
    appStore.setState({ solver: { ...initialSolver(), runStatus: 'SEARCHING', progress: progress() } });
    const { getByTestId } = render(<StatusBar />);
    const el = getByTestId('run-time');
    expect(el.textContent).toBe('recommended minimum 99 min · running 12 min');
    expect(el.getAttribute('title')).toContain('provisional');
    expect(getByTestId('status-bar').textContent).toContain('Optimiser: SEARCHING');
  });

  it('a snapshot brings the running time (no progress messages while paused); one without keeps it', () => {
    const base = { v: 1, epoch: 1, parts_rev: 0, constraint_rev: 0, mass_rev: 0, weights_rev: 0, applied_client_seq: 0, ts: '' };
    const snap = (p: ProgressPayload | undefined, seq: number) =>
      ({ ...base, type: 'state.snapshot', seq, payload: { project: null, best_validated: null, candidate: null, run_status: 'PAUSED', selector: null, progress: p } }) as unknown as Envelope;
    let r = reduceEnvelope(initialConn(), initialSolver(), snap(progress({ status: 'PAUSED', elapsed_s: 600 }), 1));
    expect(r.solver.progress!.elapsed_s).toBe(600);
    r = reduceEnvelope(r.conn, r.solver, snap(undefined, 2));
    expect(r.solver.progress!.elapsed_s).toBe(600);
  });

  it('the mock pauses (never "converges") when its placeholder attempts run out, and reports no recommendation', async () => {
    const backend = makeMockBackend();
    const store = createAppStore();
    const s = new Session(store, backend.transport());
    await s.start();
    await waitFor(() => store.getState().conn.synced);
    await s.run('start');
    await waitFor(() => store.getState().solver.runStatus === 'PAUSED', 5000);
    const sv = store.getState().solver;
    expect(sv.statusDetail).toContain('searches until you press Pause');
    expect(sv.progress!.recommended_min_s).toBeNull();
    expect(sv.progress!.elapsed_s).toBeGreaterThan(0);
    s.stop();
  });
});
