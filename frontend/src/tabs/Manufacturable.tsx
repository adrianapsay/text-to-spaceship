import { useMemo, useState } from 'react';
import type { MfgItem } from '../api/types';
import { session } from '../api/session';
import { useApp } from '../store/store';
import { useAsync } from '../hooks';
import { GoalSlider } from '../components/GoalsPanel';
import { AlgorithmChip } from '../components/AlgorithmChip';
import { useFullLayout, itemsFor } from '../components/LayoutCompare';
import { MainViewport } from '../components/viewport/Viewport';
import { Badge, Button, EmptyState, MockTag, Notice, Panel } from '../components/ui';
import { SLIDERS, MFG_LABEL } from '../lib/copy';
import { extraItemStyle } from '../lib/colors';
import { fmt } from '../lib/fmt';

/** Group hardware with metal 3D-printed brackets in their own section (Addendum 1.5). */
export function groupHardware(items: MfgItem[]): { section: string; items: MfgItem[] }[] {
  const am = items.filter((i) => extraItemStyle(i.process).section === 'METAL 3D-PRINTED');
  const other = items.filter((i) => extraItemStyle(i.process).section !== 'METAL 3D-PRINTED');
  const out: { section: string; items: MfgItem[] }[] = [];
  if (am.length) out.push({ section: 'METAL 3D-PRINTED', items: am });
  if (other.length) out.push({ section: 'OTHER HARDWARE', items: other });
  return out;
}

export function HardwareTable({ items }: { items: MfgItem[] }) {
  const groups = groupHardware(items);
  return (
    <table className="data" data-testid="hardware-list">
      <thead>
        <tr>
          <th>Part</th>
          <th>Mount type</th>
          <th>Process</th>
          <th>Material</th>
          <th className="num">Mass</th>
          <th className="num">Relative cost</th>
        </tr>
      </thead>
      {groups.map((g) => (
        <tbody key={g.section} data-section={g.section}>
          <tr>
            <th colSpan={6} style={{ position: 'static' }}>
              {g.section === 'METAL 3D-PRINTED' ? (
                <span className="row" style={{ gap: 6 }}>
                  <span className="swatch hatch" style={{ background: extraItemStyle('metal_am').color }} /> METAL 3D-PRINTED <Badge tone="accent">AM</Badge>
                </span>
              ) : (
                g.section
              )}
            </th>
          </tr>
          {g.items.map((i) => {
            const st = extraItemStyle(i.process);
            return (
              <tr key={i.id}>
                <td>{i.part_name ?? i.for_part}</td>
                <td>{i.mount_type}</td>
                <td>
                  <span className="row" style={{ gap: 4 }}>
                    <span className={`swatch ${st.hatch ? 'hatch' : ''}`} style={{ background: st.color }} />
                    {st.label}
                    {st.badge ? <Badge tone="accent">{st.badge}</Badge> : null}
                  </span>
                </td>
                <td>{i.material ?? '—'}</td>
                <td className="num">{fmt(i.mass_kg ?? null, 'kg')}</td>
                <td className="num">{fmt(i.cost_rel ?? null, 'rel')}</td>
              </tr>
            );
          })}
        </tbody>
      ))}
    </table>
  );
}

export function ManufacturableTab() {
  const settings = useApp((s) => s.goals.settings);
  const study = useApp((s) => s.solver.studies.mfg);
  const newest = useApp((s) => s.conn.newest);
  const res = useAsync(() => session().api.mfg(), [study?.at]);
  const [msg, setMsg] = useState<string | null>(null);
  const r = res.data;
  const layout = useFullLayout(r?.layout_id ?? null);
  const items = useMemo(() => itemsFor(layout.data, newest), [layout.data, newest]);
  const costDef = SLIDERS.find((s) => s.key === 'cost')!;
  const run = async () => {
    setMsg(null);
    try {
      await session().api.runMfg({});
      setMsg('Manufacturable Design started.');
      res.reload();
    } catch (e) {
      setMsg(`Could not start: ${(e as Error).message}`);
    }
  };
  return (
    <div className="tab-scroll" data-testid="tab-manufacturable">
      <Notice tone="warn" role="note">
        <strong>{MFG_LABEL}.</strong> Never a claim of flight qualification. Metal 3D-printed brackets have their own colour, a diagonal-hatch pattern and an “AM” badge.
      </Notice>
      <div className="grid-2" style={{ marginTop: 10 }}>
        <Panel title="Algorithm and cost priority" right={<MockTag />}>
          <AlgorithmChip />
          {r?.algorithm ? (
            <div className="small" style={{ marginTop: 6 }}>
              Manufacturable Design uses <strong>{r.algorithm.label}</strong>
              {r.algorithm.reason ? ` — because ${r.algorithm.reason}` : ''}
            </div>
          ) : null}
          {settings ? (
            <div style={{ marginTop: 6, border: '1px solid var(--border-subtle)' }}>
              <GoalSlider def={costDef} value={settings.sliders.cost} onChange={(v, c) => session().setSlider('cost', v, c)} note={settings.stage !== 2 ? 'Applies to Stage 2 and Manufacturable Design.' : undefined} />
            </div>
          ) : null}
          <div className="row" style={{ marginTop: 8 }}>
            <Button variant="primary" onClick={run} data-testid="mfg-run">
              Run Manufacturable Design
            </Button>
            {study ? <span className="small muted">progress {fmt((study.progress ?? 0) * 100, 'pct100')}</span> : null}
          </div>
          {msg ? <Notice tone={msg.startsWith('Could not') ? 'err' : 'info'}>{msg}</Notice> : null}
        </Panel>
        <Panel title="Totals">
          {r && r.status === 'DONE' ? (
            <div className="small" data-testid="mfg-totals">
              <div>
                {r.feasible ? <Badge tone="ok">FEASIBLE</Badge> : <Badge tone="err">INFEASIBLE</Badge>}{' '}
                {r.verdict ?? (r.feasible ? 'all parts mounted, parts and brackets validated' : 'see the violations below')}
              </div>
              <div style={{ marginTop: 4 }}>
                Hardware items: {r.items?.length ?? 0} · relative cost {fmt(r.total_cost_rel ?? null, 'rel')} (ASSUMED cost model; catalogue part = 1) · hardware mass {fmt(r.hardware_mass_kg ?? null, 'kg')}
              </div>
              {r.validation ? (
                <div style={{ marginTop: 4 }}>
                  Parts {r.validation.parts_valid ? 'validated' : 'NOT validated'} ({r.validation.pairs} pairs, {r.validation.statics} frame checks
                  {r.validation.relaxed_rules ? ', end-plate rule relaxed to report the overflow' : ''}) · brackets clear of other parts (≥ 1.2 mm, exact meshes):{' '}
                  {r.validation.brackets.filter((b) => b.ok).length}/{r.validation.brackets.length}
                </div>
              ) : null}
              {r.violations?.length ? (
                <ul style={{ margin: '4px 0 0 16px' }} data-testid="mfg-violations">
                  {r.violations.map((v) => (
                    <li key={v}>{v}</li>
                  ))}
                </ul>
              ) : null}
              <div className="muted" style={{ marginTop: 4 }}>
                {fmt(r.seconds ?? null, 's')} · {r.evaluations ?? '—'} layouts evaluated · harness mode {r.mode ?? '—'} · bracket reach {r.bracket_reach_mm ?? '—'} mm
              </div>
            </div>
          ) : r?.status === 'RUNNING' ? (
            <span className="small">Running… the result appears here when the search, bracket synthesis and checks finish.</span>
          ) : r?.status === 'ERROR' ? (
            <Notice tone="err">The run failed: {r.detail}</Notice>
          ) : (
            <span className="muted small">—</span>
          )}
        </Panel>
      </div>
      {res.notAvailable || !r || r.status !== 'DONE' ? (
        <EmptyState title="No Manufacturable Design result yet">
          {res.notAvailable ? 'The backend has not published a Manufacturable Design result. ' : res.error ?? ''}It chooses a mount for every part (direct, catalogue, sheet metal, machined or metal 3D-printed), checks the brackets like any part, and lists the hardware.
        </EmptyState>
      ) : (
        <>
          {r.layout_id ? (
            <Panel title={`Layout ${r.layout_id} with mounting hardware`}>
              <div style={{ height: 420, display: 'flex' }}>
                <MainViewport items={items} metrics={layout.data?.metrics ?? null} stage={2} testId="mfg-viewport" />
              </div>
            </Panel>
          ) : null}
          <Panel title="Hardware list" caption="part, mount type, process, material, mass, relative cost">
            {r.items?.length ? <HardwareTable items={r.items} /> : <EmptyState title="No hardware items" />}
          </Panel>
          <Panel title="Metal AM design-rule report" caption="ASSUMED rules: wall ≥ 1.0 mm, overhang ≤ 45°, holes ≥ 2 mm, build-volume fit">
            {r.am_rules?.length ? (
              <table className="data">
                <thead>
                  <tr>
                    <th>Bracket</th>
                    <th>Rule</th>
                    <th className="num">Value</th>
                    <th className="num">Limit</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {r.am_rules.map((x, i) => (
                    <tr key={i}>
                      <td>{x.item_id}</td>
                      <td>{x.rule}</td>
                      <td className="num">{String(x.value ?? '—')}</td>
                      <td className="num">{String(x.limit ?? '—')}</td>
                      <td>{x.pass ? <Badge tone="ok">PASS</Badge> : <Badge tone="err">FAIL</Badge>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <EmptyState title="No AM brackets / rule report" />
            )}
          </Panel>
          <Panel title="Exports" caption={MFG_LABEL}>
            {r.exports?.length ? (
              <div className="row">
                {r.exports.map((e) => (
                  <Button key={e.url} onClick={() => void session().api.download(e.url, e.label)}>
                    {e.label}
                  </Button>
                ))}
              </div>
            ) : (
              <EmptyState title="No export files yet" />
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
