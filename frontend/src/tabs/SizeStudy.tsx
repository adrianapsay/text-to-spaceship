import { useEffect, useMemo, useState } from 'react';
import * as Plot from '@observablehq/plot';
import { session } from '../api/session';
import type { Layout, SizeStudy } from '../api/types';
import { useApp } from '../store/store';
import { useAsync } from '../hooks';
import { PlotFigure } from '../components/charts/Charts';
import { ThumbGrid } from '../components/viewport/ThumbGrid';
import { Badge, Button, EmptyState, MockTag, Notice, Panel } from '../components/ui';
import { fmt } from '../lib/fmt';
import { algoColor } from '../lib/colors';

export const STOP_REASON_TEXT: Record<string, { text: string; tone: 'ok' | 'neutral' | 'warn' }> = {
  proven_optimal: { text: 'Ended: proven optimal (matches a proven lower bound at every size)', tone: 'ok' },
  converged: { text: 'Ended: no further improvement found (30 min without improvement)', tone: 'neutral' },
  time_limit: { text: 'Ended: 6-hour limit reached', tone: 'warn' },
};

export function sizeChartOptions(s: SizeStudy, enclosureLength = 340.5): Plot.PlotOptions {
  const rows = (s.results ?? []).filter((r) => r.feasible && r.length_used_mm != null);
  const algos = [...new Set((s.results ?? []).map((r) => r.algorithm))];
  const scales = (s.results ?? []).map((r) => r.scale);
  const sMin = Math.min(1, ...scales);
  const sMax = Math.max(1.05, ...scales);
  const marks: Plot.Markish[] = [
    Plot.ruleY([enclosureLength], { stroke: 'currentColor', strokeDasharray: '6 3' }),
    Plot.text([enclosureLength], { x: sMin, y: (d: number) => d, text: () => `3U length ${enclosureLength} mm`, textAnchor: 'start', dy: -6 }),
    Plot.line(rows, { x: 'scale', y: 'length_used_mm', stroke: 'algorithm', z: 'algorithm', marker: 'circle' }),
  ];
  for (const b of s.bounds ?? []) {
    if (b.coeff_mm != null) {
      const e = b.exponent ?? 3;
      const pts = Array.from({ length: 40 }, (_, i) => {
        const x = sMin + ((sMax - sMin) * i) / 39;
        return { x, y: b.coeff_mm! * x ** e };
      });
      marks.push(Plot.line(pts, { x: 'x', y: 'y', stroke: 'currentColor', strokeDasharray: '2 3' }));
      marks.push(Plot.text([pts[pts.length - 1]], { x: 'x', y: 'y', text: () => b.label, textAnchor: 'end', dy: -6 }));
    }
    if (b.max_scale != null) {
      marks.push(Plot.ruleX([b.max_scale], { stroke: 'currentColor', strokeDasharray: '4 4' }));
      marks.push(Plot.text([b.max_scale], { x: (d: number) => d, y: enclosureLength, text: () => b.label, rotate: -90, textAnchor: 'start', dx: -6 }));
    }
  }
  return {
    height: 320,
    marginLeft: 56,
    grid: true,
    x: { label: 'scale factor s →' },
    y: { label: '↑ length used (mm)' },
    color: { domain: algos, range: algos.map((a) => algoColor(a, algos)), legend: true },
    marks,
  };
}

function useLayouts(ids: string[]) {
  const [map, setMap] = useState<Record<string, Layout>>({});
  const key = ids.join(',');
  useEffect(() => {
    let alive = true;
    Promise.all(ids.map((id) => session().api.layout(id).then((l) => [id, l] as const, () => null))).then((res) => {
      if (!alive) return;
      setMap(Object.fromEntries(res.filter(Boolean) as [string, Layout][]));
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return map;
}

export function SizeStudyTab() {
  const study = useApp((s) => s.solver.studies.size);
  const res = useAsync(() => session().api.sizeStudy(), [study?.at]);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const s = res.data;
  const winners = s?.winners ?? [];
  const thumbs = useLayouts(winners.map((w) => w.layout_id).filter(Boolean) as string[]);
  const algos = useMemo(() => [...new Set((s?.results ?? []).map((r) => r.algorithm))], [s]);
  const chart = useMemo(() => (s ? sizeChartOptions(s) : null), [s]);
  const run = async () => {
    setRunMsg(null);
    try {
      await session().api.runSizeStudy({});
      setRunMsg('Size Study started; results stream in as they are found.');
      res.reload();
    } catch (e) {
      setRunMsg(`Could not start the Size Study: ${(e as Error).message}`);
    }
  };
  const stop = s?.stop_reason ? STOP_REASON_TEXT[s.stop_reason] ?? { text: `Ended: ${s.stop_reason}`, tone: 'neutral' as const } : null;
  return (
    <div className="tab-scroll" data-testid="tab-size">
      <Panel
        title="Size Study"
        caption="every part scaled uniformly (geometry s, mass s³, inertia s⁵); hardware is not scaled"
        right={
          <>
            {stop ? (
              <Badge tone={stop.tone}>
                <span data-testid="stop-reason">{stop.text}</span>
              </Badge>
            ) : null}
            <MockTag />
            <Button variant="primary" onClick={run} data-testid="size-run">
              Run Size Study
            </Button>
          </>
        }
      >
        {runMsg ? <Notice tone={runMsg.startsWith('Could not') ? 'err' : 'info'}>{runMsg}</Notice> : null}
        {study ? <div className="small muted">Progress: {fmt((study.progress ?? 0) * 100, 'pct100')}</div> : null}
        {res.notAvailable || !s ? (
          <EmptyState title="No Size Study results yet">
            {res.notAvailable ? 'The backend has not published Size Study results. ' : res.error ?? ''}The study scales every part in steps of 5 % until no algorithm finds a valid layout, then bisects the
            last step to 0.5 %. It runs for up to 6 hours, or stops earlier when the result is proven optimal or stops improving.
          </EmptyState>
        ) : (
          <div className="stack">
            {chart ? <PlotFigure options={chart} ariaLabel="Length used against scale factor, one line per algorithm, with bounds" testId="size-chart" /> : null}
            <div>
              <div className="small muted">Winner per size (most compact valid layout)</div>
              <div className="row" style={{ gap: 2 }} data-testid="winner-strip">
                {winners.map((w) => (
                  <div key={w.scale} title={`×${w.scale.toFixed(2)}: ${w.algorithm}`} style={{ textAlign: 'center' }}>
                    <div style={{ width: 44, height: 14, background: algoColor(w.algorithm, algos), border: '1px solid var(--border)' }} />
                    <div className="small num">{fmt(w.scale, 'scale')}</div>
                  </div>
                ))}
              </div>
            </div>
            <table className="data" style={{ width: 'auto' }}>
              <thead>
                <tr>
                  <th>Algorithm</th>
                  <th className="num">Largest size with a layout found</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(s.max_scale ?? {}).map(([a, v]) => (
                  <tr key={a}>
                    <td>
                      <span className="swatch" style={{ display: 'inline-block', marginRight: 6, background: algoColor(a, algos) }} />
                      {a}
                    </td>
                    <td className="num">{fmt(v, 'scale')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {winners.length ? (
              <ThumbGrid entries={winners.map((w) => ({ key: String(w.scale), title: `${fmt(w.scale, 'scale')} · ${w.algorithm}`, layout: w.layout_id ? thumbs[w.layout_id] ?? null : null }))} />
            ) : null}
            <details>
              <summary>Full results table</summary>
              <table className="data">
                <thead>
                  <tr>
                    <th className="num">Scale</th>
                    <th>Algorithm</th>
                    <th className="num">Length used</th>
                    <th>Feasible</th>
                    <th className="num">Balance error</th>
                    <th className="num">λ_max</th>
                    <th className="num">Seed</th>
                  </tr>
                </thead>
                <tbody>
                  {(s.results ?? []).map((r, i) => (
                    <tr key={i}>
                      <td className="num">{fmt(r.scale, 'scale')}</td>
                      <td>{r.algorithm}</td>
                      <td className="num">{fmt(r.length_used_mm, 'mm')}</td>
                      <td>{r.feasible ? 'yes' : 'no layout found'}</td>
                      <td className="num">{fmt(r.com_error_mm ?? null, 'mm')}</td>
                      <td className="num">{fmt(r.lambda_max_kgm2 ?? null, 'kgm2')}</td>
                      <td className="num">{r.seed ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </div>
        )}
      </Panel>
    </div>
  );
}
