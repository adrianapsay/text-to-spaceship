// V3 CubeSat Builder tab: from a mission idea to an engineering-informed CubeSat design. Sections: Mission Setup
// (adaptive questions), Recommended Architecture (parts and checks), Component Catalog, 3D Preview, Engineering
// Analysis, Trade Study and Design Summary. Every change to the design is analysed again; until the new analysis is
// in, the old one is dimmed and labelled with the design version it describes.
import { useCallback, useEffect, useRef, useState } from 'react';
import { session } from '../api/session';
import { useApp } from '../store/store';
import { useAsync } from '../hooks';
import type { BuilderResponse, DesignSummary, Finding, QuestionView } from '../builder/types';
import type { Analysis, CadList, CatalogList, ProjectInfo, SlotInfo } from '../builder/analysisTypes';
import { Findings, QuestionCard, RequirementsPanel } from '../builder/MissionSetup';
import { AnalysisSection } from '../builder/AnalysisView';
import { ArchitectureSection } from '../builder/ArchitectureView';
import { CatalogSection } from '../builder/CatalogView';
import { PreviewSection } from '../builder/PreviewView';
import { SendSection } from '../builder/SendView';
import { SummarySection } from '../builder/SummaryView';
import { TradeSection, type PrefsPatch } from '../builder/TradeView';
import { Button, EmptyState, Notice, Panel } from '../components/ui';

const LAST = 't2s.builder.design';

function remember(id: string | null) {
  try {
    if (id) localStorage.setItem(LAST, id);
    else localStorage.removeItem(LAST);
  } catch {
    /* private window: not remembered */
  }
}
function recalled(): string | null {
  try {
    return localStorage.getItem(LAST);
  } catch {
    return null;
  }
}

export const BUILDER_SECTIONS = [
  { id: 'setup', label: 'Mission Setup' },
  { id: 'architecture', label: 'Recommended Architecture' },
  { id: 'catalog', label: 'Component Catalog' },
  { id: 'preview', label: '3D Preview' },
  { id: 'analysis', label: 'Engineering Analysis' },
  { id: 'trade', label: 'Trade Study' },
  { id: 'summary', label: 'Design Summary' },
  { id: 'send', label: 'Send to Optimization' },
] as const;
type SectionId = (typeof BUILDER_SECTIONS)[number]['id'];
const NEEDS_ANALYSIS: SectionId[] = ['architecture', 'preview', 'analysis', 'trade', 'summary', 'send'];

function NewDesign(props: { onCreated: (r: BuilderResponse) => void; busy: boolean; setBusy: (b: boolean) => void }) {
  const [text, setText] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const start = async (statement: string) => {
    props.setBusy(true);
    setErr(null);
    try {
      props.onCreated(await session().api.builderCreate({ statement: statement.trim() || undefined }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      props.setBusy(false);
    }
  };
  return (
    <Panel title="Start a new mission" caption="describe your idea in a sentence; the Builder asks only what it still needs">
      <textarea
        aria-label="Mission description"
        rows={3}
        style={{ width: '100%', maxWidth: 720 }}
        placeholder="For example: I want to build a satellite that photographs California from orbit."
        value={text}
        onChange={(e) => setText(e.target.value)}
        data-testid="statement-input"
      />
      <div className="row" style={{ gap: 8, marginTop: 6 }}>
        <Button variant="primary" disabled={props.busy || !text.trim()} onClick={() => void start(text)} data-testid="start-mission">
          Start
        </Button>
        <Button disabled={props.busy} onClick={() => void start('')}>
          Start without a description
        </Button>
      </div>
      {err ? <Notice tone="err">{err}</Notice> : null}
    </Panel>
  );
}

/** Questions the analysis answered with their defaults, with a way back to them. */
function OpenQuestions({ a, onAnswer }: { a: Analysis; onAnswer: () => void }) {
  const basic = a.open_questions.filter((q) => !q.advanced);
  if (!basic.length) return null;
  return (
    <Notice tone="info">
      {basic.length} question{basic.length > 1 ? 's are' : ' is'} still open; the analysis uses {basic.length > 1 ? 'their defaults' : 'its default'} (ASSUMED):{' '}
      {basic
        .slice(0, 4)
        .map((q) => `${q.prompt} → ${q.default}`)
        .join('; ')}
      {basic.length > 4 ? '; …' : ''}.{' '}
      <Button size="small" onClick={onAnswer}>
        Answer them
      </Button>
    </Notice>
  );
}

export function BuilderTab() {
  const expert = useApp((s) => s.view.expert);
  const designs = useAsync(() => session().api.builderDesigns(), []);
  const meta = useAsync(() => session().api.builderMeta(), []);
  const [current, setCurrent] = useState<BuilderResponse | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<QuestionView | null>(null);
  const [section, setSection] = useState<SectionId>('setup');
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [aErr, setAErr] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<CatalogList | null>(null);
  const [cad, setCad] = useState<CadList | null>(null);
  const [geometryRev, setGeometryRev] = useState(0);
  const [projects, setProjects] = useState<{ projects: ProjectInfo[]; current: string } | null>(null);
  const [sentNote, setSentNote] = useState<string | null>(null);
  const request = useRef(0);
  const shownId = useRef<string | null>(null);         // the design on screen (its findings survive a list refresh)
  const list: DesignSummary[] = designs.data?.designs ?? [];
  const slots: SlotInfo[] = meta.data?.slots ?? [];

  const open = useCallback(
    async (id: string) => {
      setErr(null);
      try {
        const r = await session().api.builderGet(id, expert);
        setCurrent(r);
        if (shownId.current !== id) setFindings([]);
        shownId.current = id;
        setEditing(null);
        remember(id);
      } catch (e) {
        setErr((e as Error).message);
        remember(null);
      }
    },
    [expert],
  );
  // open the last design (or the newest) once the list is in; reload it when expert mode changes
  useEffect(() => {
    if (designs.loading || creating) return;
    const id = current?.design.id ?? recalled() ?? list[0]?.id;
    if (id && list.some((d) => d.id === id)) void open(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [designs.loading, expert]);

  // analyse every new version of the design; an answer that arrives late for an older version is dropped
  const did = current?.design.id;
  const version = current?.design.version;
  useEffect(() => {
    if (!did) {
      setAnalysis(null);
      return;
    }
    const n = ++request.current;
    setAnalysing(true);
    session()
      .api.builderAnalysis(did)
      .then((a) => {
        if (n !== request.current) return;
        setAnalysis(a);
        setAErr(null);
      })
      .catch((e: Error) => {
        if (n === request.current) setAErr(e.message);
      })
      .finally(() => {
        if (n === request.current) setAnalysing(false);
      });
  }, [did, version, geometryRev]);
  useEffect(() => {
    if (catalog || !(section === 'catalog' || section === 'architecture')) return;
    session()
      .api.builderCatalog()
      .then(setCatalog)
      .catch((e: Error) => setErr(e.message));
  }, [section, catalog]);
  useEffect(() => {
    if (section !== 'catalog') return;
    session()
      .api.builderCad()
      .then(setCad)
      .catch((e: Error) => setErr(e.message));
  }, [section, geometryRev]);
  useEffect(() => {
    if (section !== 'send') return;
    session()
      .api.projects()
      .then(setProjects)
      .catch((e: Error) => setErr(e.message));
  }, [section, version]);
  /** sending, or switching project: the server closes the page's connection (4001) and the page reloads onto it */
  const sendToOptimization = async () => {
    if (!did) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await session().api.builderSend(did, true);
      setSentNote(`Sent as ${r.project}; the optimiser now runs on it — reloading…`);
      setTimeout(() => window.location.reload(), 1500);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };
  const switchProject = async (name: string) => {
    setBusy(true);
    setErr(null);
    try {
      await session().api.projectSwitch(name);
      setSentNote(`The optimiser now runs on ${name} — reloading…`);
      setTimeout(() => window.location.reload(), 800);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };
  /** a CAD change: then the geometry list and the analysis's geometry labels are read again */
  const cadAct = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
      setGeometryRev((v) => v + 1);
    }
  };

  const act = async (fn: () => Promise<BuilderResponse>) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fn();
      setCurrent(r);
      setEditing(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const editQuestion = async (qid: string) => {
    if (!current) return;
    const all = await session().api.builderQuestions(current.design.id, true);
    setEditing(all.questions.find((q) => q.id === qid) ?? null);
    setSection('setup');
  };

  if (designs.loading && !designs.data) return <div className="tab-scroll muted">Loading…</div>;
  const id = current?.design.id;
  const q = editing ?? current?.view.next ?? null;
  const shown = analysis && analysis.design_id === id ? analysis : null;
  const stale = !!shown && (analysing || shown.design_version !== current?.design.version);
  const select = (slot: string, component: string | null, qty: number) => {
    if (id) void act(() => session().api.builderSelect(id, slot, component, qty, expert));
  };
  const unselect = (slot: string) => {
    if (id) void act(() => session().api.builderUnselect(id, slot, expert));
  };
  const prefs = (p: PrefsPatch) => {
    if (id) void act(() => session().api.builderPrefs(id, p, expert));
  };
  return (
    <div className="tab-scroll" data-testid="tab-builder">
      <div className="row" style={{ gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <strong>CubeSat Builder</strong>
        {list.length ? (
          <select aria-label="Design" value={id ?? ''} onChange={(e) => void open(e.target.value)} data-testid="design-select">
            {!id ? <option value="">Choose a design…</option> : null}
            {list.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({d.id})
              </option>
            ))}
          </select>
        ) : null}
        <Button size="small" onClick={() => setCreating(true)} data-testid="new-design">
          New design
        </Button>
        <nav className="row" style={{ gap: 4, flexWrap: 'wrap' }} aria-label="Builder sections">
          {BUILDER_SECTIONS.map((s) => (
            <button key={s.id} type="button" className="btn small" aria-pressed={section === s.id} onClick={() => setSection(s.id)} data-testid={`section-${s.id}`}>
              {s.label}
            </button>
          ))}
        </nav>
        {current && NEEDS_ANALYSIS.includes(section) ? (
          <span className="small muted" role="status">
            {analysing ? 'Analysing…' : shown ? `Analysis of version ${shown.design_version}` : null}
          </span>
        ) : null}
      </div>
      {err ? <Notice tone="err">{err}</Notice> : null}
      {creating || !list.length ? (
        <NewDesign
          busy={busy}
          setBusy={setBusy}
          onCreated={(r) => {
            setCurrent(r);
            shownId.current = r.design.id;
            setFindings(r.findings ?? []);
            setCreating(false);
            setSection('setup');
            remember(r.design.id);
            designs.reload();
          }}
        />
      ) : null}
      {!current && !creating && list.length ? <EmptyState title="Choose a design">Pick one above, or start a new mission.</EmptyState> : null}
      {current && !creating && section === 'setup' ? (
        <div className="grid-2" data-testid="mission-setup">
          <Panel title={current.design.name} caption="Mission Setup — answer what you know; say “I don't know” for the rest">
            <div className="bq-chat">
              <Findings statement={current.design.statement} findings={findings} />
              {q ? (
                <QuestionCard
                  q={q}
                  busy={busy}
                  onAnswer={(v) => void act(() => session().api.builderAnswer(current.design.id, q.id, { value: v }, expert))}
                  onUnknown={() => void act(() => session().api.builderAnswer(current.design.id, q.id, { unknown: true }, expert))}
                  onCancel={editing ? () => setEditing(null) : undefined}
                />
              ) : (
                <Notice tone="ok">
                  Every question that applies is answered{expert ? '' : ' (switch to Expert for the advanced ones)'}. Change any answer on the right; see the{' '}
                  <Button size="small" onClick={() => setSection('architecture')}>
                    Recommended Architecture
                  </Button>
                </Notice>
              )}
              {current.view.next && !editing ? (
                <div className="row small" style={{ gap: 8, marginTop: 8 }}>
                  <Button size="small" disabled={busy} onClick={() => void act(() => session().api.builderDefaults(current.design.id, expert))} data-testid="accept-defaults">
                    Use the defaults for the rest
                  </Button>
                  <span className="muted">{current.view.pending.length} question(s) left</span>
                </div>
              ) : null}
            </div>
          </Panel>
          <RequirementsPanel view={current.view} busy={busy} onEdit={(qid) => void editQuestion(qid)} />
        </div>
      ) : null}
      {current && !creating && section === 'catalog' ? (
        <CatalogSection
          catalog={catalog}
          slots={slots}
          busy={busy}
          onUse={(slot, c) => select(slot, c, 1)}
          cad={cad}
          onCadImport={(cid, f) => void cadAct(() => session().api.builderCadImport(cid, f))}
          onCadSimplified={(cid) => void cadAct(() => session().api.builderCadSimplified(cid))}
          onCadDelete={(cid) => void cadAct(() => session().api.builderCadDelete(cid))}
        />
      ) : null}
      {current && !creating && NEEDS_ANALYSIS.includes(section) ? (
        <div className="stack">
          {aErr ? <Notice tone="err">The analysis failed: {aErr}</Notice> : null}
          {!shown ? (
            <span className="muted">{analysing ? 'Analysing the design…' : 'No analysis yet.'}</span>
          ) : (
            <>
              <OpenQuestions a={shown} onAnswer={() => setSection('setup')} />
              {section === 'architecture' ? (
                <ArchitectureSection a={shown} stale={stale} busy={busy} catalog={catalog} slots={slots} onSelect={select} onUnselect={unselect} />
              ) : null}
              {section === 'preview' ? <PreviewSection a={shown} stale={stale} /> : null}
              {section === 'analysis' ? <AnalysisSection a={shown} stale={stale} expert={expert} /> : null}
              {section === 'trade' ? <TradeSection a={shown} stale={stale} busy={busy} onPrefs={prefs} /> : null}
              {section === 'summary' ? <SummarySection r={current} a={shown} stale={stale} /> : null}
              {section === 'send' ? (
                <>
                  {sentNote ? <Notice tone="ok">{sentNote}</Notice> : null}
                  <SendSection
                    a={shown}
                    stale={stale}
                    busy={busy}
                    projects={projects}
                    sentBy={current.design.sent ?? []}
                    onSend={() => void sendToOptimization()}
                    onSwitch={(n) => void switchProject(n)}
                  />
                </>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
