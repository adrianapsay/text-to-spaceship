import { Fragment, useMemo, useState } from 'react';
import type { BracketDesign, BracketInfo, BracketMode, BracketOverride, ContestResults, DesignOptions, LayoutSummary, Settings } from '../api/types';
import { session } from '../api/session';
import { useApp } from '../store/store';
import { useAsync, useParts } from '../hooks';
import { BracketSettings, DesignSettings, governingText, outdatedText } from '../components/BracketDesign';
import { DesignProgressPanel, SavedStlPanel } from '../components/DesignProgress';
import { GoalSlider } from '../components/GoalsPanel';
import { itemsFor, useLayoutList } from '../components/LayoutCompare';
import { MainViewport } from '../components/viewport/Viewport';
import { Badge, Button, EmptyState, MockTag, Notice, Panel } from '../components/ui';
import { COM_FIRST_WHAT, DISCLAIMER_STAGE2, SLIDERS } from '../lib/copy';
import { extraItemStyle } from '../lib/colors';
import { fmt } from '../lib/fmt';
import { comFirstOn } from '../store/presets';

const KIND_LABEL: Record<string, string> = {
  direct: 'Direct (M3 + spacer washers)',
  machined: 'Machined spacer block',
  sheet: 'Sheet-metal Z-bracket',
  clamp: 'Tube clamp',
  cradle: 'Machined cradle',
  metal_am: 'Metal 3D-printed bracket',
};

const DESIGNED_KINDS = ['metal_am', 'cradle', 'clamp'];

/** The bracket budget's metal-AM step (backend mfg.rules.am_level). */
function amLevelText(budget: number): string {
  if (budget <= 0) return 'Budget 0: simple brackets only (direct, machined, sheet metal, clamps, machined cradles).';
  if (budget < 34) return 'Metal 3D-printed brackets only where no simple bracket fits.';
  if (budget < 67) return 'Metal 3D-printed brackets where they cost at most 2× the cheapest simple bracket that fits (they replace machined cradles).';
  if (budget < 100) return 'Metal 3D-printed brackets where they cost at most 10× the cheapest simple bracket (also instead of blocks, sheet brackets and clamps).';
  return 'Budget 100: a metal 3D-printed bracket wherever one fits (parts bolted straight to a wall keep their bolts).';
}

function latestStage2(list: LayoutSummary[] | null): LayoutSummary | null {
  const c = (list ?? []).filter((l) => l.stage === 2 && (l.status === 'VALIDATED' || l.status === 'FINAL'));
  c.sort((a, b) => ((a.created ?? '') < (b.created ?? '') ? 1 : -1));
  return c[0] ?? null;
}

function boxSize(r: number[]): string {
  if (r.length !== 6) return '—';
  return [0, 1, 2].map((k) => fmt(r[k + 3] - r[k], 'mm', { unit: false })).join(' × ') + ' mm';
}

function Margin({ v }: { v: number | null | undefined }) {
  if (v == null) return <span className="muted">—</span>;
  return <Badge tone={v >= 0 ? 'ok' : 'err'}>{(v >= 0 ? '+' : '') + v.toFixed(2)}</Badge>;
}

/** First natural frequency and what the part does in that mode (e.g. "part rotates about x"). */
function F1Cell({ f1, modes }: { f1: number | null | undefined; modes?: BracketMode[] | null }) {
  if (f1 == null) return <span className="muted">—</span>;
  const m = modes?.[0];
  return (
    <span title={modes?.map((x) => `${Math.round(x.f_hz)} Hz: ${x.motion}`).join('\n')}>
      {Math.round(f1)} Hz{m ? <span className="muted small"> ({m.motion})</span> : null}
    </span>
  );
}

/** Mass cell: exact (built solid), ESTIMATE (reserved box only) or the designed, FEA-checked solid. */
function MassCell({ b, d }: { b: BracketInfo; d?: BracketDesign }) {
  if (d && d.mass_kg == null) {
    return (
      <span title={d.reason}>
        {fmt(b.mass_kg, 'kg')} <Badge tone="err">design failed</Badge>
      </span>
    );
  }
  if (d) {
    return (
      <span>
        {fmt(d.mass_kg, 'kg')} <Badge tone="ok">designed</Badge>
      </span>
    );
  }
  return (
    <span>
      {fmt(b.mass_kg, 'kg')} {b.exact ? <Badge>exact</Badge> : <Badge tone="warn">ESTIMATE</Badge>}
    </span>
  );
}

function BracketTable(props: {
  layoutId: string;
  brackets: BracketInfo[];
  designs: Record<string, BracketDesign>;
  overrides: Record<string, BracketOverride>;
  names: Record<string, string>;
  options: DesignOptions | null;
  settings: Settings | null;
  running: boolean;
}) {
  const { brackets, designs, overrides, names, options, settings } = props;
  const [open, setOpen] = useState<string | null>(null);
  const env = settings?.launch_environment ?? options?.launch_environment ?? 'gevs';
  const mat = settings?.bracket_material ?? options?.bracket_material ?? 'AlSi10Mg';
  const envName = options?.environments.find((e) => e.id === env)?.name;
  return (
    <table className="data" data-testid="bracket-table">
      <thead>
        <tr>
          <th>Part</th>
          <th>Bracket</th>
          <th>Fixed to</th>
          <th className="num">Gap</th>
          <th>Reserved box</th>
          <th>Material</th>
          <th className="num">Mass</th>
          <th className="num">Rel. cost</th>
          <th className="num">MS yield</th>
          <th className="num">MS ult.</th>
          <th className="num">MS bolts</th>
          <th className="num">f1</th>
          <th>Governing check</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {brackets.map((b) => {
          const d0 = designs[b.pid];
          const failed = !!d0 && d0.mass_kg == null;
          const d = failed ? undefined : d0;
          const st = extraItemStyle(b.process);
          const designable = DESIGNED_KINDS.includes(b.kind);
          const isOpen = open === b.pid;
          const stale = outdatedText(b, d0, overrides[b.pid], env, mat, envName);
          return (
            <Fragment key={b.name}>
              <tr className={isOpen ? 'bracket-open' : undefined}>
                <td>{names[b.pid] ?? b.pid}</td>
                <td>
                  <span className="row" style={{ gap: 6 }}>
                    <span className={`swatch ${st.hatch ? 'hatch' : ''}`} style={{ background: st.color }} />
                    {KIND_LABEL[b.kind] ?? b.mount_type}
                    {st.badge ? <Badge tone="accent">{st.badge}</Badge> : null}
                  </span>
                  {d ? <div className="small muted">{d.generator}</div> : null}
                  {stale ? (
                    <div className="small" data-testid={`outdated-${b.pid}`}>
                      <Badge tone="warn">outdated</Badge> {stale}
                    </div>
                  ) : null}
                </td>
                <td className="small">{b.target}</td>
                <td className="num">{fmt(b.gap_mm, 'mm')}</td>
                <td className="small">{boxSize(b.reserve)}</td>
                <td className="small">{d0?.material ?? b.material}</td>
                <td className="num">
                  <MassCell b={b} d={d0} />
                </td>
                <td className="num">{fmt(d ? d.cost_rel : b.cost_rel, 'rel')}</td>
                <td className="num">
                  <Margin v={d?.ms_yield} />
                </td>
                <td className="num">
                  <Margin v={d?.ms_ult} />
                </td>
                <td className="num">
                  <Margin v={d?.ms_bolt} />
                </td>
                <td className="num"><F1Cell f1={d?.f1_hz} modes={d?.modes} /></td>
                <td className="small">{d?.governing ? governingText(d.governing) : <span className="muted">—</span>}</td>
                <td>
                  {designable ? (
                    <Button size="small" onClick={() => setOpen(isOpen ? null : b.pid)} aria-expanded={isOpen} data-testid={`bracket-open-${b.pid}`}>
                      {isOpen ? 'Close' : 'Adjust'}
                    </Button>
                  ) : null}
                </td>
              </tr>
              {isOpen ? (
                <tr className="bracket-open">
                  <td colSpan={14}>
                    <BracketSettings layoutId={props.layoutId} b={b} d={d0} ov={overrides[b.pid]} options={options} settings={settings} running={props.running} />
                  </td>
                </tr>
              ) : null}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

function ContestPanel({ c, notAvailable }: { c: ContestResults | null; notAvailable: boolean }) {
  if (!c || notAvailable) {
    return (
      <Panel title="Generative-design contest" caption="open-source generators, each design checked with CalculiX and NGSolve">
        <EmptyState title="No contest results yet">The contest results are published by the backend once the contest has run.</EmptyState>
      </Panel>
    );
  }
  const problems = c.problems.map((p) => p.name);
  return (
    <Panel title="Generative-design contest" caption={`${c.entrants.length} entrants × ${c.problems.length} bracket problems · ${c.created}`}>
      {c.winner ? (
        <Notice tone="info">
          <strong data-testid="contest-winner">Winner: {c.winner.generator}</strong> — {c.winner.why}
        </Notice>
      ) : null}
      <table className="data" data-testid="contest-standings">
        <thead>
          <tr>
            <th className="num">Rank</th>
            <th>Generator</th>
            <th className="num">Passed</th>
            <th className="num">Total mass (passing)</th>
          </tr>
        </thead>
        <tbody>
          {c.standings.map((s) => (
            <tr key={s.generator}>
              <td className="num">{s.rank}</td>
              <td>{s.generator}</td>
              <td className="num">
                {s.passed}/{s.problems}
              </td>
              <td className="num">{s.total_mass_g != null ? `${s.total_mass_g.toFixed(1)} g` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {problems.map((p) => (
        <div key={p} style={{ marginTop: 10 }}>
          <div className="small">
            <strong>{p}</strong> — {c.problems.find((x) => x.name === p)?.description}
          </div>
          <table className="data">
            <thead>
              <tr>
                <th>Generator</th>
                <th className="num">Mass</th>
                <th className="num">Stress (voxel avg)</th>
                <th className="num">Raw peak</th>
                <th className="num">MS yield</th>
                <th className="num">MS ult.</th>
                <th className="num">f1 (with part)</th>
                <th className="num">Solver agreement</th>
                <th className="num">Time</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {c.rows
                .filter((r) => r.problem === p)
                .map((r) => (
                  <tr key={r.generator}>
                    <td>{r.generator}</td>
                    <td className="num">{r.mass_g != null ? `${r.mass_g.toFixed(1)} g` : '—'}</td>
                    <td className="num">{r.sigma_mpa != null ? `${r.sigma_mpa.toFixed(0)} MPa` : '—'}</td>
                    <td className="num muted">{r.sigma_peak_mpa != null ? `${r.sigma_peak_mpa.toFixed(0)} MPa` : '—'}</td>
                    <td className="num">
                      <Margin v={r.ms_yield} />
                    </td>
                    <td className="num">
                      <Margin v={r.ms_ult} />
                    </td>
                    <td className="num"><F1Cell f1={r.f1_hz} modes={r.modes} /></td>
                    <td className="num small">{r.agreement?.sigma_rel != null ? `σ ${(100 * r.agreement.sigma_rel).toFixed(3)} %` : '—'}</td>
                    <td className="num">{fmt((r.gen_seconds ?? 0) + (r.fea_seconds ?? 0), 's')}</td>
                    <td>{r.passed ? <Badge tone="ok">PASS</Badge> : <Badge tone="err">{r.ok ? 'FAIL' : 'NO DESIGN'}</Badge>}{r.reason ? <div className="small muted">{r.reason}</div> : null}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ))}
      <div className="small muted" style={{ marginTop: 8 }}>
        Margins use the stress averaged over each design voxel: the raw peak at the sharp corners of a voxel-built
        design grows every time the mesh is refined, the voxel average does not. Criteria (ASSUMED): {c.criteria.join(' · ')}. Entrants: {c.entrants.map((e) => `${e.name}${e.available ? '' : ' (not run: ' + (e.note ?? 'unavailable') + ')'}`).join('; ')}.
      </div>
    </Panel>
  );
}

export function HardwareTab() {
  const settings = useApp((s) => s.goals.settings);
  const newest = useApp((s) => s.conn.newest);
  const study = useApp((s) => s.solver.studies['bracket_design']);
  const infeasible = useApp((s) => s.solver.infeasible);
  const best = useApp((s) => s.solver.best);
  const parts = useParts();
  const list = useLayoutList();
  // the best Stage 2 layout (the one the search reports and the automatic bracket design works on), else the newest
  const s2v =
    best && best.stage === 2 && (best.status === 'VALIDATED' || best.status === 'FINAL')
      ? (best as unknown as LayoutSummary)
      : latestStage2(list.data);
  const s2 = s2v ?? (infeasible && infeasible.stage === 2 ? (infeasible as unknown as LayoutSummary) : null);
  // reloaded when a bracket-design run has finished (designed solids replace the estimates)
  const doneAt = (study?.partial as { status?: string } | undefined)?.status === 'DONE' ? study?.at : null;
  const layout = useAsync(s2?.id ? () => session().api.layout(s2.id) : null, [s2?.id, doneAt]);
  const contest = useAsync(() => session().api.gdContest(), []);
  const options = useAsync(() => session().api.designOptions(), []);
  const [msg, setMsg] = useState<string | null>(null);
  const items = useMemo(() => itemsFor(layout.data, newest), [layout.data, newest]);
  const names = useMemo(() => Object.fromEntries(parts.map((p) => [p.id, p.name])), [parts]);
  const view = layout.data?.stage2;
  const brackets = view?.brackets ?? [];
  const designs = view?.bracket_designs ?? {};
  const runStatus = (study?.partial as { status?: string } | undefined)?.status;
  const running = runStatus === 'PENDING' || runStatus === 'RUNNING';
  const envId = settings?.launch_environment ?? options.data?.launch_environment;
  const envName = options.data?.environments.find((e) => e.id === envId)?.name ?? envId ?? 'the launch environment';
  const budgetDef = SLIDERS.find((s) => s.key === 'bracket_budget')!;
  const byKind = useMemo(() => {
    const m: Record<string, number> = {};
    brackets.forEach((b) => (m[b.kind] = (m[b.kind] ?? 0) + 1));
    return m;
  }, [brackets]);
  const mass = brackets.reduce((s, b) => s + (designs[b.pid]?.mass_kg ?? b.mass_kg), 0);
  // the layout's cost C is the search-time estimate; designed brackets replace their estimated cost
  const cost =
    view?.hardware_cost_rel == null
      ? null
      : view.hardware_cost_rel + brackets.reduce((s, b) => s + (designs[b.pid]?.mass_kg != null ? designs[b.pid].cost_rel - b.cost_rel : 0), 0);
  const estimates = brackets.filter((b) => !b.exact && !designs[b.pid]).length;
  // brackets the design job gives a real solid (metal AM, cradle, clamp band); until then: box / catalogue envelope
  const undesigned = brackets.filter((b) => DESIGNED_KINDS.includes(b.kind) && designs[b.pid]?.mass_kg == null).length;
  // what the button designs: no solid yet, or designed for another launch environment or material
  const overrides = view?.bracket_overrides ?? {};
  const matId = settings?.bracket_material ?? options.data?.bracket_material ?? 'AlSi10Mg';
  const todo = brackets
    .filter((b) => DESIGNED_KINDS.includes(b.kind))
    .filter((b) => designs[b.pid]?.mass_kg == null || outdatedText(b, designs[b.pid], overrides[b.pid], envId ?? 'gevs', matId) != null)
    .map((b) => b.pid);
  const auto = settings?.auto_design_brackets ?? true;
  const design = async () => {
    if (!layout.data) return;
    setMsg(null);
    try {
      await session().api.designBrackets(layout.data.id, { pids: todo });
      setMsg(`Bracket design started under ${envName}: the contest winner designs every metal-AM bracket, and the rule-based shape every cradle and clamp band, inside its reserved box; each design is checked with CalculiX and NGSolve and replaces the box in the 3D views and exports.`);
    } catch (e) {
      setMsg(`Could not start: ${(e as Error).message}`);
    }
  };
  return (
    <div className="tab-scroll" data-testid="tab-hardware">
      <Notice tone="warn" role="note">
        Stage 2 only. Every part except the PC/104 boards is held by a bracket whose reserved box is part of the packing: it keeps 1.2 mm from every other part, bracket and keep-out, and the fit proof certifies it (Lemma 4). Costs are relative and ASSUMED; cradle and metal 3D-printed bracket masses are ESTIMATES until designed. {DISCLAIMER_STAGE2}
      </Notice>
      <div className="grid-2" style={{ marginTop: 10 }}>
        <Panel title="Bracket budget" right={<MockTag />}>
          {settings ? (
            <div style={{ border: '1px solid var(--border-subtle)' }}>
              <GoalSlider
                def={budgetDef}
                value={settings.sliders.bracket_budget ?? 50}
                onChange={(v, c) => session().setSlider('bracket_budget', v, c)}
                note={settings.stage !== 2 ? 'Brackets are modelled in Stage 2 only.' : undefined}
              />
            </div>
          ) : null}
          <div className="small" style={{ marginTop: 6 }} data-testid="budget-mode">
            {amLevelText(settings?.sliders.bracket_budget ?? 50)}
            {(settings?.sliders.bracket_budget ?? 50) > 0 ? ` Hardware cost weighted by ${(100 - (settings?.sliders.bracket_budget ?? 50)).toFixed(0)} / 100.` : ''}
          </div>
          {settings && comFirstOn(settings.sliders, settings.stage) ? (
            <div className="small" style={{ marginTop: 6 }} data-testid="com-first">
              <Badge tone="accent">Centre of mass first</Badge> With Balance at 100 as well, {COM_FIRST_WHAT}
            </div>
          ) : null}
        </Panel>
        <Panel title="Totals" caption={s2 ? `layout ${s2.id}` : undefined}>
          {brackets.length ? (
            <div className="small" data-testid="hardware-totals">
              <div>
                {brackets.length} brackets · hardware mass {fmt(mass, 'kg')}
                {estimates ? ` (${estimates} estimated)` : ''} · relative cost {fmt(cost, 'rel')}
              </div>
              <div style={{ marginTop: 4 }}>
                {Object.entries(byKind).map(([k, n]) => (
                  <Badge key={k} tone={k === 'metal_am' ? 'accent' : 'neutral'}>
                    {n} × {KIND_LABEL[k] ?? k}
                  </Badge>
                ))}
              </div>
              <div className="row" style={{ marginTop: 8 }}>
                <Button variant="primary" onClick={design} disabled={!layout.data || !todo.length || running} data-testid="design-brackets">
                  Design the 3D-printed, cradle and clamp brackets{todo.length ? ` (${todo.length})` : ''}
                </Button>
              </div>
              <label className="small row" style={{ marginTop: 6, gap: 6 }}>
                <input
                  type="checkbox"
                  checked={auto}
                  onChange={(ev) => session().patchSettings({ auto_design_brackets: ev.target.checked })}
                  data-testid="auto-design"
                />
                Design them automatically when the search pauses (best Stage 2 layout)
              </label>
              {msg ? <Notice tone={msg.startsWith('Could not') ? 'err' : 'info'}>{msg}</Notice> : null}
            </div>
          ) : (
            <span className="muted small">{s2 ? 'This layout has no brackets (all parts on the PC/104 stack, or mounting relaxed).' : 'No Stage 2 layout yet.'}</span>
          )}
        </Panel>
      </div>
      <Panel title="Design settings" caption="the launch loads every bracket is checked under, and the material of the metal 3D-printed ones">
        <DesignSettings options={options.data ?? null} settings={settings ?? null} notAvailable={!!options.notAvailable} />
      </Panel>
      {study ? (
        <Panel title="Bracket design run" caption="one bar per bracket; up to 4 are designed at the same time, each checked with CalculiX and NGSolve">
          <DesignProgressPanel />
        </Panel>
      ) : null}
      <Panel
        title="Saved STL files"
        caption="the designed assembly as STL files (world coordinates, mm): written when a bracket design run finishes; moving a slider removes the brackets from them"
      >
        <SavedStlPanel layoutId={layout.data?.stage === 2 ? layout.data.id : null} />
      </Panel>
      {!s2 ? (
        <EmptyState title="No ENGINEERING-CONSTRAINED layout yet">Switch to Stage 2 and optimise: every layout found there carries its brackets.</EmptyState>
      ) : (
        <>
          <Panel
            title={`Layout ${s2.id} with its brackets`}
            caption={`metal 3D-printed brackets hatched (AM badge); ${undesigned ? `${undesigned} not designed yet: shown as their reserved box (cradle, metal AM) or catalogue envelope (clamp)` : 'every bracket shown as its real solid'}`}
          >
            <div style={{ height: 420, display: 'flex' }}>
              <MainViewport items={items} metrics={layout.data?.metrics ?? null} stage={2} testId="hardware-viewport" />
            </div>
          </Panel>
          <Panel
            title="Brackets"
            caption={`one per part${view?.com_first ? ', found with the centre of mass first: of any length (beyond 40 mm metal 3D-printed only)' : ''}; mass exact for built solids, ESTIMATE from the reserved box until designed; margins from two FEA solvers once designed, under ${envName} (the smallest over every load case and axis); Adjust sets a bracket's material, material used and member thickness`}
          >
            {brackets.length ? (
              <BracketTable
                layoutId={s2.id}
                brackets={brackets}
                designs={designs}
                overrides={view?.bracket_overrides ?? {}}
                names={names}
                options={options.data ?? null}
                settings={settings ?? null}
                running={running}
              />
            ) : (
              <EmptyState title="No brackets in this layout" />
            )}
          </Panel>
        </>
      )}
      <ContestPanel c={contest.data ?? null} notAvailable={!!contest.notAvailable} />
      <Panel title="Bracket rules (ASSUMED)">
        <ul className="small" style={{ margin: '0 0 0 16px' }}>
          <li>Reach: a bracket bridges up to 40 mm from the part's mounting side (its 3 mm layer side) to chassis structure only: a wall, an end plate or a corner rail, never another part. With Balance and the Bracket budget both at 100 (centre of mass first) there is no limit (beyond 40 mm only metal 3D-printed), and the parts are moved along the length until the balance point is centred. The PC/104 boards hang on four rods with spacer tubes from the nearest end plate.</li>
          <li>Cheapest bracket that fits: direct (≤ 3.5 mm), machined block (≤ 15 mm), sheet Z-bracket, tube clamp for cylindrical parts, machined cradle for curved or irregular sides. Metal 3D-printed brackets need a budget above 0, and the budget sets how much more they may cost than the simple bracket they replace (steps at 34, 67 and 100).</li>
          <li>Clearance: each reserved box keeps 1.2 mm from every other part, bracket and keep-out except the one it is fixed to.</li>
          <li>
            Loads: the launch environment chosen above (default GEVS, GSFC-STD-7000B). Quasi-static: the GSFC mass-acceleration curve by the part&apos;s mass, each axis separately. Random vibration: modal superposition (all
            modes combined, CQC) over 20–2000 Hz, 3σ von Mises. Two checks: the limit level × the preset&apos;s factors (GEVS 1.25 / 1.4 static, 1.6 / 1.8 random), and the qualification level (limit + 3 dB) against
            yield × 1.0 and ultimate × 1.25. Bolts: M3 A2-70 with a fitting factor of 1.15, plus flange bearing and head pull-through in the bracket&apos;s bolted flange (at least 2 mm). Shock: an ESTIMATE, reported only. First natural frequency with the part ≥ 100 Hz (GEVS
            guidance, kept as this project&apos;s rule). Materials: AlSi10Mg or Ti-6Al-4V (metal 3D-printed), 6061-T6 (machined), vendor minimum values, not design allowables.
          </li>
        </ul>
      </Panel>
    </div>
  );
}
