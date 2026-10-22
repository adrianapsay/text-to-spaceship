import { useMemo, useState } from 'react';
import * as Plot from '@observablehq/plot';
import type { FidelityResult } from '../api/types';
import { session } from '../api/session';
import { useApp } from '../store/store';
import { useAsync } from '../hooks';
import { fmt } from '../lib/fmt';
import { algoColor } from '../lib/colors';
import { PlotFigure } from './charts/Charts';
import { Badge, Button, EmptyState, Notice } from './ui';

const STOP_TEXT: Record<string, string> = {
  converged: 'stopped: more detail no longer changed the result',
  time_budget: 'stopped: the next level would be too slow',
  max_level: 'stopped: most detailed level reached',
};

export interface FidelityPoint {
  algorithm: string;
  level: string;
  label: string;
  t_us: number;
  length_mm: number | null;
  frr_pct: number | null;
  chosen: boolean;
}

/** Flatten a detail-ladder result into one point per (algorithm, level), ordered by level. */
export function fidelityPoints(f: FidelityResult): FidelityPoint[] {
  const out: FidelityPoint[] = [];
  const algos = new Set<string>();
  for (const lv of f.levels) for (const a of Object.keys(lv.results ?? {})) algos.add(a);
  for (const a of [...algos].sort())
    for (const lv of f.levels) {
      const r = lv.results?.[a];
      if (!r || lv.eval_us_median == null) continue;
      out.push({
        algorithm: a,
        level: lv.level,
        label: lv.label,
        t_us: lv.eval_us_median,
        length_mm: r.length_used_mm,
        frr_pct: r.false_reject_rate != null ? r.false_reject_rate * 100 : null,
        chosen: f.chosen?.[a] === lv.level,
      });
    }
  return out;
}

export function FidelityPanel({ partId }: { partId: string }) {
  const run = useApp((s) => s.solver.fidelityRuns[partId]);
  const mode = useApp((s) => s.conn.mode);
  const res = useAsync(() => session().api.fidelity(partId), [partId, run?.status, run?.progress]);
  const f = res.data;
  const pts = useMemo(() => (f ? fidelityPoints(f) : []), [f]);
  const algos = [...new Set(pts.map((p) => p.algorithm))];
  const color = (a: string) => algoColor(a, algos);
  // one line per algorithm, one point per level; the chosen level is ringed and labelled
  const plotLen = useMemo(() => buildChart(pts, 'length_mm', '↑ best length used (mm)', algos, color), [pts]); // eslint-disable-line react-hooks/exhaustive-deps
  const plotFrr = useMemo(() => buildChart(pts, 'frr_pct', '↑ false-reject rate (%)', algos, color), [pts]); // eslint-disable-line react-hooks/exhaustive-deps
  const [runError, setRunError] = useState<string | null>(null);

  const rerun = async () => {
    setRunError(null);
    try {
      await session().api.runFidelity({ part_ids: [partId] });
    } catch (e) {
      setRunError((e as Error).message);
    }
    res.reload();
  };

  return (
    <section className="panel" data-testid="fidelity-panel" aria-labelledby="fid-h">
      <div className="panel-head">
        <h2 id="fid-h">Detail level</h2>
        <span className="caption">shape detail used by the search (validation always uses the full mesh)</span>
        <div className="right">
          {f ? <Badge tone={f.status === 'DONE' ? 'ok' : 'warn'}>{f.status}</Badge> : null}
          {f?.stop_reason ? <Badge tone="neutral">{STOP_TEXT[f.stop_reason] ?? f.stop_reason}</Badge> : null}
          {f?.mock || mode === 'mock' ? <Badge tone="mock">MOCK</Badge> : null}
          <Button size="small" onClick={rerun} data-testid="fidelity-rerun">
            Re-run detail study
          </Button>
        </div>
      </div>
      <div className="panel-body stack">
        {runError ? <Notice tone="err">Re-run failed: {runError}</Notice> : null}
        {res.notAvailable ? (
          <EmptyState title="No detail-level study from the backend yet">The backend has not published a detail ladder for this part.</EmptyState>
        ) : res.error ? (
          <Notice tone="err">{res.error}</Notice>
        ) : !f ? (
          <div className="muted small">Loading…</div>
        ) : f.status !== 'DONE' && !f.levels.length ? (
          <EmptyState title={f.status === 'PENDING' ? 'Detail study queued' : 'Detail study running'}>
            The ladder climbs from a bounding box to the full mesh, runs every algorithm at each level, and stops when more detail stops paying off.
          </EmptyState>
        ) : (
          <>
            {f.mock_note ? <Notice tone="warn">{f.mock_note}</Notice> : null}
            {f.status !== 'DONE' ? <Notice tone="info">Running — levels so far are shown; the choice is made when the ladder stops.</Notice> : null}
            <div className="grid-2">
              <PlotFigure options={plotLen} ariaLabel="Best length used against evaluation time, one line per algorithm, one point per detail level" testId="fidelity-chart-length" />
              <PlotFigure options={plotFrr} ariaLabel="False-reject rate against evaluation time, one line per algorithm" testId="fidelity-chart-frr" />
            </div>
            <table className="data" data-testid="fidelity-chosen">
              <thead>
                <tr>
                  <th>Algorithm</th>
                  <th>Chosen level</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {algos.map((a) => (
                  <tr key={a}>
                    <td>
                      <span className="swatch" style={{ background: color(a), display: 'inline-block', marginRight: 6 }} />
                      {a}
                    </td>
                    <td>
                      <strong>{f.chosen?.[a] ?? '—'}</strong> {f.levels.find((l) => l.level === f.chosen?.[a])?.label ?? ''}
                    </td>
                    <td className="small">{f.reasons?.[a] ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <details>
              <summary>Levels tested ({f.levels.length})</summary>
              <table className="data">
                <thead>
                  <tr>
                    <th>Level</th>
                    <th>Representation</th>
                    <th className="num">Proxy volume</th>
                    <th className="num">Overhead</th>
                    <th className="num">Build</th>
                    <th className="num">Eval (median)</th>
                  </tr>
                </thead>
                <tbody>
                  {f.levels.map((l) => (
                    <tr key={l.level}>
                      <td>{l.level}</td>
                      <td>{l.label}</td>
                      <td className="num">{fmt(l.proxy_volume_mm3, 'mm3')}</td>
                      <td className="num">{fmt(l.overhead, 'pct')}</td>
                      <td className="num">{fmt(l.build_s, 's')}</td>
                      <td className="num">{fmt(l.eval_us_median, 'us')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </>
        )}
      </div>
    </section>
  );
}

function buildChart(pts: FidelityPoint[], key: 'length_mm' | 'frr_pct', yLabel: string, algos: string[], color: (a: string) => string) {
  const data = pts.filter((p) => p[key] != null);
  return {
    height: 220,
    marginLeft: 56,
    marginRight: 20,
    x: { type: 'log' as const, label: 'evaluation time per query (µs, log) →', grid: true, tickFormat: '~g' },
    y: { label: yLabel, grid: true },
    color: { domain: algos, range: algos.map(color), legend: true },
    marks: [
      lineMark(data, key),
      dotMark(data, key, false),
      dotMark(
        data.filter((p) => p.chosen),
        key,
        true,
      ),
      textMark(
        data.filter((p) => p.chosen),
        key,
      ),
    ],
  };
}

function lineMark(data: FidelityPoint[], key: 'length_mm' | 'frr_pct') {
  return Plot.line(data, { x: 't_us', y: key, stroke: 'algorithm', z: 'algorithm', strokeWidth: 1.5 });
}
function dotMark(data: FidelityPoint[], key: 'length_mm' | 'frr_pct', chosen: boolean) {
  return chosen
    ? Plot.dot(data, { x: 't_us', y: key, stroke: 'currentColor', r: 7, strokeWidth: 2, fill: 'none' })
    : Plot.dot(data, { x: 't_us', y: key, fill: 'algorithm', r: 3, title: (d: FidelityPoint) => `${d.algorithm} · ${d.level} ${d.label}` });
}
function textMark(data: FidelityPoint[], key: 'length_mm' | 'frr_pct') {
  return Plot.text(data, { x: 't_us', y: key, text: (d: FidelityPoint) => `chosen ${d.level}`, dy: -12, fontWeight: 600 });
}
