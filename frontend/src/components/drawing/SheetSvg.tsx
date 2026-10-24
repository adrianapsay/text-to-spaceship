// V2 WS6 engineering drawings: one sheet as SVG in sheet millimetres (viewBox 0 0 width height): the template (trimmed
// edge, frame, grid reference, centring marks, revision block, parts list, title block with the projection symbol)
// and the drawing (rendered views as images; outlines, centre lines, dimensions and balloons as vectors). Black on
// white paper in every theme, like a CAD sheet; balloons and parts-list rows select their part in the 3D views.

import type { KeyboardEvent, ReactNode, Ref } from 'react';
import { scaleLabel, type P2 } from './projection';
import {
  centringMarks,
  fitText,
  frameRect,
  LINE,
  PL_COLS,
  PL_HEAD,
  projectionSymbol,
  REV_COLS,
  REV_ROW,
  titleBlock,
  zones,
  ZONE_STRIP,
  type SheetTemplate,
  type TitleValues,
} from './sheet';
import type { SheetData } from './sheetData';

export const SHEET_CSS = `
.t2s-sheet text { font-family: Arial, Helvetica, sans-serif; fill: #000; }
.t2s-sheet .frame { stroke: #000; stroke-width: ${LINE.frame}; fill: none; }
.t2s-sheet .wide { stroke: #000; stroke-width: ${LINE.wide}; fill: none; }
.t2s-sheet .narrow { stroke: #000; stroke-width: ${LINE.narrow}; fill: none; }
.t2s-sheet .edge { stroke: #9a9a9a; stroke-width: 0.25; fill: none; }
.t2s-sheet .phantom { stroke: #000; stroke-width: ${LINE.narrow}; fill: none; stroke-dasharray: 7 1 0.5 1 0.5 1; }
.t2s-sheet .centre { stroke: #000; stroke-width: ${LINE.narrow}; fill: none; stroke-dasharray: 8 1 1 1; }
.t2s-sheet .ink { fill: #000; stroke: none; }
.t2s-sheet .lbl { fill: #333; }
.t2s-sheet .balloon circle { fill: #fff; stroke: #000; stroke-width: ${LINE.wide}; }
.t2s-sheet .leader { stroke: #000; stroke-width: ${LINE.narrow}; fill: none; }
.t2s-sheet [role='button'] { cursor: pointer; }
.t2s-sheet [role='button']:focus { outline: none; }
.t2s-sheet .sel circle, .t2s-sheet [role='button']:focus-visible circle { stroke: #1f5fbf; stroke-width: 0.6; }
.t2s-sheet .sel text { fill: #1f5fbf; }
.t2s-sheet .sel .leader { stroke: #1f5fbf; }
.t2s-sheet .selrow { fill: #dbe6f7; }
@media print {
  .t2s-sheet .sel circle { stroke: #000; stroke-width: ${LINE.wide}; }
  .t2s-sheet .sel text { fill: #000; }
  .t2s-sheet .sel .leader { stroke: #000; }
  .t2s-sheet .selrow { fill: none; }
}
`;

const segPath = (segs: [P2, P2][]) => segs.map(([a, b]) => `M${a[0].toFixed(3)} ${a[1].toFixed(3)}L${b[0].toFixed(3)} ${b[1].toFixed(3)}`).join('');

/** Text fitted to a width: smaller first, then squeezed (SVG textLength). */
function Fit(props: { x: number; y: number; w: number; size: number; text: string; anchor?: 'start' | 'middle' | 'end'; bold?: boolean; min?: number; className?: string }) {
  const f = fitText(props.text, props.w, props.size, props.min ?? 1.4);
  return (
    <text
      x={props.x}
      y={props.y}
      fontSize={f.size}
      textAnchor={props.anchor ?? 'start'}
      fontWeight={props.bold ? 700 : undefined}
      className={props.className}
      {...(f.squeeze ? { textLength: props.w, lengthAdjust: 'spacingAndGlyphs' } : {})}
    >
      {props.text}
    </text>
  );
}

function activate(fn: () => void) {
  return (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      fn();
    }
  };
}

export function Template(props: { t: SheetTemplate }) {
  const t = props.t;
  const f = frameRect(t);
  const z = zones(t);
  const s = ZONE_STRIP;
  const ticks: [P2, P2][] = [];
  for (const c of z.cols.slice(1)) {
    ticks.push([[c.from, f.y], [c.from, f.y - s]]);
    ticks.push([[c.from, f.y + f.h], [c.from, f.y + f.h + s]]);
  }
  for (const r of z.rows.slice(1)) {
    ticks.push([[f.x, r.from], [f.x - s, r.from]]);
    ticks.push([[f.x + f.w, r.from], [f.x + f.w + s, r.from]]);
  }
  return (
    <g data-part="template">
      <rect x={0} y={0} width={t.width} height={t.height} className="edge" />
      <rect x={f.x - s} y={f.y - s} width={f.w + 2 * s} height={f.h + 2 * s} className="narrow" />
      <path d={segPath(ticks)} className="wide" />
      {z.cols.map((c) => (
        <g key={`c${c.label}`}>
          <text x={(c.from + c.to) / 2} y={f.y - s / 2 + 1.2} fontSize={3.2} textAnchor="middle">
            {c.label}
          </text>
          <text x={(c.from + c.to) / 2} y={f.y + f.h + s / 2 + 1.2} fontSize={3.2} textAnchor="middle">
            {c.label}
          </text>
        </g>
      ))}
      {z.rows.map((r) => (
        <g key={`r${r.label}`}>
          <text x={f.x - s / 2} y={(r.from + r.to) / 2 + 1.2} fontSize={3.2} textAnchor="middle">
            {r.label}
          </text>
          <text x={f.x + f.w + s / 2} y={(r.from + r.to) / 2 + 1.2} fontSize={3.2} textAnchor="middle">
            {r.label}
          </text>
        </g>
      ))}
      <path d={centringMarks(t).map(([x1, y1, x2, y2]) => `M${x1} ${y1}L${x2} ${y2}`).join('')} className="frame" />
      <rect x={f.x} y={f.y} width={f.w} height={f.h} className="frame" />
    </g>
  );
}

function ProjectionSymbolSvg(props: { t: SheetTemplate; x: number; y: number; w: number; h: number }) {
  const s = projectionSymbol(props.t.projection, props.x, props.y, props.w, props.h);
  return (
    <g data-part="projection-symbol" aria-label={props.t.projection === 'first' ? 'first-angle projection' : 'third-angle projection'}>
      <polygon points={s.cone.map((p) => p.join(',')).join(' ')} className="wide" />
      {s.circles.map((c, i) => (
        <circle key={i} cx={c.cx} cy={c.cy} r={c.r} className="wide" />
      ))}
      <path d={s.centre.map(([x1, y1, x2, y2]) => `M${x1} ${y1}L${x2} ${y2}`).join('')} className="centre" />
    </g>
  );
}

export function TitleBlockSvg(props: { t: SheetTemplate; v: TitleValues }) {
  const tb = titleBlock(props.t);
  const v = props.v;
  return (
    <g data-part="title-block">
      {tb.fields.map((f) => {
        const label = (
          <text x={f.x + 0.8} y={f.y + 2} fontSize={1.5} className="lbl">
            {f.label}
          </text>
        );
        let value: ReactNode;
        if (f.key === 'projection') value = <ProjectionSymbolSvg t={props.t} x={f.x + 1} y={f.y + 2.4} w={f.w - 2} h={f.h - 3} />;
        else if (f.key === 'title')
          value = (
            <>
              <Fit x={f.x + 1} y={f.y + 9.5} w={f.w - 2} size={4.5} text={v.title} bold min={2.5} />
              <Fit x={f.x + 1} y={f.y + 15.5} w={f.w - 2} size={2.8} text={v.subtitle} />
            </>
          );
        else value = <Fit x={f.x + 1} y={f.y + f.h - 1.6} w={f.w - 2} size={f.size} text={String(v[f.key])} bold={f.key === 'drawingNo' || f.key === 'sheet' || f.key === 'rev'} />;
        return (
          <g key={f.key} data-field={f.key}>
            <rect x={f.x} y={f.y} width={f.w} height={f.h} className="narrow" />
            {label}
            {value}
          </g>
        );
      })}
      <rect x={tb.rect.x} y={tb.rect.y} width={tb.rect.w} height={tb.rect.h} className="frame" />
    </g>
  );
}

function RevisionBlockSvg(props: { d: SheetData }) {
  const r = props.d.layout.revisions;
  let x = r.x;
  const cols = REV_COLS.map((c) => {
    const o = { ...c, x };
    x += c.w;
    return o;
  });
  return (
    <g data-part="revision-block">
      {cols.map((c) => (
        <g key={c.key}>
          <rect x={c.x} y={r.y} width={c.w} height={REV_ROW} className="narrow" />
          <text x={c.x + c.w / 2} y={r.y + 3.6} fontSize={2.2} textAnchor="middle" fontWeight={700}>
            {c.label}
          </text>
        </g>
      ))}
      {props.d.revisions.map((rv, i) => (
        <g key={rv.rev}>
          {cols.map((c) => (
            <g key={c.key}>
              <rect x={c.x} y={r.y + REV_ROW * (i + 1)} width={c.w} height={REV_ROW} className="narrow" />
              <Fit x={c.key === 'description' ? c.x + 1 : c.x + c.w / 2} y={r.y + REV_ROW * (i + 1) + 3.6} w={c.w - 2} size={2.2} text={rv[c.key]} anchor={c.key === 'description' ? 'start' : 'middle'} />
            </g>
          ))}
        </g>
      ))}
      <rect x={r.x} y={r.y} width={r.w} height={r.h} className="wide" />
    </g>
  );
}

function PartsListSvg(props: { d: SheetData; selectedPartId: string | null; onSelect?: (partId: string | null) => void }) {
  const g = props.d.layout.parts;
  const rows = props.d.parts;
  if (!g || !rows) return null;
  let x = g.rect.x;
  const cols = PL_COLS.map((c) => {
    const o = { ...c, x };
    x += c.w;
    return o;
  });
  const shown = rows.slice(0, g.shown);
  const ty = (y: number, h: number) => y + h / 2 + 0.8;
  const size = Math.min(2.2, g.rowH * 0.55);
  return (
    <g data-part="parts-list" data-testid="drawing-parts-list">
      {shown.map((r, i) => {
        const y = g.headY - g.rowH * (i + 1);
        const sel = !!props.selectedPartId && r.partId === props.selectedPartId;
        const interactive = !!props.onSelect && !!r.partId;
        return (
          <g
            key={r.item}
            data-item={r.item}
            {...(interactive
              ? { role: 'button', tabIndex: 0, 'aria-label': `Parts list item ${r.item}: ${r.name}`, onClick: () => props.onSelect!(r.partId), onKeyDown: activate(() => props.onSelect!(r.partId)) }
              : {})}
          >
            <rect x={g.rect.x} y={y} width={g.rect.w} height={g.rowH} className={sel ? 'selrow' : undefined} fill={sel ? undefined : '#fff'} />
            {cols.map((c) => {
              const text = c.key === 'item' ? String(r.item) : c.key === 'qty' ? String(r.qty) : String(r[c.key as 'name' | 'material' | 'mass' | 'source']);
              const tx = c.align === 'middle' ? c.x + c.w / 2 : c.align === 'end' ? c.x + c.w - 1 : c.x + 1;
              return (
                <g key={c.key}>
                  <rect x={c.x} y={y} width={c.w} height={g.rowH} className="narrow" />
                  <Fit x={tx} y={ty(y, g.rowH)} w={c.w - 2} size={size} text={text} anchor={c.align} min={1.2} />
                </g>
              );
            })}
          </g>
        );
      })}
      {g.overflow ? (
        <g>
          <rect x={g.rect.x} y={g.rect.y} width={g.rect.w} height={g.rowH} className="narrow" fill="#fff" />
          <Fit x={g.rect.x + 1} y={ty(g.rect.y, g.rowH)} w={g.rect.w - 2} size={size} text={`… ${g.overflow} more items: see the Bill of Materials tab or its CSV`} />
        </g>
      ) : null}
      {cols.map((c) => (
        <g key={c.key}>
          <rect x={c.x} y={g.headY} width={c.w} height={PL_HEAD} className="narrow" />
          <text x={c.x + c.w / 2} y={g.headY + 3.5} fontSize={2.2} fontWeight={700} textAnchor="middle">
            {c.label}
          </text>
        </g>
      ))}
      <rect x={g.rect.x} y={g.rect.y} width={g.rect.w} height={g.rect.h} className="wide" />
    </g>
  );
}

function NotesSvg(props: { d: SheetData }) {
  const r = props.d.layout.notes;
  const notes = props.d.notes;
  if (!r || !notes) return null;
  const size = 2.2;
  const lines: string[] = [];
  const maxW = r.w - 6;
  notes.forEach((n, i) => {
    const words = `${i + 1}. ${n}`.split(' ');
    let cur = '';
    for (const w of words) {
      const next = cur ? `${cur} ${w}` : w;
      if (next.length * size * 0.5 > maxW && cur) {
        lines.push(cur);
        cur = `   ${w}`;
      } else cur = next;
    }
    if (cur) lines.push(cur);
  });
  const lh = Math.min(3.2, (r.h - 6) / Math.max(lines.length, 1));
  return (
    <g data-part="notes">
      <rect x={r.x} y={r.y} width={r.w} height={r.h} className="wide" />
      <text x={r.x + 1.5} y={r.y + 4} fontSize={2.5} fontWeight={700}>
        NOTES
      </text>
      {lines.map((l, i) => (
        <Fit key={i} x={r.x + 1.5} y={r.y + 7.5 + i * lh} w={r.w - 3} size={Math.min(size, lh * 0.8)} text={l} min={1.2} />
      ))}
    </g>
  );
}

export interface DrawingSheetProps {
  data: SheetData;
  selectedPartId?: string | null;
  onSelectPart?: (id: string | null) => void;
  viewBox?: string;
  svgRef?: Ref<SVGSVGElement>;
  testId?: string;
  /** names for the balloons' accessible labels */
  names?: Record<number, string>;
}

export function DrawingSheet(props: DrawingSheetProps) {
  const d = props.data;
  const t = d.template;
  const sel = props.selectedPartId ?? null;
  const viewLabelY = (v: SheetData['layout']['views'][number]) => v.y + v.h + v.margins.b - 2.5;
  return (
    <svg
      ref={props.svgRef}
      xmlns="http://www.w3.org/2000/svg"
      xmlnsXlink="http://www.w3.org/1999/xlink"
      viewBox={props.viewBox ?? `0 0 ${t.width} ${t.height}`}
      preserveAspectRatio="xMidYMid meet"
      className="t2s-sheet"
      role="img"
      aria-label={`Sheet ${d.index + 1} of ${d.count}: ${d.title.docType.toLowerCase()} ${d.title.drawingNo}, ${d.title.title}`}
      data-testid={props.testId ?? 'drawing-sheet'}
      data-sheet={d.key}
    >
      <title>{`${d.title.drawingNo} — ${d.title.title} (sheet ${d.title.sheet})`}</title>
      <style>{SHEET_CSS}</style>
      <rect x={0} y={0} width={t.width} height={t.height} fill="#fff" />
      <g data-part="views">
        {d.renders.map((r) => (
          <image key={r.view} href={r.href} x={r.x} y={r.y} width={r.w} height={r.h} preserveAspectRatio="none" data-view={r.view} />
        ))}
      </g>
      <path d={segPath(d.phantom)} className="phantom" data-part="outline" />
      <path d={segPath(d.centre)} className="centre" data-part="centre-lines" />
      {d.layout.views.map((v) => (
        <text key={v.view} x={v.x + v.w / 2} y={viewLabelY(v)} fontSize={3} textAnchor="middle" data-view-label={v.view}>
          {v.label}
          {v.ownScale ? ` (SCALE ${scaleLabel(v.scale)})` : ''}
        </text>
      ))}
      <g data-part="dimensions">
        {d.dims.map((m, i) => (
          <g key={i}>
            <path d={segPath([...m.ext, m.line])} className="narrow" />
            {m.arrows.map((a, j) => (
              <polygon key={j} points={a.map((p) => p.join(',')).join(' ')} className="ink" />
            ))}
            <text x={m.text.x} y={m.text.y} fontSize={3.5} textAnchor="middle" transform={m.text.rotate ? `rotate(${m.text.rotate} ${m.text.x} ${m.text.y})` : undefined}>
              {m.text.value}
            </text>
          </g>
        ))}
      </g>
      {d.holes.length ? (
        <g data-part="holes">
          {d.holes.map((h, i) => (
            <g key={i}>
              <circle cx={h.c[0]} cy={h.c[1]} r={h.r} className="wide" />
              <path d={`M${h.c[0] - h.r - 1.5} ${h.c[1]}L${h.c[0] + h.r + 1.5} ${h.c[1]}M${h.c[0]} ${h.c[1] - h.r - 1.5}L${h.c[0]} ${h.c[1] + h.r + 1.5}`} className="centre" />
            </g>
          ))}
        </g>
      ) : null}
      <g data-part="balloons" data-testid="drawing-balloons">
        {d.balloons.map((b) => {
          const part = d.partSelection[b.itemNo] ?? null;
          const isSel = !!sel && part === sel;
          const interactive = !!props.onSelectPart && !!part;
          return (
            <g
              key={b.itemNo}
              className={`balloon${isSel ? ' sel' : ''}`}
              data-item={b.itemNo}
              {...(interactive
                ? { role: 'button', tabIndex: 0, 'aria-label': `Item ${b.itemNo}${props.names?.[b.itemNo] ? `: ${props.names[b.itemNo]}` : ''}`, onClick: () => props.onSelectPart!(part), onKeyDown: activate(() => props.onSelectPart!(part)) }
                : {})}
            >
              <line x1={b.leader[0][0]} y1={b.leader[0][1]} x2={b.leader[1][0]} y2={b.leader[1][1]} className="leader" />
              <circle cx={b.anchor[0]} cy={b.anchor[1]} r={0.5} className="ink" />
              <circle cx={b.centre[0]} cy={b.centre[1]} r={b.r} />
              <text x={b.centre[0]} y={b.centre[1] + 1.25} fontSize={3.5} textAnchor="middle">
                {b.itemNo}
              </text>
            </g>
          );
        })}
      </g>
      <Template t={t} />
      <RevisionBlockSvg d={d} />
      <PartsListSvg d={d} selectedPartId={sel} onSelect={props.onSelectPart} />
      <NotesSvg d={d} />
      <TitleBlockSvg t={t} v={d.title} />
      {d.unballooned.length || d.renderError ? (
        <Fit
          x={d.layout.main.x}
          y={d.layout.main.y + d.layout.main.h + 2.5}
          w={d.layout.main.w}
          size={2.2}
          text={d.renderError ?? `Not ballooned (hidden in these views): item${d.unballooned.length > 1 ? 's' : ''} ${d.unballooned.join(', ')}`}
          className="lbl"
        />
      ) : null}
    </svg>
  );
}

/** A sheet with only the template while its views are being rendered. */
export function SheetPlaceholder(props: { t: SheetTemplate; text: string }) {
  const t = props.t;
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox={`0 0 ${t.width} ${t.height}`} preserveAspectRatio="xMidYMid meet" className="t2s-sheet" role="img" aria-label={props.text} data-testid="drawing-placeholder">
      <style>{SHEET_CSS}</style>
      <rect x={0} y={0} width={t.width} height={t.height} fill="#fff" />
      <Template t={t} />
      <text x={t.width / 2} y={t.height / 2} fontSize={6} textAnchor="middle" className="lbl">
        {props.text}
      </text>
    </svg>
  );
}
