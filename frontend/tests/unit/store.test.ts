import { describe, expect, it } from 'vitest';
import { createAppStore } from '../../src/store/store';
import { Session } from '../../src/api/session';
import type { Envelope } from '../../src/api/types';
import { SOCKET_OPEN, type SocketLike, type Transport } from '../../src/api/transport';
import { loadFixtures, sleep, waitFor } from './helpers';

function loadedStore() {
  const store = createAppStore();
  store.getState().loadProject(loadFixtures().project);
  return store;
}

describe('physical edits vs goal edits use separate store slices (T-UI4)', () => {
  it('goal edits never touch the physical or dataset slices', () => {
    const store = loadedStore();
    const before = store.getState();
    store.getState().setSlider('space', 80);
    store.getState().setPreset('com_priority');
    store.getState().setStage(2);
    const after = store.getState();
    expect(after.physical).toBe(before.physical);
    expect(after.dataset).toBe(before.dataset);
    expect(after.goals).not.toBe(before.goals);
    expect(after.goals.settings!.sliders.balance).toBe(70);
  });

  it('physical edits never touch the goals slice', () => {
    const store = loadedStore();
    const before = store.getState();
    const id = before.dataset.partOrder[0];
    store.getState().setMassEdit(id, 1.234, 7, true);
    store.getState().setLockEdit(id, true, 8);
    const after = store.getState();
    expect(after.goals).toBe(before.goals);
    expect(after.dataset).toBe(before.dataset);
    expect(after.physical.massEdits[id].mass_kg).toBe(1.234);
  });

  it('presets: favoured slider 70, others 10; Balanced equal; manual change → Custom', () => {
    const store = loadedStore();
    store.getState().setPreset('max_packing');
    expect(store.getState().goals.settings!.sliders).toMatchObject({ space: 70, balance: 10, inertia: 10 });
    expect(store.getState().goals.preset).toBe('max_packing');
    store.getState().setSlider('inertia', 33);
    expect(store.getState().goals.preset).toBe('custom');
    store.getState().setPreset('balanced');
    expect(store.getState().goals.settings!.sliders).toMatchObject({ space: 25, balance: 25, inertia: 25 });
  });
});

/** Capturing fake transport: records every client→server envelope. */
function captureTransport() {
  const sent: Envelope[] = [];
  let sock: (SocketLike & { emit: (e: Partial<Envelope>) => void }) | null = null;
  let serverSeq = 0;
  const t: Transport = {
    mode: 'mock',
    fetch: async () => new Response(JSON.stringify(loadFixtures().project), { headers: { 'content-type': 'application/json' } }),
    openSocket() {
      const s = {
        readyState: 0,
        onopen: null as SocketLike['onopen'],
        onmessage: null as SocketLike['onmessage'],
        onclose: null as SocketLike['onclose'],
        onerror: null as SocketLike['onerror'],
        send(data: string) {
          sent.push(JSON.parse(data) as Envelope);
        },
        close() {
          this.readyState = 3;
        },
        emit(e: Partial<Envelope>) {
          serverSeq++;
          s.onmessage?.({ data: JSON.stringify({ v: 1, epoch: 1, parts_rev: 1, constraint_rev: 1, mass_rev: 1, weights_rev: 1, applied_client_seq: 0, ts: '', seq: serverSeq, ...e }) });
        },
      };
      setTimeout(() => {
        s.readyState = SOCKET_OPEN;
        s.onopen?.({});
      }, 0);
      sock = s;
      return s;
    },
  };
  return { t, sent, sock: () => sock! };
}

describe('session: separate message types and throttled slider edits', () => {
  it('slider drags send edit.settings at ≤ 20 Hz plus a commit; mass edits send edit.part only', async () => {
    const store = createAppStore();
    const cap = captureTransport();
    const s = new Session(store, cap.t);
    await s.start();
    await waitFor(() => cap.sent.some((e) => e.type === 'hello'));
    cap.sock().emit({ type: 'state.snapshot', payload: { project: loadFixtures().project, best_validated: null, candidate: null, run_status: 'IDLE', selector: null } });
    await waitFor(() => store.getState().conn.synced);
    // drag for ~200 ms with an update every 5 ms
    const t0 = performance.now();
    let v = 25;
    while (performance.now() - t0 < 200) {
      s.setSlider('space', ++v % 100, false);
      await sleep(5);
    }
    s.setSlider('space', 60, true);
    await sleep(80);
    const edits = cap.sent.filter((e) => e.type === 'edit.settings');
    const nonCommit = edits.filter((e) => !(e.payload as { commit: boolean }).commit);
    const commits = edits.filter((e) => (e.payload as { commit: boolean }).commit);
    expect(commits).toHaveLength(1);
    expect((commits[0].payload as { settings: { sliders: { space: number } } }).settings.sliders.space).toBe(60);
    // ≤ 20 Hz over ~0.2 s → at most 4–6 sends (leading + trailing), never one per pointer event (~40)
    expect(nonCommit.length).toBeGreaterThanOrEqual(2);
    expect(nonCommit.length).toBeLessThanOrEqual(6);
    const times = nonCommit.map((e) => Date.parse(e.ts));
    for (let i = 1; i < times.length; i++) expect(times[i] - times[i - 1]).toBeGreaterThanOrEqual(40);
    expect(cap.sent.some((e) => e.type === 'edit.part')).toBe(false);
    // scores hidden until the server applies the last client_seq
    expect(store.getState().conn.lastClientSeqSent).toBe((commits[0].payload as { client_seq: number }).client_seq);
    expect(store.getState().conn.appliedClientSeq).toBe(0);

    const pid = store.getState().dataset.partOrder[0];
    const nBefore = cap.sent.length;
    s.setMass(pid, 0.5, true);
    await sleep(10);
    const newMsgs = cap.sent.slice(nBefore);
    expect(newMsgs.map((e) => e.type)).toEqual(['edit.part']);
    expect((newMsgs[0].payload as { part_id: string; patch: { mass_kg: number } }).patch).toEqual({ mass_kg: 0.5 });
    expect(store.getState().physical.massEdits[pid].mass_kg).toBe(0.5);
    s.stop();
  });
});
