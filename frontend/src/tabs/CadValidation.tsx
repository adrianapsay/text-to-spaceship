import { useState } from 'react';
import { session } from '../api/session';
import { displayKind } from '../api/protocol';
import { useApp } from '../store/store';
import { useAsync } from '../hooks';
import { Badge, Button, Notice, Panel } from '../components/ui';

const CHECKLIST = [
  'Install Autodesk Fusion 360 on this computer (not done by this app).',
  'Confirm the installation and authorise the integration in a message to the project lead.',
  'Configure the local add-in folder the export package is copied to.',
  'Run the packaged import script inside Fusion 360 and return the result file.',
  'Ingest the result here (interference report and mass properties are compared with the app’s values).',
];

export function CadValidationTab() {
  const best = useApp((s) => s.solver.best);
  const newest = useApp((s) => s.conn.newest);
  const status = useAsync(() => session().api.cadStatus(), []);
  const [pkg, setPkg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const kind = best ? displayKind(best, newest) : null;
  const canPackage = kind === 'VALIDATED' || kind === 'FINAL';
  const build = async () => {
    if (!best) return;
    setErr(null);
    setPkg(null);
    try {
      const r = await session().api.cadPackage(best.id);
      setPkg(String(r.path ?? r.download ?? JSON.stringify(r)));
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <div className="tab-scroll" data-testid="tab-cad">
      <section className="panel" aria-labelledby="cad-status">
        <div className="panel-body">
          <h2 id="cad-status" style={{ margin: '4px 0 8px', fontSize: 'var(--fs-18)' }} data-testid="cad-card">
            FUSION 360 VALIDATION: NOT CONFIGURED
          </h2>
          <div className="small">
            Backend status: {status.data ? <Badge tone="warn">{status.data.status}</Badge> : status.notAvailable ? 'not reported' : status.error ? `error — ${status.error}` : '…'} {status.data?.detail ?? ''}
          </div>
          <p className="small muted">
            No Fusion API call has been made, and none will be made until the installation is confirmed and the integration is authorised. Validation in Fusion is an independent cross-check; it
            does not replace the app’s exact-mesh validator.
          </p>
        </div>
      </section>
      <div className="grid-2">
        <Panel title="Export package" caption="enabled only for a VALIDATED layout for the current inputs">
          <div className="row">
            <Button variant="primary" disabled={!canPackage} onClick={build} data-testid="cad-package">
              Build Fusion export package{best ? ` for ${best.id}` : ''}
            </Button>
            {!canPackage ? <span className="small muted">{best ? `The layout on screen is ${kind}.` : 'No layout on screen.'}</span> : null}
          </div>
          {pkg ? <Notice tone="ok">Package ready: {pkg}</Notice> : null}
          {err ? <Notice tone="err">{err}</Notice> : null}
        </Panel>
        <Panel title="Setup checklist" caption="deferred until you authorise">
          <ol className="small">
            {CHECKLIST.map((c) => (
              <li key={c}>
                <label className="check">
                  <input type="checkbox" disabled /> {c}
                </label>
              </li>
            ))}
          </ol>
          <div className="small muted">Result ingestion appears here once Fusion 360 validation is configured.</div>
        </Panel>
      </div>
    </div>
  );
}
