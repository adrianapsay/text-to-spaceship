import { useMemo, useState } from 'react';
import type { SliderKey } from '../api/types';
import { session } from '../api/session';
import { COM_FIRST_HINT, COM_FIRST_NOTE, GOALS_CAPTION, SLIDERS, type SliderDef } from '../lib/copy';
import { normalisedWeights } from '../lib/physics';
import { activeGoalSliders, comFirstOn, PRESETS, type PresetId } from '../store/presets';
import { useApp } from '../store/store';
import { useAsync } from '../hooks';
import { Button, InfoTip } from './ui';
import { AlgorithmChip } from './AlgorithmChip';

export function valueText(v: number, def?: SliderDef): string {
  if (def?.ends) return `${v} of 100 (0 ${def.ends[0]}, 100 ${def.ends[1]})`;
  return `${v} percent priority`;
}

const FORM_FACTORS: { id: '3U' | '6U' | '12U'; size: string; com: string }[] = [
  { id: '3U', size: '100 × 100 × 340.5 mm', com: '±20 / ±20 / ±70 mm' },
  { id: '6U', size: '226.3 × 100 × 366 mm', com: '±45 / ±20 / ±70 mm' },
  { id: '12U', size: '226.3 × 226.3 × 366 mm', com: '±45 / ±45 / ±70 mm' },
];

/** V2 CubeSat size: the envelope and COM box (CDS Rev 14.1); changing it starts a new search. */
export function FormFactorControl() {
  const settings = useApp((s) => s.goals.settings);
  if (!settings) return null;
  const current = settings.form_factor ?? '3U';
  const ff = FORM_FACTORS.find((f) => f.id === current) ?? FORM_FACTORS[0];
  return (
    <div className="goal" data-testid="form-factor">
      <div className="goal-head">
        <span className="label" id="form-factor-label">
          CubeSat size
        </span>
        <InfoTip
          tip={{
            plain: 'Choose the CubeSat size to pack into. A bigger CubeSat gives the parts more room.',
            technical: 'CDS Rev 14.1 rail envelopes: 3U 100 × 100 × 340.5 mm, 6U 226.3 × 100 × 366 mm, 12U 226.3 × 226.3 × 366 mm (226.3 mm along X); COM box ±20/±20/±70, ±45/±20/±70, ±45/±45/±70 mm. Walls, corner rails and clearances as for 3U (ASSUMED).',
            why: 'if the parts do not fit a 3U, a 6U or 12U may hold them at full size.',
          }}
          label="CubeSat size"
        />
      </div>
      <div className="row" role="radiogroup" aria-labelledby="form-factor-label" style={{ gap: 6 }}>
        {FORM_FACTORS.map((f) => (
          <button
            key={f.id}
            type="button"
            role="radio"
            aria-checked={current === f.id}
            className={`btn small ${current === f.id ? 'primary' : ''}`}
            data-testid={`form-factor-${f.id}`}
            onClick={() => current !== f.id && session().patchSettings({ form_factor: f.id })}
          >
            {f.id}
          </button>
        ))}
      </div>
      <div className="goal-note">
        {ff.size}, COM box {ff.com}. Changing it starts a new search.
      </div>
    </div>
  );
}

/** V2 part-size slider (Stage 2): scales every part in all three axes; moving it starts a new search. */
export function PartSizeControl() {
  const settings = useApp((s) => s.goals.settings);
  const [draft, setDraft] = useState<number | null>(null);
  if (!settings || settings.stage !== 2) return null;
  const value = draft ?? Math.round(settings.part_scale_pct ?? 100);
  const commit = (v: number) => {
    setDraft(null);
    if (v !== Math.round(settings.part_scale_pct ?? 100)) session().patchSettings({ part_scale_pct: v });
  };
  return (
    <div className="goal" data-testid="part-size">
      <div className="goal-head">
        <label className="label" htmlFor="part-size-range">
          Part size
        </label>
        <InfoTip
          tip={{
            plain: 'Shrinks every part by the same factor in all three directions, to find a size that fits with all the engineering rules.',
            technical: 'geometry × s, volume and computed mass × s³, inertia × s⁵ (masses you entered are kept); the frame, clearances and brackets are not scaled. Each layout keeps the size it was found at.',
            why: 'at full size no layout may satisfy every Stage 2 rule; the slider shows how much smaller the parts would need to be.',
          }}
          label="Part size"
        />
        <span className="value" aria-hidden="true">
          {value} %
        </span>
      </div>
      <input
        id="part-size-range"
        className="range"
        type="range"
        min={50}
        max={100}
        step={1}
        value={value}
        aria-valuetext={`${value} percent of full size`}
        style={{ ['--fill' as string]: `${((value - 50) / 50) * 100}%` }}
        onChange={(e) => setDraft(Number(e.target.value))}
        onPointerUp={(e) => commit(Number((e.target as HTMLInputElement).value))}
        onKeyUp={(e) => {
          if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(e.key))
            commit(Number((e.target as HTMLInputElement).value));
        }}
      />
      <div className="goal-note">Stage 2 only. Moving it starts a new search; each layout keeps the size it was found at.</div>
      <LargestSizeFinder />
    </div>
  );
}

/** V2: bisection on the part size with a fixed-effort search per size (search-based, not a proof). */
function LargestSizeFinder() {
  const study = useApp((s) => s.solver.studies['largest_size']);
  const res = useAsync(() => session().api.largestSize(), [study?.progress, study?.at]);
  const [err, setErr] = useState<string | null>(null);
  const r = res.data;
  const running = !!r && (r.status === 'RUNNING' || r.status === 'PENDING');
  const run = async () => {
    setErr(null);
    try {
      await session().api.runLargestSize();
      res.reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <div className="row" style={{ marginTop: 6, flexWrap: 'wrap', gap: 6 }}>
      <Button size="small" onClick={run} disabled={running} data-testid="largest-size-run">
        {running ? `Searching… ${Math.round((r?.progress ?? 0) * 100)} %` : 'Find largest size that fits'}
      </Button>
      {r && r.status === 'DONE' ? (
        r.largest_pct != null ? (
          <>
            <span className="small" data-testid="largest-size-result">
              {r.largest_pct.toFixed(0)} % (search-based)
            </span>
            <Button size="small" onClick={() => session().patchSettings({ part_scale_pct: r.largest_pct! })} data-testid="largest-size-use">
              Use {r.largest_pct.toFixed(0)} %
            </Button>
          </>
        ) : (
          <span className="small">{r.verdict ?? 'no size found'}</span>
        )
      ) : null}
      {r?.status === 'ERROR' ? <span className="small">The search failed: {r.detail}</span> : null}
      {err ? <span className="small">{err}</span> : null}
    </div>
  );
}

export function GoalSlider(props: { def: SliderDef; value: number; disabled?: boolean; share?: number | null; onChange: (v: number, commit: boolean) => void; note?: string }) {
  const { def, value } = props;
  const id = `goal-${def.key}`;
  return (
    <div className={`goal ${props.disabled ? 'disabled' : ''}`} data-testid={id}>
      <div className="goal-head">
        <label className="label" htmlFor={id}>
          {def.label}
        </label>
        <InfoTip tip={def} label={def.label} />
        <span className="value" aria-hidden="true">
          {value}
        </span>
      </div>
      <input
        id={id}
        className="range"
        type="range"
        min={0}
        max={100}
        step={1}
        value={value}
        disabled={props.disabled}
        aria-valuetext={valueText(value, def)}
        aria-describedby={props.disabled || props.note ? `${id}-note` : undefined}
        style={{ ['--fill' as string]: `${value}%` }}
        onChange={(e) => props.onChange(Number(e.target.value), false)}
        onPointerUp={(e) => props.onChange(Number((e.target as HTMLInputElement).value), true)}
        onKeyUp={(e) => {
          if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(e.key))
            props.onChange(Number((e.target as HTMLInputElement).value), true);
        }}
      />
      {props.disabled && def.stage1Disabled ? (
        <div className="goal-note" id={`${id}-note`}>
          {def.stage1Disabled}
        </div>
      ) : props.note ? (
        <div className="goal-note" id={`${id}-note`}>
          {props.note}
        </div>
      ) : props.share != null ? (
        <div className="goal-note">share of the goals: {(props.share * 100).toFixed(0)} %</div>
      ) : null}
    </div>
  );
}

function cableModeNote(v: number, threshold = 70): string {
  if (v <= 0) return 'Mode: Default — channel interrupted beside the board stack (wiring ASSUMED through the stack connector).';
  if (v < threshold) return `Mode: Soft — blocked channel length counts against a layout (continuous-cable mode from ${threshold}).`;
  return 'Mode: Continuous-cable — full-length channel is a hard rule; boards may stand on edge only where mountable.';
}

/** Goal sliders + presets + algorithm chip. Edits go to the goals slice and `edit.settings` only. */
export function GoalsPanel(props: { showExpert?: boolean; compact?: boolean }) {
  const settings = useApp((s) => s.goals.settings);
  const preset = useApp((s) => s.goals.preset);
  const expert = useApp((s) => s.view.expert);
  const limits = useApp((s) => s.dataset.project?.limits);
  const hasOptional = useApp((s) => (s.dataset.project?.parts ?? []).some((p) => (p.tags ?? []).includes('optional')));
  const stage = settings?.stage ?? 1;
  const active = activeGoalSliders(stage);
  const weights = useMemo(() => (settings ? normalisedWeights(settings.sliders, active) : null), [settings, active]);
  if (!settings) return <div className="panel-body muted">Waiting for the project settings…</div>;
  const onChange = (k: SliderKey) => (v: number, commit: boolean) => session().setSlider(k, v, commit);
  const visible = SLIDERS.filter((d) => {
    if (d.notInGoals) return false;
    if (d.expertOnly && !(props.showExpert ?? expert)) return false;
    if (d.stage2Only && stage !== 2) return false;
    if (d.needsOptional && !hasOptional) return false;
    return true;
  });
  return (
    <div>
      <div className="panel-head">
        <h2>Goals</h2>
        <span className="caption">priorities, unitless — {GOALS_CAPTION}</span>
      </div>
      <div className="goal" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <label htmlFor="preset-select" style={{ fontWeight: 600 }}>
          Presets
        </label>
        <select
          id="preset-select"
          value={preset}
          onChange={(e) => session().setPreset(e.target.value as PresetId)}
          style={{ flex: 1 }}
        >
          {PRESETS.map((p) => (
            <option key={p.id} value={p.id} disabled={p.id === 'custom'}>
              {p.label}
            </option>
          ))}
        </select>
      </div>
      <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border-subtle)' }}>
        <AlgorithmChip />
      </div>
      <FormFactorControl />
      <PartSizeControl />
      {visible.map((def) => {
        const disabled = def.key === 'feasibility' && stage === 1;
        const share = weights && (active as string[]).includes(def.key) ? weights[def.key as keyof typeof weights] : null;
        const note =
          def.key === 'cable'
            ? cableModeNote(settings.sliders.cable, (limits?.cable_mode_threshold as number | undefined) ?? 70)
            : def.key === 'balance' && stage === 2 && settings.sliders.balance >= 100
              ? comFirstOn(settings.sliders, stage)
                ? COM_FIRST_NOTE
                : COM_FIRST_HINT
              : undefined;
        return <GoalSlider key={def.key} def={def} value={settings.sliders[def.key] ?? (def.key === 'optional_parts' ? 75 : 50)} disabled={disabled} share={share} onChange={onChange(def.key)} note={note} />;
      })}
    </div>
  );
}
