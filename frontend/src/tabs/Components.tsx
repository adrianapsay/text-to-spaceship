import { useMemo, useState } from 'react';
import type { BracketDesign, BracketLayouts, Layout, LayoutDesignRecord, LayoutRunSettings, Part } from '../api/types';
import { useApp } from '../store/store';
import { useAsync, useParts } from '../hooks';
import { fmt, fmtColumn, fmtVec } from '../lib/fmt';
import { SUBSYSTEM_LABELS, extraItemStyle, subsystemColor } from '../lib/colors';
import { massBadge, statusBadge } from '../components/PartsPanel';
import { FidelityPanel } from '../components/FidelityPanel';
import { BracketFeaPanel } from '../components/FeaView';
import { governingText } from '../components/BracketDesign';
import { useFullLayout } from '../components/LayoutCompare';
import { PartPreview } from '../components/viewport/PartPreview';
import { Badge, Button, EmptyState, Panel, MockTag, KV } from '../components/ui';
import { session } from '../api/session';

const DESIGNED_KINDS = ['metal_am', 'cradle', 'clamp'];
const BRACKET_KIND: Record<string, string> = { metal_am: 'Metal 3D-printed bracket', cradle: 'Machined cradle', clamp: 'Tube-clamp band' };

interface DesignedRow {
  itemId: string;
  pid: string;
  kind: string;
  target: string;
  meshUrl: string | null;
  design: BracketDesign | null;
}

/** The brackets of a Stage 2 layout that the design job builds (metal AM, cradles, clamp bands) with their designs. */
export function designedRows(layout: Layout | null): DesignedRow[] {
  const brs = layout?.stage2?.brackets ?? [];
  const designs = layout?.stage2?.bracket_designs ?? {};
  const urls = new Map((layout?.extra_items ?? []).map((it) => [it.id, it.mesh_url]));
  const out: DesignedRow[] = [];
  brs.forEach((b, k) => {
    if (!DESIGNED_KINDS.includes(b.kind) || !layout) return;
    const itemId = `${layout.id}-br${k}`;
    const d = designs[b.pid];
    out.push({ itemId, pid: b.pid, kind: b.kind, target: b.target, meshUrl: urls.get(itemId) ?? null, design: d && d.mass_kg != null ? d : null });
  });
  return out;
}

/** M4: a combined bracket or the one piece of the layout (Mounting Hardware → Bracket layout), when it has a solid. */
export interface PieceRow {
  itemId: string;
  mode: 'combined' | 'one_piece';
  key: string;
  title: string;
  meshUrl: string;
  design: LayoutDesignRecord;
  /** why it has no colour maps: designed before they were saved ('old'), or its two-solver check did not run */
  noMaps: 'old' | 'not solved' | null;
}

export function pieceRows(data: BracketLayouts | null | undefined): PieceRow[] {
  if (!data) return [];
  const out: PieceRow[] = [];
  for (const mode of ['one_piece', 'combined'] as const) {
    const designs = data.modes[mode]?.result?.designs ?? {};
    for (const [key, d] of Object.entries(designs)) {
      if (d.mass_kg == null || !d.mesh_file) continue;
      const itemId = mode === 'one_piece' ? `${data.layout_id}-op` : `${data.layout_id}-cb${d.index ?? 0}`;
      const n = d.parts?.length ?? 0;
      const title =
        mode === 'one_piece' ? `One piece for ${n} parts${d.brace_frame ? ', bracing the frame' : ''}` : `Combined bracket ${d.name} for ${n} parts`;
      const noMaps = d.fea_file ? null : (d.reason ?? '').startsWith('not solved') ? 'not solved' : 'old';
      out.push({ itemId, mode, key, title, meshUrl: `/api/items/${itemId}/mesh?v=${mode[0]}${Math.round(d.mass_kg * 1e7)}`, design: d, noMaps });
    }
  }
  return out;
}

/** The settings a combined bracket or the one piece was designed with, to design it again the same way. */
export function rerunSettings(d: LayoutDesignRecord): LayoutRunSettings {
  const s = d.settings ?? {};
  const out: LayoutRunSettings = { material: s.material ?? null, vol_frac: s.vol_frac ?? 'auto', min_member_mm: s.min_member_mm ?? 'auto' };
  if (s.budget_s != null) out.budget_s = s.budget_s;
  if (s.brace_frame) out.brace_frame = true;
  return out;
}

function msBadge(v: number | null | undefined) {
  if (v == null) return <span className="muted">—</span>;
  return <Badge tone={v >= 0 ? 'ok' : 'err'}>{(v >= 0 ? '+' : '') + v.toFixed(2)}</Badge>;
}

type SortKey = 'name' | 'status' | 'subsystem' | 'triangles' | 'volume' | 'mass' | 'density' | 'i1';

const COLS: { key: SortKey; label: string; num?: boolean }[] = [
  { key: 'name', label: 'Name' },
  { key: 'status', label: 'Status' },
  { key: 'subsystem', label: 'Subsystem' },
  { key: 'triangles', label: 'Triangles', num: true },
  { key: 'volume', label: 'V (cm³)', num: true },
  { key: 'mass', label: 'm (kg)', num: true },
  { key: 'density', label: 'ρ (kg/m³)', num: true },
];

function sortValue(p: Part, k: SortKey, mass: number | null): string | number {
  switch (k) {
    case 'name':
      return p.name;
    case 'status':
      return p.status;
    case 'subsystem':
      return p.subsystem;
    case 'triangles':
      return p.triangles;
    case 'volume':
      return p.volume_mm3 ?? -1;
    case 'mass':
      return mass ?? -1;
    case 'density':
      return p.density_kg_m3 ?? -1;
    case 'i1':
      return p.principal_kgm2?.[0] ?? -1;
  }
}

export function ComponentsTab() {
  const parts = useParts();
  const selected = useApp((s) => s.view.selectedPartId);
  const select = useApp((s) => s.select);
  const massEdits = useApp((s) => s.physical.massEdits);
  const best = useApp((s) => s.solver.best);
  const infeasible = useApp((s) => s.solver.infeasible);
  const [sort, setSort] = useState<{ k: SortKey; dir: 1 | -1 }>({ k: 'name', dir: 1 });
  // the layout whose brackets the app designs: the best Stage 2 layout, else the least-violating Stage 2 candidate
  const s2id = best && best.stage === 2 ? best.id : infeasible && infeasible.stage === 2 ? infeasible.id : null;
  const s2 = useFullLayout(s2id);
  const brackets = useMemo(() => designedRows(s2.data), [s2.data]);
  const study = useApp((s) => s.solver.studies['bracket_design']);
  const runStatus = (study?.partial as { status?: string } | undefined)?.status;
  const running = runStatus === 'PENDING' || runStatus === 'RUNNING';
  // M4: the layout's combined brackets and its one piece (fetched again when a design run finishes)
  const layouts = useAsync(s2id ? () => session().api.bracketLayouts(s2id) : null, [s2id, runStatus === 'DONE' ? study?.at : null]);
  const pieces = useMemo(() => pieceRows(layouts.data), [layouts.data]);
  const [selBracket, setSelBracket] = useState<string | null>(null);
  const bracket = brackets.find((b) => b.itemId === selBracket) ?? null;
  const piece = pieces.find((p) => p.itemId === selBracket) ?? null;
  // designs made before the colour maps were saved: one click designs them again (their settings are kept)
  const noMaps = brackets.filter((b) => b.design && !b.design.fea_file).map((b) => b.pid);
  const [mapsMsg, setMapsMsg] = useState<string | null>(null);
  const addMaps = async () => {
    if (!s2.data) return;
    setMapsMsg(null);
    try {
      await session().api.designBrackets(s2.data.id, { pids: noMaps });
      setMapsMsg(`Designing ${noMaps.length} bracket(s) again with their settings, to save their colour maps (progress in the Mounting Hardware tab).`);
    } catch (e) {
      setMapsMsg(`Could not start: ${(e as Error).message}`);
    }
  };
  const pieceMaps = async (p: PieceRow) => {
    if (!s2.data) return;
    setMapsMsg(null);
    try {
      const all = layouts.data?.modes[p.mode]?.result?.designs ?? {};
      const req =
        p.mode === 'one_piece' ? { settings: rerunSettings(p.design) } : { overrides: Object.fromEntries(Object.entries(all).map(([k, d]) => [k, rerunSettings(d)])) };
      await session().api.runBracketLayout(s2.data.id, p.mode, req);
      setMapsMsg(`Designing the ${p.mode === 'one_piece' ? 'one piece' : 'combined brackets'} again with the same settings, to save the colour maps (progress in the Mounting Hardware tab).`);
    } catch (e) {
      setMapsMsg(`Could not start: ${(e as Error).message}`);
    }
  };
  const names = useMemo(() => Object.fromEntries(parts.map((p) => [p.id, p.name])), [parts]);
  const rows = useMemo(() => {
    const r = parts.map((p) => ({ p, m: massEdits[p.id]?.mass_kg ?? p.mass_kg }));
    r.sort((a, b) => {
      const va = sortValue(a.p, sort.k, a.m);
      const vb = sortValue(b.p, sort.k, b.m);
      return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
    });
    return r;
  }, [parts, massEdits, sort]);
  const principalCols = [0, 1, 2].map((k) => fmtColumn(rows.map((r) => r.p.principal_kgm2?.[k] ?? null)));
  const sel = selected ? parts.find((p) => p.id === selected) : null;
  const header = (c: { key: SortKey; label: string; num?: boolean }) => (
    <th key={c.key} className={c.num ? 'num' : ''} aria-sort={sort.k === c.key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
      <button type="button" onClick={() => setSort((s) => ({ k: c.key, dir: s.k === c.key ? (s.dir === 1 ? -1 : 1) : 1 }))}>
        {c.label}
        {sort.k === c.key ? (sort.dir === 1 ? ' ▲' : ' ▼') : ''}
      </button>
    </th>
  );
  return (
    <div className="tab-scroll" data-testid="tab-components">
      <Panel title={`Components (${parts.length})`} caption="geometry, validity, repairs, labels, mass properties" right={<MockTag what="part properties computed by the mock fixture script" />}>
        <div className="table-wrap" style={{ maxHeight: 420 }}>
          <table className="data" aria-label="Parts table">
            <thead>
              <tr>
                {COLS.map(header)}
                <th>Mass source</th>
                <th>Labels</th>
                <th>Repairs</th>
                <th className="num">Size (mm)</th>
                <th className="num">COM (part frame, mm)</th>
                <th className="num">I₁ {principalCols[0].header}</th>
                <th className="num">I₂ {principalCols[1].header}</th>
                <th className="num">I₃ {principalCols[2].header}</th>
                <th className="num">Solidity</th>
                <th className="num">OBB fill</th>
                <th>Tags</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ p, m }, i) => (
                <tr
                  key={p.id}
                  aria-selected={p.id === selected && !bracket}
                  onClick={() => {
                    select(p.id);
                    setSelBracket(null);
                  }}
                  style={{ cursor: 'pointer' }}
                >
                  <td>
                    <span className="swatch" style={{ background: subsystemColor(p.subsystem), display: 'inline-block', marginRight: 6 }} />
                    {p.name}
                  </td>
                  <td>
                    {p.status} {statusBadge(p)}
                  </td>
                  <td>{SUBSYSTEM_LABELS[p.subsystem] ?? p.subsystem}</td>
                  <td className="num">{fmt(p.triangles, 'int')}</td>
                  <td className="num">{fmt(p.volume_mm3, 'mm3', { unit: false })}</td>
                  <td className="num">{fmt(m, 'kg', { unit: false })}</td>
                  <td className="num">{fmt(p.density_kg_m3, 'density', { unit: false })}</td>
                  <td>{massBadge(massEdits[p.id] ? 'USER_MASS' : p.mass_source)}</td>
                  <td className="small">{p.labels.join(', ') || '—'}</td>
                  <td className="small">{p.repairs.join(', ') || '—'}</td>
                  <td className="num">{p.extents_mm.map((v) => fmt(v, 'mm', { unit: false })).join(' × ')}</td>
                  <td className="num">{fmtVec(p.com_canonical_mm).replace(/ mm$/, '')}</td>
                  <td className="num">{principalCols[0].cells[i]}</td>
                  <td className="num">{principalCols[1].cells[i]}</td>
                  <td className="num">{principalCols[2].cells[i]}</td>
                  <td className="num">{fmt(p.solidity, 'ratio')}</td>
                  <td className="num">{fmt(p.obb_fill, 'ratio')}</td>
                  <td className="small">{p.tags.join(', ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel
        title={`Designed brackets${s2.data ? ` — layout ${s2.data.id}` : ''}`}
        caption="the 3D-printed (metal AM), machined cradle and clamp brackets the design job builds, and the layout's combined brackets and one piece once designed (Mounting Hardware → Bracket layout); select one for its FEA colour maps"
      >
        {!s2id ? (
          <EmptyState title="No Stage 2 layout yet">Brackets exist in Stage 2: switch to it and run the search.</EmptyState>
        ) : !brackets.length && !pieces.length ? (
          <span className="muted small">{s2.loading ? 'Loading…' : 'This layout has no bracket that the design job builds.'}</span>
        ) : (
          <div className="table-wrap" style={{ maxHeight: 320 }}>
            {noMaps.length || mapsMsg ? (
              <div className="row small" style={{ marginBottom: 6 }}>
                {noMaps.length ? (
                  <>
                    <span className="muted">{noMaps.length} design(s) were made before the colour maps were saved.</span>
                    <Button size="small" onClick={addMaps} disabled={running} data-testid="add-maps">
                      Design again with colour maps ({noMaps.length})
                    </Button>
                  </>
                ) : null}
                {mapsMsg ? <span>{mapsMsg}</span> : null}
              </div>
            ) : null}
            <table className="data" aria-label="Designed brackets" data-testid="designed-brackets">
              <thead>
                <tr>
                  <th>Part</th>
                  <th>Bracket</th>
                  <th>Material</th>
                  <th className="num">Mass</th>
                  <th className="num">MS yield</th>
                  <th className="num">MS ult.</th>
                  <th className="num">MS bolts</th>
                  <th className="num">f1</th>
                  <th>Governing check</th>
                  <th>FEA maps</th>
                </tr>
              </thead>
              <tbody>
                {brackets.map((b) => {
                  const d = b.design;
                  const st = extraItemStyle(b.kind === 'metal_am' ? 'metal_am' : 'machined');
                  return (
                    <tr key={b.itemId} aria-selected={b.itemId === selBracket} onClick={() => setSelBracket(b.itemId)} style={{ cursor: 'pointer' }} data-testid={`designed-${b.pid}`}>
                      <td>{names[b.pid] ?? b.pid}</td>
                      <td>
                        <span className="row" style={{ gap: 6 }}>
                          <span className={`swatch ${st.hatch ? 'hatch' : ''}`} style={{ background: st.color }} />
                          {BRACKET_KIND[b.kind] ?? b.kind}
                        </span>
                      </td>
                      <td className="small">{d?.material ?? '—'}</td>
                      <td className="num">{d ? fmt(d.mass_kg, 'kg') : <span className="muted">not designed</span>}</td>
                      <td className="num">{msBadge(d?.ms_yield)}</td>
                      <td className="num">{msBadge(d?.ms_ult)}</td>
                      <td className="num">{msBadge(d?.ms_bolt)}</td>
                      <td className="num">{d?.f1_hz != null ? `${Math.round(d.f1_hz)} Hz` : '—'}</td>
                      <td className="small">{d?.governing ? governingText(d.governing) : '—'}</td>
                      <td className="small">{d ? (d.fea_file ? <Badge tone="ok">yes</Badge> : <span className="muted">redesign for maps</span>) : '—'}</td>
                    </tr>
                  );
                })}
                {pieces.map((p) => {
                  const d = p.design;
                  const st = extraItemStyle('metal_am');
                  return (
                    <tr key={p.itemId} aria-selected={p.itemId === selBracket} onClick={() => setSelBracket(p.itemId)} style={{ cursor: 'pointer' }} data-testid={`designed-${p.mode}-${p.key}`}>
                      <td title={d.parts.map((x) => names[x] ?? x).join(', ')}>{d.parts.length} parts</td>
                      <td>
                        <span className="row" style={{ gap: 6 }}>
                          <span className={`swatch ${st.hatch ? 'hatch' : ''}`} style={{ background: st.color }} />
                          {p.mode === 'one_piece' ? 'One piece (metal 3D-printed)' : `Combined bracket ${d.name}`}
                          {d.brace_frame ? <Badge tone="accent">braces the frame</Badge> : null}
                        </span>
                      </td>
                      <td className="small">{d.material_name ?? d.material ?? '—'}</td>
                      <td className="num">{fmt(d.mass_kg, 'kg')}</td>
                      <td className="num">{msBadge(d.ms_yield)}</td>
                      <td className="num">{msBadge(d.ms_ult)}</td>
                      <td className="num">{msBadge(d.ms_bolt)}</td>
                      <td className="num">{d.f1_hz != null ? `${Math.round(d.f1_hz)} Hz` : '—'}</td>
                      <td className="small">{d.governing ? governingText(d.governing) : '—'}</td>
                      <td className="small">
                        {p.noMaps === null ? (
                          <Badge tone="ok">yes</Badge>
                        ) : p.noMaps === 'not solved' ? (
                          <span className="muted" title={d.reason}>
                            check did not run (memory)
                          </span>
                        ) : (
                          <Button
                            size="small"
                            disabled={running}
                            onClick={(ev) => {
                              ev.stopPropagation();
                              void pieceMaps(p);
                            }}
                            data-testid={`maps-${p.mode}`}
                          >
                            Design again with maps
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {piece ? (
        <BracketFeaPanel
          itemId={piece.itemId}
          meshUrl={piece.meshUrl}
          design={piece.design}
          title={piece.title}
          target={piece.design.target ?? (piece.mode === 'one_piece' ? 'the walls and end plates, where the per-part brackets were bolted' : undefined)}
        />
      ) : bracket ? (
        bracket.design && bracket.meshUrl ? (
          <BracketFeaPanel
            itemId={bracket.itemId}
            meshUrl={bracket.meshUrl}
            design={bracket.design}
            title={`${BRACKET_KIND[bracket.kind] ?? bracket.kind} for ${names[bracket.pid] ?? bracket.pid}`}
            target={bracket.target}
          />
        ) : (
          <EmptyState title="Not designed yet">Pause the search, or press Design in the Mounting Hardware tab: the design job builds this bracket and checks it.</EmptyState>
        )
      ) : sel ? (
        <div className="grid-2">
          <Panel title={`Inspector — ${sel.name}`} caption="local (canonical) frame">
            <PartPreview part={sel} />
            <div style={{ marginTop: 8 }}>
              <KV
                rows={[
                  ['File', `${sel.file} (${sel.units}${sel.units_confirmed ? ', confirmed' : ', not confirmed'})`],
                  ['SHA-256', <span className="num small">{sel.sha256.slice(0, 16)}…</span>],
                  ['Status', `${sel.status} — ${sel.status_detail}`],
                  ['Allowed orientations', `${sel.allowed_orients.length} of 24`],
                  ['Locked', sel.locked ? 'yes' : 'no'],
                ]}
              />
            </div>
          </Panel>
          <FidelityPanel partId={sel.id} />
        </div>
      ) : (
        <div className="muted">Select a part to inspect it and see its detail-level study, or a designed bracket for its FEA colour maps.</div>
      )}
    </div>
  );
}
