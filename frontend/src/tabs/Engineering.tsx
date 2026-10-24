import { useMemo, useState } from 'react';
import type { LayoutSummary, Metrics, Vec3 } from '../api/types';
import { session } from '../api/session';
import { useApp } from '../store/store';
import { useAsync, useParts } from '../hooks';
import { itemsFor, MetricsDeltaTable, useFullLayout, useLayoutList } from '../components/LayoutCompare';
import { DualViewport } from '../components/viewport/DualViewport';
import { Badge, Button, EmptyState, MockTag, Notice, Panel } from '../components/ui';
import { fmt } from '../lib/fmt';
import { DISCLAIMER_STAGE2 } from '../lib/copy';
import { minutesText } from '../lib/runTime';

export interface Check {
  name: string;
  value: string;
  limit: string;
  margin: string;
  pass: boolean | null;
}

/** Checks table rows from a Stage 2 layout's metrics (backend verdicts; nothing is re-derived here). */
export function stage2Checks(m: Metrics | null, limits: Record<string, unknown>): Check[] {
  if (!m) return [];
  const box = (limits.com_box_mm as Vec3 | undefined) ?? [20, 20, 70];
  const cPart = (limits.clearance_part_mm as number | undefined) ?? 2.2;
  const com = (m.com_mm as Vec3 | null) ?? null;
  const out: Check[] = [];
  (['x', 'y', 'z'] as const).forEach((ax, k) => {
    const v = com ? Math.abs(com[k]) : null;
    out.push({
      name: `COM |${ax}| (CDS box, HARD)`,
      value: fmt(v, 'mm'),
      limit: `≤ ${fmt(box[k], 'mm')}`,
      margin: fmt(m.com_box_margin_mm?.[k] ?? (v != null ? box[k] - v : null), 'mm'),
      pass: m.com_box_margin_mm ? m.com_box_margin_mm[k] >= 0 : v != null ? v <= box[k] : null,
    });
  });
  out.push({
    name: 'Minimum certified clearance (slack beyond required)',
    value: fmt(m.min_clearance_mm ?? null, 'clearance'),
    limit: `part–part ${fmt(cPart, 'clearance')} / part–wall ${fmt((limits.clearance_wall_mm as number | undefined) ?? 1.2, 'clearance')} required`,
    margin: '—',
    pass: m.min_clearance_mm == null ? null : m.min_clearance_mm >= 0,
  });
  out.push({
    name: 'Insertion order along ±Z',
    value: m.insertion_order ? `${m.insertion_order.length} steps` : '—',
    limit: 'every part insertable',
    margin: m.interlocked?.length ? `${m.interlocked.length} interlocked pair(s)` : '—',
    pass: m.insertion_order ? !(m.interlocked && m.interlocked.length) : null,
  });
  out.push({
    name: 'Cable channel blocked fraction',
    value: fmt(m.cable_blocked_fraction ?? null, 'pct'),
    limit: 'objective (hard 0 % in continuous-cable mode)',
    margin: '—',
    pass: null,
  });
  return out;
}

function latest(list: LayoutSummary[] | null, pred: (l: LayoutSummary) => boolean): LayoutSummary | null {
  const c = (list ?? []).filter((l) => (l.status === 'VALIDATED' || l.status === 'FINAL') && pred(l));
  c.sort((a, b) => ((a.created ?? '') < (b.created ?? '') ? 1 : -1));
  return c[0] ?? null;
}

export function cableMode(v: number, threshold = 70): { mode: string; text: string } {
  if (v <= 0) return { mode: 'Default', text: 'channel interrupted across the PCB stack; wiring ASSUMED through the PC/104 stack bus' };
  if (v < threshold) return { mode: 'Soft', text: 'blocked channel length is a weighted objective' };
  return { mode: 'Continuous-cable', text: 'full-length channel is a HARD keep-out; channel wall is a search variable; edge-mounted boards only with validated card guides or standoffs' };
}

export function EngineeringTab() {
  const project = useApp((s) => s.dataset.project);
  const settings = useApp((s) => s.goals.settings);
  const runStatus = useApp((s) => s.solver.runStatus);
  const detail = useApp((s) => s.solver.statusDetail);
  const progress = useApp((s) => s.solver.progress);
  const newest = useApp((s) => s.conn.newest);
  const parts = useParts();
  const list = useLayoutList();
  const infeasible = useApp((s) => s.solver.infeasible);
  const s1 = latest(list.data, (l) => l.stage === 1);
  const s2v = latest(list.data, (l) => l.stage === 2);
  // no feasible Stage 2 layout yet: compare against the least-violating certified candidate (labelled)
  const s2 = s2v ?? (infeasible && infeasible.stage === 2 ? (infeasible as unknown as LayoutSummary) : null);
  const s2default = latest(list.data, (l) => l.stage === 2 && (l.mode ?? 'default') === 'default');
  const s2cable = latest(list.data, (l) => l.stage === 2 && l.mode === 'continuous_cable');
  const a = useFullLayout(s1?.id ?? null);
  const b = useFullLayout(s2?.id ?? null);
  const limits = project?.limits ?? {};
  const frame = project?.stage2_frame;
  const checks = useMemo(() => stage2Checks(b.data?.metrics ?? null, limits), [b.data, limits]);
  const threshold = (limits.cable_mode_threshold as number | undefined) ?? 70;
  const cm = cableMode(settings?.sliders.cable ?? 0, threshold);
  const dL = s2default?.metrics?.length_used_mm != null && s2cable?.metrics?.length_used_mm != null ? s2cable.metrics.length_used_mm - s2default.metrics.length_used_mm : null;
  const dD = s2default?.metrics?.com_error_mm != null && s2cable?.metrics?.com_error_mm != null ? s2cable.metrics.com_error_mm - s2default.metrics.com_error_mm : null;
  // the search never stops on its own (V2): with no feasible Stage 2 layout yet, say for how long it has searched
  const searchedNothing =
    (settings?.stage === 2 && !s2v && !!infeasible) || (settings?.stage === 2 && !s2 && (progress?.evaluations ?? 0) > 0);
  const searchedFor = progress?.elapsed_s != null && Number.isFinite(progress.elapsed_s) ? ` after ${minutesText(progress.elapsed_s)} of search` : '';
  const stillSearching = runStatus === 'SEARCHING' || runStatus === 'REVALIDATING';
  const infeasibleProven = /INFEASIBLE \(proven\)/i.test(detail);
  const byId = Object.fromEntries(parts.map((p) => [p.id, p.name]));
  const rules: [string, string][] = [
    ['Enclosure walls', frame?.wall_mm != null ? `${fmt(frame.wall_mm, 'mm')} → inner box ${(frame.inner_box_mm ?? []).map((v) => fmt(v, 'mm', { unit: false })).join(' × ')} mm` : '—'],
    ['Corner rails', frame?.rail_mm ? `${frame.rail_mm.map((v) => fmt(v, 'mm', { unit: false })).join(' × ')} mm, full length` : '—'],
    ['Clearance part–part', fmt((limits.clearance_part_mm as number | undefined) ?? null, 'clearance')],
    ['Clearance part–wall/rail', fmt((limits.clearance_wall_mm as number | undefined) ?? null, 'clearance')],
    ['CDS COM box', ((limits.com_box_mm as number[] | undefined) ?? []).map((v) => `±${v}`).join(' / ') + ' mm (standard, HARD in Stage 2)'],
    ['Frame mass in COM check', settings?.show_frame_mass_in_com ? 'included' : 'excluded by default (COM reported both ways)'],
    ['Cable-routing mode threshold', `${threshold}`],
    ['PCB stack', 'PCB-tagged parts parallel to XY, rail-centred, 15.24 mm PC/104 pitch'],
    ['COM-centring shift', 'whole layout moved along Z: at least into the COM box, further toward the centre as the search chooses; within the end plates, never at the cost of a mount'],
  ];
  return (
    <div className="tab-scroll" data-testid="tab-engineering">
      <Notice tone="warn" role="note">
        {DISCLAIMER_STAGE2} Every Stage 2 result is ENGINEERING-CONSTRAINED — not flight-qualified.
      </Notice>
      <Panel title="IDEALIZED vs ENGINEERING-CONSTRAINED" caption="synchronised cameras; movement overlay shows per-part arrows and ΔCOM" right={<MockTag />}>
        {searchedNothing || infeasibleProven ? (
          <Notice tone={stillSearching && !infeasibleProven ? 'warn' : 'err'} role="status">
            <strong data-testid="no-feasible">
              {infeasibleProven
                ? 'INFEASIBLE (proven)'
                : stillSearching
                  ? `No feasible layout yet${searchedFor} (not proven infeasible; still searching)`
                  : `NO FEASIBLE LAYOUT FOUND${searchedFor} (not proven infeasible)`}
            </strong>{' '}
            — constraints are never relaxed automatically.
            {b.data?.status === 'INFEASIBLE' && b.data.violations_engineering?.length ? (
              <span>
                {' '}
                Least-violating candidate {b.data.id} (geometry certified) breaks: {b.data.violations_engineering.join('; ')}.
              </span>
            ) : null}
          </Notice>
        ) : null}
        <div style={{ height: 420, display: 'flex' }}>
          <DualViewport
            left={{ label: s1?.id ?? 'no Stage 1 layout', items: itemsFor(a.data, newest), metrics: a.data?.metrics ?? null, stage: 1, empty: <span className="vp-chip">No Stage 1 layout yet</span> }}
            right={{
              label: s2?.id ?? 'no Stage 2 layout',
              items: itemsFor(b.data, newest),
              metrics: b.data?.metrics ?? null,
              stage: 2,
              empty: <span className="vp-chip">{list.notAvailable ? 'No layout archive from the backend' : 'No ENGINEERING-CONSTRAINED layout yet — switch to Stage 2 and optimise'}</span>,
            }}
          />
        </div>
        {a.data && b.data ? <MetricsDeltaTable a={a.data} b={b.data} labels={['IDEALIZED', 'ENGINEERING']} /> : null}
      </Panel>
      <div className="grid-2">
        <Panel title="Checks" caption="value / limit / margin / pass — backend verdicts">
          {checks.length ? (
            <table className="data" data-testid="checks-table">
              <thead>
                <tr>
                  <th>Check</th>
                  <th className="num">Value</th>
                  <th>Limit</th>
                  <th className="num">Margin</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {checks.map((c) => (
                  <tr key={c.name}>
                    <td>{c.name}</td>
                    <td className="num">{c.value}</td>
                    <td className="small">{c.limit}</td>
                    <td className="num">{c.margin}</td>
                    <td>{c.pass === null ? <Badge>—</Badge> : c.pass ? <Badge tone="ok">PASS</Badge> : <Badge tone="err">FAIL</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState title="No ENGINEERING-CONSTRAINED layout to check yet" />
          )}
          {b.data?.stage2?.com_shift_mm != null ? (
            <div className="small muted" style={{ marginTop: 6 }} data-testid="com-shift">
              {b.data.stage2.com_shift_mm
                ? `COM-centring shift: whole layout moved ${fmt(b.data.stage2.com_shift_mm, 'mm')} along Z`
                : 'COM-centring shift: none for this layout (no room between the end plates, no need, or it would cost a mount)'}
              {b.data.stage2.com_shift_mm && b.data.stage2.com_z_unshifted_mm != null ? ` (COM z before the shift ${fmt(b.data.stage2.com_z_unshifted_mm, 'mm')})` : ''}.
            </div>
          ) : null}
        </Panel>
        <Panel title="ASSUMED rules" caption="values from the project; editing needs a backend endpoint (not in the contract yet)">
          <table className="data">
            <tbody>
              {rules.map(([k, v]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td>{v}</td>
                  <td>
                    <Badge tone="warn">ASSUMED</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
      <div className="grid-2">
        <Panel title="Cable routing" caption="driven by the “Keep cable path clear” slider">
          <div className="row">
            <Badge tone={cm.mode === 'Continuous-cable' ? 'accent' : 'neutral'}>
              <span data-testid="cable-mode">MODE: {cm.mode.toUpperCase()}</span>
            </Badge>
            <span className="small">{cm.text}</span>
          </div>
          <div className="small" style={{ marginTop: 6 }}>
            Packing penalty vs default mode: ΔL {dL == null ? '—' : fmt(dL, 'mm', { signed: true })} · ΔCOM error {dD == null ? '—' : fmt(dD, 'mm', { signed: true })}
          </div>
        </Panel>
        <Panel title="Insertion order" caption="exact ±Z blocking matrix, greedy removal">
          {b.data?.metrics?.insertion_order?.length ? (
            <ol className="small" data-testid="insertion-order">
              {b.data.metrics.insertion_order.map((id) => (
                <li key={id}>{byId[id] ?? id}</li>
              ))}
            </ol>
          ) : (
            <EmptyState title="No insertion order yet" />
          )}
          {b.data?.metrics?.interlocked?.length ? <Notice tone="err">Interlocked: {b.data.metrics.interlocked.map((p) => p.map((x) => byId[x] ?? x).join(' ↔ ')).join('; ')}</Notice> : null}
        </Panel>
      </div>
      <AttributionPanel />
    </div>
  );
}

function AttributionPanel() {
  const study = useApp((s) => s.solver.studies['attribution']);
  const res = useAsync(() => session().api.attribution(), [study?.progress, study?.at]);
  const [err, setErr] = useState<string | null>(null);
  const a = res.data;
  const running = a && a.status !== 'DONE';
  const run = async () => {
    setErr(null);
    try {
      await session().api.runAttribution();
    } catch (e) {
      setErr((e as Error).message);
    }
    res.reload();
  };
  return (
    <Panel
      title="Constraint attribution"
      caption="Stage 2 re-solved with each constraint family relaxed in turn — same seed and budget per row (measured, not certified)"
      right={
        <Button size="small" onClick={run} disabled={!!running} data-testid="attribution-run">
          {running ? 'Running…' : 'Run attribution'}
        </Button>
      }
    >
      {err ? <Notice tone="err">{err}</Notice> : null}
      {!a || res.notAvailable ? (
        <EmptyState title="No constraint-attribution results yet">Run it to see which ASSUMED rule costs the most length, balance or feasibility.</EmptyState>
      ) : (
        <>
          {a.largest_effect ? <Notice tone="info">{a.largest_effect.text}.</Notice> : null}
          <table className="data" data-testid="attribution-table">
            <thead>
              <tr>
                <th>Relaxed</th>
                <th className="num">Violation measure</th>
                <th className="num">Used length</th>
                <th className="num">ΔL vs all rules</th>
                <th className="num">Overflow</th>
                <th className="num">Unmounted</th>
                <th className="num">COM error</th>
                <th>Feasible</th>
              </tr>
            </thead>
            <tbody>
              {a.rows.map((r) => (
                <tr key={r.relaxed}>
                  <td>{r.label}</td>
                  <td className="num">{fmt(r.cv, 'score')}</td>
                  <td className="num">{fmt(r.length_used_mm, 'mm')}</td>
                  <td className="num">{r.delta_length_used_mm == null ? '—' : fmt(r.delta_length_used_mm, 'mm', { signed: true })}</td>
                  <td className="num">{fmt(r.overflow_mm, 'mm')}</td>
                  <td className="num">{r.unmounted}</td>
                  <td className="num">{fmt(r.com_error_mm, 'mm')}</td>
                  <td>{r.feasible ? <Badge tone="ok">yes</Badge> : <Badge tone="err">no</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="muted small">
            {a.note} · mode {a.mode ?? '—'} · seed {a.seed ?? '—'} · {a.generations ?? '—'} generations × {a.population ?? '—'} per row
            {running ? ` · running ${Math.round((a.progress ?? 0) * 100)} %` : ''}
          </div>
        </>
      )}
    </Panel>
  );
}
