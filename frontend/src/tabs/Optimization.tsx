import { useMemo } from 'react';
import type uPlot from 'uplot';
import { session } from '../api/session';
import { useApp } from '../store/store';
import { useDisplayMetrics } from '../hooks';
import { GoalsPanel } from '../components/GoalsPanel';
import { AlgorithmChip } from '../components/AlgorithmChip';
import { UPlotChart, chartAxis } from '../components/charts/Charts';
import { Button, EmptyState, KV, MockTag, Panel } from '../components/ui';
import { fmt } from '../lib/fmt';
import { normalisedWeights } from '../lib/physics';
import { activeGoalSliders } from '../store/presets';
import { NOT_OPTIMAL } from '../lib/copy';

export function OptimizationTab() {
  const settings = useApp((s) => s.goals.settings);
  const best = useApp((s) => s.solver.best);
  const runStatus = useApp((s) => s.solver.runStatus);
  const detail = useApp((s) => s.solver.statusDetail);
  const progress = useApp((s) => s.solver.progress);
  const history = useApp((s) => s.solver.progressHistory);
  const log = useApp((s) => s.solver.log);
  const selector = useApp((s) => s.solver.selector);
  const expert = useApp((s) => s.view.expert);
  const dm = useDisplayMetrics();
  const stage = settings?.stage ?? 1;
  const active = activeGoalSliders(stage);
  const weights = settings ? normalisedWeights(settings.sliders, active) : null;
  const data = useMemo<uPlot.AlignedData>(() => {
    const pts = history.filter((h) => h.elapsed_s != null && h.best_g != null);
    return [pts.map((p) => p.elapsed_s as number), pts.map((p) => p.best_g as number)];
  }, [history]);
  const chartOpts = useMemo<Omit<uPlot.Options, 'width' | 'height'>>(
    () => ({
      scales: { x: { time: false } },
      series: [{ label: 'elapsed (s)' }, { label: 'best g', stroke: '#5D96F0', width: 1.5, points: { show: false } }],
      axes: [chartAxis('elapsed time (s)'), chartAxis('best scalarised score g (lower is better)')],
      legend: { show: true },
    }),
    [],
  );
  const searching = runStatus === 'SEARCHING' || runStatus === 'REVALIDATING';
  return (
    <div className="tab-scroll" data-testid="tab-optimization">
      <div className="grid-2">
        <section className="panel">
          <GoalsPanel showExpert />
        </section>
        <div className="stack">
          <Panel title="Exact weights" caption="w_k = (s_k + 1) / Σ(s_j + 1) over the active goals" right={<MockTag />}>
            {weights ? (
              <table className="data">
                <thead>
                  <tr>
                    <th>Goal</th>
                    <th className="num">Slider</th>
                    <th className="num">Weight</th>
                    <th className="num">Normalised gap f̂ (current layout)</th>
                  </tr>
                </thead>
                <tbody>
                  {active.map((k) => {
                    const key = k === 'space' ? 'L' : k === 'balance' ? 'D' : k === 'inertia' ? 'I' : 'G';
                    return (
                      <tr key={k}>
                        <td>{k}</td>
                        <td className="num">{settings!.sliders[k]}</td>
                        <td className="num">{fmt(weights[k], 'score')}</td>
                        <td className="num">{dm.scoresShown ? fmt(best?.scores?.normalised?.[key] ?? null, 'score') : 'updating…'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : null}
            <div className="small muted" style={{ marginTop: 6 }}>
              Normalisation epoch: {best?.scores?.norm_epoch ?? '—'} (utopia/nadir frozen per epoch; the same slider position always means the same thing within an epoch).
              Scalarisation: augmented weighted Tchebycheff, g = max_k w_k f̂_k + 10⁻³ Σ w_k f̂_k. Score g:{' '}
              {dm.scoresShown ? fmt(best?.scores?.g ?? null, 'score') : 'updating…'}
            </div>
          </Panel>
          <Panel title="Algorithm and run" caption={NOT_OPTIMAL}>
            <AlgorithmChip />
            <div style={{ marginTop: 8 }}>
              <KV
                rows={[
                  ['Layout algorithm', best?.algorithm ? `${best.algorithm.label}${best.algorithm.reason ? ` — ${best.algorithm.reason}` : ''}` : '—'],
                  ['Selector reasons', selector?.reasons?.join('; ') || '—'],
                  ['Seed', '— (not reported in the contract yet)'],
                  ['Budget', settings ? `speed ↔ quality ${settings.sliders.speed_quality} (compute budget only)` : '—'],
                  ['Status', `${runStatus}${detail ? ` — ${detail}` : ''}`],
                  ['Evaluations', fmt(progress?.evaluations ?? null, 'int')],
                  ['Elapsed', fmt(progress?.elapsed_s ?? null, 's')],
                ]}
              />
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <Button variant="primary" onClick={() => session().run('start')} disabled={searching}>
                Start
              </Button>
              <Button onClick={() => session().run('pause')} disabled={!searching}>
                Pause
              </Button>
              <Button onClick={() => session().run('resume')} disabled={runStatus !== 'PAUSED'}>
                Resume
              </Button>
              <Button onClick={() => session().run('rerun')}>Re-run with current parts</Button>
              <Button onClick={() => session().run('reset')}>Reset</Button>
            </div>
          </Panel>
        </div>
      </div>
      {expert ? (
        <Panel title="Convergence" caption="best scalarised score over time, from progress messages" right={<MockTag />}>
          {data[0].length > 1 ? (
            <UPlotChart options={chartOpts} data={data} ariaLabel="Convergence chart: best score against elapsed time" testId="convergence-chart" />
          ) : (
            <EmptyState title="No progress yet">Start the optimiser to see the convergence curve.</EmptyState>
          )}
        </Panel>
      ) : (
        <div className="notice info">Switch to Expert to see the convergence chart.</div>
      )}
      <Panel title="Generation log" caption="newest last">
        <ul className="log" aria-label="Generation log" data-testid="generation-log">
          {log.slice(-200).map((e, i) => (
            <li key={i}>
              {new Date(e.at).toLocaleTimeString()} [{e.kind}] {e.text}
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
