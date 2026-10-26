// V3 CubeSat Builder — Component Catalog: the real parts the architect chooses from, as their makers publish them.
// A value a maker does not publish says so; prices are listed only where published ("quote required" otherwise);
// every part links to its source. Any part can be put into a slot that takes its kind. Each part's geometry: the
// maker's CAD the user downloaded and imported (the app never downloads by itself), or a simplified shape of its
// published size — always labelled with where it came from, with the import checks.
import { useMemo, useRef, useState } from 'react';
import type { CadEntry, CadList, CatalogList, PartSummary, SlotInfo } from './analysisTypes';
import { dimsText, num, powerText, priceText } from './analysisTypes';
import { Badge, Button, Panel } from '../components/ui';

const CAD_TEXT: Record<string, string> = {
  public: 'maker offers a public file',
  registration: 'maker asks you to register',
  'on request': 'maker sends it on request',
  unknown: 'no maker CAD found',
};
const ORIGIN_TONE = { manufacturer: 'ok', reconstructed: 'accent', bbox: 'warn', placeholder: 'err' } as const;

export function GeometryCell(props: {
  c: PartSummary;
  entry: CadEntry | undefined;
  offerUrl: string | null;
  busy: boolean;
  onImport: (file: File) => void;
  onSimplified: () => void;
  onDelete: () => void;
  /** use another model of the imported archive (its path in the archive) */
  onModel?: (member: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const e = props.entry;
  const models = e?.archive_models ?? [];
  return (
    <div className="stack small" style={{ gap: 3 }} data-testid={`geometry-${props.c.id}`}>
      <span className="muted">
        {props.offerUrl ? (
          <a href={props.offerUrl} target="_blank" rel="noreferrer">
            {CAD_TEXT[props.c.cad] ?? props.c.cad}
          </a>
        ) : (
          CAD_TEXT[props.c.cad] ?? props.c.cad
        )}
      </span>
      {e ? (
        <details>
          <summary>
            <Badge tone={ORIGIN_TONE[e.origin]}>{e.origin_text}</Badge> {e.ok ? '' : <Badge tone="err">check failed</Badge>}
          </summary>
          <ul style={{ margin: '2px 0 0 14px' }}>
            {e.checks.map((ch) => (
              <li key={ch.name}>
                {ch.ok === true ? '✓' : ch.ok === false ? '✗' : '?'} {ch.name}: {ch.detail}
              </li>
            ))}
            <li>units: {e.units}</li>
            {e.source_name ? <li>from {e.source_name}</li> : null}
            {models.length > 1 && props.onModel ? (
              <li>
                model in the archive:{' '}
                <select
                  value={e.archive_member ?? ''}
                  disabled={props.busy}
                  aria-label={`Model in the archive for ${props.c.product}`}
                  onChange={(ev) => props.onModel?.(ev.target.value)}
                  data-testid={`cad-model-${props.c.id}`}
                >
                  {models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </li>
            ) : e.archive_member ? (
              <li>model in the archive: {e.archive_member}</li>
            ) : null}
            {e.licence ? <li>{e.licence}</li> : null}
          </ul>
        </details>
      ) : (
        <span className="muted">no geometry yet</span>
      )}
      <span className="row" style={{ gap: 4, flexWrap: 'wrap' }}>
        <input
          ref={input}
          type="file"
          accept=".step,.stp,.iges,.igs,.brep,.stl,.zip"
          style={{ display: 'none' }}
          aria-label={`CAD file for ${props.c.product}`}
          onChange={(ev) => {
            const f = ev.target.files?.[0];
            if (f) props.onImport(f);
            ev.target.value = '';
          }}
          data-testid={`cad-file-${props.c.id}`}
        />
        <Button size="small" disabled={props.busy} onClick={() => input.current?.click()}>
          Import CAD…
        </Button>
        <Button size="small" disabled={props.busy} onClick={props.onSimplified} data-testid={`cad-simple-${props.c.id}`}>
          Simplified shape
        </Button>
        {e ? (
          <Button size="small" disabled={props.busy} onClick={props.onDelete}>
            Remove
          </Button>
        ) : null}
      </span>
    </div>
  );
}

export function CatalogSection(props: {
  catalog: CatalogList | null;
  slots: SlotInfo[];
  busy: boolean;
  onUse: (slot: string, component: string) => void;
  cad?: CadList | null;
  onCadImport?: (cid: string, file: File) => void;
  onCadSimplified?: (cid: string) => void;
  onCadDelete?: (cid: string) => void;
  onCadModel?: (cid: string, member: string) => void;
}) {
  const [cat, setCat] = useState('');
  const [q, setQ] = useState('');
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (props.catalog?.components ?? []).filter(
      (c) => (!cat || c.category === cat) && (!t || `${c.manufacturer} ${c.product} ${c.description ?? ''}`.toLowerCase().includes(t)),
    );
  }, [props.catalog, cat, q]);
  const offers = useMemo(() => new Map((props.cad?.offered ?? []).map((o) => [o.id, o.url])), [props.cad]);
  if (!props.catalog) return <span className="muted">Loading the catalog…</span>;
  const slotsFor = (c: PartSummary) => props.slots.filter((s) => s.categories.includes(c.category));
  return (
    <Panel title="Component catalog" caption={`${props.catalog.components.length} parts from the makers' own pages and datasheets`}>
      <div className="row small" style={{ gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <select aria-label="Category" value={cat} onChange={(e) => setCat(e.target.value)} data-testid="catalog-category">
          <option value="">All kinds</option>
          {Object.entries(props.catalog.categories).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <input type="search" aria-label="Search the catalog" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted">{rows.length} shown · CAD is imported from files you download; the app never downloads by itself</span>
      </div>
      <table className="data small" data-testid="catalog-table">
        <thead>
          <tr>
            <th>Part</th>
            <th>Kind</th>
            <th>Mass</th>
            <th>Size</th>
            <th>Power</th>
            <th>Price</th>
            <th>Geometry</th>
            <th>Use in</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id} data-testid={`part-${c.id}`}>
              <td>
                {c.url ? (
                  <a href={c.url} target="_blank" rel="noreferrer">
                    {c.manufacturer} {c.product}
                  </a>
                ) : (
                  `${c.manufacturer} ${c.product}`
                )}
                {c.fits ? <div className="muted">{c.fits}</div> : null}
              </td>
              <td>{c.category_name ?? c.category}</td>
              <td>{c.mass_kg != null ? `${num(c.mass_kg)} kg` : <span className="muted">not published</span>}</td>
              <td>{c.dims_mm ? dimsText(c.dims_mm) : <span className="muted">not published</span>}</td>
              <td>{powerText(c.power_w)}</td>
              <td title={c.price.note}>{c.price.value == null ? <span className="muted">quote required</span> : priceText(c.price)}</td>
              <td>
                <GeometryCell
                  c={c}
                  entry={props.cad?.items[c.id]}
                  offerUrl={offers.get(c.id) ?? null}
                  busy={props.busy}
                  onImport={(f) => props.onCadImport?.(c.id, f)}
                  onSimplified={() => props.onCadSimplified?.(c.id)}
                  onDelete={() => props.onCadDelete?.(c.id)}
                  onModel={props.onCadModel ? (m) => props.onCadModel?.(c.id, m) : undefined}
                />
              </td>
              <td>
                {slotsFor(c).length ? (
                  <select
                    aria-label={`Use ${c.product} in`}
                    value=""
                    disabled={props.busy}
                    onChange={(e) => e.target.value && props.onUse(e.target.value, c.id)}
                    data-testid={`use-in-${c.id}`}
                  >
                    <option value="">Choose…</option>
                    {slotsFor(c).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
