import { useMemo } from 'react';
import type { SliderKey } from '../api/types';
import { session } from '../api/session';
import { GOALS_CAPTION, SLIDERS, type SliderDef } from '../lib/copy';
import { normalisedWeights } from '../lib/physics';
import { activeGoalSliders, PRESETS, type PresetId } from '../store/presets';
import { useApp } from '../store/store';
import { InfoTip } from './ui';
import { AlgorithmChip } from './AlgorithmChip';

export function valueText(v: number): string {
  return `${v} percent priority`;
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
        aria-valuetext={valueText(value)}
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
  const stage = settings?.stage ?? 1;
  const active = activeGoalSliders(stage);
  const weights = useMemo(() => (settings ? normalisedWeights(settings.sliders, active) : null), [settings, active]);
  if (!settings) return <div className="panel-body muted">Waiting for the project settings…</div>;
  const onChange = (k: SliderKey) => (v: number, commit: boolean) => session().setSlider(k, v, commit);
  const visible = SLIDERS.filter((d) => {
    if (d.expertOnly && !(props.showExpert ?? expert)) return false;
    if (d.stage2Only && stage !== 2) return false;
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
      {visible.map((def) => {
        const disabled = def.key === 'feasibility' && stage === 1;
        const share = weights && (active as string[]).includes(def.key) ? weights[def.key as keyof typeof weights] : null;
        const note = def.key === 'cable' ? cableModeNote(settings.sliders.cable, (limits?.cable_mode_threshold as number | undefined) ?? 70) : undefined;
        return <GoalSlider key={def.key} def={def} value={settings.sliders[def.key]} disabled={disabled} share={share} onChange={onChange(def.key)} note={note} />;
      })}
    </div>
  );
}
