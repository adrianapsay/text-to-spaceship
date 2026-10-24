import { useRef } from 'react';
import type { Part } from '../api/types';
import { session } from '../api/session';
import { useApp } from '../store/store';
import { useParts } from '../hooks';
import { extraItemStyle, subsystemColor, SUBSYSTEM_LABELS } from '../lib/colors';
import { fmt, fmtVec } from '../lib/fmt';
import { PHYSICAL_CAPTION } from '../lib/copy';
import { Badge, Button, NumberField, Notice } from './ui';

export function massBadge(source: string) {
  switch (source) {
    case 'USER_MASS':
    case 'USER_DENSITY':
      return (
        <Badge tone="accent" title={source === 'USER_MASS' ? 'mass entered by you' : 'density entered by you'}>
          USER
        </Badge>
      );
    case 'WITHHELD':
      return (
        <Badge tone="err" title="mass properties withheld">
          WITHHELD
        </Badge>
      );
    default:
      return (
        <Badge tone="warn" title="assumed density (2,700 kg/m³ unless stated)">
          ASSUMED
        </Badge>
      );
  }
}

export function statusBadge(p: Part) {
  switch (p.status) {
    case 'VALID':
      return null;
    case 'REPAIRED':
      return (
        <Badge tone="warn" title={p.repairs.join(', ') || p.status_detail}>
          REPAIRED
        </Badge>
      );
    case 'WITHHELD':
      return (
        <Badge tone="err" title={p.status_detail}>
          WITHHELD
        </Badge>
      );
    case 'NEEDS_UNITS':
      return (
        <Badge tone="neutral" title="confirm the file units">
          UNITS?
        </Badge>
      );
    case 'ANALYSING':
      return (
        <Badge tone="neutral" title={p.status_detail || 'mesh checks, mass properties and proxies are being computed'}>
          ANALYSING…
        </Badge>
      );
  }
}

function FidelityIndicator({ id }: { id: string }) {
  const run = useApp((s) => s.solver.fidelityRuns[id]);
  if (!run || run.status === 'DONE') return null;
  return (
    <span className="badge neutral dashed" data-testid={`fidelity-running-${id}`} title="The detail-level study for this part is running in the background">
      detail study {run.progress != null ? `${Math.round(run.progress * 100)} %` : '…'}
    </span>
  );
}

export function PartsList() {
  const parts = useParts();
  const selected = useApp((s) => s.view.selectedPartId);
  const select = useApp((s) => s.select);
  const massEdits = useApp((s) => s.physical.massEdits);
  const uploading = useApp((s) => s.dataset.uploading);
  const error = useApp((s) => s.dataset.error);
  const setError = useApp((s) => s.setDatasetError);
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="stack" style={{ gap: 0, minHeight: 0, flex: 1 }}>
      <div className="panel-head">
        <h2>Parts ({parts.length})</h2>
        <div className="right">
          <Button size="small" onClick={() => input.current?.click()} data-testid="add-parts" disabled={uploading > 0}>
            {uploading ? 'Adding…' : 'Add parts'}
          </Button>
          <input
            ref={input}
            type="file"
            accept=".stl,model/stl,application/sla"
            multiple
            hidden
            data-testid="file-input"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = '';
              if (files.length) void session().addFiles(files);
            }}
          />
        </div>
      </div>
      {error ? (
        <div style={{ padding: '4px 8px' }}>
          <Notice tone="err" role="alert">
            {error}{' '}
            <button type="button" className="btn small" onClick={() => setError(null)}>
              Dismiss
            </button>
          </Notice>
        </div>
      ) : null}
      <div className="small muted" style={{ padding: '2px 10px' }}>
        Drop STL files anywhere on the window to add them.
      </div>
      <ul className="parts-list" role="listbox" aria-label="Parts" data-testid="parts-list">
        {parts.map((p) => {
          const m = massEdits[p.id]?.mass_kg ?? p.mass_kg;
          return (
            <li
              key={p.id}
              role="option"
              aria-selected={selected === p.id}
              tabIndex={0}
              onClick={() => select(p.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  select(p.id);
                } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                  e.preventDefault();
                  const sib = (e.currentTarget as HTMLElement)[e.key === 'ArrowDown' ? 'nextElementSibling' : 'previousElementSibling'] as HTMLElement | null;
                  sib?.focus();
                }
              }}
              data-testid={`part-${p.name}`}
            >
              <span className="swatch" style={{ background: subsystemColor(p.subsystem) }} title={SUBSYSTEM_LABELS[p.subsystem] ?? p.subsystem} />
              <span className="name">{p.name}</span>
              {statusBadge(p)}
              <FidelityIndicator id={p.id} />
              {p.locked ? <Badge tone="accent">LOCK</Badge> : null}
              <span className="num small">{fmt(m, 'kg')}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Mounting hardware of the displayed layout; metal 3D-printed brackets in their own section. */
const NO_ITEMS: never[] = [];

export function HardwareItemsList() {
  // selector must return a stable reference (a fresh [] would loop useSyncExternalStore)
  const items = useApp((s) => s.solver.best?.extra_items ?? NO_ITEMS);
  const parts = useApp((s) => s.dataset.parts);
  if (!items.length) return null;
  const am = items.filter((i) => extraItemStyle(i.process).section === 'METAL 3D-PRINTED');
  const other = items.filter((i) => extraItemStyle(i.process).section !== 'METAL 3D-PRINTED');
  const row = (i: (typeof items)[number]) => {
    const st = extraItemStyle(i.process);
    return (
      <li key={i.id} data-process={i.process}>
        <span className={`swatch ${st.hatch ? 'hatch' : ''}`} style={{ background: st.color }} />
        <span className="name">
          {i.kind === 'rod' && i.label ? i.label : `${st.label} — ${parts[i.for_part]?.name ?? i.for_part}`}
        </span>
        {st.badge ? <Badge tone="accent">{st.badge}</Badge> : null}
        <span className="num small">{fmt(i.mass_kg, 'kg')}</span>
      </li>
    );
  };
  return (
    <div data-testid="hardware-items">
      {am.length ? (
        <>
          <div className="panel-head">
            <h3>Metal 3D-printed ({am.length})</h3>
          </div>
          <ul className="parts-list" style={{ flex: 'none' }}>
            {am.map(row)}
          </ul>
        </>
      ) : null}
      {other.length ? (
        <>
          <div className="panel-head">
            <h3>Other hardware ({other.length})</h3>
          </div>
          <ul className="parts-list" style={{ flex: 'none' }}>
            {other.map(row)}
          </ul>
        </>
      ) : null}
    </div>
  );
}

/** Physical properties of the selected part. Edits go to the physical slice and `edit.part` only. */
export function PartInspector() {
  const id = useApp((s) => s.view.selectedPartId);
  const part = useApp((s) => (id ? s.dataset.parts[id] : null));
  const edit = useApp((s) => (id ? s.physical.massEdits[id] : undefined));
  const lockEdit = useApp((s) => (id ? s.physical.lockEdits[id] : undefined));
  const expert = useApp((s) => s.view.expert);
  if (!part) {
    return (
      <div className="panel-flat">
        <div className="panel-head">
          <h2>Part properties</h2>
          <span className="caption">physical — {PHYSICAL_CAPTION}</span>
        </div>
        <div className="panel-body muted small">Select a part to see and edit its physical properties.</div>
      </div>
    );
  }
  const mass = edit?.mass_kg ?? part.mass_kg;
  const locked = lockEdit?.locked ?? part.locked;
  const maxMass = Math.max(1, (part.mass_kg ?? 0.5) * 3);
  const canEditMass = part.status !== 'NEEDS_UNITS' && part.status !== 'ANALYSING';
  return (
    <div className="panel-flat" data-testid="part-inspector">
      <div className="panel-head">
        <h2>Part properties</h2>
        <span className="caption">physical — {PHYSICAL_CAPTION}</span>
      </div>
      <div className="panel-body stack">
        <div className="row">
          <strong>{part.name}</strong> {statusBadge(part)}
        </div>
        {part.status === 'WITHHELD' ? (
          <Notice tone="err">
            {part.status_detail}. Enter the mass yourself, or remove the part.
          </Notice>
        ) : null}
        <div>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <label htmlFor="mass-slider">Mass</label>
            {massBadge(edit ? 'USER_MASS' : part.mass_source)}
          </div>
          <input
            id="mass-slider"
            className="range"
            type="range"
            min={0.001}
            max={maxMass}
            step={0.001}
            value={mass ?? 0}
            disabled={!canEditMass || mass == null}
            aria-valuetext={`${fmt(mass, 'kg')}`}
            onChange={(e) => session().setMass(part.id, Number(e.target.value), false)}
            onPointerUp={(e) => session().setMass(part.id, Number((e.target as HTMLInputElement).value), true)}
            onKeyUp={(e) => session().setMass(part.id, Number((e.target as HTMLInputElement).value), true)}
            style={{ ['--fill' as string]: `${((mass ?? 0) / maxMass) * 100}%` }}
            data-testid="mass-slider"
          />
          <div className="row">
            <NumberField label="Mass in kilograms" value={mass} decimals={3} min={0.001} max={100} step={0.001} unit="kg" onCommit={(v) => session().setMass(part.id, v, true)} disabled={!canEditMass} />
            {edit && edit.client_seq !== null && !edit.committed ? <span className="small muted">sending…</span> : null}
          </div>
        </div>
        <dl className="kv">
          <dt>Density</dt>
          <dd className="num">{fmt(part.density_kg_m3, 'density')}</dd>
          <dt>Volume</dt>
          <dd className="num">{fmt(part.volume_mm3, 'mm3')}</dd>
          <dt>Size</dt>
          <dd className="num">{part.extents_mm.map((v) => fmt(v, 'mm', { unit: false })).join(' × ')} mm</dd>
          <dt>Subsystem</dt>
          <dd>{SUBSYSTEM_LABELS[part.subsystem] ?? part.subsystem}</dd>
          <dt>Shape</dt>
          <dd>{part.labels.join(', ') || '—'}</dd>
          {expert ? (
            <>
              <dt>COM (part frame)</dt>
              <dd className="num">{fmtVec(part.com_canonical_mm)}</dd>
              <dt>Triangles</dt>
              <dd className="num">
                {fmt(part.triangles, 'int')}
                {part.display_triangles !== part.triangles ? ` (display ${fmt(part.display_triangles, 'int')}, decimated)` : ''}
              </dd>
            </>
          ) : null}
        </dl>
        <div className="row">
          <label className="check">
            <input type="checkbox" checked={locked} onChange={(e) => session().setLocked(part.id, e.target.checked)} data-testid="lock-position" disabled={!canEditMass} />
            Lock position
          </label>
          <label className="check" title="The search may leave an optional part out when it does not fit; the “Include optional parts” goal sets how hard it tries.">
            <input type="checkbox" checked={(part.tags ?? []).includes('optional')} onChange={(e) => session().setOptional(part.id, e.target.checked)} data-testid="optional-part" disabled={!canEditMass} />
            Optional
          </label>
          <span style={{ flex: 1 }} />
          <Button size="small" onClick={() => void session().removePart(part.id)}>
            Remove part
          </Button>
        </div>
      </div>
    </div>
  );
}
