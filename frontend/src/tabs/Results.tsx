import { useState } from 'react';
import type { ExportKind } from '../api/rest';
import { session } from '../api/session';
import { displayKind, badgeText, layoutCoverage } from '../api/protocol';
import { useApp } from '../store/store';
import { useParts } from '../hooks';
import { LayoutCompare, useFullLayout, useLayoutList } from '../components/LayoutCompare';
import { Badge, Button, EmptyState, KV, MockTag, Notice, Panel } from '../components/ui';
import { fmt, fmtTime } from '../lib/fmt';
import type { LayoutSummary } from '../api/types';

const EXPORTS: { kind: ExportKind; label: string; ext: string }[] = [
  { kind: 'report_md', label: 'Report (Markdown)', ext: 'md' },
  { kind: 'report_html', label: 'Report (HTML)', ext: 'html' },
  { kind: 'csv', label: 'Poses (CSV)', ext: 'csv' },
  { kind: 'json', label: 'Layout (JSON)', ext: 'json' },
  { kind: 'stl_zip', label: 'Placed STL files (ZIP)', ext: 'zip' },
];

function Provenance({ id }: { id: string }) {
  const l = useFullLayout(id);
  const project = useApp((s) => s.dataset.project);
  if (!l.data) return <span className="muted small">{l.error ?? 'Loading…'}</span>;
  const v = l.data.validation;
  return (
    <KV
      rows={[
        ['Layout', `${l.data.id} (hash ${l.data.hash})`],
        ['Stage / mode', `${l.data.stage === 2 ? 'ENGINEERING-CONSTRAINED' : 'IDEALIZED'} · ${l.data.mode}`],
        ['Status', l.data.status],
        ['Revisions', `parts r${l.data.parts_rev} · constraints r${l.data.constraint_rev} · mass r${l.data.mass_rev} · weights r${l.data.weights_rev}`],
        ['Algorithm', l.data.algorithm ? `${l.data.algorithm.label}${l.data.algorithm.reason ? ` — ${l.data.algorithm.reason}` : ''}` : '—'],
        ['Origin', l.data.origin],
        ['Created', fmtTime(l.data.created)],
        ['Validation', v ? `${v.certified ? 'certified' : 'not certified'} · validator ${v.validator_version} · tolerance ${fmt(v.tolerance_mm, 'clearance')} · ${v.pairs ?? '—'} pairs · ${fmtTime(v.checked_at)}` : '—'],
        ['Dataset', project?.dataset_sha256 ? `${project.dataset_sha256.slice(0, 16)}…` : '—'],
      ]}
    />
  );
}

export function ResultsTab() {
  const best = useApp((s) => s.solver.best);
  const newest = useApp((s) => s.conn.newest);
  const parts = useParts();
  const finals = useLayoutList('FINAL');
  const history = useLayoutList(undefined, 100);
  const [selected, setSelected] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null);
  const target = selected ?? best?.id ?? null;
  const freeze = async (id: string) => {
    setMsg(null);
    try {
      const l = await session().api.finalize(id);
      setMsg({ tone: 'ok', text: `${l.id} frozen as FINAL after full re-validation.` });
      finals.reload();
      history.reload();
    } catch (e) {
      setMsg({ tone: 'err', text: `Could not freeze ${id}: ${(e as Error).message}` });
    }
  };
  const exp = async (kind: ExportKind, ext: string) => {
    if (!target) return;
    setMsg(null);
    try {
      await session().api.download(session().api.exportPath(target, kind), `${target}.${ext}`);
    } catch (e) {
      setMsg({ tone: 'err', text: `Export ${kind} failed: ${(e as Error).message}` });
    }
  };
  const row = (l: LayoutSummary) => {
    const kind = displayKind({ ...l, poses: [], extra_items: [], scores: null, algorithm: null, validation: null, origin: '', created: '', hash: l.hash ?? '', mode: l.mode ?? 'default', mass_rev: l.mass_rev ?? 0, weights_rev: l.weights_rev ?? 0 } as never, newest, 'archive');
    const missing = l.part_ids ? parts.filter((p) => (p.status === 'VALID' || p.status === 'REPAIRED') && !l.part_ids!.includes(p.id)) : [];
    return (
      <tr key={l.id} aria-selected={target === l.id} onClick={() => setSelected(l.id)} style={{ cursor: 'pointer' }}>
        <td className="num">{l.id}</td>
        <td>{l.stage === 2 ? 'ENGINEERING' : 'IDEALIZED'}</td>
        <td>
          <Badge tone={kind === 'VALIDATED' || kind === 'FINAL' ? 'ok' : 'warn'}>{badgeText(kind)}</Badge>
          {missing.length ? <Badge tone="warn">does not include {missing.map((p) => p.name).join(', ')}</Badge> : null}
        </td>
        <td className="num">{fmt(l.metrics?.length_used_mm ?? null, 'mm')}</td>
        <td className="num">{fmt(l.metrics?.com_error_mm ?? null, 'mm')}</td>
        <td className="num">{fmt(l.metrics?.lambda_max_kgm2 ?? null, 'kgm2')}</td>
        <td className="small">{fmtTime(l.created)}</td>
        <td>
          <Button size="small" onClick={() => void freeze(l.id)} disabled={!(kind === 'VALIDATED')}>
            Freeze as FINAL
          </Button>
        </td>
      </tr>
    );
  };
  const table = (list: LayoutSummary[], testId: string) => (
    <div className="table-wrap" style={{ maxHeight: 300 }}>
      <table className="data" data-testid={testId}>
        <thead>
          <tr>
            <th>Layout</th>
            <th>Kind</th>
            <th>Status</th>
            <th className="num">Length used</th>
            <th className="num">Balance error</th>
            <th className="num">λ_max</th>
            <th>Created</th>
            <th />
          </tr>
        </thead>
        <tbody>{list.map(row)}</tbody>
      </table>
    </div>
  );
  const cov = best ? layoutCoverage(best, parts) : null;
  return (
    <div className="tab-scroll" data-testid="tab-results">
      {msg ? <Notice tone={msg.tone}>{msg.text}</Notice> : null}
      <div className="grid-2">
        <Panel title="FINAL layouts" caption="frozen snapshots, fully re-validated; the source for exports" right={<MockTag />}>
          {finals.notAvailable ? (
            <EmptyState title="No layout archive from the backend yet" />
          ) : finals.data?.length ? (
            table(finals.data, 'finals-table')
          ) : (
            <EmptyState title="No FINAL layouts yet">Freeze a VALIDATED layout from the history below.</EmptyState>
          )}
        </Panel>
        <Panel title="Export" caption={target ? `layout ${target}` : 'select a layout'}>
          <div className="row">
            {EXPORTS.map((e) => (
              <Button key={e.kind} size="small" disabled={!target} onClick={() => void exp(e.kind, e.ext)}>
                {e.label}
              </Button>
            ))}
          </div>
          {cov?.missing.length ? <Notice tone="warn">The current layout does not include {cov.missing.map((p) => p.name).join(', ')}.</Notice> : null}
          <h3 className="small" style={{ marginTop: 12 }}>
            Provenance
          </h3>
          {target ? <Provenance id={target} /> : <span className="muted small">—</span>}
        </Panel>
      </div>
      <Panel title="History" caption="validated layouts in the archive; restoring re-validates against the current inputs (restore needs a backend endpoint — not in the contract yet)">
        {history.notAvailable ? <EmptyState title="No layout archive from the backend yet" /> : history.data?.length ? table(history.data, 'history-table') : <EmptyState title="No layouts yet" />}
      </Panel>
      <Panel title="Compare two configurations">
        <LayoutCompare testId="results-compare" />
      </Panel>
    </div>
  );
}
