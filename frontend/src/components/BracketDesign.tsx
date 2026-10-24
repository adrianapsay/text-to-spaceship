// V2 (WS4): what the bracket designs are set to. Project-wide: the launch environment the brackets are checked under
// and the default AM material (Mounting Hardware tab, "Design settings"). Per bracket: its material, the material
// used (volume fraction of its reserved box) and the minimum member thickness, each with its minimum (the FEA
// minimum from the automatic run's ladder; the AM minimum wall), "Redesign this bracket", and the design's margins
// per load case under the launch environment (backend gd.evaluate.score).
import { useEffect, useMemo, useState } from 'react';
import type {
  BracketDesign,
  BracketInfo,
  BracketMargin,
  BracketOverride,
  DesignOptions,
  LadderRung,
  LaunchEnvironment,
  Settings,
} from '../api/types';
import { session } from '../api/session';
import { Badge, Button, Notice } from './ui';

type Stop = 'auto' | number;

/** Stops of the material-used slider: "auto" (the automatic run: the ladder, lightest first, stops at the first
 * passing rung), the ladder's rungs, and 60 % when the allowed range reaches it. */
export function vfStops(o: DesignOptions | null | undefined): Stop[] {
  const ladder = o?.vol_frac.ladder ?? [0.03, 0.05, 0.08, 0.12, 0.2, 0.3, 0.45];
  const hi = o?.vol_frac.range[1] ?? 0.8;
  return ['auto', ...ladder, ...(hi >= 0.6 && !ladder.includes(0.6) ? [0.6] : [])];
}

/** Stops of the minimum-member-thickness slider (mm). */
export const MEMBER_STOPS: Stop[] = ['auto', 1.5, 2, 2.5, 3, 4, 5, 6, 8];

/** Index of a stored value on a slider's stops (the nearest stop; 0 for "auto" or nothing set). */
export function stopIndex(stops: Stop[], v: Stop | null | undefined): number {
  if (v == null || v === 'auto') return 0;
  let best = 0;
  let bd = Infinity;
  stops.forEach((s, i) => {
    if (s !== 'auto' && Math.abs(s - v) < bd) {
      bd = Math.abs(s - v);
      best = i;
    }
  });
  return best;
}

export function pctText(v: number | null | undefined): string {
  return v == null ? '—' : `${Math.round(100 * v)} %`;
}

function signed(v: number | null | undefined): string {
  return v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2);
}

/** "random qualification, y, yield" — the gating check with the smallest margin. */
export function governingText(g: BracketDesign['governing'] | null | undefined): string {
  if (!g) return '—';
  return `${g.case}, ${g.axis}, ${g.part === 'bolt' ? `bolt ${g.check}` : g.check}`;
}

/** Why a design no longer matches the settings (another launch environment, another material), else null. The
 * backend designs such brackets again when the search is paused and automatic design is on. */
export function outdatedText(b: BracketInfo, d: BracketDesign | undefined, ov: BracketOverride | undefined, env: string, mat: string, envName?: string): string | null {
  if (!d) return null;
  if (d.environment !== env) {
    return d.environment
      ? `designed for ${d.environment_name ?? d.environment}, not ${envName ?? env}`
      : `designed before the launch environments (old loads), not for ${envName ?? env}`;
  }
  const want = ov?.material || mat;
  if (b.kind === 'metal_am' && d.material !== want) return `designed in ${d.material ?? 'another material'}, not ${want}`;
  return null;
}

/** The lightest passing material use known for a design: its own automatic run, or one carried over. */
export function feaMinimum(d: BracketDesign | undefined): number | null {
  return d?.min_vol_frac ?? null;
}

/** The slider's note on the FEA minimum: when the lightest rung tried already passed, the minimum is that or less. */
export function feaMinimumText(minVf: number, stops: Stop[], carried: boolean): string {
  const lightest = stops.find((s): s is number => s !== 'auto');
  const from = carried ? ' (from an earlier automatic run)' : '';
  return minVf === lightest
    ? `FEA minimum ${pctText(minVf)} or less: the lightest material use tried passed every check${from}`
    : `FEA minimum ${pctText(minVf)}: the lightest material use that passed every check${from}`;
}

function rungsOf(d: BracketDesign | undefined): LadderRung[] {
  return d?.auto_ladder ?? d?.ladder ?? [];
}

// ------------------------------------------------------------------------------------------------ project-wide

function factorText(f: { yield: number; ultimate: number }): string {
  return `${f.yield.toFixed(2)} / ${f.ultimate.toFixed(2)}`;
}

export function EnvironmentSummary({ e }: { e: LaunchEnvironment }) {
  return (
    <ul className="small" style={{ margin: '4px 0 0 16px' }} data-testid="environment-summary">
      <li>
        Random vibration: limit {e.random_limit.grms.toFixed(1)} Grms, qualification {e.random_qual.grms.toFixed(1)} Grms (
        <span className="muted">{e.random_qual.source}</span>).
      </li>
      <li>
        Factors on the limit level (yield / ultimate): {Object.entries(e.factors).map(([k, f]) => `${k} ${factorText(f)}`).join(', ')}; the qualification level
        is checked at {factorText(e.qual_factors)}
        {e.analysis_only ? ' (qualified by analysis only: higher factors)' : ''}.
      </li>
      <li>
        Quasi-static: <span className="muted">{e.static}</span>
      </li>
      <li>{e.sine ? `Sine: ${e.sine.level_g} g, ${e.sine.f_lo}–${e.sine.f_hi} Hz.` : e.sine_note}</li>
      <li>Shock: {e.shock ? 'checked as an ESTIMATE (reported, not a pass criterion).' : e.shock_note}</li>
      <li>
        First natural frequency ≥ {e.f1_guidance_hz} Hz: <span className="muted">{e.f1_source}</span>
      </li>
      {e.notes.map((n) => (
        <li key={n}>{n}</li>
      ))}
    </ul>
  );
}

/** Launch environment and default AM material of the project (settings launch_environment, bracket_material). */
export function DesignSettings({ options, settings, notAvailable }: { options: DesignOptions | null; settings: Settings | null; notAvailable?: boolean }) {
  const [open, setOpen] = useState(false);
  if (!options) return <span className="muted small">{notAvailable ? 'The backend does not provide bracket design settings.' : 'Loading…'}</span>;
  const env = settings?.launch_environment ?? options.launch_environment;
  const mat = settings?.bracket_material ?? options.bracket_material;
  const E = options.environments.find((x) => x.id === env);
  return (
    <div className="small" data-testid="design-settings">
      <div className="row">
        <label htmlFor="launch-environment" style={{ fontWeight: 600 }}>
          Launch environment
        </label>
        <select id="launch-environment" value={env} onChange={(ev) => session().patchSettings({ launch_environment: ev.target.value })} data-testid="launch-environment">
          {options.environments.map((x) => (
            <option key={x.id} value={x.id}>
              {x.name}
            </option>
          ))}
        </select>
        <Button size="small" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? 'Hide details' : 'Details'}
        </Button>
      </div>
      {E && open ? <EnvironmentSummary e={E} /> : null}
      <div className="row" style={{ marginTop: 6 }}>
        <label htmlFor="bracket-material" style={{ fontWeight: 600 }}>
          Default material (metal 3D-printed)
        </label>
        <select id="bracket-material" value={mat} onChange={(ev) => session().patchSettings({ bracket_material: ev.target.value })} data-testid="bracket-material">
          {options.materials
            .filter((m) => m.process === 'metal_am')
            .map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}: yield {m.yield_mpa} MPa, ultimate {m.ultimate_mpa} MPa, {m.density_g_cm3.toFixed(2)} g/cm³
              </option>
            ))}
        </select>
      </div>
      <div className="muted" style={{ marginTop: 4 }}>
        Cradles and clamp bands are machined {options.machined}. Material values: {options.allowables}. Brackets designed for another environment or
        material are designed again when the search is paused (automatic design on), or with Redesign.
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ per bracket

export function StopSlider(props: {
  id: string;
  label: string;
  stops: Stop[];
  index: number;
  onChange: (i: number) => void;
  text: (s: Stop) => string;
  /** stop marked as the minimum (FEA or AM), with its label */
  mark?: { value: number; label: string } | null;
  disabled?: boolean;
}) {
  const { stops, index } = props;
  const max = stops.length - 1;
  const markI = props.mark ? stopIndex(stops, props.mark.value) : null;
  return (
    <div className="stop-slider" data-testid={props.id}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <label htmlFor={props.id} style={{ fontWeight: 600 }}>
          {props.label}
        </label>
        <span className="num">{props.text(stops[index])}</span>
      </div>
      <input
        id={props.id}
        className="range"
        type="range"
        min={0}
        max={max}
        step={1}
        value={index}
        disabled={props.disabled}
        aria-valuetext={props.text(stops[index])}
        style={{ ['--fill' as string]: `${(100 * index) / Math.max(1, max)}%` }}
        onChange={(ev) => props.onChange(Number(ev.target.value))}
      />
      <div className="stop-ticks" aria-hidden="true">
        {stops.map((s, i) => (
          <span key={String(s)} className={`${i === markI ? 'mark' : ''} ${i === index ? 'on' : ''}`} style={{ left: `${(100 * i) / Math.max(1, max)}%` }}>
            {s === 'auto' ? 'auto' : props.text(s).replace(' mm', '')}
          </span>
        ))}
      </div>
      {props.mark ? <div className="small muted">▲ {props.mark.label}</div> : null}
    </div>
  );
}

function LadderChips({ rungs, min }: { rungs: LadderRung[]; min: number | null }) {
  if (!rungs.length || rungs.every((r) => r.vol_frac == null)) return null;
  return (
    <div className="row small" style={{ gap: 4 }} data-testid="ladder">
      <span className="muted">Automatic run:</span>
      {rungs.map((r) => (
        <Badge
          key={String(r.vol_frac)}
          tone={r.passed ? 'ok' : 'err'}
          title={[r.reason, r.governing ? `governing: ${governingText(r.governing)}` : ''].filter(Boolean).join('\n') || undefined}
        >
          {pctText(r.vol_frac)} {r.passed ? '✓' : '✗'}
          {r.mass_g != null ? ` ${r.mass_g.toFixed(1)} g` : ''}
          {r.vol_frac === min ? ' (FEA min)' : ''}
        </Badge>
      ))}
    </div>
  );
}

export function MarginsTable({ margins }: { margins: Record<string, BracketMargin> }) {
  const rows = Object.entries(margins);
  if (!rows.length) return null;
  return (
    <table className="data" data-testid="margins-table">
      <thead>
        <tr>
          <th>Load case</th>
          <th>Axis</th>
          <th className="num">MS yield</th>
          <th className="num">MS ultimate</th>
          <th>Counts toward pass</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([k, m]) => (
          <tr key={k}>
            <td>{k}</td>
            <td>{m.axis}</td>
            {m.ms != null ? (
              <td className="num" colSpan={2}>
                <Badge tone={m.ms >= 0 ? 'ok' : 'err'}>{signed(m.ms)}</Badge> <span className="muted small">{m.check}{m.bolt != null ? `, bolt ${m.bolt + 1}` : ''}</span>
              </td>
            ) : (
              <>
                <td className="num">
                  <Badge tone={(m.ms_yield ?? 0) >= 0 ? 'ok' : 'err'}>{signed(m.ms_yield)}</Badge>
                </td>
                <td className="num">
                  <Badge tone={(m.ms_ult ?? 0) >= 0 ? 'ok' : 'err'}>{signed(m.ms_ult)}</Badge>
                </td>
              </>
            )}
            <td className="small">{m.gates ? 'yes' : <span className="muted">reported only (ESTIMATE)</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** One bracket's settings and results (a row of the Brackets table opened). */
export function BracketSettings(props: {
  layoutId: string;
  b: BracketInfo;
  d?: BracketDesign;
  ov?: BracketOverride;
  options: DesignOptions | null;
  settings: Settings | null;
  /** a design run is under way (one at a time) */
  running: boolean;
  onStarted?: (text: string) => void;
}) {
  const { b, d, ov, options } = props;
  const am = b.kind === 'metal_am';
  const defMat = props.settings?.bracket_material ?? options?.bracket_material ?? 'AlSi10Mg';
  const stops = useMemo(() => vfStops(options), [options]);
  const [mat, setMat] = useState<string | null>(ov?.material ?? null);
  const [vfI, setVfI] = useState(() => stopIndex(stops, ov?.vol_frac));
  const [mmI, setMmI] = useState(() => stopIndex(MEMBER_STOPS, ov?.min_member_mm));
  const [msg, setMsg] = useState<{ tone: 'info' | 'err'; text: string } | null>(null);
  useEffect(() => {
    // the stored settings changed (a run started here or elsewhere): show them
    setMat(ov?.material ?? null);
    setVfI(stopIndex(stops, ov?.vol_frac));
    setMmI(stopIndex(MEMBER_STOPS, ov?.min_member_mm));
  }, [ov?.material, ov?.vol_frac, ov?.min_member_mm, stops]);
  const minVf = feaMinimum(d);
  const minWall = options?.min_member_mm.am_min_wall_mm ?? d?.am_min_wall_mm ?? 2;
  const vf = stops[vfI];
  const mm = MEMBER_STOPS[mmI];
  const below = typeof vf === 'number' && minVf != null && vf < minVf;
  const thin = typeof mm === 'number' && mm < minWall;
  const sameMaterialAsDesign = (mat || defMat) === d?.settings?.material;
  const redesign = async () => {
    setMsg(null);
    const o: BracketOverride = { vol_frac: vf, min_member_mm: mm };
    if (am) o.material = mat;
    try {
      await session().api.designBrackets(props.layoutId, { pids: [b.pid], overrides: { [b.pid]: o } });
      const text = `Redesigning this bracket: ${am ? `${mat || defMat}, ` : ''}material used ${vf === 'auto' ? 'automatic' : pctText(vf)}, minimum member ${mm === 'auto' ? 'automatic' : `${mm} mm`}.`;
      setMsg({ tone: 'info', text });
      props.onStarted?.(text);
    } catch (e) {
      setMsg({ tone: 'err', text: `Could not start: ${(e as Error).message}` });
    }
  };
  return (
    <div className="bracket-settings" data-testid={`bracket-settings-${b.pid}`}>
      <div className="grid-2">
        <div>
          {am ? (
            <div className="row small" style={{ marginBottom: 6 }}>
              <label htmlFor={`mat-${b.pid}`} style={{ fontWeight: 600 }}>
                Material
              </label>
              <select id={`mat-${b.pid}`} value={mat ?? ''} onChange={(ev) => setMat(ev.target.value || null)} data-testid={`material-${b.pid}`}>
                <option value="">Project default ({defMat})</option>
                {(options?.materials ?? [])
                  .filter((m) => m.process === 'metal_am')
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.id}
                    </option>
                  ))}
              </select>
            </div>
          ) : (
            <div className="small" style={{ marginBottom: 6 }}>
              <strong>Material:</strong> machined {options?.machined ?? '6061-T6'} (rule-based shape: the material used follows the rule; the minimum member
              thickness thickens the bolted plate and the contact skin).
            </div>
          )}
          {am ? (
            <StopSlider
              id={`vf-${b.pid}`}
              label="Material used (share of the reserved box)"
              stops={stops}
              index={vfI}
              onChange={setVfI}
              text={(s) => (s === 'auto' ? 'automatic (lightest passing)' : pctText(s))}
              mark={minVf != null && sameMaterialAsDesign ? { value: minVf, label: feaMinimumText(minVf, stops, !!d?.min_vol_frac_carried) } : null}
            />
          ) : null}
          {am && minVf == null && d ? (
            <div className="small muted">FEA minimum not known yet: choose automatic and redesign to find it.</div>
          ) : null}
          {am && minVf != null && !sameMaterialAsDesign ? (
            <div className="small muted">The FEA minimum {pctText(minVf)} was found for {d?.settings?.material}: another material needs an automatic run.</div>
          ) : null}
          <div style={{ marginTop: 8 }}>
            <StopSlider
              id={`mm-${b.pid}`}
              label="Minimum member thickness"
              stops={MEMBER_STOPS}
              index={mmI}
              onChange={setMmI}
              text={(s) => (s === 'auto' ? 'automatic' : `${s} mm`)}
              mark={{ value: minWall, label: `AM minimum wall ${minWall} mm (structural walls, L-PBF)` }}
            />
          </div>
          {below ? <Notice tone="warn">Below the FEA minimum ({pctText(minVf)}): the design is expected to fail a check; it is designed and flagged with the failing case.</Notice> : null}
          {thin ? <Notice tone="warn">Thinner than the {minWall} mm AM minimum wall: flagged as not printable as is.</Notice> : null}
          {am && options && !options.min_member_mm.generator_sets_member_size ? (
            <div className="small muted">The design generator ({options.generator}) has no member-size setting: only the bolted plate and the contact skin are thickened.</div>
          ) : null}
          <div className="row" style={{ marginTop: 8 }}>
            <Button variant="primary" onClick={redesign} disabled={props.running} data-testid={`redesign-${b.pid}`}>
              Redesign this bracket
            </Button>
            {props.running ? <span className="small muted">a design run is under way</span> : null}
          </div>
          {msg ? <Notice tone={msg.tone}>{msg.text}</Notice> : null}
        </div>
        <div className="small">
          {d ? (
            <>
              <div>
                <strong>Designed:</strong> {d.material_name ?? d.material ?? '—'} · {d.environment_name ?? d.environment ?? 'loads before the launch environments'}
                {d.settings ? ` · material used ${d.settings.vol_frac === 'auto' ? `automatic${d.vol_frac != null ? ` (${pctText(d.vol_frac)})` : ''}` : pctText(d.settings.vol_frac)}` : ''}
                {d.settings ? ` · member ${d.settings.min_member_mm === 'auto' ? 'automatic' : `${d.settings.min_member_mm} mm`}` : ''}
              </div>
              <div>
                Thinnest generated member {d.member_mm != null ? `${d.member_mm.toFixed(1)} mm` : d.member_why ? `— (${d.member_why})` : '—'}
                {d.plate_mm != null ? ` · bolted plate ${d.plate_mm.toFixed(1)} mm` : ''}
                {d.skin_mm != null ? ` · contact skin ${d.skin_mm.toFixed(1)} mm` : ''}
                {d.member_mm != null && d.member_mm < minWall ? <Badge tone="warn">below {minWall} mm</Badge> : null}
              </div>
              <div>
                Governing: {governingText(d.governing)} {d.governing ? <Badge tone={d.governing.ms >= 0 ? 'ok' : 'err'}>MS {signed(d.governing.ms)}</Badge> : null}
              </div>
              {d.member_note ? <div className="muted">{d.member_note}</div> : null}
              {d.reason ? <div className="muted">Failed: {d.reason}</div> : null}
              {d.fallback ? <div className="muted">{d.fallback}</div> : null}
              <LadderChips rungs={rungsOf(d)} min={minVf} />
              {d.margins ? <MarginsTable margins={d.margins} /> : <div className="muted">No per-case margins (designed before the launch environments).</div>}
              {d.flags?.length ? (
                <ul style={{ margin: '4px 0 0 16px' }} data-testid="design-flags">
                  {d.flags.map((f, i) => (
                    <li key={`${f.code}-${i}`} title={f.source}>
                      <Badge tone={f.code === 'thin_members' || f.code === 'shock_estimate' ? 'warn' : 'neutral'}>{f.code}</Badge> {f.text}
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : (
            <span className="muted">Not designed yet: the box is the reserved space.</span>
          )}
        </div>
      </div>
    </div>
  );
}
