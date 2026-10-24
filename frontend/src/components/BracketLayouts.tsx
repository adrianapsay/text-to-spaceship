// M4: the bracket layout of a Stage 2 layout, three ways side by side — one bracket per part (the default), combined
// per wall (neighbouring metal 3D-printed brackets on one wall joined into one print) and one piece (one print that
// holds every part except the PC/104 boards; exploratory). Each column: the bracket mass in total, the worst margin
// and its check, the system's first natural frequency, the number of prints and the largest one's size against an
// ASSUMED L-PBF build volume. Combined and one piece run on request in the background (the same progress bars as the
// per-part design run, one run at a time); "Use for saved STL files" chooses what the 3D views, the bill of
// materials, the drawings, the fit proof and the saved STL files show (backend GET/POST
// /api/layouts/{id}/bracket-layouts…).
import { useMemo, useState } from 'react';
import type {
  BracketLayoutMode,
  BracketLayouts,
  DesignOptions,
  LayoutModeView,
  LayoutRunSettings,
  OnePieceEstimate,
  Settings,
} from '../api/types';
import { session } from '../api/session';
import { useAsync } from '../hooks';
import { useApp } from '../store/store';
import { governingText, MEMBER_STOPS, pctText, StopSlider, vfStops } from './BracketDesign';
import { secondsText } from './DesignProgress';
import { Badge, Button, Notice } from './ui';

export const MODES: BracketLayoutMode[] = ['per_part', 'combined', 'one_piece'];
export const MODE_TITLE: Record<BracketLayoutMode, string> = {
  per_part: 'One bracket per part',
  combined: 'Combined per wall',
  one_piece: 'One piece',
};

export function sizeText(s: number[] | null | undefined): string {
  if (!s || s.length !== 3) return '—';
  return s.map((x) => x.toFixed(0)).join(' × ') + ' mm';
}

export function massText(kg: number | null | undefined): string {
  return kg == null ? '—' : `${(kg * 1000).toFixed(1)} g`;
}

function signed(v: number): string {
  return (v >= 0 ? '+' : '') + v.toFixed(2);
}

/** The comparison cells of one column (plain text, for the table and its test). */
export function columnCells(v: LayoutModeView | undefined): Record<string, string> {
  const s = v?.summary;
  if (!s) return { mass: '—', worst: '—', f1: '—', prints: '—', largest: '—' };
  return {
    mass: `${massText(s.bracket_mass_kg)}${s.estimates ? ` (${s.estimates} ESTIMATE${s.estimates > 1 ? 's' : ''})` : ''}`,
    worst: s.worst ? `MS ${signed(s.worst.ms)} — ${governingText(s.worst as never)}${s.worst.bracket ? ` (${s.worst.bracket})` : ''}` : 'no designed bracket yet',
    f1: s.f1 ? `${Math.round(s.f1.f_hz)} Hz${s.f1.bracket ? ` (${s.f1.bracket})` : ''}` : '—',
    prints: String(s.prints),
    largest: s.largest_print_mm ? `${sizeText(s.largest_print_mm)}${s.largest_fits === false ? ' — larger than the build volume' : ''}` : '—',
  };
}

function statusBadge(v: LayoutModeView | undefined, mode: BracketLayoutMode) {
  if (!v) return <Badge>—</Badge>;
  if (v.status === 'not run') return <Badge>not run</Badge>;
  if (mode === 'per_part') return <Badge tone={v.status === 'designed' ? 'ok' : 'warn'}>{v.status}</Badge>;
  const s = v.summary;
  if (s?.failed?.length) return <Badge tone="err">{s.failed.length} without a solid</Badge>;
  return <Badge tone={s?.passed ? 'ok' : 'err'}>{s?.passed ? 'designed, passed' : 'designed, did not pass'}</Badge>;
}

export interface LayoutTableProps {
  data: BracketLayouts;
  /** a design run (any mode) is under way */
  running: boolean;
  names?: Record<string, string>;
  onRun?: (mode: 'combined' | 'one_piece') => void;
  onUse?: (mode: BracketLayoutMode) => void;
}

/** The three columns side by side. */
export function BracketLayoutTable({ data, running, names, onRun, onUse }: LayoutTableProps) {
  const cells = MODES.map((m) => columnCells(data.modes[m]));
  const rows: [string, string, string][] = [
    ['mass', 'Bracket mass (all brackets, fasteners included)', 'the PC/104 rods and standoffs are the same in every layout and left out'],
    ['worst', 'Worst margin and its check', 'the smallest gating margin over the designed brackets'],
    ['f1', 'System first natural frequency', 'the lowest over the brackets with the parts they hold (≥ 100 Hz required)'],
    ['prints', 'Printed pieces', 'metal 3D-printed brackets'],
    ['largest', 'Largest print', `bounding box; build volume ${sizeText(data.build_volume_mm)} (ASSUMED)`],
  ];
  const nm = (p: string) => names?.[p] ?? p;
  return (
    <table className="data bracket-layouts" data-testid="bracket-layouts-table">
      <thead>
        <tr>
          <th />
          {MODES.map((m) => (
            <th key={m} data-testid={`layout-col-${m}`}>
              {MODE_TITLE[m]}
              {m === 'one_piece' && data.exploratory?.one_piece ? <Badge tone="warn">exploratory</Badge> : null}
              {data.chosen === m ? <Badge tone="accent">chosen</Badge> : null}
              <div className="small">{statusBadge(data.modes[m], m)}</div>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(([key, label, hint]) => (
          <tr key={key}>
            <td title={hint}>{label}</td>
            {MODES.map((m, i) => (
              <td key={m} className="num" data-testid={`cell-${key}-${m}`}>
                {cells[i][key]}
              </td>
            ))}
          </tr>
        ))}
        <tr>
          <td>Parts held</td>
          {MODES.map((m) => {
            const designs = data.modes[m]?.result?.designs ?? {};
            const held = Object.values(designs).flatMap((d) => d.parts ?? []);
            return (
              <td key={m} className="small" data-testid={`cell-parts-${m}`}>
                {m === 'per_part'
                  ? `${data.modes[m]?.summary?.pieces ?? 0} brackets, one each`
                  : held.length
                    ? Object.values(designs)
                        .map(
                          (d) =>
                            `${d.name}: ${d.parts.map(nm).join(', ')}` +
                            (d.mass_kg == null
                              ? ` — no solid${d.reason ? ` (${d.reason})` : ''}: these parts keep their own brackets in the numbers`
                              : ''),
                        )
                        .join('; ')
                    : m === 'combined' && data.combined_plan.length
                      ? `plan: ${data.combined_plan.map((g) => `${g.target}: ${g.pids.map(nm).join(', ')}`).join('; ')}`
                      : m === 'combined'
                        ? 'nothing to join (no two metal 3D-printed brackets on one wall with clear space between)'
                        : 'every part but the PC/104 boards'}
              </td>
            );
          })}
        </tr>
        <tr>
          <td />
          {MODES.map((m) => {
            const v = data.modes[m];
            const designed = m === 'per_part' || !!v?.summary && !(v.summary.failed?.length && v.summary.failed.length === Object.keys(v.result?.designs ?? {}).length);
            const canRun = m === 'combined' ? data.combined_plan.length > 0 : m === 'one_piece';
            return (
              <td key={m}>
                <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                  {m !== 'per_part' ? (
                    <Button size="small" onClick={() => onRun?.(m as 'combined' | 'one_piece')} disabled={running || !canRun} data-testid={`run-${m}`}>
                      {v?.status === 'not run' ? 'Design' : 'Design again'}
                    </Button>
                  ) : null}
                  <Button
                    size="small"
                    variant={data.chosen === m ? undefined : 'primary'}
                    onClick={() => onUse?.(m)}
                    disabled={running || data.chosen === m || !designed}
                    data-testid={`use-${m}`}
                  >
                    {data.chosen === m ? 'Used for the saved STL files' : 'Use for saved STL files'}
                  </Button>
                </div>
              </td>
            );
          })}
        </tr>
      </tbody>
    </table>
  );
}

/** Settings of a combined / one-piece run: material, material used, minimum member thickness, time budget. */
export function LayoutRunForm(props: {
  mode: 'combined' | 'one_piece';
  options: DesignOptions | null;
  settings: Settings | null;
  budgetRange: [number, number];
  running: boolean;
  estimate?: OnePieceEstimate | null;
  onEstimate?: (s: LayoutRunSettings) => void;
  onStart: (s: LayoutRunSettings) => void;
}) {
  const stops = useMemo(() => vfStops(props.options), [props.options]);
  const [mat, setMat] = useState<string>('');
  const [vfI, setVfI] = useState(0);
  const [mmI, setMmI] = useState(0);
  const [budgetMin, setBudgetMin] = useState(15);
  const defMat = props.settings?.bracket_material ?? props.options?.bracket_material ?? 'AlSi10Mg';
  const out = (): LayoutRunSettings => {
    const s: LayoutRunSettings = { material: mat || null, vol_frac: stops[vfI], min_member_mm: MEMBER_STOPS[mmI] };
    if (props.mode === 'one_piece') s.budget_s = Math.round(budgetMin * 60);
    return s;
  };
  const one = props.mode === 'one_piece';
  const e = props.estimate;
  return (
    <div className="small" data-testid={`run-form-${props.mode}`}>
      <div className="row" style={{ gap: 6 }}>
        <label htmlFor={`layout-mat-${props.mode}`} style={{ fontWeight: 600 }}>
          Material
        </label>
        <select id={`layout-mat-${props.mode}`} value={mat} onChange={(ev) => setMat(ev.target.value)} data-testid={`layout-material-${props.mode}`}>
          <option value="">Project default ({defMat})</option>
          {(props.options?.materials ?? [])
            .filter((m) => m.process === 'metal_am')
            .map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}
              </option>
            ))}
        </select>
      </div>
      <StopSlider
        id={`layout-vf-${props.mode}`}
        label={one ? 'Material used (share of the free space)' : 'Material used (share of the design space)'}
        stops={stops}
        index={vfI}
        onChange={setVfI}
        text={(s) => (s === 'auto' ? 'automatic (lightest passing: the FEA minimum)' : pctText(s))}
      />
      <StopSlider
        id={`layout-mm-${props.mode}`}
        label={one ? 'Minimum member thickness (filter, joins)' : 'Minimum member thickness'}
        stops={MEMBER_STOPS}
        index={mmI}
        onChange={setMmI}
        text={(s) => (s === 'auto' ? 'automatic' : `${s} mm`)}
        mark={{ value: props.options?.min_member_mm.am_min_wall_mm ?? 2, label: `AM minimum wall ${props.options?.min_member_mm.am_min_wall_mm ?? 2} mm` }}
      />
      {one ? (
        <div className="row" style={{ gap: 6, marginTop: 6 }}>
          <label htmlFor="layout-budget" style={{ fontWeight: 600 }}>
            Optimiser time budget
          </label>
          <input
            id="layout-budget"
            type="number"
            min={Math.ceil(props.budgetRange[0] / 60)}
            max={Math.floor(props.budgetRange[1] / 60)}
            value={budgetMin}
            onChange={(ev) => setBudgetMin(Math.max(1, Number(ev.target.value) || 1))}
            style={{ width: 70 }}
            data-testid="layout-budget"
          />
          <span>min per material-use step</span>
          <Button size="small" onClick={() => props.onEstimate?.(out())} disabled={props.running} data-testid="estimate-one-piece">
            Estimate time and memory
          </Button>
        </div>
      ) : null}
      {one && e ? (
        <Notice tone="info">
          <span data-testid="one-piece-estimate">
            About {secondsText(e.seconds_estimate)} for one material-use step (optimiser {secondsText(e.simp_seconds_estimate)}, FEA {secondsText(e.fe_seconds_estimate)}),
            peak memory about {(e.memory_mb_estimate / 1024).toFixed(1)} GB{e.available_mb != null ? ` (${(e.available_mb / 1024).toFixed(1)} GB available now)` : ''}; grid{' '}
            {e.grid.join(' × ')} voxels of {e.h_mm.map((h) => h.toFixed(2)).join(' × ')} mm, {e.free_voxels.toLocaleString()} free, {e.held_parts} parts held
            {e.kept_brackets.length ? `, ${e.kept_brackets.length} keep their own bracket (corner rail)` : ''}. {e.model}.
          </span>
        </Notice>
      ) : null}
      <div className="row" style={{ marginTop: 6 }}>
        <Button variant="primary" onClick={() => props.onStart(out())} disabled={props.running || (one && !e)} data-testid={`start-${props.mode}`}>
          {one ? 'Start the one piece' : 'Start combining'}
        </Button>
        {one && !e ? <span className="muted">estimate first</span> : null}
      </div>
    </div>
  );
}

/** Mounting Hardware tab: the comparison, the run forms and the choice for the saved STL files. */
export function BracketLayoutsPanel({
  layoutId,
  options,
  settings,
  names,
  onChanged,
}: {
  layoutId: string | null;
  options: DesignOptions | null;
  settings: Settings | null;
  names?: Record<string, string>;
  /** the layout's views changed (a layout chosen): reload them */
  onChanged?: () => void;
}) {
  const study = useApp((s) => s.solver.studies['bracket_design']);
  const runStatus = (study?.partial as { status?: string } | undefined)?.status;
  const running = runStatus === 'PENDING' || runStatus === 'RUNNING';
  const [refresh, setRefresh] = useState(0);
  const doneAt = runStatus === 'DONE' ? study?.at : null;
  const data = useAsync(layoutId ? () => session().api.bracketLayouts(layoutId) : null, [layoutId, doneAt, refresh]);
  const [open, setOpen] = useState<'combined' | 'one_piece' | null>(null);
  const [estimate, setEstimate] = useState<OnePieceEstimate | null>(null);
  const [msg, setMsg] = useState<{ tone: 'info' | 'err'; text: string } | null>(null);
  if (!layoutId) return <span className="muted small">No Stage 2 layout yet.</span>;
  if (data.notAvailable) return <span className="muted small">The bracket layouts (combined per wall, one piece) are computed by the backend (not available here).</span>;
  if (!data.data) return <span className="muted small">{data.error ? `Could not load: ${data.error}` : 'Loading…'}</span>;
  const d = data.data;
  const act = async (f: () => Promise<unknown>, text: string) => {
    setMsg(null);
    try {
      await f();
      setMsg({ tone: 'info', text });
      setRefresh((x) => x + 1);
      onChanged?.();
    } catch (e) {
      setMsg({ tone: 'err', text: `Could not start: ${(e as Error).message}` });
    }
  };
  return (
    <div data-testid="bracket-layouts">
      <BracketLayoutTable
        data={d}
        running={running}
        names={names}
        onRun={(m) => setOpen(open === m ? null : m)}
        onUse={(m) => act(() => session().api.useBracketLayout(layoutId, m), `${MODE_TITLE[m]} is now used for the 3D views, the bill of materials, the drawings, the fit proof and the saved STL files.`)}
      />
      {open ? (
        <div className="bracket-settings" style={{ marginTop: 8 }}>
          <LayoutRunForm
            mode={open}
            options={options}
            settings={settings}
            budgetRange={d.budget_range_s}
            running={running}
            estimate={open === 'one_piece' ? estimate : null}
            onEstimate={async (s) => {
              setMsg({ tone: 'info', text: 'Building the one piece’s design space to estimate its time and memory…' });
              try {
                setEstimate(await session().api.onePieceEstimate(layoutId, s));
                setMsg(null);
              } catch (e) {
                setMsg({ tone: 'err', text: `Could not estimate: ${(e as Error).message}` });
              }
            }}
            onStart={(s) =>
              act(
                () => session().api.runBracketLayout(layoutId, open, { settings: s }),
                open === 'combined'
                  ? 'Combining: each combined bracket is optimised in its member boxes and bridges and checked with CalculiX and NGSolve; the per-part brackets stay until you choose.'
                  : 'The one piece is being designed (exploratory): optimised in the free space, joined into one print and checked with CalculiX and NGSolve.',
              ).then(() => setOpen(null))
            }
          />
        </div>
      ) : null}
      {msg ? <Notice tone={msg.tone}>{msg.text}</Notice> : null}
      <ul className="small muted" style={{ margin: '6px 0 0 16px' }}>
        <li>
          Combined per wall: neighbouring metal 3D-printed brackets on one wall (or corner rail) are joined by bridging boxes that keep 1.2 mm from every other part, bracket and keep-out; each combined
          bracket holds its parts at their own mounting sides and is bolted with their bolts. No part is held only by another part (checked on the design and on the final mesh).
        </li>
        <li>
          One piece (exploratory): one print in the free space of the enclosure, bolted where the per-part brackets were (each part&apos;s wall or end plate, under its footprint), on voxels of about
          2.7 mm; the PC/104 boards stay on their rods. Its distance to the parts it holds is numeric (FCL), not proven.
        </li>
        <li>{d.build_volume_note}.</li>
      </ul>
    </div>
  );
}
