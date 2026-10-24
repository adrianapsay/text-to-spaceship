// V2 WS6: Engineering Drawings of the shown layout, on a CAD-style sheet (ISO A3 first-angle by default, ANSI B
// third-angle as the alternative): sheet 1 is the assembly (front, top, side and isometric views, overall dimensions,
// balloons numbered like the bill of materials), then one detail sheet per designed bracket. The views are rendered
// from the same meshes as the 3D view and follow the design: a new best layout, designed brackets, part edits.
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent as RPointerEvent, type ReactNode } from 'react';
import { badgeText } from '../api/protocol';
import { Button, EmptyState, MockTag, Notice } from '../components/ui';
import { downloadSvg, exportableSvg, printSheets, sheetMarkup } from '../components/drawing/print';
import { DrawingSheet, SheetPlaceholder } from '../components/drawing/SheetSvg';
import { TEMPLATES, type SheetTemplate, type TemplateId } from '../components/drawing/sheet';
import { useDrawingSet } from '../components/drawing/useDrawing';
import { useBom, useShownLayout } from '../lib/bom';
import { useApp } from '../store/store';
import '../components/drawing/drawing.css';

interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

const PREF = 't2s.drawings.template';
function readTemplate(): TemplateId {
  try {
    const v = globalThis.localStorage?.getItem(PREF);
    return v === 'ansi-b' ? 'ansi-b' : 'iso-a3';
  } catch {
    return 'iso-a3';
  }
}
function saveTemplate(v: TemplateId) {
  try {
    globalThis.localStorage?.setItem(PREF, v);
  } catch {
    /* a convenience only */
  }
}

export function fitBox(t: SheetTemplate): ViewBox {
  const m = 6;
  return { x: -m, y: -m, w: t.width + 2 * m, h: t.height + 2 * m };
}

const HELP = 'Wheel or + and − zoom about the pointer, drag or the arrow keys pan, 0 fits the sheet. Balloons and parts-list rows select their part in the 3D views.';

function SheetViewport(props: { t: SheetTemplate; vb: ViewBox; setVb: (f: (v: ViewBox) => ViewBox) => void; stale: boolean; status: string | null; children: (viewBox: string) => ReactNode }) {
  const { t, setVb } = props;
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; id: number; moved: boolean } | null>(null);
  const [panning, setPanning] = useState(false);
  /** screen pixels per sheet mm for a view box, and the letterbox offsets of preserveAspectRatio meet (computed from
   * the view box being updated, so that a burst of wheel events zooms about the pointer too) */
  const fitOf = useCallback((vb: ViewBox) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r || !r.width || !r.height) return null;
    const s = Math.min(r.width / vb.w, r.height / vb.h);
    return { r, s, ox: (r.width - vb.w * s) / 2, oy: (r.height - vb.h * s) / 2 };
  }, []);
  const zoom = useCallback(
    (f: number, clientX?: number, clientY?: number) => {
      setVb((vb) => {
        const m = fitOf(vb);
        const w = Math.min(t.width * 3, Math.max(t.width / 40, vb.w * f));
        const k = w / vb.w;
        const px = m && clientX != null ? vb.x + (clientX - m.r.left - m.ox) / m.s : vb.x + vb.w / 2;
        const py = m && clientY != null ? vb.y + (clientY - m.r.top - m.oy) / m.s : vb.y + vb.h / 2;
        return { x: px - (px - vb.x) * k, y: py - (py - vb.y) * k, w, h: vb.h * k };
      });
    },
    [fitOf, setVb, t.width],
  );
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      zoom(e.deltaY > 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoom]);
  const down = (e: RPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 && e.button !== 1) return;
    drag.current = { x: e.clientX, y: e.clientY, id: e.pointerId, moved: false };
  };
  const move = (e: RPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 3) return;
    if (!d.moved) {
      d.moved = true;
      setPanning(true);
      ref.current?.setPointerCapture?.(e.pointerId);
    }
    d.x = e.clientX;
    d.y = e.clientY;
    setVb((vb) => {
      const m = fitOf(vb);
      return m ? { ...vb, x: vb.x - dx / m.s, y: vb.y - dy / m.s } : vb;
    });
  };
  const up = (e: RPointerEvent<HTMLDivElement>) => {
    if (drag.current?.moved) ref.current?.releasePointerCapture?.(e.pointerId);
    drag.current = null;
    setPanning(false);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = (sx: number, sy: number) => setVb((vb) => ({ ...vb, x: vb.x + sx * vb.w * 0.1, y: vb.y + sy * vb.h * 0.1 }));
    if (e.target !== e.currentTarget) return;
    if (e.key === '+' || e.key === '=') zoom(1 / 1.25);
    else if (e.key === '-') zoom(1.25);
    else if (e.key === '0') setVb(() => fitBox(t));
    else if (e.key === 'ArrowLeft') step(-1, 0);
    else if (e.key === 'ArrowRight') step(1, 0);
    else if (e.key === 'ArrowUp') step(0, -1);
    else if (e.key === 'ArrowDown') step(0, 1);
    else return;
    e.preventDefault();
  };
  const vb = props.vb;
  return (
    <div
      ref={ref}
      className={`sheet-viewport${panning ? ' panning' : ''}${props.stale ? ' stale' : ''}`}
      tabIndex={0}
      role="group"
      aria-label="Drawing sheet (zoom and pan)"
      aria-describedby="sheet-help"
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      onKeyDown={onKey}
      data-testid="sheet-viewport"
    >
      <span id="sheet-help" className="sr-only">
        {HELP}
      </span>
      {props.children(`${vb.x} ${vb.y} ${vb.w} ${vb.h}`)}
      {props.status ? (
        <span className="sheet-status" role="status">
          {props.status}
        </span>
      ) : null}
      {zoomButtons(zoom, () => setVb(() => fitBox(t)))}
    </div>
  );
}

function zoomButtons(zoom: (f: number) => void, fit: () => void) {
  return (
    <div style={{ position: 'absolute', left: 8, bottom: 8, display: 'flex', gap: 4 }} onPointerDown={(e) => e.stopPropagation()}>
      <Button size="small" onClick={() => zoom(1 / 1.25)} aria-label="Zoom in">
        +
      </Button>
      <Button size="small" onClick={() => zoom(1.25)} aria-label="Zoom out">
        −
      </Button>
      <Button size="small" onClick={fit} data-testid="sheet-fit">
        Fit sheet
      </Button>
    </div>
  );
}

export function DrawingsTab() {
  const { item, layout } = useShownLayout();
  const bom = useBom(layout);
  const [template, setTemplate] = useState<TemplateId>(readTemplate);
  const [hidden, setHidden] = useState(false);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const selected = useApp((s) => s.view.selectedPartId);
  const select = useApp((s) => s.select);
  const study = useApp((s) => s.solver.studies['bracket_design']);
  const run = study?.partial as { status?: string; layout_id?: string } | undefined;
  const designedAt = run?.status === 'DONE' && layout && run.layout_id === layout.id ? study!.at : null;
  const badge = item ? (item.kind === 'INFEASIBLE' ? 'LEAST-VIOLATING CANDIDATE' : badgeText(item.kind)) : '';
  const set = useDrawingSet({ layout, bom: bom.data, template, hidden, index, badge, designedAt });
  const sheets = set.model?.sheets ?? [];
  const t = TEMPLATES[template];
  const [vb, setVbState] = useState<ViewBox>(() => fitBox(t));
  const setVb = useCallback((f: (v: ViewBox) => ViewBox) => setVbState(f), []);
  const svgRef = useRef<SVGSVGElement>(null);
  useEffect(() => setVbState(fitBox(TEMPLATES[template])), [template]);
  useEffect(() => {
    if (sheets.length && index >= sheets.length) setIndex(0);
  }, [sheets.length, index]);
  const names = useMemo(() => Object.fromEntries((bom.data?.items ?? []).map((r) => [r.item_no, r.name])), [bom.data]);
  const want = sheets[Math.min(index, Math.max(0, sheets.length - 1))];
  const d = set.data;
  const stale = !!d && (!want || d.key !== want.key || d.template.id !== template);
  const sheetLabel = (i: number) => {
    const s = sheets[i];
    if (!s) return '';
    return s.kind === 'assembly' ? `${i + 1} — Assembly, layout ${layout?.id}` : `${i + 1} — Detail: ${s.row?.name} (item ${s.row?.item_no})`;
  };
  const exportSvg = () => {
    if (!svgRef.current || !d) return;
    downloadSvg(exportableSvg(svgRef.current, d.template), `${d.title.drawingNo}_sheet${d.index + 1}.svg`);
  };
  const printCurrent = () => {
    if (!svgRef.current || !d) return;
    printSheets([exportableSvg(svgRef.current, d.template)], d.template);
  };
  const printAll = async () => {
    if (!sheets.length) return;
    setMsg(null);
    setBusy(`Preparing ${sheets.length} sheet${sheets.length > 1 ? 's' : ''}…`);
    try {
      const all: string[] = [];
      for (let i = 0; i < sheets.length; i++) {
        const s = d && d.key === sheets[i].key && !stale ? d : await set.build(i);
        if (s) all.push(sheetMarkup(s));
      }
      setBusy(null);
      printSheets(all, t);
    } catch (e) {
      setBusy(null);
      setMsg(`Could not prepare the sheets: ${(e as Error).message}`);
    }
  };
  if (!layout) {
    return (
      <div className="tab-scroll" data-testid="tab-drawings">
        <EmptyState title="No validated layout yet">Run the optimiser: the drawings show the layout the Overview shows.</EmptyState>
      </div>
    );
  }
  const status = busy ?? (set.pending || stale ? 'Rendering the views…' : null);
  return (
    <div className="tab-scroll drawings-tab" data-testid="tab-drawings">
      <div className="drawing-toolbar" role="toolbar" aria-label="Drawing options">
        <label>
          Sheet
          <select value={Math.min(index, Math.max(0, sheets.length - 1))} onChange={(e) => setIndex(Number(e.target.value))} aria-label="Sheet" data-testid="sheet-select">
            {sheets.map((s, i) => (
              <option key={s.key} value={i}>
                {sheetLabel(i)}
              </option>
            ))}
          </select>
        </label>
        <Button size="small" onClick={() => setIndex((i) => Math.max(0, i - 1))} disabled={index <= 0} aria-label="Previous sheet">
          ‹
        </Button>
        <Button size="small" onClick={() => setIndex((i) => Math.min(sheets.length - 1, i + 1))} disabled={index >= sheets.length - 1} aria-label="Next sheet">
          ›
        </Button>
        <label>
          Template
          <select
            value={template}
            onChange={(e) => {
              const v = e.target.value as TemplateId;
              setTemplate(v);
              saveTemplate(v);
            }}
            aria-label="Sheet template"
            data-testid="template-select"
          >
            <option value="iso-a3">{TEMPLATES['iso-a3'].label}</option>
            <option value="ansi-b">{TEMPLATES['ansi-b'].label}</option>
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={hidden} onChange={(e) => setHidden(e.target.checked)} data-testid="hidden-lines" />
          Hidden lines
        </label>
        <span style={{ flex: 1 }} />
        <MockTag what="drawing of the MOCK placeholder layout" />
        <Button size="small" onClick={exportSvg} disabled={!d || stale} data-testid="export-svg">
          Export SVG
        </Button>
        <Button size="small" onClick={printCurrent} disabled={!d || stale} title="Print this sheet; choose “Save as PDF” in the dialog. Print at 100 % for true scale." data-testid="print-sheet">
          Print / Save as PDF
        </Button>
        <Button size="small" onClick={printAll} disabled={!sheets.length || !!busy} title="Every sheet of the set, one per page">
          Print all sheets
        </Button>
      </div>
      {bom.error && !bom.data ? <Notice tone="warn">The bill of materials could not be loaded ({bom.error}): the drawing has no parts list or balloons.</Notice> : null}
      {set.error ? <Notice tone="err">{set.error}</Notice> : null}
      {msg ? <Notice tone="err">{msg}</Notice> : null}
      <SheetViewport t={t} vb={vb} setVb={setVb} stale={stale} status={status}>
        {(viewBox) =>
          d ? (
            <DrawingSheet data={d} viewBox={viewBox} svgRef={svgRef} selectedPartId={selected} onSelectPart={(id: string | null) => select(id)} names={names} />
          ) : (
            <SheetPlaceholder t={t} text="Rendering the views…" />
          )
        }
      </SheetViewport>
      <ul className="small muted" style={{ margin: '2px 0 0 16px', padding: 0 }}>
        <li>
          Views rendered from the same meshes as the 3D view (white faces, feature and silhouette edges{hidden ? ', hidden edges dashed' : ''}); outlines, dimensions, centre lines and
          balloons are vectors from the same projection. Balloon numbers are the bill of materials’ item numbers; each item is ballooned once, in the view where most of it shows.
        </li>
        <li>
          {sheets.length > 1 ? `${sheets.length - 1} detail sheet(s), one per designed bracket.` : 'Detail sheets appear once brackets are designed (Mounting Hardware tab).'} The drawings
          follow the design: a new best layout, designed brackets and part edits redraw them.
        </li>
        <li>For true scale print at 100 % (no “fit to page”) on {t.size === 'A3' ? 'A3' : 'ANSI B (11 × 17 in)'} paper. Templates: {TEMPLATES['iso-a3'].label}; {TEMPLATES['ansi-b'].label} (zones and margins as in common CAD templates, ASSUMED).</li>
      </ul>
    </div>
  );
}
