import { Dialog } from 'radix-ui';
import { useEffect, useState } from 'react';
import type { Units } from '../api/types';
import { session } from '../api/session';
import { useApp } from '../store/store';
import { fmt } from '../lib/fmt';
import { unitAdvice, UNIT_FACTORS, UNIT_LABELS } from '../lib/units';
import { Notice } from './ui';

/** Units confirmation for NEEDS_UNITS parts: millimetres by default, warns when extents suggest inches / metres. */
export function UnitsDialog() {
  const queue = useApp((s) => s.dataset.unitsQueue);
  const parts = useApp((s) => s.dataset.parts);
  const id = queue.find((q) => parts[q]?.status === 'NEEDS_UNITS') ?? null;
  const part = id ? parts[id] : null;
  const [units, setUnits] = useState<Units>('mm');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setUnits('mm');
    setBusy(false);
  }, [id]);
  if (!part) return null;
  const advice = unitAdvice(part.extents_mm, units);
  const scaled = part.extents_mm.map((v) => v * UNIT_FACTORS[units]);
  const confirm = async () => {
    setBusy(true);
    await session().confirmUnits(part.id, units);
    setBusy(false);
  };
  return (
    <Dialog.Root open onOpenChange={() => undefined}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog" data-testid="units-dialog" onEscapeKeyDown={(e) => e.preventDefault()} onPointerDownOutside={(e) => e.preventDefault()}>
          <Dialog.Title>Confirm the units of “{part.name}”</Dialog.Title>
          <Dialog.Description className="muted">
            STL files carry no units. Choose what one file unit means. The geometry is only scaled; nothing else changes.
            {queue.length > 1 ? ` (${queue.length - 1} more file${queue.length > 2 ? 's' : ''} waiting)` : ''}
          </Dialog.Description>
          <div className="stack" style={{ marginTop: 10 }}>
            <div className="small">
              File: <strong>{part.file}</strong> · {fmt(part.triangles, 'int')} triangles · raw size {part.extents_mm.map((v) => Number(v.toPrecision(4))).join(' × ')} (file units)
            </div>
            <fieldset style={{ border: '1px solid var(--border-subtle)', padding: '6px 10px' }}>
              <legend>Units</legend>
              {(Object.keys(UNIT_FACTORS) as Units[]).map((u) => (
                <label key={u} className="check" style={{ marginRight: 14 }}>
                  <input type="radio" name="units" value={u} checked={units === u} onChange={() => setUnits(u)} data-testid={`units-${u}`} />
                  {UNIT_LABELS[u]}
                  {u === 'mm' ? ' — default' : ''}
                </label>
              ))}
            </fieldset>
            <div className="small" data-testid="units-preview">
              Size in millimetres: {scaled.map((v) => fmt(v, 'mm', { unit: false })).join(' × ')} mm
            </div>
            {advice.warnings.map((w, i) => (
              <Notice key={i} tone="warn" role="alert">
                {w}
              </Notice>
            ))}
            {advice.suggest && advice.suggest !== units ? (
              <div>
                <button type="button" className="btn small" onClick={() => setUnits(advice.suggest!)}>
                  Use {UNIT_LABELS[advice.suggest]}
                </button>
              </div>
            ) : null}
          </div>
          <div className="row" style={{ justifyContent: 'flex-end', marginTop: 14 }}>
            <button
              type="button"
              className="btn"
              onClick={() => {
                void session().removePart(part.id);
              }}
            >
              Leave this part out
            </button>
            <button type="button" className="btn primary" disabled={busy} onClick={confirm} data-testid="units-confirm">
              Confirm {units}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
