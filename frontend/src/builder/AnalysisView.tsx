// V3 CubeSat Builder — Engineering Analysis: every calculation in plain words first (its value, whether it meets the
// need, one sentence), with the working one click away — or always open in Expert mode: the equation, each input
// with where it came from, the assumptions, the sources and the fidelity. Stale results are dimmed and labelled while
// the analysis recomputes, never shown as current.
import type { Analysis, Calc, RefInfo } from './analysisTypes';
import { verdict, withUnit } from './analysisTypes';
import { Badge, Notice, Panel } from '../components/ui';

export function VerdictBadge({ c }: { c: Calc }) {
  if (c.value == null && c.missing) return <Badge tone="neutral" title={c.missing}>cannot compute</Badge>;
  const v = verdict(c);
  if (v === true) return <Badge tone="ok">meets</Badge>;
  if (v === false) return <Badge tone="err">not met</Badge>;
  return null;
}

function inputText(i: { value: unknown; unit: string | null }): string {
  if (i.value == null) return '—';
  if (typeof i.value === 'string') return i.value;
  return withUnit(i.value, i.unit);
}

/** The working behind a value: equation, inputs and their sources, assumptions, references, fidelity. */
export function Working({ c, refs }: { c: Calc; refs: Record<string, RefInfo> }) {
  const inputs = Object.entries(c.inputs ?? {});
  return (
    <div className="stack small" style={{ gap: 6 }} data-testid={`working-${c.id}`}>
      {c.equation ? <code className="bq-eq">{c.equation}</code> : null}
      {inputs.length ? (
        <table className="data small">
          <thead>
            <tr>
              <th>Input</th>
              <th>Value</th>
              <th>From</th>
            </tr>
          </thead>
          <tbody>
            {inputs.map(([k, i]) => (
              <tr key={k}>
                <td>{k}</td>
                <td>{inputText(i)}</td>
                <td className="muted">{i.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {c.assumptions?.length ? (
        <div>
          <div className="muted">Assumptions</div>
          <ul style={{ margin: '2px 0 0 16px' }}>
            {c.assumptions.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {c.refs?.length ? (
        <div>
          <div className="muted">Sources</div>
          <ul style={{ margin: '2px 0 0 16px' }}>
            {c.refs.map((k) => {
              const r = refs[k];
              return (
                <li key={k}>
                  {r ? (
                    <>
                      <a href={r.url} target="_blank" rel="noreferrer">
                        {r.title}
                      </a>{' '}
                      <span className="muted">
                        — {r.publisher} (accessed {r.accessed})
                      </span>
                    </>
                  ) : (
                    k
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      <span className="muted">
        Fidelity: {c.fidelity === 'preliminary' ? 'preliminary (traceable equation on verified data)' : 'conceptual (rough sizing, simplified physics)'}
      </span>
    </div>
  );
}

/** One calculation: label, value, verdict, the plain-English sentence, and the working. */
export function CalcCard({ c, refs, expert }: { c: Calc; refs: Record<string, RefInfo>; expert: boolean }) {
  const shown = c.value == null ? (c.missing ? 'not computed' : typeof c.text === 'string' ? c.text : '—') : withUnit(c.value, c.unit);
  return (
    <div className="bq-calc" data-testid={`calc-${c.id}`}>
      <div className="row" style={{ justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
        <span>{c.label}</span>
        <span className="row" style={{ gap: 6, alignItems: 'baseline' }}>
          <strong>{shown}</strong>
          <VerdictBadge c={c} />
        </span>
      </div>
      {c.missing ? <div className="muted small">Needs: {c.missing}</div> : null}
      {typeof c.need === 'number' ? <div className="muted small">Needed: {withUnit(c.need, c.unit)}</div> : null}
      {c.explain ? <div className="small">{c.explain}</div> : null}
      {expert ? (
        <Working c={c} refs={refs} />
      ) : (
        <details className="small">
          <summary>Show the working</summary>
          <Working c={c} refs={refs} />
        </details>
      )}
    </div>
  );
}

/** The analysis by subsystem. */
export function AnalysisSection(props: { a: Analysis; stale: boolean; expert: boolean }) {
  const { a, stale } = props;
  return (
    <div className="stack" data-testid="analysis" aria-busy={stale}>
      {stale ? (
        <Notice tone="info" role="status">
          Recomputing for your latest change — the numbers below are from design version {a.design_version} and are not current.
        </Notice>
      ) : null}
      <Notice tone="warn">{a.disclaimer}</Notice>
      <div className="grid-2" style={{ opacity: stale ? 0.55 : 1 }}>
        {a.groups.map((g) => (
          <Panel key={g.id} title={g.label} id={`calc-group-${g.id}`}>
            <div className="stack" style={{ gap: 8 }}>
              {g.calcs.map((id) => (a.calcs[id] ? <CalcCard key={id} c={a.calcs[id]} refs={a.refs} expert={props.expert} /> : null))}
            </div>
          </Panel>
        ))}
      </div>
    </div>
  );
}
