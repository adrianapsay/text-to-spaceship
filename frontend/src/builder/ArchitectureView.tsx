// V3 CubeSat Builder — Recommended Architecture: the CubeSat size and orbit the architect chose and why, one row per
// subsystem slot (the part, why it was picked, what was not and why), the user's own choices, and the compatibility
// checks in their four statuses, worst first.
import { useState } from 'react';
import type { Analysis, CatalogList, Check, CheckStatus, Pick, SlotInfo } from './analysisTypes';
import { dimsText, PICK_TEXT, powerText, priceText, STATUS_TEXT, num } from './analysisTypes';
import { Badge, Button, Notice, NumberField, Panel } from '../components/ui';

const PICK_TONE = { recommended: 'accent', user: 'ok', none: 'neutral', missing: 'err', placeholder: 'warn' } as const;
const CHECK_TONE: Record<CheckStatus, 'ok' | 'warn' | 'err' | 'neutral'> = { compatible: 'ok', assumptions: 'warn', incompatible: 'err', unknown: 'neutral' };
const CHECK_ORDER: CheckStatus[] = ['incompatible', 'unknown', 'assumptions', 'compatible'];

export function orbitText(o: Analysis['orbit']): string {
  const lt = o.ltdn_h;
  const hh = lt == null ? null : `${Math.floor(lt)}:${String(Math.round((lt % 1) * 60)).padStart(2, '0')}`;
  return `${num(o.alt_km)} km, ${o.sso ? 'sun-synchronous ' : ''}${num(o.inc_deg)}° inclination${hh ? `, equator southbound at ${hh} local time` : ''}`;
}

export function ChecksPanel({ checks }: { checks: Check[] }) {
  const groups = CHECK_ORDER.map((s) => [s, checks.filter((c) => c.status === s)] as const).filter(([, cs]) => cs.length);
  return (
    <Panel title="Compatibility" caption={CHECK_ORDER.map((s) => `${checks.filter((c) => c.status === s).length} ${STATUS_TEXT[s].toLowerCase()}`).join(' · ')}>
      {!checks.length ? <span className="muted small">No checks yet.</span> : null}
      {groups.map(([s, cs]) => (
        <details key={s} open={s !== 'compatible'} className="small" data-testid={`checks-${s}`}>
          <summary>
            <Badge tone={CHECK_TONE[s]}>{STATUS_TEXT[s]}</Badge> {cs.length}
          </summary>
          <ul style={{ margin: '4px 0 8px 16px' }}>
            {cs.map((c, i) => (
              <li key={`${c.rule}-${c.title}-${i}`}>
                <strong>{c.title}</strong> — {c.detail}
                {c.fix ? <span className="muted"> (fix: {c.fix})</span> : null}
              </li>
            ))}
          </ul>
        </details>
      ))}
    </Panel>
  );
}

const GEOMETRY_TONE = { manufacturer: 'ok', reconstructed: 'accent', bbox: 'warn', placeholder: 'err' } as const;

function PartLine({ p, geometry }: { p: Pick; geometry: Analysis['geometry'] }) {
  if (!p.items.length) return <span className="muted">—</span>;
  return (
    <div className="stack" style={{ gap: 2 }}>
      {p.items.map((it) => (
        <div key={it.id}>
          {it.url ? (
            <a href={it.url} target="_blank" rel="noreferrer">
              {it.name}
            </a>
          ) : (
            it.name
          )}
          {it.qty > 1 ? ` ×${it.qty}` : ''}
          {geometry?.[it.id] ? (
            <>
              {' '}
              <Badge tone={GEOMETRY_TONE[geometry[it.id].origin]} title="where this part's geometry comes from">
                {geometry[it.id].origin_text}
              </Badge>
            </>
          ) : null}
          <div className="muted small">
            {it.mass_kg != null ? `${num(it.mass_kg)} kg` : 'mass not published'} · {dimsText(it.dims_mm)} · {powerText(it.power_w)} · {priceText(it.price)}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Changing a slot: the alternatives with the reasons they were not picked, any part of the slot's kind, a quantity. */
function Picker(props: { p: Pick; slot: SlotInfo | undefined; catalog: CatalogList | null; busy: boolean; onUse: (component: string | null, qty: number) => void; onReset: () => void; onClose: () => void }) {
  const { p } = props;
  const [qty, setQty] = useState<number>(p.items[0]?.qty ?? 1);
  const [other, setOther] = useState('');
  const kinds = props.slot?.categories ?? [];
  const parts = (props.catalog?.components ?? []).filter((c) => kinds.includes(c.category));
  return (
    <div className="bq-picker stack small" style={{ gap: 6 }} data-testid={`picker-${p.slot}`}>
      {p.alternatives.length ? (
        <table className="data small">
          <tbody>
            {p.alternatives.map((alt) => (
              <tr key={alt.id}>
                <td>{alt.name}</td>
                <td className="muted">{alt.reason}</td>
                <td>
                  <Button size="small" disabled={props.busy} onClick={() => props.onUse(alt.id, qty)} data-testid={`use-${p.slot}-${alt.id}`}>
                    Use
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <span className="muted">No other candidates were ranked for this slot.</span>
      )}
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <label className="row" style={{ gap: 4 }}>
          Any part of this kind
          <select aria-label={`Any part for ${p.label}`} value={other} onChange={(e) => setOther(e.target.value)}>
            <option value="">Choose…</option>
            {parts.map((c) => (
              <option key={c.id} value={c.id}>
                {c.manufacturer} {c.product}
              </option>
            ))}
          </select>
        </label>
        <Button size="small" disabled={props.busy || !other} onClick={() => props.onUse(other, qty)}>
          Use it
        </Button>
        <label className="row" style={{ gap: 4 }}>
          Quantity
          <NumberField value={qty} onCommit={(v) => setQty(Math.max(1, Math.round(v)))} label="Quantity" min={1} max={12} width={50} />
        </label>
        <Button size="small" disabled={props.busy} onClick={() => props.onUse(null, 1)} data-testid={`remove-${p.slot}`}>
          Leave it out
        </Button>
        {p.status === 'user' || p.recommended ? (
          <Button size="small" disabled={props.busy} onClick={props.onReset} data-testid={`reset-${p.slot}`}>
            Back to the recommendation
          </Button>
        ) : null}
        <Button size="small" onClick={props.onClose}>
          Close
        </Button>
      </div>
    </div>
  );
}

export function ArchitectureSection(props: {
  a: Analysis;
  stale: boolean;
  busy: boolean;
  catalog: CatalogList | null;
  slots: SlotInfo[];
  onSelect: (slot: string, component: string | null, qty: number) => void;
  onUnselect: (slot: string) => void;
}) {
  const { a, stale } = props;
  const [open, setOpen] = useState<string | null>(null);
  const order = a.slots.map((s) => s.id).filter((s) => a.picks[s]);
  return (
    <div className="stack" data-testid="architecture" aria-busy={stale}>
      {stale ? (
        <Notice tone="info" role="status">
          Recomputing for your latest change — showing design version {a.design_version}.
        </Notice>
      ) : null}
      <div style={{ opacity: stale ? 0.55 : 1 }} className="stack">
        <Panel title={`Recommended architecture — ${a.size_label}`} caption={orbitText(a.orbit)}>
          <div className="stack small" style={{ gap: 4 }}>
            <span>{a.size_why}</span>
            <span className="muted">{a.orbit.why}</span>
            {a.failures.length ? <Notice tone="err">This size still fails: {a.failures.join('; ')}.</Notice> : null}
            {a.flags.map((f) => (
              <Notice key={f} tone="warn">
                {f}
              </Notice>
            ))}
            {a.missing_hardware.length ? (
              <Notice tone="info">
                Also needed (not in the catalog): {a.missing_hardware.join('; ')}.
              </Notice>
            ) : null}
          </div>
          <table className="data small" style={{ marginTop: 8 }} data-testid="slots">
            <thead>
              <tr>
                <th>Subsystem</th>
                <th>Part</th>
                <th>Why</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {order.map((sid) => {
                const p = a.picks[sid];
                return [
                  <tr key={sid} data-testid={`slot-${sid}`} className={p.status === 'none' ? 'muted' : undefined}>
                    <td>
                      {p.label}
                      <div>
                        <Badge tone={PICK_TONE[p.status]}>{PICK_TEXT[p.status]}</Badge>
                        {p.place === 'external' && p.items.length ? (
                          <Badge tone="neutral" title="Outside the structure: counted in mass and power, shown in the preview, not packed by the optimiser">
                            not packed
                          </Badge>
                        ) : null}
                      </div>
                    </td>
                    <td>
                      <PartLine p={p} geometry={a.geometry} />
                    </td>
                    <td>
                      {p.why}
                      {p.recommended ? (
                        <div className="muted">Recommended: {p.recommended.items.map((i) => i.name).join(', ') || 'none'}</div>
                      ) : null}
                      {p.flags.map((f) => (
                        <div key={f} className="warn-text">
                          {f}
                        </div>
                      ))}
                    </td>
                    <td>
                      <Button size="small" disabled={props.busy} onClick={() => setOpen(open === sid ? null : sid)} aria-expanded={open === sid} data-testid={`change-${sid}`}>
                        Change
                      </Button>
                    </td>
                  </tr>,
                  open === sid ? (
                    <tr key={`${sid}-picker`}>
                      <td colSpan={4}>
                        <Picker
                          p={p}
                          slot={props.slots.find((s) => s.id === sid)}
                          catalog={props.catalog}
                          busy={props.busy}
                          onUse={(c, q) => {
                            props.onSelect(sid, c, q);
                            setOpen(null);
                          }}
                          onReset={() => {
                            props.onUnselect(sid);
                            setOpen(null);
                          }}
                          onClose={() => setOpen(null)}
                        />
                      </td>
                    </tr>
                  ) : null,
                ];
              })}
            </tbody>
          </table>
        </Panel>
        <ChecksPanel checks={a.checks} />
      </div>
    </div>
  );
}
