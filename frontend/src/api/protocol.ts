// Pure client-side protocol state machine for the WebSocket envelope (docs/api-contract.md §4, protocol §M).
// Everything here is side-effect free so the generation / revision invariants can be property-tested.

import type {
  Envelope,
  Layout,
  ParetoPoint,
  Part,
  ProgressPayload,
  ProjectSnapshot,
  Revs,
  SavedStl,
  SelectorChoice,
  SnapshotPayload,
  StudyUpdatePayload,
} from './types';

export interface ConnProto {
  /** epoch of the server state we are following (null before the first snapshot) */
  epoch: number | null;
  /** last server seq accepted on the current connection */
  lastSeq: number;
  /** newest revisions the client has received (component-wise maximum) */
  newest: Revs;
  /** highest applied_client_seq / edit.ack seen on the current connection */
  appliedClientSeq: number;
  /** highest client_seq sent on the current connection */
  lastClientSeqSent: number;
  /** true once a state.snapshot has been received on the current connection */
  synced: boolean;
}

export interface LogEntry {
  at: string;
  kind: 'validated' | 'candidate' | 'stale' | 'status' | 'error' | 'selector' | 'info' | 'progress';
  text: string;
}

export interface ProgressPoint {
  t: number;
  evaluations: number | null;
  best_g: number | null;
  elapsed_s: number | null;
}

export interface StudyState {
  progress: number | null;
  partial: unknown;
  at: string;
}

export interface FidelityRun {
  status: string;
  progress: number | null;
  level?: string | null;
}

export interface SolverState {
  best: Layout | null;
  /** Stage 2 with no feasible layout: least-violating certified candidate (never drawn as VALIDATED) */
  infeasible: Layout | null;
  bestSource: 'archive' | 'search' | 'snapshot' | null;
  prevBest: Layout | null;
  candidate: Layout | null;
  staleReasons: Record<string, string>;
  runStatus: string;
  statusDetail: string;
  progress: ProgressPayload | null;
  progressHistory: ProgressPoint[];
  selector: SelectorChoice | null;
  selectorLog: { at: string; algorithm: string; reasons: string[] }[];
  pareto: ParetoPoint[] | null;
  studies: Record<string, StudyState>;
  fidelityRuns: Record<string, FidelityRun>;
  /** V2: the saved STL files as last pushed (saved_stl.updated); null until a push — the UI fetches them on mount */
  savedStl: SavedStl | null;
  savedStlAt: string | null;
  log: LogEntry[];
  lastError: string | null;
  metricsConfirmedAt: string | null;
}

export type Effect =
  | { type: 'project'; project: ProjectSnapshot }
  | { type: 'refetchProject' }
  | { type: 'resendIntents' }
  | { type: 'announce'; text: string };

export const ZERO_REVS: Revs = { epoch: 0, parts_rev: 0, constraint_rev: 0, mass_rev: 0, weights_rev: 0 };

export function initialConn(): ConnProto {
  return { epoch: null, lastSeq: 0, newest: { ...ZERO_REVS }, appliedClientSeq: 0, lastClientSeqSent: 0, synced: false };
}

export function initialSolver(): SolverState {
  return {
    best: null,
    infeasible: null,
    bestSource: null,
    prevBest: null,
    candidate: null,
    staleReasons: {},
    runStatus: 'IDLE',
    statusDetail: '',
    progress: null,
    progressHistory: [],
    selector: null,
    selectorLog: [],
    pareto: null,
    studies: {},
    fidelityRuns: {},
    savedStl: null,
    savedStlAt: null,
    log: [],
    lastError: null,
    metricsConfirmedAt: null,
  };
}

/** A new connection starts a new session: server seq and client_seq numbering restart (see DECISIONS.md). */
export function connOnNewConnection(c: ConnProto): ConnProto {
  return { ...c, lastSeq: 0, appliedClientSeq: 0, lastClientSeqSent: 0, synced: false };
}

export function markClientSeqSent(c: ConnProto, clientSeq: number): ConnProto {
  return clientSeq > c.lastClientSeqSent ? { ...c, lastClientSeqSent: clientSeq } : c;
}

export function revsOf(env: Pick<Envelope, 'epoch' | 'parts_rev' | 'constraint_rev' | 'mass_rev' | 'weights_rev'>): Revs {
  return {
    epoch: env.epoch ?? 0,
    parts_rev: env.parts_rev ?? 0,
    constraint_rev: env.constraint_rev ?? 0,
    mass_rev: env.mass_rev ?? 0,
    weights_rev: env.weights_rev ?? 0,
  };
}

export function maxRevs(a: Revs, b: Revs): Revs {
  return {
    epoch: Math.max(a.epoch, b.epoch),
    parts_rev: Math.max(a.parts_rev, b.parts_rev),
    constraint_rev: Math.max(a.constraint_rev, b.constraint_rev),
    mass_rev: Math.max(a.mass_rev, b.mass_rev),
    weights_rev: Math.max(a.weights_rev, b.weights_rev),
  };
}

/** Rule 1 helper: a layout is current only if neither its constraint_rev nor its parts_rev is older than the newest seen. */
export function isCurrent(l: Pick<Layout, 'constraint_rev' | 'parts_rev'>, newest: Revs): boolean {
  return l.constraint_rev >= newest.constraint_rev && l.parts_rev >= newest.parts_rev;
}

function isOlderThan(a: Pick<Layout, 'constraint_rev' | 'parts_rev'>, b: Pick<Layout, 'constraint_rev' | 'parts_rev'>): boolean {
  return a.constraint_rev < b.constraint_rev || a.parts_rev < b.parts_rev;
}

const VALID_STATUSES = new Set(['VALIDATED', 'FINAL']);
const nowIso = () => new Date().toISOString();
const MAX_LOG = 400;
const MAX_HISTORY = 5000;

function pushLog(log: LogEntry[], e: LogEntry): LogEntry[] {
  const out = log.length >= MAX_LOG ? log.slice(log.length - MAX_LOG + 1) : log.slice();
  out.push(e);
  return out;
}

export function algorithmId(sel: SelectorChoice | null | undefined): string {
  if (!sel || !sel.algorithm) return '';
  return typeof sel.algorithm === 'string' ? sel.algorithm : sel.algorithm.id;
}
export function algorithmLabel(sel: SelectorChoice | null | undefined, legend?: Record<string, string>): string {
  if (!sel || !sel.algorithm) return '';
  if (typeof sel.algorithm === 'string') return legend?.[sel.algorithm] ?? sel.algorithm;
  return sel.algorithm.label || sel.algorithm.id;
}

export interface ReduceResult {
  conn: ConnProto;
  solver: SolverState;
  effects: Effect[];
  accepted: boolean;
}

/** Apply one server→client envelope. Latest wins; stale epochs and duplicate / out-of-order seqs are dropped. */
export function reduceEnvelope(conn: ConnProto, solver: SolverState, env: Envelope): ReduceResult {
  const effects: Effect[] = [];
  const at = env.ts || nowIso();

  if (env.type === 'state.snapshot') {
    const p = env.payload as SnapshotPayload;
    const projectRevs = p.project?.revs ?? ZERO_REVS;
    const epochChanged = conn.epoch !== null && env.epoch !== conn.epoch;
    // A different epoch is a different server state (restart / reset): revisions start over.
    const base = epochChanged ? { ...ZERO_REVS } : conn.newest;
    const newest = maxRevs(maxRevs(base, revsOf(env)), projectRevs);
    const nextConn: ConnProto = {
      ...conn,
      epoch: env.epoch,
      lastSeq: env.seq,
      newest,
      appliedClientSeq: Math.max(conn.appliedClientSeq, env.applied_client_seq ?? 0),
      synced: true,
    };
    const incoming = p.best_validated && VALID_STATUSES.has(p.best_validated.status) ? p.best_validated : null;
    const nextSolver: SolverState = {
      ...solver,
      best: incoming,
      infeasible: p.least_violating && p.least_violating.status === 'INFEASIBLE' ? p.least_violating : null,
      bestSource: incoming ? 'snapshot' : null,
      prevBest: solver.best && incoming && solver.best.id !== incoming.id ? solver.best : solver.prevBest,
      candidate: p.candidate ?? null,
      runStatus: p.run_status ?? solver.runStatus,
      progress: p.progress ?? solver.progress,
      selector: p.selector ?? solver.selector,
      log: pushLog(solver.log, { at, kind: 'info', text: `snapshot received (epoch ${env.epoch})` }),
    };
    if (p.project) effects.push({ type: 'project', project: p.project });
    effects.push({ type: 'resendIntents' });
    return { conn: nextConn, solver: nextSolver, effects, accepted: true };
  }

  if (conn.epoch !== null && env.epoch < conn.epoch) return { conn, solver, effects, accepted: false };
  if (env.seq <= conn.lastSeq) return { conn, solver, effects, accepted: false };

  const newest = maxRevs(conn.newest, revsOf(env));
  if (newest.parts_rev > conn.newest.parts_rev || newest.mass_rev > conn.newest.mass_rev) effects.push({ type: 'refetchProject' });
  let c: ConnProto = {
    ...conn,
    epoch: conn.epoch === null ? env.epoch : Math.max(conn.epoch, env.epoch),
    lastSeq: env.seq,
    newest,
    appliedClientSeq: Math.max(conn.appliedClientSeq, env.applied_client_seq ?? 0),
  };
  let s: SolverState = solver;

  switch (env.type) {
    case 'edit.ack': {
      const cs = (env.payload as { client_seq?: number })?.client_seq ?? 0;
      c = { ...c, appliedClientSeq: Math.max(c.appliedClientSeq, cs) };
      break;
    }
    case 'layout.validated': {
      const p = env.payload as { layout: Layout; source?: 'archive' | 'search' };
      const L = p?.layout;
      if (!L || !VALID_STATUSES.has(L.status)) {
        s = { ...s, log: pushLog(s.log, { at, kind: 'error', text: `ignored layout.validated with status ${L?.status ?? '?'}` }) };
        break;
      }
      if (s.best && isOlderThan(L, s.best)) {
        s = { ...s, log: pushLog(s.log, { at, kind: 'info', text: `ignored ${L.id}: older inputs than the layout on screen` }) };
        break;
      }
      s = {
        ...s,
        prevBest: s.best && s.best.id !== L.id ? s.best : s.prevBest,
        best: L,
        bestSource: p.source ?? 'search',
        candidate: s.candidate && (s.candidate.hash === L.hash || s.candidate.id === L.id) ? null : s.candidate,
        log: pushLog(s.log, { at, kind: 'validated', text: `${L.id} validated (${p.source ?? 'search'})` }),
      };
      if (!s.prevBest || s.prevBest.id !== L.id) effects.push({ type: 'announce', text: `New validated layout ${L.id}` });
      break;
    }
    case 'layout.updated': {
      // the same layout with new derived data (e.g. its brackets designed: new meshes and masses) — replaced where it
      // is shown, without counting as a new layout
      const p = env.payload as { layout: Layout; reason?: string };
      const L = p?.layout;
      if (!L) break;
      if (s.best && s.best.id === L.id) s = { ...s, best: s.best.status === 'STALE' ? { ...L, status: 'STALE' } : L };
      if (s.infeasible && s.infeasible.id === L.id) s = { ...s, infeasible: L };
      s = { ...s, log: pushLog(s.log, { at, kind: 'info', text: `${L.id} updated${p.reason ? ` (${p.reason})` : ''}` }) };
      break;
    }
    case 'saved_stl.updated': {
      // V2: the saved STL files were written, or their brackets removed after a slider moved
      const m = (env.payload as { saved_stl?: SavedStl })?.saved_stl;
      if (!m) break;
      const text =
        m.status === 'brackets_removed'
          ? `saved STL files: brackets removed (${m.brackets_removed?.reason ?? 'settings changed'})`
          : `saved STL files: ${m.layout_id} with ${m.brackets?.length ?? 0} bracket(s)`;
      s = { ...s, savedStl: m, savedStlAt: at, log: pushLog(s.log, { at, kind: 'info', text }) };
      break;
    }
    case 'layout.infeasible': {
      const L = (env.payload as { layout: Layout })?.layout;
      if (!L || L.status !== 'INFEASIBLE') break;
      if (s.infeasible && isOlderThan(L, s.infeasible)) break;
      s = { ...s, infeasible: L, log: pushLog(s.log, { at, kind: 'info', text: `${L.id}: least-violating candidate (INFEASIBLE)` }) };
      break;
    }
    case 'layout.candidate': {
      const L = (env.payload as { layout: Layout })?.layout;
      if (!L || !isCurrent(L, c.newest)) break;
      s = { ...s, candidate: L, log: pushLog(s.log, { at, kind: 'candidate', text: `candidate ${L.id} (unverified)` }) };
      break;
    }
    case 'layout.stale': {
      const p = env.payload as { layout_id: string; reason: string };
      const staleReasons = { ...s.staleReasons, [p.layout_id]: p.reason };
      s = {
        ...s,
        staleReasons,
        best: s.best && s.best.id === p.layout_id ? { ...s.best, status: 'STALE' } : s.best,
        candidate: s.candidate && s.candidate.id === p.layout_id ? null : s.candidate,
        log: pushLog(s.log, { at, kind: 'stale', text: `${p.layout_id} stale: ${p.reason}` }),
      };
      break;
    }
    case 'metrics.update': {
      const p = env.payload as { layout_id: string; metrics: Layout['metrics'] };
      if (s.best && s.best.id === p.layout_id && p.metrics) {
        s = {
          ...s,
          best: { ...s.best, metrics: { ...(s.best.metrics ?? {}), ...p.metrics }, mass_rev: Math.max(s.best.mass_rev, env.mass_rev ?? 0) },
          metricsConfirmedAt: at,
        };
      }
      break;
    }
    case 'progress': {
      const p = env.payload as ProgressPayload;
      const hist = s.progressHistory.length >= MAX_HISTORY ? s.progressHistory.slice(1) : s.progressHistory.slice();
      hist.push({ t: Date.parse(at) || Date.now(), evaluations: p.evaluations ?? null, best_g: p.best_g ?? null, elapsed_s: p.elapsed_s ?? null });
      s = { ...s, progress: p, progressHistory: hist };
      break;
    }
    case 'selector.changed': {
      const p = env.payload as SelectorChoice;
      const prevId = algorithmId(s.selector);
      const nextId = algorithmId(p);
      s = {
        ...s,
        selector: { ...(s.selector ?? { reasons: [] }), ...p },
        selectorLog: prevId !== nextId ? [...s.selectorLog, { at, algorithm: algorithmLabel(p) || nextId, reasons: p.reasons ?? [] }] : s.selectorLog,
        log: pushLog(s.log, { at, kind: 'selector', text: `algorithm: ${algorithmLabel(p) || nextId}` }),
      };
      break;
    }
    case 'pareto.update': {
      const p = env.payload as { points: ParetoPoint[] };
      s = { ...s, pareto: p.points ?? [] };
      break;
    }
    case 'study.update': {
      const p = env.payload as StudyUpdatePayload;
      const studies = { ...s.studies, [p.study]: { progress: p.progress ?? null, partial: p.partial, at } };
      let fidelityRuns = s.fidelityRuns;
      if (p.study === 'fidelity') {
        fidelityRuns = { ...fidelityRuns };
        const items = Array.isArray(p.partial) ? p.partial : p.partial ? [p.partial] : [];
        for (const raw of items) {
          const it = raw as { part_id?: string; status?: string; progress?: number; level?: string };
          if (!it || !it.part_id) continue;
          fidelityRuns[it.part_id] = { status: it.status ?? 'RUNNING', progress: it.progress ?? p.progress ?? null, level: it.level ?? null };
        }
      }
      s = { ...s, studies, fidelityRuns };
      break;
    }
    case 'status': {
      const p = env.payload as { run_status: string; detail?: string };
      s = {
        ...s,
        runStatus: p.run_status ?? s.runStatus,
        statusDetail: p.detail ?? '',
        log: pushLog(s.log, { at, kind: 'status', text: `${p.run_status}${p.detail ? ` — ${p.detail}` : ''}` }),
      };
      effects.push({ type: 'announce', text: `Optimiser ${String(p.run_status).toLowerCase()}` });
      break;
    }
    case 'error': {
      const p = env.payload as { message: string };
      s = { ...s, lastError: p.message, log: pushLog(s.log, { at, kind: 'error', text: p.message }) };
      break;
    }
    default:
      break;
  }
  return { conn: c, solver: s, effects, accepted: true };
}

// ---------------------------------------------------------------------------------------------- display rules

export type DisplayKind = 'VALIDATED' | 'FINAL' | 'PREVIOUS_INPUTS' | 'STALE' | 'UNVERIFIED' | 'REJECTED' | 'INFEASIBLE';
export type RenderStyle = 'solid' | 'stale' | 'ghost';

export function displayKind(l: Layout, newest: Revs, role: 'best' | 'candidate' | 'archive' = 'best'): DisplayKind {
  if (role === 'candidate' || l.status === 'CANDIDATE' || l.status === 'VALIDATING') return 'UNVERIFIED';
  if (l.status === 'REJECTED') return 'REJECTED';
  if (l.status === 'INFEASIBLE') return 'INFEASIBLE';
  if (!isCurrent(l, newest)) return 'PREVIOUS_INPUTS';
  if (l.status === 'STALE') return 'STALE';
  return l.status === 'FINAL' ? 'FINAL' : 'VALIDATED';
}

export function badgeText(kind: DisplayKind): string {
  switch (kind) {
    case 'VALIDATED':
      return 'VALIDATED';
    case 'FINAL':
      return 'FINAL';
    case 'PREVIOUS_INPUTS':
      return 'VALIDATED FOR PREVIOUS INPUTS';
    case 'STALE':
      return 'STALE';
    case 'UNVERIFIED':
      return 'UNVERIFIED';
    case 'REJECTED':
      return 'REJECTED';
    case 'INFEASIBLE':
      return 'NO FEASIBLE LAYOUT FOUND (not proven infeasible)';
  }
}

export function styleFor(kind: DisplayKind): RenderStyle {
  if (kind === 'VALIDATED' || kind === 'FINAL') return 'solid';
  if (kind === 'UNVERIFIED' || kind === 'REJECTED') return 'ghost';
  return 'stale';
}

/** Rule 2: scores are shown only when the server has applied every edit this client sent. */
export function scoresVisible(c: Pick<ConnProto, 'appliedClientSeq' | 'lastClientSeqSent'>): boolean {
  return c.appliedClientSeq >= c.lastClientSeqSent;
}

export interface RenderItem {
  layout: Layout;
  role: 'best' | 'candidate';
  kind: DisplayKind;
  style: RenderStyle;
}

/**
 * The layout the views show as the main one: the best validated layout, or — in Stage 2 with no feasible layout for
 * the current inputs — the least-violating candidate (`infeasible`: drawn desaturated with its verdict, never as
 * VALIDATED). The 3D view, its labels and the metrics all follow this one choice.
 */
export function shownLayout(
  solver: Pick<SolverState, 'best'> & Partial<Pick<SolverState, 'infeasible'>>,
  newest: Revs,
): { layout: Layout | null; infeasible: boolean } {
  const inf = solver.infeasible ?? null;
  if (inf && isCurrent(inf, newest) && (!solver.best || !isCurrent(solver.best, newest))) return { layout: inf, infeasible: true };
  return { layout: solver.best ?? null, infeasible: false };
}

/** What the viewport draws. Candidates are only ever ghosts (rule 3), and only in Expert mode with ghosts enabled. */
export function renderPlan(
  solver: Pick<SolverState, 'best' | 'candidate'> & Partial<Pick<SolverState, 'infeasible'>>,
  newest: Revs,
  opts: { expert: boolean; showGhost: boolean },
): RenderItem[] {
  const out: RenderItem[] = [];
  const shown = shownLayout(solver, newest);
  if (shown.infeasible && shown.layout) {
    out.push({ layout: shown.layout, role: 'best', kind: 'INFEASIBLE', style: 'stale' });
  } else if (solver.best) {
    const kind = displayKind(solver.best, newest, 'best');
    out.push({ layout: solver.best, role: 'best', kind, style: styleFor(kind) });
  }
  if (solver.candidate && opts.expert && opts.showGhost) {
    out.push({ layout: solver.candidate, role: 'candidate', kind: 'UNVERIFIED', style: 'ghost' });
  }
  return out;
}

/** Packable parts of the current project that a layout does not place, and placed ids no longer in the project. */
export function layoutCoverage(l: Pick<Layout, 'poses'>, parts: Part[]): { missing: Part[]; removed: string[] } {
  const placed = new Set(l.poses.map((p) => p.part_id));
  const ids = new Set(parts.map((p) => p.id));
  const missing = parts.filter((p) => !placed.has(p.id) && (p.status === 'VALID' || p.status === 'REPAIRED'));
  const removed = [...placed].filter((id) => !ids.has(id));
  return { missing, removed };
}
