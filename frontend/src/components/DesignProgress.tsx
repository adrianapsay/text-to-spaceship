// V2: progress bars of the bracket design run (study 'bracket_design'), and the saved STL files of the designed layout
// (GET /api/saved-stl, pushed as saved_stl.updated).
import { Fragment, useEffect, useMemo, useState } from 'react';
import type { DesignProgress, DesignRow, SavedStl } from '../api/types';
import { session } from '../api/session';
import { useApp } from '../store/store';
import { useAsync, useParts } from '../hooks';
import { Badge, Button, Notice } from './ui';

const KIND_TEXT: Record<string, string> = {
  metal_am: 'metal 3D-printed',
  cradle: 'machined cradle',
  clamp: 'tube-clamp band',
  combined: 'combined, metal 3D-printed',
  one_piece: 'one piece (exploratory)',
  frame_check: 'frame, brackets and parts',
};
const RUN_WHAT: Record<string, string> = { per_part: 'the brackets', combined: 'the combined brackets', one_piece: 'the one piece' };
/** how long the Overview keeps the "designed" / "saved" / "brackets removed" note after the event */
export const NOTE_MS = 20000;

export function secondsText(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return '—';
  const r = Math.max(0, Math.round(s));
  return r < 60 ? `${r} s` : `${Math.floor(r / 60)} min ${String(r % 60).padStart(2, '0')} s`;
}

function timeText(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleTimeString();
}

/** A clock for the bars: ticks every second while `on`. */
function useNow(on: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [on]);
  return now;
}

export interface DesignRunView {
  run: DesignProgress;
  active: boolean;
  /** seconds since the run started, now */
  elapsed: number;
  /** estimated seconds left, now (null until one bracket is done) */
  eta: number | null;
  /** 0…1: the brackets done, plus the share of the mean design time the running ones have had (at most 90 %) */
  fraction: number;
  /** mean design time of the brackets done so far (s) */
  mean: number | null;
  total: number;
  done: number;
}

/** The run as the last update reported it, moved on to `now` (the update's server time is `at`). */
export function designRunView(run: DesignProgress | null | undefined, at: string | undefined, now: number): DesignRunView | null {
  if (!run || !Array.isArray(run.brackets)) return null;
  const active = run.status === 'PENDING' || run.status === 'RUNNING';
  const t0 = at ? Date.parse(at) : NaN;
  const age = active && Number.isFinite(t0) ? Math.max(0, now - t0) / 1000 : 0;
  const elapsed = (run.seconds ?? 0) + age;
  const times = run.brackets.filter((r) => r.status === 'done' && r.seconds != null).map((r) => r.seconds as number);
  const mean = times.length ? times.reduce((a, b) => a + b, 0) / times.length : null;
  const total = run.n_total ?? run.brackets.length;
  const done = run.n_done ?? run.brackets.filter((r) => r.status === 'done').length;
  let fraction = total ? done / total : 1;
  if (!active) fraction = 1;
  else if (mean && total) {
    const partial = run.brackets
      .filter((r) => r.status === 'running')
      .reduce((s, r) => s + Math.min(0.9, Math.max(0, elapsed - (r.started_s ?? 0)) / mean), 0);
    fraction = Math.min(0.99, (done + partial) / total);
  }
  const eta = !active ? 0 : run.eta_s == null ? null : Math.max(0, run.eta_s - age);
  return { run, active, elapsed, eta, fraction, mean, total, done };
}

function rowFraction(r: DesignRow, v: DesignRunView): number {
  if (r.status === 'done') return 1;
  if (r.status === 'queued') return 0;
  return v.mean ? Math.min(0.9, Math.max(0.05, (v.elapsed - (r.started_s ?? 0)) / v.mean)) : 0.15;
}

export function ProgressBar(props: { value: number; label: string; running?: boolean; tone?: 'ok' | 'err'; testId?: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, props.value)) * 100);
  return (
    <div
      className={`pbar ${props.tone ?? ''} ${props.running ? 'running' : ''}`}
      role="progressbar"
      aria-label={props.label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      data-testid={props.testId}
    >
      <div className="fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

function RowStatus({ r, elapsed }: { r: DesignRow; elapsed: number }) {
  if (r.status === 'queued') return <span className="muted">waiting</span>;
  if (r.status === 'running') return <span>{r.phase ? `${r.phase}… ` : 'designing… '}{secondsText(elapsed - (r.started_s ?? 0))}</span>;
  if (!r.solid) {
    // a whole-satellite check that did not run (memory) has no result; a design without a solid failed
    return (
      <span title={r.reason}>
        {r.kind === 'frame_check' ? <Badge tone="warn">not checked</Badge> : <Badge tone="err">no solid</Badge>} {secondsText(r.seconds)}
      </span>
    );
  }
  return (
    <span title={r.reason || undefined}>
      {r.mass_g != null ? `${r.mass_g.toFixed(1)} g · ` : ''}
      {secondsText(r.seconds)} {r.passed ? <Badge tone="ok">passed</Badge> : <Badge tone="err">failed</Badge>}
    </span>
  );
}

function useDesignRun() {
  const st = useApp((s) => s.solver.studies['bracket_design']);
  const run = (st?.partial ?? null) as DesignProgress | null;
  return { run, at: st?.at };
}

export function headline(v: DesignRunView): string {
  const id = v.run.layout_id ?? '';
  const what = RUN_WHAT[v.run.mode ?? 'per_part'] ?? 'the brackets';
  if (v.run.mode === 'frame_check') {
    if (v.active) return `Checking the whole satellite of ${id} · ${secondsText(v.elapsed)}`;
    return v.run.brackets.some((r) => r.solid)
      ? `Whole satellite of ${id} checked in ${secondsText(v.elapsed)}`
      : `Whole satellite of ${id} not checked (${secondsText(v.elapsed)})`;
  }
  if (!v.active) {
    const done = { per_part: 'Brackets', combined: 'Combined brackets', one_piece: 'One piece' }[v.run.mode ?? 'per_part'] ?? 'Brackets';
    return `${done} of ${id} designed: ${v.total} in ${secondsText(v.elapsed)}`;
  }
  const left = v.eta == null ? 'estimating the time left…' : `about ${secondsText(Math.ceil(v.eta / 5) * 5)} left`;
  return `Designing ${what} of ${id}: ${v.done} of ${v.total} done · ${secondsText(v.elapsed)} · ${left}`;
}

/** Mounting Hardware tab: the whole run, one bar per bracket. */
export function DesignProgressPanel() {
  const { run, at } = useDesignRun();
  const parts = useParts();
  const names = useMemo(() => Object.fromEntries(parts.map((p) => [p.id, p.name])), [parts]);
  const active = run?.status === 'PENDING' || run?.status === 'RUNNING';
  const now = useNow(active);
  const v = designRunView(run, at, now);
  if (!v) return null;
  const passed = v.run.brackets.filter((r) => r.status === 'done' && r.solid && r.passed).length;
  const failed = v.run.brackets.filter((r) => r.status === 'done' && !(r.solid && r.passed)).length;
  return (
    <div className="design-progress" data-testid="design-progress">
      <div className="small" style={{ marginBottom: 4 }}>
        <strong>{headline(v)}</strong>
        {!v.active ? (
          v.run.mode === 'frame_check' ? null : (
            <span>
              {' '}
              · {passed} passed{failed ? `, ${failed} failed` : ''}
            </span>
          )
        ) : v.run.workers ? (
          <span className="muted"> · {v.run.workers} at a time</span>
        ) : null}
      </div>
      <ProgressBar value={v.fraction} running={v.active} label="Bracket design run" testId="design-progress-bar" />
      <div className="design-rows" style={{ marginTop: 8 }}>
        {v.run.brackets.map((r) => (
          <Fragment key={r.k}>
            <span title={r.parts?.map((p) => names[p] ?? p).join(', ')}>
              {r.parts?.length ? `${r.label?.split(':')[0] ?? r.pid}: ${r.parts.map((p) => names[p] ?? p).join(', ')}` : r.label ?? names[r.pid] ?? r.pid}
            </span>
            <span className="muted">{KIND_TEXT[r.kind] ?? r.kind}</span>
            <ProgressBar
              value={rowFraction(r, v)}
              running={v.active && r.status === 'running'}
              tone={r.status === 'done' ? (r.solid && r.passed ? 'ok' : r.kind === 'frame_check' && !r.solid ? undefined : 'err') : undefined}
              label={`${names[r.pid] ?? r.pid}: ${r.status}`}
            />
            <RowStatus r={r} elapsed={v.elapsed} />
          </Fragment>
        ))}
      </div>
    </div>
  );
}

function savedSummary(m: SavedStl): string {
  const designed = (m.brackets ?? []).filter((b) => b.designed).length;
  return `${m.parts?.length ?? 0} parts + ${m.brackets?.length ?? 0} brackets${designed ? ` (${designed} designed)` : ''}`;
}

/** Overview: one line under the heading while the brackets are designed, and for a moment after the files change. */
export function DesignStrip() {
  const { run, at } = useDesignRun();
  const saved = useApp((s) => s.solver.savedStl);
  const savedAt = useApp((s) => s.solver.savedStlAt);
  const now = useNow(true);
  const v = designRunView(run, at, now);
  const recent = (iso: string | null | undefined) => !!iso && now - Date.parse(iso) < NOTE_MS;
  if (v?.active) {
    return (
      <div className="design-strip" role="status" data-testid="design-strip">
        <span>{headline(v)}</span>
        <ProgressBar value={v.fraction} running label="Bracket design run" />
        <span className="muted">details: Mounting Hardware</span>
      </div>
    );
  }
  if (saved && recent(savedAt) && saved.status !== 'none') {
    return (
      <div className={`design-strip ${saved.status === 'brackets_removed' ? 'warn' : 'ok'}`} role="status" data-testid="design-strip">
        {saved.status === 'complete' ? (
          <span>
            Saved as STL files: {saved.layout_id}, {savedSummary(saved)} — {saved.folder}
          </span>
        ) : (
          <span>
            Bracket STL files removed ({saved.brackets_removed?.reason ?? 'settings changed'}): they are saved again after the next bracket design run.
          </span>
        )}
      </div>
    );
  }
  if (v && run?.status === 'DONE' && recent(at)) {
    return (
      <div className="design-strip ok" role="status" data-testid="design-strip">
        <span>{headline(v)}</span>
      </div>
    );
  }
  return null;
}

/** Mounting Hardware tab: what the saved STL files hold, where they are, download / save now. */
export function SavedStlPanel({ layoutId }: { layoutId: string | null }) {
  const pushed = useApp((s) => s.solver.savedStl);
  const pushedAt = useApp((s) => s.solver.savedStlAt);
  const fetched = useAsync(() => session().api.savedStl(), [pushedAt]);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => setMsg((x) => (x?.startsWith('Saving') ? null : x)), [pushedAt]);   // the files were written
  const m = pushed ?? fetched.data;
  if (fetched.notAvailable && !pushed) {
    return <span className="muted small">The saved STL files are written by the backend (not available here).</span>;
  }
  const save = async () => {
    if (!layoutId) return;
    setMsg(null);
    try {
      await session().api.saveStl(layoutId);
      setMsg(`Saving the STL files of ${layoutId}…`);
    } catch (e) {
      setMsg(`Could not save: ${(e as Error).message}`);
    }
  };
  const download = async () => {
    try {
      await session().api.download(session().api.savedStlZipPath(), 'saved_stl.zip');
    } catch (e) {
      setMsg(`Could not download: ${(e as Error).message}`);
    }
  };
  const has = !!m && m.status !== 'none';
  const s = m?.settings;
  return (
    <div className="small" data-testid="saved-stl">
      {!m ? (
        <span className="muted">Loading…</span>
      ) : !has ? (
        <div className="muted">No saved STL files yet: they are written when a bracket design run finishes.</div>
      ) : (
        <>
          <div>
            <Badge tone={m.status === 'complete' ? 'ok' : 'warn'}>{m.status === 'complete' ? 'SAVED' : 'BRACKETS REMOVED'}</Badge> layout{' '}
            <strong>{m.layout_id}</strong> · {savedSummary(m)} · saved {timeText(m.saved_at)}
            {s ? (
              <span className="muted">
                {' '}
                · {s.form_factor}, part size {s.part_scale_pct} %, bracket budget {s.sliders?.bracket_budget ?? '—'}
              </span>
            ) : null}
          </div>
          <div className="muted" style={{ marginTop: 2 }}>
            {m.folder} — {m.assembly ?? 'assembly.stl'} (the whole assembly), parts\, brackets\, manifest.json
          </div>
          {m.status === 'brackets_removed' && m.brackets_removed ? (
            <Notice tone="warn">
              Bracket files removed at {timeText(m.brackets_removed.at)}: {m.brackets_removed.reason}. The parts are still saved; the brackets are saved
              again after the next bracket design run, or when the search pauses on a layout whose brackets were designed.
            </Notice>
          ) : null}
          {m.left_out?.length ? (
            <div className="muted" style={{ marginTop: 2 }}>
              Not saved (no real solid yet): {m.left_out.map((x) => `${x.part ?? x.part_id} (${KIND_TEXT[x.kind ?? ''] ?? x.kind})`).join(', ')}
            </div>
          ) : null}
        </>
      )}
      {m?.saving ? <div className="muted">Saving the STL files of {m.saving}…</div> : null}
      <div className="row" style={{ marginTop: 6, gap: 6 }}>
        <Button onClick={download} disabled={!has} data-testid="saved-stl-download">
          Download the saved STL files (zip)
        </Button>
        <Button onClick={save} disabled={!layoutId} data-testid="saved-stl-save">
          Save the STL files of {layoutId ?? 'this layout'} now
        </Button>
      </div>
      {msg ? <Notice tone={msg.startsWith('Could not') ? 'err' : 'info'}>{msg}</Notice> : null}
    </div>
  );
}
