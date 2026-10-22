import { afterEach, describe, expect, it, vi } from 'vitest';
import { backoffDelay, Throttle } from '../../src/api/ws';
import { createAppStore } from '../../src/store/store';
import { Session } from '../../src/api/session';
import { boxTriangles, buildBinaryStl } from '../../src/mock/stl';
import { makeMockBackend, waitFor } from './helpers';

afterEach(() => vi.useRealTimers());

describe('reconnection backoff', () => {
  it('doubles from 250 ms and caps at 5 s', () => {
    expect([0, 1, 2, 3, 4, 5, 6, 10].map((a) => backoffDelay(a))).toEqual([250, 500, 1000, 2000, 4000, 5000, 5000, 5000]);
  });
});

describe('Throttle (≤ 20 Hz while dragging, commit on release)', () => {
  it('sends leading + trailing at most every 50 ms and flushes the final value with commit', () => {
    vi.useFakeTimers({ now: 0 });
    const out: [number, boolean, number][] = [];
    const t = new Throttle<number>((v, c) => out.push([v, c, Date.now()]), 50, () => Date.now());
    for (let i = 1; i <= 30; i++) {
      t.push(i); // a pointer event every 5 ms for 150 ms
      vi.advanceTimersByTime(5);
    }
    vi.advanceTimersByTime(50);
    t.flush(99);
    const nonCommit = out.filter((o) => !o[1]);
    expect(nonCommit.length).toBeGreaterThanOrEqual(3);
    expect(nonCommit.length).toBeLessThanOrEqual(Math.ceil(150 / 50) + 1);
    for (let i = 1; i < nonCommit.length; i++) expect(nonCommit[i][2] - nonCommit[i - 1][2]).toBeGreaterThanOrEqual(50);
    // the trailing send carries the latest value
    expect(nonCommit[nonCommit.length - 1][0]).toBe(30);
    expect(out[out.length - 1].slice(0, 2)).toEqual([99, true]);
  });
});

describe('WebSocket client against the in-browser mock backend (T-UI7)', () => {
  it('hello → snapshot; reconnects with backoff after a drop and re-syncs', async () => {
    const backend = makeMockBackend();
    const store = createAppStore();
    const s = new Session(store, backend.transport());
    await s.start();
    await waitFor(() => store.getState().conn.synced && !!store.getState().solver.best);
    expect(store.getState().conn.wsState).toBe('open');
    expect(store.getState().dataset.partOrder).toHaveLength(19);
    expect(store.getState().solver.best!.status).toBe('VALIDATED');
    backend.dropConnections();
    await waitFor(() => store.getState().conn.wsState === 'reconnecting');
    expect(store.getState().conn.nextRetryMs).toBe(250);
    await waitFor(() => store.getState().conn.wsState === 'open' && store.getState().conn.synced, 3000);
    s.stop();
  });

  it('a slider edit is acknowledged; scores show only once applied_client_seq catches up', async () => {
    const backend = makeMockBackend();
    const store = createAppStore();
    const s = new Session(store, backend.transport());
    await s.start();
    await waitFor(() => store.getState().conn.synced);
    s.setSlider('balance', 80, true);
    const sent = store.getState().conn.lastClientSeqSent;
    expect(sent).toBeGreaterThan(0);
    expect(store.getState().conn.appliedClientSeq).toBeLessThan(sent);
    await waitFor(() => store.getState().conn.appliedClientSeq >= sent);
    expect(store.getState().goals.pendingSeq).toBeNull();
    s.stop();
  });

  it('mass edit → metrics.update moves the COM; part record becomes USER_MASS', async () => {
    const backend = makeMockBackend();
    const store = createAppStore();
    const s = new Session(store, backend.transport());
    await s.start();
    await waitFor(() => !!store.getState().solver.best?.metrics);
    const battery = Object.values(store.getState().dataset.parts).find((p) => p.name === 'battery_pack')!;
    const before = store.getState().solver.best!.metrics!.mass_kg!;
    s.setMass(battery.id, 1.38016, true);
    await waitFor(() => Math.abs((store.getState().solver.best!.metrics!.mass_kg ?? 0) - (before + 1)) < 1e-9);
    await waitFor(() => store.getState().dataset.parts[battery.id].mass_source === 'USER_MASS');
    expect(store.getState().physical.massEdits[battery.id]).toBeUndefined();
    s.stop();
  });

  it('add a new STL → NEEDS_UNITS → confirm mm → VALID, parts_rev increases, old layout no longer current, detail study runs', async () => {
    const backend = makeMockBackend();
    const store = createAppStore();
    const s = new Session(store, backend.transport());
    await s.start();
    await waitFor(() => !!store.getState().solver.best);
    const partsRev0 = store.getState().conn.newest.parts_rev;
    const file = new File([buildBinaryStl(boxTriangles([0, 0, 0], [30, 20, 10]))], 'unseen_box.stl');
    const [p] = await s.addFiles([file]);
    expect(p.status).toBe('NEEDS_UNITS');
    expect(store.getState().dataset.unitsQueue).toContain(p.id);
    const confirmed = await s.confirmUnits(p.id, 'mm');
    expect(confirmed!.status).toBe('VALID');
    expect(confirmed!.mass_kg).toBeCloseTo(30 * 20 * 10 * 1e-9 * 2700, 9);
    await waitFor(() => store.getState().conn.newest.parts_rev > partsRev0);
    await waitFor(() => !!store.getState().solver.fidelityRuns[p.id]);
    await waitFor(() => store.getState().solver.fidelityRuns[p.id].status === 'DONE');
    const best = store.getState().solver.best!;
    expect(best.parts_rev).toBeLessThan(store.getState().conn.newest.parts_rev);
    expect(best.poses.some((q) => q.part_id === p.id)).toBe(false);
    // re-run includes the new part
    await s.run('rerun');
    await waitFor(() => !!store.getState().solver.best?.poses.some((q) => q.part_id === p.id), 5000);
    expect(store.getState().solver.best!.parts_rev).toBe(store.getState().conn.newest.parts_rev);
    s.stop();
  });

  it('an open-mesh file is explained, not fatal', async () => {
    const backend = makeMockBackend();
    const store = createAppStore();
    const s = new Session(store, backend.transport());
    await s.start();
    await waitFor(() => store.getState().conn.synced);
    const tris = boxTriangles([0, 0, 0], [10, 10, 10]).slice(0, 10);
    const [p] = await s.addFiles([new File([buildBinaryStl(tris)], 'open_box.stl')]);
    const r = await s.confirmUnits(p.id, 'mm');
    expect(r!.status).toBe('WITHHELD');
    expect(r!.status_detail).toMatch(/open mesh — 1 hole/);
    s.stop();
  });
});
