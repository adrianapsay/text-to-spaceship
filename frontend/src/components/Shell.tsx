import { useEffect, useState } from 'react';
import { session, hasSession } from '../api/session';
import { useApp } from '../store/store';
import { Badge } from './ui';
import { fmt } from '../lib/fmt';
import { runTime } from '../lib/runTime';

export function MockBanner() {
  const mode = useApp((s) => s.conn.mode);
  const reason = useApp((s) => s.conn.modeReason);
  const detected = useApp((s) => s.conn.backendDetected);
  if (mode !== 'mock') return null;
  return (
    <div className="mock-banner" role="note" data-testid="mock-banner">
      <span>MOCK DATA</span>
      <span style={{ fontWeight: 400 }}>
        In-browser mock backend ({reason}). Parts come from the synthetic dataset; layouts are placeholders, not optimisation results. Values marked MOCK are illustrative.
      </span>
      {detected ? (
        <button type="button" className="btn small" onClick={() => window.location.reload()}>
          A backend now answers /api/health — reload to use it
        </button>
      ) : null}
    </div>
  );
}

export function BackendStatus() {
  const mode = useApp((s) => s.conn.mode);
  const ws = useApp((s) => s.conn.wsState);
  const attempt = useApp((s) => s.conn.reconnectAttempt);
  const next = useApp((s) => s.conn.nextRetryMs);
  const tone = ws === 'open' ? 'ok' : ws === 'reconnecting' || ws === 'connecting' ? 'warn' : 'err';
  const text =
    ws === 'open'
      ? 'connected'
      : ws === 'reconnecting'
        ? `reconnecting${next ? ` in ${(next / 1000).toFixed(2)} s` : ''} (attempt ${attempt})`
        : ws === 'connecting'
          ? 'connecting…'
          : ws === 'closed'
            ? 'disconnected'
            : 'starting…';
  return (
    <span className="row" style={{ gap: 6 }} data-testid="backend-status">
      <span className="muted">Backend:</span>
      <Badge tone={tone}>{text}</Badge>
      {mode === 'mock' ? <Badge tone="mock">MOCK</Badge> : null}
    </span>
  );
}

export function TopBar() {
  const project = useApp((s) => s.dataset.project);
  const settings = useApp((s) => s.goals.settings);
  const runStatus = useApp((s) => s.solver.runStatus);
  const expert = useApp((s) => s.view.expert);
  const setExpert = useApp((s) => s.setExpert);
  const stage = settings?.stage ?? 1;
  const searching = runStatus === 'SEARCHING' || runStatus === 'REVALIDATING';
  return (
    <header className="topbar" role="banner">
      <span className="brand" title="TEXT-TO-SPACESHIP">
        T2S
      </span>
      <span className="muted" data-testid="project-name">
        {project?.name ?? 'Loading project…'}
      </span>
      <span className="sep" />
      <Badge tone="neutral">{settings?.form_factor ?? '3U'}</Badge>
      <label className="row" style={{ gap: 4 }}>
        <span className="sr-only">Stage</span>
        <select
          aria-label="Stage"
          data-testid="stage-select"
          value={stage}
          disabled={!settings}
          onChange={(e) => hasSession() && session().setStage(Number(e.target.value) as 1 | 2)}
        >
          <option value={1}>Stage 1 IDEALIZED</option>
          <option value={2}>Stage 2 ENGINEERING-CONSTRAINED</option>
        </select>
      </label>
      <span className="sep" />
      <BackendStatus />
      <span className="spacer" />
      <button
        type="button"
        className="btn primary"
        data-testid="optimise"
        disabled={searching || !hasSession()}
        onClick={() => session().run(runStatus === 'PAUSED' ? 'resume' : 'start')}
      >
        {runStatus === 'PAUSED' ? 'Resume' : 'Optimise'}
      </button>
      <button type="button" className="btn" data-testid="pause" disabled={!searching} onClick={() => session().run('pause')}>
        Pause
      </button>
      <span className="sep" />
      <div className="seg" role="group" aria-label="Detail level">
        <button type="button" className="btn small" aria-pressed={!expert} onClick={() => setExpert(false)}>
          Beginner
        </button>
        <button type="button" className="btn small" aria-pressed={expert} onClick={() => setExpert(true)} data-testid="expert-toggle">
          Expert
        </button>
      </div>
    </header>
  );
}

export function StatusBar() {
  const runStatus = useApp((s) => s.solver.runStatus);
  const detail = useApp((s) => s.solver.statusDetail);
  const progress = useApp((s) => s.solver.progress);
  const newest = useApp((s) => s.conn.newest);
  const lastAt = useApp((s) => s.conn.lastMessageAt);
  const applied = useApp((s) => s.conn.appliedClientSeq);
  const sent = useApp((s) => s.conn.lastClientSeqSent);
  const error = useApp((s) => s.solver.lastError);
  const fid = useApp((s) => s.solver.fidelityRuns);
  const running = Object.entries(fid).filter(([, r]) => r.status !== 'DONE').length;
  const rt = runTime(progress, runStatus);
  const [, force] = useState(0);
  useEffect(() => {
    const t = setInterval(() => force((x) => x + 1), 5000);
    return () => clearInterval(t);
  }, []);
  return (
    <footer className="statusbar" role="contentinfo" data-testid="status-bar">
      <span>
        Optimiser: <strong>{runStatus}</strong>
        {detail ? ` — ${detail}` : ''}
      </span>
      {rt ? (
        <span title={rt.title} data-testid="run-time">
          {rt.text}
        </span>
      ) : null}
      {progress ? <span>evaluations {fmt(progress.evaluations, 'int')}</span> : null}
      {running ? <span data-testid="fidelity-running-status">detail study running for {running} part(s)</span> : null}
      <span>{applied >= sent ? 'in sync' : `updating… (edit ${sent}, applied ${applied})`}</span>
      <span title="newest revisions received">
        epoch {newest.epoch} · parts r{newest.parts_rev} · constraints r{newest.constraint_rev} · mass r{newest.mass_rev} · weights r{newest.weights_rev}
      </span>
      {lastAt ? <span>last message {new Date(lastAt).toLocaleTimeString()}</span> : null}
      {error ? <span style={{ color: 'var(--err)' }}>error: {error}</span> : null}
    </footer>
  );
}

/** Screen-reader announcements for selection and state changes. */
export function LiveRegion() {
  const text = useApp((s) => s.view.announce);
  return (
    <div className="sr-only" role="status" aria-live="polite" data-testid="live-region">
      {text}
    </div>
  );
}

/** Drop STL files anywhere on the window → POST /api/parts. */
export function DropZone() {
  const [over, setOver] = useState(false);
  useEffect(() => {
    let depth = 0;
    const hasFiles = (e: DragEvent) => !!e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files');
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth++;
      setOver(true);
      e.preventDefault();
    };
    const overH = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setOver(false);
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      setOver(false);
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (files.length && hasSession()) void session().addFiles(files);
    };
    window.addEventListener('dragenter', enter);
    window.addEventListener('dragover', overH);
    window.addEventListener('dragleave', leave);
    window.addEventListener('drop', drop);
    return () => {
      window.removeEventListener('dragenter', enter);
      window.removeEventListener('dragover', overH);
      window.removeEventListener('dragleave', leave);
      window.removeEventListener('drop', drop);
    };
  }, []);
  if (!over) return null;
  return <div className="drop-overlay">Drop STL files to add them as parts</div>;
}
