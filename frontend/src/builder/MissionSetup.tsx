// V3 CubeSat Builder — Mission Setup: the adaptive questionnaire as a conversation. The current question offers its
// options, "I don't know" (which takes the default the question explains) and "Why this matters"; the requirements
// panel lists every value set so far with where it came from (you, your description, a default, or derived).
import { useEffect, useState } from 'react';
import type { BuilderResponse, BuilderView, Finding, QuestionView, Requirement, ReqSource } from './types';
import { Badge, Button, NumberField, Panel } from '../components/ui';

export const SOURCE_TEXT: Record<ReqSource, string> = {
  user: 'You',
  statement: 'From your description',
  default: 'Default (ASSUMED)',
  derived: 'Derived',
};
const SOURCE_TONE: Record<ReqSource, 'ok' | 'accent' | 'warn' | 'neutral'> = { user: 'ok', statement: 'accent', default: 'warn', derived: 'neutral' };

export function SourceBadge({ source, title }: { source: ReqSource; title?: string }) {
  return (
    <Badge tone={SOURCE_TONE[source]} title={title}>
      {SOURCE_TEXT[source]}
    </Badge>
  );
}

/** The default a question takes on "I don't know", in words. */
export function defaultText(q: QuestionView): string {
  const d = q.default;
  if (d == null) return 'no value (decided later)';
  if (q.kind === 'choice') return q.options.find((o) => o.value === d)?.label ?? String(d);
  if (q.kind === 'multi' && Array.isArray(d)) return d.map((x) => q.options.find((o) => o.value === x)?.label ?? String(x)).join(', ');
  if (q.kind === 'number') return `${d}${q.unit ? ` ${q.unit}` : ''}`;
  if (q.kind === 'bool') return d ? 'Yes' : 'No';
  if (q.kind === 'region' || q.kind === 'station') return q.options.find((o) => o.value === d)?.label ?? String(d);
  return String(d);
}

function BoxEditor(props: { onSubmit: (v: Record<string, number>) => void; busy: boolean }) {
  const [b, setB] = useState({ lat_min: 32.5, lat_max: 42.0, lon_min: -124.4, lon_max: -114.1 });
  const field = (k: keyof typeof b, label: string, min: number, max: number) => (
    <label className="row small" style={{ gap: 4 }}>
      {label}
      <NumberField value={b[k]} onCommit={(v) => setB((x) => ({ ...x, [k]: v }))} label={label} min={min} max={max} unit="°" width={80} />
    </label>
  );
  return (
    <div className="stack" style={{ gap: 6 }} data-testid="box-editor">
      <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
        {field('lat_min', 'South', -90, 90)}
        {field('lat_max', 'North', -90, 90)}
        {field('lon_min', 'West', -180, 180)}
        {field('lon_max', 'East', -180, 180)}
      </div>
      <Button size="small" variant="primary" disabled={props.busy} onClick={() => props.onSubmit(b)}>
        Use this box
      </Button>
    </div>
  );
}

function StationEditor(props: { onSubmit: (v: Record<string, number>) => void; busy: boolean }) {
  const [s, setS] = useState({ lat: 37.87, lon: -122.26, min_elev_deg: 10 });
  return (
    <div className="stack" style={{ gap: 6 }} data-testid="station-editor">
      <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
        <label className="row small" style={{ gap: 4 }}>
          Latitude
          <NumberField value={s.lat} onCommit={(v) => setS((x) => ({ ...x, lat: v }))} label="Latitude" min={-90} max={90} unit="°" width={80} />
        </label>
        <label className="row small" style={{ gap: 4 }}>
          Longitude
          <NumberField value={s.lon} onCommit={(v) => setS((x) => ({ ...x, lon: v }))} label="Longitude" min={-180} max={180} unit="°" width={80} />
        </label>
        <label className="row small" style={{ gap: 4 }}>
          Elevation mask
          <NumberField value={s.min_elev_deg} onCommit={(v) => setS((x) => ({ ...x, min_elev_deg: v }))} label="Elevation mask" min={0} max={89} unit="°" width={60} />
        </label>
      </div>
      <Button size="small" variant="primary" disabled={props.busy} onClick={() => props.onSubmit(s)}>
        Use this station
      </Button>
    </div>
  );
}

/** One question with the input its kind needs, "I don't know" and "Why this matters". */
export function QuestionCard(props: { q: QuestionView; busy: boolean; onAnswer: (value: unknown) => void; onUnknown: () => void; onCancel?: () => void }) {
  const { q } = props;
  const [multi, setMulti] = useState<unknown[]>(Array.isArray(q.answer?.value) ? (q.answer?.value as unknown[]) : Array.isArray(q.default) ? (q.default as unknown[]) : []);
  const [num, setNum] = useState<number | null>(typeof q.answer?.value === 'number' ? (q.answer.value as number) : typeof q.default === 'number' ? (q.default as number) : null);
  const [custom, setCustom] = useState(false);
  useEffect(() => {
    setMulti(Array.isArray(q.answer?.value) ? (q.answer?.value as unknown[]) : Array.isArray(q.default) ? (q.default as unknown[]) : []);
    setNum(typeof q.answer?.value === 'number' ? (q.answer.value as number) : typeof q.default === 'number' ? (q.default as number) : null);
    setCustom(false);
  }, [q.id, q.answer, q.default]);
  const choices = (
    <div className="bq-options" role="group" aria-label={q.prompt}>
      {q.options
        .filter((o) => !(q.kind === 'region' || q.kind === 'station') || o.value !== 'custom')
        .map((o) => (
          <button key={String(o.value)} type="button" className="bq-option" disabled={props.busy} onClick={() => props.onAnswer(o.value)} data-testid={`opt-${String(o.value)}`}>
            <strong>{o.label}</strong>
            {o.explain ? <span className="muted small">{o.explain}</span> : null}
          </button>
        ))}
      {q.kind === 'region' || q.kind === 'station' ? (
        <button type="button" className="bq-option" onClick={() => setCustom((v) => !v)} aria-pressed={custom}>
          <strong>{q.options.find((o) => o.value === 'custom')?.label ?? 'Somewhere else'}</strong>
        </button>
      ) : null}
    </div>
  );
  let input: React.ReactNode = null;
  if (q.kind === 'choice' || q.kind === 'region' || q.kind === 'station') input = choices;
  else if (q.kind === 'bool')
    input = (
      <div className="bq-options" role="group" aria-label={q.prompt}>
        <button type="button" className="bq-option" disabled={props.busy} onClick={() => props.onAnswer(true)} data-testid="opt-yes">
          <strong>Yes</strong>
        </button>
        <button type="button" className="bq-option" disabled={props.busy} onClick={() => props.onAnswer(false)} data-testid="opt-no">
          <strong>No</strong>
        </button>
      </div>
    );
  else if (q.kind === 'multi')
    input = (
      <div className="stack" style={{ gap: 6 }}>
        <div className="bq-checks" role="group" aria-label={q.prompt}>
          {q.options.map((o) => (
            <label key={String(o.value)} className="row" style={{ gap: 6, alignItems: 'flex-start' }}>
              <input
                type="checkbox"
                checked={multi.includes(o.value)}
                onChange={(e) => setMulti((m) => (e.target.checked ? [...m, o.value] : m.filter((x) => x !== o.value)))}
                data-testid={`check-${String(o.value)}`}
              />
              <span>
                {o.label}
                {o.explain ? <span className="muted small"> — {o.explain}</span> : null}
              </span>
            </label>
          ))}
        </div>
        <Button size="small" variant="primary" disabled={props.busy || !multi.length} onClick={() => props.onAnswer(multi)} data-testid="multi-continue">
          Continue
        </Button>
      </div>
    );
  else if (q.kind === 'number')
    input = (
      <div className="stack" style={{ gap: 6 }}>
        {q.options.length ? (
          <div className="bq-options" role="group" aria-label={`${q.prompt} (presets)`}>
            {q.options.map((o) => (
              <button key={String(o.value)} type="button" className="bq-option" disabled={props.busy} onClick={() => props.onAnswer(o.value)} data-testid={`opt-${String(o.value)}`}>
                <strong>{o.label}</strong>
                {o.explain ? <span className="muted small">{o.explain}</span> : null}
              </button>
            ))}
          </div>
        ) : null}
        <div className="row" style={{ gap: 8 }}>
          <NumberField value={num} onCommit={setNum} label={q.prompt} min={q.min ?? undefined} max={q.max ?? undefined} unit={q.unit ?? undefined} id={`num-${q.id}`} />
          <Button size="small" variant="primary" disabled={props.busy || num == null} onClick={() => props.onAnswer(num)} data-testid="number-continue">
            Continue
          </Button>
        </div>
      </div>
    );
  return (
    <div className="bq-card" data-testid={`question-${q.id}`}>
      <div className="row" style={{ gap: 8, alignItems: 'baseline' }}>
        <h3 style={{ margin: 0 }}>{q.prompt}</h3>
        {q.advanced ? <Badge tone="neutral">expert</Badge> : null}
      </div>
      <details className="small" style={{ margin: '4px 0 8px' }}>
        <summary>Why this matters</summary>
        <p style={{ margin: '4px 0' }}>{q.help}</p>
      </details>
      {input}
      {custom && q.kind === 'region' ? <BoxEditor busy={props.busy} onSubmit={props.onAnswer} /> : null}
      {custom && q.kind === 'station' ? <StationEditor busy={props.busy} onSubmit={props.onAnswer} /> : null}
      <div className="row small" style={{ gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
        <Button size="small" disabled={props.busy} onClick={props.onUnknown} data-testid="dont-know">
          I don't know
        </Button>
        <span className="muted">
          Then: <strong>{defaultText(q)}</strong> — {q.default_why}
        </span>
        {props.onCancel ? (
          <Button size="small" onClick={props.onCancel}>
            Cancel
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/** Every requirement set so far, by section, with where its value came from. */
export function RequirementsPanel(props: { view: BuilderView; onEdit: (qid: string) => void; busy: boolean }) {
  const { view } = props;
  const bySection = new Map<string, Requirement[]>();
  for (const r of view.requirements) bySection.set(r.section ?? 'mission', [...(bySection.get(r.section ?? 'mission') ?? []), r]);
  const c = view.completeness;
  return (
    <Panel title="Requirements" caption={`${c.answered} of ${c.total} questions answered`}>
      <div className="pbar" role="progressbar" aria-label="Questions answered" aria-valuemin={0} aria-valuemax={c.total} aria-valuenow={c.answered} style={{ marginBottom: 8 }}>
        <div className="fill" style={{ width: `${c.total ? (100 * c.answered) / c.total : 0}%` }} />
      </div>
      {!view.requirements.length ? <span className="muted small">Nothing set yet.</span> : null}
      {[...bySection.entries()].map(([sec, rows]) => (
        <div key={sec} style={{ marginBottom: 8 }}>
          <h4 className="small" style={{ margin: '6px 0 4px' }}>
            {view.sections[sec] ?? sec}
          </h4>
          <table className="data small" data-testid={`reqs-${sec}`}>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td style={{ width: '45%' }}>{r.prompt}</td>
                  <td>
                    {r.display ?? String(r.value)}
                    {r.source === 'default' && r.note ? <div className="muted">{r.note}</div> : null}
                    {r.source === 'statement' && r.answer_why ? <div className="muted">{r.answer_why}</div> : null}
                  </td>
                  <td>
                    <SourceBadge source={r.source} />
                  </td>
                  <td>
                    {r.qid ? (
                      <Button size="small" disabled={props.busy} onClick={() => props.onEdit(r.qid as string)} data-testid={`edit-${r.qid}`}>
                        Change
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </Panel>
  );
}

/** What was read from the mission statement. */
export function Findings({ statement, findings }: { statement: string; findings: Finding[] }) {
  if (!statement) return null;
  return (
    <div className="bq-msg user" data-testid="statement">
      <div className="small muted">Your description</div>
      <div>“{statement}”</div>
      {findings.length ? (
        <ul className="small" style={{ margin: '4px 0 0 16px' }}>
          {findings.map((f) => (
            <li key={f.qid}>
              {f.qid}: {String(Array.isArray(f.value) ? f.value.join(', ') : f.value)} — {f.why}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export type BuilderAction = (fn: () => Promise<BuilderResponse>) => Promise<void>;
