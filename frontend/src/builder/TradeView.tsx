// V3 CubeSat Builder — Trade Study: the priority sliders the architect ranks parts by, the mission lifetime, the
// CubeSat size (recommended or yours), and every size side by side. Slider moves are sent once the hand stops (half a
// second), and the results stay labelled as recomputing until the new analysis is in.
import { useEffect, useRef, useState } from 'react';
import type { Analysis } from './analysisTypes';
import { num } from './analysisTypes';
import { Badge, Button, Notice, NumberField, Panel } from '../components/ui';

export type PrefsPatch = Record<string, number | null>;

export function TradeSection(props: { a: Analysis; stale: boolean; busy: boolean; onPrefs: (p: PrefsPatch) => void }) {
  const { a, stale } = props;
  const [vals, setVals] = useState<Record<string, number>>(a.prefs);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef<PrefsPatch>({});
  useEffect(() => setVals(a.prefs), [a.inputs_hash, a.prefs]);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const send = (patch: PrefsPatch, now = false) => {
    pending.current = { ...pending.current, ...patch };
    if (timer.current) clearTimeout(timer.current);
    const go = () => {
      const p = pending.current;
      pending.current = {};
      props.onPrefs(p);
    };
    if (now) go();
    else timer.current = setTimeout(go, 500);
  };
  const recommended = a.trade.find((t) => t.feasible)?.label;
  return (
    <div className="stack" data-testid="trade" aria-busy={stale}>
      {stale ? (
        <Notice tone="info" role="status">
          Recomputing — the table shows design version {a.design_version}.
        </Notice>
      ) : null}
      <div className="grid-2">
        <Panel title="Priorities" caption="how the architect ranks parts that meet the requirements">
          <div className="stack" style={{ gap: 10 }}>
            {Object.entries(a.sliders).map(([k, s]) => (
              <label key={k} className="stack small" style={{ gap: 2 }}>
                <span>{s.label}</span>
                <span className="row" style={{ gap: 8 }}>
                  <span className="muted" style={{ width: 110 }}>
                    {s.low}
                  </span>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={vals[k] ?? s.default}
                    aria-label={s.label}
                    disabled={props.busy}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setVals((x) => ({ ...x, [k]: v }));
                      send({ [k]: v });
                    }}
                    data-testid={`slider-${k}`}
                  />
                  <span className="muted" style={{ width: 110 }}>
                    {s.high}
                  </span>
                </span>
              </label>
            ))}
            <div className="row small" style={{ gap: 8, flexWrap: 'wrap' }}>
              <span>Mission lifetime</span>
              <NumberField
                value={a.prefs.lifetime_years ?? a.mission_years}
                onCommit={(v) => send({ lifetime_years: v }, true)}
                label="Mission lifetime"
                min={0.1}
                max={15}
                unit="years"
                width={70}
              />
              {a.prefs.lifetime_years != null ? (
                <Button size="small" disabled={props.busy} onClick={() => send({ lifetime_years: null }, true)}>
                  Use the requirement
                </Button>
              ) : null}
            </div>
            <div className="row small" style={{ gap: 8, flexWrap: 'wrap' }}>
              <span>CubeSat size</span>
              <select
                aria-label="CubeSat size"
                value={a.size_user ? String(a.size_u) : ''}
                disabled={props.busy}
                onChange={(e) => send({ size_u: e.target.value === '' ? null : Number(e.target.value) }, true)}
                data-testid="size-select"
              >
                <option value="">Recommended{recommended ? ` (${recommended})` : ''}</option>
                {a.trade.map((t) => (
                  <option key={t.size_u} value={String(t.size_u)}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </Panel>
        <Panel title="Sizes side by side" caption="each size gets its own orbit, parts and checks">
          <table className="data small" style={{ opacity: stale ? 0.55 : 1 }} data-testid="trade-table">
            <thead>
              <tr>
                <th>Size</th>
                <th>Passes</th>
                <th>Orbit</th>
                <th>Mass</th>
                <th>Power margin</th>
                <th>Data returned</th>
                <th>Volume used</th>
                <th>Payload</th>
              </tr>
            </thead>
            <tbody>
              {a.trade.map((t) => (
                <tr key={t.size_u} aria-current={t.size_u === a.size_u ? 'true' : undefined} style={t.size_u === a.size_u ? { fontWeight: 600 } : undefined}>
                  <td>{t.label}</td>
                  <td title={t.failures.join('; ')}>{t.feasible ? <Badge tone="ok">yes</Badge> : <Badge tone="err">{t.failures.length} failing</Badge>}</td>
                  <td>{num(t.alt_km)} km</td>
                  <td>
                    {num(t.mass_kg)} / {num(t.mass_limit_kg)} kg
                  </td>
                  <td>{t.margin_pct == null ? '—' : `${num(t.margin_pct)} %`}</td>
                  <td>{t.data_pct == null ? '—' : `${num(t.data_pct)} %`}</td>
                  <td>{num(t.fill_pct)} %</td>
                  <td>{t.payload.join(', ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {a.trade.some((t) => !t.feasible) ? (
            <ul className="small muted" style={{ margin: '6px 0 0 16px' }}>
              {a.trade
                .filter((t) => !t.feasible)
                .map((t) => (
                  <li key={t.size_u}>
                    {t.label}: {t.failures.join('; ')}
                  </li>
                ))}
            </ul>
          ) : null}
        </Panel>
      </div>
    </div>
  );
}
