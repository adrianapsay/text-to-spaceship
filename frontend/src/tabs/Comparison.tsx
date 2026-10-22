import { useMemo } from 'react';
import * as Plot from '@observablehq/plot';
import { session } from '../api/session';
import type { Benchmarks, Pareto } from '../api/types';
import { appStore, useApp } from '../store/store';
import { useAsync } from '../hooks';
import { LayoutCompare } from '../components/LayoutCompare';
import { PlotFigure } from '../components/charts/Charts';
import { Badge, Button, EmptyState, MockTag, Notice, Panel } from '../components/ui';
import { fmt } from '../lib/fmt';
import { algoColor } from '../lib/colors';

export function paretoOptions(p: Pareto, comLimitZ = 70): Plot.PlotOptions {
  const pts = p.points.filter((x) => Number.isFinite(x.L) && Number.isFinite(x.D));
  return {
    height: 300,
    marginLeft: 56,
    grid: true,
    x: { label: 'length used L (mm) →' },
    y: { label: '↑ balance error D (mm)' },
    color: { type: 'linear', label: 'inertia I (kg·m²)', legend: true, scheme: 'viridis' },
    marks: [
      Plot.ruleY([comLimitZ], { stroke: 'currentColor', strokeDasharray: '4 3' }),
      Plot.text([comLimitZ], { x: () => Math.max(...pts.map((d) => d.L)), y: (d: number) => d, text: () => `±${comLimitZ} mm (CDS z limit)`, textAnchor: 'end', dy: -6 }),
      Plot.dot(pts, { x: 'L', y: 'D', fill: 'I', r: 4, stroke: 'currentColor', strokeWidth: 0.5, title: (d: { layout_id: string; L: number; D: number; I: number }) => `${d.layout_id}: L ${d.L.toFixed(1)} mm, D ${d.D.toFixed(1)} mm, I ${d.I.toExponential(2)}` }),
    ],
  };
}

function StripPlots({ b }: { b: Benchmarks }) {
  const rows = b.rows ?? [];
  const algos = [...new Set(rows.map((r) => r.algorithm))];
  const opts = useMemo(
    () =>
      (['L', 'D'] as const).map((k) => ({
        height: 40 + algos.length * 28,
        marginLeft: 160,
        x: { label: k === 'L' ? 'length used L (mm) →' : 'balance error D (mm) →', grid: true },
        y: { label: null },
        color: { domain: algos, range: algos.map((a) => algoColor(a, algos)) },
        marks: [
          Plot.dot(rows.filter((r) => r[k] != null), { x: k, y: 'algorithm', fill: 'algorithm', r: 3.5, title: (r: { seed: number }) => `seed ${r.seed}` }),
          Plot.tickX(rows.filter((r) => r[k] != null), Plot.groupY({ x: 'median' }, { x: k, y: 'algorithm', stroke: 'currentColor', strokeWidth: 2 })),
        ],
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [b],
  );
  if (!rows.length) return <EmptyState title="No benchmark rows yet" />;
  return (
    <div className="grid-2">
      <PlotFigure options={opts[0]} ariaLabel="Length used over seeds per algorithm (dots), median tick" testId="strip-L" />
      <PlotFigure options={opts[1]} ariaLabel="Balance error over seeds per algorithm (dots), median tick" testId="strip-D" />
    </div>
  );
}

function AnytimeCurves({ b }: { b: Benchmarks }) {
  const curves = b.curves ?? {};
  const data = Object.entries(curves).flatMap(([alg, c]) => c.t.map((t, i) => ({ alg, t, median: c.median[i], q1: c.q1[i], q3: c.q3[i] })));
  const algos = Object.keys(curves);
  const opts = useMemo(
    () => ({
      height: 260,
      marginLeft: 56,
      grid: true,
      x: { label: 'time (s) →' },
      y: { label: '↑ best g (median, IQR band)' },
      color: { domain: algos, range: algos.map((a) => algoColor(a, algos)), legend: true },
      marks: [Plot.areaY(data, { x: 't', y1: 'q1', y2: 'q3', fill: 'alg', fillOpacity: 0.2 }), Plot.line(data, { x: 't', y: 'median', stroke: 'alg' })],
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [b],
  );
  if (!data.length) return <EmptyState title="No anytime curves yet" />;
  return <PlotFigure options={opts} ariaLabel="Median and inter-quartile anytime curves per algorithm" testId="anytime-curves" />;
}

export function FidelitySummaryTable() {
  const fid = useApp((s) => s.solver.fidelityRuns);
  const res = useAsync(() => session().api.fidelitySummary(), [Object.values(fid).map((f) => f.status).join(',')]);
  if (res.notAvailable) return <EmptyState title="No detail-level summary from the backend yet" />;
  if (res.error) return <Notice tone="err">{res.error}</Notice>;
  const parts = res.data?.parts ?? [];
  const algos = [...new Set(parts.flatMap((p) => Object.keys(p.chosen ?? {})))].sort();
  if (!parts.length) return <EmptyState title="No detail-level studies have finished yet" />;
  return (
    <div className="table-wrap" style={{ maxHeight: 360 }}>
      <table className="data" data-testid="fidelity-summary">
        <thead>
          <tr>
            <th>Part</th>
            {algos.map((a) => (
              <th key={a}>{a}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {parts.map((p) => (
            <tr key={p.part_id}>
              <td>{p.name}</td>
              {algos.map((a) => (
                <td key={a}>{p.chosen?.[a] ?? '—'}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {res.data?.mock ? <div className="small muted">MOCK — illustrative chosen levels, not measured.</div> : null}
    </div>
  );
}

export function ComparisonTab() {
  const bests = useApp((s) => s.solver.best?.id);
  const bench = useAsync(() => session().api.benchmarks(), []);
  const pareto = useAsync(() => session().api.pareto(), [bests]);
  const limits = useApp((s) => s.dataset.project?.limits);
  const box = (limits?.com_box_mm as number[] | undefined) ?? [20, 20, 70];
  const runBench = async () => {
    try {
      await session().api.runBenchmarks();
      bench.reload();
    } catch (e) {
      alertish((e as Error).message);
    }
  };
  return (
    <div className="tab-scroll" data-testid="tab-comparison">
      <Panel title="Side by side" caption="any two layouts from the archive; linked cameras; movement overlay">
        <LayoutCompare testId="comparison-compare" />
      </Panel>
      <div className="grid-2">
        <Panel title="Pareto front (validated archive)" caption="length vs balance error, coloured by inertia — Best trade-offs found — approximate" right={<MockTag />}>
          {pareto.notAvailable ? (
            <EmptyState title="No Pareto data from the backend yet" />
          ) : pareto.error ? (
            <Notice tone="err">{pareto.error}</Notice>
          ) : pareto.data && pareto.data.points.length ? (
            <>
              <PlotFigure options={paretoOptions(pareto.data, box[2])} ariaLabel="Pareto scatter: length used against balance error, colour = inertia" testId="pareto-scatter" />
              <div className="small muted">
                {pareto.data.points.length} points · hypervolume {pareto.data.hv == null ? '—' : fmt(pareto.data.hv, 'ratio')} · normalisation epoch {pareto.data.norm_epoch ?? '—'}
              </div>
            </>
          ) : (
            <EmptyState title="No points yet" />
          )}
        </Panel>
        <Panel title="Hypervolume / IGD+" caption="from the benchmark protocol">
          {bench.data?.hv_table?.length ? (
            <table className="data">
              <thead>
                <tr>
                  <th>Algorithm</th>
                  <th className="num">HV</th>
                  <th className="num">IGD+</th>
                  <th className="num">n</th>
                </tr>
              </thead>
              <tbody>
                {bench.data.hv_table.map((r) => (
                  <tr key={r.algorithm}>
                    <td>{r.algorithm}</td>
                    <td className="num">{fmt(r.hv, 'ratio')}</td>
                    <td className="num">{fmt(r.igd_plus ?? null, 'ratio')}</td>
                    <td className="num">{fmt(r.n ?? null, 'int')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState title="No benchmark results yet" action={<Button onClick={runBench}>Run benchmarks</Button>}>
              {bench.notAvailable ? 'The backend has not published benchmark results.' : bench.error ?? ''}
            </EmptyState>
          )}
        </Panel>
      </div>
      <Panel title="Seeds per algorithm" caption="strip plots (dots = seeds, tick = median)">
        {bench.data ? <StripPlots b={bench.data} /> : <EmptyState title="No benchmark results yet">{bench.notAvailable ? 'Benchmarks run in the backend (milestone M8).' : bench.error ?? ''}</EmptyState>}
      </Panel>
      <Panel title="Anytime curves" caption="median and inter-quartile range over seeds">
        {bench.data ? <AnytimeCurves b={bench.data} /> : <EmptyState title="No benchmark results yet" />}
      </Panel>
      <Panel title="Chosen detail level per part and algorithm" caption="from the detail-ladder study (Addendum 4)" right={<Badge tone="neutral">GET /api/fidelity/summary</Badge>}>
        <FidelitySummaryTable />
      </Panel>
    </div>
  );
}

function alertish(msg: string) {
  // surfaced through the live region rather than a blocking alert
  appStore.getState().announce(`Benchmark run failed: ${msg}`);
}
