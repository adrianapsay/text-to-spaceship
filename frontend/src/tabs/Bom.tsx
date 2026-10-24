// V2 WS6: Bill of Materials of the shown layout (the one the Overview draws), linked to its 3D view: a row selects its
// part in 3D (brackets: the part they hold), a part picked in 3D highlights its rows; it follows the best layout, its
// designed brackets (layout.updated) and the part masses. The backend's report/bom.py is the single source.
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { badgeText } from '../api/protocol';
import { itemsFor } from '../components/LayoutCompare';
import { MainViewport } from '../components/viewport/Viewport';
import { Badge, Button, EmptyState, MockTag, Notice, Panel, type BadgeTone } from '../components/ui';
import { downloadBomCsv, gramText, groupRows, partForRow, rowsForPart, useBom, useShownLayout, type Bom, type BomRow } from '../lib/bom';
import { DISCLAIMER_STAGE2 } from '../lib/copy';
import { useApp } from '../store/store';
import '../components/drawing/drawing.css';

const SOURCE: Record<string, { tone: BadgeTone; text: string; title: string; dashed?: boolean }> = {
  designed: { tone: 'ok', text: 'designed', title: 'the designed solid, checked with two FEA solvers (Mounting Hardware tab)' },
  exact: { tone: 'neutral', text: 'exact', title: 'the mass of the modelled solid (built from boxes in its reserved box)' },
  catalogue: { tone: 'neutral', text: 'catalogue', title: 'a catalogue figure (ASSUMED)' },
  ESTIMATE: { tone: 'warn', text: 'ESTIMATE', title: 'estimated from the reserved box until the bracket is designed' },
  ASSUMED: { tone: 'warn', text: 'ASSUMED', title: 'an ASSUMED value: density, standard-part mass or geometry' },
  USER_MASS: { tone: 'accent', text: 'USER', title: 'mass entered by you' },
  USER_DENSITY: { tone: 'accent', text: 'USER', title: 'density entered by you' },
  WITHHELD: { tone: 'err', text: 'WITHHELD', title: 'mass properties withheld (no closed mesh): not in the totals' },
  'not modelled': { tone: 'neutral', text: 'not modelled', title: 'no mass model in the layout data: listed, not in the totals', dashed: true },
};

export function SourceBadge({ source }: { source: string }) {
  const s = SOURCE[source] ?? { tone: 'neutral' as BadgeTone, text: source, title: source };
  return (
    <Badge tone={s.tone} title={s.title} dashed={s.dashed}>
      {s.text}
    </Badge>
  );
}

function pieces(rows: BomRow[]) {
  return rows.reduce((s, r) => s + r.qty, 0);
}

function Totals({ bom }: { bom: Bom }) {
  const t = bom.totals;
  const kg = (v: number | null) => (v == null ? '' : ` (${v.toFixed(3)} kg)`);
  return (
    <tfoot data-testid="bom-totals">
      <tr>
        <th colSpan={6} scope="row">
          Parts
        </th>
        <td className="num">{gramText(t.parts_kg)}</td>
        <td />
      </tr>
      <tr>
        <th colSpan={6} scope="row">
          Hardware: brackets, fasteners, washers, standoffs
        </th>
        <td className="num">{gramText(t.hardware_kg)}</td>
        <td>{t.estimate_kg > 0 ? <span className="small muted">of which ESTIMATE {gramText(t.estimate_kg)} g</span> : null}</td>
      </tr>
      <tr>
        <th colSpan={6} scope="row">
          Parts + hardware{kg(t.assembly_kg)}
        </th>
        <td className="num" data-testid="bom-total">
          {gramText(t.assembly_kg)}
        </td>
        <td>
          {t.matches_metrics === true ? (
            <Badge tone="ok" title="the same as the layout's total mass in its metrics">
              = layout mass
            </Badge>
          ) : t.matches_metrics === false ? (
            <Badge tone="warn" title={`layout metrics: ${t.metrics_mass_kg?.toFixed(6)} kg`}>
              differs by {gramText(t.difference_kg, 3)} g
            </Badge>
          ) : (
            <span className="small muted">no layout mass to compare</span>
          )}
        </td>
      </tr>
      {t.frame_kg != null ? (
        <>
          <tr>
            <th colSpan={6} scope="row" className="muted">
              Frame (ASSUMED, listed, not included)
            </th>
            <td className="num muted">{gramText(t.frame_kg)}</td>
            <td />
          </tr>
          <tr>
            <th colSpan={6} scope="row">
              Total with the frame{kg(t.with_frame_kg)}
            </th>
            <td className="num">{gramText(t.with_frame_kg)}</td>
            <td />
          </tr>
        </>
      ) : null}
    </tfoot>
  );
}

function BomTable(props: { bom: Bom; selected: string | null; onRow: (r: BomRow) => void; onIsolate: (r: BomRow) => void; onHover: (id: string | null) => void }) {
  const { bom, selected } = props;
  const { own, related } = useMemo(() => rowsForPart(bom.items, selected), [bom.items, selected]);
  const rowEls = useRef(new Map<number, HTMLTableRowElement>());
  // a part picked in 3D: bring its first row into view
  useEffect(() => {
    const first = [...own].sort((a, b) => a - b)[0];
    if (first != null) rowEls.current.get(first)?.scrollIntoView?.({ block: 'nearest' });
  }, [own]);
  const onKey = (r: BomRow) => (e: KeyboardEvent<HTMLTableRowElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      props.onRow(r);
    } else if (e.key === 'i' || e.key === 'I') {
      e.preventDefault();
      props.onIsolate(r);
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const all = [...rowEls.current.entries()].sort((a, b) => a[0] - b[0]).map((x) => x[1]);
      const i = all.indexOf(e.currentTarget);
      all[i + (e.key === 'ArrowDown' ? 1 : -1)]?.focus();
    }
  };
  return (
    <table className="data bom-table" role="grid" aria-label={`Bill of materials of layout ${bom.layout_id}`} data-testid="bom-table">
      <thead>
        <tr>
          <th className="num" scope="col">
            Item
          </th>
          <th className="num" scope="col">
            Qty
          </th>
          <th scope="col">Name and description</th>
          <th scope="col">Material</th>
          <th scope="col">Process</th>
          <th className="num" scope="col">
            Unit (g)
          </th>
          <th className="num" scope="col">
            Total (g)
          </th>
          <th scope="col">Mass source</th>
        </tr>
      </thead>
      {groupRows(bom).map((g) => (
        <tbody key={g.id} aria-label={g.label} data-group={g.id}>
          <tr className="bom-group">
            <th colSpan={8} scope="rowgroup">
              {g.label} <span className="muted">· {g.rows.length} rows, {pieces(g.rows)} pieces</span>
            </th>
          </tr>
          {g.rows.map((r) => {
            const part = partForRow(r);
            return (
              <tr
                key={r.item_no}
                ref={(el) => {
                  if (el) rowEls.current.set(r.item_no, el);
                  else rowEls.current.delete(r.item_no);
                }}
                tabIndex={0}
                aria-selected={own.has(r.item_no)}
                data-related={related.has(r.item_no) ? 'true' : undefined}
                data-testid={`bom-row-${r.item_no}`}
                data-part={part ?? undefined}
                title={part ? 'Click or Enter: select in the 3D view · double-click or I: isolate' : `Used on ${r.for_parts.length} parts`}
                onClick={() => props.onRow(r)}
                onDoubleClick={() => props.onIsolate(r)}
                onKeyDown={onKey(r)}
                onMouseEnter={() => props.onHover(part)}
                onMouseLeave={() => props.onHover(null)}
              >
                <td className="num">{r.item_no}</td>
                <td className="num">{r.qty}</td>
                <td>
                  <div className="bom-name">
                    <span>{r.name}</span>
                    {r.designed ? <Badge tone={r.passed ? 'ok' : 'err'}>{r.passed ? 'designed' : 'design failed'}</Badge> : null}
                    {!r.in_total && r.total_mass_kg != null ? <Badge tone="neutral">not in total</Badge> : null}
                  </div>
                  {r.description ? <div className="bom-desc">{r.description}</div> : null}
                </td>
                <td className="small">{r.material}</td>
                <td className="small">{r.process}</td>
                <td className="num">{gramText(r.unit_mass_kg)}</td>
                <td className="num">{gramText(r.total_mass_kg)}</td>
                <td>
                  <SourceBadge source={r.mass_source} />
                </td>
              </tr>
            );
          })}
        </tbody>
      ))}
      <Totals bom={bom} />
    </table>
  );
}

export function BomTab() {
  const { item, layout } = useShownLayout();
  const bom = useBom(layout);
  const newest = useApp((s) => s.conn.newest);
  const selected = useApp((s) => s.view.selectedPartId);
  const isolated = useApp((s) => s.view.isolated);
  const hiddenCount = useApp((s) => s.view.hidden.length);
  const parts = useApp((s) => s.dataset.parts);
  const select = useApp((s) => s.select);
  const hover = useApp((s) => s.hover);
  const isolate = useApp((s) => s.isolate);
  const showAll = useApp((s) => s.showAll);
  const [msg, setMsg] = useState<string | null>(null);
  const items = useMemo(() => itemsFor(layout, newest), [layout, newest]);
  useEffect(() => () => hover(null), [hover]);
  const b = bom.data && layout && bom.data.layout_id === layout.id ? bom.data : null;
  const stale = !!bom.data && !!layout && bom.data.layout_id !== layout.id;
  const onRow = (r: BomRow) => {
    const p = partForRow(r);
    if (p) select(p);
  };
  const onIsolate = (r: BomRow) => {
    const p = partForRow(r);
    if (p) isolate(p);
  };
  const csv = async () => {
    if (!layout) return;
    setMsg(null);
    try {
      await downloadBomCsv(layout.id);
    } catch (e) {
      setMsg(`Could not download: ${(e as Error).message}`);
    }
  };
  const ownRows = b && selected ? [...rowsForPart(b.items, selected).own].sort((x, y) => x - y) : [];
  return (
    <div className="tab-scroll" data-testid="tab-bom">
      {!layout ? (
        <EmptyState title="No validated layout yet">Run the optimiser: the bill of materials lists the layout the Overview shows, with its brackets and hardware in Stage 2.</EmptyState>
      ) : (
        <>
          <Notice tone="info" role="note">
            Layout <strong>{layout.id}</strong> ({item ? badgeText(item.kind) : '—'}, Stage {layout.stage}
            {layout.part_scale != null && layout.part_scale !== 1 ? `, parts at ${Math.round(layout.part_scale * 100)} %` : ''}). Masses are what the layout data says, each with its source;
            nothing is made up. {layout.stage === 2 ? DISCLAIMER_STAGE2 : 'Stage 1 is IDEALIZED: parts only.'}
          </Notice>
          <div className="bom-layout" style={{ marginTop: 10 }}>
            <Panel
              title="Bill of materials"
              caption={b ? `${b.totals.rows} items · ${b.totals.pieces} pieces · ${gramText(b.totals.assembly_kg)} g` : undefined}
              right={
                <>
                  {b?.mock ? <MockTag what="bill of materials built in the browser from the MOCK placeholder layout" /> : null}
                  {stale || bom.loading ? <span className="small muted">updating…</span> : null}
                  <Button size="small" onClick={csv} disabled={!b} data-testid="bom-csv">
                    Download CSV
                  </Button>
                </>
              }
            >
              {bom.notAvailable ? (
                <EmptyState title="The backend does not provide the bill of materials">It is served at GET /api/layouts/{'{id}'}/bom.</EmptyState>
              ) : bom.error && !b ? (
                <Notice tone="err">Could not load the bill of materials: {bom.error}</Notice>
              ) : !b ? (
                <span className="muted small">Loading…</span>
              ) : (
                <>
                  <div className="row small" style={{ marginBottom: 6 }} data-testid="bom-selection">
                    {selected ? (
                      <>
                        <span>
                          Selected: <strong>{parts[selected]?.name ?? selected}</strong>
                          {ownRows.length ? ` — item${ownRows.length > 1 ? 's' : ''} ${ownRows.join(', ')}` : ' — not in this layout'}
                        </span>
                        <Button size="small" onClick={() => isolate(selected)} aria-pressed={isolated === selected}>
                          {isolated === selected ? 'Show all in 3D' : 'Isolate in 3D'}
                        </Button>
                        <Button size="small" onClick={() => select(null)}>
                          Clear selection
                        </Button>
                      </>
                    ) : (
                      <span className="muted">Click a row to select its part in the 3D view (a bracket selects the part it holds); click a part in the 3D view to find its rows.</span>
                    )}
                    {(isolated || hiddenCount) && isolated !== selected ? (
                      <Button size="small" onClick={showAll}>
                        Show all parts
                      </Button>
                    ) : null}
                  </div>
                  <BomTable bom={b} selected={selected} onRow={onRow} onIsolate={onIsolate} onHover={hover} />
                  <ul className="small muted" style={{ margin: '8px 0 0 16px', padding: 0 }}>
                    <li>{b.totals.included}</li>
                    {b.notes.map((n) => (
                      <li key={n}>{n}</li>
                    ))}
                  </ul>
                </>
              )}
              {msg ? <Notice tone="err">{msg}</Notice> : null}
            </Panel>
            <div className="bom-3d">
              <Panel title="3D view" caption="the same layout; the selected part is outlined">
                <div style={{ height: 520, display: 'flex' }}>
                  <MainViewport items={items} metrics={layout.metrics ?? null} stage={layout.stage} testId="bom-viewport" ariaLabel="3D view of the layout in the bill of materials" />
                </div>
              </Panel>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
