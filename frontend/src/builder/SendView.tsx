// V3 CubeSat Builder — Send to Optimization: what goes to the optimiser (the parts inside the structure, with their
// masses and geometry) and what does not (external hardware, "not packed"), then a new optimiser project made from
// the design — never overwriting one — and the app switched to it. The project list switches back at any time; each
// Builder project shows what it was made from and the constraints the optimiser does not enforce.
import type { Analysis, CheckStatus, ProjectInfo, SentRecord } from './analysisTypes';
import { num } from './analysisTypes';
import { Badge, Button, Notice, Panel } from '../components/ui';

const PACKED = [3, 6, 12];
const TONE: Record<CheckStatus, 'ok' | 'warn' | 'err' | 'neutral'> = { compatible: 'ok', assumptions: 'warn', incompatible: 'err', unknown: 'neutral' };

export function SentDetails({ s }: { s: SentRecord }) {
  return (
    <div className="stack small" style={{ gap: 4 }} data-testid="sent-details">
      <span>
        From design {s.design_name ?? s.design_id} (version {s.design_version ?? '?'}), sent {s.sent_at} as a {s.size}: {s.parts.length} part(s) to pack
        {s.not_packed.length ? `, ${s.not_packed.length} not packed` : ''}.
      </span>
      {s.warnings.map((w) => (
        <Notice key={w} tone="warn">
          {w}
        </Notice>
      ))}
      <div className="muted">The optimiser does not enforce:</div>
      <ul style={{ margin: '0 0 0 16px' }}>
        {s.unenforced.map((u) => (
          <li key={u}>{u}</li>
        ))}
      </ul>
    </div>
  );
}

export function SendSection(props: {
  a: Analysis;
  stale: boolean;
  busy: boolean;
  projects: { projects: ProjectInfo[]; current: string } | null;
  sentBy: { project: string; at: string; version: number }[];
  onSend: () => void;
  onSwitch: (name: string) => void;
}) {
  const { a } = props;
  const inside = a.slots.flatMap((s) => (a.picks[s.id]?.place === 'internal' ? a.picks[s.id].items.map((it) => ({ slot: s.label, it })) : []));
  const outside = a.slots.flatMap((s) => (a.picks[s.id]?.place === 'external' ? a.picks[s.id].items.map((it) => ({ slot: s.label, it })) : []));
  const packing = a.checks.filter((c) => c.rule === 'packing_model');
  const packable = PACKED.includes(a.size_u);
  const current = props.projects?.projects.find((p) => p.current);
  return (
    <div className="stack" data-testid="send">
      <Panel
        title="Send to Optimization"
        caption={`a new optimiser project from this design (${a.size_label}); your existing projects are never overwritten`}
        right={
          <Button variant="primary" disabled={props.busy || props.stale || !packable || !inside.length} onClick={props.onSend} data-testid="send-button">
            Send to Optimization
          </Button>
        }
      >
        {!packable ? <Notice tone="err">The optimiser packs 3U, 6U and 12U; this design is {a.size_label}. Choose a size in the Trade Study.</Notice> : null}
        {props.stale ? <Notice tone="info">Waiting for the analysis of your latest change before sending.</Notice> : null}
        <div className="grid-2">
          <div>
            <h4 className="small" style={{ margin: '4px 0' }}>
              Packed by the optimiser ({inside.reduce((n, x) => n + x.it.qty, 0)})
            </h4>
            <table className="data small">
              <tbody>
                {inside.map(({ slot, it }) => (
                  <tr key={`${slot}-${it.id}`}>
                    <td>{slot}</td>
                    <td>
                      {it.name}
                      {it.qty > 1 ? ` ×${it.qty}` : ''}
                    </td>
                    <td>{it.mass_kg != null ? `${num(it.mass_kg)} kg` : <span className="muted">mass not published</span>}</td>
                    <td>
                      <Badge tone="neutral">{a.geometry?.[it.id]?.origin_text ?? 'simplified box (made on sending)'}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <h4 className="small" style={{ margin: '4px 0' }}>Not packed (outside the structure)</h4>
            <ul className="small" style={{ margin: '0 0 0 16px' }}>
              {outside.map(({ slot, it }) => (
                <li key={`${slot}-${it.id}`}>
                  {it.name}
                  {it.qty > 1 ? ` ×${it.qty}` : ''} — {slot}
                </li>
              ))}
            </ul>
            {packing.map((c) => (
              <div key={c.title} className="small">
                <Badge tone={TONE[c.status]}>{c.status_text}</Badge> {c.title}: {c.detail}
              </div>
            ))}
          </div>
        </div>
        {props.sentBy.length ? (
          <div className="small muted" style={{ marginTop: 6 }}>
            Sent before: {props.sentBy.map((s) => `${s.project} (version ${s.version}, ${s.at})`).join('; ')}
          </div>
        ) : null}
      </Panel>
      <Panel title="Projects" caption="the optimiser runs one project at a time; switching reloads the page">
        {!props.projects ? (
          <span className="muted">Loading…</span>
        ) : (
          <table className="data small" data-testid="projects">
            <thead>
              <tr>
                <th>Project</th>
                <th>Size</th>
                <th>Parts</th>
                <th>From the Builder</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {props.projects.projects.map((p) => (
                <tr key={p.name} aria-current={p.current ? 'true' : undefined}>
                  <td>
                    {p.name} {p.current ? <Badge tone="ok">running</Badge> : null}
                  </td>
                  <td>{p.form_factor}</td>
                  <td>{p.parts}</td>
                  <td>{p.builder ? `${p.builder.design_name ?? p.builder.design_id} v${p.builder.design_version ?? '?'}` : '—'}</td>
                  <td>
                    {!p.current ? (
                      <Button size="small" disabled={props.busy} onClick={() => props.onSwitch(p.name)} data-testid={`switch-${p.name}`}>
                        Switch to
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {current?.builder ? (
          <div style={{ marginTop: 8 }}>
            <h4 className="small" style={{ margin: '4px 0' }}>
              {current.name}
            </h4>
            <SentDetails s={current.builder} />
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
