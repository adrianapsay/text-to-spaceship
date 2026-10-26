import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import type { Envelope, Layout, LayoutStatus, Revs } from '../../src/api/types';
import {
  connOnNewConnection,
  displayKind,
  initialConn,
  initialSolver,
  isCurrent,
  markClientSeqSent,
  reduceEnvelope,
  renderPlan,
  scoresVisible,
  shownLayout,
  type ConnProto,
  type SolverState,
} from '../../src/api/protocol';

// ------------------------------------------------------------------ a tiny simulated server
type Ev =
  | { k: 'validated'; lagC: number; lagP: number; status: LayoutStatus }
  | { k: 'candidate'; lagC: number; lagP: number }
  | { k: 'stale' }
  | { k: 'bumpParts' }
  | { k: 'bumpConstraint' }
  | { k: 'send' }
  | { k: 'ack'; behind: number }
  | { k: 'dup' }
  | { k: 'oldEpoch' }
  | { k: 'metrics' }
  | { k: 'snapshot' }
  | { k: 'reconnect' };

const evArb: fc.Arbitrary<Ev> = fc.oneof(
  { weight: 6, arbitrary: fc.record({ k: fc.constant('validated' as const), lagC: fc.integer({ min: 0, max: 2 }), lagP: fc.integer({ min: 0, max: 2 }), status: fc.constantFrom<LayoutStatus>('VALIDATED', 'VALIDATED', 'FINAL', 'CANDIDATE', 'REJECTED') }) },
  { weight: 4, arbitrary: fc.record({ k: fc.constant('candidate' as const), lagC: fc.integer({ min: 0, max: 1 }), lagP: fc.integer({ min: 0, max: 1 }) }) },
  { weight: 2, arbitrary: fc.constant({ k: 'stale' as const }) },
  { weight: 2, arbitrary: fc.constant({ k: 'bumpParts' as const }) },
  { weight: 2, arbitrary: fc.constant({ k: 'bumpConstraint' as const }) },
  { weight: 4, arbitrary: fc.constant({ k: 'send' as const }) },
  { weight: 4, arbitrary: fc.record({ k: fc.constant('ack' as const), behind: fc.integer({ min: 0, max: 2 }) }) },
  { weight: 2, arbitrary: fc.constant({ k: 'dup' as const }) },
  { weight: 1, arbitrary: fc.constant({ k: 'oldEpoch' as const }) },
  { weight: 2, arbitrary: fc.constant({ k: 'metrics' as const }) },
  { weight: 1, arbitrary: fc.constant({ k: 'snapshot' as const }) },
  { weight: 1, arbitrary: fc.constant({ k: 'reconnect' as const }) },
);

function layout(id: string, status: LayoutStatus, revs: Revs): Layout {
  return {
    id,
    hash: id,
    stage: 1,
    mode: 'default',
    status,
    parts_rev: revs.parts_rev,
    constraint_rev: revs.constraint_rev,
    mass_rev: revs.mass_rev,
    weights_rev: revs.weights_rev,
    poses: [],
    extra_items: [],
    metrics: { length_used_mm: 200 },
    scores: { normalised: { L: 0.1 }, g: 0.1, norm_epoch: 1 },
    algorithm: null,
    validation: null,
    origin: 'search',
    created: new Date(0).toISOString(),
  };
}

function run(events: Ev[], check: (c: ConnProto, s: SolverState, ctx: { prevNewest: Revs; seen: Revs; sentSinceAck: boolean; prevBest: Layout | null }) => void) {
  let conn = initialConn();
  let solver = initialSolver();
  const server: Revs = { epoch: 3, parts_rev: 1, constraint_rev: 1, mass_rev: 1, weights_rev: 1 };
  let seq = 0;
  let clientSeq = 0;
  let applied = 0;
  let n = 0;
  let last: Envelope | null = null;
  const seen: Revs = { epoch: 0, parts_rev: 0, constraint_rev: 0, mass_rev: 0, weights_rev: 0 };
  const env = (type: string, payload: unknown, epoch = server.epoch): Envelope => ({
    v: 1,
    type,
    seq: ++seq,
    epoch,
    parts_rev: server.parts_rev,
    constraint_rev: server.constraint_rev,
    mass_rev: server.mass_rev,
    weights_rev: server.weights_rev,
    applied_client_seq: applied,
    ts: new Date(0).toISOString(),
    payload,
  });
  const deliver = (e: Envelope) => {
    const prevNewest = { ...conn.newest };
    const prevBest = solver.best;
    const r = reduceEnvelope(conn, solver, e);
    conn = r.conn;
    solver = r.solver;
    if (r.accepted && e.epoch === conn.epoch) {
      seen.parts_rev = Math.max(seen.parts_rev, e.parts_rev);
      seen.constraint_rev = Math.max(seen.constraint_rev, e.constraint_rev);
    }
    last = e;
    check(conn, solver, { prevNewest, seen, sentSinceAck: clientSeq > applied, prevBest });
  };
  const snapshot = () =>
    deliver(
      env('state.snapshot', {
        project: { revs: { ...server } },
        best_validated: layout(`L${++n}`, 'VALIDATED', { ...server, parts_rev: Math.max(1, server.parts_rev - 1) }),
        candidate: null,
        run_status: 'SEARCHING',
        selector: null,
      }),
    );
  snapshot();
  for (const ev of events) {
    switch (ev.k) {
      case 'validated':
        deliver(env('layout.validated', { layout: layout(`L${++n}`, ev.status, { ...server, constraint_rev: Math.max(1, server.constraint_rev - ev.lagC), parts_rev: Math.max(1, server.parts_rev - ev.lagP) }), source: 'search' }));
        break;
      case 'candidate':
        deliver(env('layout.candidate', { layout: layout(`C${++n}`, 'CANDIDATE', { ...server, constraint_rev: Math.max(1, server.constraint_rev - ev.lagC), parts_rev: Math.max(1, server.parts_rev - ev.lagP) }) }));
        break;
      case 'stale':
        if (solver.best) deliver(env('layout.stale', { layout_id: solver.best.id, reason: 'test' }));
        break;
      case 'bumpParts':
        server.parts_rev++;
        server.constraint_rev++;
        deliver(env('status', { run_status: 'REVALIDATING' }));
        break;
      case 'bumpConstraint':
        server.constraint_rev++;
        deliver(env('status', { run_status: 'REVALIDATING' }));
        break;
      case 'send':
        clientSeq++;
        conn = markClientSeqSent(conn, clientSeq);
        check(conn, solver, { prevNewest: conn.newest, seen, sentSinceAck: clientSeq > applied, prevBest: solver.best });
        break;
      case 'ack':
        applied = Math.max(applied, clientSeq - ev.behind);
        deliver(env('edit.ack', { client_seq: applied }));
        break;
      case 'dup':
        if (last) deliver({ ...(last as Envelope) });
        break;
      case 'oldEpoch':
        deliver(env('layout.validated', { layout: layout(`X${++n}`, 'VALIDATED', { ...server, constraint_rev: 999, parts_rev: 999 }), source: 'search' }, server.epoch - 1));
        break;
      case 'metrics':
        server.mass_rev++;
        if (solver.best) deliver(env('metrics.update', { layout_id: solver.best.id, metrics: { mass_kg: 3 } }));
        break;
      case 'snapshot':
        snapshot();
        break;
      case 'reconnect':
        conn = connOnNewConnection(conn);
        seq = 0;
        clientSeq = 0;
        applied = 0;
        snapshot();
        break;
    }
  }
}

describe('generation / revision invariants (T-UI3, fast-check)', () => {
  it('a layout drawn as VALIDATED is never older than the newest constraint_rev / parts_rev seen', () => {
    fc.assert(
      fc.property(fc.array(evArb, { maxLength: 80 }), (events) => {
        run(events, (conn, solver) => {
          for (const item of renderPlan(solver, conn.newest, { expert: true, showGhost: true })) {
            if (item.style === 'solid') {
              expect(['VALIDATED', 'FINAL']).toContain(item.layout.status);
              expect(item.layout.constraint_rev).toBeGreaterThanOrEqual(conn.newest.constraint_rev);
              expect(item.layout.parts_rev).toBeGreaterThanOrEqual(conn.newest.parts_rev);
            }
            if (item.kind === 'VALIDATED' || item.kind === 'FINAL') expect(isCurrent(item.layout, conn.newest)).toBe(true);
          }
        });
      }),
      { numRuns: 400 },
    );
  });

  it('the displayed best is always a VALIDATED/FINAL/STALE layout — never a candidate or a rejected one', () => {
    fc.assert(
      fc.property(fc.array(evArb, { maxLength: 80 }), (events) => {
        run(events, (_conn, solver) => {
          if (solver.best) expect(['VALIDATED', 'FINAL', 'STALE']).toContain(solver.best.status);
        });
      }),
      { numRuns: 300 },
    );
  });

  it('newest revisions never decrease within an epoch and cover every accepted envelope', () => {
    fc.assert(
      fc.property(fc.array(evArb, { maxLength: 80 }), (events) => {
        run(events, (conn, _s, ctx) => {
          if (conn.epoch === 3) {
            expect(conn.newest.parts_rev).toBeGreaterThanOrEqual(ctx.prevNewest.parts_rev);
            expect(conn.newest.constraint_rev).toBeGreaterThanOrEqual(ctx.prevNewest.constraint_rev);
            expect(conn.newest.parts_rev).toBeGreaterThanOrEqual(ctx.seen.parts_rev);
            expect(conn.newest.constraint_rev).toBeGreaterThanOrEqual(ctx.seen.constraint_rev);
          }
        });
      }),
      { numRuns: 300 },
    );
  });

  it('candidates are only ever drawn as dotted ghosts (and only in Expert with ghosts on)', () => {
    fc.assert(
      fc.property(fc.array(evArb, { maxLength: 80 }), fc.boolean(), fc.boolean(), (events, expert, showGhost) => {
        run(events, (conn, solver) => {
          const plan = renderPlan(solver, conn.newest, { expert, showGhost });
          for (const item of plan) {
            if (item.role === 'candidate' || item.layout.status === 'CANDIDATE' || item.layout.status === 'VALIDATING') {
              expect(item.style).toBe('ghost');
              expect(item.kind).toBe('UNVERIFIED');
            }
          }
          if (!(expert && showGhost)) expect(plan.some((i) => i.role === 'candidate')).toBe(false);
        });
      }),
      { numRuns: 300 },
    );
  });

  it('scores are hidden ("updating…") until applied_client_seq catches up with the last client_seq sent', () => {
    fc.assert(
      fc.property(fc.array(evArb, { maxLength: 80 }), (events) => {
        run(events, (conn, _s, ctx) => {
          expect(scoresVisible(conn)).toBe(conn.appliedClientSeq >= conn.lastClientSeqSent);
          if (ctx.sentSinceAck) expect(scoresVisible(conn)).toBe(false);
        });
      }),
      { numRuns: 300 },
    );
  });

  it('duplicate seqs and older epochs are dropped (latest wins)', () => {
    let conn = initialConn();
    let solver = initialSolver();
    const base = { v: 1 as const, epoch: 5, parts_rev: 1, constraint_rev: 1, mass_rev: 1, weights_rev: 1, applied_client_seq: 0, ts: '' };
    let r = reduceEnvelope(conn, solver, { ...base, type: 'state.snapshot', seq: 1, payload: { project: null, best_validated: null, candidate: null, run_status: 'IDLE', selector: null } } as unknown as Envelope);
    conn = r.conn;
    solver = r.solver;
    r = reduceEnvelope(conn, solver, { ...base, type: 'status', seq: 2, payload: { run_status: 'SEARCHING' } });
    expect(r.accepted).toBe(true);
    conn = r.conn;
    solver = r.solver;
    expect(reduceEnvelope(conn, solver, { ...base, type: 'status', seq: 2, payload: { run_status: 'PAUSED' } }).accepted).toBe(false);
    expect(reduceEnvelope(conn, solver, { ...base, type: 'status', seq: 3, epoch: 4, payload: { run_status: 'PAUSED' } }).accepted).toBe(false);
  });

  it('an older layout never replaces a newer one on screen; a stale best is badged, not hidden', () => {
    let conn = initialConn();
    let solver = initialSolver();
    const revs = { epoch: 1, parts_rev: 2, constraint_rev: 2, mass_rev: 1, weights_rev: 1 };
    const base = { v: 1 as const, ...revs, applied_client_seq: 0, ts: '' };
    let r = reduceEnvelope(conn, solver, { ...base, type: 'layout.validated', seq: 1, payload: { layout: layout('A', 'VALIDATED', revs) } });
    r = reduceEnvelope(r.conn, r.solver, { ...base, type: 'layout.validated', seq: 2, payload: { layout: layout('B', 'VALIDATED', { ...revs, constraint_rev: 1 }) } });
    expect(r.solver.best?.id).toBe('A');
    r = reduceEnvelope(r.conn, r.solver, { ...base, parts_rev: 3, type: 'status', seq: 3, payload: { run_status: 'REVALIDATING' } });
    conn = r.conn;
    solver = r.solver;
    expect(displayKind(solver.best!, conn.newest)).toBe('PREVIOUS_INPUTS');
    expect(renderPlan(solver, conn.newest, { expert: false, showGhost: false })[0].style).toBe('stale');
  });
});

describe('Stage 2 least-violating candidate (INFEASIBLE)', () => {
  const revs: Revs = { epoch: 3, parts_rev: 2, constraint_rev: 5, mass_rev: 1, weights_rev: 1 };
  const env = (type: string, payload: unknown, seq: number): Envelope => ({
    v: 1, type, seq, ...revs, applied_client_seq: 0, ts: new Date(0).toISOString(), payload,
  });
  it('is shown only when no current validated layout exists, and never as VALIDATED', () => {
    let conn = initialConn();
    let solver = initialSolver();
    const inf = { ...layout('L-0007', 'INFEASIBLE', revs), stage: 2 as const, violations_engineering: ['exceeds the usable length by 4.2 mm'] };
    ({ conn, solver } = reduceEnvelope(conn, solver, env('state.snapshot', { project: null, best_validated: null, candidate: null, run_status: 'SEARCHING', selector: null, least_violating: inf }, 1)));
    let plan = renderPlan(solver, conn.newest, { expert: false, showGhost: false });
    expect(plan).toHaveLength(1);
    expect(plan[0].kind).toBe('INFEASIBLE');
    expect(plan[0].style).toBe('stale');
    expect(displayKind(inf, conn.newest)).toBe('INFEASIBLE');
    // a layout.validated with status INFEASIBLE is refused as a "best"
    ({ solver } = reduceEnvelope(conn, solver, env('layout.validated', { layout: { ...inf, id: 'L-0008' } }, 2)));
    expect(solver.best).toBeNull();
    // a feasible validated layout for the current inputs takes over
    const ok = { ...layout('L-0009', 'VALIDATED', revs), stage: 2 as const };
    ({ conn, solver } = reduceEnvelope(conn, solver, env('layout.validated', { layout: ok, source: 'search' }, 3)));
    plan = renderPlan(solver, conn.newest, { expert: false, showGhost: false });
    expect(plan[0].layout.id).toBe('L-0009');
    expect(plan[0].kind).toBe('VALIDATED');
  });
  it('the views label the layout they draw: the candidate exactly when it is the one shown', () => {
    // as found in the app: a Stage 1 layout validated under earlier inputs, and Stage 2's least-violating candidate
    const s1 = { ...layout('L-0571', 'VALIDATED', { ...revs, constraint_rev: 4 }), metrics: { length_used_mm: 235.4 } };
    const inf = { ...layout('L-0620', 'INFEASIBLE', revs), stage: 2 as const, metrics: { length_used_mm: 467.7 } };
    let shown = shownLayout({ best: s1, infeasible: inf }, revs);
    expect(shown).toEqual({ layout: inf, infeasible: true });
    expect(renderPlan({ best: s1, infeasible: inf, candidate: null }, revs, { expert: false, showGhost: false })[0].layout.id).toBe('L-0620');
    expect(shown.layout?.metrics?.length_used_mm).toBe(467.7); // not the Stage 1 layout's 235.4 mm
    // a validated layout for the current inputs is shown (and labelled) instead
    const ok = { ...layout('L-0700', 'VALIDATED', revs), stage: 2 as const };
    shown = shownLayout({ best: ok, infeasible: inf }, revs);
    expect(shown).toEqual({ layout: ok, infeasible: false });
    // a candidate for older inputs is never shown over a validated layout, current or not
    expect(shownLayout({ best: s1, infeasible: { ...inf, constraint_rev: 4 } }, revs)).toEqual({ layout: s1, infeasible: false });
    expect(shownLayout({ best: null }, revs)).toEqual({ layout: null, infeasible: false });
  });
  it('layout.infeasible updates the candidate but ignores older inputs', () => {
    let conn = initialConn();
    let solver = initialSolver();
    const a = { ...layout('L-0001', 'INFEASIBLE', revs), stage: 2 as const };
    ({ conn, solver } = reduceEnvelope(conn, solver, env('layout.infeasible', { layout: a }, 1)));
    expect(solver.infeasible?.id).toBe('L-0001');
    const older = { ...layout('L-0002', 'INFEASIBLE', { ...revs, constraint_rev: 4 }), stage: 2 as const };
    ({ conn, solver } = reduceEnvelope(conn, solver, env('layout.infeasible', { layout: older }, 2)));
    expect(solver.infeasible?.id).toBe('L-0001');
  });
});

describe('V2: layout.updated (brackets designed after validation)', () => {
  const revs: Revs = { epoch: 3, parts_rev: 2, constraint_rev: 5, mass_rev: 1, weights_rev: 1 };
  const env = (type: string, payload: unknown, seq: number): Envelope => ({
    v: 1, type, seq, ...revs, applied_client_seq: 0, ts: new Date(0).toISOString(), payload,
  });
  const bracket = (url: string) => ({ id: 'L-0042-br0', kind: 'bracket', process: 'metal_am', mesh_url: url, mass_kg: 0.01 });
  it('replaces the layout on screen in place: new bracket meshes, no "new layout", earlier best kept', () => {
    let conn = initialConn();
    let solver = initialSolver();
    const prev = { ...layout('L-0041', 'VALIDATED', revs), stage: 2 as const };
    const box = { ...layout('L-0042', 'VALIDATED', revs), stage: 2 as const, extra_items: [bracket('/api/items/L-0042-br0/mesh')] } as Layout;
    ({ conn, solver } = reduceEnvelope(conn, solver, env('layout.validated', { layout: prev, source: 'search' }, 1)));
    ({ conn, solver } = reduceEnvelope(conn, solver, env('layout.validated', { layout: box, source: 'search' }, 2)));
    expect(solver.prevBest?.id).toBe('L-0041');
    const designed = { ...box, extra_items: [bracket('/api/items/L-0042-br0/mesh?v=d1')] } as Layout;
    const r = reduceEnvelope(conn, solver, env('layout.updated', { layout: designed, reason: 'brackets designed' }, 3));
    expect(r.solver.best?.extra_items[0].mesh_url).toBe('/api/items/L-0042-br0/mesh?v=d1');
    expect(r.solver.prevBest?.id).toBe('L-0041');
    expect(r.effects.some((e) => e.type === 'announce')).toBe(false);
    const plan = renderPlan(r.solver, r.conn.newest, { expert: false, showGhost: false });
    expect(plan[0].layout.extra_items[0].mesh_url).toContain('?v=d1');
    // an update for a layout that is not on screen changes nothing
    const other = reduceEnvelope(r.conn, r.solver, env('layout.updated', { layout: { ...designed, id: 'L-0099' } }, 4));
    expect(other.solver.best?.id).toBe('L-0042');
  });
});

describe('V2: saved STL files (saved_stl.updated)', () => {
  const revs: Revs = { epoch: 3, parts_rev: 2, constraint_rev: 5, mass_rev: 1, weights_rev: 1 };
  const env = (payload: unknown, seq: number, ts: string): Envelope => ({
    v: 1, type: 'saved_stl.updated', seq, ...revs, applied_client_seq: 0, ts, payload,
  });
  const file = (f: string) => ({ file: f, part_id: 'p1', triangles: 12 });
  it('keeps the latest manifest and when it came, and logs what happened', () => {
    let conn = initialConn();
    let solver = initialSolver();
    const saved = { status: 'complete', folder: 'D:/p/saved_stl', saving: null, layout_id: 'L-0042', parts: [file('parts/a.stl')], brackets: [file('brackets/AM_a_br0.stl')] };
    ({ conn, solver } = reduceEnvelope(conn, solver, env({ saved_stl: saved }, 1, '2026-10-24T06:00:00Z')));
    expect(solver.savedStl?.layout_id).toBe('L-0042');
    expect(solver.savedStlAt).toBe('2026-10-24T06:00:00Z');
    expect(solver.log.at(-1)?.text).toBe('saved STL files: L-0042 with 1 bracket(s)');
    const removed = { ...saved, status: 'brackets_removed', brackets: [], brackets_removed: { at: 'x', reason: 'Balance the Spacecraft 36 → 40' } };
    ({ conn, solver } = reduceEnvelope(conn, solver, env({ saved_stl: removed }, 2, '2026-10-24T06:01:00Z')));
    expect(solver.savedStl?.status).toBe('brackets_removed');
    expect(solver.log.at(-1)?.text).toBe('saved STL files: brackets removed (Balance the Spacecraft 36 → 40)');
    const same = reduceEnvelope(conn, solver, env({}, 3, '2026-10-24T06:02:00Z'));      // no manifest: ignored
    expect(same.solver.savedStl?.status).toBe('brackets_removed');
  });
});
