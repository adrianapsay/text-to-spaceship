import { useEffect, useState } from 'react';
import { algorithmLabel } from '../api/protocol';
import { hasSession, session } from '../api/session';
import type { SelectorChoice } from '../api/types';
import { useApp } from '../store/store';
import { MockTag, Tip } from './ui';

/** "Algorithm in use: X — because …" next to the sliders (Addendum 3.2 c). */
export function AlgorithmChip() {
  const live = useApp((s) => s.solver.selector);
  const weightsRev = useApp((s) => s.conn.newest.weights_rev);
  const [fetched, setFetched] = useState<SelectorChoice | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    if (live || !hasSession()) return;
    let alive = true;
    session()
      .api.selector()
      .then((s) => alive && setFetched(s))
      .catch(() => alive && setUnavailable(true));
    return () => {
      alive = false;
    };
  }, [live, weightsRev]);
  const sel = live ?? fetched;
  if (!sel || !sel.algorithm) {
    return (
      <div className="chip" data-testid="algorithm-chip">
        <span className="muted">Algorithm in use:</span> <span>{unavailable ? 'not reported by the backend yet' : '—'}</span>
      </div>
    );
  }
  const label = algorithmLabel(sel);
  const because = sel.reasons?.[0];
  return (
    <Tip
      content={
        <div>
          <p>
            <strong>{label}</strong>
          </p>
          {(sel.reasons ?? []).map((r, i) => (
            <p key={i}>• {r}</p>
          ))}
        </div>
      }
    >
      <div className="chip" data-testid="algorithm-chip" tabIndex={0} aria-label={`Algorithm in use: ${label}${because ? `, because ${because}` : ''}`}>
        <span className="muted">Algorithm in use:</span>
        <strong>{label}</strong>
        {because ? <span className="muted">— because {because}</span> : null}
        <MockTag what="selector rule is illustrative" />
      </div>
    </Tip>
  );
}
