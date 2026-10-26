import type { Layout, Metrics } from '../api/types';
import { useApp } from '../store/store';
import { useDisplayMetrics } from '../hooks';
import { fmt, fmtDelta, type Quantity } from '../lib/fmt';
import { METRIC_TIPS, NOT_OPTIMAL } from '../lib/copy';
import { InfoTip, MockTag } from './ui';

function Metric(props: { k: string; tipKey: keyof typeof METRIC_TIPS; v: string; n?: string; testId?: string }) {
  return (
    <div className="metric" data-testid={props.testId}>
      <div className="k">
        {props.k} <InfoTip tip={METRIC_TIPS[props.tipKey]} label={props.k} />
      </div>
      <div className="v">{props.v}</div>
      {props.n ? <div className="n">{props.n}</div> : null}
    </div>
  );
}

/** Bottom metric strip (Overview). Metrics are shown exactly as published (or as a labelled local recompute). */
export function MetricStrip() {
  const dm = useDisplayMetrics();
  const stage = useApp((s) => s.goals.settings?.stage ?? 1);
  const limits = useApp((s) => s.dataset.project?.limits);
  const size = useApp((s) => s.dataset.project?.enclosure.size_mm as number[] | undefined);
  const mode = useApp((s) => s.conn.mode);
  const m = dm.metrics;                       // of the layout the 3D view draws (the candidate when Stage 2 is infeasible)
  const layoutStage = dm.layout?.stage ?? null;
  const showingInfeasible = dm.infeasible;
  const total = size?.[2] ?? 340.5;
  const note = limits?.cds_mass_note_kg ?? 6.0;
  const src = dm.source === 'local' ? ' · local recompute (awaiting backend)' : '';
  const mock = mode === 'mock' ? 'MOCK · ' : '';
  return (
    <div className="metric-strip" role="region" aria-label="Current layout metrics" data-testid="metric-strip">
      <Metric
        k="Space used"
        tipKey="space"
        v={fmt(m?.space_used ?? null, 'pct')}
        n={`${mock}length ${fmt(m?.length_used_mm ?? null, 'mm', { unit: false })} / ${fmt(total, 'mm')} · same for every layout${
          m?.optional_left_out?.length ? ` · optional part${m.optional_left_out.length > 1 ? 's' : ''} left out: ${m.optional_left_out.length}` : ''
        }`}
        testId="metric-space"
      />
      <Metric k="Total mass" tipKey="mass" v={fmt(m?.mass_kg ?? null, 'kg')} n={`${mock}CDS note ${fmt(note, 'kg')} (typical maximum, not a limit)${src}`} testId="metric-mass" />
      <Metric
        k="Balance error"
        tipKey="balance"
        v={fmt(m?.com_error_mm ?? null, 'mm')}
        n={`${mock}${m?.com_box_ok == null ? 'CDS box —' : m.com_box_ok ? 'inside the CDS box' : stage === 1 ? 'outside the CDS box — allowed in Stage 1, enforced in Stage 2' : 'outside the CDS box'}${src}`}
        testId="metric-balance"
      />
      <Metric k="Rotational inertia (worst axis)" tipKey="inertia" v={fmt(m?.lambda_max_kgm2 ?? null, 'kgm2')} n={`${mock}λ_max${src}`} testId="metric-inertia" />
      <Metric
        k="Engineering validity"
        tipKey="validity"
        v={
          showingInfeasible
            ? 'INFEASIBLE'
            : layoutStage !== 2
              ? 'Not assessed'
              : m
                ? m.min_clearance_mm != null
                  ? `min slack ${fmt(m.min_clearance_mm, 'clearance')}`
                  : '—'
                : '—'
        }
        n={
          showingInfeasible
            ? `no feasible layout found yet (not proven infeasible) — least-violating candidate breaks ${dm.layout?.violations_engineering?.length ?? 0} rule(s)`
            : layoutStage !== 2
              ? stage === 2
                ? 'layout on screen is IDEALIZED — no Stage 2 layout yet'
                : 'IDEALIZED — switch to Stage 2 for engineering checks'
              : `ENGINEERING-CONSTRAINED — not flight-qualified · ${NOT_OPTIMAL}`
        }
        testId="metric-validity"
      />
    </div>
  );
}

interface DeltaRow {
  label: string;
  q: Quantity;
  get: (m: Metrics) => number | null | undefined;
  direction?: 'lower' | 'higher';
}
const ROWS: DeltaRow[] = [
  { label: 'Length used', q: 'mm', get: (m) => m.length_used_mm },
  { label: 'Balance error', q: 'mm', get: (m) => m.com_error_mm },
  { label: 'Rotational inertia (worst axis)', q: 'kgm2', get: (m) => m.lambda_max_kgm2 },
  { label: 'Inertia trace', q: 'kgm2', get: (m) => m.trace_kgm2 },
  { label: 'Total mass', q: 'kg', get: (m) => m.mass_kg },
];

export function deltaRows(prev: Layout | null, cur: Layout | null) {
  if (!prev?.metrics || !cur?.metrics) return [];
  return ROWS.map((r) => {
    const a = r.get(prev.metrics!);
    const b = r.get(cur.metrics!);
    const d = a != null && b != null ? b - a : null;
    return { label: r.label, ...fmtDelta(d, r.q, r.direction ?? 'lower') };
  });
}

/** "What changed" — signed deltas with words between the previous and current validated layout. */
export function WhatChanged() {
  const prev = useApp((s) => s.solver.prevBest);
  const cur = useApp((s) => s.solver.best);
  const dm = useDisplayMetrics();
  const rows = deltaRows(prev, cur);
  return (
    <div>
      <div className="panel-head">
        <h2>What changed</h2>
        <span className="caption">{prev && cur ? `${prev.id} → ${cur.id}` : ''}</span>
        <div className="right">
          <MockTag />
        </div>
      </div>
      <div className="panel-body" data-testid="what-changed">
        {!rows.length ? (
          <div className="small muted">No earlier validated layout to compare with yet.</div>
        ) : (
          <table className="data">
            <tbody>
              {rows.map((r) => (
                <tr key={r.label}>
                  <td>{r.label}</td>
                  <td className={`num ${r.verdict === 'better' ? 'delta-better' : r.verdict === 'worse' ? 'delta-worse' : ''}`}>{r.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="small muted" style={{ marginTop: 6 }}>
          Score: {dm.scoresShown ? (cur?.scores?.g != null ? fmt(cur.scores.g, 'score') : '—') : 'updating…'} · {NOT_OPTIMAL}
        </div>
      </div>
    </div>
  );
}
