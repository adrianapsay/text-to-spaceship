import { useMemo, useState } from 'react';
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

function BenchmarkStats({ b, block, setBlock }: { b: Benchmarks; block: string; setBlock: (v: string) => void }) {
  const ext = b as Benchmarks & BenchExtras;
  const tests = ext.tests ?? [];
  const label = (id: string) => ext.algorithms?.find((a) => a.id === id)?.label ?? id;
  return (
    <div className="stack" data-testid="bench-stats">
      <div className="row">
        <label className="small" htmlFor="bench-block">
          Instance and preset
        </label>{' '}
        <select id="bench-block" value={block} onChange={(e) => setBlock(e.target.value)} data-testid="bench-block">
          {(ext.blocks ?? []).map((k) => (
            <option key={k} value={k}>
              {k.replace('|', ' · ')}
            </option>
          ))}
        </select>
        <span className="small muted">
          budget {fmt(ext.budget ?? null, 'int')} decode-equivalents · {ext.seeds ?? '—'} seeds · {ext.validation ? `${ext.validation.validated_outputs}/${ext.validation.runs} best layouts re-validated, ${ext.validation.invalid_outputs} invalid` : ''}
        </span>
      </div>
      {ext.adoption ? <Notice tone={ext.adoption.ships_as_default ? 'ok' : 'warn'}>Adoption rule (§D.4): {ext.adoption.text}.</Notice> : null}
      {tests.length ? (
        <table className="data" data-testid="bench-tests">
          <thead>
            <tr>
              <th>Full hybrid vs</th>
              <th className="num">A12 (95 % CI)</th>
              <th className="num">p (Holm)</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {tests.map((t) => (
              <tr key={t.b}>
                <td>{label(t.b)}</td>
                <td className="num">
                  {fmt(t.a12, 'ratio')} ({fmt(t.a12_ci[0], 'ratio')}–{fmt(t.a12_ci[1], 'ratio')})
                </td>
                <td className="num">{fmt(t.p_holm, 'ratio')}</td>
                <td>{t.verdict === 'inconclusive' ? <Badge>inconclusive</Badge> : t.verdict === 'hybrid better' ? <Badge tone="ok">hybrid better</Badge> : <Badge tone="err">hybrid worse</Badge>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <div className="small muted">A12 = probability that the full hybrid scores better than the other variant on a seed; with 10 seeds, non-significant differences are reported as inconclusive, not as equivalent.</div>
    </div>
  );
}

interface BenchExtras {
  blocks?: string[];
  block?: { instance: string; preset: string };
  budget?: number;
  seeds?: number;
  validation?: { runs: number; validated_outputs: number; invalid_outputs: number };
  adoption?: { ships_as_default: boolean; text: string };
  tests?: { b: string; a12: number; a12_ci: [number, number]; p_holm: number; verdict: string }[];
}

export function ComparisonTab() {
  const bests = useApp((s) => s.solver.best?.id);
  const [block, setBlock] = useState('I1|balanced');
  const bench = useAsync(() => session().api.benchmarks(block), [block]);
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
      {bench.data && bench.data.status === 'DONE' ? (
        <Panel title="Benchmark statistics" caption="paired tests per instance and preset (protocol §J.3)">
          <BenchmarkStats b={bench.data} block={block} setBlock={setBlock} />
        </Panel>
      ) : null}
      <Panel title="Seeds per algorithm" caption="strip plots (dots = seeds, tick = median)">
        {bench.data ? <StripPlots b={bench.data} /> : <EmptyState title="No benchmark results yet">{bench.notAvailable ? 'Benchmarks run in the backend (milestone M8).' : bench.error ?? ''}</EmptyState>}
      </Panel>
      <Panel title="Anytime curves" caption="median and inter-quartile range over seeds">
        {bench.data ? <AnytimeCurves b={bench.data} /> : <EmptyState title="No benchmark results yet" />}
      </Panel>
      <Panel title="Chosen detail level per part and algorithm" caption="from the detail-ladder study (Addendum 4)" right={<Badge tone="neutral">GET /api/fidelity/summary</Badge>}>
        <FidelitySummaryTable />
      </Panel>
      <Panel title="Free-rotation experiment (Stage 1, research)" caption="reported separately — the main search and every other tab use the 24 axis-aligned orientations">
        <FreeRotationPanel />
      </Panel>
    </div>
  );
}

function FreeRotationPanel() {
  const study = useApp((s) => s.solver.studies.free_rotation);
  const res = useAsync(() => session().api.freeRotation(), [study?.at]);
  const [msg, setMsg] = useState<string | null>(null);
  const r = res.data;
  const run = async () => {
    setMsg(null);
    try {
      await session().api.runFreeRotation({ budget_s: 120 });
      setMsg('Started (about 2 minutes).');
      res.reload();
    } catch (e) {
      setMsg(`Could not start: ${(e as Error).message}`);
    }
  };
  return (
    <div data-testid="free-rotation">
      <div className="row">
        <Button onClick={run} disabled={r?.status === 'RUNNING'} data-testid="free-rotation-run">
          Run free-rotation experiment
        </Button>
        {r?.status === 'RUNNING' ? <span className="small muted">running…</span> : null}
        {msg ? <span className="small">{msg}</span> : null}
      </div>
      {r && r.status === 'DONE' ? (
        <div className="small" style={{ marginTop: 8 }} data-testid="free-rotation-result">
          <div>
            {r.valid ? <Badge tone="ok">checked on the meshes</Badge> : <Badge tone="err">final check failed</Badge>} Start {r.start_layout_id}: {fmt(r.start_length_mm ?? null, 'mm')} → with free rotations{' '}
            <strong>{fmt(r.length_used_mm ?? null, 'mm')}</strong> (shorter by {fmt(r.improvement_mm ?? null, 'mm')})
          </div>
          <div className="muted" style={{ marginTop: 4 }}>
            {r.accepted_moves} moves kept in {r.rounds} rounds · {r.exact_checks} exact pair checks · {fmt(r.seconds ?? null, 's')} · minimum distance {fmt(r.min_distance_mm ?? null, 'clearance')}
          </div>
          {r.rotated?.length ? (
            <table className="data" style={{ marginTop: 6 }}>
              <thead>
                <tr>
                  <th>Part</th>
                  <th className="num">Turned away from axis-aligned by</th>
                </tr>
              </thead>
              <tbody>
                {r.rotated.map((x) => (
                  <tr key={x.part_id}>
                    <td>{x.name ?? x.part_id}</td>
                    <td className="num">{fmt(x.angle_deg, 'deg')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="muted">No part ended at a non-axis-aligned orientation.</div>
          )}
          <div className="muted" style={{ marginTop: 4 }}>Method: {r.method}</div>
        </div>
      ) : r?.status === 'ERROR' ? (
        <Notice tone="err">{r.detail}</Notice>
      ) : !r ? (
        <EmptyState title="Not run yet">Starts from the shortest validated axis-aligned Stage 1 layout and tries arbitrary rotations of the parts that set the length; every kept pose is checked on the meshes.</EmptyState>
      ) : null}
    </div>
  );
}

function alertish(msg: string) {
  // surfaced through the live region rather than a blocking alert
  appStore.getState().announce(`Benchmark run failed: ${msg}`);
}
