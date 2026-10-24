import { useEffect, useMemo, useRef, useState } from 'react';
import type { SelectorSweep, SliderKey } from '../api/types';
import { session } from '../api/session';
import { isCurrent } from '../api/protocol';
import { useApp, type TabId } from '../store/store';
import { useAsync } from '../hooks';
import { layoutIdeaMap, navigate, tabFromName } from '../lib/ideamapLayout';
import { SLIDERS } from '../lib/copy';
import { Markdown } from '../components/Markdown';
import { normaliseMap, SelectorHeatmap, SweepStrip } from '../components/SelectorViews';
import { Badge, Button, EmptyState, MockTag, Notice, Panel } from '../components/ui';
import { algorithmLabel } from '../api/protocol';

const KIND_FILL: Record<string, string> = {
  parts: 'var(--bg-sunken)',
  proxy: 'var(--bg-sunken)',
  algorithm: 'var(--bg-panel)',
  weights: 'var(--bg-selected)',
  constraints: 'var(--bg-selected)',
  selected: 'var(--bg-selected)',
  layout: 'var(--bg-panel)',
};

function IdeaMapView() {
  const setTab = useApp((s) => s.setTab);
  const weightsRev = useApp((s) => s.conn.newest.weights_rev);
  const partsRev = useApp((s) => s.conn.newest.parts_rev);
  const bestId = useApp((s) => s.solver.best?.id);
  const res = useAsync(() => session().api.ideamap(), [weightsRev, partsRev, bestId]);
  const layout = useMemo(() => (res.data ? layoutIdeaMap(res.data) : null), [res.data]);
  const [focus, setFocus] = useState<string | null>(null);
  const refs = useRef<Record<string, SVGGElement | null>>({});
  useEffect(() => {
    if (focus) refs.current[focus]?.focus();
  }, [focus]);
  if (res.notAvailable) return <EmptyState title="No idea map from the backend yet">The idea map is generated from the live run (GET /api/ideamap).</EmptyState>;
  if (res.error) return <Notice tone="err">{res.error}</Notice>;
  if (!layout) return <div className="muted">Loading…</div>;
  const focused = layout.nodes.find((n) => n.id === focus) ?? null;
  const open = (tab: string | null) => {
    const t = tabFromName(tab);
    if (t) setTab(t as TabId);
  };
  return (
    <div className="stack">
      <div className="small muted">
        Click a node, or use the keyboard: Tab to enter, arrows to move along links / within a column, Enter to open the tab with the detail.
        {res.data?.mock ? ' MOCK — built from the mock backend state.' : ''}
      </div>
      <div style={{ overflow: 'auto', border: '1px solid var(--border-subtle)', background: 'var(--bg-panel)' }}>
        <svg width={layout.width} height={layout.height} role="group" aria-label="Idea map" data-testid="idea-map">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="var(--text-muted)" />
            </marker>
          </defs>
          {layout.edges.map((e, i) => (
            <g key={i}>
              <path d={e.path} fill="none" stroke="var(--text-muted)" strokeWidth={1.2} markerEnd="url(#arrow)" />
              {e.label ? (
                <text x={e.mid[0]} y={e.mid[1]} fontSize={10} textAnchor="middle" fill="var(--text)" style={{ paintOrder: 'stroke', stroke: 'var(--bg-panel)', strokeWidth: 3 }}>
                  {e.label}
                </text>
              ) : null}
            </g>
          ))}
          {layout.nodes.map((n, i) => (
            <g
              key={n.id}
              ref={(el) => {
                refs.current[n.id] = el;
              }}
              className="idea-node"
              role="link"
              tabIndex={focus ? (focus === n.id ? 0 : -1) : i === 0 ? 0 : -1}
              aria-label={`${n.kind}: ${n.label}${n.detail ? `. ${n.detail}` : ''}${n.tab ? `. Opens ${n.tab}` : ''}`}
              data-focused={focus === n.id}
              data-node={n.id}
              onFocus={() => setFocus(n.id)}
              onClick={() => {
                setFocus(n.id);
                open(n.tab);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  open(n.tab);
                  return;
                }
                const next = navigate(layout, n.id, e.key);
                if (next !== n.id) {
                  e.preventDefault();
                  setFocus(next);
                }
              }}
            >
              <rect x={n.x} y={n.y} width={n.w} height={n.h} fill={KIND_FILL[n.kind] ?? 'var(--bg-panel)'} stroke={n.kind === 'selected' ? 'var(--accent)' : 'var(--border)'} strokeWidth={n.kind === 'selected' ? 2 : 1} />
              <text x={n.x + 8} y={n.y + 16} fontSize={10} fill="var(--text-muted)">
                {n.kind}
              </text>
              <text x={n.x + 8} y={n.y + 32} fontSize={12} fill="var(--text)" fontWeight={600}>
                {n.label.length > 28 ? `${n.label.slice(0, 27)}…` : n.label}
              </text>
            </g>
          ))}
        </svg>
      </div>
      {focused ? (
        <div className="notice info" aria-live="polite">
          <strong>{focused.label}</strong> ({focused.kind}) — {focused.detail ?? 'no detail'}{' '}
          {focused.tab ? (
            <Button size="small" onClick={() => open(focused.tab)}>
              Open {focused.tab}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function FitProofView() {
  const best = useApp((s) => s.solver.best);
  const newest = useApp((s) => s.conn.newest);
  const id = best?.id ?? null;
  const res = useAsync(id ? () => session().api.proof(id) : null, [id]);
  const [dlError, setDlError] = useState<string | null>(null);
  if (!best) return <EmptyState title="No validated layout on screen" />;
  const dl = async (kind: 'md' | 'json' | 'checker', name: string) => {
    setDlError(null);
    try {
      await session().api.download(session().api.proofDownloadPath(best.id, kind), name);
    } catch (e) {
      setDlError(`${name}: ${(e as Error).message}`);
    }
  };
  return (
    <div className="stack">
      <div className="row">
        <span>
          Proof for <strong>{best.id}</strong>
        </span>
        {!isCurrent(best, newest) ? <Badge tone="warn">VALIDATED FOR PREVIOUS INPUTS</Badge> : null}
        {res.data?.mock ? <Badge tone="mock">MOCK — AABB argument, not the backend validator</Badge> : null}
        <span style={{ flex: 1 }} />
        <Button size="small" onClick={() => dl('md', `proof_${best.id}.md`)} data-testid="dl-proof-md">
          Download proof (.md)
        </Button>
        <Button size="small" onClick={() => dl('json', `certificate_${best.id}.json`)}>
          Certificate (.json)
        </Button>
        <Button size="small" onClick={() => dl('checker', 'check_certificate.py')}>
          Checker script (.py)
        </Button>
      </div>
      {dlError ? <Notice tone="err">Download failed — {dlError}</Notice> : null}
      {res.notAvailable ? (
        <EmptyState title="No proof from the backend yet">The validator writes a step-by-step proof with the actual numbers for every validated layout.</EmptyState>
      ) : res.error ? (
        <Notice tone="err">{res.error}</Notice>
      ) : res.data ? (
        <div data-testid="proof-markdown" style={{ maxHeight: 560, overflow: 'auto', border: '1px solid var(--border-subtle)', padding: '0 12px', background: 'var(--bg-panel)' }}>
          <Markdown source={res.data.markdown} />
        </div>
      ) : (
        <div className="muted">Loading…</div>
      )}
    </div>
  );
}

// speed_quality is not swept: since the search runs until Pause (V2) nothing in the backend reads it
const SWEEP_SLIDERS: SliderKey[] = ['space', 'balance', 'inertia', 'feasibility', 'cable', 'cost', 'mass_symmetry'];

function SelectorExplorer() {
  const settings = useApp((s) => s.goals.settings);
  const weightsRev = useApp((s) => s.conn.newest.weights_rev);
  const constraintRev = useApp((s) => s.conn.newest.constraint_rev);
  const live = useApp((s) => s.solver.selector);
  const switchLog = useApp((s) => s.solver.selectorLog);
  const expert = useApp((s) => s.view.expert);
  const stage = settings?.stage ?? 1;
  const sliders = SWEEP_SLIDERS.filter((k) => {
    if ((k === 'cable' || k === 'cost' || k === 'feasibility') && stage !== 2) return false;
    if (k === 'mass_symmetry' && !expert) return false;
    return true;
  });
  const [sweeps, setSweeps] = useState<Record<string, SelectorSweep>>({});
  const [sweepErr, setSweepErr] = useState<{ notAvailable: boolean; message: string } | null>(null);
  useEffect(() => {
    let alive = true;
    Promise.all(sliders.map((k) => session().api.selectorSweep(k).then((s) => [k, s] as const)))
      .then((rs) => {
        if (!alive) return;
        setSweeps(Object.fromEntries(rs));
        setSweepErr(null);
      })
      .catch((e: { notAvailable?: boolean; message?: string }) => alive && setSweepErr({ notAvailable: !!e?.notAvailable, message: e?.message ?? String(e) }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weightsRev, constraintRev, sliders.join(',')]);
  const [mx, setMx] = useState<SliderKey>('space');
  const [my, setMy] = useState<SliderKey>('balance');
  const mapRes = useAsync(() => session().api.selectorMap(mx, my, 41), [mx, my, weightsRev, constraintRev]);
  const map = normaliseMap(mapRes.data, mx, my);
  const sel = useAsync(() => session().api.selector(), [weightsRev, constraintRev, live ? algorithmLabel(live) : '']);
  const allIds = useMemo(() => {
    const ids = new Set<string>();
    for (const s of Object.values(sweeps)) {
      s.choices.forEach((c) => ids.add(c));
      Object.keys(s.legend ?? {}).forEach((c) => ids.add(c));
    }
    map?.grid.flat().forEach((c) => ids.add(c));
    return [...ids].sort();
  }, [sweeps, map]);
  const legend = Object.assign({}, ...Object.values(sweeps).map((s) => s.legend ?? {}), map?.legend ?? {}) as Record<string, string>;
  const label = (k: SliderKey) => SLIDERS.find((s) => s.key === k)?.label ?? k;
  const evidence = sel.data?.evidence ?? [];
  const evCols = [...new Set(evidence.flatMap((e) => Object.keys(e)))];
  const anyMock = Object.values(sweeps).some((s) => s.mock) || map?.mock;
  return (
    <div className="stack">
      <div className="row">
        <span>
          Current choice: <strong>{algorithmLabel(live ?? sel.data) || '—'}</strong>
        </span>
        {anyMock ? <Badge tone="mock">MOCK selector rule — illustrative</Badge> : null}
        <span className="small muted">The selector is deterministic, so these sweeps are exact, not samples.</span>
      </div>
      <Panel title="One strip per slider" caption="other sliders held at their current values">
        {sweepErr ? (
          sweepErr.notAvailable ? (
            <EmptyState title="No selector sweep from the backend yet" />
          ) : (
            <Notice tone="err">{sweepErr.message}</Notice>
          )
        ) : !settings ? null : (
          sliders.map((k) => (sweeps[k] ? <SweepStrip key={k} sweep={sweeps[k]} label={label(k)} current={settings.sliders[k]} allIds={allIds} /> : null))
        )}
      </Panel>
      <div className="grid-2">
        <Panel
          title="Two-slider map"
          caption="41 × 41 grid"
          right={
            <>
              <select aria-label="Map x slider" value={mx} onChange={(e) => setMx(e.target.value as SliderKey)}>
                {sliders.map((k) => (
                  <option key={k} value={k}>
                    x: {label(k)}
                  </option>
                ))}
              </select>
              <select aria-label="Map y slider" value={my} onChange={(e) => setMy(e.target.value as SliderKey)}>
                {sliders.map((k) => (
                  <option key={k} value={k}>
                    y: {label(k)}
                  </option>
                ))}
              </select>
            </>
          }
        >
          {mapRes.notAvailable ? (
            <EmptyState title="No selector map from the backend yet" />
          ) : mapRes.error ? (
            <Notice tone="err">{mapRes.error}</Notice>
          ) : map && settings ? (
            <SelectorHeatmap map={map} xLabel={label(mx)} yLabel={label(my)} xVal={settings.sliders[mx]} yVal={settings.sliders[my]} allIds={allIds} legend={legend} />
          ) : (
            <div className="muted">Loading…</div>
          )}
        </Panel>
        <div className="stack">
          <Panel title="Evidence behind the current choice" right={<MockTag />}>
            {sel.notAvailable ? (
              <EmptyState title="No selector evidence from the backend yet" />
            ) : evidence.length ? (
              <table className="data" data-testid="evidence-table">
                <thead>
                  <tr>
                    {evCols.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {evidence.map((e, i) => (
                    <tr key={i}>
                      {evCols.map((c) => (
                        <td key={c}>{typeof e[c] === 'object' ? JSON.stringify(e[c]) : String(e[c] ?? '—')}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="small muted">No evidence rows (default rule, no benchmark evidence yet).</div>
            )}
            {sel.data?.reasons?.length ? (
              <ul className="small">
                {sel.data.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            ) : null}
          </Panel>
          <Panel title="Switch log" caption="every change of choice this session">
            {switchLog.length ? (
              <ul className="log" data-testid="switch-log">
                {switchLog.map((s, i) => (
                  <li key={i}>
                    {new Date(s.at).toLocaleTimeString()} → {s.algorithm}
                    {s.reasons.length ? ` — ${s.reasons.join('; ')}` : ''}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="small muted">No switches yet. Move a slider across a switch point to see one.</div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

export function ExplainTab() {
  const section = useApp((s) => s.view.explainSection);
  const setSection = useApp((s) => s.setExplainSection);
  return (
    <div className="tab-scroll" data-testid="tab-explain">
      <div className="seg" role="tablist" aria-label="Explain sections" style={{ marginBottom: 10 }}>
        {(
          [
            ['map', 'Idea map'],
            ['proof', 'Proof that the parts fit'],
            ['selector', 'How sliders change the algorithm'],
          ] as const
        ).map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={section === k} className="btn" aria-pressed={section === k} onClick={() => setSection(k)} data-testid={`explain-${k}`}>
            {l}
          </button>
        ))}
      </div>
      {section === 'map' ? (
        <Panel title="Idea map" caption="parts → simplified shapes → candidate algorithms → priorities → constraints → chosen algorithm → layout">
          <IdeaMapView />
        </Panel>
      ) : section === 'proof' ? (
        <Panel title="Fit proof" caption="containment, separation, balance, lower bounds — with the actual numbers">
          <FitProofView />
        </Panel>
      ) : (
        <SelectorExplorer />
      )}
    </div>
  );
}
