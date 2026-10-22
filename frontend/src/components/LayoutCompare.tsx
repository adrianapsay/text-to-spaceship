import { useEffect, useMemo, useState } from 'react';
import type { Layout, LayoutSummary, Metrics, Revs, Vec3 } from '../api/types';
import { session } from '../api/session';
import { displayKind, layoutCoverage, styleFor, type RenderItem } from '../api/protocol';
import { useApp } from '../store/store';
import { useAsync, useParts } from '../hooks';
import { fmt, fmtDelta, fmtVec, type Quantity } from '../lib/fmt';
import { DualViewport } from './viewport/DualViewport';
import { EmptyState, Notice } from './ui';

export function useLayoutList(status?: string, limit = 200) {
  const newest = useApp((s) => s.conn.newest);
  const bestId = useApp((s) => s.solver.best?.id);
  return useAsync(() => session().api.layouts({ status, limit }), [status, limit, newest.parts_rev, newest.constraint_rev, bestId]);
}

export function useFullLayout(id: string | null) {
  return useAsync(id ? () => session().api.layout(id) : null, [id]);
}

export function itemsFor(layout: Layout | null, newest: Revs): RenderItem[] {
  if (!layout) return [];
  const kind = displayKind(layout, newest, 'archive');
  return [{ layout, role: 'best', kind, style: styleFor(kind) }];
}

const METRIC_ROWS: { label: string; q: Quantity; get: (m: Metrics) => number | null | undefined }[] = [
  { label: 'Length used', q: 'mm', get: (m) => m.length_used_mm },
  { label: 'Span', q: 'mm', get: (m) => m.span_mm },
  { label: 'Space used', q: 'pct', get: (m) => m.space_used },
  { label: 'Balance error', q: 'mm', get: (m) => m.com_error_mm },
  { label: 'λ_max', q: 'kgm2', get: (m) => m.lambda_max_kgm2 },
  { label: 'Trace', q: 'kgm2', get: (m) => m.trace_kgm2 },
  { label: 'Products ‖P‖', q: 'kgm2', get: (m) => m.products_norm_kgm2 },
  { label: 'Tilt', q: 'deg', get: (m) => m.tilt_deg },
  { label: 'Min clearance', q: 'clearance', get: (m) => m.min_clearance_mm },
  { label: 'Total mass', q: 'kg', get: (m) => m.mass_kg },
];

export function MetricsDeltaTable(props: { a: Layout | null; b: Layout | null; labels: [string, string] }) {
  const { a, b } = props;
  return (
    <table className="data" data-testid="compare-table">
      <thead>
        <tr>
          <th>Metric</th>
          <th className="num">{props.labels[0]}</th>
          <th className="num">{props.labels[1]}</th>
          <th className="num">Δ (right − left)</th>
        </tr>
      </thead>
      <tbody>
        {METRIC_ROWS.map((r) => {
          const va = a?.metrics ? r.get(a.metrics) : null;
          const vb = b?.metrics ? r.get(b.metrics) : null;
          const d = fmtDelta(va != null && vb != null ? vb - va : null, r.q, r.label === 'Min clearance' ? 'higher' : 'lower');
          return (
            <tr key={r.label}>
              <td>{r.label}</td>
              <td className="num">{fmt(va ?? null, r.q)}</td>
              <td className="num">{fmt(vb ?? null, r.q)}</td>
              <td className={`num ${d.verdict === 'better' ? 'delta-better' : d.verdict === 'worse' ? 'delta-worse' : ''}`}>{r.label === 'Space used' || r.label === 'Total mass' ? fmt(va != null && vb != null ? vb - va : null, r.q, { signed: true }) : d.text}</td>
            </tr>
          );
        })}
        <tr>
          <td>COM</td>
          <td className="num">{fmtVec((a?.metrics?.com_mm as Vec3) ?? null)}</td>
          <td className="num">{fmtVec((b?.metrics?.com_mm as Vec3) ?? null)}</td>
          <td />
        </tr>
      </tbody>
    </table>
  );
}

function label(l: LayoutSummary) {
  return `${l.id} · stage ${l.stage} · ${l.status}${l.metrics?.length_used_mm != null ? ` · L ${l.metrics.length_used_mm.toFixed(1)} mm` : ''}`;
}

/** Pick any two archive layouts and compare them side by side (dual view + signed metric deltas). */
export function LayoutCompare(props: { defaultLeft?: string | null; defaultRight?: string | null; testId?: string; filter?: (l: LayoutSummary) => boolean }) {
  const list = useLayoutList();
  const newest = useApp((s) => s.conn.newest);
  const parts = useParts();
  const options = useMemo(() => (list.data ?? []).filter(props.filter ?? (() => true)), [list.data, props.filter]);
  const [left, setLeft] = useState<string | null>(props.defaultLeft ?? null);
  const [right, setRight] = useState<string | null>(props.defaultRight ?? null);
  useEffect(() => {
    if (!left && options.length > 1) setLeft(options[1].id);
    if (!right && options.length) setRight(options[0].id);
  }, [options, left, right]);
  const la = useFullLayout(left);
  const lb = useFullLayout(right);
  if (list.notAvailable) return <EmptyState title="No layout archive from the backend yet" />;
  if (list.error) return <Notice tone="err">{list.error}</Notice>;
  if (!options.length) return <EmptyState title="No layouts in the archive yet">Run the optimiser to fill the archive.</EmptyState>;
  const covA = la.data ? layoutCoverage(la.data, parts) : null;
  const covB = lb.data ? layoutCoverage(lb.data, parts) : null;
  return (
    <div className="stack" data-testid={props.testId}>
      <div className="row">
        <label className="row" style={{ gap: 4 }}>
          Left
          <select value={left ?? ''} onChange={(e) => setLeft(e.target.value || null)} aria-label="Left layout">
            {options.map((l) => (
              <option key={l.id} value={l.id}>
                {label(l)}
              </option>
            ))}
          </select>
        </label>
        <label className="row" style={{ gap: 4 }}>
          Right
          <select value={right ?? ''} onChange={(e) => setRight(e.target.value || null)} aria-label="Right layout">
            {options.map((l) => (
              <option key={l.id} value={l.id}>
                {label(l)}
              </option>
            ))}
          </select>
        </label>
        {covA?.missing.length ? <span className="badge warn">left does not include {covA.missing.map((p) => p.name).join(', ')}</span> : null}
        {covB?.missing.length ? <span className="badge warn">right does not include {covB.missing.map((p) => p.name).join(', ')}</span> : null}
      </div>
      <div style={{ height: 420, display: 'flex' }}>
        <DualViewport
          left={{ label: left ?? '—', items: itemsFor(la.data, newest), metrics: la.data?.metrics ?? null, stage: la.data?.stage ?? 1 }}
          right={{ label: right ?? '—', items: itemsFor(lb.data, newest), metrics: lb.data?.metrics ?? null, stage: lb.data?.stage ?? 1 }}
        />
      </div>
      <MetricsDeltaTable a={la.data} b={lb.data} labels={[left ?? 'left', right ?? 'right']} />
    </div>
  );
}
