import { useMemo } from 'react';
import { renderPlan, isCurrent, layoutCoverage } from '../api/protocol';
import { session } from '../api/session';
import { useApp } from '../store/store';
import { useDisplayMetrics, useParts } from '../hooks';
import { MainViewport } from '../components/viewport/Viewport';
import { GoalsPanel } from '../components/GoalsPanel';
import { HardwareItemsList, PartInspector, PartsList } from '../components/PartsPanel';
import { MetricStrip, WhatChanged } from '../components/Metrics';
import { Badge, Button } from '../components/ui';
import { NOT_OPTIMAL } from '../lib/copy';

export function RerunBar() {
  const best = useApp((s) => s.solver.best);
  const newest = useApp((s) => s.conn.newest);
  const parts = useParts();
  const runStatus = useApp((s) => s.solver.runStatus);
  if (!best) return null;
  const cov = layoutCoverage(best, parts);
  const partsChanged = best.parts_rev < newest.parts_rev || cov.missing.length > 0 || cov.removed.length > 0;
  if (!partsChanged) return null;
  return (
    <div className="notice info row" style={{ margin: 0 }} data-testid="rerun-bar">
      <span>
        The parts changed since this layout was validated
        {cov.missing.length ? ` (does not include ${cov.missing.map((p) => p.name).join(', ')})` : ''}.
      </span>
      <Button variant="primary" size="small" onClick={() => session().run('rerun')} disabled={runStatus === 'SEARCHING'} data-testid="rerun">
        Re-run
      </Button>
    </div>
  );
}

export function OverviewTab() {
  const solver = useApp((s) => s.solver);
  const newest = useApp((s) => s.conn.newest);
  const expert = useApp((s) => s.view.expert);
  const showGhost = useApp((s) => s.view.showGhost);
  const dm = useDisplayMetrics();
  const items = useMemo(() => renderPlan(solver, newest, { expert, showGhost }), [solver, newest, expert, showGhost]);
  const best = solver.best;
  return (
    <div className="overview" data-testid="tab-overview">
      <aside className="left" aria-label="Parts and physical properties">
        <PartsList />
        <HardwareItemsList />
        <PartInspector />
      </aside>
      <section className="centre" aria-label="3D view">
        <div className="vp-head">
          <strong>{best ? (isCurrent(best, newest) && best.status !== 'STALE' ? 'BEST VALIDATED' : 'LAST VALIDATED') : 'NO LAYOUT'}</strong>
          {best ? <span className="num">{best.id}</span> : null}
          {best?.algorithm ? <span className="muted">· {best.algorithm.label}</span> : null}
          {best ? <Badge tone="neutral">{best.stage === 2 ? 'ENGINEERING-CONSTRAINED' : 'IDEALIZED'}</Badge> : null}
          <span className="muted small">{NOT_OPTIMAL}</span>
        </div>
        <RerunBar />
        <MainViewport items={items} metrics={dm.metrics} prevLayout={solver.prevBest} testId="overview-viewport" />
      </section>
      <aside className="right" aria-label="Goals">
        <GoalsPanel />
        <WhatChanged />
      </aside>
      <div className="metrics">
        <MetricStrip />
      </div>
    </div>
  );
}
