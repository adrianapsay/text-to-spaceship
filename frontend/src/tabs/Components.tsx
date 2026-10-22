import { useMemo, useState } from 'react';
import type { Part } from '../api/types';
import { useApp } from '../store/store';
import { useParts } from '../hooks';
import { fmt, fmtColumn, fmtVec } from '../lib/fmt';
import { SUBSYSTEM_LABELS, subsystemColor } from '../lib/colors';
import { massBadge, statusBadge } from '../components/PartsPanel';
import { FidelityPanel } from '../components/FidelityPanel';
import { PartPreview } from '../components/viewport/PartPreview';
import { Panel, MockTag, KV } from '../components/ui';

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
  const [sort, setSort] = useState<{ k: SortKey; dir: 1 | -1 }>({ k: 'name', dir: 1 });
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
                <tr key={p.id} aria-selected={p.id === selected} onClick={() => select(p.id)} style={{ cursor: 'pointer' }}>
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
      {sel ? (
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
        <div className="muted">Select a part in the table to inspect it and see its detail-level study.</div>
      )}
    </div>
  );
}
